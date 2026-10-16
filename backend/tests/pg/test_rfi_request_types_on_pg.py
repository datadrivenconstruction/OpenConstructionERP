# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request types as data, against PostgreSQL: catalogue, numbering, required fields, routes, API, migration.

Each test gets a throwaway database cloned from the schema template, with a
manager who owns the project, an editor on the project team and an outsider.

What is proved here and nowhere else:

* a project that never opened its catalogue files ``RFI-001`` as before;
* numbering runs per prefix through the real ``MAX(cast(substr(...)))`` scan,
  and ``SBQ-0001`` never joins the ``SQ`` sequence;
* a preset loads once, a second load skips, and a project's own edits survive;
* a type's required fields stop the request being issued, never drafted;
* a type's default approval route is the one ``start_approval`` uses;
* the HTTP surface: managers edit the catalogue, editors read it, strangers get 404;
* revision ``v83_rfi_request_types`` backfills every existing row as an RFI
  without an UPDATE, and goes down and up again.
"""

from __future__ import annotations

import importlib.util
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.approval_routes.schemas import RouteCreate, StepCreate
from app.modules.approval_routes.service import ApprovalRouteService
from app.modules.rfi.permissions import register_rfi_permissions
from app.modules.rfi.schemas import RequestTypeCreate, RequestTypeUpdate, RFICreate, RFIUpdate
from app.modules.rfi.service import RFIService
from app.modules.rfi.type_service import RequestTypeService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project, add_user

pytestmark = [pytest.mark.asyncio]

BASE = "/api/v1/rfi"


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    editor: uuid.UUID
    outsider: uuid.UUID


@pytest_asyncio.fixture
async def world():
    register_rfi_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            manager = await add_user(s, "manager")
            editor = await add_user(s, "editor")
            outsider = await add_user(s, "manager")
            pid = await add_project(s, manager, [editor])
            await s.commit()
        yield World(factory, pid, manager, editor, outsider)


async def _create(w: World, **kw) -> object:
    async with w.factory() as s:
        payload = {"project_id": w.project_id, "subject": "Subject", "question": "Question", **kw}
        rfi = await RFIService(s).create_rfi(RFICreate(**payload), user_id=str(w.manager))
        await s.commit()
        return rfi


async def _load(w: World, preset: str) -> tuple[list[str], list[str]]:
    async with w.factory() as s:
        out = await RequestTypeService(s).load_preset(w.project_id, preset)
        await s.commit()
        return out


# ── Catalogue and numbering ─────────────────────────────────────────────


async def test_a_project_without_a_catalogue_files_rfis_as_before(world: World) -> None:
    async with world.factory() as s:
        catalogue = await RequestTypeService(s).catalogue(world.project_id)
    assert [(t.code, t.is_builtin) for t in catalogue] == [("RFI", True)]
    first = await _create(world)
    second = await _create(world)
    assert (first.rfi_number, first.request_type) == ("RFI-001", "RFI")
    assert second.rfi_number == "RFI-002"


async def test_numbering_runs_per_prefix_and_rfi_continues_its_own_sequence(world: World) -> None:
    await _create(world)  # RFI-001 before any catalogue exists
    await _load(world, "epc_oil_gas")
    tq1 = await _create(world, request_type="TQ")
    tq2 = await _create(world, request_type="tq")
    rfi = await _create(world)
    assert [tq1.rfi_number, tq2.rfi_number, rfi.rfi_number] == ["TQ-0001", "TQ-0002", "RFI-002"]
    assert tq2.request_type == "TQ"


async def test_sbq_numbers_never_join_the_sq_sequence(world: World) -> None:
    await _load(world, "general_construction")
    await _create(world, request_type="SBQ")
    await _create(world, request_type="SBQ")
    sq = await _create(world, request_type="SQ")
    assert sq.rfi_number == "SQ-0001"


async def test_a_preset_loads_once_and_a_second_preset_skips_what_the_project_has(world: World) -> None:
    created, skipped = await _load(world, "general_construction")
    assert created == ["RFI", "SQ", "DQ", "SBQ", "CLR", "DEC"] and skipped == []
    again = await _load(world, "general_construction")
    assert again == ([], ["RFI", "SQ", "DQ", "SBQ", "CLR", "DEC"])
    created, skipped = await _load(world, "epc_oil_gas")
    assert set(skipped) == {"RFI", "SQ"}
    assert {"TQ", "VQ", "FQ", "IQ", "TDR", "CON", "KDCN", "HAZ", "CIP"} == set(created)


async def test_a_project_edit_survives_reloading_the_preset(world: World) -> None:
    await _load(world, "epc_oil_gas")
    async with world.factory() as s:
        svc = RequestTypeService(s)
        row = await svc.repo.get_by_code(world.project_id, "TQ")
        await svc.update_type(row, RequestTypeUpdate(default_response_days=4))
        await s.commit()
    await _load(world, "epc_oil_gas")
    async with world.factory() as s:
        row = await RequestTypeService(s).repo.get_by_code(world.project_id, "TQ")
    assert row.default_response_days == 4


async def test_a_custom_type_cannot_reuse_a_prefix(world: World) -> None:
    await _load(world, "general_construction")
    async with world.factory() as s:
        with pytest.raises(HTTPException) as exc:
            await RequestTypeService(s).create_type(
                RequestTypeCreate(
                    project_id=world.project_id, code="SQX", number_prefix="SQ", name_i18n={"en": "Second site"}
                )
            )
    assert exc.value.status_code == 409


async def test_a_custom_type_cannot_take_the_builtin_rfi_prefix(world: World) -> None:
    async with world.factory() as s:
        with pytest.raises(HTTPException) as exc:
            await RequestTypeService(s).create_type(
                RequestTypeCreate(project_id=world.project_id, code="RFX", number_prefix="RFI", name_i18n={"en": "X"})
            )
    assert exc.value.status_code == 409


async def test_unknown_type_is_refused(world: World) -> None:
    with pytest.raises(HTTPException) as exc:
        await _create(world, request_type="TQ")
    assert exc.value.status_code == 422


# ── Required fields and SLA ─────────────────────────────────────────────


async def test_an_issued_request_needs_its_types_fields_and_a_draft_does_not(world: World) -> None:
    await _load(world, "epc_oil_gas")
    with pytest.raises(HTTPException) as exc:
        await _create(world, request_type="TDR", status="open")
    assert exc.value.status_code == 422
    assert exc.value.detail["missing_fields"] == ["assigned_to", "discipline", "linked_drawing_ids"]

    draft = await _create(world, request_type="TDR", status="draft")
    async with world.factory() as s:
        with pytest.raises(HTTPException) as exc:
            await RFIService(s).update_rfi(draft.id, RFIUpdate(status="open"))
        assert exc.value.detail["missing_fields"] == ["assigned_to", "discipline", "linked_drawing_ids"]
    async with world.factory() as s:
        issued = await RFIService(s).update_rfi(
            draft.id,
            RFIUpdate(
                status="open",
                assigned_to=str(world.editor),
                discipline="mechanical",
                linked_drawing_ids=[str(uuid.uuid4())],
            ),
        )
        await s.commit()
    assert issued.status == "open"


async def test_the_type_sla_sets_the_due_date(world: World) -> None:
    from datetime import UTC, datetime

    from app.modules.rfi.service import _add_business_days

    await _load(world, "general_construction")
    clr = await _create(world, request_type="CLR", status="open", assigned_to=str(world.editor))
    assert clr.response_due_date == _add_business_days(datetime.now(UTC), 7)


async def test_a_retired_type_stops_new_requests_but_not_existing_ones(world: World) -> None:
    await _load(world, "epc_oil_gas")
    cip = await _create(world, request_type="CIP")
    async with world.factory() as s:
        svc = RequestTypeService(s)
        await svc.update_type(await svc.repo.get_by_code(world.project_id, "CIP"), RequestTypeUpdate(is_active=False))
        await s.commit()
    with pytest.raises(HTTPException) as exc:
        await _create(world, request_type="CIP")
    assert exc.value.status_code == 422
    async with world.factory() as s:
        moved = await RFIService(s).update_rfi(cip.id, RFIUpdate(status="open"))
        await s.commit()
    assert moved.status == "open"


async def test_a_type_in_use_cannot_be_deleted(world: World) -> None:
    await _load(world, "epc_oil_gas")
    await _create(world, request_type="VQ")
    async with world.factory() as s:
        svc = RequestTypeService(s)
        with pytest.raises(HTTPException) as exc:
            await svc.delete_type(await svc.repo.get_by_code(world.project_id, "VQ"))
        assert exc.value.status_code == 409
        await svc.delete_type(await svc.repo.get_by_code(world.project_id, "FQ"))
        await s.commit()


# ── Register: filter, stats, validation ─────────────────────────────────


async def test_list_filters_and_stats_count_by_type(world: World) -> None:
    await _load(world, "epc_oil_gas")
    await _create(world)
    await _create(world, request_type="TQ")
    await _create(
        world,
        request_type="TQ",
        status="open",
        assigned_to=str(world.editor),
        discipline="civil",
        response_due_date="2020-01-01",
    )
    async with world.factory() as s:
        svc = RFIService(s)
        rows, total = await svc.list_rfis(world.project_id, request_type="TQ")
        stats = await svc.get_stats(world.project_id)
    assert total == 2 and {r.request_type for r in rows} == {"TQ"}
    assert stats.by_type["TQ"].total == 2
    assert stats.by_type["TQ"].open == 2
    assert stats.by_type["TQ"].overdue == 1
    assert stats.by_type["RFI"].total == 1


async def test_validation_flags_an_issued_request_its_type_now_requires_more_of(world: World) -> None:
    await _load(world, "epc_oil_gas")
    cip = await _create(world, request_type="CIP", status="open")
    async with world.factory() as s:
        svc = RequestTypeService(s)
        await svc.update_type(
            await svc.repo.get_by_code(world.project_id, "CIP"), RequestTypeUpdate(required_fields=["priority"])
        )
        await s.commit()
    async with world.factory() as s:
        report = await RFIService(s).validate_register(world.project_id)
    failed = [r for r in report.results if not r.passed]
    assert [(r.rule_id, r.element_ref) for r in failed] == [("rfi.request_type_required_fields", str(cip.id))]


# ── Approval routes ─────────────────────────────────────────────────────


async def _route(w: World, kind: str = "rfi") -> uuid.UUID:
    async with w.factory() as s:
        route = await ApprovalRouteService(s).create_route(
            RouteCreate(
                project_id=w.project_id,
                name=f"{kind} sign-off",
                target_kind=kind,
                steps=[StepCreate(ordinal=1, approver_user_id=w.manager, mode="all")],
            ),
            created_by=w.manager,
        )
        await s.commit()
        return route.id


async def test_a_types_default_route_is_the_one_an_approval_starts_on(world: World) -> None:
    await _load(world, "epc_oil_gas")
    route_id = await _route(world)
    async with world.factory() as s:
        svc = RequestTypeService(s)
        await svc.update_type(
            await svc.repo.get_by_code(world.project_id, "TQ"), RequestTypeUpdate(default_route_id=route_id)
        )
        await s.commit()
    # A draft with what TQ requires: starting the approval issues it (draft -> open).
    tq = await _create(
        world, request_type="TQ", assigned_to=str(world.editor), discipline="process", response_due_date="2026-12-01"
    )
    rfi = await _create(world)
    async with world.factory() as s:
        instance = await RFIService(s).start_approval(tq.id, None, started_by=str(world.manager))
        await s.commit()
    assert instance.route_id == route_id
    async with world.factory() as s:
        with pytest.raises(HTTPException) as exc:
            await RFIService(s).start_approval(rfi.id, None, started_by=str(world.manager))
    assert exc.value.status_code == 422


async def test_a_default_route_must_sign_off_rfis(world: World) -> None:
    await _load(world, "epc_oil_gas")
    other = await _route(world, kind="submittal")
    async with world.factory() as s:
        svc = RequestTypeService(s)
        with pytest.raises(HTTPException) as exc:
            await svc.update_type(
                await svc.repo.get_by_code(world.project_id, "TQ"), RequestTypeUpdate(default_route_id=other)
            )
    assert exc.value.status_code == 422


# ── HTTP ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.rfi.router import router

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": [],
        "tenant_id": str(user_id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://rfi-types-test") as c:
        yield c


async def test_http_catalogue_presets_and_filtered_register(world: World) -> None:
    pid = str(world.project_id)
    async with client_as(world, world.manager, "manager") as c:
        listed = await c.get(f"{BASE}/types/", params={"project_id": pid})
        assert listed.status_code == 200
        assert [(t["code"], t["is_builtin"]) for t in listed.json()["items"]] == [("RFI", True)]

        presets = await c.get(f"{BASE}/types/presets/")
        assert [p["code"] for p in presets.json()["items"]] == ["general_construction", "epc_oil_gas"]

        loaded = await c.post(f"{BASE}/types/presets/epc_oil_gas/load/", params={"project_id": pid})
        assert loaded.status_code == 200 and "TQ" in loaded.json()["created"]
        missing = await c.post(f"{BASE}/types/presets/nope/load/", params={"project_id": pid})
        assert missing.status_code == 404

        made = await c.post(
            f"{BASE}/",
            json={"project_id": pid, "subject": "Nozzle load", "question": "Allowable?", "request_type": "TQ"},
        )
        assert made.status_code == 201 and made.json()["rfi_number"] == "TQ-0001"
        assert made.json()["request_type"] == "TQ"
        refused = await c.post(
            f"{BASE}/",
            json={"project_id": pid, "subject": "s", "question": "q", "request_type": "TQ", "status": "open"},
        )
        assert refused.status_code == 422
        assert refused.json()["detail"]["error"] == "request_type_required_fields"

        only_tq = await c.get(f"{BASE}/", params={"project_id": pid, "request_type": "TQ"})
        assert [r["rfi_number"] for r in only_tq.json()["items"]] == ["TQ-0001"]
        stats = await c.get(f"{BASE}/stats/", params={"project_id": pid})
        assert stats.json()["by_type"]["TQ"]["total"] == 1

        custom = await c.post(
            f"{BASE}/types/",
            json={"project_id": pid, "code": "mq", "number_prefix": "mq", "name_i18n": {"en": "Method Query"}},
        )
        assert custom.status_code == 201 and custom.json()["code"] == "MQ"
        patched = await c.patch(
            f"{BASE}/types/{custom.json()['id']}", json={"name_i18n": {"en": "Method Query", "de": "Methodenanfrage"}}
        )
        assert patched.json()["name_i18n"]["de"] == "Methodenanfrage"
        deleted = await c.delete(f"{BASE}/types/{custom.json()['id']}")
        assert deleted.status_code == 204

        check = await c.get(f"{BASE}/validation/", params={"project_id": pid})
        assert check.status_code == 200 and check.json()["status"] == "passed"


async def test_http_editors_read_the_catalogue_but_do_not_edit_it(world: World) -> None:
    pid = str(world.project_id)
    async with client_as(world, world.editor, "editor") as c:
        assert (await c.get(f"{BASE}/types/", params={"project_id": pid})).status_code == 200
        load = await c.post(f"{BASE}/types/presets/general_construction/load/", params={"project_id": pid})
        assert load.status_code == 403


@pytest.mark.tenant_isolation
async def test_http_a_stranger_sees_404_on_another_projects_catalogue(world: World) -> None:
    pid = str(world.project_id)
    await _load(world, "general_construction")
    async with world.factory() as s:
        sq = await RequestTypeService(s).repo.get_by_code(world.project_id, "SQ")
    async with client_as(world, world.outsider, "manager") as c:
        responses = [
            await c.get(f"{BASE}/types/", params={"project_id": pid}),
            await c.post(f"{BASE}/types/presets/epc_oil_gas/load/", params={"project_id": pid}),
            await c.patch(f"{BASE}/types/{sq.id}", json={"is_active": False}),
            await c.delete(f"{BASE}/types/{sq.id}"),
            await c.get(f"{BASE}/validation/", params={"project_id": pid}),
        ]
    assert [r.status_code for r in responses] == [404] * len(responses)


# ── Migration ───────────────────────────────────────────────────────────


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/v83_rfi_request_types.py"
    spec = importlib.util.spec_from_file_location("rfi_request_types_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_migration_backfills_every_existing_request_as_an_rfi_and_round_trips(world: World) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _migration()
    rid = str(uuid.uuid4())

    def run(conn) -> None:
        # The database as it stood before this revision: no catalogue, no column.
        conn.execute(text('DROP TABLE "oe_rfi_request_type"'))
        conn.execute(text('ALTER TABLE "oe_rfi_rfi" DROP COLUMN "request_type"'))
        conn.execute(
            text(
                'INSERT INTO "oe_rfi_rfi" (id, project_id, rfi_number, subject, question, raised_by, status, '
                "cost_impact, schedule_impact) VALUES (:id, :pid, 'RFI-007', 'Old', 'Old question', :uid, 'open', "
                "false, false)"
            ),
            {"id": rid, "pid": str(world.project_id), "uid": str(world.manager)},
        )
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        migration.upgrade()  # idempotent on a database that already has everything

        insp = inspect(conn)
        column = {c["name"]: c for c in insp.get_columns("oe_rfi_rfi")}["request_type"]
        assert column["nullable"] is False
        assert "RFI" in str(column["default"])
        assert "ix_rfi_project_request_type" in {ix["name"] for ix in insp.get_indexes("oe_rfi_rfi")}
        assert "oe_rfi_request_type" in insp.get_table_names()
        assert (
            conn.execute(text('SELECT request_type FROM "oe_rfi_rfi" WHERE id = :id'), {"id": rid}).scalar_one()
            == "RFI"
        )

        migration.downgrade()
        migration.downgrade()
        insp = inspect(conn)
        assert "oe_rfi_request_type" not in insp.get_table_names()
        assert "request_type" not in {c["name"] for c in insp.get_columns("oe_rfi_rfi")}
        assert (
            conn.execute(text('SELECT rfi_number FROM "oe_rfi_rfi" WHERE id = :id'), {"id": rid}).scalar_one()
            == "RFI-007"
        )

        migration.upgrade()
        assert (
            conn.execute(text('SELECT request_type FROM "oe_rfi_rfi" WHERE id = :id'), {"id": rid}).scalar_one()
            == "RFI"
        )

    async with world.factory() as s:
        await s.run_sync(lambda sync_session: run(sync_session.connection()))
        await s.commit()

    # The service reads the backfilled row as an RFI and numbers on from it.
    nxt = await _create(world)
    assert nxt.rfi_number == "RFI-008"
