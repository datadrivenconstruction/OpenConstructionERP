# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The permits guards (what a write refuses and what a ``can`` flag says) and the notice extraction parser.

Both are pure: no database, no provider.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.permits import extraction, guards
from app.modules.permits.errors import PermitError
from app.modules.permits.fsm import USER_TARGETS

ME = uuid.uuid4()
OTHER = uuid.uuid4()
THIRD = uuid.uuid4()


def _refusal(guard) -> tuple[int, str, bool]:
    with pytest.raises(PermitError) as exc:
        guard()
    return exc.value.status_code, exc.value.code, bool(getattr(exc.value, "applies", True))


def _app(status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status)


def _permit(status: str = "in_force", started=None, paused=None) -> SimpleNamespace:
    return SimpleNamespace(status=status, start_notified_at=started, paused_since=paused)


def _cond(status: str = "open", **kw) -> SimpleNamespace:
    base = {
        "status": status,
        "confirmed": True,
        "trigger": "before_start",
        "kind": "obligation",
        "owner_user_id": OTHER,
        "evidence_submitted_by": None,
        "requires_authority_approval": False,
    }
    return SimpleNamespace(**{**base, **kw})


# ── the flag is the guard run dry ──────────────────────────────────────────


def test_a_flag_carries_the_code_the_write_refuses_with() -> None:
    assert guards.flag(lambda: None) == {"allowed": True, "applies": True, "reason": None}
    assert guards.flag(lambda: guards.application_clock(_app("planned"))) == {
        "allowed": False,
        "applies": True,
        "reason": "clock_not_running",
    }
    # An action that makes no sense for the record is told apart from one refused for now.
    assert guards.flag(lambda: guards.application_decide(_app("decided"))) == {
        "allowed": False,
        "applies": False,
        "reason": "already_decided",
    }


def test_a_flag_never_hides_an_error_that_is_not_a_refusal() -> None:
    def broken() -> None:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        guards.flag(broken)


def test_the_permission_comes_first_where_the_action_belongs_to_the_record() -> None:
    viewer = guards.Caller(ME)
    flag = guards.flag(lambda: guards.needs_edit(viewer), lambda: guards.application_clock(_app("planned")))
    assert flag == {"allowed": False, "applies": True, "reason": "edit_required"}
    assert _refusal(lambda: guards.needs_manage(viewer)) == (403, "manage_required", True)
    assert _refusal(lambda: guards.needs_verify(viewer)) == (403, "verify_required", True)
    guards.needs_edit(guards.Caller(ME, edit=True))
    assert guards.flag() == {"allowed": True, "applies": True, "reason": None}


def test_whether_an_action_applies_does_not_depend_on_who_asks() -> None:
    """A reader must see the same set of actions as an editor, only disabled."""
    viewer, editor = guards.Caller(ME), guards.Caller(ME, edit=True)

    def move(caller: guards.Caller, target: str) -> dict:
        return guards.flag(
            lambda: guards.needs_edit(caller),
            lambda: guards.application_transition(_app("preparing"), target, False),
        )

    for target in guards.TARGET_ORDER:
        assert move(viewer, target)["applies"] == move(editor, target)["applies"], target
    assert move(viewer, "validated") == {"allowed": False, "applies": False, "reason": "invalid_transition"}
    assert move(viewer, "submitted") == {"allowed": False, "applies": True, "reason": "edit_required"}
    assert [t for t in guards.TARGET_ORDER if move(viewer, t)["applies"]] == ["submitted", "withdrawn"]
    # The same for the owner test of a condition: a closed condition is closed for everyone.
    waived = _cond("waived")
    stranger = guards.flag(
        lambda: guards.needs_edit(editor),
        lambda: guards.condition_owned(waived, ME, False),
        lambda: guards.condition_edit(waived),
    )
    assert stranger == {"allowed": False, "applies": False, "reason": "condition_closed"}


# ── applications ───────────────────────────────────────────────────────────


def test_the_workflow_order_names_exactly_the_user_targets() -> None:
    assert set(guards.TARGET_ORDER) == set(USER_TARGETS)
    assert len(guards.TARGET_ORDER) == len(USER_TARGETS)
    assert guards.TARGET_ORDER.index("preparing") < guards.TARGET_ORDER.index("internal_review")
    assert guards.TARGET_ORDER.index("internal_review") < guards.TARGET_ORDER.index("submitted")
    assert guards.TARGET_ORDER[-1] == "withdrawn"


def test_internal_review_exists_only_where_the_project_enabled_it() -> None:
    preparing = _app("preparing")
    # Without the setting the branch is not offered and a direct filing is.
    assert _refusal(lambda: guards.application_transition(preparing, "internal_review", False)) == (
        409,
        "internal_review_not_enabled",
        False,
    )
    guards.application_transition(preparing, "submitted", False)
    # With it the application goes through the release first.
    guards.application_transition(preparing, "internal_review", True)
    assert _refusal(lambda: guards.application_transition(preparing, "submitted", True)) == (
        409,
        "internal_review_required",
        False,
    )
    guards.application_transition(_app("internal_review"), "submitted", True)


def test_same_state_terminal_and_unknown_moves_are_refused() -> None:
    assert _refusal(lambda: guards.application_transition(_app("submitted"), "submitted", False))[:2] == (
        409,
        "invalid_transition",
    )
    for closed in ("decided", "withdrawn"):
        assert _refusal(lambda closed=closed: guards.application_transition(_app(closed), "preparing", False))[:2] == (
            409,
            "invalid_transition",
        )
    # ``decided`` is entered only by recording a decision.
    assert _refusal(lambda: guards.application_transition(_app("submitted"), "decided", False))[:2] == (
        422,
        "transition_not_allowed",
    )
    assert _refusal(lambda: guards.application_transition(_app("planned"), "submitted", False))[1] == (
        "invalid_transition"
    )


def test_application_edit_clock_and_decision() -> None:
    assert _refusal(lambda: guards.application_edit(_app("decided")))[:2] == (409, "application_closed")
    guards.application_edit(_app("under_review"))
    for idle in ("planned", "preparing", "internal_review", "decided", "withdrawn"):
        assert _refusal(lambda idle=idle: guards.application_clock(_app(idle)))[1] == "clock_not_running"
    guards.application_clock(_app("info_requested"))
    assert _refusal(lambda: guards.application_decide(_app("preparing"))) == (409, "application_not_decidable", True)
    # What an applicant can still cure waits (applies); what is over is not offered at all.
    for early in ("planned", "preparing", "internal_review"):
        assert _refusal(lambda early=early: guards.application_clock(_app(early)))[2] is True
    for over in ("decided", "withdrawn"):
        assert _refusal(lambda over=over: guards.application_clock(_app(over)))[2] is False
    assert _refusal(lambda: guards.application_decide(_app("withdrawn"))) == (409, "application_not_decidable", False)
    for open_ in guards.DECIDABLE:
        guards.application_decide(_app(open_))


def test_only_the_newest_decision_revision_is_corrected_or_completed() -> None:
    old = SimpleNamespace(id=uuid.uuid4(), conditions_pending=True)
    new = SimpleNamespace(id=uuid.uuid4(), conditions_pending=False)
    assert _refusal(lambda: guards.decision_current(old, new)) == (409, "decision_superseded", False)
    guards.decision_current(new, new)
    assert _refusal(lambda: guards.decision_complete_register(old, new))[1] == "decision_superseded"
    assert _refusal(lambda: guards.decision_complete_register(new, new)) == (409, "register_already_complete", False)
    guards.decision_complete_register(old, old)


def test_requirement_guards() -> None:
    req = SimpleNamespace(responsible_user_id=OTHER)
    assert _refusal(lambda: guards.requirement_edit(req, ME, False)) == (403, "not_requirement_owner", True)
    guards.requirement_edit(req, OTHER, False)
    guards.requirement_edit(req, ME, True)
    assert _refusal(lambda: guards.requirement_delete([_app("submitted")]))[:2] == (409, "requirement_has_applications")
    guards.requirement_delete([_app("planned"), _app("withdrawn")])


# ── permits ────────────────────────────────────────────────────────────────


def test_permit_start_interruption_and_resumption() -> None:
    assert _refusal(lambda: guards.permit_start(_permit(started="2026-01-01"))) == (
        409,
        "start_already_notified",
        False,
    )
    # A suspended permit can come back: the action waits. Any other state is final for it.
    assert _refusal(lambda: guards.permit_start(_permit("suspended"))) == (409, "permit_not_in_force", True)
    for gone in ("revoked", "lapsed", "expired", "superseded"):
        assert _refusal(lambda gone=gone: guards.permit_start(_permit(gone))) == (409, "permit_not_in_force", False)
        assert _refusal(lambda gone=gone: guards.permit_interruption(_permit(gone, started="2026-01-01"), False)) == (
            409,
            "permit_not_in_force",
            False,
        )
    guards.permit_start(_permit())
    # Work that has not started can be neither interrupted nor resumed: not an action of this permit yet.
    assert _refusal(lambda: guards.permit_interruption(_permit(), False)) == (409, "work_not_started", False)
    assert _refusal(lambda: guards.permit_interruption(_permit(), True)) == (409, "work_not_started", False)
    running = _permit(started="2026-01-01")
    paused = _permit(started="2026-01-01", paused="2026-02-01")
    guards.permit_interruption(running, False)
    assert _refusal(lambda: guards.permit_interruption(running, True)) == (409, "work_not_interrupted", False)
    guards.permit_interruption(paused, True)
    assert _refusal(lambda: guards.permit_interruption(paused, False)) == (409, "work_already_interrupted", False)


def test_permit_transitions() -> None:
    guards.permit_transition(_permit(), "suspended")
    guards.permit_transition(_permit("suspended"), "in_force")
    assert _refusal(lambda: guards.permit_transition(_permit("lapsed"), "in_force"))[:2] == (
        422,
        "lapsed_needs_extension_decision",
    )
    assert _refusal(lambda: guards.permit_transition(_permit("revoked"), "in_force")) == (
        409,
        "invalid_transition",
        False,
    )
    # ``superseded`` comes only from a variation or a new decision.
    assert _refusal(lambda: guards.permit_transition(_permit(), "superseded"))[:2] == (422, "transition_not_allowed")


# ── conditions ─────────────────────────────────────────────────────────────


def test_a_condition_belongs_to_its_owner_or_to_nobody_yet() -> None:
    assert _refusal(lambda: guards.condition_owned(_cond(), ME, False)) == (403, "not_condition_owner", True)
    guards.condition_owned(_cond(), OTHER, False)
    guards.condition_owned(_cond(), ME, True)
    # A proposal the AI made has no owner: any editor may correct it before it is confirmed.
    guards.condition_owned(_cond(owner_user_id=None, confirmed=False), ME, False)


def test_gate_fields_and_owner_freeze_once_the_condition_left_open() -> None:
    guards.condition_gate_fields(_cond())
    guards.condition_assign(_cond())
    assert _refusal(lambda: guards.condition_gate_fields(_cond("evidence_submitted")))[:2] == (
        409,
        "condition_field_frozen",
    )
    assert _refusal(lambda: guards.condition_assign(_cond("discharged")))[1] == "condition_field_frozen"
    assert _refusal(lambda: guards.condition_assign(_cond("waived"))) == (409, "condition_closed", False)
    # Nothing changed, nothing frozen.
    guards.condition_frozen(_cond("discharged"), [])


def test_evidence_guards() -> None:
    assert _refusal(lambda: guards.condition_add_evidence(_cond("discharged")))[1] == "condition_closed"
    guards.condition_add_evidence(_cond("discharge_applied"))
    assert _refusal(lambda: guards.condition_remove_evidence(_cond("not_triggered")))[1] == "condition_closed"
    assert _refusal(lambda: guards.condition_submit_evidence(_cond(confirmed=False), 1))[1] == (
        "condition_not_confirmed"
    )
    assert _refusal(lambda: guards.condition_submit_evidence(_cond(), 0)) == (422, "evidence_required", True)
    assert _refusal(lambda: guards.condition_submit_evidence(_cond("evidence_submitted"), 1)) == (
        409,
        "invalid_transition",
        False,
    )
    guards.condition_submit_evidence(_cond(), 1)


def test_only_an_ongoing_condition_is_in_compliance_or_in_breach() -> None:
    assert _refusal(lambda: guards.condition_ongoing(_cond(), "breach")) == (422, "condition_not_ongoing", False)
    ongoing = _cond(trigger="ongoing")
    guards.condition_ongoing(ongoing, "breach")
    guards.condition_ongoing(ongoing, "in_compliance")
    assert _refusal(lambda: guards.condition_ongoing(_cond("breach", trigger="ongoing"), "breach"))[1] == (
        "invalid_transition"
    )
    assert _refusal(lambda: guards.condition_confirm(_cond())) == (409, "condition_already_confirmed", False)
    guards.condition_confirm(_cond(confirmed=False))


def test_a_condition_takes_one_tracked_limit() -> None:
    guards.condition_link_requirement(_cond(requirement_id=None))
    assert _refusal(lambda: guards.condition_link_requirement(_cond(requirement_id=uuid.uuid4()))) == (
        409,
        "condition_already_linked",
        False,
    )


def test_a_settled_condition_has_no_discharge_left_and_one_on_its_way_waits() -> None:
    def refusal(c, mode):
        return _refusal(lambda: guards.condition_discharge(c, mode, ME, set(), has_document=True))

    assert refusal(_cond(), "self_certified") == (409, "evidence_not_submitted", True)
    assert refusal(_cond("evidence_submitted"), "not_triggered") == (409, "invalid_transition", True)
    for settled in ("discharged", "not_triggered", "waived", "superseded"):
        assert refusal(_cond(settled), "self_certified") == (409, "evidence_not_submitted", False), settled
        assert refusal(_cond(settled), "waived_by_authority") == (409, "invalid_transition", False), settled
    authority = _cond("evidence_submitted", requires_authority_approval=True)
    assert refusal(authority, "self_certified") == (422, "authority_discharge_required", False)


def test_a_manual_discharge_is_four_eyes_in_every_mode() -> None:
    ready = _cond("evidence_submitted", evidence_submitted_by=OTHER)
    assert guards.condition_discharge(ready, "self_certified", ME, {OTHER}, has_document=False) == "discharged"
    assert _refusal(lambda: guards.condition_discharge(ready, "self_certified", OTHER, {OTHER}, has_document=False))[
        :2
    ] == (403, "verifier_is_owner")
    assert _refusal(
        lambda: guards.condition_discharge(ready, "self_certified", THIRD, {OTHER, THIRD}, has_document=False)
    )[:2] == (403, "verifier_is_involved")
    assert _refusal(lambda: guards.condition_discharge(_cond(), "self_certified", ME, set(), has_document=False))[
        :2
    ] == (409, "evidence_not_submitted")
    assert (
        _refusal(lambda: guards.condition_discharge(_cond(), "waived_by_authority", ME, set(), has_document=False))[1]
        == "waiver_needs_document"
    )
    assert guards.condition_discharge(_cond(), "waived_by_authority", ME, set(), has_document=True) == "waived"
    suspensive = _cond(kind="suspensive")
    assert (
        _refusal(lambda: guards.condition_discharge(suspensive, "not_triggered", ME, set(), has_document=False))[1]
        == "not_triggered_needs_document"
    )
    assert guards.condition_discharge(_cond(), "not_triggered", ME, set(), has_document=False) == "not_triggered"
    assert _refusal(lambda: guards.condition_discharge(_cond(), "authority_discharged", ME, set(), has_document=True))[
        :2
    ] == (422, "discharge_needs_application")


def test_the_frame_document_must_exist_have_a_container_and_be_writable() -> None:
    assert _refusal(lambda: guards.frame_document(None))[:2] == (404, "frame_document_not_found")
    assert _refusal(lambda: guards.frame_document(SimpleNamespace(container_id=None, read_only=False)))[1] == (
        "frame_document_without_container"
    )
    assert _refusal(lambda: guards.frame_document(SimpleNamespace(container_id=ME, read_only=True)))[1] == (
        "frame_document_read_only"
    )
    guards.frame_document(SimpleNamespace(container_id=ME, read_only=False))


# ── reading the notice ─────────────────────────────────────────────────────

NOTICE = (
    "Baugenehmigung Az. 2026-0815\n\n"
    "1. Vor Baubeginn ist der Standsicherheitsnachweis   geprüft vorzulegen.\n"
    "2. Die Baustelle ist arbeitstäglich zu reinigen.\n"
)


def _item(**kw) -> dict:
    base = {
        "number": "1",
        "text": "Vor Baubeginn ist der Standsicherheitsnachweis geprüft vorzulegen.",
        "kind": "suspensive",
        "trigger": "before_start",
        "topic": "other",
        "confidence": 0.9,
        "text_span": "Nr. 1",
        "passage": "Vor Baubeginn ist der Standsicherheitsnachweis geprüft vorzulegen.",
    }
    return {**base, **kw}


def test_a_proposal_keeps_confidence_locator_and_the_quoted_passage() -> None:
    parsed = extraction.parse_response({"conditions": [_item()]}, NOTICE)
    assert parsed is not None and parsed.rejected == 0
    (p,) = parsed.proposals
    assert (p["number"], p["kind"], p["trigger"], p["confidence"], p["text_span"]) == (
        "1",
        "suspensive",
        "before_start",
        "0.9",
        "Nr. 1",
    )
    # The quotation is matched against the notice ignoring case and runs of whitespace.
    assert p["passage"].startswith("Vor Baubeginn")


def test_a_quotation_that_is_not_in_the_notice_is_not_shown_as_one() -> None:
    parsed = extraction.parse_response([_item(passage="The applicant shall plant twelve trees.")], NOTICE)
    assert parsed is not None
    assert parsed.proposals[0]["passage"] == ""
    assert parsed.proposals[0]["text"].startswith("Vor Baubeginn")


def test_what_fails_validation_is_counted_and_left_out_never_repaired() -> None:
    items = [
        _item(),
        _item(number="2", text="Die Baustelle ist arbeitstäglich zu reinigen.", kind="made_up_kind"),
        _item(number="3", text="Dritte Auflage.", confidence=None),
        _item(number="4", text="Vierte Auflage.", confidence=1.4),
        _item(number="", text="Ohne Nummer."),
        _item(number="5", text=""),
        "not an object",
        # The same condition a second time.
        _item(number="6"),
    ]
    parsed = extraction.parse_response({"conditions": items}, NOTICE)
    assert parsed is not None
    assert [p["number"] for p in parsed.proposals] == ["1"]
    assert parsed.rejected == 7


def test_a_trigger_that_needs_a_further_field_is_left_for_the_reviewer() -> None:
    parsed = extraction.parse_response(
        [_item(trigger="by_date"), _item(number="2", text="Zwei.", trigger="nonsense")], NOTICE
    )
    assert parsed is not None
    assert [p["trigger"] for p in parsed.proposals] == ["", ""]


def test_an_answer_without_a_list_is_unreadable_and_an_empty_list_is_an_answer() -> None:
    assert extraction.parse_response(None, NOTICE) is None
    assert extraction.parse_response({"answer": "none"}, NOTICE) is None
    assert extraction.parse_response("1. first condition", NOTICE) is None
    empty = extraction.parse_response({"conditions": []}, NOTICE)
    assert empty is not None and empty.proposals == [] and empty.rejected == 0


def test_the_prompt_names_the_values_the_schema_accepts_and_cuts_a_long_notice() -> None:
    system = extraction.system_prompt()
    for value in ("suspensive", "reserved_obligation", "before_occupation", "noise", "passage", "confidence"):
        assert value in system
    prompt, cut = extraction.build_prompt(NOTICE)
    assert not cut and NOTICE.strip() in prompt
    prompt, cut = extraction.build_prompt("x" * (extraction.MAX_DOCUMENT_CHARS + 10))
    assert cut and len(prompt) < extraction.MAX_DOCUMENT_CHARS + 100
