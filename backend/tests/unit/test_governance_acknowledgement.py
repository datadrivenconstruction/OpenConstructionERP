"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unknown evidence of a blocking provider never blocks, and never passes unseen.

A blocking provider that fails, or that says nothing about the area it is
registered for, leaves an ``unknown`` item. A go must name each of them, so the
record shows the decider saw that a module had not answered.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.modules.project_governance import evaluator as ev

CODE = "unknown_evidence_not_acknowledged"
TODAY = date(2026, 5, 4)


def _evidence(area: str, code: str = "plant:error", state: str = "unknown", *, blocking: bool = True):
    return ev.EvidenceState(area_code=area, code=code, state=state, blocking=blocking, provider="plant")


def _ctx(*evidence: ev.EvidenceState, areas: tuple[ev.AreaState, ...] | None = None) -> ev.GateContext:
    return ev.GateContext(
        gate_code="G1",
        gate_status="in_review",
        areas=areas or (ev.AreaState("A", "owner-a"), ev.AreaState("B", "owner-b")),
        documents=(),
        checks=(ev.CheckState("A", "ready", "owner-a"), ev.CheckState("B", "ready", "owner-b")),
        prior_conditions=(),
        today=TODAY,
        evidence=evidence,
    )


def _req(outcome: str = "go", **kw) -> ev.DecisionRequest:
    base = {"outcome": outcome, "rationale": "because", "decider_id": "decider"}
    return ev.DecisionRequest(**(base | kw))


def _refs(ctx: ev.GateContext, req: ev.DecisionRequest) -> list[tuple[str | None, str | None]]:
    return [(v.area_code, v.ref) for v in ev.validate_decision(ctx, req) if v.code == CODE]


def test_unknown_evidence_is_still_not_a_blocker() -> None:
    assert ev.gate_blockers(_ctx(_evidence("A"))) == []


def test_a_go_that_does_not_name_the_unknown_item_is_refused() -> None:
    ctx = _ctx(_evidence("A"))
    assert _refs(ctx, _req()) == [("A", "plant:error")]
    assert ev.decision_refusal(ev.validate_decision(ctx, _req())) == (CODE, 422)


def test_a_go_that_names_it_is_admitted() -> None:
    ctx = _ctx(_evidence("A"))
    assert ev.validate_decision(ctx, _req(acknowledged_evidence=(("A", "plant:error"),))) == []


def test_a_go_with_conditions_needs_the_acknowledgement_too() -> None:
    ctx = _ctx(_evidence("A"))
    conditions = (ev.ProposedCondition("A", None, "watch it", "owner-a"),)
    assert _refs(ctx, _req("go_with_conditions", conditions=conditions)) == [("A", "plant:error")]
    named = _req("go_with_conditions", conditions=conditions, acknowledged_evidence=(("A", "plant:error"),))
    assert ev.validate_decision(ctx, named) == []


def test_proceeding_at_risk_does_not_stand_in_for_the_acknowledgement() -> None:
    ctx = _ctx(_evidence("A"), _evidence("A", "plant:late", "not_met"))
    conditions = (ev.ProposedCondition("A", None, "watch it", "owner-a"),)
    req = _req("go_with_conditions", conditions=conditions, proceed_at_risk_areas=("A",))
    assert _refs(ctx, req) == [("A", "plant:error")]


def test_the_same_code_in_two_areas_is_two_items() -> None:
    ctx = _ctx(_evidence("A"), _evidence("B"))
    assert _refs(ctx, _req(acknowledged_evidence=(("A", "plant:error"),))) == [("B", "plant:error")]


@pytest.mark.parametrize("outcome", ["hold", "recycle", "stop"])
def test_an_outcome_that_does_not_pass_the_gate_needs_no_acknowledgement(outcome: str) -> None:
    extra = {"hold_resume_date": date(2026, 6, 1)} if outcome == "hold" else {}
    assert _refs(_ctx(_evidence("A")), _req(outcome, **extra)) == []


def test_only_blocking_providers_and_only_unknown_ask_for_it() -> None:
    ctx = _ctx(
        _evidence("A", "info:error", blocking=False),
        _evidence("A", "plant:fine", "met"),
    )
    assert ev.evidence_to_acknowledge(ctx) == []
    assert ev.validate_decision(ctx, _req()) == []


def test_an_area_that_does_not_apply_asks_for_nothing() -> None:
    areas = (ev.AreaState("A", "owner-a"), ev.AreaState("B", "owner-b", applicable=False, na_rationale="no plant"))
    ctx = _ctx(_evidence("B"), areas=areas)
    assert ev.evidence_to_acknowledge(ctx) == []


def test_naming_an_item_that_is_no_longer_unknown_is_not_an_error() -> None:
    # The dialog was opened before the provider answered.
    ctx = _ctx(_evidence("A", "plant:fine", "met"))
    assert ev.validate_decision(ctx, _req(acknowledged_evidence=(("A", "plant:error"),))) == []


def test_the_record_keeps_what_was_acknowledged_and_what_the_providers_said() -> None:
    ctx = _ctx(_evidence("A"), _evidence("B", "plant:fine", "met"))
    stale = ("B", "gone")
    snapshot = ev.build_snapshot(ctx, _req(acknowledged_evidence=(("A", "plant:error"), stale)))
    assert snapshot["acknowledged_evidence"] == [
        {"area_code": "A", "code": "plant:error", "provider": "plant", "state": "unknown"}
    ]
    assert {(e["area_code"], e["code"], e["state"], e["blocking"]) for e in snapshot["evidence"]} == {
        ("A", "plant:error", "unknown", True),
        ("B", "plant:fine", "met", True),
    }


def test_the_code_is_registered_with_a_message_in_both_languages() -> None:
    assert CODE in ev.ALL_CODES
    for locale in ("en", "de"):
        path = Path(ev.__file__).parent / "messages" / f"{locale}.json"
        text = json.dumps(json.loads(path.read_text(encoding="utf-8")))
        assert f'"{CODE}": "' in text, locale


# ── a warning: the provider's own rule lets the gate pass, with something outstanding ──


def test_a_warning_never_blocks() -> None:
    assert ev.gate_blockers(_ctx(_evidence("A", "permit_due_later", "warning"))) == []


@pytest.mark.parametrize("blocking", [True, False])
def test_a_warning_has_to_be_named_on_a_go_whoever_reports_it(blocking: bool) -> None:
    ctx = _ctx(_evidence("A", "permit_due_later", "warning", blocking=blocking))
    assert _refs(ctx, _req()) == [("A", "permit_due_later")]
    assert ev.validate_decision(ctx, _req(acknowledged_evidence=(("A", "permit_due_later"),))) == []


def test_a_warning_is_kept_in_the_record_with_its_state() -> None:
    ctx = _ctx(_evidence("A", "permit_due_later", "warning"), _evidence("A"))
    named = (("A", "permit_due_later"), ("A", "plant:error"))
    snapshot = ev.build_snapshot(ctx, _req(acknowledged_evidence=named))
    assert snapshot["acknowledged_evidence"] == [
        {"area_code": "A", "code": "permit_due_later", "provider": "plant", "state": "warning"},
        {"area_code": "A", "code": "plant:error", "provider": "plant", "state": "unknown"},
    ]


def test_a_provider_can_report_a_warning() -> None:
    from app.modules.project_governance import evidence as evd

    assert "warning" in evd.EVIDENCE_STATES
    assert evd.EvidenceItem(code="permit_due_later", state="warning").state == "warning"
