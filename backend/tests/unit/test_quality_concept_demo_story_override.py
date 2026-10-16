# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The quality concept seed applies a pack story key by key and keeps its defaults otherwise."""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.quality_concept import seed

_ROOT = Path(__file__).resolve().parents[3]
_STORY = (
    _ROOT
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-quality_concept.json"
)
_CATALOGUE = _ROOT / "backend/app/modules/quality_concept/catalogues/neutral.json"


def _codes(catalogue: dict) -> dict:
    return {
        "families": {f["code"] for f in catalogue["standard_families"]},
        "categories": {c["code"] for c in catalogue["requirement_categories"]},
        "regimes": {r["code"] for r in catalogue["acceptance_regimes"]},
    }


def _resolve(story: dict) -> dict:
    catalogue = json.loads(_CATALOGUE.read_text(encoding="utf-8"))
    return seed.resolve_story(story, "en", **_codes(catalogue))


def test_default_plan_equals_the_constants() -> None:
    plan = seed.default_plan()
    assert plan["packages"] == seed._PACKAGES
    assert [r[:5] for r in plan["standards"]] == [tuple(r) for r in seed._STANDARDS]
    assert plan["requirements"] == seed._REQUIREMENTS
    assert [r[:5] for r in plan["expert_reports"]] == [tuple(r) for r in seed._EXPERT_REPORTS]
    assert plan["expert_reports"][0][5] == seed._REPORTS_AFTER_START[0]
    assert plan["start"] == 190
    assert plan["regime"] == "fidic_taking_over"
    assert plan["regime_before"] == "de_vob_b"


def test_empty_or_malformed_story_keeps_the_default() -> None:
    assert _resolve({}) == seed.default_plan()
    bad = {
        "start_days": "soon",
        "regime": "no_such_regime",
        "packages": [{"ref": "A"}],
        "standards": [{"code": "X"}, "text"],
        "requirements": [{"category": "quality.unknown", "entity": "e", "attribute": "a"}],
        "expert_reports": [{"subject": "no offsets"}],
        "units": [{"code": "U", "title": "t", "kind": "nope", "days": 3}],
        "survey_neighbour": {"triggers": ["no_such_trigger"], "methods": []},
    }
    assert _resolve(bad) == seed.default_plan()


def test_stage_names_of_a_story_keep_the_good_ones() -> None:
    plan = _resolve({"stage_names": {"factory_test": {"en": "Shell acceptance"}, "bad": 5, "other": ""}})
    assert plan["stage_names"] == {"factory_test": "Shell acceptance"}
    assert seed.default_plan()["stage_names"] == {}


def test_start_days_moves_the_reports_of_the_story_before_construction() -> None:
    plan = _resolve({"start_days": 100})
    assert plan["start"] == 100
    assert plan["expert_reports"][0][5] == (130,)


def test_shipped_school_story_resolves_against_the_shipped_catalogue() -> None:
    story = json.loads(_STORY.read_text(encoding="utf-8"))
    plan = _resolve(story)
    assert plan["regime"] == "de_vob_b"
    assert len(plan["packages"]) == 2
    assert len(plan["standards"]) == len(story["standards"])
    assert len(plan["requirements"]) == len(story["requirements"])
    assert len(plan["expert_reports"]) == len(story["expert_reports"])
    assert len(plan["units"]) == len(story["units"])
    assert plan["neighbour"]["address"] == story["survey_neighbour"]["address"]["en"]
    assert plan["neighbour"]["triggers"] == ["excavation", "vibration"]
    subjects = " ".join(r[0] for r in plan["expert_reports"])
    for needle in ("DIN 18041", "DIN 18032-2", "DIN 18040-1", "Pruefsachverstaendiger", "Blower door", "CO2"):
        assert needle in subjects
    assert all(i in (0, 1) for u in plan["units"] for i in u[4])
    assert any(u[2] == "total" for u in plan["units"])
    assert any(u[2] == "handover_to_operation" for u in plan["units"])


def test_shipped_school_story_has_no_dashes() -> None:
    text = _STORY.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text


def _schemes() -> list:
    from types import SimpleNamespace

    catalogue = json.loads(_CATALOGUE.read_text(encoding="utf-8"))
    return [
        SimpleNamespace(
            code=x["code"], scope=x["scope"], levels=x.get("levels", []), credit_categories=x.get("credit_categories")
        )
        for x in catalogue["certification_schemes"]
    ]


def test_without_a_story_list_each_scope_gets_its_first_graded_scheme() -> None:
    picked = seed.certification_targets(_schemes(), seed.default_plan()["certification_schemes"])
    assert len({x.scope for x in picked}) == len(picked) >= 2
    assert "leed_o_m" in [x.code for x in picked]


def test_a_story_names_its_certification_schemes_and_nothing_foreign_is_added() -> None:
    plan = _resolve({"certification_schemes": ["dgnb_new_construction", "no_such_scheme"]})
    assert plan["certification_schemes"] == ("dgnb_new_construction", "no_such_scheme")
    picked = seed.certification_targets(_schemes(), plan["certification_schemes"])
    assert [x.code for x in picked] == ["dgnb_new_construction"]
    assert seed.certification_targets(_schemes(), ()) == []
    assert _resolve({"certification_schemes": "dgnb"})["certification_schemes"] is None


def test_both_german_demo_stories_target_dgnb_only() -> None:
    for name in ("residential-regensburg", "school-ludwigsburg"):
        story = json.loads((_STORY.parent / f"{name}-quality_concept.json").read_text(encoding="utf-8"))
        picked = seed.certification_targets(_schemes(), _resolve(story)["certification_schemes"])
        assert [x.code for x in picked] == ["dgnb_new_construction"], name
