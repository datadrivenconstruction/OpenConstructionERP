# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A British or Irish project gets one consistent answer from every table that has an opinion.

Three tables say something about a new project in these two countries, and
none of them reads the others:

* ``COUNTRY_DEFAULTS`` - currency, paper, units, date order, number pattern.
* the classification registry - which measurement standard the bill is coded in.
* the dated tax seed - which VAT rate is in force today.

The VAT rate is deliberately NOT copied into ``COUNTRY_DEFAULTS``. An undated
second copy of a rate is how the platform came to state two Israeli rates at
once; the dated seed is the one source, and this test reads the rate from there.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.classification_registry import COUNTRY_TO_STANDARD, standard_for_country
from app.core.i18n_data import COUNTRY_DEFAULTS
from app.core.regional_format import ANGLO, format_date, number_style
from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_rules import resolve, row_from_mapping


@pytest.mark.parametrize(
    ("country", "currency", "vat"),
    [("GB", "GBP", "20"), ("IE", "EUR", "23")],
)
def test_the_country_defaults_are_the_british_and_irish_ones(country: str, currency: str, vat: str) -> None:
    defaults = COUNTRY_DEFAULTS[country]
    assert defaults["currency"] == currency
    assert defaults["measurement"] == "metric"
    assert defaults["paper"] == "A4"
    assert defaults["date_format"] == "DD/MM/YYYY", "both countries write the day first"
    assert number_style(country, currency) == ANGLO
    # Day first, the distinguishing case against the American order.
    assert format_date(date(2026, 10, 4), country) == "04/10/2026"

    outcome = resolve([row_from_mapping(r) for r in load_tax_seed_rows()], country, None, "2026-10-04")
    assert outcome.resolved and outcome.combined_rate_pct == vat


@pytest.mark.parametrize("country", ["GB", "IE"])
def test_both_are_measured_to_nrm(country: str) -> None:
    assert standard_for_country(country) == "nrm"
    assert COUNTRY_TO_STANDARD[country] == "nrm"


def test_the_vat_rate_is_not_duplicated_into_the_country_defaults() -> None:
    """The dated seed is the only home of a rate; a second undated copy drifts."""
    for country, defaults in COUNTRY_DEFAULTS.items():
        assert not any("vat" in key or "tax" in key for key in defaults), country
