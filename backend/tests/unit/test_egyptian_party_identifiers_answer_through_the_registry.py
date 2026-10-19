# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egyptian identifiers answer through the shared party identifier registry.

Other features (e-invoice pre-submit checks, the subcontractor register) ask
the registry, not the catalogue. These tests pin that the registry answers for
the three Egyptian schemes and that it can never disagree with the
subcontractor tax check, because both read one sourced row.
"""

from __future__ import annotations

import pytest

from app.core import party_identifiers
from app.modules.subcontractors.tax_id import validate_tax_id

NATIONAL_ID = "28503150123457"


def test_egypt_registers_its_three_schemes() -> None:
    assert party_identifiers.schemes_for("eg") == ["commercial_register", "national_id", "rin"]


def test_a_rin_is_checked_and_carries_its_provenance() -> None:
    result = party_identifiers.check("EG", "rin", "١٢٣-٤٥٦-٧٨٩")
    assert result is not None
    assert result.valid, result.reason
    assert result.normalised == "123456789"
    assert result.scheme == "rin"
    assert result.country == "EG"
    assert result.source
    assert result.details["needs_expert_review"] == "yes"
    assert result.details["checksum_verified"] == "no"


def test_a_short_rin_is_a_result_not_an_exception() -> None:
    result = party_identifiers.check("EG", "rin", "1234")
    assert result is not None
    assert not result.valid
    assert result.reason == "format"


def test_a_national_id_reads_out_its_structure_through_the_registry() -> None:
    result = party_identifiers.check("EG", "national_id", NATIONAL_ID)
    assert result is not None
    assert result.valid, result.reason
    assert result.details["birth_date"] == "1985-03-15"


def test_the_commercial_register_is_kept_lenient() -> None:
    result = party_identifiers.check("EG", "commercial_register", "45231")
    assert result is not None
    assert result.valid


def test_an_unregistered_scheme_is_not_judged() -> None:
    assert party_identifiers.check("EG", "vat_number", "123") is None


@pytest.mark.parametrize("value", ["123456789", "123 456 789", "١٢٣٤٥٦٧٨٩", "1234", "1234567890", "", "ABCDEFGHI"])
def test_registry_and_subcontractor_check_agree_on_a_rin(value: str) -> None:
    registry = party_identifiers.check("EG", "rin", value)
    assert registry is not None
    subcontractor = validate_tax_id("EG", value)
    assert registry.valid == bool(subcontractor.format_valid), value
