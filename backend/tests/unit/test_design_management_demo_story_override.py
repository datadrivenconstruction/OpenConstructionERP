# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The design management seed applies a pack story key by key and keeps its defaults otherwise."""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.design_management import seed

_ROOT = Path(__file__).resolve().parents[3]
_STORY = (
    _ROOT
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-design_management.json"
)
_REPORTS = _ROOT / "backend/app/modules/design_management/catalogues/design_reports/default.json"


def _kinds() -> set[str]:
    return {k["code"] for k in json.loads(_REPORTS.read_text(encoding="utf-8"))["report_kinds"]}


def test_empty_or_malformed_story_keeps_the_default() -> None:
    default = seed.default_plan()
    assert seed.resolve_story({}, "en", report_kinds=_kinds()) == default
    bad = {
        "wbs": {"top": {"code": "1", "name": "x"}, "children": [{"code": "9.1", "name": "n", "kind": "system"}]},
        "roles": {"arch": {"originator": "lowercase"}},
        "drawings": ["only one"],
        "review": {"comments": 5},
        "reports": {
            "overrides": {"RPT-001": {"kind": "no_such_kind"}},
            "extra": [
                {"code": "RPT-001", "kind": "acoustics", "title": "taken", "author": "arch", "phase": "mid"},
                {"code": "RPT-020", "kind": "no_such_kind", "title": "t", "author": "arch", "phase": "mid"},
                {"code": "RPT-021", "kind": "acoustics", "title": "t", "author": "nobody", "phase": "mid"},
                {"code": "RPT-022", "kind": "acoustics", "title": "t", "author": "arch", "phase": "late"},
            ],
        },
    }
    plan = seed.resolve_story(bad, "en", report_kinds=_kinds())
    assert plan["extra_reports"] == ()
    assert plan["reports"] == {"RPT-001": ("", "")}
    assert {k: v for k, v in plan.items() if k != "reports"} == {k: v for k, v in default.items() if k != "reports"}


def test_review_comments_are_padded_with_the_defaults() -> None:
    plan = seed.resolve_story({"review": {"comments": ["only the first"]}}, "en", report_kinds=_kinds())
    assert plan["review"]["comments"][0] == "only the first"
    assert plan["review"]["comments"][1:] == seed.default_plan()["review"]["comments"][1:]


def test_shipped_school_story_resolves_against_the_shipped_catalogue() -> None:
    story = json.loads(_STORY.read_text(encoding="utf-8"))
    plan = seed.resolve_story(story, "en", report_kinds=_kinds())
    default = seed.default_plan()
    assert plan["wbs_top"] == ("1", "School building")
    assert len(plan["wbs_children"]) == len(story["wbs"]["children"])
    assert len(plan["wbs_extra"]) == len(story["wbs"]["extra"])
    assert plan["roles"]["checker"][1] == "CHK"
    assert plan["roles"]["owner"][1] is None
    assert len(plan["drawings"]) == 6
    assert set(plan["deliverables"]) == set(default["deliverables"])
    assert all(v != default["deliverables"][k] for k, v in plan["deliverables"].items())
    assert len(plan["extra_reports"]) == len(story["reports"]["extra"])
    assert set(plan["reports"]) == {"RPT-001", "RPT-002", "RPT-003", "RPT-004", "RPT-005"}
    kinds = {e["kind"] for e in plan["extra_reports"]}
    assert {"contamination", "uxo", "environmental", "acoustics", "fire_proof_check"} <= kinds
    assert {e["status"] for e in plan["extra_reports"]} >= {"accepted", "required"}
    de = seed.resolve_story(story, "de", report_kinds=_kinds())
    assert de["approval_points"]["AP-001"] != plan["approval_points"]["AP-001"]


def test_shipped_school_story_has_no_dashes() -> None:
    text = _STORY.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text


def test_report_statuses_come_from_the_story_and_unknown_ones_are_ignored() -> None:
    from app.modules.design_management.seed import _report_statuses

    story = {
        "overrides": {
            "RPT-005": {"status_before_gate": "in_progress", "status_after_gate": "required"},
            "RPT-001": {"status_after_gate": "done"},
            "bad": "x",
        },
        "extra": [{"code": "RPT-010", "status_before_gate": "submitted"}, "x", {"title": "no code"}],
    }
    assert _report_statuses(story) == {
        "RPT-005": {"before_gate": "in_progress", "after_gate": "required"},
        "RPT-010": {"before_gate": "submitted"},
    }
    assert _report_statuses(None) == {} and _report_statuses({}) == {}


def test_execution_design_is_parsed_and_incomplete_input_is_ignored() -> None:
    story = {
        "execution": {
            "code": "DL-005",
            "release_code": "REL-003",
            "title": "Execution design",
            "release_title": "Execution issue",
            "drawings": ["Formwork plan", "", 3],
        }
    }
    plan = seed.resolve_story(story, "en", report_kinds=_kinds())
    assert plan["execution"] == {
        "code": "DL-005",
        "title": "Execution design",
        "drawings": ["Formwork plan"],
        "release_code": "REL-003",
        "release_title": "Execution issue",
    }
    assert seed.resolve_story({"execution": {"code": "DL-005"}}, "en", report_kinds=_kinds())["execution"] is None
    assert seed.default_plan()["execution"] is None


def test_shipped_regensburg_story_has_an_execution_design_in_both_languages() -> None:
    path = _STORY.with_name("residential-regensburg-design_management.json")
    story = json.loads(path.read_text(encoding="utf-8"))
    for locale in ("en", "de"):
        plan = seed.resolve_story(story, locale, report_kinds=_kinds())
        assert plan["execution"] is not None
        assert len(plan["execution"]["drawings"]) == 3
