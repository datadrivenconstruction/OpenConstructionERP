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
* Ireland's temporary 21 % rate, 2020-09-01 to 2021-02-28: Chartered
  Accountants Ireland, TaxSource, "VAT Matters", September 2020.
* Hungary: 27 % standard since 2012-01-01; 5 % since EU accession on
  2004-01-01 and 18 % since 2009-07-01.
* Switzerland: ESTV, "Erhoehung der MWST-Steuersaetze 2024" - 7.7, 2.5 and
  3.7 % from 2018-01-01 to 2023-12-31, then 8.1, 2.6 and 3.8 %.
* Russia: Federal Tax Service, "Taxes 2026", https://www.nalog.gov.ru/new2026/
  - 20 % to 22 % from 2026-01-01.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.markup_templates import CONSTRUCTION_TIER_COUNTRIES, CONSTRUCTION_TIER_TAX_CODE
from app.modules.boq.service import _construction_tier_rate
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


def test_every_construction_tier_country_names_the_row_its_bill_is_priced_from() -> None:
    """The two maps carry one set of countries, and each named row ships."""
    assert set(CONSTRUCTION_TIER_COUNTRIES) == set(CONSTRUCTION_TIER_TAX_CODE)
    shipped = {(row["country_code"], row["tax_code"]) for row in load_tax_seed_rows()}
    for country, tax_code in CONSTRUCTION_TIER_TAX_CODE.items():
        assert (country, tax_code) in shipped, f"{country}'s tier row {tax_code} is not in the seed"


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        # The day that tells every wrong answer apart: the standard rate was 21
        # then, the UK stack carries 20 and today's standard rate is 23.
        ("2020-10-01", "13.5"),
        ("2026-10-04", "13.5"),
        ("2011-12-31", "13.5"),
        # The tier row opens on 2003-01-01; before it the bill has no tier on
        # file and the caller falls back, rather than being handed 23.
        ("2002-12-31", None),
    ],
)
def test_an_irish_bill_reads_the_construction_tier(on_date: str, expected: str | None) -> None:
    assert _construction_tier_rate(_rows(), "IE", "VAT_RED", on_date, uuid.uuid4()) == expected


def test_china_reads_its_nine_percent_tier_not_its_headline_rate() -> None:
    assert _standard("CN", "2026-10-04") == "13"
    assert _construction_tier_rate(_rows(), "CN", "VAT_RED", "2026-10-04", uuid.uuid4()) == "9"


def test_two_tier_rows_in_force_are_refused_rather_than_picked(caplog: pytest.LogCaptureFixture) -> None:
    """A second VAT_RED row in one window leaves nothing to choose by, so nothing is chosen."""
    rows = [*_rows(), row_from_mapping({**_irish_tier_row(), "rate_pct": "12.5"})]
    with caplog.at_level("WARNING", logger="app.modules.boq.service"):
        assert _construction_tier_rate(rows, "IE", "VAT_RED", "2026-10-04", uuid.uuid4()) is None
    assert any("VAT_RED" in record.getMessage() for record in caplog.records)


def test_a_tier_row_that_is_not_a_number_is_refused_loudly(caplog: pytest.LogCaptureFixture) -> None:
    rows = [row for row in _rows() if not (row.country_code == "IE" and row.tax_code == "VAT_RED")]
    rows.append(row_from_mapping({**_irish_tier_row(), "rate_pct": "thirteen and a half"}))
    with caplog.at_level("WARNING", logger="app.modules.boq.service"):
        assert _construction_tier_rate(rows, "IE", "VAT_RED", "2026-10-04", uuid.uuid4()) is None
    assert any("thirteen and a half" in record.getMessage() for record in caplog.records)


def _irish_tier_row() -> dict:
    return next(row for row in load_tax_seed_rows() if row["country_code"] == "IE" and row["tax_code"] == "VAT_RED")


def test_the_irish_second_reduced_rate_did_not_exist_before_july_2011() -> None:
    assert "VAT_RED_9" not in _rates_in_force("IE", "2011-06-30")
    assert _rates_in_force("IE", "2011-07-01")["VAT_RED_9"] == Decimal("9")


@pytest.mark.parametrize(
    ("on_date", "rate"),
    [
        ("2012-01-01", "23"),
        ("2020-08-31", "23"),
        ("2020-09-01", "21"),
        ("2021-02-28", "21"),
        ("2021-03-01", "23"),
        ("2026-10-04", "23"),
    ],
)
def test_ireland_charged_21_percent_for_half_a_year(on_date: str, rate: str) -> None:
    """Both edges of the temporary rate, so neither window can leak into the other."""
    assert _standard("IE", on_date) == rate


def test_an_irish_date_before_the_first_standard_window_gets_no_rate() -> None:
    """2011 was 21 % too, which the seed does not carry, so it must say nothing rather than 23 or 13.5."""
    assert _standard("IE", "2011-12-31") is None


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


# ── Switzerland ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("on_date", "rate"),
    [("2018-01-01", "7.7"), ("2023-12-31", "7.7"), ("2024-01-01", "8.1"), ("2026-10-04", "8.1")],
)
def test_switzerland_charges_the_rate_of_the_documents_own_year(on_date: str, rate: str) -> None:
    """The distinguishing case is 2023-12-31: an open 8.1 % window would answer 8.1 there."""
    assert _standard("CH", on_date) == rate


def test_a_swiss_date_before_2018_gets_no_rate_rather_than_a_later_one() -> None:
    assert _standard("CH", "2017-12-31") is None


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        ("2023-12-31", {"VAT": Decimal("7.7"), "VAT_REDUCED": Decimal("2.5"), "VAT_SPECIAL": Decimal("3.7")}),
        ("2024-01-01", {"VAT": Decimal("8.1"), "VAT_REDUCED": Decimal("2.6"), "VAT_SPECIAL": Decimal("3.8")}),
    ],
)
def test_the_swiss_tiers_move_on_the_same_day_as_the_standard_rate(on_date: str, expected: dict) -> None:
    assert _rates_in_force("CH", on_date) == expected


# ── Russia ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("on_date", "rate"), [("2025-12-31", "20"), ("2026-01-01", "22")])
def test_russia_charges_22_percent_only_from_2026(on_date: str, rate: str) -> None:
    assert _standard("RU", on_date) == rate


# ── No later rate on an earlier date, anywhere ───────────────────────────────


def _window_contains(row, on_date: str) -> bool:
    return (row.effective_from is None or row.effective_from <= on_date) and (
        row.effective_to is None or row.effective_to >= on_date
    )


def test_no_country_answers_a_date_with_a_standard_rate_that_was_not_in_force_on_it() -> None:
    """Swept over every country and every window boundary in the seed, the day before and the day of.

    Whatever the resolver answers for a country-wide date has to be the rate
    of a standard row whose own window contains that date. A rate from a
    window that starts later is exactly the defect of pricing yesterday's
    invoice at tomorrow's rate, and this is where it would show.
    """
    from datetime import date, timedelta

    rows = _rows()
    countries = sorted({row.country_code for row in rows})
    bounds = {row.effective_from for row in rows if row.effective_from} | {
        row.effective_to for row in rows if row.effective_to
    }
    dates = set()
    for bound in bounds:
        day = date.fromisoformat(bound)
        dates.update({(day - timedelta(days=1)).isoformat(), day.isoformat()})

    checked = 0
    for country in countries:
        for on_date in sorted(dates):
            outcome = resolve(rows, country, None, on_date)
            if outcome.status != "national":
                continue
            checked += 1
            in_force = {
                Decimal(row.rate_pct)
                for row in rows
                if row.country_code == country
                and row.combination in ("national", "federal")
                and _window_contains(row, on_date)
            }
            assert Decimal(outcome.combined_rate_pct) in in_force, (
                f"{country} on {on_date} answered {outcome.combined_rate_pct}, which no row in force that day carries"
            )
    # Not vacuous: the sweep has to have priced a real number of dates.
    assert checked > 500, checked


# ── Türkiye ──────────────────────────────────────────────────────────────────


def _turkish_seed_rows() -> dict[str, dict]:
    return {row["tax_code"]: row for row in load_tax_seed_rows() if row["country_code"] == "TR"}


def test_turkiye_offers_its_general_rate_and_both_reduced_lists() -> None:
    """The rates are read from the seed, not restated: this pins the set of lines."""
    seeded = _turkish_seed_rows()
    assert set(seeded) == {"KDV", "KDV_RED", "KDV_1"}
    assert _rates_in_force("TR", "2026-10-10") == {code: Decimal(row["rate_pct"]) for code, row in seeded.items()}


def test_turkiye_still_resolves_to_its_general_rate_with_the_list_one_tier_beside_it() -> None:
    general = _turkish_seed_rows()["KDV"]
    assert general["is_default"] is True
    assert Decimal(_standard("TR", "2026-10-10")) == Decimal(general["rate_pct"])


def test_the_turkish_tier_opens_with_the_general_rate_and_not_before_it() -> None:
    """A tier in force on a date the general rate is not would be all the resolver had."""
    seeded = _turkish_seed_rows()
    assert seeded["KDV_1"]["effective_from"] == seeded["KDV"]["effective_from"]
    assert "KDV_1" not in _rates_in_force("TR", "2023-07-09")
    assert _standard("TR", "2023-07-09") is None


# ── Every shipped tier ───────────────────────────────────────────────────────


def test_no_new_tier_is_flagged_as_a_standard_rate() -> None:
    tiers = {("IE", "VAT_RED_9"), ("IE", "VAT_ZERO"), ("HU", "AFA_18"), ("HU", "AFA_5"), ("TR", "KDV_1")}
    tiers.add(("ES", "IVA_SRED"))
    found = {(row["country_code"], row["tax_code"]): row for row in load_tax_seed_rows()}
    for line in tiers:
        assert line in found, f"{line} is missing from the seed file"
        assert found[line]["is_default"] is False, f"{line} claims to be the standard rate"
        assert found[line]["combination"] == "national"
