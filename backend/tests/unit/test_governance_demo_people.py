# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The people who own the areas of the two filmed demo projects: file shape, names and mail addresses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.project_governance import seed_story
from app.modules.project_governance.seed_people import PEOPLE_DOMAIN, parse_people, person_email

_ROOT = Path(__file__).resolve().parents[3]
_DEMO = _ROOT / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
_AREAS = {f"m{n:02d}" for n in range(1, 12)}


def _entries() -> dict[str, dict]:
    data = json.loads((_DEMO / "demo_project.json").read_text(encoding="utf-8"))
    return {e["project"]["demo_template_id"]: e for e in seed_story.project_entries(data)}


def test_mail_address_is_ascii_on_the_reserved_domain() -> None:
    assert person_email("sabine.rottenwoehrer") == f"sabine.rottenwoehrer@{PEOPLE_DOMAIN}"
    assert person_email("Lena Wöhrle") == f"lena.wohrle@{PEOPLE_DOMAIN}"
    assert PEOPLE_DOMAIN.endswith("example.org")


def test_parse_drops_unusable_rows_and_a_second_owner_of_one_area() -> None:
    entry = {
        "people": [
            {"key": "a.b", "name": "A B", "area": "x"},
            {"key": "c.d", "name": "C D", "area": "x"},
            {"key": "", "name": "E F", "area": "y"},
            {"key": "g.h", "area": "z"},
            "nonsense",
        ]
    }
    assert [p["key"] for p in parse_people(entry, "de")] == ["a.b"]
    assert parse_people(None, "de") == []


@pytest.mark.parametrize("demo_id", ["residential-regensburg", "school-ludwigsburg"])
def test_each_filmed_project_names_ten_distinct_people_for_ten_areas(demo_id: str) -> None:
    people = parse_people(_entries()[demo_id], "de")
    assert len(people) == 10
    assert len({p["key"] for p in people}) == 10
    assert len({p["name"] for p in people}) == 10
    assert len({person_email(p["key"]) for p in people}) == 10
    assert {p["area"][:3] for p in people} <= _AREAS
    # The project's own account keeps the project management area.
    assert "m01_project_management" not in {p["area"] for p in people}


@pytest.mark.parametrize("demo_id", ["residential-regensburg", "school-ludwigsburg"])
def test_the_people_are_the_ones_the_staffing_story_names(demo_id: str) -> None:
    """One name is one person across the modules: every owner is a line of the staffing roster, firm included."""
    staffing = json.loads((_DEMO / f"{demo_id}-staffing.json").read_text(encoding="utf-8"))
    roster = {r["name"]["de"]: r["company"]["de"] for r in staffing["roster"]}
    for person in parse_people(_entries()[demo_id], "de"):
        assert roster.get(person["name"]) == person["company"], person


def test_the_handbook_edition_follows_the_phase_of_each_filmed_project() -> None:
    from app.modules.project_handbook.seed import _PROFILES

    assert _PROFILES["residential-regensburg"]["edition"] == "Ausgabe 2, Ausführungsphase"
    assert _PROFILES["school-ludwigsburg"]["edition"] == "Ausgabe 1, Entwicklungsphase"
