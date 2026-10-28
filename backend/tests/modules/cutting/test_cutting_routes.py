# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The cutting API end to end against the real ASGI app and database.

Covers the whole loop an estimator walks: create a job, import a cut list,
optimise, export the cutting list, review the proposal, confirm it into the BOQ
line and the requisition, and book offcuts in site inventory. Also the access
rules: a foreign project is a 404, a missing permission a 403.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_PREFIX = "/api/v1/cutting"
_ALL = ["cutting.read", "cutting.write", "cutting.apply"]


@pytest_asyncio.fixture(scope="module")
async def app_factory():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        yield session


async def _seed_user_and_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"cutting-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Cutting Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Cutting Project", owner_id=user.id)
    session.add(project)
    await session.commit()
    return user.id, project.id


async def _seed_boq_line(session, project_id: uuid.UUID, *, unit: str = "m", quantity: str = "48.5") -> uuid.UUID:
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="Structure")
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id, ordinal="01.001", description="Rebar 16 mm", unit=unit, quantity=quantity, unit_rate="2.5"
    )
    session.add(position)
    await session.commit()
    return position.id


async def _seed_req_item(session, project_id: uuid.UUID, *, status: str = "draft") -> uuid.UUID:
    from app.modules.procurement.models import MaterialRequisition, MaterialRequisitionItem

    req = MaterialRequisition(project_id=project_id, status=status, req_number=f"MR-{uuid.uuid4().hex[:4]}")
    session.add(req)
    await session.flush()
    item = MaterialRequisitionItem(
        requisition_id=req.id, description="Rebar 16 mm bars", unit="pcs", quantity_requested="10"
    )
    session.add(item)
    await session.commit()
    return item.id


def _auth(app, user_id: uuid.UUID, perms: list[str], role: str = "editor") -> None:
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict:
        return {"sub": str(user_id), "role": role, "permissions": list(perms)}

    app.dependency_overrides[get_current_user_payload] = _payload


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _job_body(project_id: uuid.UUID, **extra) -> dict:
    body = {
        "project_id": str(project_id),
        "name": "Rebar 16",
        "kind": "linear",
        "material": "B500 16",
        "kerf_mm": "3",
        "min_offcut_mm": "500",
        "currency": "EUR",
        "pieces": [
            {"ref": "A", "length_mm": "4000", "quantity": 5},
            {"ref": "B", "length_mm": "3000", "quantity": 7},
            {"ref": "C", "length_mm": "2500", "quantity": 3},
        ],
        "stocks": [
            {"ref": "12m", "length_mm": "12000", "unit_cost": "60"},
            {"ref": "6m", "length_mm": "6000", "unit_cost": "32"},
        ],
    }
    body.update(extra)
    return body


async def test_the_router_is_mounted(app_factory) -> None:
    paths = app_factory.openapi()["paths"]
    assert f"{_PREFIX}/jobs/" in paths
    assert f"{_PREFIX}/jobs/{{job_id}}/optimise" in paths
    assert f"{_PREFIX}/plans/{{plan_id}}/apply" in paths


async def test_the_full_loop_from_cut_list_to_boq_and_inventory(app_factory, db_session) -> None:
    user_id, project_id = await _seed_user_and_project(db_session)
    position_id = await _seed_boq_line(db_session, project_id)
    req_item_id = await _seed_req_item(db_session, project_id)
    _auth(app_factory, user_id, _ALL)
    try:
        async with _client(app_factory) as client:
            body = _job_body(project_id, boq_position_id=str(position_id), procurement_req_item_id=str(req_item_id))
            created = await client.post(f"{_PREFIX}/jobs/", json=body)
            assert created.status_code == 201, created.text
            job = created.json()
            assert len(job["pieces"]) == 3 and job["kerf_mm"] == "3.00"

            validated = await client.get(f"{_PREFIX}/jobs/{job['id']}/validate")
            assert validated.status_code == 200, validated.text
            assert validated.json()["errors"] == 0

            optimised = await client.post(f"{_PREFIX}/jobs/{job['id']}/optimise")
            assert optimised.status_code == 201, optimised.text
            plan = optimised.json()
            assert plan["pieces_unplaced"] == 0
            assert plan["pieces_placed"] == 15
            assert Decimal(plan["yield_pct"]) > 80
            assert Decimal(plan["cost"]) > 0
            assert plan["layout"]["bars"]

            listed = await client.get(f"{_PREFIX}/jobs/", params={"project_id": str(project_id)})
            assert listed.status_code == 200
            assert listed.json()["items"][0]["latest_plan_id"] == plan["id"]

            for fmt, magic in (("pdf", b"%PDF"), ("xlsx", b"PK")):
                exported = await client.get(f"{_PREFIX}/plans/{plan['id']}/export", params={"format": fmt})
                assert exported.status_code == 200, exported.text
                assert exported.content.startswith(magic)

            proposal = await client.get(f"{_PREFIX}/plans/{plan['id']}/proposal")
            assert proposal.status_code == 200, proposal.text
            lines = {line["target"]: line for line in proposal.json()["lines"]}
            assert lines["boq_position"]["appliable"] is True
            assert lines["boq_position"]["basis"] == "length"
            assert lines["requisition_item"]["basis"] == "stock_count"
            assert Decimal(lines["requisition_item"]["proposed_quantity"]) == plan["stock_count"]
            assert 0 < proposal.json()["confidence"] <= 1

            applied = await client.post(f"{_PREFIX}/plans/{plan['id']}/apply", json={})
            assert applied.status_code == 200, applied.text
            assert all(r["applied"] for r in applied.json()["results"])

            returned = await client.post(f"{_PREFIX}/plans/{plan['id']}/return-offcuts", json={})
            assert returned.status_code == 200, returned.text
            again = await client.post(f"{_PREFIX}/plans/{plan['id']}/return-offcuts", json={})
            assert again.status_code == 409

            offcuts = await client.get(
                f"{_PREFIX}/inventory-offcuts/", params={"project_id": str(project_id), "material": "B500 16"}
            )
            assert offcuts.status_code == 200
            assert sum(o["on_hand"] for o in offcuts.json()["items"]) == returned.json()["returned"]
    finally:
        app_factory.dependency_overrides.clear()

    from app.modules.boq.models import Position
    from app.modules.procurement.models import MaterialRequisitionItem

    db_session.expire_all()
    position = await db_session.get(Position, position_id)
    assert Decimal(position.quantity) == Decimal(lines["boq_position"]["proposed_quantity"])
    assert position.metadata_["cutting_update"]["plan_id"] == plan["id"]
    item = await db_session.get(MaterialRequisitionItem, req_item_id)
    assert Decimal(item.quantity_requested) == plan["stock_count"]


async def test_a_submitted_requisition_is_not_rewritten(app_factory, db_session) -> None:
    user_id, project_id = await _seed_user_and_project(db_session)
    req_item_id = await _seed_req_item(db_session, project_id, status="submitted")
    _auth(app_factory, user_id, _ALL)
    try:
        async with _client(app_factory) as client:
            job = (
                await client.post(
                    f"{_PREFIX}/jobs/", json=_job_body(project_id, procurement_req_item_id=str(req_item_id))
                )
            ).json()
            plan = (await client.post(f"{_PREFIX}/jobs/{job['id']}/optimise")).json()
            applied = await client.post(f"{_PREFIX}/plans/{plan['id']}/apply", json={})
    finally:
        app_factory.dependency_overrides.clear()
    result = applied.json()["results"][0]
    assert result["applied"] is False
    assert result["reason"] == "requisition_not_draft"


async def test_imports_from_a_boq_line_and_a_csv_file(app_factory, db_session) -> None:
    user_id, project_id = await _seed_user_and_project(db_session)
    position_id = await _seed_boq_line(db_session, project_id, unit="m", quantity="25")
    _auth(app_factory, user_id, _ALL)
    try:
        async with _client(app_factory) as client:
            job = (await client.post(f"{_PREFIX}/jobs/", json=_job_body(project_id, pieces=[]))).json()
            from_boq = await client.post(
                f"{_PREFIX}/jobs/{job['id']}/import/boq",
                json={"position_id": str(position_id), "piece_length_mm": "6000"},
            )
            assert from_boq.status_code == 200, from_boq.text
            pieces = from_boq.json()["job"]["pieces"]
            assert [(p["length_mm"], p["quantity"]) for p in pieces] == [("6000.0", 4), ("1000.0", 1)]
            assert from_boq.json()["job"]["boq_position_id"] == str(position_id)

            csv = b"mark,length,qty\nX1,2000,3\nX2,1500,2\n"
            from_file = await client.post(
                f"{_PREFIX}/jobs/{job['id']}/import/file",
                files={"upload": ("cut.csv", io.BytesIO(csv), "text/csv")},
            )
            assert from_file.status_code == 200, from_file.text
            assert from_file.json()["imported"] == 2
            assert {p["ref"] for p in from_file.json()["job"]["pieces"]} == {"X1", "X2"}

            too_big = await client.post(
                f"{_PREFIX}/jobs/{job['id']}/import/file",
                files={"upload": ("cut.csv", io.BytesIO(b"x" * (8 * 1024 * 1024 + 1)), "text/csv")},
            )
            assert too_big.status_code == 413
    finally:
        app_factory.dependency_overrides.clear()


async def test_a_sheet_job_optimises_into_guillotine_layouts(app_factory, db_session) -> None:
    user_id, project_id = await _seed_user_and_project(db_session)
    _auth(app_factory, user_id, _ALL)
    body = {
        "project_id": str(project_id),
        "name": "Plywood 18",
        "kind": "sheet",
        "kerf_mm": "4",
        "min_offcut_mm": "300",
        "pieces": [
            {"ref": "D", "length_mm": "2000", "width_mm": "800", "quantity": 2, "rotatable": False},
            {"ref": "S", "length_mm": "600", "width_mm": "400", "quantity": 6},
        ],
        "stocks": [{"ref": "2500x1250", "length_mm": "2500", "width_mm": "1250", "unit_cost": "40"}],
    }
    try:
        async with _client(app_factory) as client:
            job = await client.post(f"{_PREFIX}/jobs/", json=body)
            assert job.status_code == 201, job.text
            plan = await client.post(f"{_PREFIX}/jobs/{job.json()['id']}/optimise")
    finally:
        app_factory.dependency_overrides.clear()
    assert plan.status_code == 201, plan.text
    data = plan.json()
    assert data["pieces_unplaced"] == 0
    placements = [p for s in data["layout"]["sheets"] for p in s["placements"]]
    assert len(placements) == 8
    assert not any(p["rotated"] for p in placements if p["ref"] == "D")


async def test_a_sheet_job_without_widths_is_refused(app_factory, db_session) -> None:
    user_id, project_id = await _seed_user_and_project(db_session)
    _auth(app_factory, user_id, _ALL)
    try:
        async with _client(app_factory) as client:
            response = await client.post(f"{_PREFIX}/jobs/", json=_job_body(project_id, kind="sheet"))
    finally:
        app_factory.dependency_overrides.clear()
    assert response.status_code == 422


async def test_duplicate_refs_are_refused(app_factory, db_session) -> None:
    user_id, project_id = await _seed_user_and_project(db_session)
    _auth(app_factory, user_id, _ALL)
    body = _job_body(project_id)
    body["pieces"].append({"ref": "A", "length_mm": "100"})
    try:
        async with _client(app_factory) as client:
            response = await client.post(f"{_PREFIX}/jobs/", json=body)
    finally:
        app_factory.dependency_overrides.clear()
    assert response.status_code == 422


async def test_a_foreign_project_job_is_a_404(app_factory, db_session) -> None:
    owner_id, project_id = await _seed_user_and_project(db_session)
    stranger_id, _ = await _seed_user_and_project(db_session)
    _auth(app_factory, owner_id, _ALL)
    try:
        async with _client(app_factory) as client:
            job = (await client.post(f"{_PREFIX}/jobs/", json=_job_body(project_id))).json()
        _auth(app_factory, stranger_id, _ALL)
        async with _client(app_factory) as client:
            response = await client.get(f"{_PREFIX}/jobs/{job['id']}")
            listing = await client.get(f"{_PREFIX}/jobs/", params={"project_id": str(project_id)})
    finally:
        app_factory.dependency_overrides.clear()
    assert response.status_code == 404
    assert listing.status_code == 404


async def test_a_viewer_can_read_but_not_optimise(app_factory, db_session) -> None:
    user_id, project_id = await _seed_user_and_project(db_session)
    _auth(app_factory, user_id, _ALL)
    try:
        async with _client(app_factory) as client:
            job = (await client.post(f"{_PREFIX}/jobs/", json=_job_body(project_id))).json()
        _auth(app_factory, user_id, ["cutting.read"], role="viewer")
        async with _client(app_factory) as client:
            read = await client.get(f"{_PREFIX}/jobs/{job['id']}")
            optimise = await client.post(f"{_PREFIX}/jobs/{job['id']}/optimise")
    finally:
        app_factory.dependency_overrides.clear()
    assert read.status_code == 200
    assert optimise.status_code == 403
