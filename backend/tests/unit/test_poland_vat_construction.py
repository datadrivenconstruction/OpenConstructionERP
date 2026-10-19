"""Polish VAT rules for construction invoices: split payment, housing rate limits, reverse charge.

Each case differs from its neighbour in exactly the input the rule turns on:
the gross amount either side of PLN 15,000, the date either side of
1 November 2019, the usable area either side of the 150 and 300 m2 limits.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal

import pytest

from app.core import vat_construction as vc


class TestSplitPayment:
    def test_an_annex_15_invoice_above_fifteen_thousand_requires_split_payment(self) -> None:
        d = vc.split_payment_decision("PL", date(2026, 3, 2), Decimal("15000.01"), "PLN", annex_15=True)
        assert d is not None
        assert d.required is True
        assert d.reason == "required"
        assert d.einvoice_field == "P_18A"
        assert d.annotation == "mechanizm podzielonej płatności"

    def test_exactly_fifteen_thousand_does_not_exceed_the_threshold(self) -> None:
        d = vc.split_payment_decision("PL", date(2026, 3, 2), Decimal("15000.00"), "PLN", annex_15=True)
        assert d is not None
        assert d.required is False
        assert d.reason == "below_threshold"

    def test_an_invoice_outside_annex_15_is_not_caught_whatever_its_amount(self) -> None:
        d = vc.split_payment_decision("PL", date(2026, 3, 2), Decimal("900000"), "PLN", annex_15=False)
        assert d is not None
        assert d.required is False
        assert d.reason == "not_annex_15"

    def test_one_construction_line_on_a_mixed_invoice_is_enough(self) -> None:
        # 43.21 electrical installation work is in section 43; 46.73 wholesale
        # of timber is not. The threshold is the whole invoice.
        assert vc.annex_15_from_codes("PL", ["46.73.11", "43.21.10"]) is True
        assert vc.annex_15_from_codes("PL", ["46.73.11"]) is False
        assert vc.annex_15_from_codes("PL", []) is None

    def test_a_prefix_match_is_on_the_section_not_on_any_leading_digits(self) -> None:
        # "4" alone or "410" without the dot would match "41" by string prefix.
        assert vc.annex_15_from_codes("PL", ["4"]) is False
        assert vc.annex_15_from_codes("PL", ["41"]) is True
        assert vc.annex_15_from_codes("PL", ["41.00.30.0"]) is True
        assert vc.annex_15_from_codes("PL", ["14.13"]) is False

    def test_an_unknown_annex_status_is_undecided_not_cleared(self) -> None:
        d = vc.split_payment_decision("PL", date(2026, 3, 2), Decimal("20000"), "PLN", annex_15=None)
        assert d is not None
        assert d.required is None
        assert d.reason == "annex_15_unknown"

    def test_an_amount_in_another_currency_is_undecided(self) -> None:
        d = vc.split_payment_decision("PL", date(2026, 3, 2), Decimal("20000"), "EUR", annex_15=True)
        assert d is not None
        assert d.required is None
        assert d.reason == "other_currency"

    def test_before_the_mandatory_regime_nothing_is_required(self) -> None:
        d = vc.split_payment_decision("PL", date(2019, 10, 31), Decimal("20000"), "PLN", annex_15=True)
        assert d is not None
        assert d.required is False
        assert d.reason == "not_in_force"
        on_the_day = vc.split_payment_decision("PL", date(2019, 11, 1), Decimal("20000"), "PLN", annex_15=True)
        assert on_the_day is not None
        assert on_the_day.required is True

    def test_a_country_without_the_regime_has_no_decision(self) -> None:
        assert vc.split_payment_decision("DE", date(2026, 3, 2), Decimal("20000"), "EUR", annex_15=True) is None

    def test_the_sanction_is_thirty_percent_of_the_vat(self) -> None:
        assert vc.split_payment_sanction("PL", Decimal("4600.00")) == Decimal("1380.00")
        assert vc.split_payment_sanction("DE", Decimal("4600.00")) is None


class TestDomesticReverseCharge:
    def test_domestic_construction_reverse_charge_ended_on_1_november_2019(self) -> None:
        assert vc.domestic_reverse_charge_allowed("PL", date(2019, 10, 31)) is True
        assert vc.domestic_reverse_charge_allowed("PL", date(2019, 11, 1)) is False

    def test_a_country_without_a_row_is_not_judged(self) -> None:
        assert vc.domestic_reverse_charge_allowed("DE", date(2026, 1, 1)) is None


class TestHousingRate:
    def test_a_flat_within_the_limit_is_all_reduced_rate(self) -> None:
        split = vc.reduced_rate_split("PL", "flat", Decimal("120"), Decimal("120000"), date(2026, 3, 2))
        assert split is not None
        assert [(p.tax_code, p.rate_percent, p.base) for p in split.parts] == [
            ("VAT_RED", Decimal("8.0"), Decimal("120000.00")),
        ]

    def test_a_180_m2_flat_is_split_150_to_30(self) -> None:
        # The research worked example: 8 % on 150/180 and 23 % on 30/180.
        #   180000 x 150/180 = 150000.00 at 8 %  -> VAT 12000.00
        #   180000 x  30/180 =  30000.00 at 23 % -> VAT  6900.00
        split = vc.reduced_rate_split("PL", "flat", Decimal("180"), Decimal("180000"), date(2026, 3, 2))
        assert split is not None
        assert split.limit_m2 == Decimal("150")
        assert [(p.tax_code, p.rate_percent, p.base, p.vat) for p in split.parts] == [
            ("VAT_RED", Decimal("8.0"), Decimal("150000.00"), Decimal("12000.00")),
            ("VAT", Decimal("23.0"), Decimal("30000.00"), Decimal("6900.00")),
        ]

    def test_the_same_area_is_within_the_limit_for_a_house(self) -> None:
        # 180 m2 is above the flat limit and below the 300 m2 house limit.
        split = vc.reduced_rate_split("PL", "residential_building", Decimal("180"), Decimal("180000"), date(2026, 3, 2))
        assert split is not None
        assert [p.tax_code for p in split.parts] == ["VAT_RED"]

    def test_a_house_above_300_m2_is_split(self) -> None:
        split = vc.reduced_rate_split(
            "PL", "residential_building", Decimal("400"), Decimal("1000000"), date(2026, 3, 2)
        )
        assert split is not None
        assert [(p.tax_code, p.base) for p in split.parts] == [
            ("VAT_RED", Decimal("750000.00")),
            ("VAT", Decimal("250000.00")),
        ]

    def test_the_parts_always_add_up_to_the_price(self) -> None:
        split = vc.reduced_rate_split("PL", "flat", Decimal("151.37"), Decimal("123456.79"), date(2026, 3, 2))
        assert split is not None
        assert sum(p.base for p in split.parts) == Decimal("123456.79")

    def test_commercial_premises_get_the_standard_rate_on_all_of_it(self) -> None:
        split = vc.reduced_rate_split("PL", "commercial_premises", Decimal("80"), Decimal("50000"), date(2026, 3, 2))
        assert split is not None
        assert split.eligible is False
        assert [(p.tax_code, p.rate_percent, p.base) for p in split.parts] == [
            ("VAT", Decimal("23.0"), Decimal("50000.00")),
        ]

    def test_an_unknown_object_kind_is_refused(self) -> None:
        with pytest.raises(ValueError):
            vc.reduced_rate_split("PL", "garage", Decimal("20"), Decimal("1000"), date(2026, 3, 2))

    def test_a_country_without_the_rule_has_no_split(self) -> None:
        assert vc.reduced_rate_split("DE", "flat", Decimal("180"), Decimal("1000"), date(2026, 3, 2)) is None

    def test_the_rates_come_from_the_dated_tax_seed(self) -> None:
        seed = vc.seed_rate_percent("PL", "VAT_RED", date(2026, 3, 2))
        assert seed == Decimal("8.0")
        assert vc.seed_rate_percent("PL", "VAT", date(2026, 3, 2)) == Decimal("23.0")
        assert vc.seed_rate_percent("PL", "VAT", date(2010, 12, 31)) is None


class TestHousingFindings:
    def test_the_whole_price_at_the_reduced_rate_above_the_limit_is_a_finding(self) -> None:
        found = vc.housing_rate_findings("PL", "flat", Decimal("180"), Decimal("8"), date(2026, 3, 2))
        assert [f.key for f in found] == ["reduced_rate_above_area_limit"]
        assert found[0].params["limit_m2"] == "150"
        assert found[0].params["reduced_share_percent"] == "83.33"

    def test_the_reduced_rate_within_the_limit_is_silent(self) -> None:
        assert vc.housing_rate_findings("PL", "flat", Decimal("150"), Decimal("8"), date(2026, 3, 2)) == []

    def test_the_reduced_rate_on_commercial_premises_is_a_finding(self) -> None:
        found = vc.housing_rate_findings("PL", "commercial_premises", Decimal("50"), Decimal("8"), date(2026, 3, 2))
        assert [f.key for f in found] == ["reduced_rate_not_eligible"]

    def test_the_reduced_rate_without_a_recorded_object_is_a_finding(self) -> None:
        found = vc.housing_rate_findings("PL", None, None, Decimal("8"), date(2026, 3, 2))
        assert [f.key for f in found] == ["reduced_rate_object_unknown"]

    def test_the_standard_rate_is_never_questioned(self) -> None:
        assert vc.housing_rate_findings("PL", "flat", Decimal("400"), Decimal("23"), date(2026, 3, 2)) == []
        assert vc.housing_rate_findings("PL", None, None, Decimal("23"), date(2026, 3, 2)) == []


class TestData:
    def test_the_shipped_rows_validate(self) -> None:
        assert vc.validate_rows() == []

    def test_a_row_without_a_source_is_refused(self) -> None:
        data = json.loads(vc.DATA_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(data)
        broken["countries"]["PL"]["split_payment"]["sources"] = []
        assert any("sources" in p for p in vc.validate_rows(broken))

    def test_a_tax_code_missing_from_the_seed_is_refused(self) -> None:
        data = json.loads(vc.DATA_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(data)
        broken["countries"]["PL"]["reduced_rate_area_limits"]["within_tax_code"] = "VAT_8"
        assert any("VAT_8" in p for p in vc.validate_rows(broken))
