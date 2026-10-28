# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plant register rules on PostgreSQL: what a state is read from, what money binds on, what stays true.

Each test pins a way the register once said something its sources did not:
``ordered`` after the order was cancelled, a slot held on a made-up commitment
id, a catalogue of another tenant pinned, limits removed after the route was
set, a long-lead item with no need date counted as secured.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit_log import ActivityLog
from app.modules.plant_register.catalogue import PLANT_KIND, shipped_default
from app.modules.plant_register.errors import PlantError
from app.modules.plant_register.models import (
    DecisionPaper,
    DeliveryLimit,
    PlantItem,
    PlantSettings,
    SlotReservation,
    SparePartRequirement,
)
from app.modules.plant_register.ports import (
    CommitmentRef,
    register_commitment_provider,
    unregister_commitment_provider,
    unregister_package_plan_provider,
)
from app.modules.plant_register.service import PlantService
from tests._pg import isolated_engine
from tests.pg.plant_fixtures import World, build_world, get, item, quote, view

TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio


@dataclass
class FakeCommitments:
    """The commitment release port: it answers only for ids it was given, per project."""

    refs: dict[tuple[uuid.UUID, uuid.UUID], CommitmentRef] = field(default_factory=dict)

    async def get_commitment(self, session: Any, project_id: uuid.UUID, commitment_item_id: uuid.UUID):
        return self.refs.get((project_id, commitment_item_id))

    def add(self, project_id: uuid.UUID, **kw: Any) -> uuid.UUID:
        cid = uuid.uuid4()
        self.refs[(project_id, cid)] = CommitmentRef(cid, **kw)
        return cid


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)
    unregister_package_plan_provider()
    unregister_commitment_provider()


async def _do(w: World, fn):
    async with w.factory() as s:
        out = await fn(PlantService(s))
        await s.commit()
        return out


async def _refused(w: World, fn) -> tuple[str, list[str], str | None]:
    with pytest.raises(PlantError) as exc:
        await _do(w, fn)
    return exc.value.code, [v["code"] for v in exc.value.violations], exc.value.detail


def _steps() -> list[str]:
    return list(shipped_default().step_codes())


async def _route_set(w: World, code: str = "PL-1", cls: str = "lift", **extra: Any) -> uuid.UUID:
    """A non-critical item taken to ``route_set`` the way the rules allow it."""
    iid = await item(w, code, cls, **extra)
    await quote(w, iid)
    for target in ("specified", "enquired"):
        await _do(w, lambda svc, t=target: svc.transition_item(w.project_id, iid, t, actor_id=w.manager, today=TODAY))
    await _do(
        w,
        lambda svc: svc.set_route(
            w.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=w.supplier_pkg,
            actor_id=w.manager,
        ),
    )
    await _do(
        w,
        lambda svc: svc.put_limits(
            w.project_id, iid, [{"step": s, "party": "contractor"} for s in _steps()], actor_id=w.manager
        ),
    )
    await _do(w, lambda svc: svc.transition_item(w.project_id, iid, "route_set", actor_id=w.manager, today=TODAY))
    return iid


async def _purchase_order(w: World, status: str = "issued") -> uuid.UUID:
    from app.modules.procurement.models import PurchaseOrder

    async with w.factory() as s:
        po = PurchaseOrder(project_id=w.project_id, po_number=f"PO-{uuid.uuid4().hex[:8]}", status=status)
        s.add(po)
        await s.commit()
        return po.id


async def _set_po(w: World, po_id: uuid.UUID, status: str) -> None:
    from app.modules.procurement.models import PurchaseOrder

    async with w.factory() as s:
        (await s.get(PurchaseOrder, po_id)).status = status
        await s.commit()


async def _status(w: World, iid: uuid.UUID) -> str:
    return (await get(w, PlantItem, iid)).status


async def _moves(w: World, iid: uuid.UUID) -> list[tuple[str | None, str | None]]:
    async with w.factory() as s:
        rows = await s.execute(
            select(ActivityLog.from_status, ActivityLog.to_status)
            .where(ActivityLog.entity_id == str(iid), ActivityLog.to_status.is_not(None))
            .order_by(ActivityLog.created_at, ActivityLog.id)
        )
        return [(r.from_status, r.to_status) for r in rows if r.from_status is not None]


# ── rule 11: the state is read, in both directions ────────────────────────


async def test_an_order_that_is_cancelled_or_unlinked_takes_the_item_back(world: World) -> None:
    from app.modules.plant_register.events import handle_po_event

    iid = await _route_set(world)
    po = await _purchase_order(world, "issued")
    # Linking the order reads the state at once.
    await _do(
        world, lambda svc: svc.update_item(world.project_id, iid, {"purchase_order_id": po}, actor_id=world.manager)
    )
    assert await _status(world, iid) == "ordered"
    assert (await view(world, iid))["order_status"] == "ok"

    # A goods receipt completes the order; the real event name and payload key move the item.
    await _set_po(world, po, "completed")
    await handle_po_event({"gr_id": str(uuid.uuid4()), "po_id": str(po)}, session_factory=world.factory)
    assert await _status(world, iid) == "delivered"

    await _set_po(world, po, "cancelled")
    await handle_po_event({"po_id": str(po)}, session_factory=world.factory)
    assert await _status(world, iid) == "route_set"

    await _set_po(world, po, "issued")
    await _do(world, lambda svc: svc.sync_item_state(world.project_id, iid, actor_id=world.manager))
    assert await _status(world, iid) == "ordered"
    await _do(
        world, lambda svc: svc.update_item(world.project_id, iid, {"purchase_order_id": None}, actor_id=world.manager)
    )
    assert await _status(world, iid) == "route_set"

    # Every move went through the state machine and left exactly one audit row.
    assert (await _moves(world, iid))[-5:] == [
        ("route_set", "ordered"),
        ("ordered", "delivered"),
        ("delivered", "route_set"),
        ("route_set", "ordered"),
        ("ordered", "route_set"),
    ]


async def test_manufactured_stands_while_an_order_supports_it(world: World) -> None:
    iid = await _route_set(world)
    po = await _purchase_order(world, "issued")
    await _do(
        world, lambda svc: svc.update_item(world.project_id, iid, {"purchase_order_id": po}, actor_id=world.manager)
    )
    await _do(
        world,
        lambda svc: svc.transition_item(world.project_id, iid, "manufactured", actor_id=world.manager, today=TODAY),
    )
    await _do(world, lambda svc: svc.sync_item_state(world.project_id, iid, actor_id=None))
    assert await _status(world, iid) == "manufactured"
    await _set_po(world, po, "cancelled")
    await _do(world, lambda svc: svc.sync_item_state(world.project_id, iid, actor_id=None))
    assert await _status(world, iid) == "route_set"


async def test_a_jump_read_from_the_owner_furnished_item_is_a_real_transition(world: World) -> None:
    iid = await item(world, cls="lift")
    await _do(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="owner_furnished_contractor_installed",
            contract_package_id=world.installer_pkg,
            actor_id=world.manager,
        ),
    )
    await quote(world, iid)
    for target in ("specified", "enquired"):
        await _do(
            world,
            lambda svc, t=target: svc.transition_item(world.project_id, iid, t, actor_id=world.manager, today=TODAY),
        )
    await _do(
        world,
        lambda svc: svc.put_limits(
            world.project_id, iid, [{"step": s, "party": "contractor"} for s in _steps()], actor_id=world.manager
        ),
    )
    await _do(
        world, lambda svc: svc.transition_item(world.project_id, iid, "route_set", actor_id=world.manager, today=TODAY)
    )
    row = await get(world, PlantItem, iid)
    world.provider.set_progress(row.owner_furnished_item_id, "installed")
    await _do(world, lambda svc: svc.sync_item_state(world.project_id, iid, actor_id=world.manager))
    assert await _status(world, iid) == "installed"
    assert (await _moves(world, iid))[-1] == ("route_set", "installed")


async def test_a_delivered_order_with_a_commissioned_system_reads_commissioned(world: World) -> None:
    from app.modules.commissioning.models import CxSystem

    iid = await _route_set(world)
    po = await _purchase_order(world, "completed")
    async with world.factory() as s:
        cx = CxSystem(project_id=world.project_id, name="Lifts", status="commissioned")
        s.add(cx)
        await s.commit()
        cx_id = cx.id
    await _do(
        world,
        lambda svc: svc.update_item(
            world.project_id, iid, {"purchase_order_id": po, "cx_system_id": cx_id}, actor_id=world.manager
        ),
    )
    assert await _status(world, iid) == "commissioned"
    # Commissioning without anything on site is not read.
    await _set_po(world, po, "draft")
    await _do(world, lambda svc: svc.sync_item_state(world.project_id, iid, actor_id=None))
    assert await _status(world, iid) == "route_set"


async def test_an_item_before_route_set_or_after_handover_is_not_read(world: World) -> None:
    iid = await item(world, cls="lift")
    po = await _purchase_order(world, "completed")
    await _do(
        world, lambda svc: svc.update_item(world.project_id, iid, {"purchase_order_id": po}, actor_id=world.manager)
    )
    assert await _status(world, iid) == "identified"


# ── rule 13: a fee binds money only through a released commitment ─────────


async def _fee_slot(w: World, iid: uuid.UUID, **kw: Any) -> SlotReservation:
    data = {
        "reservation_fee": Decimal("25000.00"),
        "currency": "EUR",
        "fee_refundable": "none",
        "convert_by_date": date(2026, 10, 20),
        **kw,
    }
    return await _do(w, lambda svc: svc.create_slot(w.project_id, iid, data, actor_id=w.manager))


async def test_a_fee_slot_cannot_be_held_while_nobody_can_confirm_the_commitment(world: World) -> None:
    iid = await item(world, cls="power_transformer")
    slot = await _fee_slot(world, iid)
    hold = lambda svc: svc.transition_slot(world.project_id, iid, slot.id, "held", actor_id=world.manager)  # noqa: E731
    assert (await _refused(world, hold))[0] == "slot_fee_needs_commitment"
    # No commitment module: an id cannot even be stored, let alone satisfy the rule.
    code, _, _ = await _refused(
        world,
        lambda svc: svc.update_slot(
            world.project_id, iid, slot.id, {"commitment_item_id": uuid.uuid4()}, actor_id=world.manager
        ),
    )
    assert code == "commitment_release_unavailable"
    assert (await get(world, SlotReservation, slot.id)).commitment_item_id is None
    # An id that reached the row some other way still does not hold the slot.
    async with world.factory() as s:
        (await s.get(SlotReservation, slot.id)).commitment_item_id = uuid.uuid4()
        await s.commit()
    assert (await _refused(world, hold))[0] == "commitment_release_unavailable"
    assert (await get(world, SlotReservation, slot.id)).status == "requested"


async def test_a_fee_slot_is_held_only_on_a_released_commitment_of_this_project(world: World) -> None:
    commitments = FakeCommitments()
    register_commitment_provider(commitments)
    iid = await item(world, cls="power_transformer")
    slot = await _fee_slot(world, iid)
    link = lambda cid: _do(  # noqa: E731
        world,
        lambda svc: svc.update_slot(
            world.project_id, iid, slot.id, {"commitment_item_id": cid}, actor_id=world.manager
        ),
    )
    hold = lambda svc: svc.transition_slot(world.project_id, iid, slot.id, "held", actor_id=world.manager)  # noqa: E731

    # A made-up id, and a real commitment of another project, are both "not found".
    foreign = commitments.add(uuid.uuid4(), released=True)
    for bad in (uuid.uuid4(), foreign):
        code, _, detail = await _refused(
            world,
            lambda svc, b=bad: svc.update_slot(
                world.project_id, iid, slot.id, {"commitment_item_id": b}, actor_id=world.manager
            ),
        )
        assert (code, detail) == ("link_not_found", "commitment_item_id")

    planned = commitments.add(world.project_id, released=False)
    await link(planned)
    assert (await _refused(world, hold))[0] == "commitment_not_released"

    small = commitments.add(world.project_id, released=True, released_amount=Decimal("1000.00"), currency="EUR")
    await link(small)
    assert (await _refused(world, hold))[0] == "commitment_release_below_fee"

    released = commitments.add(world.project_id, released=True, released_amount=Decimal("25000.00"), currency="EUR")
    await link(released)
    await _do(world, hold)
    assert (await get(world, SlotReservation, slot.id)).status == "held"

    # A held slot keeps meeting its terms: the link cannot be swapped for a weaker one.
    code, _, _ = await _refused(
        world,
        lambda svc: svc.update_slot(
            world.project_id, iid, slot.id, {"commitment_item_id": planned}, actor_id=world.manager
        ),
    )
    assert code == "commitment_not_released"
    assert (await get(world, SlotReservation, slot.id)).commitment_item_id == released


async def test_a_slot_without_a_fee_is_held_without_a_commitment_and_a_fee_needs_its_currency(world: World) -> None:
    iid = await item(world, cls="power_transformer")
    code, _, _ = await _refused(
        world,
        lambda svc: svc.create_slot(
            world.project_id, iid, {"reservation_fee": Decimal("100.00")}, actor_id=world.manager
        ),
    )
    assert code == "fee_needs_currency"
    slot = await _fee_slot(world, iid, reservation_fee=Decimal("0.00"))
    await _do(world, lambda svc: svc.transition_slot(world.project_id, iid, slot.id, "held", actor_id=world.manager))
    assert (await get(world, SlotReservation, slot.id)).status == "held"


# ── the periodic job ──────────────────────────────────────────────────────


async def _notifications(w: World, kind: str) -> list[uuid.UUID]:
    from app.modules.notifications.models import Notification

    async with w.factory() as s:
        rows = await s.execute(select(Notification.user_id).where(Notification.notification_type == f"plant_{kind}"))
        return list(rows.scalars())


async def test_the_periodic_job_expires_slots_notifies_once_a_day_and_reads_sources(world: World) -> None:
    from app.modules.plant_register.sweeper import run_once

    slot_item = await item(world, "PL-SLOT", "power_transformer")
    slot = await _fee_slot(world, slot_item, reservation_fee=Decimal("0.00"))
    await _do(
        world, lambda svc: svc.transition_slot(world.project_id, slot_item, slot.id, "held", actor_id=world.manager)
    )

    # Overdue: needed tomorrow, 44 weeks of lead. Due soon: the order date is three weeks out, after the
    # 44 weeks and the catalogue's order buffers (transport 14, installation 21, approval 14 days), so it is
    # still ahead on the days the sweeps below run.
    late = await item(world, "PL-LATE", "lift", need_date_fixed=TODAY + timedelta(days=1))
    await quote(world, late)
    soon = await item(world, "PL-SOON", "lift", need_date_fixed=TODAY + timedelta(days=44 * 7 + 49 + 21))
    await quote(world, soon)
    gone = await item(world, "PL-GONE", "lift", need_date_fixed=TODAY + timedelta(days=1))
    await quote(world, gone)
    await _do(
        world, lambda svc: svc.transition_item(world.project_id, gone, "cancelled", actor_id=world.manager, today=TODAY)
    )
    views = {
        v["code"]: v["order_status"]
        for v in await _do(world, lambda svc: svc.item_views(world.project_id, today=TODAY))
    }
    assert views == {"PL-SLOT": "ok", "PL-LATE": "overdue", "PL-SOON": "due_soon", "PL-GONE": "ok"}

    ordered = await _route_set(world, "PL-ORD")
    po = await _purchase_order(world, "draft")
    await _do(
        world, lambda svc: svc.update_item(world.project_id, ordered, {"purchase_order_id": po}, actor_id=world.manager)
    )
    await _set_po(world, po, "issued")  # procurement moved; its event was missed

    before = await run_once(today=date(2026, 10, 20), session_factory=world.factory)
    assert before["expired_slots"] == 0  # the deadline day itself is still inside the term
    first = await run_once(today=date(2026, 10, 21), session_factory=world.factory)
    assert first["expired_slots"] == 1
    assert (await get(world, SlotReservation, slot.id)).status == "expired"
    assert await _status(world, ordered) == "ordered"

    # One notice per person and item: the item owner and the area owner are the same user here.
    assert len(await _notifications(world, "slot_expired")) == 1
    overdue_once = await _notifications(world, "order_overdue")
    assert len(overdue_once) >= 1 and set(overdue_once) == {world.area_owner}
    assert len(await _notifications(world, "order_due_soon")) >= 1

    second = await run_once(today=date(2026, 10, 21), session_factory=world.factory)
    assert (second["expired_slots"], second["order_notices"], second["synced_items"]) == (0, 0, 0)
    assert await _notifications(world, "order_overdue") == overdue_once
    assert len(await _notifications(world, "slot_expired")) == 1


async def test_a_cancelled_item_is_never_overdue_and_never_long_lead_open(world: World) -> None:
    iid = await item(world, cls="lift", need_date_fixed=TODAY + timedelta(days=1))
    await quote(world, iid)
    assert (await view(world, iid))["order_status"] == "overdue"
    await _do(
        world, lambda svc: svc.transition_item(world.project_id, iid, "cancelled", actor_id=world.manager, today=TODAY)
    )
    assert (await view(world, iid))["order_status"] == "ok"
    out = await _do(world, lambda svc: svc.escalate(world.project_id, today=TODAY))
    assert out["overdue"] == [] and await _notifications(world, "order_overdue") == []


# ── readiness and gate evidence (SPEC 7) ──────────────────────────────────


@pytest_asyncio.fixture
async def bare_world():
    """A project that does not use gates: no phase model, so no areas, gates or frame documents."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, model=False)
    unregister_package_plan_provider()
    unregister_commitment_provider()


async def test_a_project_without_gates_takes_a_critical_item_from_identified_to_ordered(bare_world: World) -> None:
    """Rule 26: nothing in the register waits for a gate decision or a frame document that cannot come.

    The decision paper is approved by its own approval route, the route is set
    by hand, the order is read from the purchase order. All of it works
    without a phase model, and the readiness read says that no gate is in use.
    """
    from app.modules.plant_register.errors import PlantError as Refused
    from app.modules.plant_register.events import handle_route_event
    from app.modules.plant_register.evidence import plant_readiness
    from app.modules.project_governance.evidence import GateAttempt
    from app.modules.project_governance.public import project_controls

    w = bare_world
    async with w.factory() as s:
        assert (await project_controls(s, w.project_id)).has_model is False
        # Nobody owns an equipment area here, so the register is edited by the holders of the manage right.
        await PlantService(s).require_editor(w.project_id, w.manager, can_manage=True)
        with pytest.raises(Refused) as exc:
            await PlantService(s).require_editor(w.project_id, w.area_owner, can_manage=False)
        assert exc.value.code == "not_equipment_owner"

    iid = await item(w)  # mv_switchgear is critical by default
    await quote(w, iid, set_basis=True)
    for target in ("specified", "enquired"):
        await _do(w, lambda svc, t=target: svc.transition_item(w.project_id, iid, t, actor_id=w.manager, today=TODAY))
    await _do(
        w,
        lambda svc: svc.set_route(
            w.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=w.supplier_pkg,
            actor_id=w.manager,
        ),
    )
    await _do(
        w,
        lambda svc: svc.put_limits(
            w.project_id, iid, [{"step": s, "party": "contractor"} for s in _steps()], actor_id=w.manager
        ),
    )
    # Before the paper is approved the critical item cannot go on, with or without gates.
    code, blockers, _ = await _refused(
        w, lambda svc: svc.transition_item(w.project_id, iid, "route_set", actor_id=w.manager, today=TODAY)
    )
    # A single blocking rule is named by its own code; ``transition_blocked`` stands for several at once.
    assert code == "critical_without_decision" and "critical_without_decision" in blockers

    paper = await _submitted(w, iid, by=w.manager)
    assert paper.status == "submitted"
    await handle_route_event(
        {
            "target_kind": "plant_decision_paper",
            "target_id": str(paper.id),
            "instance_id": str(paper.approval_instance_id),
        },
        decision="approved",
        session_factory=w.factory,
    )
    assert (await get(w, DecisionPaper, paper.id)).status == "approved"

    # The first thing the approval unlocks, then the order.
    await _do(w, lambda svc: svc.transition_item(w.project_id, iid, "route_set", actor_id=w.manager, today=TODAY))
    assert await _status(w, iid) == "route_set"
    po = await _purchase_order(w, "issued")
    await _do(w, lambda svc: svc.update_item(w.project_id, iid, {"purchase_order_id": po}, actor_id=w.manager))
    assert await _status(w, iid) == "ordered"

    r = await _do(w, lambda svc: svc.readiness(w.project_id, today=TODAY))
    assert r["gates_in_use"] is False
    assert (r["frame_document_exists"], r["frame_document_attached"]) == (False, False)
    assert (r["critical_open"], r["long_lead_open"]) == ([], [])
    # No frame document exists to attach here, so it does not hold the register back.
    assert r["ready"] is (not r["error_findings"])
    payload = await _do(w, lambda svc: svc.validation_payload(w.project_id, today=TODAY))
    assert payload["gate_date"] is None
    # And no gate finding: the evidence provider has nothing to say about a project without a model.
    from types import SimpleNamespace

    async with w.factory() as s:
        area = SimpleNamespace(code="m04_equipment", applicable=True)
        attempt = GateAttempt(uuid.uuid4(), "development_to_execution", 1)
        assert await plant_readiness(s, w.project_id, attempt, area) == []


async def test_with_gates_the_readiness_read_says_so_and_still_wants_the_frame_document(world: World) -> None:
    r = await _do(world, lambda svc: svc.readiness(world.project_id, today=TODAY))
    assert r["gates_in_use"] is True
    assert r["frame_document_attached"] is False and r["ready"] is False


async def test_readiness_counts_a_long_lead_item_with_no_need_date_as_open_until_it_is_ordered(world: World) -> None:
    iid = await _route_set(world)  # lift, 44 weeks, no activity and no fixed date
    v = await view(world, iid)
    assert (v["long_lead"], v["latest_order_date"], v["order_status"]) == (True, None, "ok")
    r = await _do(world, lambda svc: svc.readiness(world.project_id, today=TODAY))
    assert r["long_lead_open"] == ["PL-1"] and r["ready"] is False

    po = await _purchase_order(world, "issued")
    await _do(
        world, lambda svc: svc.update_item(world.project_id, iid, {"purchase_order_id": po}, actor_id=world.manager)
    )
    r = await _do(world, lambda svc: svc.readiness(world.project_id, today=TODAY))
    assert r["long_lead_open"] == []


async def _evidence(
    w: World, area_code: str, gate_code: str = "development_to_execution", *, label: bool = False
) -> list[tuple[str, str, str]]:
    from types import SimpleNamespace

    from app.modules.plant_register.evidence import plant_readiness
    from app.modules.project_governance.evidence import GateAttempt

    async with w.factory() as s:
        found = await plant_readiness(
            s, w.project_id, GateAttempt(uuid.uuid4(), gate_code, 1), SimpleNamespace(code=area_code, applicable=True)
        )
    # A reason the reader must understand travels as the label key; ``detail`` carries data only.
    return [
        (e.code, e.state, (e.label_key or "").removeprefix("plant.evidence.") if label else e.detail) for e in found
    ]


async def test_evidence_is_given_for_the_tagged_area_at_the_tagged_gate_and_says_what_is_missing(world: World) -> None:
    from app.modules.plant_register.evidence import PROVIDER_NAME, register_gate_evidence
    from app.modules.project_governance.evidence import evidence_providers
    from tests.pg.governance_fixtures import only_evidence

    # The registry is one per process: registered here, it is put back as it was, so a gate another
    # test decides later is not answered by this module's blocking provider.
    with only_evidence(register=register_gate_evidence):
        reg = next(r for r in evidence_providers() if r.name == PROVIDER_NAME)
        assert (reg.key, reg.blocking) == ("*", True)  # no area code is named anywhere in the module

    assert await _evidence(world, "m04_equipment") == []  # no items: nothing to say
    await item(world)  # critical switchgear, no route, no paper
    assert await _evidence(world, "m04_equipment", "some_other_gate") == []
    assert await _evidence(world, "m01_project_management") == []
    states = {code: state for code, state, _ in await _evidence(world, "m04_equipment")}
    assert states["plant:critical_route_set"] == "not_met"
    assert states["plant:frame_document_attached"] == "not_met"


async def test_evidence_is_met_and_the_register_ready_once_every_condition_holds(world: World) -> None:
    from app.modules.project_governance.models import GovernanceDocument
    from tests.pg.governance_fixtures import add_container

    iid = await _route_set(world, need_date_fixed=date(2028, 6, 1))
    po = await _purchase_order(world, "issued")
    await _do(
        world, lambda svc: svc.update_item(world.project_id, iid, {"purchase_order_id": po}, actor_id=world.manager)
    )
    before = await _do(world, lambda svc: svc.readiness(world.project_id, today=TODAY))
    assert before["error_findings"] == [] and before["critical_open"] == [] and before["long_lead_open"] == []
    assert (before["frame_document_attached"], before["ready"]) == (False, False)

    async with world.factory() as s:
        container = await add_container(s, world.project_id, "frame")
        docs = (
            await s.execute(
                select(GovernanceDocument).where(
                    GovernanceDocument.project_id == world.project_id,
                    GovernanceDocument.doc_type == "m04_equipment_frame",
                )
            )
        ).scalars()
        for doc in docs:
            doc.container_id = container
        await s.commit()
    after = await _do(world, lambda svc: svc.readiness(world.project_id, today=TODAY))
    assert after["ready"] is True
    assert {state for _, state, _ in await _evidence(world, "m04_equipment")} == {"met"}


@contextmanager
def _host_read_as(host):
    """Stand in for the governance read port: what a model with other (or no) tags would answer."""
    from app.modules.plant_register import hosting

    real = hosting.project_host

    async def answer(session, project_id):
        return host

    hosting.project_host = answer
    try:
        yield
    finally:
        hosting.project_host = real


async def test_the_shipped_model_says_where_plant_sits(world: World) -> None:
    from app.modules.plant_register.hosting import PlantHost, project_host

    async with world.factory() as s:
        host = await project_host(s, world.project_id)
        nowhere = await project_host(s, uuid.uuid4())
    assert host == PlantHost(
        "m04_equipment", ("m04_equipment_frame",), ("development_to_execution",), host.first_area_code
    )
    assert nowhere is None


async def test_evidence_is_unknown_with_a_reason_when_the_model_does_not_say_where_plant_sits(world: World) -> None:
    from app.modules.plant_register.hosting import PlantHost

    await item(world)
    with _host_read_as(PlantHost(first_area_code="m01_project_management")):
        first = await _evidence(world, "m01_project_management", label=True)
        elsewhere = await _evidence(world, "m04_equipment")
        # Nobody owns the register then: only a holder of the manage permission edits it.
        code, _, _ = await _refused(
            world, lambda svc: svc.require_editor(world.project_id, world.area_owner, can_manage=False)
        )
    assert first == [("plant:host_unresolved", "unknown", "no_area_hosts_plant")] and elsewhere == []
    assert code == "not_equipment_owner"

    with _host_read_as(PlantHost("m04_equipment", ("m04_equipment_frame",), (), "m01_project_management")):
        no_gate = await _evidence(world, "m04_equipment", label=True)
    assert no_gate == [("plant:host_unresolved", "unknown", "no_phase_enables_construction_start")]

    # The model names the document type, but this project has no such document row.
    from app.modules.project_governance.models import GovernanceDocument

    async with world.factory() as s:
        rows = await s.execute(select(GovernanceDocument).where(GovernanceDocument.project_id == world.project_id))
        for doc in rows.scalars():
            if doc.doc_type == "m04_equipment_frame":
                await s.delete(doc)
        await s.commit()
    no_row = {code: (state, label) for code, state, label in await _evidence(world, "m04_equipment", label=True)}
    assert no_row["plant:frame_document_attached"] == ("unknown", "frame_document_missing")
    raw = {code: detail for code, _, detail in await _evidence(world, "m04_equipment")}
    assert raw["plant:frame_document_attached"] == ""  # no code that stands for a sentence in the shown detail


# ── the catalogue a project pins ──────────────────────────────────────────


async def _tenant_catalogue(w: World, tenant: uuid.UUID, code: str) -> uuid.UUID:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    async with w.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            str(tenant),
            code=code,
            name="Own plant catalogue",
            based_on_source="shipped",
            based_on_id="neutral",
            based_on_version=None,
            actor_id=tenant,
            kind=PLANT_KIND,
        )
        await store.publish(str(tenant), row.id, actor_id=tenant)
        await s.commit()
        return row.id


async def test_a_tenant_catalogue_is_pinned_only_by_its_tenant_and_not_once_retired(world: World) -> None:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    theirs = await _tenant_catalogue(world, world.outsider, "theirs")
    mine = await _tenant_catalogue(world, world.manager, "mine")

    def pin(cid: uuid.UUID):
        return lambda svc: svc.pin_catalogue(
            world.project_id,
            tenant_id=str(world.manager),
            source="tenant",
            catalogue_id=str(cid),
            version=None,
            actor_id=world.manager,
        )

    assert (await _refused(world, pin(theirs)))[0] == "unknown_catalogue"
    assert await get_settings(world) is None
    row = await _do(world, pin(mine))
    assert (row.catalogue_source, row.catalogue_id, row.catalogue_version) == ("tenant", str(mine), 1)

    async with world.factory() as s:
        await CatalogueStore(s).retire(str(world.manager), mine)
        await s.commit()
    code, _, _ = await _refused(world, pin(mine))
    assert code == "catalogue_retired"


async def get_settings(w: World) -> PlantSettings | None:
    async with w.factory() as s:
        return (
            await s.execute(select(PlantSettings).where(PlantSettings.project_id == w.project_id))
        ).scalar_one_or_none()


async def test_the_first_item_pins_the_catalogue_version_the_project_keeps(world: World) -> None:
    assert await get_settings(world) is None
    await item(world)
    row = await get_settings(world)
    assert row is not None
    assert (row.catalogue_source, row.catalogue_id, row.catalogue_version) == (
        "shipped",
        "neutral",
        shipped_default().version,
    )
    await item(world, "PL-2")
    async with world.factory() as s:
        count = await s.scalar(
            select(func.count()).select_from(PlantSettings).where(PlantSettings.project_id == world.project_id)
        )
    assert count == 1


# ── links must resolve inside the project ─────────────────────────────────


async def test_the_item_owner_must_be_someone_who_can_see_the_project(world: World) -> None:
    iid = await item(world)
    for stranger in (world.outsider, uuid.uuid4()):
        code, _, detail = await _refused(
            world,
            lambda svc, u=stranger: svc.update_item(
                world.project_id, iid, {"owner_user_id": u}, actor_id=world.manager
            ),
        )
        assert (code, detail) == ("link_not_found", "owner_user_id")
    await _do(
        world,
        lambda svc: svc.update_item(world.project_id, iid, {"owner_user_id": world.editor}, actor_id=world.manager),
    )
    assert (await get(world, PlantItem, iid)).owner_user_id == world.editor


@pytest.mark.parametrize(
    "field_name", ["vendor_id", "wbs_id", "boq_position_id", "purchase_order_id", "submittal_id", "cx_system_id"]
)
async def test_a_dangling_item_link_is_refused(world: World, field_name: str) -> None:
    iid = await item(world)
    code, _, detail = await _refused(
        world,
        lambda svc: svc.update_item(world.project_id, iid, {field_name: uuid.uuid4()}, actor_id=world.manager),
    )
    assert (code, detail) == ("link_not_found", field_name)
    assert getattr(await get(world, PlantItem, iid), field_name) is None


async def test_links_of_quotes_papers_spares_and_services_are_checked(world: World) -> None:
    iid = await item(world)
    other = await item(world, "PL-2")
    foreign_quote = await quote(world, other)
    stray = uuid.uuid4()

    code, _, detail = await _refused(
        world,
        lambda svc: svc.add_quote(
            world.project_id,
            iid,
            {
                "source": "supplier_quote",
                "enquiry_date": date(2026, 8, 3),
                "lead_weeks_min": 1,
                "lead_weeks_max": 2,
                "vendor_id": stray,
            },
            actor_id=world.manager,
            today=TODAY,
        ),
    )
    assert (code, detail) == ("link_not_found", "vendor_id")
    code, _, detail = await _refused(
        world,
        lambda svc: svc.add_quote(
            world.project_id,
            iid,
            {
                "source": "supplier_catalogue",
                "enquiry_date": date(2026, 8, 3),
                "lead_weeks_min": 1,
                "lead_weeks_max": 2,
                "catalogue_entry_id": stray,
            },
            actor_id=world.manager,
            today=TODAY,
        ),
    )
    assert (code, detail) == ("link_not_found", "catalogue_entry_id")

    paper = {"options": [{"code": "a", "quote_id": str(foreign_quote.id)}, {"code": "b"}]}
    code, _, detail = await _refused(
        world, lambda svc: svc.create_paper(world.project_id, iid, paper, actor_id=world.manager)
    )
    assert (code, detail) == ("link_not_found", "options.quote_id")
    paper = {"options": [{"code": "a", "vendor_id": str(stray)}, {"code": "b"}]}
    code, _, detail = await _refused(
        world, lambda svc: svc.create_paper(world.project_id, iid, paper, actor_id=world.manager)
    )
    assert (code, detail) == ("link_not_found", "options.vendor_id")

    code, _, _ = await _refused(
        world,
        lambda svc: svc.create_spare(
            world.project_id, iid, {"category": "special_tools", "supply_package_id": stray}, actor_id=world.manager
        ),
    )
    assert code == "package_not_found"
    code, _, detail = await _refused(
        world,
        lambda svc: svc.create_it_service(
            world.project_id, {"kind": "site_network", "needed_from_activity_id": stray}, actor_id=world.manager
        ),
    )
    assert (code, detail) == ("link_not_found", "needed_from_activity_id")
    code, _, detail = await _refused(
        world,
        lambda svc: svc.create_slot(world.project_id, iid, {"vendor_id": stray}, actor_id=world.manager),
    )
    assert (code, detail) == ("link_not_found", "vendor_id")


async def test_a_quote_from_a_supplier_catalogue_carries_the_entry_lead_time(world: World) -> None:
    from app.modules.supplier_catalogs.models import CatalogEntry, CatalogItem, PriceList, Vendor

    async with world.factory() as s:
        vendor = Vendor(code=f"V-{uuid.uuid4().hex[:6]}", name="Catalogue vendor")
        part = CatalogItem(sku=f"S-{uuid.uuid4().hex[:6]}", name="Lift car")
        s.add_all([vendor, part])
        await s.flush()
        prices = PriceList(vendor_id=vendor.id, name="2026")
        s.add(prices)
        await s.flush()
        entry = CatalogEntry(price_list_id=prices.id, catalog_item_id=part.id, lead_time_days=100)
        s.add(entry)
        await s.commit()
        entry_id, vendor_id = entry.id, vendor.id
    iid = await item(world, cls="lift")

    def add(lo: int, hi: int):
        return lambda svc: svc.add_quote(
            world.project_id,
            iid,
            {
                "source": "supplier_catalogue",
                "enquiry_date": date(2026, 8, 3),
                "lead_weeks_min": lo,
                "lead_weeks_max": hi,
                "catalogue_entry_id": entry_id,
                "vendor_id": vendor_id,
            },
            actor_id=world.manager,
            today=TODAY,
        )

    # 100 days are 15 weeks, rounded up: a range that leaves them out contradicts its source.
    assert (await _refused(world, add(2, 10)))[0] == "catalogue_lead_mismatch"
    assert (await _refused(world, add(16, 20)))[0] == "catalogue_lead_mismatch"
    q = await _do(world, add(14, 15))
    assert (q.catalogue_entry_id, q.vendor_id) == (entry_id, vendor_id)


async def test_a_package_id_is_not_stored_while_no_plan_can_confirm_it(world: World) -> None:
    unregister_package_plan_provider()
    iid = await item(world, cls="lift")
    stray = uuid.uuid4()
    code, _, _ = await _refused(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=stray,
            actor_id=world.manager,
        ),
    )
    assert code == "package_plan_unavailable"
    code, _, _ = await _refused(
        world,
        lambda svc: svc.put_limits(
            world.project_id, iid, [{"step": "supply", "contract_package_id": stray}], actor_id=world.manager
        ),
    )
    assert code == "package_plan_unavailable"
    row = await get(world, PlantItem, iid)
    assert (row.procurement_route, row.contract_package_id) == (None, None)
    # A party code needs no plan.
    await _do(
        world,
        lambda svc: svc.put_limits(
            world.project_id, iid, [{"step": "supply", "party": "supplier"}], actor_id=world.manager
        ),
    )


# ── what a gate let through cannot be taken apart afterwards ──────────────


async def test_delivery_limits_cannot_be_emptied_after_the_route_is_set(world: World) -> None:
    iid = await _route_set(world)
    code, blockers, _ = await _refused(
        world, lambda svc: svc.put_limits(world.project_id, iid, [], actor_id=world.manager)
    )
    assert code == "delivery_limit_gap"
    async with world.factory() as s:
        kept = await s.scalar(select(func.count()).select_from(DeliveryLimit).where(DeliveryLimit.plant_item_id == iid))
    assert kept == len(_steps())
    # Reassigning every step is still an edit.
    await _do(
        world,
        lambda svc: svc.put_limits(
            world.project_id, iid, [{"step": s, "party": "supplier"} for s in _steps()], actor_id=world.manager
        ),
    )


async def test_route_set_is_blocked_by_a_limit_gap_and_by_a_stale_quote_on_a_critical_item(world: World) -> None:
    iid = await item(world)  # mv_switchgear: critical, main component
    await quote(world, iid)
    for target in ("specified", "enquired"):
        await _do(
            world,
            lambda svc, t=target: svc.transition_item(world.project_id, iid, t, actor_id=world.manager, today=TODAY),
        )
    await _do(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=world.supplier_pkg,
            actor_id=world.manager,
        ),
    )
    later = TODAY + timedelta(days=120)  # the quote answered on 2026-08-03 is past its 90 days
    code, blockers, _ = await _refused(
        world, lambda svc: svc.transition_item(world.project_id, iid, "route_set", actor_id=world.manager, today=later)
    )
    assert code == "transition_blocked"
    assert {"lead_time_stale", "delivery_limit_gap", "critical_without_decision"} <= set(blockers)
    _, fresh, _ = await _refused(
        world, lambda svc: svc.transition_item(world.project_id, iid, "route_set", actor_id=world.manager, today=TODAY)
    )
    assert "lead_time_stale" not in fresh


async def test_the_last_strategic_spare_of_a_critical_item_stays_once_the_route_is_set(world: World) -> None:
    iid = await item(world)  # critical
    spare = await _do(
        world,
        lambda svc: svc.create_spare(world.project_id, iid, {"category": "strategic_spares"}, actor_id=world.manager),
    )
    tools = await _do(
        world,
        lambda svc: svc.create_spare(world.project_id, iid, {"category": "special_tools"}, actor_id=world.manager),
    )
    assert (await view(world, iid))["strategic_spares_ok"] is True
    async with world.factory() as s:  # the route was set on these spares
        (await s.get(PlantItem, iid)).status = "route_set"
        await s.commit()
    delete = lambda sid: lambda svc: svc.delete_spare(world.project_id, iid, sid, actor_id=world.manager)  # noqa: E731
    assert (await _refused(world, delete(spare.id)))[0] == "critical_without_strategic_spares"
    code, _, _ = await _refused(
        world,
        lambda svc: svc.update_spare(
            world.project_id, iid, spare.id, {"category": "special_tools"}, actor_id=world.manager
        ),
    )
    assert code == "critical_without_strategic_spares"
    assert (await get(world, SparePartRequirement, spare.id)).category == "strategic_spares"
    await _do(world, delete(tools.id))


async def test_classification_overrides_need_the_manage_permission_and_freeze_with_the_route(world: World) -> None:
    iid = await item(world)  # critical by class
    override = {"critical_override": False, "critical_reason": "Standard panel, three suppliers in stock"}
    code, _, _ = await _refused(
        world, lambda svc: svc.update_item(world.project_id, iid, override, actor_id=world.area_owner)
    )
    assert code == "manage_required"
    assert (await view(world, iid))["critical"] is True
    code, _, _ = await _refused(
        world,
        lambda svc: svc.create_item(
            world.project_id,
            {"code": "PL-X", "title": "X", "component_class_code": "mv_switchgear", **override},
            actor_id=world.area_owner,
        ),
    )
    assert code == "manage_required"
    await _do(
        world,
        lambda svc: svc.update_item(world.project_id, iid, override, actor_id=world.manager, can_manage=True),
    )
    assert (await view(world, iid))["critical"] is False
    async with world.factory() as s:
        (await s.get(PlantItem, iid)).status = "route_set"
        await s.commit()
    code, _, _ = await _refused(
        world,
        lambda svc: svc.update_item(
            world.project_id, iid, {"critical_override": None}, actor_id=world.manager, can_manage=True
        ),
    )
    assert code == "classification_frozen"


# ── rule 16: handover ─────────────────────────────────────────────────────


async def test_handover_needs_the_strategic_spare_of_a_critical_item_and_a_service_asset_or_a_reason(
    world: World,
) -> None:
    iid = await item(world)  # critical, no spares at all
    async with world.factory() as s:
        (await s.get(PlantItem, iid)).status = "commissioned"
        await s.commit()

    def hand(**kw: Any):
        return lambda svc: svc.handover(
            world.project_id, iid, confirm=True, service_contract_id=None, actor_id=world.manager, **kw
        )

    code, blockers, _ = await _refused(world, hand())
    assert code == "transition_blocked"
    assert set(blockers) == {"critical_without_strategic_spares", "handover_needs_service_asset"}
    await _do(
        world,
        lambda svc: svc.update_item(
            world.project_id,
            iid,
            {"no_strategic_spare_reason": "Operator keeps a shared spare"},
            actor_id=world.manager,
        ),
    )
    assert (await _refused(world, hand()))[0] == "handover_needs_service_asset"
    code, _, detail = await _refused(
        world,
        lambda svc: svc.handover(
            world.project_id, iid, confirm=True, service_contract_id=uuid.uuid4(), actor_id=world.manager
        ),
    )
    assert (code, detail) == ("link_not_found", "service_contract_id")
    await _do(world, hand(no_asset_reason="Operator maintains with own staff"))
    assert await _status(world, iid) == "handed_over"
    async with world.factory() as s:
        row = (
            await s.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(iid), ActivityLog.to_status == "handed_over")
            )
        ).scalar_one()
    assert row.metadata_["no_asset_reason"] == "Operator maintains with own staff"
    # A handed-over item is closed to every write.
    code, _, _ = await _refused(world, lambda svc: svc.put_limits(world.project_id, iid, [], actor_id=world.manager))
    assert code == "item_closed"
    code, _, _ = await _refused(
        world,
        lambda svc: svc.create_spare(world.project_id, iid, {"category": "special_tools"}, actor_id=world.manager),
    )
    assert code == "item_closed"


# ── rule 9: the decision paper ────────────────────────────────────────────

_PAPER = {
    "question": "Which offer?",
    "criteria": [{"code": "lead", "weight": "1"}],
    "options": [{"code": "a", "scores": {"lead": "2"}}, {"code": "b", "scores": {"lead": "4"}}],
    "recommendation": "b",
    "rationale": "Shorter lead time.",
}


async def _submitted(w: World, iid: uuid.UUID, by: uuid.UUID | None = None) -> DecisionPaper:
    actor = by or w.area_owner
    paper = await _do(w, lambda svc: svc.create_paper(w.project_id, iid, _PAPER, actor_id=actor))
    return await _do(w, lambda svc: svc.submit_paper(w.project_id, iid, paper.id, actor_id=actor))


async def test_the_named_approver_cannot_submit_the_paper_they_would_approve(world: World) -> None:
    iid = await item(world)
    paper = await _do(world, lambda svc: svc.create_paper(world.project_id, iid, _PAPER, actor_id=world.approver))
    code, _, _ = await _refused(
        world, lambda svc: svc.submit_paper(world.project_id, iid, paper.id, actor_id=world.approver)
    )
    assert code == "paper_submitter_is_approver"
    assert (await get(world, DecisionPaper, paper.id)).status == "draft"


async def test_an_approval_given_by_the_submitter_does_not_approve_the_paper(world: World) -> None:
    from app.modules.approval_routes.models import StepState
    from app.modules.plant_register.events import handle_route_event

    iid = await item(world)
    paper = await _submitted(world, iid)
    # The route let the submitter decide (a role step, a delegation): the paper does not take it.
    async with world.factory() as s:
        from app.modules.approval_routes.models import Step

        step = (await s.execute(select(Step).where(Step.route_id == world.route_id))).scalars().first()
        s.add(
            StepState(
                instance_id=paper.approval_instance_id,
                step_id=step.id,
                approver_user_id=world.area_owner,
                decision="approved",
            )
        )
        await s.commit()
    await handle_route_event(
        {
            "target_kind": "plant_decision_paper",
            "target_id": str(paper.id),
            "instance_id": str(paper.approval_instance_id),
        },
        decision="approved",
        session_factory=world.factory,
    )
    done = await get(world, DecisionPaper, paper.id)
    assert (done.status, done.snapshot) == ("draft", None)


async def test_a_submitted_paper_can_be_withdrawn_and_a_lost_verdict_is_read_from_the_route(world: World) -> None:
    from app.modules.approval_routes.models import Instance
    from app.modules.plant_register.sweeper import run_once

    iid = await item(world)
    paper = await _submitted(world, iid)
    code, _, _ = await _refused(
        world, lambda svc: svc.create_paper(world.project_id, iid, _PAPER, actor_id=world.area_owner)
    )
    assert code == "paper_open"
    back = await _do(world, lambda svc: svc.withdraw_paper(world.project_id, iid, paper.id, actor_id=world.area_owner))
    assert back.status == "draft"
    async with world.factory() as s:
        assert (await s.get(Instance, paper.approval_instance_id)).status == "cancelled"
    code, _, _ = await _refused(
        world, lambda svc: svc.withdraw_paper(world.project_id, iid, paper.id, actor_id=world.area_owner)
    )
    assert code == "paper_not_submitted"

    # Submit again; the route approves but its event never arrives.
    again = await _do(world, lambda svc: svc.submit_paper(world.project_id, iid, paper.id, actor_id=world.area_owner))
    async with world.factory() as s:
        (await s.get(Instance, again.approval_instance_id)).status = "approved"
        await s.commit()
    assert (await get(world, DecisionPaper, paper.id)).status == "submitted"
    done = await run_once(today=TODAY, session_factory=world.factory)
    assert done["papers"] == 1
    approved = await get(world, DecisionPaper, paper.id)
    assert approved.status == "approved" and approved.snapshot["recommendation"] == "b"


async def test_a_refusal_of_the_approval_engine_comes_back_coded(world: World) -> None:
    from app.modules.approval_routes.models import Step

    iid = await item(world)
    paper = await _do(world, lambda svc: svc.create_paper(world.project_id, iid, _PAPER, actor_id=world.area_owner))
    async with world.factory() as s:  # a route with no steps cannot start
        for step in (await s.execute(select(Step).where(Step.route_id == world.route_id))).scalars():
            await s.delete(step)
        await s.commit()
    code, _, detail = await _refused(
        world, lambda svc: svc.submit_paper(world.project_id, iid, paper.id, actor_id=world.area_owner)
    )
    assert code == "decision_route_refused" and "no steps" in (detail or "")


async def test_an_option_cost_needs_a_currency(world: World) -> None:
    iid = await item(world)
    body = {"options": [{"code": "a", "cost": "120000.00"}, {"code": "b"}]}
    code, _, _ = await _refused(
        world, lambda svc: svc.create_paper(world.project_id, iid, body, actor_id=world.area_owner)
    )
    assert code == "cost_needs_currency"


# ── rule 18 and the rule set ──────────────────────────────────────────────


async def test_cde_access_is_provisioned_only_on_a_container_of_this_project_and_keeps_it(world: World) -> None:
    from tests.pg.governance_fixtures import add_container

    svc_row = await _do(
        world, lambda svc: svc.create_it_service(world.project_id, {"kind": "cde_access"}, actor_id=world.manager)
    )
    move = lambda svc: svc.transition_it_service(world.project_id, svc_row.id, "provisioned", actor_id=world.manager)  # noqa: E731
    assert (await _refused(world, move))[0] == "it_cde_not_linked"
    code, _, detail = await _refused(
        world,
        lambda svc: svc.update_it_service(
            world.project_id, svc_row.id, {"cde_container_id": uuid.uuid4()}, actor_id=world.manager
        ),
    )
    assert (code, detail) == ("link_not_found", "cde_container_id")
    async with world.factory() as s:
        container = await add_container(s, world.project_id, "cde")
        await s.commit()
    await _do(
        world,
        lambda svc: svc.update_it_service(
            world.project_id, svc_row.id, {"cde_container_id": container}, actor_id=world.manager
        ),
    )
    await _do(world, move)
    code, _, _ = await _refused(
        world,
        lambda svc: svc.update_it_service(
            world.project_id, svc_row.id, {"cde_container_id": None}, actor_id=world.manager
        ),
    )
    assert code == "it_cde_not_linked"
    # Same state again is a conflict and writes nothing.
    assert (await _refused(world, move))[0] == "invalid_transition"


async def test_the_rule_set_reports_each_rule_on_real_rows(world: World) -> None:
    from app.modules.plant_register.validators import run_rules

    critical = await item(world, "PL-C", need_date_fixed=TODAY + timedelta(days=1))  # critical switchgear
    await quote(world, critical, source="expert_estimate")
    await _do(
        world,
        lambda svc: svc.transition_item(world.project_id, critical, "specified", actor_id=world.manager, today=TODAY),
    )
    await _do(
        world,
        lambda svc: svc.create_it_service(
            world.project_id, {"kind": "cde_access", "needed_from": TODAY - timedelta(days=5)}, actor_id=world.manager
        ),
    )
    payload = await _do(world, lambda svc: svc.validation_payload(world.project_id, today=TODAY))
    failed = {r["rule_id"].split(".")[-1]: r["severity"] for r in await run_rules(payload, "en") if not r["passed"]}
    assert failed["order_not_overdue"] == "error"
    assert failed["critical_has_market_evidence"] == "warning"  # an error only from route_set on
    assert "critical_has_decision_paper" in failed
    passed = {r["rule_id"].split(".")[-1] for r in await run_rules(payload, "en") if r["passed"]}
    # The basis-quote rule starts at ``enquired``; this item is only ``specified``, so it has nothing to say yet.
    assert "lead_time_has_enquiry_date" in passed and "single_basis_quote" not in passed


# ── demo seed ─────────────────────────────────────────────────────────────


async def test_the_demo_seed_fills_every_list_by_the_rules_and_is_idempotent(world: World) -> None:
    from app.modules.approval_routes.models import Route, Step
    from app.modules.plant_register.seed import seed_plant_register_demo
    from app.modules.project_governance.models import GovernanceGate
    from app.modules.projects.models import Project

    async with world.factory() as s:
        project = await s.get(Project, world.project_id)
        project.metadata_ = {"demo_id": "plant-demo"}
        project.currency = "CAD"
        # This test reads the full story, which the seed tells only past the gate
        # into construction; before it no item is seeded beyond ``ordered``.
        gates = (await s.execute(select(GovernanceGate).where(GovernanceGate.project_id == world.project_id))).scalars()
        decided = [g for g in gates if g.to_phase == "execution"]
        assert decided, "the fixture no longer has a gate into execution"
        for gate in decided:
            gate.status = "decided"
        # The demo estate has no decision route of its own: the seed brings one.
        for step in (await s.execute(select(Step).where(Step.route_id == world.route_id))).scalars():
            await s.delete(step)
        await s.delete(await s.get(Route, world.route_id))
        await s.commit()
    async with world.factory() as s:
        first = await seed_plant_register_demo(s, [world.project_id])
        await s.commit()
    # The route of this world is signed by a member of the project's team, so the paper is decided.
    assert first == {"projects": 1, "items": 13, "quotes": 12, "papers_left_draft": 0, "notes": []}

    async with world.factory() as s:
        items = list((await s.execute(select(PlantItem).where(PlantItem.project_id == world.project_id))).scalars())
        slots = list(
            (await s.execute(select(SlotReservation).where(SlotReservation.project_id == world.project_id))).scalars()
        )
        papers = list(
            (await s.execute(select(DecisionPaper).where(DecisionPaper.project_id == world.project_id))).scalars()
        )
    # Every state the module can reach on its own; ``installed`` is read from an owner-furnished item.
    assert {i.status for i in items} == {
        "identified",
        "specified",
        "enquired",
        "route_set",
        "ordered",
        "manufactured",
        "delivered",
        "commissioned",
        "handed_over",
        "cancelled",
    }
    by_code = {i.code: i for i in items}
    assert by_code["PL-002"].status == "route_set"  # critical: it got there on an approved paper
    assert sum(1 for i in items if i.procurement_route) == 9
    assert {i.contract_package_id for i in items if i.procurement_route} == {world.supplier_pkg}
    assert sorted((s.status, s.currency, s.reservation_fee) for s in slots) == [
        ("held", "CAD", Decimal("0.00")),
        ("requested", "CAD", Decimal("25000.00")),
    ]
    assert [(p.status, p.submitted_by) for p in papers] == [("approved", world.manager)]
    assert papers[0].snapshot["recommendation"] == "b"
    # Each state past the route was read from its source, through the state machine.
    assert ("route_set", "commissioned") in await _moves(world, by_code["PL-010"].id)
    assert (await _moves(world, by_code["PL-011"].id))[-1] == ("commissioned", "handed_over")
    views = await _do(world, lambda svc: svc.item_views(world.project_id, today=date.today()))
    assert {v["order_status"] for v in views} >= {"ok"}
    summary = await _do(world, lambda svc: svc.frame_summary(world.project_id, today=date.today()))
    assert "unset" in summary["by_route"] and summary["by_route"]["contractor_furnished_installed"] == 9

    async with world.factory() as s:
        again = await seed_plant_register_demo(s, [world.project_id])
        await s.commit()
        count = await s.scalar(
            select(func.count()).select_from(PlantItem).where(PlantItem.project_id == world.project_id)
        )
    assert again == {"projects": 0, "items": 0, "quotes": 0, "papers_left_draft": 0, "notes": []} and count == 13


async def test_the_demo_seed_leaves_a_project_without_the_demo_marker_alone(world: World) -> None:
    from app.modules.plant_register.seed import seed_plant_register_demo

    async with world.factory() as s:
        out = await seed_plant_register_demo(s, [world.project_id])  # no demo marker
        await s.commit()
    assert out == {"projects": 0, "items": 0, "quotes": 0, "papers_left_draft": 0, "notes": []}
