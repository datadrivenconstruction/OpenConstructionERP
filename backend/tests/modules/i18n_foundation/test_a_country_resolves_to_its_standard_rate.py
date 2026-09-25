# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A country with rate tiers resolves to the standard rate, not to their sum.

The bug this file convicts
--------------------------
``resolve`` used to add up every country-wide row in force. For a country with
one rate that is right by coincidence, and every fixture in this suite carried
one rate per country, so the whole suite passed. On the shipped seed file,
which is what a customer actually gets, it produced:

    Germany 26 (19 + 7), United Kingdom 25 (20 + 5 + 0),
    France 35.5 (20 + 10 + 5.5), Italy 32 (22 + 10), Poland 31 (23 + 8)

Rate tiers are alternatives - a supply is charged at one of them - so adding
them is not a rounding disagreement, it is a category error, and it reached
``GET /tax-configs/resolve/{country}``. It surfaced while adding Romania's
11 % reduced band, which would have turned a correct RO 21 into RO 32.

Why the figures are asserted as money and not as rates
------------------------------------------------------
A rate that round-trips through a field is not evidence anybody can price
with. Each case below multiplies a real net amount by the resolved rate and
asserts the tax and the gross, rounded the way the BOQ and invoice paths round
them - two decimals, HALF_UP.

Sources for the rates
---------------------
The non-Romanian figures are the standard rates the seed file already carried
and that this suite already relied on; nothing about them changes here, only
the arithmetic over them. Romania's 21 % standard and 11 % reduced band, both
from 1 August 2025, are cited on ``ROMANIA_VAT_SOURCES`` in
``app/modules/i18n_foundation/romania_vat.py``.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from app.modules.i18n_foundation.tax_rules import resolve, row_from_mapping

_SEED = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "i18n_foundation"
    / "seed_data"
    / "tax_configurations.json"
)

#: A date inside every current rate's window, and after the Romanian reform.
TODAY = "2026-08-26"

#: A round net amount, big enough that a wrong rate shows up as a difference a
#: client would query rather than as a rounding crumb.
NET = Decimal("100000.00")


def _rows() -> list:
    return [row_from_mapping(r) for r in json.loads(_SEED.read_text(encoding="utf-8"))]


def _money(value: Decimal) -> Decimal:
    """Round to cents the way the BOQ and invoice paths do."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _tax_on(net: Decimal, rate_pct: str) -> tuple[Decimal, Decimal]:
    """Tax and gross for ``net`` at ``rate_pct``, as an invoice would carry them."""
    tax = _money(net * Decimal(rate_pct) / Decimal("100"))
    return tax, _money(net + tax)


# ── Every multi-tier country in the shipped file ─────────────────────────────

#: (country, standard rate, tax on NET, gross). The rate is the published
#: standard rate; the sum the resolver used to return is in the docstring
#: above and is deliberately not written here, because this table is what the
#: answer should be, not a record of what it was.
_STANDARD_RATE = (
    ("DE", "19", Decimal("19000.00"), Decimal("119000.00")),
    ("GB", "20", Decimal("20000.00"), Decimal("120000.00")),
    ("FR", "20", Decimal("20000.00"), Decimal("120000.00")),
    ("IT", "22", Decimal("22000.00"), Decimal("122000.00")),
    ("PL", "23", Decimal("23000.00"), Decimal("123000.00")),
    ("RO", "21", Decimal("21000.00"), Decimal("121000.00")),
    ("HR", "25", Decimal("25000.00"), Decimal("125000.00")),
)


@pytest.mark.parametrize(("country", "rate", "tax", "gross"), _STANDARD_RATE)
def test_a_country_with_reduced_tiers_prices_at_its_standard_rate(
    country: str,
    rate: str,
    tax: Decimal,
    gross: Decimal,
) -> None:
    """The resolved rate priced against a real net, not compared as a field."""
    resolution = resolve(_rows(), country, None, TODAY)

    assert resolution.resolved, f"{country}: {resolution.status} - {resolution.reason}"
    assert resolution.status == "national"
    assert resolution.combined_rate_pct == rate
    assert _tax_on(NET, resolution.combined_rate_pct) == (tax, gross)


@pytest.mark.parametrize(("country", "rate", "tax", "gross"), _STANDARD_RATE)
def test_the_components_add_up_to_what_was_charged(
    country: str,
    rate: str,
    tax: Decimal,
    gross: Decimal,
) -> None:
    """One component, and it is the rate that was charged.

    ``RateComponent`` promises the components sum to the total. Summing tiers
    kept that promise while making the total wrong, so the promise alone is
    not the check - the count is. A country-wide answer is one rate.
    """
    resolution = resolve(_rows(), country, None, TODAY)

    assert [c.effective_rate_pct for c in resolution.components] == [rate]


# ── Romania, the two bands and the negative control ──────────────────────────


def test_romania_carries_the_reduced_band_alongside_the_standard_rate() -> None:
    """11 % is on file and priceable, and it is not what the country resolves to.

    Both halves matter. A reduced band nobody can find is not shipped, and a
    reduced band the resolver hands out as the country rate would put 11 % on
    every Romanian invoice.
    """
    rows = [r for r in _rows() if r.country_code == "RO"]

    reduced = [r for r in rows if r.tax_code == "TVA_RED" and r.effective_to is None]

    assert [r.rate_pct for r in reduced] == ["11.0"]
    assert _tax_on(NET, reduced[0].rate_pct) == (Decimal("11000.00"), Decimal("111000.00"))
    assert not reduced[0].is_default
    assert resolve(_rows(), "RO", None, TODAY).combined_rate_pct == "21"


@pytest.mark.parametrize(
    ("on_date", "rate", "tax", "gross"),
    [
        ("2025-07-31", "19", Decimal("19000.00"), Decimal("119000.00")),
        ("2025-08-01", "21", Decimal("21000.00"), Decimal("121000.00")),
    ],
)
def test_the_romanian_reform_takes_effect_on_the_first_of_august(
    on_date: str,
    rate: str,
    tax: Decimal,
    gross: Decimal,
) -> None:
    """The negative control: a document at the old rate still computes at it.

    This is the assertion that says the change is a rate *addition* and not a
    rate *rewrite*. If somebody ever heals Romania by editing the 19 % row to
    say 21, the first case here fails - which is the only automatic warning
    that every estimate and invoice issued before August 2025 just changed
    value.
    """
    resolution = resolve(_rows(), "RO", None, on_date)

    assert resolution.combined_rate_pct == rate
    assert _tax_on(NET, resolution.combined_rate_pct) == (tax, gross)


# ── The refusal, when the data cannot say which rate is standard ─────────────


def test_two_rates_and_no_default_returns_no_rate_at_all() -> None:
    """Ambiguity is answered as a question nobody answered, not as a guess.

    Either candidate is a real percentage, which is exactly why picking one
    would be the dangerous kind of wrong - a plausible figure on an invoice
    with nothing to mark it as unverified.
    """
    rows = [
        row_from_mapping(
            {
                "country_code": "ZZ",
                "tax_code": code,
                "tax_name": code,
                "rate_pct": rate,
                "tax_type": "vat",
                "combination": "national",
                "effective_from": "2020-01-01",
                "is_default": False,
            }
        )
        for code, rate in (("VAT", "20.0"), ("VAT_RED", "5.0"))
    ]

    resolution = resolve(rows, "ZZ", None, TODAY)

    assert resolution.status == "default_rate_ambiguous"
    assert resolution.combined_rate_pct is None
    assert not resolution.resolved


def test_a_lone_unflagged_rate_is_still_that_country_s_rate() -> None:
    """One row needs no flag to be the answer; fixtures older than the flag work."""
    rows = [
        row_from_mapping(
            {
                "country_code": "ZZ",
                "tax_code": "VAT",
                "tax_name": "VAT",
                "rate_pct": "17.5",
                "tax_type": "vat",
                "combination": "national",
                "effective_from": "2020-01-01",
                "is_default": False,
            }
        )
    ]

    resolution = resolve(rows, "ZZ", None, TODAY)

    assert (resolution.status, resolution.combined_rate_pct) == ("national", "17.5")


def test_every_country_in_the_shipped_file_still_answers() -> None:
    """No country loses its rate to the new refusal.

    The fix introduces a status that returns no number. This is the check that
    it never fires on the data we ship - if a future rate edit leaves a country
    with two unflagged tiers, this names it rather than letting the endpoint
    start returning nulls in the field.
    """
    rows = _rows()
    countries = sorted({r.country_code for r in rows})

    statuses = {country: resolve(rows, country, None, TODAY).status for country in countries}
    unanswerable = {c: s for c, s in statuses.items() if s == "default_rate_ambiguous"}

    assert unanswerable == {}
