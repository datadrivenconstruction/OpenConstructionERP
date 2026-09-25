"""A country priced on the neutral stack still gets its own VAT line.

Croatia, Bulgaria and Mexico have no regional markup stack, so their bills are
seeded with ``DEFAULT``, which carries no tax line. The tax seed knows each of
their rates and the bill resolved them, but there was no tax line to put the
rate on, so the bill showed no VAT at all. :func:`resolve_region_lines` now
appends one line named after the country's seeded tax when it is told the
country, and only then.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.modules.boq.markup_templates import (
    _TAX_SEED_PATH,
    DEFAULT_MARKUP_TEMPLATES,
    REGION_BY_COUNTRY,
    region_key_for_country,
    region_lines_for_country,
    resolve_region_lines,
    seeded_tax_line_names,
)


def _tax_lines(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    return [line for line in lines if line.get("category") == "tax"]


@pytest.mark.parametrize(
    ("country", "rate", "name"),
    [("HR", "25", "PDV"), ("BG", "20", "DDS"), ("MX", "16", "IVA")],
)
def test_a_country_on_the_neutral_stack_gets_one_line_of_its_own_tax(country: str, rate: str, name: str) -> None:
    assert country not in REGION_BY_COUNTRY
    region = region_key_for_country(country)

    lines = resolve_region_lines(region, vat_rate=rate, country_code=country)

    taxes = _tax_lines(lines)
    assert len(taxes) == 1
    assert taxes[0]["name"] == name
    assert taxes[0]["percentage"] == rate
    assert taxes[0]["apply_to"] == "cumulative"
    assert taxes[0]["vat_override"] is True
    # The stack's own lines are untouched and the tax line comes last.
    assert [line["name"] for line in lines[:-1]] == [line["name"] for line in DEFAULT_MARKUP_TEMPLATES["DEFAULT"]]
    assert lines[-1] is taxes[0]
    assert int(str(taxes[0]["sort_order"])) > max(int(str(line["sort_order"])) for line in lines[:-1])


@pytest.mark.parametrize("country", ["US", "CA"])
def test_a_sales_tax_country_gets_no_line(country: str) -> None:
    """Sales tax is levied per state or province, so no one line describes it."""
    region = region_key_for_country(country)

    lines = resolve_region_lines(region, vat_rate="5", country_code=country)

    assert _tax_lines(lines) == _tax_lines(resolve_region_lines(region, vat_rate="5"))
    assert country not in seeded_tax_line_names()


def test_a_zero_rate_country_gets_no_line() -> None:
    lines = resolve_region_lines("DEFAULT", vat_rate="0", country_code="HK")

    assert _tax_lines(lines) == []
    assert "HK" not in seeded_tax_line_names()


def test_no_rate_and_no_country_add_nothing() -> None:
    assert _tax_lines(resolve_region_lines("DEFAULT", vat_rate=None, country_code="HR")) == []
    assert _tax_lines(resolve_region_lines("DEFAULT", vat_rate="0", country_code="HR")) == []
    assert _tax_lines(resolve_region_lines("DEFAULT", vat_rate="25")) == []


def test_a_stack_that_already_has_a_tax_line_is_not_given_a_second() -> None:
    """Idempotence: a stack with a tax line only has its rate swapped."""
    lines = resolve_region_lines("CZ", vat_rate="25", country_code="HR")

    taxes = _tax_lines(lines)
    assert len(taxes) == 1
    assert taxes[0]["name"] == "DPH"


def test_applying_twice_gives_the_same_single_line() -> None:
    first = resolve_region_lines("DEFAULT", vat_rate="25", country_code="HR")
    second = resolve_region_lines("DEFAULT", vat_rate="25", country_code="HR")

    assert first == second
    assert len(_tax_lines(second)) == 1


def test_the_methodology_side_never_sees_the_appended_line() -> None:
    """The catalogue derives templates only for mapped countries and passes no country."""
    assert region_lines_for_country("HR", vat_rate="25") is None
    for country, region in REGION_BY_COUNTRY.items():
        lines = region_lines_for_country(country, vat_rate="18")
        assert lines is not None
        assert len(_tax_lines(lines)) == len(_tax_lines(DEFAULT_MARKUP_TEMPLATES[region])), country


def test_the_name_map_is_what_the_seed_says() -> None:
    """The map is computed from the seed, so it must equal an independent reading of it."""
    rows = json.loads(_TAX_SEED_PATH.read_text(encoding="utf-8"))
    latest: dict[str, dict[str, object]] = {}
    for row in sorted(rows, key=lambda r: str(r.get("effective_from") or "")):
        if row.get("is_default"):
            latest[str(row["country_code"])] = row
    expected = {
        country: str(row["tax_code"])
        for country, row in latest.items()
        if row["combination"] == "national" and row["tax_type"] in ("vat", "gst") and Decimal(str(row["rate_pct"])) > 0
    }

    assert seeded_tax_line_names() == expected
    assert seeded_tax_line_names()["HR"] == "PDV"
