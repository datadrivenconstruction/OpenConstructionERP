# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plant register service on PostgreSQL (SPEC 8.2): quotes, route and OFI, paper approval, slots, reads."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.plant_register.errors import PlantError
from app.modules.plant_register.models import DecisionPaper, LeadTimeQuote, PlantItem, SlotReservation
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


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)
    unregister_package_plan_provider()
    unregister_commitment_provider()


async def _svc_call(w: World, fn):
    async with w.factory() as s:
        out = await fn(PlantService(s))
        await s.commit()
        return out


async def _code(w: World, fn) -> tuple[str, list[str]]:
    with pytest.raises(PlantError) as exc:
        await _svc_call(w, fn)
    return exc.value.code, [v["code"] for v in exc.value.violations]


# ── rules 2 and 4 ─────────────────────────────────────────────────────────


async def test_a_quote_without_enquiry_date_is_refused_with_its_code(world: World) -> None:
    iid = await item(world)
    code, _ = await _code(
        world,
        lambda svc: svc.add_quote(
            world.project_id,
            iid,
            {"source": "supplier_quote", "lead_weeks_min": 40, "lead_weeks_max": 44},
            actor_id=world.area_owner,
            today=TODAY,
        ),
    )
    assert code == "lead_time_without_enquiry_date"


async def test_new_basis_supersedes_the_old_and_history_is_kept(world: World) -> None:
    iid = await item(world)
    a = await quote(world, iid, lead_weeks_max=60)
    b = await quote(world, iid, lead_weeks_max=44, lead_basis="from_approved_drawings", set_basis=True)
    old, new = await get(world, LeadTimeQuote, a.id), await get(world, LeadTimeQuote, b.id)
    assert (old.is_basis, old.superseded_by, new.is_basis) == (False, b.id, True)
    v = await view(world, iid)
    assert (v["effective_lead_weeks"], v["lead_basis"], v["basis_count"], v["quote_count"]) == (
        44,
        "from_approved_drawings",
        1,
        2,
    )
    # A third quote without set_basis is history only.
    await quote(world, iid, lead_weeks_min=26, lead_weeks_max=30)
    assert (await view(world, iid))["effective_lead_weeks"] == 44


async def test_the_database_refuses_a_second_basis_for_one_item(world: World) -> None:
    iid = await item(world)
    await quote(world, iid)
    async with world.factory() as s:
        s.add(
            LeadTimeQuote(
                project_id=world.project_id,
                plant_item_id=iid,
                source="supplier_quote",
                enquiry_date=date(2026, 9, 1),
                lead_weeks_min=1,
                lead_weeks_max=2,
                is_basis=True,
            )
        )
        with pytest.raises(IntegrityError):
            await s.flush()


async def test_enquired_needs_a_basis_quote(world: World) -> None:
    iid = await item(world)
    await _svc_call(
        world,
        lambda svc: svc.transition_item(world.project_id, iid, "specified", actor_id=world.area_owner, today=TODAY),
    )
    code, _ = await _code(
        world,
        lambda svc: svc.transition_item(world.project_id, iid, "enquired", actor_id=world.area_owner, today=TODAY),
    )
    assert code == "basis_quote_required"
    await quote(world, iid)
    await _svc_call(
        world,
        lambda svc: svc.transition_item(world.project_id, iid, "enquired", actor_id=world.area_owner, today=TODAY),
    )
    assert (await get(world, PlantItem, iid)).status == "enquired"


async def test_ordered_cannot_be_set_by_hand(world: World) -> None:
    iid = await item(world)
    code, _ = await _code(
        world, lambda svc: svc.transition_item(world.project_id, iid, "ordered", actor_id=world.manager, today=TODAY)
    )
    assert code == "state_read_from_source"


# ── rules 6, 9, 10, 11, 14 at route_set ───────────────────────────────────


async def _to_enquired(w: World, iid: uuid.UUID, **qkw) -> None:
    await quote(w, iid, **qkw)
    for target in ("specified", "enquired"):
        await _svc_call(
            w, lambda svc, t=target: svc.transition_item(w.project_id, iid, t, actor_id=w.area_owner, today=TODAY)
        )


async def test_critical_item_with_only_an_estimate_and_no_paper_cannot_set_route(world: World) -> None:
    iid = await item(world)  # mv_switchgear is critical by default
    await _to_enquired(world, iid, source="expert_estimate")
    await _svc_call(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=world.supplier_pkg,
            actor_id=world.manager,
        ),
    )
    code, blockers = await _code(
        world, lambda svc: svc.transition_item(world.project_id, iid, "route_set", actor_id=world.manager, today=TODAY)
    )
    assert code == "transition_blocked"
    assert {"critical_without_market_evidence", "critical_without_decision", "delivery_limit_gap"} <= set(blockers)
    assert "route_inconsistent_with_package_plan" not in blockers


async def test_cfci_to_a_package_that_does_not_supply_is_refused(world: World) -> None:
    iid = await item(world, cls="lift")
    code, blockers = await _code(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=world.installer_pkg,
            actor_id=world.manager,
        ),
    )
    assert code == "route_inconsistent_with_package_plan"
    assert (await get(world, PlantItem, iid)).procurement_route is None


async def test_ofci_creates_the_owner_furnished_item_once_and_reads_its_progress(world: World) -> None:
    iid = await item(world, cls="lift")
    for _ in range(2):
        await _svc_call(
            world,
            lambda svc: svc.set_route(
                world.project_id,
                iid,
                route="owner_furnished_contractor_installed",
                contract_package_id=world.installer_pkg,
                actor_id=world.manager,
            ),
        )
    row = await get(world, PlantItem, iid)
    assert row.owner_furnished_item_id is not None
    assert world.provider.ensure_calls == 2 and len(world.provider.ofis) == 1
    # Route set by hand once the rules pass (lift is not critical), then the OFI state drives ordered.
    await _to_enquired(world, iid)
    await _svc_call(
        world,
        lambda svc: svc.put_limits(
            world.project_id, iid, [{"step": s, "party": "contractor"} for s in _steps()], actor_id=world.manager
        ),
    )
    await _svc_call(
        world, lambda svc: svc.transition_item(world.project_id, iid, "route_set", actor_id=world.manager, today=TODAY)
    )
    world.provider.set_progress(row.owner_furnished_item_id, "delivered")
    await _svc_call(world, lambda svc: svc.sync_item_state(world.project_id, iid, actor_id=world.manager))
    assert (await get(world, PlantItem, iid)).status == "delivered"


def _steps() -> list[str]:
    from app.modules.plant_register.catalogue import shipped_default

    return list(shipped_default().step_codes())


async def test_without_the_delivery_model_module_the_route_degrades_and_does_not_block(world: World) -> None:
    """Port state 1 of 3, not installed: route recorded unchecked, no OFI, no route blocker."""
    unregister_package_plan_provider()
    iid = await item(world, cls="lift")
    await _svc_call(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="owner_furnished_contractor_installed",
            contract_package_id=None,
            actor_id=world.manager,
        ),
    )
    row = await get(world, PlantItem, iid)
    assert (row.procurement_route, row.owner_furnished_item_id) == ("owner_furnished_contractor_installed", None)
    v = await view(world, iid)
    assert v["delivery_model"] == "not_installed"
    async with world.factory() as s:
        svc = PlantService(s)
        assert await svc.route_findings(world.project_id, row) == []
        blockers = await svc.transition_blockers(world.project_id, row, v, "route_set")
    assert not {b for b in blockers if b.startswith(("route_", "package_plan"))}


class _RaisingProvider:
    async def package_plan(self, session, project_id):
        raise RuntimeError("delivery model down")

    async def ensure_owner_furnished_item(self, *a, **kw):
        raise RuntimeError("delivery model down")

    async def get_owner_furnished_item(self, *a, **kw):
        raise RuntimeError("delivery model down")


async def test_an_installed_but_failing_delivery_model_is_an_error_not_a_pass(world: World) -> None:
    """Port state 3 of 3 (state 2, installed and working, is every other route test)."""
    from app.modules.plant_register.ports import register_package_plan_provider
    from app.modules.plant_register.validators import run_rules

    iid = await item(world, cls="lift")
    await _svc_call(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=world.supplier_pkg,
            actor_id=world.manager,
        ),
    )
    register_package_plan_provider(_RaisingProvider())
    code, _ = await _code(
        world,
        lambda svc: svc.set_route(
            world.project_id,
            iid,
            route="contractor_furnished_installed",
            contract_package_id=world.supplier_pkg,
            actor_id=world.manager,
        ),
    )
    assert code == "package_plan_failed"
    async with world.factory() as s:
        payload = await PlantService(s).validation_payload(world.project_id, today=TODAY)
    assert payload["route_findings"]["PL-1"] == ["package_plan_failed"]
    failed = [
        r
        for r in await run_rules(payload, "en")
        if not r["passed"] and r["rule_id"].endswith("route_consistent_with_package_plan")
    ]
    assert failed and failed[0]["severity"] == "error"


async def test_two_parties_on_one_step_are_refused(world: World) -> None:
    iid = await item(world)
    code, _ = await _code(
        world,
        lambda svc: svc.put_limits(
            world.project_id,
            iid,
            [{"step": "supply", "party": "supplier"}, {"step": "supply", "party": "owner"}],
            actor_id=world.manager,
        ),
    )
    assert code == "two_parties_on_one_step"


# ── rule 9 through approval_routes ────────────────────────────────────────


async def test_decision_paper_is_approved_only_through_its_route_and_frozen(world: World) -> None:
    from app.modules.plant_register.events import handle_route_event

    iid = await item(world)
    body = {
        "question": "Which offer?",
        "criteria": [{"code": "lead", "weight": "1"}],
        "options": [{"code": "a", "scores": {"lead": "2"}}, {"code": "b", "scores": {"lead": "4"}}],
        "recommendation": "b",
        "rationale": "Shorter lead time.",
    }
    paper = await _svc_call(world, lambda svc: svc.create_paper(world.project_id, iid, body, actor_id=world.area_owner))
    paper = await _svc_call(
        world, lambda svc: svc.submit_paper(world.project_id, iid, paper.id, actor_id=world.area_owner)
    )
    assert paper.status == "submitted" and paper.approval_instance_id is not None
    # A verdict carrying another instance id does nothing.
    await handle_route_event(
        {"target_kind": "plant_decision_paper", "target_id": str(paper.id), "instance_id": str(uuid.uuid4())},
        decision="approved",
        session_factory=world.factory,
    )
    assert (await get(world, DecisionPaper, paper.id)).status == "submitted"
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
    assert done.status == "approved"
    assert done.snapshot["scores"] == {"a": "2.0000", "b": "4.0000"}
    assert (await view(world, iid))["paper_status"] == "approved"


async def test_a_one_option_paper_is_refused_unless_sole_source(world: World) -> None:
    iid = await item(world)
    body = {"options": [{"code": "a"}], "recommendation": "a", "rationale": "Only one."}
    paper = await _svc_call(world, lambda svc: svc.create_paper(world.project_id, iid, body, actor_id=world.area_owner))
    code, _ = await _code(
        world, lambda svc: svc.submit_paper(world.project_id, iid, paper.id, actor_id=world.area_owner)
    )
    assert code == "decision_paper_needs_two_options"


# ── rule 13 ───────────────────────────────────────────────────────────────


async def test_slot_held_needs_terms_and_a_commitment_for_a_fee_and_expires(world: World) -> None:
    iid = await item(world, cls="power_transformer")
    slot = await _svc_call(
        world,
        lambda svc: svc.create_slot(
            world.project_id,
            iid,
            {
                "reservation_fee": Decimal("25000.00"),
                "currency": "EUR",
                "fee_refundable": "none",
                "convert_by_date": date(2026, 10, 20),
            },
            actor_id=world.manager,
        ),
    )
    code, _ = await _code(
        world, lambda svc: svc.transition_slot(world.project_id, iid, slot.id, "held", actor_id=world.manager)
    )
    assert code == "slot_fee_needs_commitment"
    # A made-up id is not a commitment: with nobody to confirm it, it is not even stored.
    code, _ = await _code(
        world,
        lambda svc: svc.update_slot(
            world.project_id, iid, slot.id, {"commitment_item_id": uuid.uuid4()}, actor_id=world.manager
        ),
    )
    assert code == "commitment_release_unavailable"
    released = CommitmentRef(uuid.uuid4(), released=True, released_amount=Decimal("25000.00"), currency="EUR")

    class Commitments:
        async def get_commitment(self, session, project_id, commitment_item_id):
            return released if (project_id, commitment_item_id) == (world.project_id, released.id) else None

    register_commitment_provider(Commitments())
    await _svc_call(
        world,
        lambda svc: svc.update_slot(
            world.project_id, iid, slot.id, {"commitment_item_id": released.id}, actor_id=world.manager
        ),
    )
    await _svc_call(
        world, lambda svc: svc.transition_slot(world.project_id, iid, slot.id, "held", actor_id=world.manager)
    )
    assert await _svc_call(world, lambda svc: svc.expire_slots(world.project_id, today=date(2026, 10, 20))) == []
    expired = await _svc_call(world, lambda svc: svc.expire_slots(world.project_id, today=date(2026, 10, 21)))
    assert [s.id for s in expired] == [slot.id]
    assert (await get(world, SlotReservation, slot.id)).status == "expired"


# ── rule 12 read path, rule 16 handover ───────────────────────────────────


async def test_other_modules_read_lead_time_and_dates_through_the_plant_item(world: World) -> None:
    from app.modules.plant_register.reads import (
        PlantItemOption,
        plant_item_dates,
        plant_item_id_by_code,
        plant_item_options,
        plant_items_dates,
    )

    iid = await item(world, need_date_fixed=date(2027, 11, 15))
    await quote(world, iid, lead_weeks_max=44, lead_basis="from_approved_drawings")
    async with world.factory() as s:
        d = await plant_item_dates(s, world.project_id, iid, today=TODAY)
        foreign = await plant_item_dates(s, uuid.uuid4(), iid, today=TODAY)
        # The batch read answers the same for the same item and leaves out what is not of this project.
        many = await plant_items_dates(s, world.project_id, [iid, uuid.uuid4(), iid], today=TODAY)
        assert many == {iid: d}
        code = (await s.get(PlantItem, iid)).code
        assert await plant_item_id_by_code(s, world.project_id, code) == iid
        assert await plant_item_id_by_code(s, uuid.uuid4(), code) is None  # another project
        assert await plant_item_id_by_code(s, world.project_id, "NO-SUCH") is None
        assert await plant_item_id_by_code(s, world.project_id, "") is None
        # The picker list: this project's items and nobody else's.
        row = await s.get(PlantItem, iid)
        assert await plant_item_options(s, world.project_id) == [
            PlantItemOption(id=iid, code=code, title=row.title, status="identified")
        ]
        assert await plant_item_options(s, uuid.uuid4()) == []
        assert d.status == "identified"
        # No route yet; once the register has one the read says which, in the single and the batch read.
        assert d.procurement_route is None
        row.procurement_route = "owner_furnished_owner_installed"
        await s.flush()
        routed = await plant_item_dates(s, world.project_id, iid, today=TODAY)
        assert routed.procurement_route == "owner_furnished_owner_installed"
        assert (await plant_items_dates(s, world.project_id, [iid], today=TODAY))[iid] == routed
        await s.rollback()
        assert await plant_items_dates(s, uuid.uuid4(), [iid], today=TODAY) == {}
        assert await plant_items_dates(s, world.project_id, [], today=TODAY) == {}
    assert foreign is None
    assert (d.lead_time_days, d.enquiry_date, d.latest_order_date, d.long_lead) == (
        308,
        date(2026, 8, 3),
        date(2026, 10, 26),
        True,
    )


async def test_handover_needs_commissioned_spares_closed_and_explicit_confirmation(world: World) -> None:
    iid = await item(world, cls="lift")
    async with world.factory() as s:
        row = await s.get(PlantItem, iid)
        row.status = "commissioned"
        await s.commit()
    spare = await _svc_call(
        world,
        lambda svc: svc.create_spare(
            world.project_id, iid, {"category": "commissioning_spares"}, actor_id=world.manager
        ),
    )
    code, blockers = await _code(
        world,
        lambda svc: svc.handover(world.project_id, iid, confirm=True, service_contract_id=None, actor_id=world.manager),
    )
    assert code == "transition_blocked"
    assert set(blockers) == {"spares_not_handed_over", "handover_needs_service_asset"}
    await _svc_call(
        world,
        lambda svc: svc.transition_spare(
            world.project_id, iid, spare.id, "waived", reason="Held by operator", actor_id=world.manager
        ),
    )
    code, _ = await _code(
        world,
        lambda svc: svc.handover(
            world.project_id,
            iid,
            confirm=False,
            service_contract_id=None,
            actor_id=world.manager,
            no_asset_reason="Maintained by the operator's own staff",
        ),
    )
    assert code == "handover_needs_confirmation"
    await _svc_call(
        world,
        lambda svc: svc.handover(
            world.project_id,
            iid,
            confirm=True,
            service_contract_id=None,
            actor_id=world.manager,
            no_asset_reason="Maintained by the operator's own staff",
        ),
    )
    row = await get(world, PlantItem, iid)
    assert (row.status, row.service_asset_id) == ("handed_over", None)


async def test_leaving_the_owner_furnished_route_releases_the_item_and_the_installer_can_be_changed(
    world: World,
) -> None:
    iid = await item(world, cls="lift")

    def route(name: str, package: uuid.UUID | None):
        return lambda svc: svc.set_route(
            world.project_id, iid, route=name, contract_package_id=package, actor_id=world.manager
        )

    await _svc_call(world, route("owner_furnished_contractor_installed", world.installer_pkg))
    ofi_id = (await get(world, PlantItem, iid)).owner_furnished_item_id
    assert world.provider.ofis[ofi_id].installer_package_id == world.installer_pkg
    # The installer is corrected on the same owner-furnished item, not refused as a mismatch.
    await _svc_call(world, route("owner_furnished_contractor_installed", world.supplier_pkg))
    row = await get(world, PlantItem, iid)
    assert row.owner_furnished_item_id == ofi_id
    assert world.provider.ofis[ofi_id].installer_package_id == world.supplier_pkg
    assert world.provider.released == []

    await _svc_call(world, route("contractor_furnished_installed", world.supplier_pkg))
    row = await get(world, PlantItem, iid)
    assert (row.owner_furnished_item_id, world.provider.released) == (None, [iid])
    assert ofi_id not in world.provider.ofis
