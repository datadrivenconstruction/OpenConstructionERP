"""A quantity-map Apply must accept exactly the preview a person reviewed."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.bim_hub.models import BIMElement, BIMModel, BIMQuantityMap, BOQElementLink
from app.modules.bim_hub.schemas import QuantityMapApplyRequest
from app.modules.bim_hub.service import BIMHubService
from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as value:
        yield value


async def seed(session):
    owner = User(email=f"preview-{uuid.uuid4().hex}@test.io", hashed_password="x", full_name="Preview")
    session.add(owner)
    await session.flush()
    project = Project(name="Preview", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    model = BIMModel(project_id=project.id, name="Walls", version="1", status="ready")
    boq = BOQ(project_id=project.id, name="Bill", is_locked=False)
    session.add_all([model, boq])
    await session.flush()
    element = BIMElement(model_id=model.id, stable_id="wall-1", element_type="Wall", quantities={"area": 12})
    rule = BIMQuantityMap(
        project_id=project.id,
        name="Walls",
        element_type_filter="Wall",
        quantity_source="area",
        unit="m2",
        boq_target={"auto_create": True, "unit_rate": "10"},
        is_active=True,
    )
    session.add_all([element, rule])
    await session.flush()
    return model, boq, element, rule


def request(model, boq, *, token=None, dry=True):
    return QuantityMapApplyRequest.model_validate(
        {
            "model_id": str(model.id),
            "target_boq_id": str(boq.id),
            "dry_run": dry,
            "preview_fingerprint": token,
        }
    )


async def counts(session):
    return tuple(
        [
            (await session.execute(select(func.count()).select_from(kind))).scalar_one()
            for kind in (Position, BOQElementLink)
        ]
    )


@pytest.mark.asyncio
async def test_apply_without_preview_is_refused_and_writes_nothing(session):
    model, boq, _, _ = await seed(session)
    with pytest.raises(HTTPException) as exc:
        await BIMHubService(session).apply_quantity_maps(request(model, boq, dry=False))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "quantity_preview_required"
    assert await counts(session) == (0, 0)


@pytest.mark.asyncio
async def test_preview_is_read_only_and_repeat_apply_creates_no_duplicate(session):
    model, boq, _, _ = await seed(session)
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    assert preview.preview_fingerprint
    assert (preview.links_to_create, preview.positions_to_create) == (1, 1)
    assert await counts(session) == (0, 0)
    assert model.metadata_ == {}
    applied = await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    assert (applied.links_created, applied.positions_created) == (1, 1)
    repeated = await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    assert repeated.replayed is True
    assert (repeated.links_created, repeated.positions_created) == (0, 0)
    refreshed = await service.apply_quantity_maps(request(model, boq))
    assert (refreshed.links_to_create, refreshed.positions_to_create) == (0, 0)
    await service.apply_quantity_maps(request(model, boq, token=refreshed.preview_fingerprint, dry=False))
    assert await counts(session) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["model", "element", "rule", "boq"])
async def test_changed_inputs_refuse_the_old_preview(session, change):
    model, boq, element, rule = await seed(session)
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    if change == "model":
        model.version = "2"
    elif change == "element":
        element.quantities = {"area": 13}
    elif change == "rule":
        rule.multiplier = "2"
    else:
        boq.name = "A revised bill"
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "quantity_preview_stale"
    assert await counts(session) == (0, 0)


@pytest.mark.asyncio
async def test_rule_failure_rolls_back_the_whole_apply(session, monkeypatch):
    model, boq, _, rule = await seed(session)
    second = BIMQuantityMap(
        project_id=model.project_id,
        name="Second",
        element_type_filter="Wall",
        quantity_source="area",
        unit="m2",
        boq_target={"auto_create": True},
        is_active=True,
    )
    session.add(second)
    await session.flush()
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    original = service._persist_rule_matches
    calls = 0

    async def fails_after_first(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure")
        return await original(**kwargs)

    monkeypatch.setattr(service, "_persist_rule_matches", fails_after_first)
    with pytest.raises(RuntimeError, match="injected failure"):
        await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    assert calls == 2
    assert await counts(session) == (0, 0)


@pytest.mark.asyncio
async def test_sidecar_content_not_just_db_rows_binds_preview(session, tmp_path, monkeypatch):
    from app.modules.bim_hub.dataframe_store import write_dataframe

    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    model, boq, element, rule = await seed(session)
    rule.property_filter = {"Phase": "new"}
    rule.quantity_source = "property:Height"
    element.properties = {}
    element.mesh_ref = "wall-1"
    await session.flush()
    args = (str(model.project_id), str(model.id))
    write_dataframe(*args, [{"id": "wall-1", "phase": "new", "height": 2}], data_root=tmp_path / "bim")
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    assert preview.results[0]["adjusted_quantity"] == 2
    # Same matches and total, but different actual sidecar input: timestamps
    # and outcome-only hashes would miss the review becoming stale.
    write_dataframe(*args, [{"id": "wall-1", "phase": "NEW", "height": 2}], data_root=tmp_path / "bim")
    with pytest.raises(HTTPException) as exc:
        await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    assert exc.value.detail["code"] == "quantity_preview_stale"
    assert await counts(session) == (0, 0)


@pytest.mark.asyncio
async def test_existing_position_only_gets_links_and_money_stays_unchanged(session):
    model, boq, _, rule = await seed(session)
    position = Position(
        boq_id=boq.id,
        ordinal="1",
        description="Measured manually",
        unit="m2",
        quantity="47",
        unit_rate="20",
        total="940",
    )
    session.add(position)
    await session.flush()
    rule.boq_target = {"position_id": str(position.id)}
    await session.flush()
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    assert (preview.links_to_create, preview.positions_to_create) == (1, 0)
    before = (position.quantity, position.unit_rate, position.total, position.version)
    await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    await session.refresh(position)
    assert (position.quantity, position.unit_rate, position.total, position.version) == before
    assert await counts(session) == (1, 1)


@pytest.mark.asyncio
async def test_changed_position_rate_refuses_preview(session):
    model, boq, _, rule = await seed(session)
    position = Position(boq_id=boq.id, ordinal="1", description="Target", unit="m2", quantity="47", unit_rate="20")
    session.add(position)
    await session.flush()
    rule.boq_target = {"position_id": str(position.id)}
    await session.flush()
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    position.unit_rate = "30"
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    assert exc.value.detail["code"] == "quantity_preview_stale"
    assert await counts(session) == (1, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("already_applied", [False, True])
async def test_locked_bill_is_checked_before_write_or_receipt_replay(session, already_applied):
    model, boq, _, _ = await seed(session)
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    payload = request(model, boq, token=preview.preview_fingerprint, dry=False)
    if already_applied:
        await service.apply_quantity_maps(payload)
    boq.is_locked = True
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await service.apply_quantity_maps(payload)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "boq_locked"
    assert await counts(session) == ((1, 1) if already_applied else (0, 0))


@pytest.mark.asyncio
async def test_token_cannot_be_rebound_to_another_model_or_bill(session):
    model, boq, _, _ = await seed(session)
    service = BIMHubService(session)
    preview = await service.apply_quantity_maps(request(model, boq))
    other_model = BIMModel(project_id=model.project_id, name="Other", status="ready")
    other_boq = BOQ(project_id=model.project_id, name="Other bill")
    session.add_all([other_model, other_boq])
    await session.flush()
    for chosen_model, chosen_boq in ((other_model, boq), (model, other_boq)):
        with pytest.raises(HTTPException) as exc:
            await service.apply_quantity_maps(
                request(chosen_model, chosen_boq, token=preview.preview_fingerprint, dry=False)
            )
        assert exc.value.detail["code"] == "quantity_preview_stale"
    assert await counts(session) == (0, 0)


@pytest.mark.asyncio
async def test_http_permission_and_project_checks_precede_receipt_replay(session):
    from app.dependencies import get_current_user_payload
    from app.modules.bim_hub.router import _get_service, router

    model, boq, _, _ = await seed(session)
    project = await session.get(Project, model.project_id)
    identity = {"sub": str(project.owner_id), "role": "q12-test", "permissions": ["bim.create"]}
    app = FastAPI()
    app.include_router(router, prefix="/bim")
    app.dependency_overrides[get_current_user_payload] = lambda: identity
    app.dependency_overrides[_get_service] = lambda: BIMHubService(session)
    url = "/bim/quantity-maps/apply/"
    body = {"model_id": str(model.id), "target_boq_id": str(boq.id), "dry_run": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://preview.test") as client:
        response = await client.post(url, json=body)
        assert response.status_code == 200, response.text
        body.update(dry_run=False, preview_fingerprint=response.json()["preview_fingerprint"])
        assert (await client.post(url, json=body)).status_code == 200
        identity["permissions"] = []
        assert (await client.post(url, json=body)).status_code == 403
        identity.update(permissions=["bim.create"], sub=str(uuid.uuid4()))
        assert (await client.post(url, json=body)).status_code == 404
    assert await counts(session) == (1, 1)


@pytest.mark.asyncio
async def test_metadata_api_cannot_forge_or_erase_apply_receipts(session):
    from app.modules.bim_hub.quantity_previews import RECEIPTS_KEY
    from app.modules.bim_hub.schemas import BIMModelCreate, BIMModelUpdate

    model, boq, _, _ = await seed(session)
    service = BIMHubService(session)
    created = await service.create_model(
        BIMModelCreate(project_id=model.project_id, name="Untrusted", metadata={RECEIPTS_KEY: [{"token": "forged"}]})
    )
    assert RECEIPTS_KEY not in created.metadata_
    preview = await service.apply_quantity_maps(request(model, boq))
    await service.apply_quantity_maps(request(model, boq, token=preview.preview_fingerprint, dry=False))
    receipts = model.metadata_[RECEIPTS_KEY]
    await service.update_model(model.id, BIMModelUpdate(metadata={RECEIPTS_KEY: []}))
    assert model.metadata_[RECEIPTS_KEY] == receipts
    await service.update_model(model.id, BIMModelUpdate(metadata=None))
    assert model.metadata_[RECEIPTS_KEY] == receipts


@pytest.mark.asyncio
async def test_concurrent_apply_is_one_write_and_one_replay():
    from tests._pg import isolated_engine

    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as setup:
            model, boq, _, _ = await seed(setup)
            preview = await BIMHubService(setup).apply_quantity_maps(request(model, boq))
            payload = request(model, boq, token=preview.preview_fingerprint, dry=False)
            await setup.commit()
        reached, release = asyncio.Event(), asyncio.Event()

        class PausedApply(BIMHubService):
            async def _persist_rule_matches(self, **kwargs):
                reached.set()
                await release.wait()
                return await super()._persist_rule_matches(**kwargs)

        async def run(session, kind):
            result = await kind(session).apply_quantity_maps(payload)
            await session.commit()
            return result

        async with factory() as first, factory() as second, factory() as observer:
            task_a = asyncio.create_task(run(first, PausedApply))
            await asyncio.wait_for(reached.wait(), timeout=10)
            task_b = asyncio.create_task(run(second, BIMHubService))
            try:

                async def waiting():
                    while not task_b.done():
                        count = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted "
                                "AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"
                            )
                        )
                        if count:
                            return count
                        await asyncio.sleep(0.01)
                    return 0

                assert await asyncio.wait_for(waiting(), timeout=10) == 1
            finally:
                release.set()
                outcomes = await asyncio.gather(task_a, task_b, return_exceptions=True)
            assert all(not isinstance(value, BaseException) for value in outcomes), outcomes
            assert [(value.positions_created, value.replayed) for value in outcomes] == [(1, False), (0, True)]
            assert await counts(observer) == (1, 1)
