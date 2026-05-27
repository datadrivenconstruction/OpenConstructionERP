# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Completeness tests for vat_rates in all regional pack configs (Wave 25 / task #168).

For each pack that declares a non-empty ``vat_rates`` dict, assert that:
1. Every country entry has a ``'standard'`` key.
2. Every rate is a valid :class:`~decimal.Decimal` in the range [0, 0.50].
3. All non-empty packs were explicitly registered in this test
   (so adding a new pack without vat_rates is caught).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.modules.asia_pac_pack.config import PACK_CONFIG as APAC_CFG

# ── Import all regional pack configs ──────────────────────────────────────────
from app.modules.dach_pack.config import PACK_CONFIG as DACH_CFG
from app.modules.india_pack.config import PACK_CONFIG as IN_CFG
from app.modules.latam_pack.config import PACK_CONFIG as LATAM_CFG
from app.modules.middle_east_pack.config import PACK_CONFIG as ME_CFG
from app.modules.russia_pack.config import PACK_CONFIG as RU_CFG
from app.modules.uk_pack.config import PACK_CONFIG as UK_CFG
from app.modules.us_pack.config import PACK_CONFIG as US_CFG

# ── Registry of all packs ─────────────────────────────────────────────────────

_PACKS: list[tuple[str, dict[str, Any]]] = [
    ("DACH", DACH_CFG),
    ("UK", UK_CFG),
    ("US", US_CFG),
    ("ME", ME_CFG),
    ("APAC", APAC_CFG),
    ("IN", IN_CFG),
    ("LATAM", LATAM_CFG),
    ("RU", RU_CFG),
]

# Expected countries per pack — used to check coverage is not accidentally
# reduced (missing a country is silent until a consumer queries it).
_EXPECTED_COUNTRIES: dict[str, set[str]] = {
    "DACH": {"DE", "AT", "CH"},
    "UK": {"GB"},
    "US": set(),  # No federal VAT — vat_rates is empty
    "ME": {"AE", "SA", "BH", "OM", "QA", "KW"},
    "APAC": {"AU", "NZ", "JP", "SG"},
    "IN": {"IN"},
    "LATAM": {"MX", "AR", "CL", "CO", "PE"},
    "RU": {"RU"},
}

# Packs where vat_rates is intentionally empty (no federal VAT)
_PACKS_WITH_NO_VAT = {"US"}

_MAX_RATE = Decimal("0.50")  # Sanity ceiling — no known jurisdiction above 50 %
_MIN_RATE = Decimal("0.00")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _vat_rates(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract vat_rates dict from a pack config (defaults to empty)."""
    return config.get("vat_rates", {})


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestAllPacksHaveVatRatesKey:
    """Every pack config must declare a 'vat_rates' key (even if empty for US)."""

    @pytest.mark.parametrize("pack_name,config", _PACKS)
    def test_vat_rates_key_present(self, pack_name: str, config: dict[str, Any]) -> None:
        assert "vat_rates" in config, (
            f"Pack {pack_name!r} is missing the 'vat_rates' key. "
            "All regional packs must declare vat_rates (empty dict {} for no-VAT jurisdictions)."
        )


class TestUSPackIsEmpty:
    """US vat_rates must be explicitly empty — no federal VAT."""

    def test_us_vat_rates_is_empty(self) -> None:
        assert _vat_rates(US_CFG) == {}, (
            "US vat_rates should be {} (no federal VAT). Per-state sales tax examples belong in tax_rules."
        )


class TestPackVatRatesStructure:
    """For packs with non-empty vat_rates, validate every entry."""

    @pytest.mark.parametrize(
        "pack_name,config", [(name, cfg) for name, cfg in _PACKS if name not in _PACKS_WITH_NO_VAT]
    )
    def test_every_country_has_standard_key(self, pack_name: str, config: dict[str, Any]) -> None:
        vat_rates = _vat_rates(config)
        for country, rates in vat_rates.items():
            assert "standard" in rates, (
                f"Pack {pack_name!r} country {country!r} is missing the 'standard' key "
                f"in vat_rates. Got keys: {sorted(rates.keys())}"
            )

    @pytest.mark.parametrize(
        "pack_name,config", [(name, cfg) for name, cfg in _PACKS if name not in _PACKS_WITH_NO_VAT]
    )
    def test_all_rates_are_decimal(self, pack_name: str, config: dict[str, Any]) -> None:
        vat_rates = _vat_rates(config)
        for country, rates in vat_rates.items():
            for kind, rate in rates.items():
                assert isinstance(rate, Decimal), (
                    f"Pack {pack_name!r} country {country!r} kind {kind!r}: "
                    f"rate must be Decimal, got {type(rate).__name__!r} ({rate!r}). "
                    "Store rates as Decimal('0.19'), not 0.19 (float) or '0.19' (str)."
                )

    @pytest.mark.parametrize(
        "pack_name,config", [(name, cfg) for name, cfg in _PACKS if name not in _PACKS_WITH_NO_VAT]
    )
    def test_all_rates_in_valid_range(self, pack_name: str, config: dict[str, Any]) -> None:
        vat_rates = _vat_rates(config)
        for country, rates in vat_rates.items():
            for kind, rate in rates.items():
                assert _MIN_RATE <= rate <= _MAX_RATE, (
                    f"Pack {pack_name!r} country {country!r} kind {kind!r}: "
                    f"rate {rate!r} is outside the valid range "
                    f"[{_MIN_RATE}, {_MAX_RATE}]. "
                    "Rates are decimal fractions (0.19 = 19 %), not percentages."
                )


class TestExpectedCountryCoverage:
    """Verify that each pack covers the expected set of countries."""

    @pytest.mark.parametrize("pack_name,config", _PACKS)
    def test_expected_countries_covered(self, pack_name: str, config: dict[str, Any]) -> None:
        vat_rates = _vat_rates(config)
        covered = set(vat_rates.keys())
        expected = _EXPECTED_COUNTRIES.get(pack_name, set())
        missing = expected - covered
        assert not missing, (
            f"Pack {pack_name!r} is missing expected countries in vat_rates: {sorted(missing)}. "
            "Add the missing country entries or update _EXPECTED_COUNTRIES if the country "
            "genuinely has no VAT system."
        )


class TestDACHRateValues:
    """Spot-check key DACH values that were the primary audit trigger."""

    def test_de_standard_is_19pct(self) -> None:
        de_rates = DACH_CFG["vat_rates"]["DE"]
        assert de_rates["standard"] == Decimal("0.19")

    def test_at_standard_is_20pct(self) -> None:
        at_rates = DACH_CFG["vat_rates"]["AT"]
        assert at_rates["standard"] == Decimal("0.20")

    def test_ch_standard_is_8_1pct(self) -> None:
        ch_rates = DACH_CFG["vat_rates"]["CH"]
        assert ch_rates["standard"] == Decimal("0.081")

    def test_de_reduced_is_7pct(self) -> None:
        de_rates = DACH_CFG["vat_rates"]["DE"]
        assert de_rates["reduced"] == Decimal("0.07")


class TestUKRateValues:
    """UK rates — HMRC VAT Notice 700."""

    def test_gb_standard_is_20pct(self) -> None:
        assert UK_CFG["vat_rates"]["GB"]["standard"] == Decimal("0.20")

    def test_gb_reduced_is_5pct(self) -> None:
        assert UK_CFG["vat_rates"]["GB"]["reduced"] == Decimal("0.05")

    def test_gb_zero_is_0pct(self) -> None:
        assert UK_CFG["vat_rates"]["GB"]["zero"] == Decimal("0.00")
