# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The transmittals demo seed is driven entirely by the project story."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.modules.transmittals import seed

_STORY = (
    Path(__file__).resolve().parents[3]
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-transmittals.json"
)


def _entry(**over) -> dict:
    base = {
        "subject": "S",
        "purpose_code": "for_review",
        "issued_days_ago": 10,
        "recipients": [{"name": "R", "acknowledged_after_days": 1}],
        "items": [{"description": "D"}],
    }
    return {**base, **over}


def test_no_story_gives_nothing() -> None:
    assert seed.parse_transmittals_story({}, "en") == []
    assert seed.parse_transmittals_story(None, "en") == []
    assert seed.parse_transmittals_story({"transmittals": "x"}, "en") == []


def test_malformed_entries_are_dropped_without_a_warning(caplog) -> None:
    bad = [
        _entry(purpose_code="bogus"),
        _entry(subject=""),
        _entry(issued_days_ago=-1),
        _entry(recipients=[]),
        _entry(items=[{"description": ""}]),
        _entry(recipients=[{"name": "R", "responded_after_days": 2, "response": "x"}]),
        _entry(recipients=[{"name": "R", "acknowledged_after_days": 1}, {"name": "R"}]),
        _entry(issued_days_ago=None, recipients=[{"name": "R", "acknowledged_after_days": 1}]),
        "junk",
    ]
    with caplog.at_level(logging.INFO):
        assert seed.parse_transmittals_story({"transmittals": [*bad, _entry()]}, "en")[0]["subject"] == "S"
        assert len(seed.parse_transmittals_story({"transmittals": [*bad, _entry()]}, "en")) == 1
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_shipped_school_story_is_well_formed() -> None:
    story = json.loads(_STORY.read_text(encoding="utf-8"))
    out = seed.parse_transmittals_story(story, "en")
    assert len(out) == len(story["transmittals"]) >= 4
    assert any(e["issued"] is None for e in out)
    assert any(r["resp"] is not None for e in out for r in e["recipients"])
    assert seed.parse_transmittals_story(story, "de")[0]["subject"] != out[0]["subject"]
    raw = _STORY.read_text(encoding="utf-8")
    assert "\u2013" not in raw and "\u2014" not in raw
