# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Allowed moves of the logistics plan: the flags come from the guards the writes call.

The agreement of a flag with the write it describes is proven on real rows in
``tests/pg/test_site_logistics_can_on_pg.py``. Here: the shape, the guards
without a database, that every write calls its guard, and that a flag asks for
the permission its route requires.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from app.modules.site_logistics import plan_service, router
from app.modules.site_logistics import planning as pl
from app.modules.site_logistics.messages import translate
from app.modules.site_logistics.plan_service import LogisticsPlanService, PlanPerms

ALL = PlanPerms(write=True, approve=True, customs=True)
WRITER = PlanPerms(write=True)
READER = PlanPerms()
PID = uuid.uuid4()

OK = {"allowed": True, "applies": True, "reason": None}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _no(reason: str, applies: bool = True) -> dict:
    return {"allowed": False, "applies": applies, "reason": reason}


def _can(kind: str, row, perms: PlanPerms = ALL, **loaded) -> dict:
    return _run(LogisticsPlanService(None).can(PID, kind, row, perms, **loaded))


def _permit(state: str, **kw) -> SimpleNamespace:
    return SimpleNamespace(state=state, valid_from=kw.get("valid_from"), valid_to=kw.get("valid_to"))


# ── shape ────────────────────────────────────────────────────────────────────


def test_a_flag_says_whether_the_action_exists_would_pass_and_why_not() -> None:
    assert plan_service._flag(True) == OK
    assert plan_service._flag(True, "permit_frozen") == _no("permit_frozen")
    assert plan_service._flag(False) == _no("permission_denied")
    # No permission is said before the state of the record is.
    assert plan_service._flag(False, "permit_frozen") == _no("permission_denied")
    assert plan_service._flag(True, "invalid_transition", applies=False) == _no("invalid_transition", applies=False)
    assert plan_service._flag(False, "invalid_transition", applies=False) == _no("permission_denied", applies=False)


def test_every_reason_a_flag_can_carry_has_a_message() -> None:
    for code in (
        "permission_denied",
        "invalid_transition",
        "stage_active",
        "last_stage",
        "contracted_capacity_required",
        "transport_closed",
        "transport_under_way",
        "goods_receipt_missing",
        "validity_required",
        "permit_frozen",
        "customs_closed",
        "customs_declared",
        "required_document_missing",
        "customs_without_lines",
        "incoterm_unknown",
        "complaint_closed",
        "response_required",
        "unknown_link_kind",
    ):
        for locale in ("en", "de"):
            key = f"site_logistics.errors.{code}"
            assert translate(key, locale=locale) != key, (code, locale)


# ── guards without a database ────────────────────────────────────────────────


def test_a_draft_permit_can_be_applied_for_and_nothing_else() -> None:
    can = _can("permit", _permit("draft"))
    assert can["edit"] == OK and can["delete"] == OK and can["frozen_fields"] == []
    assert can["transitions"]["applied"] == OK
    assert can["transitions"]["granted"] == _no("invalid_transition", applies=False)
    assert set(can["transitions"]) == set(pl.PERMIT_FSM) - {"draft"}


def test_a_permit_is_granted_only_with_its_validity() -> None:
    assert _can("permit", _permit("applied"))["transitions"]["granted"] == _no("validity_required")
    dated = _permit("applied", valid_from=date(2026, 5, 4), valid_to=date(2026, 5, 8))
    assert _can("permit", dated)["transitions"]["granted"] == OK
    assert _can("permit", dated)["transitions"]["refused"] == OK


def test_a_granted_permit_is_frozen_and_stays() -> None:
    can = _can("permit", _permit("granted"))
    assert can["delete"] == _no("permit_frozen")
    assert can["frozen_fields"] == sorted([*plan_service._PERMIT_FROZEN_FIELDS, "covers_transport_ids"])
    # The notes of a granted permit can still be written.
    assert can["edit"] == OK


def test_without_the_permission_every_flag_says_so() -> None:
    can = _can("permit", _permit("granted"), READER)
    assert can["edit"] == can["delete"] == _no("permission_denied")
    assert can["transitions"]["expired"] == _no("permission_denied")
    # An action the record does not have stays marked so; the route still answers with the permission first.
    assert can["transitions"]["applied"] == _no("permission_denied", applies=False)


def test_a_transport_under_way_keeps_what_it_was_checked_against() -> None:
    row = SimpleNamespace(state="arrived", direction="outbound", po_id=None)
    can = _can("transport", row, cat=object())
    assert can["edit"] == OK
    assert set(plan_service._TRANSPORT_FREE_FIELDS).isdisjoint(can["frozen_fields"])
    assert "planned_window_start" in can["frozen_fields"]
    assert can["delete"] == _no("transport_under_way")
    assert can["transitions"]["closed"] == OK
    closed = _can("transport", SimpleNamespace(state="closed", direction="outbound", po_id=None), cat=object())
    assert closed["edit"] == _no("transport_closed")
    assert all(not f["applies"] for f in closed["transitions"].values())


def test_moving_a_transport_is_a_manager_decision() -> None:
    row = SimpleNamespace(state="arrived", direction="outbound", po_id=None)
    can = _can("transport", row, WRITER, cat=object())
    assert can["edit"] == OK
    assert can["transitions"]["closed"] == _no("permission_denied")


def test_a_media_connection_is_contracted_only_with_a_capacity() -> None:
    assert _can("media", SimpleNamespace(state="offered", contracted_capacity=None))["transitions"] == {
        "identified": _no("invalid_transition", applies=False),
        "requested": OK,
        "contracted": _no("contracted_capacity_required"),
        "connected": _no("invalid_transition", applies=False),
        "disconnected": _no("invalid_transition", applies=False),
    }


def test_a_complaint_closes_only_with_a_response_and_then_stays_closed() -> None:
    open_ = _can("complaint", SimpleNamespace(state="acknowledged", response="  "))
    assert open_["transitions"]["action_taken"] == _no("response_required")
    assert open_["transitions"]["closed"] == _no("response_required")
    assert open_["edit"] == OK
    answered = _can("complaint", SimpleNamespace(state="acknowledged", response="Night work moved."))
    assert answered["transitions"]["closed"] == OK
    assert _can("complaint", SimpleNamespace(state="closed", response="x"))["edit"] == _no("complaint_closed")


def test_a_demand_of_a_plant_position_keeps_its_number() -> None:
    assert _can("demand", SimpleNamespace(site_plant_position_id=uuid.uuid4()))["frozen_fields"] == ["peak_demand"]
    assert _can("demand", SimpleNamespace(site_plant_position_id=None))["frozen_fields"] == []


def test_a_customs_case_follows_its_documents_lines_and_state() -> None:
    svc = LogisticsPlanService(None)

    # A case as the service reads it: its state, and the incoterm it was opened under,
    # which the move to ``declared`` looks up in the catalogue.
    def a_case(state: str) -> SimpleNamespace:
        return SimpleNamespace(state=state, id=uuid.uuid4(), incoterm="DAP", incoterm_version="2020")

    catalogue = SimpleNamespace(incoterm_version="2020", entry=lambda group, code: {"code": code})
    case = a_case("open")
    missing = [{"kind": "commercial_invoice", "required": True, "state": "missing"}]
    there = [{"kind": "commercial_invoice", "required": True, "state": "received"}]
    assert pl.missing_required(missing) and not pl.missing_required(there)

    def can(row, docs, lines):
        return _run(svc.can(PID, "customs", row, ALL, cat=catalogue, docs=docs, line_count=lines))

    assert can(case, missing, 1)["transitions"]["documents_complete"] == _no("required_document_missing")
    assert can(case, there, 0)["transitions"]["documents_complete"] == _no("customs_without_lines")
    assert can(case, there, 1)["transitions"]["documents_complete"] == OK
    assert can(case, there, 1)["add_line"] == OK

    declared = can(a_case("declared"), there, 1)
    assert declared["delete"] == declared["add_line"] == _no("customs_declared")
    assert declared["frozen_fields"] == sorted(plan_service._CUSTOMS_CHECKLIST_FIELDS)
    assert declared["edit"] == OK
    held = can(a_case("held"), there, 1)
    # A held case may still receive what customs asked for.
    assert held["add_document"] == OK and held["add_line"] == _no("customs_declared")
    cleared = can(a_case("cleared"), there, 1)
    assert cleared["edit"] == cleared["add_document"] == _no("customs_closed")


def test_lines_and_documents_follow_their_case() -> None:
    line = SimpleNamespace(customs_case_id=uuid.uuid4())
    doc = SimpleNamespace(customs_case_id=line.customs_case_id, state="received", required=True)
    open_case, held, declared = (SimpleNamespace(state=s) for s in ("open", "held", "declared"))
    assert _can("line", line, case=open_case) == {"edit": OK, "delete": OK}
    assert _can("line", line, case=held)["edit"] == _no("customs_declared")
    on_hold = _can("document", doc, case=held)
    assert on_hold["edit"] == OK and on_hold["transitions"]["verified"] == OK
    # What the case was declared on is not taken back while it is held.
    assert on_hold["transitions"]["missing"] == _no("customs_declared")
    assert _can("document", doc, case=open_case)["transitions"]["missing"] == OK
    shut = _can("document", doc, case=declared)
    assert shut["edit"] == _no("customs_declared")
    assert all(f == _no("customs_declared") for f in shut["transitions"].values())


def test_a_stage_in_use_or_the_last_one_is_not_deleted() -> None:
    assert _can("stage", SimpleNamespace(state="active"), count=3)["delete"] == _no("stage_active")
    assert _can("stage", SimpleNamespace(state="planned"), count=1)["delete"] == _no("last_stage")
    can = _can("stage", SimpleNamespace(state="planned"), count=2)
    assert can["delete"] == OK and can["transitions"] == {"active": OK, "closed": _no("invalid_transition", False)}


def test_records_without_states_carry_edit_and_delete() -> None:
    for kind in ("area", "coordination"):
        assert _can(kind, None) == {"edit": OK, "delete": OK}
        assert _can(kind, None, READER)["delete"] == _no("permission_denied")
    assert _can("neighbourhood", None) == {"edit": OK}
    assert _can("concept", None, WRITER) == {"edit": OK, "pin_catalogue": _no("permission_denied")}
    assert LogisticsPlanService(None).can_create("transport", WRITER) == {"create": OK}
    assert LogisticsPlanService(None).can_create("transport", READER) == {"create": _no("permission_denied")}


# ── the writes call the guards the flags ask ─────────────────────────────────

WRITE_GUARDS = {
    "delete_stage": "_guard_stage_delete",
    "transition_media": "_guard_media_transition",
    "update_demand": "_demand_frozen",
    "update_transport": "_transport_frozen",
    "delete_transport": "_guard_transport_delete",
    "transition_transport": "_guard_transport_transition",
    "update_permit": "_permit_frozen",
    "transition_permit": "_guard_permit_transition",
    "delete_permit": "_guard_permit_delete",
    "update_customs": "_customs_frozen",
    "delete_customs": "_guard_customs_delete",
    "transition_customs": "_guard_customs_transition",
    "_open_case": "_guard_case_open",
    "update_document": "_guard_document_move",
    "update_complaint": "_guard_complaint_edit",
    "transition_complaint": "_guard_complaint_transition",
    "transition_stage": "_move",
    "_move": "_guard_move",
}


@pytest.mark.parametrize(("write", "guard"), sorted(WRITE_GUARDS.items()))
def test_the_write_calls_the_guard_the_flag_asks(write: str, guard: str) -> None:
    source = inspect.getsource(getattr(LogisticsPlanService, write))
    assert f"self.{guard}(" in source, write
    asked = inspect.getsource(LogisticsPlanService.can) + inspect.getsource(LogisticsPlanService.can_in_case)
    if guard != "_move":
        assert f"self.{guard}(" in asked, guard


def test_no_guard_changes_the_record_it_judges() -> None:
    judged = 0
    for name, member in inspect.getmembers(LogisticsPlanService):
        if name.startswith("_guard_") or name.endswith("_frozen"):
            judged += 1
            assert not re.search(r"^\s*(row|case)\.\w+\s*=[^=]", inspect.getsource(member), flags=re.M), name
    assert judged >= 15


def test_lines_and_documents_change_only_through_the_open_case() -> None:
    for write in ("create_line", "update_line", "delete_line", "add_document", "update_document"):
        assert "self._open_case(" in inspect.getsource(getattr(LogisticsPlanService, write)), write


# ── a flag asks for the permission its route requires ────────────────────────

KIND_OF = {
    "stages": "stage",
    "areas": "area",
    "media": "media",
    "demands": "demand",
    "concept": "concept",
    "transports": "transport",
    "permits": "permit",
    "customs": "customs",
    "customs-lines": "line",
    "customs-documents": "document",
    "neighbourhood": "neighbourhood",
    "neighbour-issues": "complaint",
    "coordination": "coordination",
}
NESTED = {"demands": "demand", "lines": "line", "documents": "document"}
# Writes that are not an action on one plan record.
NOT_A_RECORD = ("/allocations", "/plant-positions/power-demand", "/validate", "/sweep")


def _action_of(route: APIRoute) -> tuple[str, str] | None:
    tail = route.path.split("/projects/{project_id}/", 1)[1]
    if any(route.path.endswith(x) for x in NOT_A_RECORD):
        return None
    parts = tail.split("/")
    method = next(iter(route.methods & {"POST", "PUT", "PATCH", "DELETE"}))
    if parts[0] == "catalogue":
        return "concept", "pin_catalogue"
    kind = NESTED.get(parts[-1]) or KIND_OF[parts[0]]
    if parts[-1] == "transition":
        return kind, "transition"
    return kind, {"POST": "create", "PUT": "edit", "PATCH": "edit", "DELETE": "delete"}[method]


def _plan_writes() -> list[APIRoute]:
    return [
        r
        for r in router.router.routes
        if isinstance(r, APIRoute)
        and "/projects/{project_id}/" in r.path
        and r.methods & {"POST", "PUT", "PATCH", "DELETE"}
    ]


@pytest.mark.parametrize("route", _plan_writes(), ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
def test_a_flag_asks_for_the_permission_of_its_route(route: APIRoute) -> None:
    action = _action_of(route)
    if action is None:
        return
    required = {p for d in route.dependant.dependencies if (p := getattr(d.call, "permission", None))}
    assert required == {plan_service.can_permission(*action)}, (route.path, action)


def test_every_write_route_of_a_record_is_an_action_a_flag_knows() -> None:
    seen = {a for r in _plan_writes() if (a := _action_of(r)) is not None}
    assert ("transport", "transition") in seen and ("concept", "pin_catalogue") in seen
    for kind, action in plan_service._CAN_PERMISSION:
        assert (kind, action) in seen, (kind, action)
    # Each kind the routes write is a kind ``can`` answers for.
    for kind in {k for k, _ in seen}:
        row = SimpleNamespace(
            state="x", site_plant_position_id=None, customs_case_id=None, response="", contracted_capacity=None
        )
        loaded = {"cat": object(), "docs": [], "line_count": 0, "count": 2, "case": SimpleNamespace(state="open")}
        assert "edit" in _can(kind, row, **loaded), kind


def test_the_permissions_of_the_caller_are_read_like_the_routes_read_them() -> None:
    perms = _run(router._plan_perms({"role": "viewer", "permissions": ["site_logistics.write"]}))
    assert perms == PlanPerms(write=True, approve=False, customs=False)
    assert _run(router._plan_perms({"role": "admin", "permissions": []})) == ALL


def test_every_record_route_returns_can() -> None:
    """A handler that serializes a plan record passes it through ``_with_can`` (or the transport body)."""
    for route in router.router.routes:
        if not isinstance(route, APIRoute) or "/projects/{project_id}/" not in route.path:
            continue
        source = inspect.getsource(route.endpoint)
        serializes = any(
            f"{name}_out(" in source
            for name in (
                "stage",
                "area",
                "media",
                "demand",
                "permit",
                "customs",
                "line",
                "document",
                "complaint",
                "coordination",
                "neighbourhood",
                "plan_concept",
            )
        )
        # The export writes a file from the read models; it serves no record to act on.
        if route.path.endswith(("/allocations", "/plant-positions/power-demand", "/export/{register}")):
            continue
        if serializes or "transport_view(" in source:
            assert "_with_can(" in source or "_transport_body(" in source, route.path


# ── gates, laydown zones and deliveries ──────────────────────────────────────


def _board_service(monkeypatch: pytest.MonkeyPatch, refusal: str | None = None):
    from app.modules.site_logistics import service as board

    svc = board.SiteLogisticsService.__new__(board.SiteLogisticsService)
    asked: list[str] = []

    async def approvable(self, project_id, **kw):
        asked.append("approvable")
        if refusal is not None:
            raise board._refusal(refusal, f"{refusal}: refused")

    monkeypatch.setattr(board.SiteLogisticsService, "_assert_approvable", approvable)
    return svc, asked


def _delivery(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=PID,
        status=status,
        gate_id=None,
        gross_weight_t=None,
        transport_id=None,
        window_start=None,
        window_end=None,
    )


def test_a_requested_delivery_can_be_approved_or_rejected_by_a_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    svc, asked = _board_service(monkeypatch)
    can = _run(svc.can_delivery(_delivery("requested"), ALL))
    assert can == {"edit": OK, "delete": OK, "approve": OK, "reject": OK}
    assert asked == ["approvable"], "the flag asked the check the approval runs"
    theirs = _run(svc.can_delivery(_delivery("requested"), WRITER))
    assert theirs["edit"] == OK and theirs["approve"] == theirs["reject"] == _no("permission_denied")


def test_the_approve_flag_carries_the_code_of_the_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    for code in ("gate_load_exceeded", "delivery_rate_exceeded", "slot_taken", "site_timezone_missing"):
        svc, _ = _board_service(monkeypatch, code)
        can = _run(svc.can_delivery(_delivery("requested"), ALL))
        assert can["approve"] == _no(code) and can["reject"] == OK


def test_a_decided_or_arrived_delivery_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    svc, asked = _board_service(monkeypatch)
    approved = _run(svc.can_delivery(_delivery("approved"), ALL))
    assert approved["approve"] == _no("invalid_transition", applies=False) and approved["reject"] == OK
    assert asked == []
    rejected = _run(svc.can_delivery(_delivery("rejected"), ALL))
    assert rejected["reject"] == _no("invalid_transition", applies=False) and rejected["approve"] == OK
    for status in ("arrived", "completed"):
        done = _run(svc.can_delivery(_delivery(status), ALL))
        assert done["approve"] == done["reject"] == _no("delivery_already_on_site"), status


def test_the_board_writes_call_the_guards_their_flags_ask() -> None:
    from app.modules.site_logistics.service import SiteLogisticsService

    assert "self._guard_approve(delivery)" in inspect.getsource(SiteLogisticsService.approve_delivery)
    assert "self._guard_decision(delivery" in inspect.getsource(SiteLogisticsService.reject_delivery)
    flag = inspect.getsource(SiteLogisticsService.can_delivery)
    assert "self._guard_approve(delivery)" in flag and "self._guard_decision(delivery" in flag
    for code in ("delivery_already_on_site", "outside_gate_hours", "slot_taken", "delivery_refused"):
        for locale in ("en", "de"):
            assert translate(f"site_logistics.errors.{code}", locale=locale) != f"site_logistics.errors.{code}"


def test_gates_zones_and_the_board_follow_the_write_permission() -> None:
    from app.modules.site_logistics.service import SiteLogisticsService

    assert SiteLogisticsService.can_plain(WRITER) == {"edit": OK, "delete": OK}
    assert SiteLogisticsService.can_plain(READER)["delete"] == _no("permission_denied")
    assert SiteLogisticsService.can_board(WRITER) == {k: {"create": OK} for k in ("gate", "zone", "delivery")}


BOARD_PERMISSION = {"approve_delivery": "approve", "reject_delivery": "approve"}


def test_board_flags_ask_for_the_permission_of_their_routes() -> None:
    seen = set()
    for route in router.router.routes:
        if not isinstance(route, APIRoute) or "/projects/{project_id}/" in route.path:
            continue
        if not route.path.startswith(("/gates", "/laydown-zones", "/deliveries")) or route.methods <= {"GET"}:
            continue
        required = {p for d in route.dependant.dependencies if (p := getattr(d.call, "permission", None))}
        name = route.endpoint.__name__
        assert required == {f"site_logistics.{BOARD_PERMISSION.get(name, 'write')}"}, name
        seen.add(name)
        if "DELETE" not in route.methods:
            assert "perms" in inspect.signature(route.endpoint).parameters, name
    assert {"approve_delivery", "reject_delivery", "update_gate", "update_zone", "update_delivery"} <= seen
