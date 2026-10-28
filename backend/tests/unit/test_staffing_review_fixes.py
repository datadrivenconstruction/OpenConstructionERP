# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pins for the defects an independent review found in staffing, the parts that need no database.

Each test names the behaviour it pins. Imports of the code under test sit
inside the tests, so a missing symbol fails that one test and not the file.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

MODULE_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "staffing"
D = date


def _pos(**kw):
    base = {
        "id": uuid.uuid4(),
        "role_code": "site_manager",
        "phase": "execution",
        "key_role": False,
        "handover_role": False,
        "required_before": None,
        "entry_date": D(2027, 1, 1),
        "exit_date": None,
        "fte": Decimal("1"),
        "headcount": 1,
        "status": "open",
    }
    return {**base, **kw}


def _fill(position, **kw):
    base = {
        "id": uuid.uuid4(),
        "position_id": position["id"],
        "roster_member_id": uuid.uuid4(),
        "fte_share": Decimal("1"),
        "from_date": D(2027, 1, 1),
        "to_date": None,
        "status": "confirmed",
    }
    return {**base, **kw}


# ── finding 9: numeric scale and range ─────────────────────────────────────


@pytest.mark.parametrize("fte", ["0.004", "0.125", "0.999"])
def test_an_fte_with_more_than_two_decimals_is_refused_not_rounded(fte) -> None:
    from app.modules.staffing import rules

    assert rules.position_errors(fte, 1, None, None) == ["fte_precision"]
    assert rules.fill_share_error(fte, D(2027, 1, 1), None) == "fte_precision"


def test_two_decimal_fte_values_still_pass() -> None:
    from app.modules.staffing import rules

    assert rules.position_errors("0.25", 1, None, None) == []
    assert rules.position_errors(Decimal("1.00"), 3, None, None) == []
    assert rules.fill_share_error("0.5", D(2027, 1, 1), None) is None


def test_headcount_has_an_upper_bound() -> None:
    from app.modules.staffing import rules

    assert rules.position_errors("1", rules.MAX_HEADCOUNT, None, None) == []
    assert rules.position_errors("1", rules.MAX_HEADCOUNT + 1, None, None) == ["headcount_invalid"]


@pytest.mark.parametrize("cost", ["-1", "10.001", "1000000000000", "abc", 12.5])
def test_a_cost_outside_the_column_is_refused(cost) -> None:
    from app.modules.staffing import rules

    assert rules.money_error(cost) == "cost_invalid"


@pytest.mark.parametrize("cost", ["0", "380.00", "999999999999.99", Decimal("12.5")])
def test_a_cost_the_column_can_hold_passes(cost) -> None:
    from app.modules.staffing import rules

    assert rules.money_error(cost) is None


def test_schema_bounds_headcount_and_sort_order() -> None:
    from app.modules.staffing.schemas import PositionIn

    for bad in ({"headcount": 0}, {"headcount": 10**9}, {"sort_order": 2**31}, {"sort_order": -1}):
        with pytest.raises(ValidationError):
            PositionIn.model_validate({"role_code": "site_manager", "phase": "execution", **bad})


# ── finding 10: explicit null on a non-nullable field ──────────────────────


@pytest.mark.parametrize(
    "field", ["title", "notes", "custom_label", "key_role", "handover_role", "sort_order", "fte", "headcount"]
)
def test_patch_position_with_an_explicit_null_is_a_validation_error(field) -> None:
    from app.modules.staffing.schemas import PositionPatch

    with pytest.raises(ValidationError):
        PositionPatch.model_validate({field: None})


def test_patch_position_may_still_clear_the_nullable_fields() -> None:
    from app.modules.staffing.schemas import PositionPatch

    body = PositionPatch.model_validate({"exit_date": None, "recruiting_channel": None, "required_before": None})
    assert body.model_dump(exclude_unset=True) == {
        "exit_date": None,
        "recruiting_channel": None,
        "required_before": None,
    }


# ── finding 3 and the lead decision: write routes take no client date ──────


def test_ending_a_file_or_a_fill_takes_no_date_from_the_client() -> None:
    from app.modules.staffing import schemas

    assert not hasattr(schemas, "FileEnd")
    assert not hasattr(schemas, "FillEnd")


def test_a_fill_ends_today_or_on_its_first_day_when_it_never_began() -> None:
    from app.modules.staffing import rules

    assert rules.fill_end_date(D(2027, 1, 1), D(2027, 3, 1)) == D(2027, 3, 1)
    assert rules.fill_end_date(D(2027, 5, 1), D(2027, 3, 1)) == D(2027, 5, 1)


# ── findings 2 and 4: a document is recorded, not linked ───────────────────


def test_the_document_request_cannot_name_a_credential() -> None:
    from app.modules.staffing.schemas import DocumentLink

    with pytest.raises(ValidationError):
        DocumentLink.model_validate({"document_kind": "work_permit", "credential_id": str(uuid.uuid4())})
    body = DocumentLink.model_validate({"document_kind": "work_permit", "valid_until": "2027-05-01"})
    assert body.valid_until == D(2027, 5, 1)


def test_personnel_credential_types_are_closed_to_the_general_register() -> None:
    from app.modules.credentials.schemas import CREDENTIAL_TYPES, PERSONNEL_CREDENTIAL_TYPES

    assert {"work_permit", "identity_document", "visa", "occupational_health"} <= set(PERSONNEL_CREDENTIAL_TYPES)
    assert set(PERSONNEL_CREDENTIAL_TYPES) <= set(CREDENTIAL_TYPES)
    # Types the site register always held stay open: a qualification is not a private document.
    assert not {"certification", "training", "professional_license"} & set(PERSONNEL_CREDENTIAL_TYPES)


def test_every_special_category_or_numbered_identity_kind_maps_to_a_closed_type() -> None:
    from app.modules.credentials.schemas import PERSONNEL_CREDENTIAL_TYPES
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind
    from app.modules.staffing.catalogue import STAFFING_MODEL_KIND, register_kinds

    register_kinds()
    for cat in get_catalogue_kind(STAFFING_MODEL_KIND).shipped():
        for kind in cat.document_kinds:
            if kind.special_category:
                assert kind.credential_type in PERSONNEL_CREDENTIAL_TYPES, (cat.id, kind.code)


# ── finding 1: the access decision is one function with a reason ───────────


@pytest.mark.parametrize(
    ("relation", "read", "edit", "want_edit", "expected"),
    [
        ("self", False, False, False, (True, None)),
        ("self", False, False, True, (False, "own_file_read_only")),
        ("self", True, True, True, (False, "own_file_read_only")),
        ("area_owner", True, False, False, (True, None)),
        ("area_owner", True, False, True, (False, "personnel_permission_missing")),
        ("position_owner", True, True, True, (True, None)),
        ("position_owner", False, False, False, (False, "personnel_permission_missing")),
        (None, True, True, False, (False, "no_relationship_to_person")),
        (None, True, True, True, (False, "no_relationship_to_person")),
    ],
)
def test_file_access_needs_the_relationship_whatever_the_permissions(relation, read, edit, want_edit, expected) -> None:
    from app.modules.staffing import rules

    assert rules.file_access(relation, can_read=read, can_edit=edit, edit=want_edit) == expected


def test_the_actor_carries_booleans_and_no_role_string() -> None:
    from app.modules.staffing.service import Actor

    actor = Actor(uuid.uuid4())
    assert not hasattr(actor, "payload") and not hasattr(actor, "is_admin")
    assert (actor.personnel_read, actor.personnel_edit, actor.personnel_erase) == (False, False, False)
    assert (actor.assign_owner, actor.manage) == (False, False)


def test_no_staffing_source_compares_a_role_string() -> None:
    for path in MODULE_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert '"admin"' not in text, path.name
        assert '.get("role")' not in text, path.name


# ── findings 7 and 11: state machines ──────────────────────────────────────


def test_a_legal_hold_exists_only_on_an_ended_file() -> None:
    from app.modules.staffing.fsm import FILE_FSM

    assert not FILE_FSM.has_transition("active", "retention_hold")
    assert FILE_FSM.has_transition("ended", "retention_hold")
    assert FILE_FSM.has_transition("retention_hold", "ended")


def test_a_proposed_fill_is_deleted_never_ended() -> None:
    from app.modules.staffing.fsm import FILL_FSM

    assert not FILL_FSM.has_transition("proposed", "ended")
    assert FILL_FSM.has_transition("confirmed", "ended")


# ── finding 14: a handover to its own position ─────────────────────────────


def test_a_handover_to_the_position_of_its_own_fill_does_not_satisfy_rule_6() -> None:
    from app.modules.staffing import rules

    catalogue = SimpleNamespace(roles=())
    giver = _pos(handover_role=True)
    fill = _fill(giver)
    own = [{"id": uuid.uuid4(), "from_fill_id": fill["id"], "to_position_id": giver["id"], "overlap_days": 30}]
    codes = [f.code for f in rules.submission_findings(catalogue, [giver], [fill], own, None)]
    assert codes == ["handover_missing"]

    receiver = _pos()
    real = [{"id": uuid.uuid4(), "from_fill_id": fill["id"], "to_position_id": receiver["id"], "overlap_days": 30}]
    assert rules.submission_findings(catalogue, [giver, receiver], [fill], real, None) == []


# ── finding 17: neutrality ─────────────────────────────────────────────────


def _governance(catalogue_id: str):
    from app.modules.project_governance.catalogue import get_catalogue

    return get_catalogue(catalogue_id)


def test_the_host_of_staffing_is_read_from_the_shipped_governance_tags() -> None:
    from app.modules.staffing import hosting

    elf = hosting.host(_governance("elf_module_framework"))
    assert (elf.area_code, elf.doc_type) == ("m05_personnel", "m05_personnel_frame")
    neutral = hosting.host(_governance("neutral"))
    assert (neutral.area_code, neutral.doc_type) == ("resources", "resource_plan")
    assert hosting.enabled_by(_governance("neutral"), "construction") == frozenset({"construction_start"})
    assert {"construction_start", "handover"} <= hosting.enabled_by(_governance("elf_module_framework"), "execution")
    assert "operation" not in hosting.enabled_tags(_governance("elf_module_framework"))
    assert "operation" in hosting.enabled_tags(_governance("neutral"))


def test_no_governance_model_resolves_nothing_instead_of_guessing() -> None:
    from app.modules.staffing import hosting

    assert hosting.host(None) is None
    assert hosting.enabled_by(None, "execution") == frozenset()
    assert hosting.enabled_tags(None) == frozenset()
    assert hosting.enabled_by(_governance("neutral"), "no_such_phase") == frozenset()


def test_evidence_is_unknown_once_when_the_module_has_data_but_the_model_hosts_it_nowhere() -> None:
    from app.modules.staffing import evidence

    assert evidence.applies(None, "a_money", "a_money", has_data=True) == (
        True,
        "governance_catalogue_has_no_staffing_area",
    )
    assert evidence.applies(None, "a_people", "a_money", has_data=True) == (False, "")
    assert evidence.applies(None, "a_money", "a_money", has_data=False) == (False, "")


def test_evidence_is_asked_of_the_hosting_area_only() -> None:
    from app.modules.staffing import evidence

    cat = _governance("elf_module_framework")
    assert evidence.applies(cat, "m05_personnel", "m01_project_management", has_data=True) == (True, "")
    assert evidence.applies(cat, "m01_project_management", "m01_project_management", has_data=True) == (False, "")


def test_a_missing_document_row_is_unknown_and_nothing_else_is_read() -> None:
    from app.modules.staffing import evidence

    ready = {
        "status": "draft",
        "submitted": False,
        "frame_document_missing": True,
        "frame_required": False,
        "errors": [],
        "key_roles_required": False,
        "key_role_findings": [],
        "unresolved_tags": [],
    }
    items = evidence.items(ready, ("staffing", "p"))
    assert [(i.code, i.state, i.detail) for i in items] == [
        ("staffing_frame_document_missing", "unknown", "project_has_no_frame_document_for_staffing")
    ]
    assert items[0].label_key == "staffing.evidence.frame_document_missing"


def test_capabilities_name_the_refusal_the_action_would_answer() -> None:
    from app.modules.staffing import rules

    plan = rules.plan_action_refusal
    assert plan("submit", "draft", can_edit=True) is None
    assert plan("submit", "draft", can_edit=False) == "edit_permission_required"
    assert plan("submit", "draft", can_edit=True, has_frame_document=False) == "frame_document_missing"
    assert plan("submit", "in_review", can_edit=True) == "plan_not_editable"
    assert plan("return", "draft", can_edit=True) == "plan_not_in_review"
    assert plan("return", "in_review", can_edit=True) is None
    assert plan("change_catalogue", "in_review", can_edit=True) == "plan_in_review"
    assert plan("change_catalogue", "binding", can_edit=True) is None

    move = rules.position_status_refusal
    assert move("open", "recruiting", "draft", can_edit=True, transition_exists=True) is None
    assert move("open", "open", "draft", can_edit=True, transition_exists=False) == "already_in_state"
    assert move("cancelled", "open", "draft", can_edit=True, transition_exists=False) == "invalid_transition"
    assert move("open", "recruiting", "in_review", can_edit=True, transition_exists=True) == "plan_in_review"
    assert move("open", "filled", "draft", can_edit=True, transition_exists=False) == "status_is_derived"

    ask = rules.resource_request_refusal
    day = D(2027, 1, 1)
    assert ask("recruiting", has_request=False, entry_date=day, exit_date=day, can_edit=True) is None
    assert ask("open", has_request=False, entry_date=day, exit_date=day, can_edit=True) == "position_not_recruiting"
    assert (
        ask("recruiting", has_request=True, entry_date=day, exit_date=day, can_edit=True) == "resource_request_exists"
    )
    assert (
        ask("recruiting", has_request=False, entry_date=day, exit_date=None, can_edit=True) == "position_dates_required"
    )

    fill = rules.fill_action_refusal
    assert fill("confirm", "proposed", "draft", can_edit=True) is None
    assert fill("confirm", "proposed", "draft", can_edit=True, confirms_own_position=True) == (
        "owner_cannot_confirm_own_fill"
    )
    assert fill("confirm", "proposed", "draft", can_edit=True, anonymised=True) == "fill_anonymised"
    assert fill("confirm", "confirmed", "draft", can_edit=True) == "already_in_state"
    assert fill("confirm", "ended", "draft", can_edit=True) == "invalid_transition"
    assert fill("end", "proposed", "draft", can_edit=True) == "fill_not_confirmed"
    assert fill("end", "ended", "draft", can_edit=True) == "already_in_state"
    assert fill("delete", "confirmed", "draft", can_edit=True) == "fill_not_proposed"
    assert fill("end", "confirmed", "in_review", can_edit=True) == "plan_in_review"


def test_every_unknown_evidence_item_has_its_own_code_and_a_sentence_in_both_languages() -> None:
    import json

    for name in ("en", "de"):
        bundle = json.loads((MODULE_DIR / "messages" / f"{name}.json").read_text(encoding="utf-8"))
        for key in ("area_unknown", "frame_document_missing", "key_roles_unresolved", "key_roles_open"):
            text = bundle[f"staffing.evidence.{key}"]
            # A sentence that says what to do, not a label.
            assert text.endswith(".") and len(text.split()) > 10, (name, key)
        assert bundle["staffing.evidence.nothing_due"]


def test_a_country_gets_the_shipped_staffing_catalogue_that_claims_it_through_the_port(monkeypatch) -> None:
    from app.modules.project_governance import catalogue_packs
    from app.modules.project_governance import public as governance
    from app.modules.staffing.catalogue import STAFFING_MODEL_KIND, register_kinds

    register_kinds()
    # No pack opinion: the answer comes from the shipped files alone.
    monkeypatch.setattr(
        catalogue_packs, "pack_default_candidates", lambda kind, country=None, subdivision_code=None: ()
    )
    for country, expected in (("DE", "de"), ("gb", "uk"), ("US", "us")):
        pin = governance.default_catalogue_pin(STAFFING_MODEL_KIND, country)
        assert (pin.source, pin.catalogue_id) == ("shipped", expected)
    # Nobody claims the country, or there is none: the module pins its neutral file.
    assert governance.default_catalogue_pin(STAFFING_MODEL_KIND, "FR") is None
    assert governance.default_catalogue_pin(STAFFING_MODEL_KIND, None) is None
    # The module keeps no country rule of its own.
    from app.modules.staffing import catalogue

    assert not hasattr(catalogue, "default_catalogue_id_for_country")


def test_the_hosting_area_always_gets_an_answer() -> None:
    from app.modules.staffing import evidence

    ready = {
        "status": "draft",
        "submitted": False,
        "frame_document_missing": False,
        "frame_required": False,
        "errors": [],
        "key_roles_required": False,
        "key_role_findings": [],
        "unresolved_tags": [],
        "open_key_roles": [],
    }
    assert [(i.code, i.state) for i in evidence.items(ready, ("staffing", "p"))] == [("staffing_nothing_due", "met")]
    # A vacant key role the gate does not ask for is one warning that names the roles; it replaces the fallback.
    vacant = {**ready, "open_key_roles": ["commissioning_manager", "operator_plant_manager"]}
    assert [(i.code, i.state, i.detail) for i in evidence.items(vacant, ("staffing", "p"))] == [
        ("staffing_key_roles_open", "warning", "commissioning_manager, operator_plant_manager")
    ]


def test_the_evidence_link_of_the_module_opens_the_staffing_screen() -> None:
    from app.modules.project_governance.evidence import evidence_link_href
    from app.modules.staffing.evidence import LINK_KIND, register_gate_evidence

    register_gate_evidence()
    assert evidence_link_href(LINK_KIND, "ignored", "p1") == "/projects/p1/staffing"


def test_a_flag_applies_by_the_state_of_the_record_and_never_by_a_right() -> None:
    from app.modules.staffing import rules

    # The line manager on a proposed fill of their own position: the action exists, they may not take it.
    own = rules.fill_action_refusal("confirm", "proposed", "draft", can_edit=True, confirms_own_position=True)
    assert rules.capability(own, None) == {
        "allowed": False,
        "reason": "owner_cannot_confirm_own_fill",
        "applies": True,
    }
    # A reader on an already confirmed fill: refused for the right, and the action does not exist anyway.
    reader = rules.fill_action_refusal("confirm", "confirmed", "draft", can_edit=False)
    by_state = rules.fill_action_refusal("confirm", "confirmed", "draft", can_edit=True)
    assert rules.capability(reader, by_state) == {
        "allowed": False,
        "reason": "edit_permission_required",
        "applies": False,
    }
    assert rules.capability(None, None) == {"allowed": True, "reason": None, "applies": True}
    # A precondition somebody can still meet is shown, not hidden.
    for fixable in ("plan_in_review", "frame_document_missing", "position_dates_required", "retention_hold_active"):
        assert rules.capability(fixable, fixable)["applies"] is True
    for gone in ("plan_not_in_review", "position_not_recruiting", "file_not_held", "file_not_active", "own_file_only"):
        assert rules.capability(gone, gone)["applies"] is False
    assert rules.plan_action_refusal("edit", "in_review", can_edit=True) == "plan_in_review"
    assert rules.plan_action_refusal("edit", "binding", can_edit=True) is None
    assert rules.plan_action_refusal("edit", "draft", can_edit=False) == "edit_permission_required"


def test_a_key_role_that_enters_after_the_gate_is_asked_to_be_named_not_to_be_there() -> None:
    from app.modules.staffing import rules

    gate_day = D(2027, 3, 1)
    later = _pos(key_role=True, required_before="construction_start", entry_date=D(2027, 8, 1))
    named = [{**_fill(later), "from_date": D(2027, 8, 1)}]
    assert rules.key_role_gate_findings([later], named, {"construction_start"}, gate_day) == []
    assert len(rules.key_role_gate_findings([later], [], {"construction_start"}, gate_day)) == 1
    # Named, but only from a month after the position starts: still a gap on its first day.
    late = [{**_fill(later), "from_date": D(2027, 9, 1)}]
    assert len(rules.key_role_gate_findings([later], late, {"construction_start"}, gate_day)) == 1
    # A position already running on the gate's day is asked on the gate's day, as before.
    early = _pos(key_role=True, required_before="construction_start", entry_date=D(2027, 1, 1))
    gone = [{**_fill(early), "from_date": D(2027, 1, 1), "to_date": D(2027, 2, 1)}]
    assert len(rules.key_role_gate_findings([early], gone, {"construction_start"}, gate_day)) == 1

    vacant = _pos(key_role=True, required_before=None, role_code="commissioning_manager")
    assert rules.open_key_positions([later, vacant], named, {"construction_start"}) == ["commissioning_manager"]


async def test_an_emptied_bus_gets_the_staffing_handlers_again() -> None:
    from app.core.events import event_bus
    from app.modules.staffing import events

    names = ("project_governance.frame_document.state_changed", "credentials.expiry.alert")
    saved = {n: list(event_bus._handlers.get(n, [])) for n in names}
    seen: list[dict] = []

    async def record(data: dict, **_kw) -> bool:
        seen.append(data)
        return True

    real = events.handle_frame_document
    events.handle_frame_document = record
    try:
        events.register_staffing_subscribers()
        for n in names:
            event_bus._handlers[n] = []
        events.register_staffing_subscribers()
        assert events._on_frame_document in event_bus._handlers[names[0]]
        assert events._on_expiry_alert in event_bus._handlers[names[1]]
        await event_bus.publish(names[0], {"status": "binding", "document_id": "x"}, source_module="test")
        assert seen == [{"status": "binding", "document_id": "x"}]
        # Registering twice subscribes once.
        events.register_staffing_subscribers()
        assert event_bus._handlers[names[0]].count(events._on_frame_document) == 1
    finally:
        events.handle_frame_document = real
        for n in names:
            event_bus._handlers[n] = saved[n]


def test_a_catalogue_change_keeps_maps_or_frees_a_role() -> None:
    from app.modules.staffing import rules

    outcome = rules.catalogue_change_outcome
    assert outcome("a", "custom", {}, ["a", "b"]) == ("kept", "a")
    assert outcome("a", "custom", {"a": "b"}, ["a", "b"]) == ("mapped", "b")
    assert outcome("gone", "custom", {}, ["a"]) == ("custom", None)
    assert outcome("custom", "custom", {"custom": "a"}, ["a"]) == ("kept", "custom")


def test_the_compliance_summary_counts_states_and_leaves_special_categories_out() -> None:
    from app.modules.staffing import rules

    today = D(2027, 1, 1)
    valid = {"status": "active", "valid_until": D(2028, 1, 1), "waived": False}
    people = [
        {"required": ["permit", "health"], "documents": {"permit": valid, "health": valid}},
        {"required": ["permit", "health"], "documents": {}},
        {"required": [], "documents": {}},
    ]
    # Three people are too few to count; the same three with a threshold of two are counted.
    assert rules.compliance_summary(people, ["permit", "health"], ["health"], today) == []
    assert rules.compliance_summary(people * 2, ["permit", "health"], ["health"], today, min_group=5) == []
    summary = rules.compliance_summary(people, ["permit", "health"], ["health"], today, min_group=2)
    assert summary == [
        {
            "document_kind": "permit",
            "required": 2,
            "uniform": False,
            "valid": 1,
            "expiring": 0,
            "expired": 0,
            "missing": 1,
            "waived": 0,
        }
    ]
    # Five withheld people who all lack the permit: a split would say "missing" of each of them by name.
    lacking = [{"required": ["permit"], "documents": {}} for _ in range(5)]
    assert rules.compliance_summary(lacking, ["permit"], [], today) == [
        {"document_kind": "permit", "required": 5, "uniform": True}
    ]
    mixed = [*lacking, {"required": ["permit"], "documents": {"permit": valid}}]
    assert rules.compliance_summary(mixed, ["permit"], [], today)[0]["missing"] == 5
    assert rules.compliance_cell(False, None, today) == {"state": "not_required"}
    soon = {"status": "expiring_soon", "valid_until": D(2027, 1, 11), "waived": False}
    assert rules.compliance_cell(True, soon, today) == {"state": "expiring", "days": 10}


def test_evidence_items_never_report_an_unresolved_requirement_as_met() -> None:
    from app.modules.staffing import evidence

    link = ("staffing", "p")
    ready = {
        "status": "in_review",
        "submitted": True,
        "frame_document_missing": False,
        "frame_required": True,
        "errors": [],
        "key_roles_required": False,
        "key_role_findings": [],
        "unresolved_tags": ["construction_start"],
    }
    items = {i.code: i for i in evidence.items(ready, link)}
    assert items["staffing_plan_submitted"].state == "met"
    assert items["staffing_key_roles_unresolved"].state == "unknown"
    assert "construction_start" in items["staffing_key_roles_unresolved"].detail
    assert "staffing_key_roles_filled" not in items

    ready = {**ready, "unresolved_tags": [], "key_roles_required": True, "key_role_findings": [{"detail": "x"}]}
    assert {i.code: i.state for i in evidence.items(ready, link)}["staffing_key_roles_filled"] == "not_met"


def test_key_roles_are_matched_by_what_the_gate_enables_not_by_a_gate_code() -> None:
    from app.modules.staffing import rules

    key = _pos(key_role=True, required_before="construction_start")
    other = _pos(key_role=True, required_before="handover")
    found = rules.key_role_gate_findings([key, other], [], {"construction_start"}, D(2027, 6, 1))
    assert [f.ref for f in found] == [str(key["id"])]
    assert rules.key_role_gate_findings([key], [_fill(key)], {"construction_start"}, D(2027, 6, 1)) == []
    assert rules.key_role_gate_findings([key, other], [], set(), D(2027, 6, 1)) == []


def test_no_governance_code_is_written_into_the_module_or_its_catalogues() -> None:
    literal = re.compile(r"m0\d_|development_to_execution|execution_to_|_to_execution")
    for path in [*MODULE_DIR.glob("*.py"), *(MODULE_DIR / "catalogues").glob("*.json")]:
        hits = literal.findall(path.read_text(encoding="utf-8"))
        assert not hits, (path.name, hits[:3])


def test_roles_name_what_must_be_enabled_and_the_catalogue_names_no_area() -> None:
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind
    from app.modules.staffing.catalogue import STAFFING_MODEL_KIND, Role, StaffingModelCatalogue, register_kinds

    assert "required_before" in Role.model_fields and "required_by_gate" not in Role.model_fields
    assert "governance_area" not in StaffingModelCatalogue.model_fields
    register_kinds()
    neutral = next(c for c in get_catalogue_kind(STAFFING_MODEL_KIND).shipped() if c.id == "neutral")
    assert neutral.role("site_manager").required_before == "construction_start"


def test_a_tenant_role_prints_its_own_label_in_the_export() -> None:
    from app.modules.staffing import export as ex
    from app.modules.staffing.catalogue import Organisation, Role

    catalogue = SimpleNamespace(
        roles=(Role(code="crane_boss", organisation="yard", phases=("execution",), labels={"en": "Crane boss"}),),
        organisations=(Organisation(code="yard", labels={"en": "Yard team", "de": "Platzteam"}),),
        document_kinds=(),
        leave_types=(),
    )
    position = {
        "role_code": "crane_boss",
        "custom_label": "",
        "organisation": "yard",
        "phase": "execution",
        "fte": "1.00",
        "headcount": 1,
        "entry_date": None,
        "exit_date": None,
        "status": "open",
        "fills": [],
    }
    doc = ex.plan_document([position], catalogue=catalogue, project_name="P", locale="de")
    assert doc.rows[0][0] == "Crane boss"
    assert doc.rows[0][1] == "Platzteam"


# ── finding 18: spec items ─────────────────────────────────────────────────


def _retention_catalogue(*actions: str):
    rules_ = {f"r{i}": SimpleNamespace(code=f"r{i}", action=a) for i, a in enumerate(actions)}
    kinds = {f"k{i}": SimpleNamespace(code=f"k{i}", retention_rule=f"r{i}") for i in range(len(actions))}
    return SimpleNamespace(
        document_kind=kinds.get,
        retention_rule=rules_.get,
        default_retention_rule="r0",
    )


def test_the_retention_action_of_the_rules_decides_between_delete_and_anonymise() -> None:
    from app.modules.staffing import rules

    both_delete = _retention_catalogue("delete", "delete")
    mixed = _retention_catalogue("delete", "anonymise")
    docs = [{"document_kind": "k0"}, {"document_kind": "k1"}]
    assert rules.retention_action(both_delete, docs) == "delete"
    # One rule that keeps the anonymous record wins: deleting would destroy what it asks to keep.
    assert rules.retention_action(mixed, docs) == "anonymise"
    # No documents: the default rule.
    assert rules.retention_action(mixed, []) == "delete"


def test_the_own_file_export_carries_everything_the_person_may_ask_for() -> None:
    from app.modules.staffing import export as ex

    catalogue = SimpleNamespace(roles=(), organisations=(), document_kinds=(), leave_types=())
    view = {
        "name": "A Person",
        "status": "ended",
        "employer_organisation": "Builder Ltd",
        "employment_basis": "posted_worker",
        "lawful_basis": "contract",
        "retention_due_at": "2029-01-01",
        "documents": [
            {
                "document_kind": "occupational_health_certificate",
                "valid_until": "2027-01-01",
                "status": "active",
                "fit_for_role": "with_restrictions",
            }
        ],
        "accommodation": [{"accommodation": "Camp", "room": "B2", "check_in": "2026-01-01", "status": "confirmed"}],
        "travel": [],
        "leave": [],
    }
    doc = ex.own_file_document(view, catalogue=catalogue, locale="en")
    details = dict(doc.details)
    flat = " | ".join(str(c) for row in doc.rows for c in row)
    assert "Builder Ltd" in details.values()
    assert "2029-01-01" in details.values()
    assert len(details) >= 6
    assert "Camp" in flat and "B2" in flat
    assert "with restrictions" in flat.lower()


def test_every_error_code_the_module_raises_has_a_message_in_each_bundle() -> None:
    import json

    pattern = re.compile(r'(?:StaffingError|conflict|forbidden|not_found)\(\s*"([a-z0-9_]+)"')
    codes: set[str] = set()
    for name in ("service.py", "router.py", "rules.py"):
        codes |= set(pattern.findall((MODULE_DIR / name).read_text(encoding="utf-8")))
    codes |= {"fte_precision", "headcount_invalid", "cost_invalid", "own_file_read_only"}
    codes |= {"personnel_permission_missing", "no_relationship_to_person", "already_in_state"}
    for bundle in ("en", "de"):
        messages = json.loads((MODULE_DIR / "messages" / f"{bundle}.json").read_text(encoding="utf-8"))
        missing = sorted(c for c in codes if f"staffing.errors.{c}" not in messages)
        assert not missing, (bundle, missing)


def test_a_plan_is_approved_by_hand_only_where_no_gates_are_in_use() -> None:
    from app.modules.staffing import rules

    assert rules.plan_action_refusal("submit", "draft", can_edit=True, has_frame_document=False) == (
        "frame_document_missing"
    )
    assert (
        rules.plan_action_refusal("submit", "draft", can_edit=True, has_frame_document=False, gates_in_use=False)
        is None
    )

    def approve(status: str = "in_review", **kw: bool) -> str | None:
        asked = {"can_manage": True, "gates_in_use": False, "four_eyes": True, "is_submitter": False} | kw
        return rules.plan_approval_refusal(status, **asked)

    assert approve() is None
    assert approve(gates_in_use=True) == "approved_by_gate_decision"
    assert approve("draft") == "plan_not_in_review"
    assert approve(can_manage=False) == "approval_permission_required"
    assert approve(is_submitter=True) == "approver_is_submitter"
    assert approve(is_submitter=True, four_eyes=False) is None
    # With gates, or outside review, the control is hidden; a missing right or the same person shows it disabled.
    assert rules.capability(approve(gates_in_use=True), approve(gates_in_use=True))["applies"] is False
    assert rules.capability(approve("binding"), approve("binding"))["applies"] is False
    assert rules.capability(approve(is_submitter=True), approve())["applies"] is True
