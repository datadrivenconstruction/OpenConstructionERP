# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The site-logistics plan service against PostgreSQL: rules that need real rows.

Covers the area balance per stage, heavy-transport scheduling against permits,
permit expiry, customs document templates, the plant-position power hook,
JSON columns holding JSON-native values, and the demo seed being idempotent
and not silently skipped.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.site_logistics.errors import LogisticsError
from app.modules.site_logistics.plan_service import LogisticsPlanService
from tests._pg import isolated_engine
from tests.pg.site_logistics_fixtures import SITE, World, build_world, square, window

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


@pytest_asyncio.fixture
async def bare():
    """A project whose logistics plan was never opened: the demo seeds only those."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, start_plan=False)


async def _stage(svc: LogisticsPlanService, w: World):
    return (await svc.stages(w.project_id))[0]


async def _area(svc, w, code, kind, stage, m2, *, geometry=None, declared=None):
    data = {"code": code, "name": code, "area_kind": kind}
    if geometry is not None:
        data["geometry"] = geometry
    if declared is not None:
        data["area_m2_declared"] = Decimal(declared)
    area = await svc.create_area(w.project_id, data, w.manager)
    await svc.put_allocations(
        w.project_id, area.id, [{"stage_id": stage.id, "area_kind": kind, "allocated_m2": Decimal(m2)}], w.manager
    )
    return area


async def test_area_balance_closes_and_reports_gaps(world: World) -> None:
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        stage = await _stage(svc, world)
        # Gaps are reported for the stage the site runs on, not for one that is only planned.
        await svc.transition_stage(world.project_id, stage.id, "active", world.manager)
        await _area(svc, world, "SITE", "site_total", stage, "10000", geometry=square(100))
        await _area(svc, world, "B1", "building_footprint", stage, "7000", declared="7000")
        bal = await svc.balance(world.project_id)
        item = bal["items"][0]
        assert item["area"]["closed"] is False
        assert Decimal(item["area"]["difference_m2"]) == Decimal("-3000")
        assert set(item["gaps"]) == {"stage_without_storage", "stage_without_site_setup"}

        await _area(svc, world, "L1", "laydown", stage, "2000", declared="2000")
        await _area(svc, world, "S1", "site_setup", stage, "950", declared="950")
        item = (await svc.balance(world.project_id))["items"][0]
        # 9950 of 10000 is inside the 2 % tolerance of the neutral catalogue.
        assert item["area"]["closed"] is True
        assert item["gaps"] == []
        await s.commit()


async def test_allocation_larger_than_its_area_is_refused(world: World) -> None:
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        stage = await _stage(svc, world)
        area = await svc.create_area(
            world.project_id, {"code": "Y1", "name": "Yard", "area_kind": "storage", "geometry": square(10)}, None
        )
        with pytest.raises(LogisticsError) as exc:
            await svc.put_allocations(
                world.project_id, area.id, [{"stage_id": stage.id, "allocated_m2": Decimal("101")}], None
            )
        assert exc.value.code == "allocation_exceeds_area"


async def test_overlapping_areas_of_different_kinds_are_found(world: World) -> None:
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        stage = await _stage(svc, world)
        a = await _area(svc, world, "A", "laydown", stage, "100", geometry=square(10))
        b = await _area(svc, world, "B", "site_setup", stage, "100", geometry=square(10, 5, 5))
        item = (await svc.balance(world.project_id))["items"][0]
        assert {tuple(sorted(p)) for p in item["overlaps"]} == {tuple(sorted((str(a.id), str(b.id))))}


async def test_heavy_transport_needs_a_granted_permit_covering_its_window(world: World) -> None:
    start, end = window(7, 22, 4)
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        t = await svc.create_transport(
            world.project_id,
            {
                "direction": "inbound",
                # The neutral catalogue has no load classes: heavy is what the transport kind says.
                "transport_kind": "heavy_oversize",
                "title": "Transformer",
                "gross_weight_t": Decimal("96"),
                "width_m": Decimal("3.6"),
                "planned_window_start": start,
                "planned_window_end": end,
            },
            world.manager,
        )
        view = await svc.transport_view(t, await svc.catalogue(world.project_id), SITE)
        assert view["is_heavy"] is True
        assert "is_heavy" not in {c.name for c in t.__table__.columns}
        with pytest.raises(LogisticsError) as exc:
            await svc.transition_transport(world.project_id, t.id, "scheduled", world.manager)
        assert exc.value.code == "heavy_without_permit"

        permit = await svc.create_permit(
            world.project_id,
            {
                "permit_kind": "oversize_permit",
                "reference": "OS-1",
                "covers_transport_ids": [t.id],
                "valid_from": start.date() - timedelta(days=1),
                "valid_to": end.date() + timedelta(days=1),
                "allowed_windows": [{"weekdays": list(range(7)), "from": "06:00", "to": "18:00"}],
            },
            world.manager,
        )
        for target in ("applied", "granted"):
            await svc.transition_permit(world.project_id, permit.id, target, world.manager)
        with pytest.raises(LogisticsError) as exc:
            await svc.transition_transport(world.project_id, t.id, "scheduled", world.manager)
        assert exc.value.code == "window_outside_permit"

        # What the authority granted is frozen: nobody widens the windows afterwards.
        with pytest.raises(LogisticsError) as exc:
            await svc.update_permit(
                world.project_id,
                permit.id,
                {"allowed_windows": [{"weekdays": list(range(7)), "from": "21:00", "to": "05:00"}]},
                world.manager,
            )
        assert (exc.value.code, exc.value.status_code) == ("permit_frozen", 409)
        for frozen in (
            {"valid_to": end.date() + timedelta(days=400)},
            {"valid_from": start.date() - timedelta(days=400)},
            {"permit_kind": "night_work"},
            {"covers_transport_ids": []},
        ):
            with pytest.raises(LogisticsError) as exc:
                await svc.update_permit(world.project_id, permit.id, frozen, world.manager)
            assert exc.value.code == "permit_frozen", frozen
        # Sending what is stored is not a change, and the free fields stay editable.
        await svc.update_permit(
            world.project_id,
            permit.id,
            {"valid_to": end.date() + timedelta(days=1), "covers_transport_ids": [str(t.id)], "authority": "Roads"},
            world.manager,
        )
        permit = await svc.create_permit(
            world.project_id,
            {
                "permit_kind": "oversize_permit",
                "reference": "OS-1b",
                "covers_transport_ids": [t.id],
                "valid_from": start.date() - timedelta(days=1),
                "valid_to": end.date() + timedelta(days=1),
                "allowed_windows": [{"weekdays": list(range(7)), "from": "21:00", "to": "05:00"}],
            },
            world.manager,
        )
        for target in ("applied", "granted"):
            await svc.transition_permit(world.project_id, permit.id, target, world.manager)
        moved = await svc.transition_transport(world.project_id, t.id, "scheduled", world.manager)
        assert moved.state == "scheduled"
        await s.commit()

    async with world.factory() as s:
        raw = (
            await s.execute(
                sa.text("SELECT allowed_windows::text FROM oe_site_logistics_transport_permit WHERE id = :id"),
                {"id": str(permit.id)},
            )
        ).scalar_one()
        assert json.loads(raw) == [{"weekdays": list(range(7)), "from": "21:00", "to": "05:00"}]


async def test_sweep_expires_a_past_permit_that_still_has_transports(world: World) -> None:
    start, end = window(1, 22, 2)
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        t = await svc.create_transport(
            world.project_id,
            {
                "direction": "inbound",
                "transport_kind": "heavy_oversize",
                "title": "Beam",
                "planned_window_start": start,
                "planned_window_end": end,
            },
            world.manager,
        )
        p = await svc.create_permit(
            world.project_id,
            {
                "permit_kind": "oversize_permit",
                "reference": "OS-2",
                "covers_transport_ids": [t.id],
                "valid_from": date(2026, 1, 1),
                "valid_to": date(2026, 1, 31),
            },
            world.manager,
        )
        for target in ("applied", "granted"):
            await svc.transition_permit(world.project_id, p.id, target, world.manager)
        # The sweep reads the server's date; it takes none from a caller.
        counts = await svc.sweep_permits(world.project_id)
        assert counts["expired"] == 1
        assert p.state == "expired"
        assert await svc.sweep_permits(world.project_id) == {"expired": 0, "expiring": 0}
        await s.commit()


async def test_customs_case_builds_its_document_checklist_from_the_incoterm(world: World) -> None:
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        fca = await svc.create_customs(
            world.project_id,
            {
                "direction": "import",
                "title": "Switchgear",
                "incoterm": "FCA",
                "transport_mode": "road",
                "declarant_party": "buyer",
                "customs_value": Decimal("184250.40"),
                "currency": "EUR",
            },
            world.manager,
            can_see_values=True,
        )
        ddp = await svc.create_customs(
            world.project_id,
            {
                "direction": "import",
                "title": "Pumps",
                "incoterm": "DDP",
                "transport_mode": "road",
                "declarant_party": "buyer",
                "customs_value": Decimal("1"),
            },
            world.manager,
            can_see_values=False,
        )
        exw = await svc.create_customs(
            world.project_id,
            {"direction": "import", "title": "Valves", "incoterm": "EXW", "transport_mode": "road"},
            world.manager,
            can_see_values=True,
        )
        ddp_out = await svc.create_customs(
            world.project_id,
            {"direction": "export", "title": "Returned formwork", "incoterm": "DDP", "transport_mode": "road"},
            world.manager,
            can_see_values=True,
        )
        await s.flush()
        assert {"commercial_invoice", "import_declaration", "cmr"} <= await _doc_kinds(s, fca.id)
        assert "export_declaration" not in await _doc_kinds(s, fca.id)
        assert not {"import_declaration", "export_declaration"} & await _doc_kinds(s, ddp.id)
        # EXW: the buyer clears export as well. DDP: the seller clears import as well.
        assert {"import_declaration", "export_declaration"} <= await _doc_kinds(s, exw.id)
        assert {"import_declaration", "export_declaration"} <= await _doc_kinds(s, ddp_out.id)
        with pytest.raises(LogisticsError) as exc:
            await svc.create_customs(
                world.project_id,
                {"direction": "import", "title": "No currency", "incoterm": "FCA", "customs_value": Decimal("5.00")},
                world.manager,
                can_see_values=True,
            )
        assert exc.value.code == "currency_required"
        assert ddp.customs_value is None  # stripped for a user without the customs permission
        assert fca.customs_value == Decimal("184250.40")
        codes = {f["code"] for f in await svc.findings(world.project_id)}
        assert "declarant_mismatch_incoterm" in codes  # DDP: the seller clears import
        await s.commit()


async def _doc_kinds(session: AsyncSession, case_id) -> set[str]:
    from app.modules.site_logistics.models import CustomsDocument

    rows = await session.execute(sa.select(CustomsDocument.kind).where(CustomsDocument.customs_case_id == case_id))
    return set(rows.scalars())


async def test_plant_position_power_demand_hook_upserts_and_removes(world: World) -> None:
    import uuid

    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        stage = await _stage(svc, world)
        position = uuid.uuid4()
        kwargs = {
            "site_plant_position_id": position,
            "stage_id": stage.id,
            "consumer": "Tower crane TC1",
            "actor_id": world.manager,
        }
        # Over the API nobody can say whose position this is until the plant module plugs in.
        with pytest.raises(LogisticsError) as exc:
            await svc.sync_plant_power_demand(world.project_id, power_demand_kva=Decimal("120"), **kwargs)
        assert exc.value.code == "link_target_unavailable"
        kwargs["trusted"] = True  # the plant module's own call
        await svc.sync_plant_power_demand(world.project_id, power_demand_kva=Decimal("120"), **kwargs)
        await svc.sync_plant_power_demand(world.project_id, power_demand_kva=Decimal("140"), **kwargs)
        from app.modules.site_logistics.models import MediaDemand

        rows = (
            (await s.execute(sa.select(MediaDemand).where(MediaDemand.project_id == world.project_id))).scalars().all()
        )
        assert [(r.media_kind, r.peak_demand) for r in rows] == [("power", Decimal("140"))]
        await svc.sync_plant_power_demand(world.project_id, power_demand_kva=None, **kwargs)
        rows = (
            (await s.execute(sa.select(MediaDemand).where(MediaDemand.project_id == world.project_id))).scalars().all()
        )
        assert rows == []
        await s.commit()


async def test_demo_seed_runs_closes_its_balances_and_is_idempotent(bare: World) -> None:
    from app.modules.site_logistics.demo_plan import seed_logistics_plan_demo

    world = bare
    async with world.factory() as s:
        first = await seed_logistics_plan_demo(s, [world.project_id])
        await s.commit()
    assert first["projects"] == 1, "the demo swallowed an error; see the warning log"
    async with world.factory() as s:
        again = await seed_logistics_plan_demo(s, [world.project_id])
        svc = LogisticsPlanService(s)
        bal = await svc.balance(world.project_id)
        readiness = await svc.readiness(world.project_id)
        codes = {f["code"] for f in await svc.findings(world.project_id)}
    assert again["projects"] == 0
    assert [i["area"]["closed"] for i in bal["items"]] == [True, True]
    # No governance model and no gates in this world: there is no frame document to
    # export into, so the saved concept meets the item.
    assert readiness["governance"] == "no_governance_model"
    assert readiness["gates_in_use"] is False
    exported = next(i for i in readiness["items"] if i["code"] == "concept_saved_and_exported")
    assert exported["state"] == "met"
    # The demo is a valid plan on its own clock: nothing was skipped for a missing zone,
    # and the flagship heavy transport is scheduled on its granted permits.
    assert (
        not {
            "site_timezone_missing",
            "gate_load_exceeded",
            "heavy_without_permit",
            "window_outside_permit",
            "quiet_hours_conflict",
        }
        & codes
    )
    json.dumps(bal)
    json.dumps(readiness)
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        summary = await svc.frame_summary(world.project_id, can_see_values=True)
        heavy = [t for t in summary["transports"] if t["is_heavy"]]
        assert [t["state"] for t in heavy] == ["scheduled"]
        assert {p["permit_kind"]: p["state"] for p in heavy[0]["permits"]} == {
            "oversize_permit": "granted",
            "night_work": "granted",
        }
        from app.modules.site_logistics import models as m

        for model in (
            m.ExpansionStage,
            m.SiteArea,
            m.AreaAllocation,
            m.MediaConnection,
            m.MediaDemand,
            m.Transport,
            m.TransportPermit,
            m.CustomsCase,
            m.CustomsLine,
            m.CustomsDocument,
            m.NeighbourIssue,
            m.CoordinationEntry,
        ):
            assert await svc._list(model, world.project_id), model.__name__
        assert summary["concept"]["site_timezone"] == "UTC"
        assert summary["concept"]["strategy"]
        # Chronology: no permit ends before it starts, no window ends before it opens.
        for p in summary["permits"]:
            assert p["valid_from"] <= p["valid_to"]
        for t in summary["transports"]:
            assert t["planned_window_start"] < t["planned_window_end"]


async def test_json_columns_hold_json_native_values(bare: World) -> None:
    from app.modules.site_logistics.demo_plan import seed_logistics_plan_demo

    world = bare
    async with world.factory() as s:
        assert (await seed_logistics_plan_demo(s, [world.project_id]))["projects"] == 1
        await s.commit()
    async with world.factory() as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_name LIKE 'oe_site_logistics_%' AND data_type IN ('json', 'jsonb')"
                )
            )
        ).all()
        assert rows
        for table, column in rows:
            values = (await s.execute(sa.text(f"SELECT {column}::text FROM {table}"))).scalars().all()
            for v in values:
                if v is not None:
                    assert "Decimal(" not in v and "datetime." not in v, (table, column, v)
                    json.loads(v)


async def test_neighbour_issue_owner_must_be_a_project_member(world: World) -> None:
    from app.modules.site_logistics.plan_service import complaint_out

    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        owned = await svc.create_complaint(
            world.project_id,
            {"kind": "noise", "description": "Pump before 07:00", "owner_user_id": world.editor},
            world.manager,
        )
        assert complaint_out(owned)["owner_user_id"] == str(world.editor)
        with pytest.raises(LogisticsError) as exc:
            await svc.create_complaint(
                world.project_id, {"kind": "dust", "owner_user_id": world.outsider}, world.manager
            )
        assert exc.value.code == "owner_not_member"
        with pytest.raises(LogisticsError) as exc:
            await svc.update_complaint(world.project_id, owned.id, {"owner_user_id": world.outsider}, world.manager)
        assert exc.value.code == "owner_not_member"
        await s.commit()
