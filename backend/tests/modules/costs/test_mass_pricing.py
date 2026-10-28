# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for mass-based (per-tonne / per-kg) cost pricing.

These exercise the pure conversion helper and the schema-level mass-field
normalisers, so they run WITHOUT a database. The worked example throughout is
the customer's "360UB" (a 360 mm Universal Beam at 44.7 kg/m): priced at 1850
per tonne, a 12 m member must cost
    12 m x 44.7 kg/m = 536.4 kg = 0.5364 t x 1850 = 992.34.

Coverage
--------
* test_effective_rate_per_tonne / _per_kg
* test_effective_rate_is_none_when_not_mass_priced
* test_effective_rate_rejects_bad_inputs
* test_line_total_matches_mass_chain (the 360UB end-to-end number)
* test_schema_normalises_mass_basis / _mass_per_unit
* test_schema_rejects_bad_mass_inputs
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.costs.schemas import (
    CostItemCreate,
    _normalize_mass_basis,
    _normalize_mass_per_unit,
)
from app.modules.costs.service import mass_effective_unit_rate

# ── Pure conversion helper ──────────────────────────────────────────────


def test_effective_rate_per_tonne() -> None:
    """44.7 kg/m at 1850 per tonne -> 82.695 per metre."""
    rate = mass_effective_unit_rate("1850", "44.7", "t")
    assert rate == Decimal("82.695")


def test_effective_rate_per_kg() -> None:
    """44.7 kg/m at 1.85 per kg -> 82.695 per metre (no /1000 on kg basis)."""
    rate = mass_effective_unit_rate("1.85", "44.7", "kg")
    assert rate == Decimal("82.695")


def test_effective_rate_tonne_vs_kg_are_consistent() -> None:
    """A per-tonne rate and the same per-kg rate (rate/1000) agree."""
    per_t = mass_effective_unit_rate("1850", "44.7", "t")
    per_kg = mass_effective_unit_rate("1.85", "44.7", "kg")
    assert per_t == per_kg


@pytest.mark.parametrize("basis", ["", None, "lb", "g", "tonnes_typo"])
def test_effective_rate_is_none_when_not_mass_priced(basis: str | None) -> None:
    """A blank / unknown basis means mass pricing is off -> fall back to rate."""
    # "tonnes_typo" is not a recognised alias, so it is treated as off.
    assert mass_effective_unit_rate("1850", "44.7", basis) is None


@pytest.mark.parametrize("mpu", ["", None, "0", "-5", "abc", "NaN", "Infinity"])
def test_effective_rate_rejects_bad_mass_per_unit(mpu: str | None) -> None:
    """Missing / zero / negative / non-finite mass -> None, never a bad figure."""
    assert mass_effective_unit_rate("1850", mpu, "t") is None


@pytest.mark.parametrize("rate", ["-1", "abc", "NaN", "Infinity"])
def test_effective_rate_rejects_bad_rate(rate: str) -> None:
    assert mass_effective_unit_rate(rate, "44.7", "t") is None


def test_effective_rate_accepts_numeric_inputs() -> None:
    """JSON numbers (float / int / Decimal) coerce the same as strings."""
    assert mass_effective_unit_rate(1850.0, 44.7, "t") == Decimal("82.695")
    assert mass_effective_unit_rate(Decimal("1850"), Decimal("44.7"), "t") == Decimal("82.695")


def test_line_total_matches_mass_chain() -> None:
    """The full 360UB number: 12 m -> 536.4 kg -> 0.5364 t -> 992.34."""
    qty = Decimal("12")
    effective = mass_effective_unit_rate("1850", "44.7", "t")
    assert effective is not None
    line_total = qty * effective
    assert line_total == Decimal("992.340")
    # Cross-check via the explicit mass chain.
    mass_kg = qty * Decimal("44.7")
    assert mass_kg == Decimal("536.4")
    mass_t = mass_kg / Decimal("1000")
    assert mass_t * Decimal("1850") == Decimal("992.340")


# ── Schema normalisers ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("t", "t"),
        ("T", "t"),
        ("kg", "kg"),
        ("KG", "kg"),
        ("tonne", "t"),
        ("tonnes", "t"),
        ("ton", "t"),
        ("", ""),
        (None, ""),
        ("  ", ""),
    ],
)
def test_schema_normalises_mass_basis(raw: str | None, expected: str) -> None:
    assert _normalize_mass_basis(raw) == expected


def test_schema_rejects_unknown_mass_basis() -> None:
    with pytest.raises(ValueError, match="mass_basis"):
        _normalize_mass_basis("lb")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("44.7", "44.7"),
        (44.7, "44.7"),
        (Decimal("44.70"), "44.70"),
        ("", ""),
        (None, ""),
        ("0", "0"),
    ],
)
def test_schema_normalises_mass_per_unit(raw: object, expected: str) -> None:
    assert _normalize_mass_per_unit(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "abc", "NaN", "Infinity"])
def test_schema_rejects_bad_mass_per_unit(raw: str) -> None:
    with pytest.raises(ValueError, match="mass_per_unit"):
        _normalize_mass_per_unit(raw)


def test_cost_item_create_accepts_mass_fields() -> None:
    """A full create payload validates and normalises the mass fields."""
    item = CostItemCreate(
        code="360UB",
        description="360 mm Universal Beam, grade 300",
        unit="m",
        rate="1850",
        currency="EUR",
        mass_per_unit="44.7",
        mass_basis="t",
        classification={"collection": "Structural Steel"},
    )
    assert item.mass_per_unit == "44.7"
    assert item.mass_basis == "t"
    # The rate is the per-tonne figure; conversion happens at apply time.
    assert item.rate == Decimal("1850")


def test_cost_item_create_defaults_mass_off() -> None:
    """Omitting the mass fields leaves the item a plain per-unit rate."""
    item = CostItemCreate(code="WALL-1", description="Wall", unit="m2", rate="50")
    assert item.mass_per_unit == ""
    assert item.mass_basis == ""
    assert mass_effective_unit_rate(item.rate, item.mass_per_unit, item.mass_basis) is None
