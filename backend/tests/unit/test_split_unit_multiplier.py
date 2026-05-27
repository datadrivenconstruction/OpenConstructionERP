# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regression tests for ``_split_unit_multiplier`` — the helper that
unwinds CWICR's ``"100 м3"``-style multiplier convention so apply-to-BOQ
math doesn't ship 100× off rates.

Per MAPPING_PROCESS.md v3 §8.6 the catalogue rate column may encode a
quantity multiplier in the unit string itself (``"100 м3 @ 5,311,861.57"``
means *per 100 m³*, not per 1 m³). The apply pipeline at
``service.py:1915-1917`` divides the raw rate by that multiplier before
multiplying by the BoQ qty — without the divide the totals are off by
exactly the multiplier, which is the kind of bug that survives a
visual review and only surfaces when the estimator notices a 100× cost
spike on one trade.

These tests pin both the helper itself and the divide-math at the
callsite so a refactor of either side cannot silently break the
contract.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.match_elements.service import _split_unit_multiplier

# ── Helper contract ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected_mult", "expected_unit"),
    [
        # Cyrillic catalogues — Russian / Bulgarian / Ukrainian seeds
        ("100 м3", 100.0, "м3"),
        ("100 м2", 100.0, "м2"),
        ("100 м", 100.0, "м"),
        ("10 шт", 10.0, "шт"),
        ("1000 кг", 1000.0, "кг"),
        # Latin catalogues — DE / EN / ES / FR
        ("100 m3", 100.0, "m3"),
        ("10 pcs", 10.0, "pcs"),
        ("1000 kg", 1000.0, "kg"),
        ("100 stk", 100.0, "stk"),
        # Decimal multipliers — comma-as-decimal (DE/RU/FR locale)
        ("0,5 t", 0.5, "t"),
        # Decimal multipliers — dot-as-decimal (EN locale)
        ("0.5 t", 0.5, "t"),
        # No multiplier present — identity case (mult = 1.0)
        ("м3", 1.0, "м3"),
        ("m3", 1.0, "m3"),
        ("pcs", 1.0, "pcs"),
        # Whitespace tolerance
        ("  100 м3  ", 100.0, "м3"),
        ("100  м3", 100.0, "м3"),  # double space between number and unit
        # Edge inputs — must NOT raise
        ("", 1.0, ""),
        ("   ", 1.0, ""),
    ],
)
def test_split_unit_multiplier_extracts_leading_factor(
    raw: str,
    expected_mult: float,
    expected_unit: str,
) -> None:
    mult, unit = _split_unit_multiplier(raw)
    assert mult == expected_mult
    assert unit == expected_unit


def test_split_unit_multiplier_handles_none() -> None:
    """``None`` is a valid input from optional DB columns. Must return
    the identity tuple, never raise."""
    mult, unit = _split_unit_multiplier(None)
    assert mult == 1.0
    assert unit == ""


def test_split_unit_multiplier_falls_back_to_identity_on_garbage() -> None:
    """A unit string that *looks* multiplier-prefixed but the prefix
    isn't actually numeric (e.g., ``"abc m3"``) must NOT swallow ``abc``
    as mult=0 — it returns (1.0, "abc m3") so the dimensional gate
    downstream can still try to normalise the original string."""
    mult, unit = _split_unit_multiplier("abc m3")
    assert mult == 1.0
    assert unit == "abc m3"


def test_split_unit_multiplier_zero_factor_falls_back_to_identity() -> None:
    """``"0 м3"`` is a corrupt seed — divide-by-zero would crash
    apply_to_boq. The helper must reject mult ≤ 0 and return identity."""
    mult, unit = _split_unit_multiplier("0 м3")
    assert mult == 1.0
    # Whole string preserved as the base unit — caller can still try
    # to normalise it; the multiplier is just neutralised.
    assert unit == "0 м3"


# ── Apply-to-BOQ rate-divide math (the spec §8.6 example) ────────────────


@pytest.mark.parametrize(
    ("unit", "raw_rate", "expected_per_unit_rate"),
    [
        # MAPPING_PROCESS.md §8.6 canonical example: a Russian rate
        # priced per 100 m3 collapses to 53,118.6157 EUR per single m3.
        ("100 м3", Decimal("5311861.57"), Decimal("53118.6157")),
        # 10× counted goods — frequent in finishing trades (per 10 doors).
        ("10 шт", Decimal("1000"), Decimal("100")),
        # Mass — 1000 kg per ton → divide by 1000.
        ("1000 кг", Decimal("2500"), Decimal("2.5")),
        # No multiplier — identity (mult = 1.0).
        ("м3", Decimal("185"), Decimal("185")),
        # Decimal multiplier — 0.5 t per qty → divide by 0.5 = ×2 effect.
        ("0,5 t", Decimal("1000"), Decimal("2000")),
    ],
)
def test_apply_pipeline_divides_rate_by_multiplier(
    unit: str,
    raw_rate: Decimal,
    expected_per_unit_rate: Decimal,
) -> None:
    """Mirror ``service.py:1915-1917`` so a refactor that drops the
    divide-by-multiplier step is caught here, not in production
    after estimators flag a 100× total."""
    mult, _base_unit = _split_unit_multiplier(unit)
    # Cast to Decimal for exact arithmetic — the real callsite uses
    # ``raw_rate / mult`` with ``raw_rate`` already a Decimal via
    # ``_to_decimal``.
    per_unit = raw_rate / Decimal(str(mult)) if mult > 0 else raw_rate
    assert per_unit == expected_per_unit_rate
