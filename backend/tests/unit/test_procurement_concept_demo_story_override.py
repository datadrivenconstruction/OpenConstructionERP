# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The procurement concept seed applies a pack story key by key and keeps its defaults otherwise."""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.procurement_concept import seed

_ROOT = Path(__file__).resolve().parents[3]
_STORY = (
    _ROOT
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-procurement_concept.json"
)
_CATALOGUE = _ROOT / "backend/app/modules/procurement_concept/catalogues/de_national.json"
_PROCEDURES = {"open", "restricted", "competitive_negotiated", "framework_call_off"}


def _story() -> dict:
    return json.loads(_STORY.read_text(encoding="utf-8"))


def test_no_story_keeps_every_default() -> None:
    for kind, base in seed._DEFAULTS.items():
        merged = seed.merge_package_story(base, None, _PROCEDURES, "en")
        assert (merged["value"], merged["public"], merged["private"], merged["lead"]) == base
        assert merged["offset"] is None
        assert merged["notes"] == ""
    assert seed.merge_names(seed._FREE_NAMES, None, "en") == seed._FREE_NAMES
    assert seed.merge_soundings(None, "en") is None
    assert seed.merge_framework(None, "en")["code"] == "FW-SUPPLY-01"
    assert seed.merge_prequal(None, "en")["weights"] == ["40", "35", "25"]
    assert seed.merge_reference(None, "en")["value"] == "3100000"


def test_bad_values_fall_back_to_the_default() -> None:
    base = seed._DEFAULTS["construction"]
    entry = {"value": "abc", "public_procedure": "no_such_procedure", "lead_days": -4, "start_offset_days": True}
    merged = seed.merge_package_story(base, entry, _PROCEDURES, "en")
    assert (merged["value"], merged["public"], merged["private"], merged["lead"]) == base
    assert merged["offset"] is None
    assert seed.merge_prequal({"weights": [50, 30, 30]}, "en")["weights"] == ["40", "35", "25"]
    assert seed.merge_framework({"code": "bad code", "package_kinds": ["nope"]}, "en")["code"] == "FW-SUPPLY-01"
    assert seed.merge_soundings([{"trade": "x"}], "en") is None


def test_package_code_wins_over_kind() -> None:
    base = seed._DEFAULTS["supply"]
    by_kind = seed.merge_package_story(base, {"value": 10, "notes": "kind note"}, _PROCEDURES, "en")
    by_code = seed.merge_package_story(base, {"value": 20}, _PROCEDURES, "en", previous=by_kind)
    assert by_code["value"] == "20"
    assert by_code["notes"] == "kind note"


def test_shipped_school_story_merges_against_the_shipped_catalogue() -> None:
    story = _story()
    catalogue = json.loads(_CATALOGUE.read_text(encoding="utf-8"))
    procedures = {p["code"] for p in catalogue["procedures"]}
    jurisdiction = next(j for j in catalogue["jurisdictions"] if j["code"] == "de_national")
    assert story["client_type"] in jurisdiction["client_types"]
    assert set(story["kinds"]) <= set(seed._DEFAULTS)
    for kind, entry in story["kinds"].items():
        merged = seed.merge_package_story(seed._DEFAULTS[kind], entry, procedures, "de")
        assert merged["value"] == str(entry["value"]) if "value" in entry else True
        assert merged["notes"], kind
        for key in ("public_procedure", "private_procedure"):
            assert entry.get(key, "open") in procedures
    assert (
        seed.merge_package_story(seed._DEFAULTS["design"], story["kinds"]["design"], procedures, "en")["public"]
        == "open"
    )
    assert seed.merge_names(seed._FREE_NAMES, story["free_names"], "en") == tuple(n["en"] for n in story["free_names"])
    assert seed.merge_prequal(story["prequal"], "en")["weights"] == ["40", "25", "35"]
    assert seed.merge_framework(story["framework"], "en")["code"] == "FW-SCHOOL-01"
    assert seed.merge_framework(story["framework"], "en")["package_kinds"] == ["supply"]
    assert seed.merge_reference(story["reference"], "en")["value"] == "6200000"
    rows = seed.merge_soundings(story["soundings"], "en")
    assert rows is not None
    assert len(rows) == len(story["soundings"])
    assert all(set(r["package_kinds"]) <= set(seed._DEFAULTS) for r in rows)


def test_shipped_school_story_has_no_dashes_and_both_languages_resolve() -> None:
    text = _STORY.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text
    notes = _story()["kinds"]["construction"]["notes"]
    assert seed._story_str(notes, "de") != seed._story_str(notes, "en")
