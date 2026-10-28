# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the carbon module's international robustness,
edge-case guards and auditable totals.

Every test here is pure (no session, no DB). They cover the improvements made
to make the carbon engine clear, robust worldwide and trustworthy:

* worldwide grid-intensity resolution with an IEA world-average fallback,
* negative-input guards on the embodied and scope pure-math functions,
* the plain-language, unit-labelled audit basis on an inventory total.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.carbon.service import (
    GRID_FACTOR_WORLD_DEFAULT,
    compute_embodied_entry_carbon,
    compute_inventory_totals,
    compute_scope1_co2e,
    compute_scope2_co2e,
    lookup_grid_factor_default,
    resolve_grid_factor,
)

# ── Worldwide grid-intensity resolution ───────────────────────────────────


def test_world_default_constant_is_documented_and_positive() -> None:
    assert Decimal(GRID_FACTOR_WORLD_DEFAULT["factor"]) > 0
    assert "world" in GRID_FACTOR_WORLD_DEFAULT["source"].lower()
    assert GRID_FACTOR_WORLD_DEFAULT["method"] == "location"


# Countries with a 2023 catalogue entry, spanning several continents.
@pytest.mark.parametrize("country", ["KR", "ID", "CH", "MX", "VN", "NG", "BR", "ZA"])
def test_broad_country_coverage_has_a_catalogued_factor(country: str) -> None:
    """Countries across every continent resolve to a real 2023 catalogue factor."""
    hit = lookup_grid_factor_default(country, 2023)
    assert hit is not None, f"{country} should be catalogued"
    assert hit["factor_kg_co2e_per_kwh"] > 0
    assert hit["fallback"] is False


def test_us_resolves_via_year_fallback() -> None:
    """The US is catalogued for 2021/2022; a 2023 query resolves by nearest year."""
    hit = resolve_grid_factor("US", 2023)
    assert hit is not None
    assert hit["country_code"] == "US"
    assert hit["fallback"] is True
    assert hit["factor_kg_co2e_per_kwh"] > 0


def test_resolve_catalogued_country_matches_lookup() -> None:
    resolved = resolve_grid_factor("DE", 2023)
    assert resolved is not None
    assert resolved["country_code"] == "DE"
    assert resolved["fallback"] is False
    assert resolved["factor_kg_co2e_per_kwh"] == Decimal("0.3800")
    assert "world_fallback" not in resolved


def test_resolve_uncatalogued_country_uses_world_average() -> None:
    """A country outside the catalogue still gets an estimate, clearly flagged."""
    resolved = resolve_grid_factor("ZZ", 2023)
    assert resolved is not None
    assert resolved["country_code"] == "WORLD"
    assert resolved["requested_country"] == "ZZ"
    assert resolved["fallback"] is True
    assert resolved["world_fallback"] is True
    assert resolved["factor_kg_co2e_per_kwh"] == Decimal(GRID_FACTOR_WORLD_DEFAULT["factor"])


def test_resolve_uncatalogued_without_fallback_returns_none() -> None:
    assert resolve_grid_factor("ZZ", 2023, allow_world_fallback=False) is None


def test_resolve_catalogued_still_works_without_fallback() -> None:
    resolved = resolve_grid_factor("GB", 2024, allow_world_fallback=False)
    assert resolved is not None
    assert resolved["country_code"] == "GB"
    assert resolved["fallback"] is False


def test_lookup_unknown_country_still_returns_none() -> None:
    """The catalogue-only lookup keeps its original None contract."""
    assert lookup_grid_factor_default("ZZ", 2023) is None


# ── Embodied carbon edge-case guards ──────────────────────────────────────


def test_embodied_positive_quantity_kg() -> None:
    # 1000 kg steel at 1.35 kgCO2e/kg = 1350 kgCO2e, Decimal-exact.
    result = compute_embodied_entry_carbon(Decimal("1000"), "kg", Decimal("1.35"), "kg")
    assert result == Decimal("1350.00")


def test_embodied_zero_quantity_is_zero_not_error() -> None:
    """An empty line contributes exactly zero and is not an error."""
    assert compute_embodied_entry_carbon(0, "kg", Decimal("1.35"), "kg") == Decimal("0")


def test_embodied_negative_quantity_raises() -> None:
    with pytest.raises(ValueError, match="quantity must not be negative"):
        compute_embodied_entry_carbon(Decimal("-5"), "kg", Decimal("1.35"), "kg")


def test_embodied_negative_factor_raises() -> None:
    with pytest.raises(ValueError, match="emission factor must not be negative"):
        compute_embodied_entry_carbon(Decimal("5"), "kg", Decimal("-1.35"), "kg")


def test_embodied_tiny_factor_no_float_drift() -> None:
    # 3 x 0.000001 = 0.000003 exactly (would drift as float).
    result = compute_embodied_entry_carbon(Decimal("3"), "kg", "0.000001", "kg")
    assert result == Decimal("0.000003")


# ── Scope 1 / Scope 2 edge-case guards ────────────────────────────────────


def test_scope1_positive() -> None:
    assert compute_scope1_co2e(Decimal("1000"), "diesel", Decimal("2.68")) == Decimal("2680.00")


def test_scope1_negative_fuel_raises() -> None:
    with pytest.raises(ValueError, match="fuel quantity must not be negative"):
        compute_scope1_co2e(Decimal("-1"), "diesel", Decimal("2.68"))


def test_scope1_negative_factor_raises() -> None:
    with pytest.raises(ValueError, match="emission factor must not be negative"):
        compute_scope1_co2e(Decimal("100"), "diesel", Decimal("-2.68"))


def test_scope2_positive() -> None:
    assert compute_scope2_co2e(Decimal("2000"), Decimal("0.207")) == Decimal("414.000")


def test_scope2_negative_energy_raises() -> None:
    with pytest.raises(ValueError, match="energy amount must not be negative"):
        compute_scope2_co2e(Decimal("-10"), Decimal("0.207"))


def test_scope2_negative_factor_raises() -> None:
    with pytest.raises(ValueError, match="emission factor must not be negative"):
        compute_scope2_co2e(Decimal("2000"), Decimal("-0.207"))


# ── Auditable, unit-labelled inventory total ──────────────────────────────


def _ns(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def test_totals_carry_explicit_unit_and_audit_basis() -> None:
    inv_id = uuid.uuid4()
    embodied = [
        _ns(stage="a1a3", carbon_kg=Decimal("100")),
        _ns(stage="a4", carbon_kg=Decimal("20")),
        _ns(stage="c", carbon_kg=Decimal("10")),
        _ns(stage="d", carbon_kg=Decimal("-5")),
    ]
    totals = compute_inventory_totals(inv_id, embodied)

    # Unit is explicit so a displayed number is never ambiguous.
    assert totals["unit"] == "kgCO2e"

    # The total excludes module D credits (A1a3 100 + A4 20 + C 10 = 130).
    assert totals["total"] == "130"

    basis = totals["basis"]
    assert isinstance(basis, list)
    joined = "\n".join(basis)
    assert "kgCO2e" in joined
    assert "130" in joined  # the headline total appears in the explanation
    assert "Module D" in joined  # the one deliberate exclusion is stated


def test_basis_reports_operational_and_scope3_split() -> None:
    inv_id = uuid.uuid4()
    s1 = [_ns(total_co2e_kg=Decimal("200"))]
    s2 = [_ns(total_co2e_kg=Decimal("400"))]
    s3 = [_ns(total_co2e_kg=Decimal("100"))]
    totals = compute_inventory_totals(inv_id, (), s1, s2, s3)
    assert totals["operational"] == "600"
    assert totals["scope3"] == "100"
    assert totals["total"] == "700"
    joined = "\n".join(totals["basis"])
    assert "600" in joined  # Scope 1 + 2
    assert "700" in joined  # total
