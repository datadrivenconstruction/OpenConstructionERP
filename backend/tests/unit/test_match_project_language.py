# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""A project's region label resolves to the catalogue language it wants.

The project form stores labels ("Italy", "DACH") in ``project.region``.
``language_for`` only knows catalogue ids, so every label used to resolve
to English, and an Italian project was bound to the English catalogue.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.match_service.boosts.region import _project_region_prefixes
from app.core.match_service.region_language import (
    PROJECT_REGION_LABELS,
    language_for,
    project_country,
    project_language,
    resolve_language,
)

_CREATE_PROJECT_PAGE = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "projects" / "CreateProjectPage.tsx"
)


def _form_region_values() -> list[str]:
    """Every ``value`` in REGION_GROUPS of the project form."""
    src = _CREATE_PROJECT_PAGE.read_text(encoding="utf-8")
    start = src.index("const REGION_GROUPS")
    end = src.index("];", start)
    values = re.findall(r"\{\s*value:\s*'([^']+)'", src[start:end])
    assert values, "REGION_GROUPS parsed to nothing; the form changed shape"
    # "Custom..." is never stored: the form saves the typed text instead.
    return [v for v in values if v != "__custom__"]


def test_every_project_form_region_is_known() -> None:
    """A region added to the form without a language entry would fall to English."""
    missing = [v for v in _form_region_values() if v not in PROJECT_REGION_LABELS]
    assert missing == []


def test_no_stale_label_entries() -> None:
    """The table carries no label the form no longer offers."""
    stale = sorted(set(PROJECT_REGION_LABELS) - set(_form_region_values()))
    assert stale == []


@pytest.mark.parametrize(
    ("region", "language", "country"),
    [
        ("Italy", "it", "IT"),
        ("DACH", "de", "DE"),
        ("France", "fr", "FR"),
        ("Spain", "es", "ES"),
        ("UK", "en", "GB"),
        ("US", "en", "US"),
        ("Czech", "cs", "CZ"),
        ("Korea", "ko", "KR"),
        ("Brazil", "pt", "BR"),
        ("Mexico", "es", "MX"),
        ("NewZealand", "en", "NZ"),
        ("SouthAfrica", "en", "ZA"),
        ("LatinAmerica", "es", None),
        ("GulfStates", "ar", None),
        ("Nordics", None, None),
        ("SoutheastAsia", None, None),
        ("WestAfrica", None, None),
        ("INTL", None, None),
    ],
)
def test_form_label_resolves(region: str, language: str | None, country: str | None) -> None:
    assert project_language(region) == language
    assert project_country(region) == country


@pytest.mark.parametrize("region", _form_region_values())
def test_no_form_label_is_read_as_english_by_default(region: str) -> None:
    """Only labels that really are English-speaking resolve to "en"."""
    english = {"UK", "Ireland", "US", "Canada", "India", "SouthAfrica", "EastAfrica", "Australia", "NewZealand"}
    if region in english:
        assert project_language(region) == "en"
    else:
        assert project_language(region) != "en"


def test_labels_are_case_insensitive() -> None:
    assert project_language("italy") == "it"
    assert project_language("  ITALY ") == "it"


def test_country_code_wins_over_region() -> None:
    assert project_language("DACH", "IT") == "it"
    assert project_country("DACH", "it") == "IT"


def test_country_code_without_catalogue_falls_through_to_region() -> None:
    # Norway has no catalogue; the region still answers.
    assert project_language("DACH", "NO") == "de"


def test_catalogue_ids_and_country_names_still_resolve() -> None:
    assert project_language("IT_ROME") == "it"
    assert project_language("DE_BERLIN") == "de"
    assert project_language("Italia") == "it"
    assert project_language("Deutschland") == "de"
    assert project_country("IT_ROME") == "IT"
    assert project_country("USA_USD") == "US"
    assert project_country("SV_STOCKHOLM") == "SE"


def test_unknown_region_is_none_not_english() -> None:
    assert project_language("Atlantis") is None
    assert project_language("") is None
    assert project_language(None) is None
    assert project_country("Atlantis") is None


def test_resolve_language_has_no_fallback() -> None:
    assert resolve_language("IT_ROME") == "it"
    assert resolve_language("ITALY") is None
    # language_for keeps its fallback for catalogue-row stamping.
    assert language_for("ITALY") == "en"


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("Italy", ("IT_",)),
        ("Spain", ("ES_",)),
        ("DACH", ("DE_", "AT_", "CH_")),
        ("IT_ROME", ("IT_ROME",)),
        ("Nordics", ()),
    ],
)
def test_region_boost_prefixes_resolve_form_labels(region: str, expected: tuple[str, ...]) -> None:
    settings = SimpleNamespace(project=SimpleNamespace(region=region))
    assert _project_region_prefixes(settings) == expected


# ── country -> language from the catalogue registry ──────────────────────
#
# The catalogue registry says which language each country's catalogue is
# in. A country code that the general table cannot place ("SE", "US") must
# not fall through to "no language" when a catalogue for it exists.


def _available_catalogues():
    from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES

    return [c for c in CWICR_V3_CATALOGUES if c.available]


@pytest.mark.parametrize(
    ("region", "country_code", "expected"),
    [
        ("", "SE", "sv"),
        ("Nordics", "SE", "sv"),
        ("INTL", "US", "en"),
        ("", "VN", "vi"),
        ("", "CN", "zh"),
        ("United States", None, "en"),
        ("Sweden", None, "sv"),
    ],
)
def test_country_language_comes_from_the_catalogue_registry(region, country_code, expected) -> None:
    assert project_language(region, country_code) == expected


def test_every_catalogue_country_resolves_to_its_catalogue_language() -> None:
    by_country: dict[str, set[str]] = {}
    for cat in _available_catalogues():
        by_country.setdefault(cat.country_iso.upper(), set()).add(cat.language)
    wrong = {
        iso: (langs, project_language("", iso))
        for iso, langs in by_country.items()
        if len(langs) == 1 and project_language("", iso) not in langs
    }
    assert wrong == {}


# ── a group label recommends a catalogue from inside the group ───────────


@pytest.mark.parametrize(
    ("region", "installed", "expected_region"),
    [
        ("EastAfrica", {"en"}, "KE_NAIROBI"),
        ("LatinAmerica", {"es"}, "MX_MEXICO"),
        ("NorthAfrica", {"ar"}, "MA_CASABLANCA"),
        ("MiddleEast", {"ar"}, "AE_DUBAI"),
        ("GulfStates", {"ar"}, "AE_DUBAI"),
        ("WestAfrica", {"en", "fr"}, "NG_LAGOS"),
        ("Ireland", {"en"}, "GB_LONDON"),
        ("DACH", {"de"}, "DE_BERLIN"),
        ("Italy", {"it"}, "IT_ROME"),
    ],
)
def test_group_labels_recommend_a_catalogue_from_the_group(region, installed, expected_region) -> None:
    from app.core.match_service.region_language import project_countries
    from app.modules.match_elements.readiness import recommend_catalogue

    rec = recommend_catalogue(project_language(region), project_countries(region), installed)
    assert rec is not None
    assert rec.region == expected_region


def test_preferred_country_lists_name_countries_that_have_catalogues() -> None:
    from app.core.match_service.region_language import PROJECT_REGION_COUNTRIES

    have = {c.country_iso.upper() for c in _available_catalogues()}
    for label, countries in PROJECT_REGION_COUNTRIES.items():
        assert label in PROJECT_REGION_LABELS, label
        assert any(c in have for c in countries), (label, countries)


def test_country_code_narrows_a_group_to_that_country() -> None:
    from app.core.match_service.region_language import project_countries

    assert project_countries("Nordics", "SE") == ("SE",)
    assert project_countries("EastAfrica")[:3] == ("KE", "UG", "TZ")
    assert project_countries("INTL") == ()
    assert project_countries("Italy") == ("IT",)


# ── region boost heads agree with the catalogue ids ──────────────────────


def test_country_boost_reaches_every_catalogue_of_that_country() -> None:
    misses = {}
    for cat in _available_catalogues():
        settings = SimpleNamespace(project=SimpleNamespace(region=cat.country_iso, country_code=None))
        prefixes = _project_region_prefixes(settings)
        if not any(cat.region.upper().startswith(p.upper()) for p in prefixes):
            misses[cat.region] = (cat.country_iso, prefixes)
    assert misses == {}


@pytest.mark.parametrize(
    ("iso", "head"),
    [("CN", "ZH_"), ("SE", "SV_"), ("VN", "VI_"), ("US", "USA_")],
)
def test_catalogue_heads_that_differ_from_the_iso_code(iso, head) -> None:
    settings = SimpleNamespace(project=SimpleNamespace(region=iso, country_code=None))
    assert head in _project_region_prefixes(settings)


def test_region_boost_reads_the_address_country_for_a_group_label() -> None:
    settings = SimpleNamespace(project=SimpleNamespace(region="Nordics", country_code="SE"))
    assert "SV_" in _project_region_prefixes(settings)


@pytest.mark.parametrize("region", ["Nordics", "SoutheastAsia", "WestAfrica", "INTL"])
def test_metadata_scorer_has_no_two_letter_guess_for_unplaceable_labels(region) -> None:
    from app.core.match_service.envelope import ElementEnvelope
    from app.core.match_service.ranker_qdrant import _score_payload_against_envelope

    envelope = ElementEnvelope(source="text", description="wall")
    first_two = region.upper()[:2]  # "NO", "SO", "WE", "IN"
    _score, breakdown = _score_payload_against_envelope(
        {"country": first_two}, envelope=envelope, project_region=region
    )
    assert breakdown.get("region", 0.0) == 0.0
