# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The defects the review of 2026-10-12 found in the logistics plan, against PostgreSQL.

Each test is one database, so related defects share a test:

* reads create no rows and do not arm the gate evidence;
* the site clock: windows stored as instants are judged in the site time zone
  after a round trip, and nothing is judged without one;
* one gate load rule for every path that approves a delivery, lifted only by a
  granted oversize permit, and the deliveries per hour of the concept;
* arrivals read only receipts dated on or after the departure, and first writes
  that race end in one row;
* the gate evidence resolves area and gate from the governance catalogue's tags.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.site_logistics import models as m
from app.modules.site_logistics.errors import LogisticsError
from app.modules.site_logistics.permissions import register_site_logistics_permissions
from app.modules.site_logistics.plan_service import LogisticsPlanService
from app.modules.site_logistics.schemas import DeliveryCreate, DeliveryUpdate
from app.modules.site_logistics.service import SiteLogisticsService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project
from tests.pg.site_logistics_fixtures import BASE, SITE, World, build_world, client_as, window

pytestmark = pytest.mark.asyncio

_PLAN_TABLES = (m.LogisticsConcept, m.ExpansionStage, m.NeighbourhoodPlan)


@pytest_asyncio.fixture
async def world():
    register_site_logistics_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


@pytest_asyncio.fixture
async def bare():
    register_site_logistics_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, start_plan=False)


async def _count(session: AsyncSession, model, project_id: uuid.UUID) -> int:
    return (
        await session.execute(sa.select(sa.func.count()).select_from(model).where(model.project_id == project_id))
    ).scalar_one()


def _utc(day, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


# ── reads never write ──────────────────────────────────────────────────────


async def test_reading_a_project_without_a_plan_creates_nothing(bare: World) -> None:
    from app.modules.project_governance.evidence import GateAttempt
    from app.modules.site_logistics.evidence import logistics_readiness

    pid = bare.project_id
    async with bare.factory() as s:
        svc = LogisticsPlanService(s)
        assert await svc.concept(pid) is None
        assert (await svc.concept_view(pid))["id"] is None
        assert await svc.stages(pid) == []
        assert (await svc.neighbourhood_view(pid))["id"] is None
        assert (await svc.balance(pid))["items"] == []
        assert await svc.findings(pid) == []
        readiness = await svc.readiness(pid)
        assert readiness["ready"] is False
        await svc.frame_summary(pid)
        await svc.validate(pid)
        assert (await svc.catalogue(pid)).id
        assert await svc.plan_started(pid) is False
        attempt = GateAttempt(gate_id=uuid.uuid4(), gate_code="any", attempt_no=1)
        assert await logistics_readiness(s, pid, attempt, type("Area", (), {"code": "any"})()) == []
        await s.commit()
    async with client_as(bare, bare.manager, "manager") as c:
        for path in (
            "concept",
            "stages",
            "neighbourhood",
            "balance",
            "readiness",
            "frame-summary",
            "catalogue",
            "transports",
            "permits",
            "customs",
            "media",
            "areas",
            "neighbour-issues",
            "coordination",
        ):
            r = await c.get(f"{BASE}/projects/{pid}/{path}")
            assert r.status_code == 200, (path, r.text)
        validated = await c.post(f"{BASE}/projects/{pid}/validate")
        assert validated.status_code == 200, validated.text
        assert len([x for x in validated.json()["rules_run"] if x.startswith("site_logistics.")]) >= 22
    async with bare.factory() as s:
        for model in _PLAN_TABLES:
            assert await _count(s, model, pid) == 0, model.__name__
        # The first write starts the plan: the concept, and the stage every project has.
        await LogisticsPlanService(s).put_concept(pid, {"site_timezone": "Europe/Berlin"}, bare.manager)
        await s.commit()
    async with bare.factory() as s:
        svc = LogisticsPlanService(s)
        assert await _count(s, m.LogisticsConcept, pid) == 1
        assert [st.code for st in await svc.stages(pid)] == ["stage_0"]
        # A concept that holds only its pin and its clock is still not a plan to hold a gate on.
        assert await svc.plan_started(pid) is False
        await svc.put_concept(pid, {"rules_text": "Book 48 hours ahead."}, bare.manager)
        assert await svc.plan_started(pid) is True


# ── the site clock, the gate load rule and the hourly rate ─────────────────


async def _gate(session: AsyncSession, project_id: uuid.UUID, name: str, **limits) -> m.Gate:
    gate = m.Gate(project_id=project_id, name=name, open_time="07:00", close_time="18:00", **limits)
    session.add(gate)
    await session.flush()
    return gate


def _booking(project_id: uuid.UUID, gate_id: uuid.UUID, start: datetime, end: datetime, **kw) -> DeliveryCreate:
    return DeliveryCreate(
        project_id=project_id, gate_id=gate_id, supplier_name="Supplier", window_start=start, window_end=end, **kw
    )


async def _refused(awaitable) -> str:
    with pytest.raises(HTTPException) as exc:
        await awaitable
    assert exc.value.status_code == 400, exc.value.detail
    return str(exc.value.detail)


async def test_site_clock_gate_load_and_rate_on_every_approval_path(world: World) -> None:
    pid = world.project_id
    day = (datetime.now(SITE) + timedelta(days=10)).date()
    async with world.factory() as s:
        gate = await _gate(s, pid, "North", max_gross_t=Decimal("40"))
        other_gate = await _gate(s, pid, "South")
        await s.commit()

    # 1. Gate hours on the site clock (UTC+05:30), after a PostgreSQL round trip.
    async with world.factory() as s:
        legacy = SiteLogisticsService(s)
        # 02:00 UTC is 07:30 on site: open, though the UTC clock reads 02:00.
        early = await legacy.create_delivery(_booking(pid, gate.id, _utc(day, 2), _utc(day, 3)), str(world.manager))
        # 13:00 UTC is 18:30 on site: closed, though the UTC clock reads 13:00.
        assert "closes" in await _refused(
            legacy.create_delivery(_booking(pid, gate.id, _utc(day, 12, 45), _utc(day, 13)), str(world.manager))
        )
        # 01:00 UTC is 06:30 on site: not open yet.
        assert "opens" in await _refused(
            legacy.create_delivery(_booking(pid, gate.id, _utc(day, 1), _utc(day, 2)), str(world.manager))
        )
        # A wall clock value without an offset is the site's wall clock.
        naive = await legacy.create_delivery(
            _booking(pid, gate.id, datetime.combine(day, time(9, 0)), datetime.combine(day, time(10, 0))),
            str(world.manager),
        )
    async with world.factory() as s:
        stored = await s.get(m.DeliveryBooking, naive.id)
        assert stored.window_start.astimezone(UTC) == _utc(day, 3, 30)
        assert (await s.get(m.DeliveryBooking, early.id)).window_start.astimezone(SITE).time() == time(7, 30)

    # 2. A 62 t load at a 40 t gate is refused on every path that would approve it.
    heavy_start, heavy_end = _utc(day, 5), _utc(day, 6)  # 10:30 to 11:30 on site
    async with world.factory() as s:
        legacy = SiteLogisticsService(s)
        detail = await _refused(
            legacy.create_delivery(
                _booking(pid, gate.id, heavy_start, heavy_end, status="approved", gross_weight_t=Decimal("62")),
                str(world.manager),
            )
        )
        assert detail.startswith("gate_load_exceeded")
        requested = await legacy.create_delivery(
            _booking(pid, gate.id, heavy_start, heavy_end, gross_weight_t=Decimal("62")), str(world.manager)
        )
        assert (await _refused(legacy.update_delivery(requested.id, DeliveryUpdate(status="approved")))).startswith(
            "gate_load_exceeded"
        )
        assert (await _refused(legacy.approve_delivery(requested.id, user_id=str(world.manager)))).startswith(
            "gate_load_exceeded"
        )
        light = await legacy.create_delivery(
            _booking(pid, gate.id, _utc(day, 7), _utc(day, 8), status="approved", gross_weight_t=Decimal("30")),
            str(world.manager),
        )
        # An approved booking cannot grow past the limit afterwards either.
        assert (
            await _refused(legacy.update_delivery(light.id, DeliveryUpdate(gross_weight_t=Decimal("62"))))
        ).startswith("gate_load_exceeded")
    async with world.factory() as s:
        assert (await s.get(m.DeliveryBooking, requested.id)).status == "requested"
        assert (await s.get(m.DeliveryBooking, light.id)).gross_weight_t == Decimal("30.00")
        codes = [f["code"] for f in await LogisticsPlanService(s).findings(pid)]
        # The requested 62 t booking is reported; the missing zone is not, the site has one.
        assert "gate_load_exceeded" in codes
        assert "site_timezone_missing" not in codes

    # 3. A granted oversize permit covering the transport and its window lifts the limit for it.
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        transport = await svc.create_transport(
            pid,
            {
                "direction": "inbound",
                "transport_kind": "heavy_oversize",
                "title": "Transformer",
                "gate_id": gate.id,
                "gross_weight_t": Decimal("62"),
                "planned_window_start": heavy_start,
                "planned_window_end": heavy_end,
            },
            world.manager,
        )
        permit = await svc.create_permit(
            pid,
            {
                "permit_kind": "oversize_permit",
                "reference": "OS-9",
                "covers_transport_ids": [transport.id],
                "valid_from": day,
                "valid_to": day,
                "allowed_windows": [{"weekdays": list(range(7)), "from": "10:00", "to": "12:00"}],
            },
            world.manager,
        )
        await svc.transition_permit(pid, permit.id, "applied", world.manager)
        view = await svc.transport_view(transport, await svc.catalogue(pid), SITE)
        assert view["gate_blocked"] is True  # applied for is not granted
        with pytest.raises(LogisticsError) as exc:
            await svc.transition_transport(pid, transport.id, "scheduled", world.manager)
        assert exc.value.code in ("gate_load_exceeded", "heavy_without_permit")
        await svc.transition_permit(pid, permit.id, "granted", world.manager)
        await s.commit()
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        legacy = SiteLogisticsService(s)
        transport = await s.get(m.Transport, transport.id)
        view = await svc.transport_view(transport, await svc.catalogue(pid), SITE)
        assert view["gate_blocked"] is False
        assert view["gate_exceeded"] == ["gross_weight_t"]
        assert view["gate_passed_by_permit"] == {
            "id": str(permit.id),
            "permit_kind": "oversize_permit",
            "reference": "OS-9",
        }
        # The same load without the transport's permit is still refused ...
        assert (await _refused(legacy.approve_delivery(requested.id, user_id=str(world.manager)))).startswith(
            "gate_load_exceeded"
        )
        # ... and so is the permitted transport outside the window the permit covers.
        late = await legacy.create_delivery(
            _booking(
                pid, gate.id, _utc(day, 9), _utc(day, 10), gross_weight_t=Decimal("62"), transport_id=transport.id
            ),
            str(world.manager),
        )
        assert (await _refused(legacy.approve_delivery(late.id, user_id=str(world.manager)))).startswith(
            "gate_load_exceeded"
        )
        await legacy.update_delivery(requested.id, DeliveryUpdate(transport_id=transport.id))
        approved = await legacy.approve_delivery(requested.id, user_id=str(world.manager))
        assert approved.status == "approved"
        moved = await svc.transition_transport(pid, transport.id, "scheduled", world.manager)
        assert moved.state == "scheduled"
        await s.commit()
    async with world.factory() as s:
        readiness = await LogisticsPlanService(s).readiness(pid)
        assert [(x["title"], x["reference"]) for x in readiness["passed_by_permit"]] == [("Transformer", "OS-9")]
        admitted = next(i for i in readiness["items"] if i["code"] == "gate_loads_admitted")
        assert "OS-9" in admitted["detail"]

    # 4. Rule 12: the concept allows one delivery per site hour; the approved one above holds 10:00.
    async with world.factory() as s:
        await LogisticsPlanService(s).put_concept(pid, {"max_deliveries_per_hour": 1}, world.manager)
        await s.commit()
    async with world.factory() as s:
        legacy = SiteLogisticsService(s)
        same_hour = _booking(pid, other_gate.id, _utc(day, 4, 45), _utc(day, 5, 15), status="approved")  # 10:15 on site
        assert (await _refused(legacy.create_delivery(same_hour, str(world.manager)))).startswith(
            "delivery_rate_exceeded"
        )
        # 05:30 UTC is 11:00 on site: the next site hour, although it is the same UTC hour as 05:00.
        next_hour = _booking(pid, other_gate.id, _utc(day, 5, 30), _utc(day, 5, 50), status="approved")
        assert (await legacy.create_delivery(next_hour, str(world.manager))).status == "approved"

    # 5. A project whose site has no time zone: nothing is compared on a guessed clock.
    async with world.factory() as s:
        clockless = await add_project(s, world.manager, [])
        gate2 = await _gate(s, clockless, "Only")
        s.add(
            m.DeliveryBooking(
                project_id=clockless,
                gate_id=gate2.id,
                supplier_name="Booked before the zone was required",
                window_start=_utc(day, 8),
                window_end=_utc(day, 9),
                status="approved",
            )
        )
        await s.commit()
    async with world.factory() as s:
        legacy = SiteLogisticsService(s)
        # The site keeps booking: the opening hours are not compared, on no clock at all.
        booked = await legacy.create_delivery(
            _booking(clockless, gate2.id, _utc(day, 22), _utc(day, 23)), str(world.manager)
        )
        assert [w["code"] for w in await legacy.delivery_warnings(booked)] == ["gate_hours_unchecked"]
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        findings = await svc.findings(clockless)
        assert [f["code"] for f in findings].count("gate_hours_unchecked") == 1
        assert findings[0]["severity"] == "warning"
        assert "site_timezone_missing" not in [f["code"] for f in findings]
        report = await svc.validate(clockless)
        failed = {r["rule_id"] for r in report["results"] if not r["passed"]}
        assert "site_logistics.gate_hours_checked" in failed
        assert "site_logistics.site_timezone_set" not in failed
        with pytest.raises(LogisticsError) as exc:
            await svc.put_concept(clockless, {"site_timezone": "Mars/Olympus"}, world.manager)
        assert (exc.value.code, exc.value.status_code) == ("timezone_invalid", 422)
        await svc.put_concept(clockless, {"site_timezone": "Europe/Berlin"}, world.manager)
        await s.commit()
    async with world.factory() as s:
        codes = [f["code"] for f in await LogisticsPlanService(s).findings(clockless)]
        assert "site_timezone_missing" not in codes and "gate_hours_unchecked" not in codes


# ── arrivals, frozen records and first writes that race ────────────────────


async def test_arrivals_frozen_records_and_racing_first_writes(world: World) -> None:
    from app.modules.procurement.models import GoodsReceipt, PurchaseOrder

    pid = world.project_id
    start, end = window(1, 9, 1)
    async with world.factory() as s:
        po = PurchaseOrder(project_id=pid, po_number="PO-1")
        s.add(po)
        await s.flush()
        svc = LogisticsPlanService(s)
        today = await svc.site_today(pid)
        transport = await svc.create_transport(
            pid,
            {
                "direction": "inbound",
                "transport_kind": "inbound_delivery",
                "title": "Second shipment of the order",
                "po_id": po.id,
                "planned_window_start": start,
                "planned_window_end": end,
            },
            world.manager,
        )
        # An earlier shipment of the same order was received last week.
        s.add(GoodsReceipt(po_id=po.id, receipt_date=(today - timedelta(days=7)).isoformat(), status="confirmed"))
        await svc.transition_transport(pid, transport.id, "scheduled", world.manager)
        # Same state again and a state that does not follow are both refused, not absorbed.
        for target in ("scheduled", "arrived"):
            with pytest.raises(LogisticsError) as exc:
                await svc.transition_transport(pid, transport.id, target, world.manager)
            assert (exc.value.code, exc.value.status_code) == ("invalid_transition", 409), target
        await svc.transition_transport(pid, transport.id, "in_transit", world.manager)
        assert transport.in_transit_on == today
        assert transport.arrived_on is None
        assert await svc.sync_arrivals(pid) == 0, "last week's receipt is not this transport's arrival"
        # Under way: what the rules were checked against no longer moves, the notes still do.
        with pytest.raises(LogisticsError) as exc:
            await svc.update_transport(pid, transport.id, {"gross_weight_t": Decimal("99")}, world.manager)
        assert exc.value.code == "transport_under_way"
        await svc.update_transport(pid, transport.id, {"route_notes": "Via the ring road"}, world.manager)
        # A non-nullable field is not cleared by sending null.
        with pytest.raises(LogisticsError) as exc:
            await svc.update_transport(pid, transport.id, {"title": None}, world.manager)
        assert (exc.value.code, exc.value.status_code) == ("field_required", 422)
        s.add(GoodsReceipt(po_id=po.id, receipt_date=today.isoformat(), status="draft"))
        await s.flush()
        assert await svc.sync_arrivals(pid) == 0, "a draft receipt is not a receipt"
        s.add(GoodsReceipt(po_id=po.id, receipt_date=today.isoformat(), status="confirmed"))
        await s.flush()
        assert await svc.sync_arrivals(pid) == 1
        assert (transport.state, transport.arrived_on) == ("arrived", today)
        assert await svc.sync_arrivals(pid) == 0
        stage = (await svc.stages(pid))[0]
        await s.commit()

    # A closed complaint is a record: it is not edited or moved again.
    async with world.factory() as s:
        svc = LogisticsPlanService(s)
        complaint = await svc.create_complaint(
            pid, {"kind": "noise", "description": "Early pump", "response": "Pump moved to nine."}, world.manager
        )
        for target in ("acknowledged", "action_taken", "closed"):
            await svc.transition_complaint(pid, complaint.id, target, world.manager)
        with pytest.raises(LogisticsError) as exc:
            await svc.update_complaint(pid, complaint.id, {"description": "Rewritten"}, world.manager)
        assert (exc.value.code, exc.value.status_code) == ("complaint_closed", 409)
        with pytest.raises(LogisticsError) as exc:
            await svc.transition_complaint(pid, complaint.id, "closed", world.manager)
        assert exc.value.status_code == 409
        await s.commit()

    # Two saves of one plant position at once end in one demand row.
    position = uuid.uuid4()

    async def save(kva: str) -> None:
        async with world.factory() as session:
            await LogisticsPlanService(session).sync_plant_power_demand(
                pid,
                site_plant_position_id=position,
                power_demand_kva=Decimal(kva),
                stage_id=stage.id,
                consumer="Tower crane",
                actor_id=world.manager,
                trusted=True,
            )
            await session.commit()

    await asyncio.gather(save("120"), save("140"))
    async with world.factory() as s:
        rows = (
            (await s.execute(sa.select(m.MediaDemand).where(m.MediaDemand.site_plant_position_id == position)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].peak_demand in (Decimal("120"), Decimal("140"))
        # The index itself refuses a second row, whatever the service does.
        s.add(
            m.MediaDemand(
                project_id=pid,
                stage_id=stage.id,
                media_kind="power",
                consumer="Duplicate",
                peak_demand=Decimal("1"),
                site_plant_position_id=position,
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            await s.flush()
        await s.rollback()

    # Two first writes on a project without a plan end in one concept and one initial stage.
    async with world.factory() as s:
        fresh = await add_project(s, world.manager, [])
        await s.commit()

    async def first_write(text: str) -> None:
        async with world.factory() as session:
            await LogisticsPlanService(session).put_concept(fresh, {"rules_text": text}, world.manager)
            await session.commit()

    await asyncio.gather(first_write("a"), first_write("b"))
    async with world.factory() as s:
        assert await _count(s, m.LogisticsConcept, fresh) == 1
        assert await _count(s, m.ExpansionStage, fresh) == 1


# ── gate evidence from catalogue tags ──────────────────────────────────────


async def test_gate_evidence_is_placed_by_catalogue_tags() -> None:
    from app.modules.project_governance.evidence import GateAttempt, collect_evidence
    from app.modules.project_governance.public import project_areas
    from app.modules.project_governance.service import GovernanceService
    from app.modules.site_logistics.evidence import PROVIDER, logistics_readiness, register_gate_evidence
    from tests.pg import governance_fixtures as gov

    register_site_logistics_permissions()
    register_gate_evidence()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await gov.build_world(factory)  # the neutral phase model
        async with factory() as s:
            framework = await add_project(s, w.manager, [])
            await GovernanceService(s).set_model(
                framework,
                source="shipped",
                catalogue_id="elf_module_framework",
                version=None,
                four_eyes=True,
                actor_id=w.manager,
                tenant_id=str(w.manager),
            )
            await s.commit()

        def attempt(code: str) -> GateAttempt:
            return GateAttempt(gate_id=uuid.uuid4(), gate_code=code, attempt_no=1)

        placed_at = {}
        for pid in (framework, w.project_id):
            async with factory() as s:
                svc = LogisticsPlanService(s)
                placed = await svc.governance_target(pid)
                assert placed.reason is None, placed
                placed_at[pid] = placed.area_code
                areas = await project_areas(s, pid)
                hosting_area = next(a for a in areas if a.code == placed.area_code)
                other_area = next(a for a in areas if a.code != placed.area_code)
                gate_code = placed.gate_codes[0]

                # No plan content: the provider says nothing, so an unopened plan blocks no gate.
                assert await logistics_readiness(s, pid, attempt(gate_code), hosting_area) == []
                await svc.put_concept(pid, {"site_timezone": "Europe/Berlin"}, w.manager)
                assert await logistics_readiness(s, pid, attempt(gate_code), hosting_area) == []

                await svc.put_concept(pid, {"rules_text": "Book 48 hours ahead."}, w.manager)
                items = await logistics_readiness(s, pid, attempt(gate_code), hosting_area)
                assert {i.code for i in items} >= {"site_logistics:no_errors", "site_logistics:balance_closed"}
                assert "not_met" in {i.state for i in items}
                assert all(i.label_key and i.label_key.startswith("site_logistics.evidence.") for i in items)
                # Only its own area, only its own gates.
                assert await logistics_readiness(s, pid, attempt(gate_code), other_area) == []
                assert await logistics_readiness(s, pid, attempt("no_such_gate"), hosting_area) == []
                collected = await collect_evidence(s, pid, attempt(gate_code), list(areas))
                mine = [c for c in collected if c.provider == PROVIDER]
                assert mine and {c.area_code for c in mine} == {placed.area_code}
                assert all(c.blocking for c in mine)
                readiness = await svc.readiness(pid)
                assert (readiness["area"], readiness["gates"], readiness["governance"]) == (
                    placed.area_code,
                    list(placed.gate_codes),
                    None,
                )
                assert readiness["frame_doc_type"] == placed.frame_doc_type
                assert readiness["gates_in_use"] is True
                exported = next(i for i in readiness["items"] if i["code"] == "concept_saved_and_exported")
                # Saved, and the frame document of this project has no revision bound yet.
                assert (exported["state"], exported["detail"]) == ("not_met", "not_exported")
                await s.commit()
        # Two phase models, two different areas, no code named in the module.
        assert placed_at[framework] != placed_at[w.project_id]
