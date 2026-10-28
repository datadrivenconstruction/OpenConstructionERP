# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plan-side rules of staffing against PostgreSQL: numbers, gate fields, warnings, evidence, the demo seed.

PostgreSQL is where these defects lived: a third decimal that the Numeric
column rounds away, a NULL that only a NOT NULL constraint refuses, a gate
that must be found by what its phase enables, and a seed whose lists have to
be non-empty when read back through the same services the screens call.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.staffing.errors import StaffingError
from app.modules.staffing.permissions import register_staffing_permissions
from app.modules.staffing.service import Actor, StaffingService
from tests._pg import isolated_engine
from tests.pg.staffing_fixtures import (
    GATE,
    PERSONNEL_AREA,
    PERSONNEL_FRAME,
    START,
    admin,
    build_world,
    call,
    confirm,
    days,
    drop_frame_document,
    fill,
    hr,
    members,
    personnel_file,
    position,
    submittable_plan,
)

pytestmark = pytest.mark.asyncio


def _flag(flag: dict) -> dict:
    """A ``can`` flag without ``applies``: these tests are about whether and why, not about relevance."""
    return {k: v for k, v in flag.items() if k != "applies"}


@pytest_asyncio.fixture
async def factory():
    register_staffing_permissions()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _refused(awaitable) -> StaffingError:
    with pytest.raises(StaffingError) as err:
        await awaitable
    return err.value


async def _row(w, model, row_id):
    async with w.factory() as s:
        return await s.get(model, row_id)


# ── finding 9: numbers ─────────────────────────────────────────────────────


async def test_a_third_decimal_is_refused_before_the_column_rounds_it_to_zero(factory) -> None:
    w = await build_world(factory, governance=False)
    data = {"role_code": "site_manager", "phase": "execution", "entry_date": START, "fte": "0.004"}
    err = await _refused(call(w, "create_position", data, admin(w)))
    assert (err.code, err.status_code) == ("fte_precision", 422)

    pid = await position(w, "site_manager")
    err = await _refused(call(w, "update_position", pid, {"fte": "0.004"}, admin(w)))
    assert err.code == "fte_precision"
    person = (await members(w))[0]
    err = await _refused(
        call(
            w, "create_fill", pid, {"roster_member_id": person.id, "fte_share": "0.004", "from_date": START}, w.manager
        )
    )
    assert err.code == "fte_precision"
    # The position is still open: nothing was stored as 0.00 and read as covered.
    view = next(v for v in await call(w, "position_views") if v["id"] == str(pid))
    assert (view["status"], view["fte"]) == ("open", "1.00")


async def test_a_number_the_column_cannot_hold_is_a_422(factory) -> None:
    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id)
    trip = {"kind": "business", "depart_date": days(3), "currency": "EUR"}
    for cost in ("1000000000000", "10.001", "-5"):
        err = await _refused(call(w, "create_travel", file_id, {**trip, "cost": cost}, admin(w)))
        assert (err.code, err.status_code) == ("cost_invalid", 422), cost
    err = await _refused(call(w, "create_travel", file_id, {**trip, "cost": "10.00", "currency": ""}, admin(w)))
    assert err.code == "currency_required"
    data = {"role_code": "site_manager", "phase": "execution", "headcount": 10**7}
    err = await _refused(call(w, "create_position", data, admin(w)))
    assert (err.code, err.status_code) == ("headcount_invalid", 422)


# ── finding 10: explicit null ──────────────────────────────────────────────


@pytest.mark.parametrize("field", ["title", "notes", "custom_label", "key_role", "handover_role", "sort_order"])
async def test_a_null_on_a_required_column_is_a_422_at_the_service_too(factory, field) -> None:
    from app.modules.staffing.models import StaffingPosition

    w = await build_world(factory, governance=False)
    pid = await position(w, "site_manager", title="Site lead")
    err = await _refused(call(w, "update_position", pid, {field: None}, admin(w)))
    assert (err.code, err.status_code) == ("field_required", 422)
    assert (await _row(w, StaffingPosition, pid)).title == "Site lead"


# ── lead decision: gate fields need the manage permission and freeze ───────


async def test_what_a_gate_reads_needs_the_manage_permission_and_an_open_position(factory) -> None:
    from app.modules.staffing.models import StaffingPosition

    w = await build_world(factory, governance=False)
    pid = await position(w, "site_manager")
    for change in ({"key_role": False}, {"required_before": None}, {"handover_role": True}):
        err = await _refused(call(w, "update_position", pid, change, hr(w.editor)))
        assert (err.code, err.status_code) == ("manage_permission_required", 403), change
    # Planning a key role as an ordinary one at creation is the same change.
    data = {"role_code": "hse_manager", "phase": "execution", "key_role": False}
    err = await _refused(call(w, "create_position", data, hr(w.editor)))
    assert err.code == "manage_permission_required"
    row = await _row(w, StaffingPosition, pid)
    assert (row.key_role, row.required_before, row.handover_role) == (True, "construction_start", False)

    await call(w, "set_position_status", pid, "recruiting", w.manager)
    err = await _refused(call(w, "update_position", pid, {"key_role": False}, admin(w)))
    assert (err.code, err.status_code) == ("gate_fields_frozen", 409)
    await call(w, "set_position_status", pid, "open", w.manager)
    await call(w, "update_position", pid, {"key_role": False}, admin(w))
    assert (await _row(w, StaffingPosition, pid)).key_role is False

    view = await call(w, "plan_view", hr(w.editor))
    assert _flag(view["can"]["manage"]) == {"allowed": False, "reason": "manage_permission_required"}
    assert _flag(view["can"]["assign_owner"]) == {"allowed": False, "reason": "owner_assignment_forbidden"}
    assert _flag((await call(w, "plan_view", admin(w)))["can"]["manage"]) == {"allowed": True, "reason": None}


# ── finding 14 ─────────────────────────────────────────────────────────────


async def test_a_handover_to_the_givers_own_position_is_refused(factory) -> None:
    w = await build_world(factory, governance=False)
    pid = await position(w, "project_manager")
    fid = await fill(w, pid, (await members(w))[0].id)
    data = {"from_fill_id": fid, "to_position_id": pid, "overlap_days": 30, "scope": ""}
    err = await _refused(call(w, "create_handover", data, w.manager))
    assert (err.code, err.status_code) == ("handover_same_position", 422)
    assert await call(w, "handover_views") == []


# ── finding 16: rule 21 and rules 16 to 18 on PostgreSQL ───────────────────


async def test_a_catalogue_change_maps_roles_and_turns_the_unmapped_into_custom(factory) -> None:
    from app.modules.project_governance.catalogue_store import CatalogueStore
    from app.modules.staffing.catalogue import STAFFING_MODEL_KIND
    from app.modules.staffing.models import StaffingPosition

    w = await build_world(factory, governance=False)
    kept = await position(w, "site_manager")
    mapped = await position(w, "scheduler")
    dropped = await position(w, "document_controller")
    tenant = str(w.manager)
    async with w.factory() as s:
        store = CatalogueStore(s)
        draft = await store.create(
            tenant,
            code="lean",
            name="Lean",
            based_on_source="shipped",
            based_on_id="neutral",
            based_on_version=None,
            actor_id=w.manager,
            kind=STAFFING_MODEL_KIND,
        )
        body = dict(draft.draft_body)
        body["roles"] = [r for r in body["roles"] if r["code"] not in ("scheduler", "document_controller")]
        body["roles"].append(
            {
                "code": "planner",
                "labels": {"en": "Planner"},
                "organisation": "owner_project_controls",
                "phases": ["development", "execution"],
            }
        )
        await store.update_draft(tenant, draft.id, body=body, name=None)
        number = (await store.publish(tenant, draft.id, actor_id=w.manager)).version
        lean = str(draft.id)
        await s.commit()

    change = {
        "catalogue_source": "tenant",
        "catalogue_id": lean,
        "catalogue_version": number,
        "role_mapping": {"scheduler": "planner"},
    }
    # Another company cannot pin, preview or read this catalogue: to it, it does not exist.
    for method in ("preview_catalogue_change", "change_catalogue"):
        extra = {"actor_id": w.outsider} if method == "change_catalogue" else {}
        async with w.factory() as s:
            with pytest.raises(StaffingError) as foreign:
                await getattr(StaffingService(s), method)(w.project_id, tenant_id=str(w.outsider), **extra, **change)
        assert (foreign.value.code, foreign.value.status_code) == ("unknown_catalogue", 404)

    # The preview says what the change will do, and writes nothing.
    async with w.factory() as s:
        preview = await StaffingService(s).preview_catalogue_change(w.project_id, tenant_id=tenant, **change)
        await s.commit()
    outcomes = {x["position_id"]: (x["outcome"], x["target_role"]) for x in preview["positions"]}
    assert outcomes == {
        str(kept): ("kept", "site_manager"),
        str(mapped): ("mapped", "planner"),
        str(dropped): ("custom", None),
    }
    assert "planner" in {r["code"] for r in preview["target_roles"]}
    assert (await _row(w, StaffingPosition, mapped)).role_code == "scheduler"

    async with w.factory() as s:
        await StaffingService(s).change_catalogue(w.project_id, actor_id=w.manager, tenant_id=tenant, **change)
        await s.commit()
    assert (await _row(w, StaffingPosition, kept)).role_code == "site_manager"
    assert (await _row(w, StaffingPosition, mapped)).role_code == "planner"
    custom = await _row(w, StaffingPosition, dropped)
    assert (custom.role_code, custom.custom_label) == ("custom", "Document controller")

    async with w.factory() as s:
        with pytest.raises(StaffingError) as err:
            await StaffingService(s).change_catalogue(
                w.project_id,
                actor_id=w.manager,
                tenant_id=tenant,
                catalogue_source="shipped",
                catalogue_id="neutral",
                catalogue_version=None,
                role_mapping={"planner": "no_such_role"},
            )
    assert err.value.code == "role_mapping_unknown_target"


async def test_leave_travel_and_accommodation_warnings_reach_the_caller(factory, monkeypatch) -> None:
    from app.modules.accommodation.models import Accommodation, Booking, Room
    from app.modules.project_governance.models import GovernanceGate

    w = await build_world(factory)
    await call(w, "patch_plan", {"requires_accommodation": True}, w.manager)
    person, other = (await members(w))[:2]
    pid = await position(w, "site_manager")
    fid = await fill(w, pid, person.id, to_date=days(60))
    _fill, warnings = await confirm(w, fid)
    # Rule 18: a remote site and no bed on the first day.
    assert "no_accommodation" in {x["code"] for x in warnings}

    async with w.factory() as s:
        camp = Accommodation(project_id=w.project_id, name="Camp")
        s.add(camp)
        await s.flush()
        room = Room(accommodation_id=camp.id, label="B2")
        s.add(room)
        await s.flush()
        s.add(Booking(room_id=room.id, roster_member_id=other.id, check_in=START))
        gate = (
            await s.execute(
                select(GovernanceGate).where(GovernanceGate.project_id == w.project_id, GovernanceGate.code == GATE)
            )
        ).scalar_one()
        gate.target_date = days(30).isoformat()
        await s.commit()
    opid = await position(w, "hse_manager")
    _fill, warnings = await confirm(w, await fill(w, opid, other.id))
    assert "no_accommodation" not in {x["code"] for x in warnings}

    file_id = await personnel_file(w, person.id)
    await call(w, "create_travel", file_id, {"kind": "mobilisation", "depart_date": days(10)}, admin(w))
    await call(
        w, "create_travel", file_id, {"kind": "business", "depart_date": days(50), "return_date": days(70)}, admin(w)
    )
    # Rule 16: leave across the person's own mobilisation.
    _leave, found = await call(
        w, "create_leave", file_id, {"leave_type": "annual", "from_date": days(8), "to_date": days(12)}, admin(w)
    )
    assert [(f["code"], f["detail"]) for f in found] == [("leave_conflicts_gate", "mobilisation")]
    # Rule 16: leave across the gate this key role is required before; the gate is found by its phase tag.
    _leave, found = await call(
        w, "create_leave", file_id, {"leave_type": "annual", "from_date": days(28), "to_date": days(33)}, admin(w)
    )
    assert [(f["code"], f["detail"]) for f in found] == [("leave_conflicts_gate", days(30).isoformat())]

    async with w.factory() as s:
        svc = StaffingService(s)
        view = await svc.file_view(w.project_id, await svc.open_file(w.project_id, file_id, admin(w)), admin(w))
        await s.commit()
    codes = [x["code"] for x in view["warnings"]]
    # Rule 17: a return after the assignment ends. Rule 18 again on the file.
    assert "travel_after_assignment" in codes and "no_accommodation" in codes
    assert codes.count("leave_conflicts_gate") == 2


# ── finding 17: evidence by tag, never fail open ───────────────────────────


async def _evidence(w, area_code: str):
    from app.modules.project_governance.evidence import GateAttempt
    from app.modules.project_governance.models import GovernanceArea, GovernanceGate
    from app.modules.staffing.evidence import plan_ready

    async with w.factory() as s:
        gate = (
            await s.execute(
                select(GovernanceGate).where(GovernanceGate.project_id == w.project_id, GovernanceGate.code == GATE)
            )
        ).scalar_one()
        area = (
            await s.execute(
                select(GovernanceArea).where(
                    GovernanceArea.project_id == w.project_id, GovernanceArea.code == area_code
                )
            )
        ).scalar_one()
        return await plan_ready(s, w.project_id, GateAttempt(gate.id, gate.code, gate.attempt_no), area)


async def test_evidence_is_unknown_when_the_governance_catalogue_does_not_say_where_staffing_lives(
    factory, monkeypatch
) -> None:
    from app.modules.staffing import hosting

    # Every shipped model hosts staffing; a company model need not. This is that model.
    monkeypatch.setattr(hosting, "host", lambda catalogue: None)
    w = await build_world(factory)
    first = sorted(a for a in ("m01_project_management", PERSONNEL_AREA))[0]
    items = await _evidence(w, first)
    assert [(i.state, i.detail) for i in items] == [("unknown", "governance_catalogue_has_no_staffing_area")]
    # Reported once, not under every area of the model.
    assert await _evidence(w, PERSONNEL_AREA) == []


async def test_evidence_follows_the_tags_and_reports_unfilled_key_roles_as_not_met(factory, monkeypatch) -> None:
    w = await build_world(factory)
    assert await _evidence(w, "m01_project_management") == []
    states = {i.code: i.state for i in await _evidence(w, PERSONNEL_AREA)}
    assert states == {"staffing_plan_submitted": "not_met", "staffing_no_errors": "not_met"}

    await submittable_plan(w)
    states = {i.code: i.state for i in await _evidence(w, PERSONNEL_AREA)}
    assert states == {
        "staffing_plan_submitted": "not_met",
        "staffing_no_errors": "met",
        "staffing_key_roles_filled": "not_met",
        # Roles not asked at this gate and still vacant are named to the decider as a warning.
        "staffing_key_roles_open": "warning",
    }
    ready = await call(w, "readiness", GATE)
    assert ready["key_roles_required"] is True and len(ready["key_role_findings"]) == 7


async def test_evidence_is_unknown_when_the_project_has_no_document_row_for_the_host(factory) -> None:
    w = await build_world(factory)
    await drop_frame_document(w)
    items = await _evidence(w, PERSONNEL_AREA)
    assert [(i.code, i.state, i.detail) for i in items] == [
        ("staffing_frame_document_missing", "unknown", "project_has_no_frame_document_for_staffing")
    ]


async def test_the_host_and_the_gate_are_resolved_from_the_shipped_tags(factory) -> None:
    w = await build_world(factory)
    async with w.factory() as s:
        svc = StaffingService(s)
        doc = await svc._resolve_frame_document(w.project_id)
        gates = {g["code"]: g["enabled"] for g in await svc._gates(w.project_id)}
        catalogue = await svc.catalogue_view(w.project_id)
    assert (doc.code, doc.area_code) == (PERSONNEL_FRAME, PERSONNEL_AREA)
    assert "construction_start" in gates[GATE]
    options = {o["tag"]: o["resolvable"] for o in catalogue["required_before_options"]}
    assert options["construction_start"] is True and options["operation"] is False
    assert catalogue["custom_role_code"] == "custom"
    assert catalogue["phases"] == ["development", "execution", "operation"]
    assert [k["code"] for k in catalogue["document_kinds"] if k["takes_fit_flag"]] == [
        "occupational_health_certificate"
    ]


async def test_position_and_fill_capabilities_are_what_the_actions_enforce(factory) -> None:
    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    pid = await position(w, "site_supervisor_civil", exit_date=days(200))
    fid = await fill(w, pid, person.id)
    editor = Actor(w.decider, edit=True)

    async def view(actor):
        return next(p for p in await call(w, "position_views", actor) if p["id"] == str(pid))

    row = await view(editor)
    assert row["can"]["request_resource"] == {
        "allowed": False,
        "reason": "position_not_recruiting",
        "applies": False,
    }
    assert row["can"]["status"]["recruiting"] == {"allowed": True, "reason": None, "applies": True}
    assert row["can"]["status"]["open"]["applies"] is False
    assert (await call(w, "plan_view", editor))["can"]["edit"] == {"allowed": True, "reason": None, "applies": True}
    assert row["can"]["status"]["open"]["reason"] == "already_in_state"
    assert row["fills"][0]["can"]["confirm"]["allowed"] is True
    assert row["fills"][0]["can"]["end"]["reason"] == "fill_not_confirmed"
    assert row["fills"][0]["can"]["delete"]["allowed"] is True
    # The line manager of the position (the world's manager) cannot confirm it; a reader can do nothing.
    own = await view(Actor(w.manager, edit=True))
    assert own["fills"][0]["can"]["confirm"] == {
        "allowed": False,
        "reason": "owner_cannot_confirm_own_fill",
        "applies": True,
    }
    err = await _refused(call(w, "confirm_fill", fid, Actor(w.manager, edit=True)))
    assert (err.code, err.status_code) == ("owner_cannot_confirm_own_fill", 403)
    reader = await view(Actor(w.editor))
    assert reader["can"]["request_resource"]["reason"] == "edit_permission_required"
    assert reader["fills"][0]["can"]["confirm"]["reason"] == "edit_permission_required"
    # The right is missing, the action exists: shown disabled. Ending a proposal does not exist: hidden.
    assert reader["fills"][0]["can"]["confirm"]["applies"] is True
    assert reader["fills"][0]["can"]["end"]["applies"] is False

    await call(w, "set_position_status", pid, "recruiting", w.manager)
    assert (await view(editor))["can"]["request_resource"] == {"allowed": True, "reason": None, "applies": True}
    await call(w, "request_resource", pid, w.manager)
    assert (await view(editor))["can"]["request_resource"]["reason"] == "resource_request_exists"
    await confirm(w, fid)
    row = await view(editor)
    assert row["fills"][0]["can"]["confirm"]["reason"] == "already_in_state"
    assert row["fills"][0]["can"]["end"]["allowed"] is True
    assert row["fills"][0]["can"]["delete"]["reason"] == "fill_not_proposed"
    err = await _refused(call(w, "set_position_status", pid, "recruiting", w.manager))
    assert (err.code, err.status_code) == ("already_in_state", 409)


async def test_a_requirement_no_phase_enables_is_unknown_not_silently_met(factory, monkeypatch) -> None:
    w = await build_world(factory)
    await position(w, "site_manager", required_before="first_power")
    items = {i.code: i for i in await _evidence(w, PERSONNEL_AREA)}
    assert items["staffing_key_roles_unresolved"].state == "unknown"
    assert "first_power" in items["staffing_key_roles_unresolved"].detail


# ── finding 18: spec items ─────────────────────────────────────────────────


async def test_a_recruiting_position_opens_one_resource_request(factory) -> None:
    from app.modules.resources.models import ResourceRequest
    from app.modules.staffing.models import StaffingPosition

    w = await build_world(factory, governance=False)
    pid = await position(w, "site_supervisor_civil", headcount=3, exit_date=days(200))
    err = await _refused(call(w, "request_resource", pid, w.manager))
    assert (err.code, err.status_code) == ("position_not_recruiting", 409)
    await call(w, "set_position_status", pid, "recruiting", w.manager)
    await call(w, "request_resource", pid, w.manager)
    row = await _row(w, StaffingPosition, pid)
    request = await _row(w, ResourceRequest, row.resource_request_id)
    assert (request.project_id, request.quantity, request.status) == (w.project_id, 3, "open")
    assert request.start_at.astimezone(UTC).date() == START
    assert request.end_at.astimezone(UTC).date() == days(200)
    err = await _refused(call(w, "request_resource", pid, w.manager))
    assert (err.code, err.status_code) == ("resource_request_exists", 409)

    undated = await position(w, "quality_manager", entry_date=None)
    await call(w, "set_position_status", undated, "recruiting", w.manager)
    err = await _refused(call(w, "request_resource", undated, w.manager))
    assert (err.code, err.status_code) == ("position_dates_required", 422)


async def test_planned_days_are_working_days_of_the_project_calendar(factory) -> None:
    from app.modules.schedule.service import ScheduleService, compute_duration, get_work_calendar

    w = await build_world(factory, governance=False)
    entry = date.today() - timedelta(days=27)
    pid = await position(w, "site_manager", entry_date=entry, fte="0.50", headcount=2)
    async with w.factory() as s:
        region = await ScheduleService(s).resolve_project_region(w.project_id)
    working = compute_duration(entry.isoformat(), date.today().isoformat(), region)
    assert 0 < working < 28
    row = next(r for r in await call(w, "planned_vs_actual") if r["position_id"] == str(pid))
    assert Decimal(row["planned_fte_days"]) == Decimal(working)
    assert row["working_days"] == working
    assert Decimal(row["hours_per_day"]) == Decimal(str(get_work_calendar(region)["hours_per_day"]))


# ── finding 13: the demo seed, read back through the screens' services ─────


async def _seed_demo(w) -> dict:
    from app.modules.projects.models import Project
    from app.modules.staffing.models import StaffingPlan
    from app.modules.staffing.seed import seed_staffing_demo

    async with w.factory() as s:
        await s.delete(
            (await s.execute(select(StaffingPlan).where(StaffingPlan.project_id == w.project_id))).scalar_one()
        )
        project = await s.get(Project, w.project_id)
        project.metadata_ = {"demo_id": "demo-staffing"}
        project.currency = "CHF"
        await s.commit()
    async with w.factory() as s:
        totals = await seed_staffing_demo(s, [w.project_id])
        await s.commit()
    return totals


async def test_the_seed_writes_no_file_about_an_account_and_logs_nothing_above_info(factory, caplog) -> None:
    import logging

    from app.modules.staffing.models import PersonnelFile, PositionFill
    from app.modules.teams.models import RosterMember
    from tests.pg.governance_fixtures import add_user

    w = await build_world(factory)
    async with w.factory() as s:
        # Somebody else's account in the installation, on no project of ours.
        foreign = await add_user(s, "manager")
        # A real colleague on the roster: the row is linked to an account.
        first = (
            (
                await s.execute(
                    select(RosterMember)
                    .where(RosterMember.project_id == w.project_id)
                    .order_by(RosterMember.created_at, RosterMember.id)
                )
            )
            .scalars()
            .first()
        )
        first.user_id = w.editor
        linked = first.id
        await s.commit()
    with caplog.at_level(logging.INFO, logger="app.modules.staffing"):
        totals = await _seed_demo(w)
    assert totals["projects"] == 1 and totals["fills"] >= 5 and totals["submitted"] == 1
    loud = [r for r in caplog.records if r.name.startswith("app.modules.staffing") and r.levelno > logging.INFO]
    assert [r.getMessage() for r in loud] == []

    async with w.factory() as s:
        files = (await s.execute(select(PersonnelFile).where(PersonnelFile.project_id == w.project_id))).scalars().all()
        fills = (await s.execute(select(PositionFill).where(PositionFill.project_id == w.project_id))).scalars().all()
        people = {
            m.id: m
            for m in (await s.execute(select(RosterMember).where(RosterMember.project_id == w.project_id))).scalars()
        }
    assert files and fills
    assert linked not in {f.roster_member_id for f in files} | {f.roster_member_id for f in fills}
    assert all(people[f.roster_member_id].user_id is None for f in files)
    # Line manager and confirmer are the project owner; the foreign account is on no seeded row.
    positions = await call(w, "position_views", admin(w))
    assert {p["owner_user_id"] for p in positions} == {str(w.manager)}
    assert str(foreign) not in str(positions)


async def test_before_the_gate_into_construction_the_seed_puts_nobody_on_site(factory) -> None:
    from app.modules.credentials.models import Credential
    from app.modules.project_governance.models import GovernanceGate
    from app.modules.staffing.models import StaffingPlan, TravelRecord
    from app.modules.staffing.seed import before_construction

    # The shipped model's gate into the phase that enables the start of construction is not decided.
    w = await build_world(factory)
    today = datetime.now(UTC).date()
    async with w.factory() as s:
        assert await before_construction(s, w.project_id) is True
        gate = (
            await s.execute(
                select(GovernanceGate).where(GovernanceGate.project_id == w.project_id, GovernanceGate.code == GATE)
            )
        ).scalar_one()
        gate.target_date = (today + timedelta(days=21)).isoformat()
        await s.commit()
    assert (await _seed_demo(w))["projects"] == 1

    owner = admin(w)
    positions = await call(w, "position_views", owner)
    site = [p for p in positions if p["phase"] != "development"]
    assert site and all(date.fromisoformat(p["entry_date"]) >= today + timedelta(days=175) for p in site)
    # A site position can have its person named; nobody is assigned to it before the site mobilises.
    starts = [date.fromisoformat(f["from_date"]) for p in site for f in p["fills"]]
    assert starts and min(starts) >= today + timedelta(days=175)
    assert "filled" in {p["status"] for p in positions if p["phase"] == "development"}
    named = {p["role_code"] for p in site if any(f["status"] == "confirmed" for f in p["fills"])}
    assert {"site_manager", "hse_manager"} <= named and "commissioning_manager" not in named
    assert "recruiting" in {p["stored_status"] for p in site}

    async with w.factory() as s:
        plan = (await s.execute(select(StaffingPlan).where(StaffingPlan.project_id == w.project_id))).scalar_one()
        trips = (await s.execute(select(TravelRecord).where(TravelRecord.project_id == w.project_id))).scalars().all()
        creds = (await s.execute(select(Credential).where(Credential.project_id == w.project_id))).scalars().all()
    assert plan.status == "in_review" and plan.commissioning_date == today + timedelta(days=560)
    assert trips and {t.kind for t in trips} == {"mobilisation"}
    assert all(t.depart_date == today + timedelta(days=174) for t in trips)
    assert creds and all(c.issued_at is None or c.issued_at <= today for c in creds)

    # The gate three weeks ahead finds the plan submitted and every key role it asks for named.
    ready = await call(w, "readiness", GATE)
    assert ready["submitted"] is True and ready["errors"] == [] and ready["key_role_findings"] == []
    assert ready["key_roles_required"] is True
    # Key roles this gate does not ask for are still vacant, and named as such.
    assert {"commissioning_manager", "operator_plant_manager"} <= set(ready["open_key_roles"])
    found = await _evidence(w, PERSONNEL_AREA)
    states = {i.code: i.state for i in found}
    assert "not_met" not in states.values() and "unknown" not in states.values()
    assert states["staffing_key_roles_filled"] == "met"
    # One warning for the decider, naming the vacant key roles this gate does not ask for.
    assert [i.detail for i in found if i.state == "warning"] == ["commissioning_manager, operator_plant_manager"]
    matrix = await call(w, "compliance_matrix", owner)
    cells = {c["state"] for row in matrix["items"] for c in row["cells"].values()}
    assert {"valid", "expiring", "missing", "waived"} <= cells


async def test_the_demo_seed_fills_every_list_and_runs_twice_without_duplicating(factory, monkeypatch) -> None:
    from app.modules.credentials.models import Credential
    from app.modules.projects.models import Project
    from app.modules.staffing.models import StaffingPlan, StaffingPosition
    from app.modules.staffing.seed import before_construction, seed_staffing_demo

    # No phase model: the seed tells the story of a site a month into construction.
    w = await build_world(factory, governance=False)
    async with w.factory() as s:
        assert await before_construction(s, w.project_id) is False
    async with w.factory() as s:
        await s.delete(
            (await s.execute(select(StaffingPlan).where(StaffingPlan.project_id == w.project_id))).scalar_one()
        )
        project = await s.get(Project, w.project_id)
        project.metadata_ = {"demo_id": "demo-staffing"}
        project.currency = "CHF"
        await s.commit()
    async with w.factory() as s:
        totals = await seed_staffing_demo(s, [w.project_id])
        await s.commit()
    assert totals["projects"] == 1

    owner = admin(w)
    positions = await call(w, "position_views")
    assert {p["phase"] for p in positions} == {"development", "execution", "operation"}
    assert {"filled", "open", "recruiting"} <= {p["status"] for p in positions}
    assert await call(w, "handover_views")
    # Nothing a submission would refuse: the plan on screen is one a project lead could send to the gate.
    assert [f for f in await call(w, "submission_findings") if f.severity == "error"] == []
    chart = await call(w, "org_chart")
    assert {ph["phase"] for ph in chart["phases"]} == {"development", "execution", "operation"}

    # A reader of the plan gets counts only where the group is too large to name anybody.
    public = await call(w, "compliance_matrix", Actor(w.editor))
    assert all(row["cells"] == {} for row in public["items"])
    assert public["summary"] and all(x["required"] >= public["summary_min_group"] for x in public["summary"])
    assert "occupational_health_certificate" not in {x["document_kind"] for x in public["summary"]}
    matrix = await call(w, "compliance_matrix", owner)
    cells = {c["state"] for row in matrix["items"] for c in row["cells"].values()}
    assert {"valid", "expiring", "missing", "waived"} <= cells
    assert any(row["cleared_to_work"] for row in matrix["items"])
    assert any(not row["cleared_to_work"] for row in matrix["items"])

    files = await call(w, "file_list", owner)
    assert len(files) >= 5 and all(f["can"]["open"]["allowed"] for f in files)
    upcoming = await call(w, "upcoming", owner)
    assert upcoming["expiring"] and upcoming["leave"]
    assert {e["bucket"] for e in upcoming["expiring"]} == {30, 60, 90}
    assert len(upcoming["mobilisations"]) >= 1
    assert all(m["currency"] == "CHF" for m in upcoming["mobilisations"] if m["cost"])
    today = datetime.now(UTC).date()
    assert all(
        today <= date.fromisoformat(m["depart_date"]) <= today + timedelta(days=14) for m in upcoming["mobilisations"]
    )

    async with w.factory() as s:
        svc = StaffingService(s)
        first = next(f for f in files if f["roles"])
        import uuid as _uuid

        pfile = await svc.open_file(w.project_id, _uuid.UUID(first["id"]), owner)
        view = await svc.file_view(w.project_id, pfile, owner)
        log = await svc.access_log(w.project_id, pfile)
        await s.commit()
    assert view["documents"] and log
    # Chronology: nothing is issued after it expires, and nobody starts before the project plan does.
    async with w.factory() as s:
        creds = (await s.execute(select(Credential).where(Credential.project_id == w.project_id))).scalars().all()
        assert creds and all(c.valid_until is None or c.issued_at is None or c.issued_at < c.valid_until for c in creds)
        # Stored status is the derived one: the reminder does not wait for the first nightly sweep.
        assert {c.status for c in creds if c.valid_until and (c.valid_until - today).days <= 20} == {"expiring_soon"}
        count = len(
            (await s.execute(select(StaffingPosition).where(StaffingPosition.project_id == w.project_id))).all()
        )

    async with w.factory() as s:
        again = await seed_staffing_demo(s, [w.project_id])
        await s.commit()
    assert again["projects"] == 0
    async with w.factory() as s:
        assert (
            len((await s.execute(select(StaffingPosition).where(StaffingPosition.project_id == w.project_id))).all())
            == count
        )
