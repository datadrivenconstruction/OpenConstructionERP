# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The stakeholders demo seed applies a per-project story on top of its defaults, key by key."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.modules.stakeholders import seed

_STORY = (
    Path(__file__).resolve().parents[3]
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-stakeholders.json"
)


def test_no_story_keeps_every_default() -> None:
    assert seed.merge_register(seed._STAKEHOLDERS, {}, "en") == seed._STAKEHOLDERS
    assert seed.merge_commitments({}, "en") == list(seed._COMMITMENTS)
    for section, texts in seed._TEXT_DEFAULTS.items():
        assert seed.merge_texts({}, section, "en") == texts


def test_register_override_keeps_code_and_category() -> None:
    base = seed._STAKEHOLDERS[0]
    story = {"stakeholders": [{"code": base[0], "label": {"en": "A", "de": "B"}, "power": 1, "current": "leading"}]}
    row = seed.merge_register(seed._STAKEHOLDERS, story, "de")[0]
    assert (row[0], row[2]) == (base[0], base[2])
    assert row[1] == "B" and row[4] == 1 and row[6] == "leading"


def test_bad_values_fall_back_without_a_warning(caplog) -> None:
    story = {
        "stakeholders": [{"code": "S-001", "power": 9, "current": "bogus", "label": 5}, "junk"],
        "evening": {"location": 3},
        "commitments": [{"text": "", "due_days": "x"}, 7],
    }
    with caplog.at_level(logging.INFO):
        assert seed.merge_register(seed._STAKEHOLDERS, story, "en") == seed._STAKEHOLDERS
        assert seed.merge_texts(story, "evening", "en") == seed._TEXT_DEFAULTS["evening"]
        assert seed.merge_commitments(story, "en") == list(seed._COMMITMENTS)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_shipped_school_story_is_well_formed() -> None:
    story = json.loads(_STORY.read_text(encoding="utf-8"))
    merged = seed.merge_register(seed._STAKEHOLDERS, story, "en")
    assert [r[0] for r in merged] == [r[0] for r in seed._STAKEHOLDERS]
    assert all(m[1] != d[1] for m, d in zip(merged, seed._STAKEHOLDERS, strict=True))
    assert len(story["stakeholders"]) == len(seed._STAKEHOLDERS)
    assert all(m[2:4] == d[2:4] for m, d in zip(merged, seed._STAKEHOLDERS, strict=True))
    assert len(story["commitments"]) == len(seed._COMMITMENTS)
    for section in seed._TEXT_DEFAULTS:
        got = seed.merge_texts(story, section, "en")
        assert set(story[section]) <= set(got)
        assert all(got[k] != v for k, v in seed._TEXT_DEFAULTS[section].items() if k in story[section])
    raw = _STORY.read_text(encoding="utf-8")
    assert "\u2014" not in raw and "\u2013" not in raw
