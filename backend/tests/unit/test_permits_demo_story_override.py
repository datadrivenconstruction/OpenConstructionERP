# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The permits demo seed applies a per-project story on top of its defaults, key by key."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from app.modules.permits import seed

_ROOT = Path(__file__).resolve().parents[3]
_STORY = (
    _ROOT
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-permits.json"
)
_CATALOGUES = [
    _ROOT / "backend/app/modules/permits/catalogues/permit_type/de.json",
    _ROOT / "backend/app/modules/permits/catalogues/permit_type/de_bw.json",
    _ROOT
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/catalogues/permit_type"
    / "eleven_areas_framework_de_bw.json",
]


def _catalogue() -> dict[str, SimpleNamespace]:
    types: dict[str, SimpleNamespace] = {}
    for path in _CATALOGUES:
        for t in json.loads(path.read_text(encoding="utf-8"))["permit_types"]:
            types[t["code"]] = SimpleNamespace(
                code=t["code"],
                scope=t["scope"],
                category=t["category"],
                triggered_by_route=t.get("triggered_by_route", []),
                requires=[SimpleNamespace(code=r if isinstance(r, str) else r["code"]) for r in t.get("requires", [])],
            )
    return types


def test_no_story_keeps_every_default() -> None:
    out = seed.resolve_permit_content({}, "en")
    for key, text in seed._TEXT_DEFAULTS.items():
        assert out[key] == text
    assert out["codes"] == {} and out["conditions"] == {} and out["early_conditions"] == {}


def test_condition_overrides_keep_kind_trigger_and_owner() -> None:
    base = [{"number": "1", "kind": "suspensive", "text": "a", "topic": "structural", "owner_user_id": 1}]
    out = seed.apply_condition_overrides(base, {"1": {"text": "b"}})
    assert out[0]["text"] == "b" and out[0]["kind"] == "suspensive" and out[0]["owner_user_id"] == 1


def test_bad_values_fall_back_without_a_warning(caplog) -> None:
    story = {
        "building_title": 5,
        "codes": {"building": "", "bogus": "x"},
        "conditions": {"1": {"topic": "not-a-topic", "text": ""}, "9": {"text": "x"}, "2": "junk"},
    }
    with caplog.at_level(logging.INFO):
        out = seed.resolve_permit_content(story, "en")
    assert out["building_title"] == seed._TEXT_DEFAULTS["building_title"]
    assert out["codes"] == {} and out["conditions"] == {}
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_due_in_days_becomes_a_due_date_and_bad_values_are_dropped() -> None:
    from datetime import date

    out = seed.resolve_permit_content(
        {"early_conditions": {"1": {"due_in_days": -30}, "2": {"due_in_days": True, "text": "x"}}}, "en"
    )
    assert out["early_conditions"]["1"] == {"due_in_days": -30}
    assert out["early_conditions"]["2"] == {"text": "x"}
    base = [{"number": "1", "kind": "obligation", "text": "a"}, {"number": "2", "kind": "obligation", "text": "b"}]
    merged = seed.apply_condition_overrides(base, out["early_conditions"], date(2026, 10, 14))
    assert merged[0]["due_date"] == date(2026, 9, 14) and "due_in_days" not in merged[0]
    assert "due_date" not in merged[1]


def test_pick_by_story_falls_back_for_unknown_or_unfit_code() -> None:
    types = _catalogue()
    default = types["baugenehmigung"]
    assert seed.pick_by_story(types, {"road": "nope"}, "road", default, ok=lambda t: True) is default
    assert (
        seed.pick_by_story(types, {"road": "bauvoranfrage"}, "road", default, ok=lambda t: t.category == "traffic_road")
        is default
    )
    assert seed.pick_by_story(types, {}, "road", default, ok=lambda t: False) is default


def test_shipped_school_story_resolves_against_the_catalogue() -> None:
    story = json.loads(_STORY.read_text(encoding="utf-8"))
    out = seed.resolve_permit_content(story, "en")
    types = _catalogue()
    assert set(out["codes"]) == set(seed._CODE_KEYS)
    assert all(code in types for code in out["codes"].values())
    assert types[out["codes"]["preliminary"]].scope == "preliminary"
    building = types[out["codes"]["building"]]
    assert building.scope == "full" and "full_permit" in building.triggered_by_route
    early = types[out["codes"]["early_start"]]
    assert early.scope == "early_start" and building.code in {r.code for r in early.requires}
    assert types[out["codes"]["road"]].category == "traffic_road"
    assert types[out["codes"]["occupancy"]].category == "occupancy"
    for key, default in seed._TEXT_DEFAULTS.items():
        assert key in story and out[key] != default
    assert set(out["conditions"]) == {"1", "2", "3", "4", "5"}
    assert set(out["early_conditions"]) == {"1", "2"}
    assert out["conditions"]["4"]["topic"] == "fire"
    de = seed.resolve_permit_content(story, "de")
    assert de["building_title"] != out["building_title"]


def test_shipped_story_has_no_dashes_or_machine_words() -> None:
    raw = _STORY.read_text(encoding="utf-8")
    assert "\u2013" not in raw and "\u2014" not in raw
    assert not re.search(r"\bAI\b|Claude", raw)
