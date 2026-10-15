# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The staffing demo seed applies a per-project story on top of its defaults, key by key."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.modules.staffing import seed

_STORY = (
    Path(__file__).resolve().parents[3]
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-staffing.json"
)
_DE = Path(seed.__file__).parent / "catalogues" / "de.json"


def test_no_story_keeps_defaults() -> None:
    d = seed.POSITIONS_BEFORE_CONSTRUCTION
    assert seed.story_positions({}, d) == d
    assert seed.story_handovers({}, "en", seed.HANDOVERS) == seed.HANDOVERS


def test_bad_rows_are_dropped_quietly(caplog) -> None:
    story = {
        "positions": [{"role": "x", "phase": "nope", "entry": 1}, {"role": "y", "phase": "execution", "entry": "1"}],
        "handovers": [{"from": "a", "to": "b", "overlap_days": 0, "scope": "s"}, 3],
        "expiring": [{"role": "a"}, "x"],
    }
    with caplog.at_level(logging.INFO):
        d = seed.POSITIONS_BEFORE_CONSTRUCTION
        assert seed.story_positions(story, d) == d
        assert seed.story_handovers(story, "en", seed.HANDOVERS) == seed.HANDOVERS
        assert seed.story_pairs(story, "expiring") == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_valid_rows_replace() -> None:
    story = {"positions": [{"role": "site_manager", "phase": "execution", "entry": 5, "exit": None}]}
    assert seed.story_positions(story, ()) == (("site_manager", "execution", 5, None, "open"),)


def test_shipped_school_story_uses_real_catalogue_codes() -> None:
    story = json.loads(_STORY.read_text(encoding="utf-8"))
    cat = json.loads(_DE.read_text(encoding="utf-8"))
    roles = {r["code"] for r in cat["roles"]}
    kinds = {k["code"] for k in cat["document_kinds"]}
    rows = seed.story_positions(story, ())
    assert len(rows) == len(story["positions"])
    assert {r[0] for r in rows} <= roles
    assert set(story["filled"]) <= {r[0] for r in rows}
    for key in ("expiring", "missing", "waived"):
        pairs = seed.story_pairs(story, key)
        assert len(pairs) == len(story[key])
        assert {r for r, _, _ in pairs} <= {r[0] for r in rows}
        assert {k for _, k, _ in pairs} <= kinds
    handovers = seed.story_handovers(story, "en", ())
    assert len(handovers) == len(story["handovers"])
    assert {h[0] for h in handovers} <= set(story["filled"])
    assert {h[1] for h in handovers} <= {r[0] for r in rows}
    assert "\u2014" not in _STORY.read_text(encoding="utf-8")


def test_a_story_roster_gives_the_people_in_filling_order_and_drops_unusable_rows() -> None:
    from app.modules.staffing.seed import story_roster

    story = {
        "roster": [
            {"name": {"en": "A", "de": "Ä"}, "company": "Firma", "site_role": "project_director", "allocation": 40},
            {"name": "B"},
            {"company": "no name"},
            "x",
            {"name": "C", "allocation": 400},
        ]
    }
    rows = story_roster(story, "de")
    assert [r["name"] for r in rows] == ["Ä", "B", "C"]
    assert [r["allocation"] for r in rows] == [40, 100, 100]
    assert story_roster({}, "de") == [] and story_roster({"roster": "x"}, "de") == []


def test_every_shipped_staffing_story_has_a_person_for_each_filled_role() -> None:
    import json
    from pathlib import Path

    from app.modules.staffing.seed import FILLED, story_roster

    demo = Path(__file__).resolve().parents[3] / "packs" / "eleven-areas-framework" / "src"
    for path in demo.glob("*/demo/*-staffing.json"):
        story = json.loads(path.read_text(encoding="utf-8"))
        names = [r["name"] for r in story_roster(story, "de")]
        assert len(names) >= len(story.get("filled") or FILLED), path.name
        assert len(set(names)) == len(names), path.name


class _Member:
    def __init__(self, name: str, site_role: str) -> None:
        self.name = name
        self.site_role = site_role


def test_roles_go_to_the_member_the_story_names_whatever_the_roster_order() -> None:
    # Rows of one flush share created_at and sort by a random id, so the roster arrives shuffled.
    members = [
        _Member("Hartmann", "design_manager"),
        _Member("Pledl", "site_supervisor_mep"),
        _Member("Lindner", "project_director"),
    ]
    pairs = seed.assign_roles(["project_director", "design_manager"], members)
    assert [(r, m.name) for r, m in pairs] == [("project_director", "Lindner"), ("design_manager", "Hartmann")]


def test_roles_nobody_names_take_the_rest_in_roster_order() -> None:
    members = [_Member("A", "foreman"), _Member("B", "site_manager"), _Member("C", "operative")]
    pairs = seed.assign_roles(["project_manager", "site_manager", "hse_manager", "scheduler"], members)
    assert [(r, m.name) for r, m in pairs] == [("project_manager", "A"), ("site_manager", "B"), ("hse_manager", "C")]


def test_shipped_stories_name_a_cast_member_for_every_filled_role() -> None:
    for path in _STORY.parent.glob("*-staffing.json"):
        story = json.loads(path.read_text(encoding="utf-8"))
        cast = seed.story_roster(story, "de")
        members = [_Member(p["name"], p["site_role"]) for p in reversed(cast)]
        pairs = seed.assign_roles(story["filled"], members)
        assert [(r, m.site_role) for r, m in pairs] == [(r, r) for r in story["filled"]], path.name
