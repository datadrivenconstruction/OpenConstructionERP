# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The stakeholders service against PostgreSQL.

Append-only assessments, the sweep, the communication plan, the commitment
lifecycle (direct, through an approval route, breach to risk), the mandate
matrix under concurrency, role changes, the authority port and erasure.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.stakeholders import authority
from app.modules.stakeholders.errors import StakeholderError
from app.modules.stakeholders.models import StakeholderCommitment
from app.modules.stakeholders.service import StakeholderService
from tests._pg import isolated_engine
from tests.pg.stakeholders_fixtures import (
    TODAY,
    World,
    build_world,
    commitment,
    contact,
    move,
    roster,
    seat,
    stakeholder,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory():
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def world(factory):
    return await build_world(factory)


async def _refused(coro) -> StakeholderError:
    with pytest.raises(StakeholderError) as exc:
        await coro
    return exc.value


async def _commitment(w: World, cid: uuid.UUID) -> StakeholderCommitment:
    async with w.factory() as s:
        return await StakeholderService(s).get_commitment(w.project_id, cid)


# ── assessments and the sweep ─────────────────────────────────────────────


async def test_assessments_append_and_classification_is_derived(world: World) -> None:
    sid = await stakeholder(world, "Residents north", is_group=True)
    async with world.factory() as s:
        svc = StakeholderService(s)
        await svc.assess(world.project_id, sid, {"scores": {"power": 1, "interest": 1}}, actor_id=world.editor)
        await svc.assess(world.project_id, sid, {"scores": {"power": 5, "interest": 5}}, actor_id=world.editor)
        await s.commit()
    async with world.factory() as s:
        history = await StakeholderService(s).list_assessments(world.project_id, sid)
    assert [h.classification for h in history] == ["manage_closely", "monitor"]


async def test_out_of_scale_scores_are_refused(world: World) -> None:
    sid = await stakeholder(world, "Grid", category="grid_operator")
    async with world.factory() as s:
        await _refused(
            StakeholderService(s).assess(
                world.project_id, sid, {"scores": {"power": 9, "interest": 1}}, actor_id=world.editor
            )
        )


async def test_the_sweep_notifies_a_due_review_once(world: World) -> None:
    await stakeholder(world, "Council", category="municipality")
    async with world.factory() as s:
        first = await StakeholderService(s).sweep(world.project_id, today=TODAY)
        await s.commit()
    async with world.factory() as s:
        second = await StakeholderService(s).sweep(world.project_id, today=TODAY)
        await s.commit()
    assert first["review_due"] == 1
    assert second["review_due"] == 0


async def test_the_daily_job_sweeps_every_project_and_survives_a_bad_one(world: World) -> None:
    from app.modules.stakeholders.jobs import sweep_all

    await stakeholder(world, "Council", category="municipality")
    other = await build_world(world.factory)
    await stakeholder(other, "Utility", category="utility")
    result = await sweep_all(world.factory)
    assert result == {"swept": 2, "failed": 0}
    async with world.factory() as s:
        again = await StakeholderService(s).sweep(world.project_id, today=TODAY)
    assert again["review_due"] == 0


# ── communication plan (rules 6, 7, 8) ────────────────────────────────────


async def _monthly_plan(w: World, sid: uuid.UUID, start) -> uuid.UUID:
    async with w.factory() as s:
        item = await StakeholderService(s).create_plan_item(
            w.project_id,
            {
                "title": "Neighbour newsletter",
                "audience_stakeholder_ids": [sid],
                "participation_level": "consult",
                "channel": "newsletter",
                "frequency": "FREQ=MONTHLY",
                "starts_on": start,
                "status": "active",
            },
            actor_id=w.editor,
        )
        await s.commit()
        return item.id


async def _record(w: World, item_id: uuid.UUID, held_on, **extra):
    async with w.factory() as s:
        row = await StakeholderService(s).create_event(
            w.project_id,
            {"plan_item_id": item_id, "held_on": held_on, "status": "held", **extra},
            actor_id=w.editor,
        )
        await s.commit()
        return row


async def _plan(w: World, item_id: uuid.UUID):
    async with w.factory() as s:
        return await StakeholderService(s).get_plan_item(w.project_id, item_id)


async def test_recording_advances_the_plan_and_a_follow_up_does_not_consume_the_next_one(world: World) -> None:
    sid = await stakeholder(world, "Residents north", is_group=True)
    start = TODAY - timedelta(days=40)
    item_id = await _monthly_plan(world, sid, start)
    assert (await _plan(world, item_id)).next_due == start
    first = await _record(world, item_id, start)
    second_due = (await _plan(world, item_id)).next_due
    assert first.occurrence_date == start
    assert second_due is not None and second_due > start
    follow_up = await _record(world, item_id, start + timedelta(days=2))
    assert follow_up.occurrence_date == start
    assert (await _plan(world, item_id)).next_due == second_due


async def test_a_consult_event_without_reported_feedback_is_flagged_after_the_framework_days(world: World) -> None:
    sid = await stakeholder(world, "Residents north", is_group=True)
    item_id = await _monthly_plan(world, sid, TODAY - timedelta(days=40))
    event = await _record(world, item_id, TODAY - timedelta(days=40))
    async with world.factory() as s:
        svc = StakeholderService(s)
        _settings, fw = await svc.context(world.project_id)
        late = svc.event_out(await svc.get_event(world.project_id, event.id), fw, TODAY)
        await svc.update_event(
            world.project_id, event.id, {"feedback_summary": "Answers sent by letter"}, actor_id=world.editor
        )
        await s.commit()
        reported = svc.event_out(await svc.get_event(world.project_id, event.id), fw, TODAY)
    assert late["feedback_not_reported"] is True
    assert reported["feedback_not_reported"] is False


async def test_a_rule_that_never_advances_is_refused_before_it_is_stored(world: World) -> None:
    sid = await stakeholder(world, "Residents north", is_group=True)
    async with world.factory() as s:
        err = await _refused(
            StakeholderService(s).create_plan_item(
                world.project_id,
                {
                    "title": "Daily note",
                    "audience_stakeholder_ids": [sid],
                    "participation_level": "inform",
                    "channel": "newsletter",
                    "frequency": "FREQ=DAILY;INTERVAL=0",
                    "starts_on": TODAY,
                },
                actor_id=world.editor,
            )
        )
    assert err.code == "invalid_frequency"


# ── commitments: direct decision (rules 9, 10, 19) ────────────────────────


async def test_a_commitment_is_agreed_by_the_mandate_holder_kept_and_verified_by_someone_else(world: World) -> None:
    sid = await stakeholder(world, "Residents east", is_group=True)
    await seat(world, "client_pm", world.manager)
    cid = await commitment(world, sid, owner=world.editor)
    for target in ("agreed", "in_progress", "fulfilled"):
        row, _ = await move(world, cid, target, world.manager)
    assert row.status == "fulfilled"
    assert row.decision_ref["decided_by"] == str(world.manager)
    own = await _refused(move(world, cid, "verified", world.editor, communicated_back_at=datetime.now(UTC)))
    assert (own.code, own.status_code) == ("owner_cannot_verify", 403)
    open_loop = await _refused(move(world, cid, "verified", world.manager))
    assert open_loop.code == "verification_needs_loop_closed"
    row, _ = await move(world, cid, "verified", world.manager, communicated_back_at=datetime.now(UTC))
    assert row.status == "verified"
    again = await _refused(move(world, cid, "verified", world.manager, communicated_back_at=datetime.now(UTC)))
    assert again.status_code == 409


async def test_nobody_agrees_a_commitment_while_the_deciding_role_is_vacant_or_expired(world: World) -> None:
    sid = await stakeholder(world, "Residents east", is_group=True)
    cid = await commitment(world, sid)
    vacant = await _refused(move(world, cid, "agreed", world.manager))
    assert (vacant.code, vacant.status_code) == ("not_decider", 403)
    await seat(world, "client_pm", world.manager, valid_to=TODAY - timedelta(days=1))
    expired = await _refused(move(world, cid, "agreed", world.manager))
    assert expired.code == "not_decider"
    assert (await _commitment(world, cid)).status == "proposed"


async def test_what_was_agreed_is_frozen_and_an_amount_always_has_a_currency(world: World) -> None:
    sid = await stakeholder(world, "Residents east", is_group=True)
    await seat(world, "client_pm", world.manager)
    cid = await commitment(world, sid)
    async with world.factory() as s:
        row = await StakeholderService(s).update_commitment(
            world.project_id, cid, {"cost_estimate": "1500.50"}, actor_id=world.editor
        )
        await s.commit()
    assert (row.cost_estimate, row.currency) == (Decimal("1500.50"), "EUR")
    row, warnings = await move(world, cid, "agreed", world.manager)
    assert warnings == ["release_item_not_checked"]
    for change in ({"currency": "JPY"}, {"cost_estimate": "9"}, {"text": "Something else"}):
        async with world.factory() as s:
            err = await _refused(
                StakeholderService(s).update_commitment(world.project_id, cid, change, actor_id=world.editor)
            )
        assert (err.code, err.status_code) == ("commitment_frozen", 409), change
    async with world.factory() as s:
        err = await _refused(
            StakeholderService(s).update_commitment(
                world.project_id, cid, {"owner_user_id": world.manager2}, actor_id=world.editor
            )
        )
        assert err.code == "owner_change_needs_manage"
        moved = await StakeholderService(s).update_commitment(
            world.project_id, cid, {"owner_user_id": world.manager2}, actor_id=world.manager, can_manage=True
        )
        await s.commit()
    assert moved.owner_user_id == world.manager2


async def test_a_confirmed_breach_opens_a_risk_once(world: World) -> None:
    from app.modules.risk.models import RiskItem

    sid = await stakeholder(world, "Residents east", is_group=True)
    await seat(world, "client_pm", world.manager)
    cid = await commitment(world, sid)
    await move(world, cid, "agreed", world.manager)
    missing = await _refused(move(world, cid, "breached", world.editor))
    assert missing.code == "rationale_required"
    row, _ = await move(world, cid, "breached", world.editor, rationale="Deliveries at 06:10", create_risk=True)
    assert row.status == "breached" and row.risk_id is not None
    async with world.factory() as s:
        risk = await s.get(RiskItem, row.risk_id)
    assert risk.project_id == world.project_id
    assert row.code in risk.title
    assert "Deliveries at 06:10" in risk.description


# ── commitments: through an approval route ────────────────────────────────


@pytest_asyncio.fixture
async def routed(factory):
    return await build_world(factory, framework_id="elf_module_framework", route=True)


async def test_a_routed_commitment_waits_for_the_approval_and_cannot_be_edited_meanwhile(routed: World) -> None:
    sid = await stakeholder(routed, "Residents east", is_group=True)
    await seat(routed, "client_pm", routed.manager)
    cid = await commitment(routed, sid)
    row, _ = await move(routed, cid, "agreed", routed.editor)
    assert (row.status, row.pending_target) == ("proposed", "agreed")
    assert row.approval_instance_id is not None
    async with routed.factory() as s:
        err = await _refused(
            StakeholderService(s).update_commitment(
                routed.project_id, cid, {"text": "A different promise"}, actor_id=routed.editor
            )
        )
    assert (err.code, err.status_code) == ("approval_pending", 409)
    second = await _refused(move(routed, cid, "agreed", routed.editor))
    assert second.code == "approval_pending"
    async with routed.factory() as s:
        done = await StakeholderService(s).apply_route_verdict(
            row.approval_instance_id, verdict="approved", decided_by=routed.manager2
        )
        await s.commit()
    after = await _commitment(routed, cid)
    assert done is True
    assert (after.status, after.pending_target, after.text) == ("agreed", None, "No deliveries before 07:00")
    assert after.decision_ref["mode"] == "approval"


async def test_a_rejected_approval_leaves_the_commitment_proposed_and_free_again(routed: World) -> None:
    sid = await stakeholder(routed, "Residents east", is_group=True)
    await seat(routed, "client_pm", routed.manager)
    cid = await commitment(routed, sid)
    row, _ = await move(routed, cid, "agreed", routed.editor)
    async with routed.factory() as s:
        await StakeholderService(s).apply_route_verdict(
            row.approval_instance_id, verdict="rejected", decided_by=routed.manager2
        )
        await s.commit()
    after = await _commitment(routed, cid)
    assert (after.status, after.pending_target) == ("proposed", None)


async def test_a_verdict_that_never_arrived_is_caught_up_on_the_next_transition(routed: World) -> None:
    from app.modules.approval_routes.models import Instance

    sid = await stakeholder(routed, "Residents east", is_group=True)
    await seat(routed, "client_pm", routed.manager)
    cid = await commitment(routed, sid)
    row, _ = await move(routed, cid, "agreed", routed.editor)
    async with routed.factory() as s:
        instance = await s.get(Instance, row.approval_instance_id)
        instance.status = "approved"  # the route finished; the subscriber that tells this module did not run
        await s.commit()
    row, _ = await move(routed, cid, "in_progress", routed.editor)
    assert (row.status, row.pending_target) == ("in_progress", None)


async def test_a_routed_commitment_without_a_route_is_refused_by_name(factory) -> None:
    w = await build_world(factory, framework_id="elf_module_framework")
    sid = await stakeholder(w, "Residents east", is_group=True)
    await seat(w, "client_pm", w.manager)
    cid = await commitment(w, sid)
    err = await _refused(move(w, cid, "agreed", w.editor))
    assert err.code == "no_commitment_route"


# ── organisation: roles, bodies, mandates ─────────────────────────────────


async def test_the_matrix_copied_at_the_first_pin_can_be_saved_back(world: World) -> None:
    async with world.factory() as s:
        svc = StakeholderService(s)
        matrix = await svc.matrix(world.project_id, today=TODAY)
        rows = [
            {k: r[k] for k in ("decision_type", "scope", "holder_kind", "holder_code", "letter", "scope_note")}
            for r in matrix["rows"]
        ]
        assert "steering_committee" in matrix["bodies"]
        assert any(r["holder_kind"] == "body" for r in rows)
        saved = await svc.put_mandates(world.project_id, rows, actor_id=world.manager, today=TODAY)
        await s.commit()
    assert saved["missing"] == []


async def test_two_deciders_for_one_type_are_refused(world: World) -> None:
    rows = [
        {"decision_type": "scope_change", "scope": "", "holder_kind": "role", "holder_code": "client", "letter": "D"},
        {"decision_type": "scope_change", "scope": "", "holder_kind": "role", "holder_code": "investor", "letter": "D"},
    ]
    async with world.factory() as s:
        err = await _refused(
            StakeholderService(s).put_mandates(world.project_id, rows, actor_id=world.manager, today=TODAY)
        )
    assert err.code == "two_deciders"


async def test_concurrent_matrix_writes_never_leave_two_deciders(world: World) -> None:
    def matrix(code: str) -> list[dict]:
        return [
            {"decision_type": "scope_change", "scope": "", "holder_kind": "role", "holder_code": code, "letter": "D"}
        ]

    async def write(code: str) -> None:
        async with world.factory() as s:
            try:
                await StakeholderService(s).put_mandates(
                    world.project_id, matrix(code), actor_id=world.manager, today=TODAY
                )
                await s.commit()
            except StakeholderError:
                await s.rollback()

    await asyncio.gather(write("client"), write("investor"))
    async with world.factory() as s:
        rows = await StakeholderService(s).repo.mandates(world.project_id)
    deciders = [r for r in rows if r.decision_type == "scope_change" and r.scope == "" and r.letter == "D"]
    assert len(deciders) == 1


async def test_concurrent_holder_writes_never_leave_two_holders_on_a_single_role(world: World) -> None:
    a, b = await roster(world, world.manager), await roster(world, world.manager2)

    async def write(member: uuid.UUID) -> None:
        async with world.factory() as s:
            await StakeholderService(s).put_role_holders(
                world.project_id, "client_pm", [{"roster_member_id": member}], actor_id=world.manager, today=TODAY
            )
            await s.commit()

    await asyncio.gather(write(a), write(b))
    async with world.factory() as s:
        holders = [r for r in await StakeholderService(s).repo.roles(world.project_id) if r.role_code == "client_pm"]
    assert len(holders) == 1


async def test_one_person_proposing_and_deciding_must_be_acknowledged(world: World) -> None:
    # In the neutral template the project manager proposes a stakeholder commitment and the client lead decides.
    await seat(world, "project_manager", world.manager)
    member = await roster(world, world.manager)
    async with world.factory() as s:
        err = await _refused(
            StakeholderService(s).put_role_holders(
                world.project_id, "client_pm", [{"roster_member_id": member}], actor_id=world.manager, today=TODAY
            )
        )
    assert err.code in ("conflict_not_acknowledged", "self_approval_forbidden")
    assert err.violations and err.violations[0]["user_id"] == str(world.manager)


async def test_changing_a_holder_publishes_role_changed_with_both_sides(world: World) -> None:
    from app.core.events import event_bus

    seen: list[dict] = []

    async def capture(event) -> None:
        seen.append(dict(event.data or {}))

    event_bus.subscribe("stakeholders.role.changed", capture)
    try:
        await seat(world, "client_pm", world.manager)
        await seat(world, "client_pm", world.manager2)
        for _ in range(50):
            if len(seen) >= 2:
                break
            await asyncio.sleep(0.1)
    finally:
        event_bus.unsubscribe("stakeholders.role.changed", capture)
    mine = [e for e in seen if e.get("project_id") == str(world.project_id)]
    assert [e["user_ids"] for e in mine] == [[str(world.manager)], [str(world.manager2)]]
    assert mine[1]["previous_user_ids"] == [str(world.manager)]
    assert mine[1]["role_code"] == "client_pm"


async def test_who_decides_names_the_holder_and_asks_the_authority_port_for_the_tier(world: World) -> None:
    member = await roster(world, None, "Client organisation")
    async with world.factory() as s:
        await StakeholderService(s).put_role_holders(
            world.project_id, "client", [{"roster_member_id": member}], actor_id=world.manager, today=TODAY
        )
        await s.commit()
    asked: list[tuple] = []

    async def evaluator(session, project_id, commitment_type, amount, currency, today):
        asked.append((project_id, commitment_type, amount, currency))
        return authority.AuthorityAnswer("tier_2", (str(world.manager2),), schedule="demo")

    async with world.factory() as s:
        plain = await StakeholderService(s).who_decides(
            world.project_id, "order_award", "", today=TODAY, amount="50000", currency="EUR"
        )
    authority.register_authority_evaluator(evaluator)
    try:
        async with world.factory() as s:
            tiered = await StakeholderService(s).who_decides(
                world.project_id, "order_award", "", today=TODAY, amount="50000", currency="EUR"
            )
    finally:
        authority.register_authority_evaluator(None)
    assert plain["holder_code"] == "client" and plain["authority"] is None
    assert "authority_not_evaluated" in plain["flags"]
    assert asked == [(world.project_id, "works", Decimal("50000"), "EUR")]
    assert tiered["authority"]["tier_code"] == "tier_2"
    assert tiered["authority"]["approver_user_ids"] == [str(world.manager2)]
    assert "authority_not_evaluated" not in tiered["flags"]


# ── contacts: linking, re-saving, erasure ─────────────────────────────────


async def test_an_erased_contact_leaves_an_anonymised_stakeholder_without_a_name(world: World) -> None:
    from app.modules.contacts.models import Contact

    cid = await contact(world, world.editor, "Jane", "Private")
    sid = await stakeholder(world, "Jane Private", contact_id=cid)
    async with world.factory() as s:
        named = await StakeholderService(s).stakeholder_views(world.project_id, can_read_personal=True, today=TODAY)
        await s.delete(await s.get(Contact, cid))
        await s.commit()
    async with world.factory() as s:
        erased = await StakeholderService(s).stakeholder_views(world.project_id, can_read_personal=True, today=TODAY)
    before = next(v for v in named if v["id"] == str(sid))
    after = next(v for v in erased if v["id"] == str(sid))
    assert before["name"] == "Jane Private" and before["display_name"] == ""
    assert (after["anonymised"], after["name"]) == (True, None)
    assert "Jane" not in str(after)


async def test_a_second_manager_can_resave_a_role_holding_a_colleagues_contact(world: World) -> None:
    cid = await contact(world, world.manager, "Client", "Organisation")
    async with world.factory() as s:
        svc = StakeholderService(s)
        await svc.put_role_holders(
            world.project_id, "client", [{"holder_contact_id": cid}], actor_id=world.manager, today=TODAY
        )
        await s.commit()
    foreign = await contact(world, world.manager, "Other", "Party")
    async with world.factory() as s:
        svc = StakeholderService(s)
        await svc.put_role_holders(
            world.project_id,
            "client",
            [{"holder_contact_id": cid, "valid_from": TODAY}],
            actor_id=world.manager2,
            today=TODAY,
        )
        await s.commit()
        # Keeping a link is allowed; making a new one to a contact the caller cannot see is not.
        err = await _refused(
            svc.put_role_holders(
                world.project_id, "client", [{"holder_contact_id": foreign}], actor_id=world.manager2, today=TODAY
            )
        )
    assert (err.code, err.status_code) == ("contact_not_found", 404)


# ── settings: tenant frameworks and the first pin ─────────────────────────


async def test_another_tenants_framework_cannot_be_pinned_by_inheriting_the_source(world: World) -> None:
    from app.modules.project_governance.catalogue_store import CatalogueStore
    from app.modules.stakeholders.catalogue import FRAMEWORK_KIND

    async def publish(tenant: uuid.UUID, code: str) -> str:
        async with world.factory() as s:
            StakeholderService(s)
            store = CatalogueStore(s)
            row = await store.create(
                str(tenant),
                code=code,
                name=code,
                based_on_source="shipped",
                based_on_id="neutral",
                based_on_version=None,
                actor_id=tenant,
                kind=FRAMEWORK_KIND,
            )
            await store.publish(str(tenant), row.id, actor_id=tenant)
            await s.commit()
            return str(row.id)

    mine = await publish(world.manager, "ours")
    theirs = await publish(world.outsider, "theirs")
    async with world.factory() as s:
        svc = StakeholderService(s)
        await svc.put_settings(
            world.project_id,
            {"framework_source": "tenant", "framework_id": mine},
            actor_id=world.manager,
            tenant_id=str(world.manager),
        )
        await s.commit()
    async with world.factory() as s:
        svc = StakeholderService(s)
        # No framework_source in the body: it is inherited from the stored pin.
        err = await _refused(
            svc.put_settings(
                world.project_id, {"framework_id": theirs}, actor_id=world.manager, tenant_id=str(world.manager)
            )
        )
    async with world.factory() as s:
        # Read back the way every later request does: from the stored pin, with no tenant in hand.
        settings, fw = await StakeholderService(s).context(world.project_id)
    assert (err.code, err.status_code) == ("unknown_catalogue", 404)
    assert (settings.framework_source, settings.framework_id) == ("tenant", mine)
    assert fw.id == "ours"


async def test_two_first_pins_at_once_leave_one_settings_row(factory) -> None:
    from sqlalchemy import func, select

    from app.modules.stakeholders.models import StakeholderSettings
    from tests.pg.governance_fixtures import add_project, add_user

    async with factory() as s:
        manager = await add_user(s, "manager")
        pid = await add_project(s, manager, [])
        await s.commit()

    async def pin() -> str:
        async with factory() as s:
            try:
                await StakeholderService(s).put_settings(pid, {"framework_id": "neutral"}, actor_id=manager)
                await s.commit()
                return "ok"
            except StakeholderError as exc:
                await s.rollback()
                return exc.code

    results = sorted(await asyncio.gather(pin(), pin()))
    async with factory() as s:
        count = await s.scalar(
            select(func.count()).select_from(StakeholderSettings).where(StakeholderSettings.project_id == pid)
        )
    assert count == 1
    assert results in (["concurrent_change", "ok"], ["ok", "ok"])


# ── demo seed ─────────────────────────────────────────────────────────────


async def test_the_demo_seed_fills_every_list_and_ends_with_a_verified_commitment(factory) -> None:
    from app.modules.stakeholders.seed import _seed_project
    from tests.pg.governance_fixtures import add_project, add_user

    async with factory() as s:
        owner = await add_user(s, "manager")
        members = [await add_user(s, "editor") for _ in range(4)]
        pid = await add_project(s, owner, members)
        await s.commit()
    async with factory() as s:
        # Called directly: the public entry point logs and skips a failing project, which would hide a defect here.
        counts = await _seed_project(s, pid)
        await s.commit()
    async with factory() as s:
        svc = StakeholderService(s)
        views = await svc.stakeholder_views(pid, can_read_personal=True, today=TODAY)
        plan = await svc.repo.plan_items(pid)
        events = await svc.repo.events(pid)
        commitments = await svc.repo.commitments(pid)
        roles = await svc.roles_view(pid, today=TODAY)
        bodies = await svc.repo.bodies(pid)
    assert counts["stakeholders"] == len(views) == 14
    assert plan and events and bodies
    assert all(v["classification"] != "not_assessed" for v in views)
    statuses = {c.status for c in commitments}
    assert {"agreed", "in_progress", "verified"} <= statuses
    assert "client" not in roles["vacant"]
    assert all(e.held_on is None or e.held_on <= TODAY for e in events if e.status == "held")


@pytest.mark.parametrize("team_size", [0, 2])
async def test_the_demo_seed_uses_only_the_projects_people_and_logs_nothing_above_info(
    factory, caplog, team_size: int
) -> None:
    """Owner only, and the demo cast of three: both are healthy installs."""
    import logging

    import sqlalchemy as sa

    from app.database import Base
    from app.modules.stakeholders.seed import _seed_project
    from app.modules.teams.models import RosterMember
    from tests.pg.governance_fixtures import add_project, add_user

    async with factory() as s:
        owner = await add_user(s, "manager")
        members = [await add_user(s, "editor") for _ in range(team_size)]
        # Somebody's real account on the same installation, with the widest role and on no project.
        foreign = await add_user(s, "admin")
        pid = await add_project(s, owner, members)
        await s.commit()
    with caplog.at_level(logging.INFO):
        async with factory() as s:
            counts = await _seed_project(s, pid)
            await s.commit()
    loud = [r for r in caplog.records if r.levelno > logging.INFO and r.name.startswith("app.modules.stakeholders")]
    assert [(r.name, r.getMessage()) for r in loud] == []
    assert counts["stakeholders"] == 14
    # Owner only: both roles a colleague would hold stay vacant, said at info and counted in the result.
    assert counts["unfilled_roles"] == (2 if team_size == 0 else 0)
    told = [r for r in caplog.records if r.name == "app.modules.stakeholders.seed" and r.levelno == logging.INFO]
    # Said once for the vacant roles and once for the commitments nobody but the owner could approve.
    assert len(told) == (2 if team_size == 0 else 0)

    people = {owner, *members}
    async with factory() as s:
        seen: set[uuid.UUID] = set()
        for name, table in Base.metadata.tables.items():
            if not name.startswith("oe_stakeholders_"):
                continue
            for row in (await s.execute(sa.select(table).where(table.c.project_id == pid))).mappings():
                seen |= {v for k, v in row.items() if isinstance(v, uuid.UUID) and k.endswith(("user_id", "_by"))}
        roster = (await s.execute(sa.select(RosterMember.user_id).where(RosterMember.project_id == pid))).scalars()
        seen |= {u for u in roster if u}
    assert foreign not in seen
    assert seen <= people, seen - people
    assert seen, "the seed names nobody, so the check above proves nothing"
