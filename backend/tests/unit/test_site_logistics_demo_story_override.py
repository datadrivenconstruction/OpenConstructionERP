# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The site logistics demo seeds apply a per-project story on top of their defaults, key by key."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.modules.site_logistics import demo, demo_plan

_STORY = (
    Path(__file__).resolve().parents[3]
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-site_logistics.json"
)


def test_no_story_keeps_every_default() -> None:
    assert demo.resolve_site_content({}, "en") == (demo._GATES, demo._ZONES, ("Articulated flatbed", "Rigid 18t"))
    out = demo_plan.resolve_plan_content(None, "en")
    for key, text in demo_plan._PLAN_TEXT_DEFAULTS.items():
        assert out[key] == text
    assert out["strategy"] == demo_plan._DEFAULT_STRATEGY
    assert out["coordination"] == demo_plan._DEFAULT_COORDINATION


def test_gates_that_do_not_hold_the_bookings_fall_back(caplog) -> None:
    gates = [
        {"name": "A", "open": "10:00", "close": "11:00", "capacity": 1, "note": "n"},
        {"name": "B", "open": "10:00", "close": "11:00", "capacity": 1, "note": "n"},
    ]
    with caplog.at_level(logging.INFO):
        out = demo.resolve_site_content({"gates": gates, "zones": [{"name": "", "capacity": "1", "note": "n"}]}, "en")
    assert out[0] == demo._GATES and out[1] == demo._ZONES
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_bad_plan_values_fall_back_without_a_warning(caplog) -> None:
    story = {
        "stage_1_title": 3,
        "strategy": [
            {"flow_code": "x", "description": "d", "mode": "teleport", "storage_area": None, "buffer_days": 1}
        ],
        "delivery_open": "25:00",
        "noise_zone_type": "moon",
        "day_dba": True,
        "coordination": [{"body": "aliens", "topic": "t", "outcome": "o", "days_ago": 1}],
    }
    with caplog.at_level(logging.INFO):
        out = demo_plan.resolve_plan_content(story, "en")
    assert out == demo_plan.resolve_plan_content(None, "en")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_shipped_school_story_is_well_formed() -> None:
    story = json.loads(_STORY.read_text(encoding="utf-8"))
    gates, zones, vehicles = demo.resolve_site_content(story, "en")
    assert gates != demo._GATES and zones != demo._ZONES and len(vehicles) == 2
    out = demo_plan.resolve_plan_content(story, "en")
    for key, default in demo_plan._PLAN_TEXT_DEFAULTS.items():
        assert key in story and out[key] != default
    assert out["strategy"] != demo_plan._DEFAULT_STRATEGY and out["coordination"] != demo_plan._DEFAULT_COORDINATION
    assert out["noise_zone_type"] == "residential"
    assert set(out["area_names"]) == {a[0] for a in demo_plan._AREAS}
    assert demo_plan.resolve_plan_content(story, "de")["rules_text"] != out["rules_text"]
    raw = _STORY.read_text(encoding="utf-8")
    assert "\u2013" not in raw and "\u2014" not in raw


def test_shipped_stories_name_the_complaint_reporter_in_german() -> None:
    for name in ("school-ludwigsburg", "residential-regensburg"):
        story = json.loads((_STORY.parent / f"{name}-site_logistics.json").read_text(encoding="utf-8"))
        assert demo_plan.resolve_plan_content(story, "de")["complaint_reporter"] == "Anwohner, anonym"
    assert demo_plan.resolve_plan_content(None, "en")["complaint_reporter"] == "Neighbour, anonymous"
