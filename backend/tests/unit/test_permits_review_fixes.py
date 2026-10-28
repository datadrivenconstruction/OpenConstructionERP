# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure pins for the review of the permits module: hosting by tag, evidence states, carry-forward, schemas."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.modules.permits import hosting as hst
from app.modules.permits.catalogue import Period, Validity
from app.modules.permits.conditions import (
    NewCondition,
    OldCondition,
    PermitView,
    ReqView,
    carry_forward,
    handover_readiness,
    paused_until,
    roadmap_readiness,
    start_readiness,
)
from app.modules.permits.evidence import GATE_PROVIDER, to_evidence, unresolved
from app.modules.permits.roadmap import AttemptView, Edge, TimelineInput, derive_state, timeline, unmet_dependencies
from app.modules.permits.schemas import (
    AssignIn,
    ConditionPatch,
    DecisionIn,
    RequirementFromConditionIn,
    RequirementPatch,
)
from app.modules.project_governance.evidence import EVIDENCE_STATES, GateAttempt


def _model(catalogue_id: str):
    """One shipped governance catalogue, parsed by module 1's own loader."""
    from app.modules.project_governance.catalogue_kinds import PHASE_MODEL_KIND, get_catalogue_kind

    return get_catalogue_kind(PHASE_MODEL_KIND).get_shipped(catalogue_id)


# ── finding 1: hosting comes from catalogue tags, at read time ─────────────


@pytest.mark.parametrize(
    ("catalogue_id", "area", "start_phase", "handover_phase"),
    [
        ("neutral", "scope", "construction", "handover"),
        ("hoai_lph", "scope", "lph8", "lph8"),
        ("riba_2020", "scope", "stage5", "stage6"),
        ("aho_heft9", "b", "stufe4", "stufe5"),
        ("elf_module_framework", "m02_contract_management", "execution", "execution"),
    ],
)
def test_areas_and_gates_resolve_from_tags_whatever_the_codes_are(
    catalogue_id: str, area: str, start_phase: str, handover_phase: str
) -> None:
    h = hst.resolve(_model(catalogue_id))
    assert h.has_model and h.roadmap_area == area and h.conditions_area == area and h.doc_type
    assert "start" in h.gates(start_phase) and {"site_start", "construction"} <= set(h.enables(start_phase))
    assert "handover" in h.gates(handover_phase) and "occupation" in h.enables(handover_phase)
    first = _model(catalogue_id).phases[0].code
    assert h.gates(first) == () and h.gates(None) == ()


def test_one_phase_may_be_both_the_start_and_the_handover() -> None:
    h = hst.resolve(_model("hoai_lph"))
    assert h.gates("lph8") == ("start", "handover")
    assert h.enables("lph9") == ("operation",)


def test_a_project_override_wins_over_the_tag_and_no_model_resolves_to_nothing() -> None:
    h = hst.resolve(_model("neutral"), "mine", "theirs")
    assert (h.roadmap_area, h.conditions_area) == ("mine", "theirs")
    none = hst.resolve(None)
    assert none.roadmap_area is None and none.doc_type is None and not none.phases_tagged and not none.has_model


def test_the_capability_and_the_permit_vocabulary_are_mapped_not_assumed_equal() -> None:
    from app.modules.project_governance.public import host_subjects, phase_capabilities

    assert set(hst.PHASE_ROLES) <= set(phase_capabilities())
    assert hst.SUBJECT in host_subjects()
    assert hst.PHASE_ROLES["handover"].enables == ("occupation",)


def test_an_unresolved_provider_answers_unknown_with_the_reason() -> None:
    attempt = GateAttempt(gate_id=uuid.uuid4(), gate_code="g_build", attempt_no=1)
    item = unresolved(GATE_PROVIDER, attempt, "no_area_hosts_permits", uuid.uuid4())
    assert item.state == "unknown" and item.detail == "no_area_hosts_permits"
    assert item.label_key == "permits.evidence.unresolved.no_area_hosts_permits"


# ── finding 2: at risk is never met; an early start covers only what it runs ahead of ──


def test_the_gate_screen_can_open_every_permits_evidence_item() -> None:
    from app.modules.permits.evidence import register_gate_evidence
    from app.modules.project_governance.evidence import evidence_link_href, unregister_evidence_link

    pid = uuid.uuid4()
    attempt = GateAttempt(gate_id=uuid.uuid4(), gate_code="g_build", attempt_no=1)
    unregister_evidence_link("permits")
    assert evidence_link_href("permits", str(pid), pid) is None
    register_gate_evidence()
    for item in (
        unresolved(GATE_PROVIDER, attempt, "no_phase_enables_tag", pid),
        to_evidence({"items": []}, "c", "l", pid),
    ):
        kind, link_id = item.link
        assert evidence_link_href(kind, link_id, pid) == f"/projects/{pid}/permits"


def test_a_warning_reaches_the_gate_in_the_detail_and_does_not_block() -> None:
    from datetime import date as day
    from types import SimpleNamespace as Gate

    from app.modules.permits.evidence import needed_from

    due = {"code": "permit_due_later", "state": "warning", "detail": "Road 2027-04-05", "ref": "r"}
    granted = {"code": "permit_granted", "state": "met", "detail": "P"}
    from app.modules.permits import evidence as ev

    pid = uuid.uuid4()
    # The check itself is met: the warning is not folded into it, it is an item of its own.
    item = to_evidence({"items": [granted, due]}, "c", "l", pid)
    assert (item.state, item.detail) == ("met", "")
    (said,) = ev.warnings({"items": [granted, due]}, "g_build", pid)
    assert said.code == "permits_due_later:g_build:r" and said.detail == "Road 2027-04-05"
    assert said.label_key == "permits.evidence.permit_due_later" and said.link == ("permits", str(pid))
    # The state is ``warning`` as soon as the governance module serves it; before that the item is
    # met and still says what is outstanding. It is never a blocker.
    assert said.state == ("warning" if "warning" in EVIDENCE_STATES else "met")
    missing = {"code": "permit_missing", "state": "not_met", "detail": "Crane", "ref": "r"}
    both = to_evidence({"items": [missing, due]}, "c", "l", pid)
    assert (both.state, both.detail) == ("not_met", "permit_missing:Crane")
    assert len(ev.warnings({"items": [missing, due]}, "g_build", pid)) == 1
    assert ev.warnings({"items": [missing, granted]}, "g_build", pid) == []
    # The check is made for the gate's target date, never for a day already past, on the server's day.
    today = day(2026, 10, 13)
    assert needed_from(Gate(target_date=day(2026, 11, 2)), today) == day(2026, 11, 2)
    assert needed_from(Gate(target_date=day(2026, 9, 1)), today) == today
    assert needed_from(Gate(target_date=None), today) is None
    assert needed_from(None, today) is None


def test_at_risk_reaches_the_gate_as_not_met_with_a_detail() -> None:
    assert "at_risk" not in EVIDENCE_STATES
    readiness = {"items": [{"code": "start_at_risk_early_start", "state": "at_risk", "detail": "Permit", "ref": "r"}]}
    item = to_evidence(readiness, "permits_start:g", "permits.evidence.start", uuid.uuid4())
    assert item.state == "not_met" and item.detail == "at_risk start_at_risk_early_start:Permit"
    met = to_evidence({"items": [{"code": "x", "state": "met", "detail": ""}]}, "c", "l", uuid.uuid4())
    assert met.state == "met" and met.detail == ""


def test_an_early_start_of_one_permit_does_not_cover_another_or_a_refusal() -> None:
    building = ReqView("r1", "baugenehmigung", "building", "full", ("site_start",), "refused", title="Building")
    water = ReqView("r3", "wasserrecht", "water", "full", ("site_start",), "in_progress", title="Water")
    early = PermitView(
        "p2", "r2", "wr_8a", "early_start", "early_start", "in_force", ("site_start",), (), ("wasserrecht",)
    )
    items = {i.ref: i for i in start_readiness([building, water], [early], []).items}
    assert (items["r1"].code, items["r1"].state) == ("permit_missing", "not_met")
    assert (items["r3"].code, items["r3"].state) == ("start_at_risk_early_start", "at_risk")
    refused = ReqView("r3", "wasserrecht", "water", "full", ("site_start",), "refused")
    assert start_readiness([refused], [early], []).items[0].code == "permit_missing"


# ── finding 7: variation carry-forward ─────────────────────────────────────


def test_variation_carries_waiver_breach_pending_discharge_and_keeps_proposals_unconfirmed() -> None:
    old = [
        OldCondition("c1", "1", "Text one.", "obligation", "ongoing", "waived"),
        OldCondition("c2", "2", "Text two.", "obligation", "ongoing", "breach"),
        OldCondition("c3", "3", "Text three.", "suspensive", "before_start", "discharge_applied"),
        OldCondition("c4", "4", "Proposed.", "obligation", "ongoing", "open", confirmed=False),
        OldCondition("c5", "5", "Evidence in.", "obligation", "ongoing", "evidence_submitted"),
    ]
    new = [NewCondition("2", "Text two, reworded.", "obligation", "ongoing")]
    out = {c.number: c for c in carry_forward(old, new)}
    assert out["1"].keep_state == "waived"
    assert out["2"].keep_state == "breach" and out["2"].replaced
    assert out["3"].keep_state == "discharge_applied"
    assert out["4"].confirmed is False and out["4"].keep_state is None
    assert out["5"].keep_state == "evidence_submitted"
    reworded = carry_forward(old[:1], [NewCondition("1", "Other text.", "obligation", "ongoing")])[0]
    assert reworded.keep_state is None and reworded.confirmed


# ── finding 8: a permit that is no longer in force is not a granted requirement ──


def test_a_favourable_decision_without_a_live_permit_is_not_granted() -> None:
    dead = AttemptView("decided", "granted", permit_live=False)
    assert derive_state(True, dead, True) == "not_in_force"
    assert derive_state(True, AttemptView("decided", "partially_granted", permit_live=False), True) == "not_in_force"
    assert derive_state(True, AttemptView("decided", "refused", permit_live=False), True) == "refused"
    edges = [Edge("b", "a", "granted"), Edge("c", "a", "submitted")]
    assert unmet_dependencies("b", edges, {"a": "not_in_force"}, {}) == ["a"]
    occ = ReqView("r9", "occ", "occupancy", "full", ("occupation",), "not_in_force")
    assert handover_readiness([occ], [], []).status == "not_ready"
    assert roadmap_readiness([occ], ("occupation",)).status == "not_ready"


# ── finding 10: rule 19 (filed, not prepared) and rule 9 (interruption) ────


def test_a_requirement_still_being_prepared_is_not_filed() -> None:
    preparing = ReqView("r1", "x", "building", "full", ("site_start",), "in_progress", submitted=False)
    assert roadmap_readiness([preparing], ("site_start",)).status == "not_ready"
    filed = ReqView("r1", "x", "building", "full", ("site_start",), "in_progress", submitted=True)
    assert roadmap_readiness([filed], ("site_start",)).status == "ready"


def test_an_interrupted_permit_lapses_after_the_catalogue_period() -> None:
    v = Validity(
        lapse_if_not_started=Period(period=3, unit="years"),
        lapse_if_paused=Period(period=1, unit="years"),
        source_url="https://example.invalid/x",
        review_status="unconfirmed",
    )
    assert paused_until(date(2026, 5, 1), v) == date(2027, 5, 1)
    no_pause = Validity(
        lapse_if_not_started=Period(period=3, unit="years"),
        source_url="https://example.invalid/x",
        review_status="unconfirmed",
    )
    assert paused_until(date(2026, 5, 1), no_pause) is None and paused_until(date(2026, 5, 1), None) is None


# ── finding 14: a granted requirement raises no schedule conflict ──────────


def test_a_settled_requirement_has_no_schedule_conflict() -> None:
    late = date(2026, 9, 10)
    open_row = TimelineInput("x", date(2026, 9, 1), "fixed_date", 30, forecast=late)
    assert timeline([open_row], [])[0].schedule_conflict
    settled = TimelineInput("x", date(2026, 9, 1), "fixed_date", 30, forecast=late, settled=True)
    (row,) = timeline([settled], [])
    assert not row.schedule_conflict and row.conflict_days == 0 and row.forecast == late


# ── findings 11, 12, 20: request bodies ────────────────────────────────────


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (RequirementPatch, {"title": None}),
        (RequirementPatch, {"clock_variant": None}),
        (ConditionPatch, {"topic": None}),
        (ConditionPatch, {"kind": None}),
    ],
)
def test_an_explicit_null_on_a_not_null_field_is_refused(model, body) -> None:
    with pytest.raises(ValidationError) as exc:
        model(**body)
    assert "field_not_nullable" in str(exc.value)


def test_a_nullable_field_may_be_cleared_and_an_absent_field_is_not_touched() -> None:
    assert RequirementPatch(planned_submit_date=None).model_dump(exclude_unset=True) == {"planned_submit_date": None}
    assert RequirementPatch().model_dump(exclude_unset=True) == {}


def test_ids_are_uuids_and_the_constraint_type_is_closed() -> None:
    with pytest.raises(ValidationError):
        AssignIn(condition_ids=["abc"], owner_user_id=str(uuid.uuid4()))
    with pytest.raises(ValidationError):
        RequirementPatch(responsible_user_id="abc")
    with pytest.raises(ValidationError):
        RequirementFromConditionIn(entity="site", attribute="noise", constraint_type="whatever")


def test_a_security_amount_needs_its_currency_and_the_reverse() -> None:
    base = {"outcome": "granted", "decision_date": date(2026, 10, 1)}
    with pytest.raises(ValidationError) as exc:
        DecisionIn(**base, security_amount="1000.00")
    assert "security_needs_amount_and_currency" in str(exc.value)
    with pytest.raises(ValidationError):
        DecisionIn(**base, security_currency="EUR")
    assert DecisionIn(**base, security_amount="1000.00", security_currency="EUR").security_currency == "EUR"
