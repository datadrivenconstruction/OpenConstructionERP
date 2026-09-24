# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service-level tests for the no_match(custom) -> real BOQ line flow.

These cover the deepening that replaced the old stub in
``MatchElementsService.no_match`` for ``action="custom"``. The stub used to
park the group as ``tbd`` with a note and silently drop the estimator's
typed description / unit / rate - the line never reached the BOQ. Now:

  * no_match(custom) marks the group ``confirmed`` with method ``custom``
    and persists the spec in ``metadata_["custom_position"]``.
  * apply_to_boq writes a real Position priced at the user's rate.
  * save_to_my_catalogue=True additionally persists a reusable CostItem
    (source="custom") and links the group to it.

Run:
    cd backend
    python -m pytest tests/modules/match_elements/test_custom_position.py -q
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

# Eager-import the model namespaces the suite touches so create_all sees a
# coherent table set (mirrors test_groups_split_merge_rfq.py).
import app.modules.bim_hub.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.match_elements.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.rfq_bidding.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401
from app.modules.match_elements import schemas  # noqa: E402
from app.modules.match_elements.service import get_service  # noqa: E402


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _create_schema():
    """Create all tables on the conftest-provisioned PostgreSQL database."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


async def _seed_project_with_bim(region: str = "DE", currency: str = "EUR") -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a Project + BIMModel + 3 walls. Returns (project, model)."""
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            User(
                id=owner_id,
                email=f"owner-{owner_id.hex[:8]}@me-custom.test",
                hashed_password="x",
                full_name="ME Custom Owner",
                role="admin",
                is_active=True,
            )
        )
        await s.flush()
        s.add(
            Project(
                id=project_id,
                name=f"ME-Custom-{uuid.uuid4().hex[:6]}",
                description="custom position test",
                owner_id=owner_id,
                currency=currency,
                region=region,
                classification_standard="din276",
                metadata_={},
                fx_rates=[],
            )
        )
        s.add(
            BIMModel(
                id=model_id,
                project_id=project_id,
                name="test.ifc",
                model_format="ifc",
                version="1",
                status="completed",
                element_count=3,
                storey_count=1,
                metadata_={},
            )
        )
        for i in range(3):
            s.add(
                BIMElement(
                    id=uuid.uuid4(),
                    model_id=model_id,
                    stable_id=f"wall-{i:03d}",
                    element_type="IfcWallStandardCase",
                    name=f"Wall_{i}",
                    storey="Level 01",
                    discipline="ARCH",
                    properties={"type_name": "Bespoke Wall 999mm", "material": "Rammed Earth"},
                    quantities={"volume_m3": 10.0, "area_m2": 40.0, "count": 1.0},
                    metadata_={},
                    asset_info={},
                    is_tracked_asset=False,
                )
            )
        await s.commit()
    return project_id, model_id


async def _new_session_with_groups(project_id: uuid.UUID, model_id: uuid.UUID):
    from app.database import async_session_factory

    svc = get_service()
    async with async_session_factory() as s:
        created = await svc.create_session(
            s,
            schemas.SessionCreate(project_id=project_id, bim_model_id=model_id, source="bim"),
        )
        await s.commit()
        session_id = created.id
    async with async_session_factory() as s:
        await svc.rebuild_groups(s, session_id)
        await s.commit()
    return session_id


def _wall_group_key(groups) -> str:
    for g in groups.groups:
        if "IfcWall" in g.group_key:
            return g.group_key
    raise AssertionError("no wall group found")


# ── no_match(custom) confirms the group with the typed spec ────────────────


@pytest.mark.asyncio
async def test_custom_no_match_confirms_group_and_persists_spec():
    from app.database import async_session_factory

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim()
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall_key = _wall_group_key(groups)

    async with async_session_factory() as s:
        detail = await svc.no_match(
            s,
            session_id,
            schemas.NoMatchRequest(
                group_key=wall_key,
                action="custom",
                custom_description="Rammed earth wall, hand-finished",
                custom_unit="m3",
                custom_rate=Decimal("145.50"),
            ),
        )
        await s.commit()

    # The group is now confirmed (not tbd) so apply will pick it up, and the
    # method records that this was a custom estimator decision.
    assert detail.status == "confirmed"
    assert detail.chosen_method == "custom"
    assert detail.chosen_unit == "m3"
    assert detail.notes is not None
    assert "Rammed earth wall" in detail.notes
    assert "pending" not in detail.notes.lower()


# ── apply_to_boq writes the custom line with the user's rate ───────────────


@pytest.mark.asyncio
async def test_custom_position_applies_to_boq_with_user_rate():
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim()
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall_key = _wall_group_key(groups)

    async with async_session_factory() as s:
        await svc.no_match(
            s,
            session_id,
            schemas.NoMatchRequest(
                group_key=wall_key,
                action="custom",
                custom_description="Rammed earth wall",
                custom_unit="m3",
                custom_rate=Decimal("145.50"),
            ),
        )
        await s.commit()

    # Dry run first - the line shows in the preview with the user's rate.
    async with async_session_factory() as s:
        preview = await svc.apply_to_boq(
            s,
            session_id,
            schemas.ApplyToBoqRequest(dry_run=True),
            applied_by=None,
        )
    assert preview.dry_run is True
    assert preview.positions_created == 1
    line = preview.positions[0]
    assert line.description == "Rammed earth wall"
    assert line.unit == "m3"
    assert line.unit_rate == Decimal("145.50")
    # 3 walls × 10 m3 each = 30 m3 → 30 × 145.50 = 4365.00
    assert line.quantity == pytest.approx(30.0)
    assert preview.grand_total == Decimal("4365.00")

    # Real write - the Position lands in the BOQ with the custom rate.
    async with async_session_factory() as s:
        written = await svc.apply_to_boq(
            s,
            session_id,
            schemas.ApplyToBoqRequest(dry_run=False),
            applied_by=None,
        )
        await s.commit()
    assert written.dry_run is False
    assert written.positions_created == 1
    assert written.boq_id is not None

    async with async_session_factory() as s:
        rows = (await s.execute(select(Position).where(Position.boq_id == written.boq_id))).scalars().all()
    assert len(rows) == 1
    pos = rows[0]
    assert pos.description == "Rammed earth wall"
    assert pos.unit == "m3"
    assert Decimal(pos.unit_rate) == Decimal("145.5000")
    assert Decimal(pos.total) == Decimal("4365.0000")
    assert pos.metadata_.get("custom_position") is True
    # The custom line links back to the BIM elements it priced.
    assert len(pos.cad_element_ids) == 3

    # Group is now applied and linked to the Position.
    async with async_session_factory() as s:
        detail = await svc.get_group_detail(s, session_id, wall_key)
    assert detail.status == "applied"
    assert detail.boq_position_id == pos.id


# ── save_to_my_catalogue persists a reusable CostItem ──────────────────────


@pytest.mark.asyncio
async def test_custom_position_saves_reusable_cost_item():
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    svc = get_service()
    # ``source == "custom"`` is not a property of this test alone: other tests
    # in the same database save custom rates too, and a full single-process run
    # found three. The rows under test are the ones carrying this description,
    # made unique per run so a database the test already ran against does not
    # hand back the previous run's row either.
    description = f"Reusable bespoke rate {uuid.uuid4().hex[:8]}"
    ours = (CostItem.source == "custom") & (CostItem.description == description)

    project_id, model_id = await _seed_project_with_bim(region="DE", currency="EUR")
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall_key = _wall_group_key(groups)

    async with async_session_factory() as s:
        detail = await svc.no_match(
            s,
            session_id,
            schemas.NoMatchRequest(
                group_key=wall_key,
                action="custom",
                custom_description=description,
                custom_unit="m3",
                custom_rate=Decimal("200.00"),
                save_to_my_catalogue=True,
            ),
        )
        await s.commit()

    # The group is linked to a real catalogue row.
    assert detail.chosen_candidate_id is not None

    async with async_session_factory() as s:
        items = (await s.execute(select(CostItem).where(ours))).scalars().all()
    assert len(items) == 1
    item = items[0]
    assert item.description == description
    assert item.unit == "m3"
    assert Decimal(item.rate) == Decimal("200.00")
    assert item.currency == "EUR"
    assert item.region == "DE"
    assert "custom" in item.tags
    assert detail.chosen_candidate_id == item.id

    # Re-saving the same description in the same region updates the rate
    # rather than creating a duplicate (upsert by code+region).
    async with async_session_factory() as s2:
        groups2 = await svc.list_groups(s2, session_id)
    # Pick any group (re-seed a fresh session to avoid the applied/confirmed
    # state interfering) - simplest: hit the same description again here by
    # calling the private saver directly through a second no_match on a new
    # session sharing the region.
    project_id2, model_id2 = await _seed_project_with_bim(region="DE", currency="EUR")
    session_id2 = await _new_session_with_groups(project_id2, model_id2)
    async with async_session_factory() as s:
        g2 = _wall_group_key(await svc.list_groups(s, session_id2))
    async with async_session_factory() as s:
        await svc.no_match(
            s,
            session_id2,
            schemas.NoMatchRequest(
                group_key=g2,
                action="custom",
                custom_description=description,
                custom_unit="m3",
                custom_rate=Decimal("210.00"),
                save_to_my_catalogue=True,
            ),
        )
        await s.commit()
    async with async_session_factory() as s:
        items_after = (await s.execute(select(CostItem).where(ours))).scalars().all()
    # Still exactly one row for this description+region; rate refreshed.
    assert len(items_after) == 1
    assert Decimal(items_after[0].rate) == Decimal("210.00")


# ── tbd / regression: tbd still parks without writing a line ───────────────


@pytest.mark.asyncio
async def test_tbd_no_match_does_not_apply():
    from app.database import async_session_factory

    svc = get_service()
    project_id, model_id = await _seed_project_with_bim()
    session_id = await _new_session_with_groups(project_id, model_id)

    async with async_session_factory() as s:
        groups = await svc.list_groups(s, session_id)
    wall_key = _wall_group_key(groups)

    async with async_session_factory() as s:
        detail = await svc.no_match(s, session_id, schemas.NoMatchRequest(group_key=wall_key, action="tbd"))
        await s.commit()
    assert detail.status == "tbd"

    # apply finds no confirmed group → nothing written.
    async with async_session_factory() as s:
        preview = await svc.apply_to_boq(s, session_id, schemas.ApplyToBoqRequest(dry_run=True), applied_by=None)
    assert preview.positions_created == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
