# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SIREN and SIRET through the shared party identifier registry.

The cases are chosen so a wrong implementation fails a specific one: a shape
check alone passes the one-digit typo, a Luhn check alone refuses the La Poste
establishment, and an exception keyed on the digit sum alone would accept any
number whose digits happen to add up to a multiple of five.
"""

from __future__ import annotations

import pytest

from app.core import party_identifiers as pid
from app.core.party_identifiers import fr


class TestSiren:
    def test_a_valid_siren_passes_and_is_normalised(self) -> None:
        result = pid.check("FR", "siren", "732 829 320")
        assert result is not None
        assert result.valid
        assert result.normalised == "732829320"
        assert result.reason is None
        assert result.details["icd"] == "0002"
        assert result.source and result.source.startswith("https://www.insee.fr/")

    def test_one_changed_digit_fails_on_the_key_not_on_the_shape(self) -> None:
        result = pid.check("FR", "siren", "732829321")
        assert result is not None
        assert not result.valid
        assert result.reason == fr.REASON_CHECKSUM

    @pytest.mark.parametrize("raw", ["73282932", "7328293200", "73282932A", ""])
    def test_a_wrong_shape_is_a_shape_failure(self, raw: str) -> None:
        result = pid.check("FR", "siren", raw)
        assert result is not None
        assert not result.valid
        assert result.reason == fr.REASON_SHAPE

    def test_lookup_is_case_insensitive_on_country_and_scheme(self) -> None:
        result = pid.check("fr", "SIREN", "552100554")
        assert result is not None and result.valid


class TestSiret:
    def test_a_valid_siret_passes_and_exposes_its_siren(self) -> None:
        result = pid.check("FR", "siret", "732 829 320 00074")
        assert result is not None
        assert result.valid
        assert result.normalised == "73282932000074"
        assert result.details["icd"] == "0009"
        assert fr.siren_of_siret("73282932000074") == "732829320"

    def test_a_valid_siren_with_a_wrong_establishment_key_fails(self) -> None:
        result = pid.check("FR", "siret", "73282932000075")
        assert result is not None
        assert not result.valid
        assert result.reason == fr.REASON_CHECKSUM

    def test_la_poste_establishment_passes_on_the_documented_exception(self) -> None:
        # Fails Luhn, digit sum is a multiple of five, SIREN is La Poste's.
        result = pid.check("FR", "siret", "35600000049837")
        assert result is not None
        assert result.valid
        assert result.reason == fr.REASON_EXCEPTION
        assert result.details["needs_expert_review"] == "true"

    def test_the_exception_is_keyed_on_la_poste_and_not_on_the_digit_sum(self) -> None:
        # Same digit-sum property, different SIREN: no exception.
        assert sum(int(c) for c in "35700000049827") % 5 == 0
        result = pid.check("FR", "siret", "35700000049827")
        assert result is not None
        assert not result.valid
        assert result.reason == fr.REASON_CHECKSUM

    def test_la_poste_head_office_passes_luhn_without_the_exception(self) -> None:
        result = pid.check("FR", "siret", "35600000000048")
        assert result is not None
        assert result.valid
        assert "needs_expert_review" not in result.details


class TestRegistry:
    def test_an_unregistered_scheme_is_not_checked(self) -> None:
        assert pid.check("XX", "nope", "1") is None

    def test_schemes_for_lists_the_french_ones(self) -> None:
        assert {"siren", "siret"} <= set(pid.schemes_for("FR"))
