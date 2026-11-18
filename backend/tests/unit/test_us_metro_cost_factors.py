# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""US metro cost factors come from the public BLS wage table, by the stated method."""

from __future__ import annotations

from decimal import Decimal

from app.scripts import seed_regional_indices as seed


def test_us_rows_are_derived_from_bls_wages() -> None:
    factors = seed.us_metro_factors()
    assert factors["US_NATIONAL"]["labor"] == Decimal("1.00")
    # 82,140 / 65,360 = 1.2567
    assert factors["US_NYC"]["labor"] == Decimal("1.26")
    # Concrete moves by its 40 percent labour share only.
    assert factors["US_NYC"]["concrete"] == Decimal("1.10")
    assert factors["US_HOUSTON"]["labor"] == Decimal("0.87")
    assert "US_NYC" not in seed._FACTORS, "no US row may come from the commercial-index matrix"


def test_us_rows_carry_their_public_source() -> None:
    us_rows = [r for r in seed._rows() if str(r["region_code"]).startswith("US_")]
    assert len(us_rows) == 12 * 6
    assert {r["source"] for r in us_rows} == {"BLS_OEWS_2025_05_SOC47"}
    assert all(r["effective_date"] > seed._SEED_DATE for r in us_rows)
