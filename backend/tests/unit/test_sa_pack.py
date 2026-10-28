# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the South Africa regional pack (oe_sa_pack).

Covers the stateless service: the PPPFA price-points formula and the ZA VAT
breakdown. These functions have no database dependency, so they run in
isolation. Money is asserted to come back as strings (never float).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.tax import VATNotApplicable
from app.modules.sa_pack.config import PACK_CONFIG, PPPFA_THRESHOLD_ZAR
from app.modules.sa_pack.service import calculate_vat, score_pppfa


class TestPPPFAScoring:
    """Official PPPFA price-points formula: Ps = W * (1 - (Pt - P_min) / P_min)."""

    def test_lowest_bid_earns_full_price_weight_8020(self) -> None:
        result = score_pppfa(Decimal("1000000"), Decimal("1000000"), Decimal("20"))
        assert result["system"] == "80/20"
        assert result["price_points"] == "80.00"
        assert result["total_points"] == "100.00"

    def test_higher_bid_9010_and_preference_capped(self) -> None:
        # Estimated value above R50m selects 90/10; preference capped at 10.
        result = score_pppfa(Decimal("1100000"), Decimal("1000000"), Decimal("18"), Decimal("60000000"))
        assert result["system"] == "90/10"
        assert result["price_points"] == "81.00"
        assert result["preference_points"] == "10.00"
        assert result["total_points"] == "91.00"

    def test_twenty_percent_over_lowest(self) -> None:
        result = score_pppfa(Decimal("1200000"), Decimal("1000000"), Decimal("20"), system="80/20")
        # 80 * (1 - 0.2) = 64.00
        assert result["price_points"] == "64.00"
        assert result["total_points"] == "84.00"

    def test_bid_far_above_lowest_floors_at_zero(self) -> None:
        # A bid more than double the lowest would compute negative raw points;
        # PPPFA floors price points at zero, never negative.
        result = score_pppfa(Decimal("3000000"), Decimal("1000000"), Decimal("20"), system="80/20")
        assert result["price_points"] == "0.00"
        assert result["total_points"] == "20.00"

    def test_system_threshold_is_inclusive(self) -> None:
        threshold = Decimal(PPPFA_THRESHOLD_ZAR)
        at = score_pppfa(Decimal("1000000"), Decimal("1000000"), estimated_value=threshold)
        above = score_pppfa(Decimal("1000000"), Decimal("1000000"), estimated_value=threshold + Decimal("1"))
        assert at["system"] == "80/20"
        assert above["system"] == "90/10"

    def test_bid_below_lowest_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            score_pppfa(Decimal("900000"), Decimal("1000000"))

    def test_nonpositive_price_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            score_pppfa(Decimal("0"), Decimal("1000000"))

    def test_negative_preference_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            score_pppfa(Decimal("1000000"), Decimal("1000000"), Decimal("-1"))

    def test_money_fields_are_strings(self) -> None:
        result = score_pppfa(Decimal("1000000"), Decimal("1000000"))
        for key in ("bid_price", "price_points", "preference_points", "total_points"):
            assert isinstance(result[key], str)


class TestVatCalc:
    """ZA VAT breakdown, reusing app.core.tax."""

    def test_standard_15pct(self) -> None:
        result = calculate_vat(Decimal("100000"))
        assert result["vat_rate"] == "0.15"
        assert result["vat"] == "15000.00"
        assert result["inclusive"] == "115000.00"

    def test_zero_rated(self) -> None:
        result = calculate_vat(Decimal("100000"), "zero")
        assert result["vat"] == "0.00"
        assert result["inclusive"] == "100000.00"

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(ValueError):
            calculate_vat(Decimal("-1"))

    def test_unknown_kind_raises_vat_not_applicable(self) -> None:
        # South Africa has no reduced tier.
        with pytest.raises(VATNotApplicable):
            calculate_vat(Decimal("100"), "reduced")


class TestPackConfig:
    """Sanity checks on the SA regional configuration."""

    def test_nine_provinces(self) -> None:
        assert len(PACK_CONFIG["provinces"]) == 9

    def test_currency_is_zar(self) -> None:
        assert PACK_CONFIG["default_currency"] == "ZAR"

    def test_vat_rates_use_decimal(self) -> None:
        assert PACK_CONFIG["vat_rates"]["ZA"]["standard"] == Decimal("0.15")

    def test_cidb_grades_cover_one_to_nine(self) -> None:
        grades = [g["grade"] for g in PACK_CONFIG["contractor_grading"]["grade_value_ceilings_zar_indicative"]]
        assert grades == list(range(1, 10))
