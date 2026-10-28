"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What a caller may do, answered by the function that refuses the request.

The ``can`` flags of the API and the refusals of the service read the same
functions in ``capabilities``. These tests pin the answers and pin that the
service does not carry a second copy of a rule.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.quality_concept import capabilities as caps
from app.modules.quality_concept import schemas, seed, vocab

MODULE = Path(caps.__file__).parent
ALICE, BOB = uuid.uuid4(), uuid.uuid4()
EDITOR = caps.Caller(ALICE, edit=True)
MANAGER = caps.Caller(BOB, edit=True, manage=True, waive=True)
VIEWER = caps.Caller(uuid.uuid4())


def _proof(caller: caps.Caller, **facts) -> dict:
    base = {
        "concept_state": "draft",
        "decision": "none",
        "requested_by": None,
        "rationale": "",
        "delivery_state": "open",
        "evidence_authors": [],
        "four_eyes": True,
    }
    return caps.proof(caller, **{**base, **facts})


def test_a_waiver_is_decided_by_a_second_person_who_holds_the_permission() -> None:
    pending = {"requested_by": ALICE, "rationale": "Supplier tested"}
    # Nothing was asked for: neither approve nor reject is offered.
    assert _proof(MANAGER)["can_reason"]["decide_waiver"] == "waiver_not_requested"
    # The editor asked; the editor holds no waive permission.
    assert _proof(EDITOR, **pending)["can_reason"]["decide_waiver"] == "waive_required"
    assert _proof(MANAGER, **pending)["can"]["decide_waiver"] is True
    # Four eyes: the manager who asked cannot decide; without four eyes they can.
    own = {"requested_by": BOB, "rationale": "Not issued"}
    assert _proof(MANAGER, **own)["can_reason"]["decide_waiver"] == "approver_is_requester"
    assert _proof(MANAGER, **own, four_eyes=False)["can"]["decide_waiver"] is True
    # A decided proof has no request pending.
    assert _proof(MANAGER, **pending, decision="waived")["can_reason"]["decide_waiver"] == "invalid_transition"
    assert caps.waiver_decision_refusal("none", ALICE, "   ", BOB, True) == "waiver_not_requested"


def test_proof_flags_say_why_not_and_carry_no_reason_when_allowed() -> None:
    out = _proof(EDITOR)
    assert set(out) == {"can", "can_reason"}
    assert out["can"]["request_waiver"] is True and "request_waiver" not in out["can_reason"]
    assert out["can_reason"]["edit"] == "manage_required"
    assert out["can_reason"]["accept"] == "proof_not_delivered"
    assert out["can_reason"]["reopen"] == "invalid_transition"
    delivered = _proof(EDITOR, delivery_state="delivered", evidence_authors=[BOB])
    assert delivered["can"]["accept"] is True
    # Whoever attached the evidence does not also accept it.
    assert _proof(EDITOR, delivery_state="delivered", evidence_authors=[ALICE])["can_reason"]["accept"] == (
        "approver_added_evidence"
    )
    assert _proof(EDITOR, decision="accepted")["can"]["reopen"] is True
    assert set(_proof(VIEWER)["can"].values()) == {False}
    # The plan of a bound concept changes only through a change request.
    assert _proof(MANAGER, concept_state="binding")["can_reason"]["edit"] == "binding_requires_change_request"
    assert _proof(MANAGER, concept_state="in_review")["can_reason"]["delete"] == "concept_not_editable"
    assert _proof(MANAGER)["can"]["edit"] is True


def test_stage_flags_follow_the_state_machine_and_the_hold_gate() -> None:
    def flags(state: str, computed: str | None = None, gate: str | None = None, caller=EDITOR) -> dict:
        return caps.stage_progress(caller, state=state, computed_state=computed or state, gate_status=gate)

    # A blocked row whose preconditions are now met opens: opening a test refreshes the state first.
    assert flags("blocked", "ready")["can"]["open_test"] is True
    assert flags("blocked")["can_reason"]["open_test"] == "invalid_transition"
    assert flags("in_test")["can"]["record_pass"] is True and flags("in_test")["can"]["record_fail"] is True
    # A pass the service would refuse for missing evidence is not offered either.
    unproven = caps.stage_progress(
        EDITOR, state="in_test", computed_state="in_test", gate_status=None, pass_refusal="stage_evidence_missing"
    )
    assert unproven["can_reason"]["record_pass"] == "stage_evidence_missing" and unproven["can"]["record_fail"] is True
    assert flags("ready")["can_reason"]["request_release"] == "stage_not_passed"
    assert flags("passed")["can"]["request_release"] is True
    assert flags("passed", gate="pending")["can_reason"]["request_release"] == "release_already_requested"
    assert flags("stale", gate="released")["can"]["request_release"] is True
    # Release itself is never offered here: the hold gate decides it in construction control.
    assert "release" not in flags("passed")["can"]
    assert flags("ready")["can_reason"]["not_applicable"] == "manage_required"
    assert flags("ready", caller=MANAGER)["can"]["not_applicable"] is True
    assert flags("not_applicable", caller=MANAGER)["can"]["reinstate"] is True
    assert flags("released", caller=MANAGER)["can_reason"]["reinstate"] == "invalid_transition"


def test_acceptance_flags_know_preconditions_dates_and_the_deemed_date() -> None:
    def flags(state: str, caller=MANAGER, **facts) -> dict:
        base = {"concept_state": "binding", "has_regime": True, "blocked": False, "deemed_due": False}
        return caps.acceptance_unit(caller, state=state, **{**base, **facts})

    assert flags("planned")["can"]["request"] is True
    assert flags("planned", blocked=True)["can_reason"]["request"] == "acceptance_preconditions_unmet"
    assert flags("planned", has_regime=False)["can_reason"]["request"] == "acceptance_regime_missing"
    assert flags("requested")["can_reason"]["request"] == "invalid_transition"
    assert flags("requested")["can_reason"]["confirm_deemed"] == "deemed_acceptance_not_due"
    assert flags("requested", deemed_due=True)["can"]["confirm_deemed"] is True
    assert flags("requested", EDITOR, deemed_due=True)["can_reason"]["confirm_deemed"] == "manage_required"
    assert flags("accepted")["can_reason"]["record_dates"] == "unit_dates_locked"
    assert flags("requested", EDITOR)["can"]["record_dates"] is True
    assert flags("requested")["can_reason"]["confirm_effect"] == "unit_not_accepted"
    assert flags("deemed_accepted")["can"]["confirm_effect"] is True
    # Accepting is the handover act's matter, never a button of this module.
    assert "accept" not in flags("requested")["can"]
    # The unit is part of the bound plan, but the act is linked afterwards.
    assert flags("planned")["can_reason"]["edit"] == "binding_requires_change_request"
    assert flags("planned")["can"]["link_handover"] is True


def test_survey_certification_and_credit_flags() -> None:
    planned = caps.survey(EDITOR, state="planned", phase="before", access_refused=False)
    assert planned["can"]["invite"] and planned["can"]["record_survey"] and planned["can"]["delete"]
    assert planned["can_reason"]["pair"] == "only_after_surveys_pair"
    assert planned["can_reason"]["close"] == "invalid_transition"
    done = caps.survey(EDITOR, state="surveyed", phase="after", access_refused=False)
    assert done["can"]["pair"] is True and done["can_reason"]["delete"] == "survey_recorded"
    assert caps.survey_action_refusal("planned", "refuse_access", True) == "refusal_is_final"
    assert set(caps.survey(VIEWER, state="planned", phase="after", access_refused=False)["can"].values()) == {False}

    cert = caps.certification(MANAGER, state="planned")
    assert cert["can"]["register"] is True and cert["can_reason"]["certify"] == "invalid_transition"
    assert caps.certification(EDITOR, state="planned")["can_reason"]["register"] == "manage_required"
    credit = caps.credit(EDITOR, state="targeted")
    assert credit["can"]["submit_evidence"] is True and credit["can_reason"]["achieve"] == "manage_required"
    assert caps.credit(MANAGER, state="targeted")["can_reason"]["achieve"] == "invalid_transition"
    assert credit["can_reason"]["delete"] == "manage_required"


def test_every_reason_has_a_message_in_both_languages_and_a_status() -> None:
    reasons: set[str] = set(caps._STATUS)
    for caller in (VIEWER, EDITOR, MANAGER):
        for state in (None, "draft", "in_review", "binding"):
            reasons |= set(_proof(caller, concept_state=state)["can_reason"].values())
            reasons |= set(caps.plan_row(caller, state)["can_reason"].values())
        for state in ("blocked", "passed", "released"):
            reasons |= set(
                caps.stage_progress(caller, state=state, computed_state=state, gate_status="pending")[
                    "can_reason"
                ].values()
            )
        for state in ("planned", "accepted"):
            reasons |= set(
                caps.acceptance_unit(
                    caller, concept_state="draft", state=state, has_regime=False, blocked=True, deemed_due=False
                )["can_reason"].values()
            )
            reasons |= set(caps.survey(caller, state=state, phase="before", access_refused=True)["can_reason"].values())
        reasons |= set(caps.certification(caller, state="certified")["can_reason"].values())
        reasons |= set(caps.credit(caller, state="achieved")["can_reason"].values())
    for locale in ("en", "de"):
        messages = json.loads((MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
        missing = sorted(r for r in reasons if f"quality_concept.errors.{r}" not in messages)
        assert missing == [], (locale, missing)
    assert caps.status_of("approver_is_requester") == 403
    assert caps.status_of("waiver_not_requested") == 422
    assert caps.status_of("release_already_requested") == 409


@pytest.mark.parametrize(
    "code",
    [
        "approver_is_requester",
        "approver_added_evidence",
        "waiver_not_requested",
        "stage_not_passed",
        "release_already_requested",
        "unit_dates_locked",
        "unit_not_accepted",
        "survey_recorded",
        "only_after_surveys_pair",
        "refusal_is_final",
        "binding_requires_change_request",
        "binding_requires_reopen",
        "concept_not_editable",
    ],
)
def test_the_service_keeps_no_second_copy_of_a_rule(code: str) -> None:
    """A rule written twice drifts: the flag would say yes where the request says no."""
    service = (MODULE / "service.py").read_text(encoding="utf-8")
    assert f'"{code}"' not in service, code


def test_expert_report_trigger_and_frequency_are_vocabulary() -> None:
    ok = schemas.ExpertReportIn(subject="Fire inspection", trigger="before_concealment", frequency="per_floor")
    assert (ok.trigger, ok.frequency) == ("before_concealment", "per_floor")
    # Not stated is allowed; free text is not.
    assert schemas.ExpertReportIn(subject="x").trigger == ""
    with pytest.raises(ValidationError):
        schemas.ExpertReportIn(subject="x", trigger="Before the ceilings are closed")
    with pytest.raises(ValidationError):
        schemas.ExpertReportIn(subject="x", frequency="per floor")
    with pytest.raises(ValidationError):
        schemas.ExpertReportPatch(frequency="every now and then")
    assert schemas.ExpertReportPatch(trigger="on_defect").trigger == "on_defect"
    for _subject, trigger, frequency, _offsets, _state in seed._EXPERT_REPORTS:
        assert trigger in vocab.EXPERT_REPORT_TRIGGERS
        assert frequency in vocab.EXPERT_REPORT_FREQUENCIES


def test_a_pack_catalogue_can_be_named_in_a_pin() -> None:
    fields = schemas.CataloguePin.model_fields["catalogue_source"]
    assert set(fields.annotation.__args__) == {"shipped", "tenant", "pack"}


def test_a_credit_is_decided_by_a_manager_not_by_whoever_submitted_its_evidence() -> None:
    submitted = caps.credit(EDITOR, state="evidence_submitted")
    assert submitted["can_reason"]["achieve"] == "manage_required"
    assert submitted["can_reason"]["not_achieve"] == "manage_required"
    assert submitted["can"]["return"] is True
    decided = caps.credit(MANAGER, state="evidence_submitted")
    assert decided["can"]["achieve"] is True and decided["can"]["not_achieve"] is True
    assert caps.credit_action_refusal(EDITOR, "targeted", "submit_evidence") is None


def test_the_catalogue_cites_publishers_or_names_the_standard() -> None:
    """A public catalogue cites the body that publishes a rule, or names the rule; never a company page or a wiki."""
    from urllib.parse import urlparse

    text = (MODULE / "catalogues" / "neutral.json").read_text(encoding="utf-8")
    hosts = {urlparse(m).hostname for m in __import__("re").findall(r'"source_url": "([^"]+)"', text)}
    for host in hosts:
        assert "wiki" not in host and "blog" not in host, host
    allowed = {
        "www.gesetze-im-internet.de",
        "www.dgnb.de",
        "bregroup.com",
        "www.usgbc.org",
        "learn.aiacontracts.com",
        "www.ashrae.org",
        "www.dinmedia.de",
    }
    assert hosts <= allowed, sorted(hosts - allowed)
    data = json.loads(text)

    def walk(node):
        if isinstance(node, dict):
            if "source_url" in node:
                yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    for fact in walk(data):
        # A fact without a page still says where it is from, and is never called verified.
        if fact.get("source_url") is None and fact.get("source_title") is None:
            continue
        if fact.get("source_url") is None:
            assert fact.get("review_status") != "verified", fact


def test_without_gates_the_concept_is_approved_by_a_second_manager_and_with_gates_never_by_hand() -> None:
    someone = uuid.uuid4()
    ask = {"state": "in_review", "submitted_by": someone, "four_eyes": True}
    # With gates the gate decides: the actions do not exist on the screen.
    gated = caps.concept_approval(MANAGER, gates_in_use=True, **ask)
    assert (gated["approve"], gated["approve_reason"], gated["approve_applies"]) == (False, "approved_by_gate", False)
    assert (gated["reopen_reason"], gated["reopen_applies"]) == ("reopened_by_change_request", False)
    # Without gates a manager other than the submitter approves; one code per reason it is refused.
    free = caps.concept_approval(MANAGER, gates_in_use=False, **ask)
    assert (free["approve"], free["approve_reason"], free["approve_applies"]) == (True, None, True)
    own = caps.concept_approval(MANAGER, gates_in_use=False, **{**ask, "submitted_by": MANAGER.user_id})
    assert own["approve_reason"] == "approver_is_submitter"
    assert caps.concept_approval(
        MANAGER, gates_in_use=False, **{**ask, "submitted_by": MANAGER.user_id, "four_eyes": False}
    )["approve"]
    assert caps.concept_approval(MANAGER, gates_in_use=False, **{**ask, "state": "draft"})["approve_reason"] == (
        "invalid_transition"
    )
    assert caps.concept_approval(EDITOR, gates_in_use=False, **ask)["approve_reason"] == "manage_required"
    # A plan in force can change again: a manager reopens it.
    bound = caps.concept_approval(MANAGER, gates_in_use=False, **{**ask, "state": "binding"})
    assert (bound["reopen"], bound["approve_reason"]) == (True, "invalid_transition")
    assert free["reopen_reason"] == "invalid_transition"
    for code, status in (
        ("approved_by_gate", 409),
        ("reopened_by_change_request", 409),
        ("approver_is_submitter", 403),
    ):
        assert caps.status_of(code) == status
        for locale in ("en", "de"):
            messages = json.loads((MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
            assert f"quality_concept.errors.{code}" in messages, (locale, code)


def test_a_plan_in_force_names_the_way_to_change_it_that_exists_on_the_project() -> None:
    """With gates a change request reopens the plan; without gates there is none, a manager reopens it."""
    assert caps.plan_refusal("binding") == "binding_requires_change_request"
    assert caps.plan_refusal("binding", gates_in_use=False) == "binding_requires_reopen"
    assert caps.plan_refusal("in_review", gates_in_use=False) == "concept_not_editable"
    assert caps.plan_refusal("draft", gates_in_use=False) is None
    row = caps.plan_row(MANAGER, "binding", False)
    assert row["can_reason"] == {"edit": "binding_requires_reopen", "delete": "binding_requires_reopen"}
    assert (
        _proof(MANAGER, concept_state="binding", gates_in_use=False)["can_reason"]["edit"] == "binding_requires_reopen"
    )
    assert caps.status_of("binding_requires_reopen") == 409
    for locale in ("en", "de"):
        messages = json.loads((MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
        assert "quality_concept.errors.binding_requires_reopen" in messages, locale


def test_the_four_eyes_refusal_says_who_can_approve_instead() -> None:
    """The submitter of a one-person project reads what unblocks the approval, not only that it is refused."""
    key = "quality_concept.errors.approver_is_submitter"
    for locale, words in (("en", ("second person", "manage")), ("de", ("zweite Person", "verwalten"))):
        sentence = json.loads((MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))[key]
        assert all(word in sentence for word in words), sentence
