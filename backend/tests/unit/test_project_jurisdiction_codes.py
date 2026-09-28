# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which jurisdiction codes and measurement systems a project may be set to.

No database: the check reads the regional pack configs and the country table,
both importable on their own. What is pinned is that the settings picker and the
validator cannot drift apart - every option the picker is served is accepted,
and a code nothing in the product carries rules for is refused rather than
stored as a setting that changes nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.projects.jurisdiction import (
    jurisdiction_conflict,
    jurisdiction_country,
    jurisdiction_options,
    jurisdiction_subdivision,
    known_countries,
    known_subdivisions,
    normalise_jurisdiction,
    normalise_unit_system,
)
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" us-ca ", "US-CA"),
        ("US-TX", "US-TX"),
        ("ca-on", "CA-ON"),
        ("de", "DE"),
        ("US", "US"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_a_known_code_is_kept_in_its_canonical_form(raw: str | None, expected: str | None) -> None:
    assert normalise_jurisdiction(raw) == expected


@pytest.mark.parametrize("raw", ["US-ZZ", "US-NY", "ZZ", "USA", "US_CA", "DE-BY-1", "1A"])
def test_a_code_the_platform_carries_nothing_for_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="jurisdiction"):
        normalise_jurisdiction(raw)


@pytest.mark.parametrize(
    ("raw", "expected"), [("Metric", "metric"), (" imperial ", "imperial"), ("", None), (None, None)]
)
def test_the_two_measurement_systems_and_blank(raw: str | None, expected: str | None) -> None:
    assert normalise_unit_system(raw) == expected


@pytest.mark.parametrize("raw", ["us_customary", "si", "feet"])
def test_any_other_measurement_system_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="unit_system"):
        normalise_unit_system(raw)


def test_every_option_the_picker_is_served_is_accepted_as_it_is() -> None:
    options = jurisdiction_options()
    codes = [option["code"] for option in options]
    print(f"options: {len(options)}; subdivisions: {sum(o['kind'] == 'subdivision' for o in options)}")
    assert len(codes) == len(set(codes)), "an option is listed twice"
    # The subdivisions the packs and the tax registry carry, by name, so an
    # empty list cannot pass for a complete one.
    assert {"US-CA", "US-TX", "CA-ON", "CA-QC"} <= set(codes)
    assert {"US", "CA", "DE", "GB", "CN", "IN", "BR"} <= set(codes)
    for option in options:
        assert normalise_jurisdiction(option["code"]) == option["code"]
        assert option["country_code"] == jurisdiction_country(option["code"])
        assert option["country_code"] in known_countries(), f"{option['code']} lies in an unknown country"
    assert set(known_subdivisions()) == {o["code"] for o in options if o["kind"] == "subdivision"}


def test_the_country_and_subdivision_halves_are_read_apart() -> None:
    assert jurisdiction_country("US-CA") == "US"
    assert jurisdiction_subdivision("US-CA") == "US-CA"
    assert jurisdiction_subdivision("US") is None
    assert jurisdiction_subdivision(None) is None


def test_a_conflict_needs_both_halves_set_and_different() -> None:
    assert jurisdiction_conflict("US-CA", "DE") is True
    assert jurisdiction_conflict("US-CA", "us") is False
    assert jurisdiction_conflict("US-CA", None) is False
    assert jurisdiction_conflict(None, "DE") is False


def test_neither_field_is_filled_from_the_country() -> None:
    # The founder's condition for the feature: an empty field keeps every
    # consumer on the answer it derives from the country, so a create that
    # names only a country must come out with both fields unset.
    created = ProjectCreate(name="Tower", country_code="US")
    assert created.jurisdiction is None
    assert created.unit_system is None


def test_the_request_schemas_refuse_what_the_codes_refuse() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="Tower", jurisdiction="US-NY")
    with pytest.raises(ValidationError):
        ProjectUpdate(unit_system="furlongs")
    patch = ProjectUpdate(jurisdiction="us-tx", unit_system="IMPERIAL")
    assert (patch.jurisdiction, patch.unit_system) == ("US-TX", "imperial")
    # An explicit null is a request to clear, and must survive as a set field.
    cleared = ProjectUpdate(jurisdiction=None)
    assert "jurisdiction" in cleared.model_fields_set
