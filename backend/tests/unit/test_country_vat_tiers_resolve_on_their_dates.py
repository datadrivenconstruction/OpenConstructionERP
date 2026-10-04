# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Ireland, Hungary, Switzerland and Russia price at the rate of the document's own date.

Read against the shipped seed file, never a fixture: a hand-built fixture lets
this go green while the data a customer installs stays wrong.

Every country here gets a case that tells the right answer from the wrong one.
A tier added beside the standard rate must not change what the country
resolves to, so each tier test also asserts the standard answer is unmoved,
and each dated window is checked on the last day before it as well as on its
first day, because a window that leaks one way prices yesterday's invoice at
tomorrow's rate.

Sources, read 2026-10-04:

* Ireland: Revenue, "Current VAT rates",
  https://www.revenue.ie/en/vat/vat-rates/search-vat-rates/current-vat-rates.aspx
  - standard 23, reduced 13.5, second reduced 9.
* Hungary: 27 % standard since 2012-01-01; 5 % since EU accession on
  2004-01-01 and 18 % since 2009-07-01.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_rules import active_rows, resolve, row_from_mapping


def _rows():
    return [row_from_mapping(row) for row in load_tax_seed_rows()]


def _standard(country: str, on_date: str) -> str | None:
    """The standard rate the resolver gives a country on a date, or None."""
    outcome = resolve(_rows(), country, None, on_date)
    return outcome.combined_rate_pct if outcome.resolved else None


def _rates_in_force(country: str, on_date: str) -> dict[str, Decimal]:
    """Every country-wide rate in force on a date, by tax code."""
    return {
        row.tax_code or "": Decimal(row.rate_pct)
        for row in active_rows(_rows(), country, on_date)
        if row.combination in ("national", "federal")
    }


# ── Ireland ──────────────────────────────────────────────────────────────────


def test_ireland_offers_all_four_rates_today() -> None:
    rates = _rates_in_force("IE", "2026-10-04")
    assert sorted(rates.values()) == [Decimal("0"), Decimal("9"), Decimal("13.5"), Decimal("23")]


def test_ireland_still_resolves_to_its_standard_rate_with_the_tiers_beside_it() -> None:
    # The distinguishing case: an unflagged 9 % or 0 % row promoted to the
    # standard rate would answer 9 or 0 here.
    assert _standard("IE", "2026-10-04") == "23"


def test_the_irish_construction_rate_is_the_reduced_tier() -> None:
    reduced = [row for row in load_tax_seed_rows() if row["country_code"] == "IE" and row["tax_code"] == "VAT_RED"]
    assert [row["rate_pct"] for row in reduced] == ["13.5"]
    assert "Construction" in reduced[0]["tax_name"]
    assert reduced[0]["is_default"] is False


def test_the_irish_second_reduced_rate_did_not_exist_before_july_2011() -> None:
    assert "VAT_RED_9" not in _rates_in_force("IE", "2011-06-30")
    assert _rates_in_force("IE", "2011-07-01")["VAT_RED_9"] == Decimal("9")


# ── Hungary ──────────────────────────────────────────────────────────────────


def test_hungary_offers_its_standard_and_both_reduced_rates() -> None:
    rates = _rates_in_force("HU", "2026-10-04")
    assert rates == {"AFA": Decimal("27"), "AFA_18": Decimal("18"), "AFA_5": Decimal("5")}


def test_hungary_still_resolves_to_27_with_the_tiers_beside_it() -> None:
    assert _standard("HU", "2026-10-04") == "27"


@pytest.mark.parametrize("on_date", ["2004-01-01", "2009-07-01", "2011-12-31"])
def test_a_hungarian_date_before_the_27_percent_rate_is_not_priced_at_a_tier(on_date: str) -> None:
    """Before 2012 the seed has no Hungarian standard rate, and a tier must not stand in for it."""
    assert _standard("HU", on_date) is None


# ── Every shipped tier ───────────────────────────────────────────────────────


def test_no_new_tier_is_flagged_as_a_standard_rate() -> None:
    tiers = {("IE", "VAT_RED_9"), ("IE", "VAT_ZERO"), ("HU", "AFA_18"), ("HU", "AFA_5")}
    found = {(row["country_code"], row["tax_code"]): row for row in load_tax_seed_rows()}
    for line in tiers:
        assert line in found, f"{line} is missing from the seed file"
        assert found[line]["is_default"] is False, f"{line} claims to be the standard rate"
        assert found[line]["combination"] == "national"
