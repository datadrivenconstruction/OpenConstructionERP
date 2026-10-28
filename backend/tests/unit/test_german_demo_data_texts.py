# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The German demo projects tell their data in German: defaults by locale, stories by pack file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.commitment_release.validators import _day
from app.modules.documents import documents_seed
from app.modules.site_logistics import demo as site_demo
from app.modules.stakeholders import seed as stakeholder_seed

_DEMO = (
    Path(__file__).resolve().parents[3]
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
)
_PROJECTS = ("residential-regensburg", "school-ludwigsburg")


def _story(project: str, module: str) -> dict:
    return json.loads((_DEMO / f"{project}-{module}.json").read_text(encoding="utf-8-sig"))


def test_a_german_project_without_a_story_gets_german_gates_zones_and_vehicles() -> None:
    gates, zones, vehicles = site_demo.resolve_site_content({}, "de")
    assert (gates, zones, vehicles) == (site_demo._GATES_DE, site_demo._ZONES_DE, site_demo._VEHICLES_DE)
    # Same hours as the English defaults, so every default booking still sits inside its gate.
    assert [g[1:4] for g in gates] == [g[1:4] for g in site_demo._GATES]


def test_other_locales_keep_the_english_defaults() -> None:
    assert site_demo.resolve_site_content({}, "fr")[0] == site_demo._GATES


def test_a_decision_date_reads_in_german_format_for_a_german_reader_only() -> None:
    assert _day("2026-10-09", "de") == "09.10.2026"
    assert _day("2026-10-09", "de-DE") == "09.10.2026"
    assert _day("2026-10-09", "en") == "2026-10-09"
    assert _day(None, "de") == ""
    assert _day("soon", "de") == "soon"


@pytest.mark.parametrize("project", _PROJECTS)
def test_no_stakeholder_commitment_of_the_pack_story_is_overdue_on_the_seed_day(project: str) -> None:
    rows = stakeholder_seed.merge_commitments(_story(project, "stakeholders"), "de")
    assert [due for _text, _cat, _who, due, _ver in rows if due < 0] == []


@pytest.mark.parametrize("project", _PROJECTS)
def test_every_register_document_has_a_german_name_description_and_tags(project: str) -> None:
    story = _story(project, "documents")
    for spec in documents_seed._REGISTER:
        localized = documents_seed._localized(spec, story, "de")
        assert localized.name != spec.name and localized.name.endswith(".pdf"), spec.key
        assert localized.description != spec.description, spec.key
        assert len(localized.tags) == len(spec.tags) and localized.tags != spec.tags, spec.key


def test_a_document_the_story_does_not_name_keeps_its_default() -> None:
    spec = documents_seed._REGISTER[0]
    assert documents_seed._localized(spec, {"documents": {}}, "de") is spec
    assert documents_seed._localized(spec, {}, "de") is spec
