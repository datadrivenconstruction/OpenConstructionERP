"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Readiness criteria of a catalogue shown as a checklist the area owner ticks."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

from app.modules.project_governance import evaluator as ev

AT = "2026-05-04T09:00:00+00:00"


def test_every_criterion_of_the_area_is_listed_in_catalogue_order_ticked_or_not() -> None:
    ticks = {"b": {"met": True, "note": "Signed off", "by": "owner-a", "at": AT}}
    assert ev.criteria_rows(["a", "b"], ticks) == [
        {"code": "a", "met": False, "note": "", "ticked_by": None, "ticked_at": None},
        {"code": "b", "met": True, "note": "Signed off", "ticked_by": "owner-a", "ticked_at": AT},
    ]


def test_a_tick_for_a_criterion_the_catalogue_no_longer_has_is_not_shown() -> None:
    assert ev.criteria_rows(["a"], {"gone": {"met": True, "note": "", "by": "x", "at": AT}}) == [
        {"code": "a", "met": False, "note": "", "ticked_by": None, "ticked_at": None}
    ]


def test_a_tick_records_who_and_when_and_leaves_the_others_alone() -> None:
    before = {"a": {"met": True, "note": "first", "by": "owner-a", "at": AT}}
    after = ev.criterion_tick(before, "b", met=True, note="  second  ", actor_id="deputy", at="later")
    assert after == {
        "a": {"met": True, "note": "first", "by": "owner-a", "at": AT},
        "b": {"met": True, "note": "second", "by": "deputy", "at": "later"},
    }
    assert before == {"a": {"met": True, "note": "first", "by": "owner-a", "at": AT}}


def test_unticking_keeps_the_trace_of_who_took_it_back() -> None:
    before = {"a": {"met": True, "note": "first", "by": "owner-a", "at": AT}}
    after = ev.criterion_tick(before, "a", met=False, note="Survey was withdrawn", actor_id="deputy", at="later")
    assert after["a"] == {"met": False, "note": "Survey was withdrawn", "by": "deputy", "at": "later"}


def test_the_decision_record_keeps_the_checklist_as_it_stood() -> None:
    ticks = {"a": {"met": True, "note": "ok", "by": "owner-a", "at": AT}}
    ctx = ev.GateContext(
        gate_code="G1",
        gate_status="in_review",
        areas=(ev.AreaState("A", "owner-a"),),
        documents=(),
        checks=(ev.CheckState("A", "ready", "owner-a", criteria=ticks),),
        prior_conditions=(),
        today=date(2026, 5, 4),
    )
    snapshot = ev.build_snapshot(ctx, ev.DecisionRequest(outcome="go", rationale="", decider_id="d"))
    assert snapshot["checks"][0]["criteria"] == ticks


def test_the_code_is_registered_with_a_message_in_both_languages() -> None:
    assert "unknown_criterion" in ev.ALL_CODES
    for locale in ("en", "de"):
        path = Path(ev.__file__).parent / "messages" / f"{locale}.json"
        assert "unknown_criterion" in json.loads(path.read_text(encoding="utf-8"))["governance"]["errors"], locale


def test_the_migration_creates_the_column_the_model_declares() -> None:
    from app.modules.project_governance.models import GovernanceCheck

    assert "criteria" in GovernanceCheck.__table__.columns
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v68_project_governance.py"
    spec = importlib.util.spec_from_file_location("v68_project_governance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    columns = next(build() for name, build, _ in module._TABLES if name == "oe_governance_check")
    assert "criteria" in {c.name for c in columns if hasattr(c, "name")}
