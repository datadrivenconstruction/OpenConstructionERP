# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The commissioning demo seed takes the systems of a building from the pack story, in the project's language."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.commissioning import seed, seed_texts_de
from app.modules.quality_concept import seed as quality_seed

_ROOT = Path(__file__).resolve().parents[3]
_DEMO = _ROOT / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
_DEMOS = ("residential-regensburg", "school-ludwigsburg")
_OTHER_PROJECT_NAMES = ("Air handling unit", "Main switchboard", "Smoke control system", "Camera system")


def _story(demo: str) -> dict:
    return json.loads((_DEMO / f"{demo}-commissioning.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("demo", _DEMOS)
def test_every_story_system_is_usable_and_german_in_german(demo: str) -> None:
    story = _story(demo)
    de = seed._story_systems(story, "de")
    en = seed._story_systems(story, "en")
    assert len(de) == len(en) == len(story["systems"]) >= 8
    assert all(row["type"] in seed._SYSTEM_CATALOGUE for row in de)
    assert all(a["name"] != b["name"] for a, b in zip(de, en, strict=True))
    assert len({row["tag"] for row in de}) == len(de)
    for row in de + en:
        assert not any(other in row["name"] for other in _OTHER_PROJECT_NAMES)


@pytest.mark.parametrize("demo", _DEMOS)
def test_no_story_system_is_under_test_before_the_shell_stands(demo: str) -> None:
    # Regensburg digs its pit and Ludwigsburg has not started: no system can be tested or commissioned yet.
    rows = seed._story_systems(_story(demo), "de")
    assert rows and {row.get("status") for row in rows} == {seed._NOT_STARTED}


def test_the_positional_register_still_shows_every_lifecycle() -> None:
    plan = seed._lifecycle_plan(11)
    assert {seed._COMMISSIONED, seed._TESTS_COMPLETE, seed._IN_PROGRESS, seed._NOT_STARTED} <= set(plan)


def test_a_story_status_is_read_only_when_it_is_a_lifecycle() -> None:
    story = {
        "systems": [
            {"type": "hvac", "name": "A", "status": "commissioned"},
            {"type": "hvac", "name": "B", "status": "flying"},
            {"type": "hvac", "name": "C"},
        ]
    }
    assert [row.get("status") for row in seed._story_systems(story, "en")] == ["commissioned", None, None]


def test_a_story_entry_that_cannot_be_read_is_skipped() -> None:
    story = {
        "systems": [
            {"type": "no_such_type", "name": "x"},
            {"type": "hvac"},
            "text",
            {"type": "hvac", "name": {"en": "Plant", "de": "Anlage"}},
        ]
    }
    assert [row["name"] for row in seed._story_systems(story, "de")] == ["Anlage"]
    assert seed._story_systems({}, "de") == []


def test_german_texts_cover_every_system_type_like_the_english_catalogue() -> None:
    assert set(seed_texts_de.CHECKS) == set(seed._SYSTEM_CATALOGUE)
    for system_type, (pre, func) in seed_texts_de.CHECKS.items():
        spec = seed._SYSTEM_CATALOGUE[system_type]
        assert len(pre) == len(spec["prefunctional"]), system_type
        assert len(func) == len(spec["functional"]), system_type
    assert set(seed_texts_de.ISSUES) == set(seed._ISSUE_TEXT)
    assert len(seed_texts_de.RESOLUTIONS) == len(seed._ISSUE_RESOLUTION)
    assert (
        seed._is_german("de") and seed._is_german("de-AT") and not seed._is_german("en") and not seed._is_german(None)
    )


def test_credits_reach_the_floor_of_the_target_level() -> None:
    reachable = SimpleNamespace(min_score="65", score_unit="percent")
    assert sum(quality_seed._credit_points(reachable, 5, Decimal("100"))) == Decimal("70")
    short = SimpleNamespace(min_score="60", score_unit="points")
    points = quality_seed._credit_points(short, 3, Decimal("100"))
    assert sum(points) == Decimal("60") and points[1:] == [Decimal("16"), Decimal("14")]
    assert quality_seed._credit_points(SimpleNamespace(min_score=None, score_unit="points"), 3, Decimal("100")) == [
        Decimal("18"),
        Decimal("16"),
        Decimal("14"),
    ]
