# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Croatia charges PDV at 25 %, and its 13, 5 and 0 % rates are on file beside it.

A Croatian main contractor had to type 25 % by hand on every line. The shipped
seed carried one Croatian row, the 25 % standard rate, dated a year late
(2013-03-01), and none of the three other rates Croatian law applies.

Sources, read 2026-09-25:

- 25 % standard rate from 2012-03-01, raised from 23 % by the amendment to the
  Zakon o PDV-u in force that day (RRiF, "Koje novosti donose izmjene i dopune
  Zakona o PDV-u od 1. ozujka 2012."; hr.wikipedia "Porez na dodanu vrijednost").
- 5 % from 2013-01-01, replacing the abolished 0 % rate on bread, milk, books
  and medicines (Novi list and tportal, 2013-01-01).
- 13 % from 2014-01-01, raised from the 10 % band (RRiF, "Nova stopa PDV-a od
  13% od 1. sijecnja 2014."). The 10 % band before it is not shipped.
- 0 % from 2022-10-01 on the supply and installation of solar panels on
  residential and public-interest buildings, article 38(6) as amended by
  NN 113/22 (Porezna uprava, "Stopa PDV-a od 0% na isporuku i ugradnju
  solarnih ploca"; PwC Worldwide Tax Summaries, Croatia).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_rules import active_rows, resolve, row_from_mapping, validate_tax_row
from app.modules.i18n_foundation.tax_seed_reconcile import LINE_FIRST_SHIPPED

TODAY = "2026-09-25"


def _rows() -> list:
    return [row_from_mapping(r) for r in load_tax_seed_rows()]


def _croatian(on_date: str) -> dict[str, str]:
    """Croatian rows in force on a date, tax code to rate."""
    return {r.tax_code: r.rate_pct for r in active_rows(_rows(), "HR", on_date)}


def test_a_croatian_project_resolves_to_pdv_25() -> None:
    resolution = resolve(_rows(), "HR", None, TODAY)

    assert resolution.status == "national", resolution.reason
    assert resolution.combined_rate_pct == "25"
    assert [c.tax_code for c in resolution.components] == ["PDV"]


def test_the_reduced_and_zero_rates_are_offered_beside_the_standard_one() -> None:
    assert _croatian(TODAY) == {"PDV": "25.0", "PDV_13": "13.0", "PDV_5": "5.0", "PDV_0": "0.0"}


def test_only_the_standard_rate_is_the_default() -> None:
    flagged = [r.tax_code for r in active_rows(_rows(), "HR", TODAY) if r.is_default]

    assert flagged == ["PDV"]


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        # 25 % had been in force for a year before the old seed date.
        ("2012-06-01", {"PDV": "25.0"}),
        ("2013-06-01", {"PDV": "25.0", "PDV_5": "5.0"}),
        ("2014-01-01", {"PDV": "25.0", "PDV_13": "13.0", "PDV_5": "5.0"}),
        ("2022-09-30", {"PDV": "25.0", "PDV_13": "13.0", "PDV_5": "5.0"}),
        ("2022-10-01", {"PDV": "25.0", "PDV_13": "13.0", "PDV_5": "5.0", "PDV_0": "0.0"}),
    ],
)
def test_each_rate_starts_on_the_day_the_law_says(on_date: str, expected: dict[str, str]) -> None:
    assert _croatian(on_date) == expected
    assert resolve(_rows(), "HR", None, on_date).combined_rate_pct == "25"


def test_every_croatian_row_is_named_pdv_in_croatian() -> None:
    croatian = [r for r in load_tax_seed_rows() if r["country_code"] == "HR"]

    assert len(croatian) == 4
    for row in croatian:
        assert row["tax_name_translations"]["hr"].startswith("PDV"), row
        assert "PDV" in row["tax_name"], row


def test_every_croatian_row_passes_the_write_rules() -> None:
    for row in load_tax_seed_rows():
        if row["country_code"] == "HR":
            validate_tax_row(row["country_code"], row["combination"], row["subdivision_code"], rate_pct=row["rate_pct"])


def test_the_new_rates_reach_an_install_seeded_before_them() -> None:
    """A line not in the reconciler's table is never delivered to an old install."""
    for code in ("PDV_13", "PDV_5", "PDV_0"):
        assert ("HR", code) in LINE_FIRST_SHIPPED


def test_croatia_prices_in_euro() -> None:
    countries = json.loads(
        (Path(__file__).resolve().parents[3] / "app/modules/i18n_foundation/seed_data/countries.json").read_text(
            encoding="utf-8"
        )
    )

    assert next(c for c in countries if c["iso_code"] == "HR")["currency_default"] == "EUR"
