"""A quantity or rate cell holding text is a row error, unless the text is a bill placeholder.

"PM", "Inclus" or "-" in a price column is how bills mark a line priced elsewhere: the line
imports at 0 with a warning. "abc" or "12x" is a typo, and importing it as 0 would hide it
inside a total nobody checks, so the row is reported and skipped.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.modules.boq.importers._encoding import is_price_placeholder, parse_numeric_cell
from app.modules.boq.importers.excel import ExcelImporter
from app.modules.boq.router import _prepare_rows


@pytest.mark.parametrize("value", ["PM", "pm", "P.M.", "Inclus", "incl.", "-", "--", "  ", "n/a", "TBD", "включено"])
def test_bill_placeholders_are_recognised(value: str) -> None:
    assert is_price_placeholder(value)


@pytest.mark.parametrize("value", ["abc", "12x", "1O0", "ten"])
def test_text_that_is_not_a_placeholder_is_malformed(value: str) -> None:
    assert not is_price_placeholder(value)


@pytest.mark.parametrize("value", ["1O0", "12-15", "5 x 3"])
def test_a_number_that_would_lose_digits_is_rejected(value: str) -> None:
    assert parse_numeric_cell(value)[0] is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("12 m3", 12.0), ("12 m²", 12.0), ("12,50 €/m2", 12.5), ("150 EUR", 150.0), ("1.234,56", 1234.56)],
)
def test_a_unit_or_currency_after_the_number_is_still_read(value: str, expected: float) -> None:
    assert parse_numeric_cell(value) == (expected, None)


def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


async def test_the_importer_reports_a_malformed_rate_and_keeps_the_other_rows() -> None:
    result = await ExcelImporter.parse(
        _csv(
            [
                ["1", "Concrete C30/37", "m3", "10", "150"],
                ["2", "Formwork", "m2", "40", "1O0"],
                ["3", "Reinforcement", "kg", "1200", "1.85"],
            ]
        )
    )
    assert [p.description for p in result.positions] == ["Concrete C30/37", "Reinforcement"]
    assert len(result.errors) == 1
    assert result.errors[0]["column"] == "unit_rate"
    assert result.errors[0]["ordinal"] == "2"


async def test_the_importer_keeps_a_placeholder_line_at_zero() -> None:
    result = await ExcelImporter.parse(_csv([["1", "Site setup", "lsum", "1", "PM"]]))
    assert result.errors == []
    assert len(result.positions) == 1
    assert result.positions[0].unit_rate == 0


async def test_a_malformed_quantity_is_named_as_the_quantity() -> None:
    result = await ExcelImporter.parse(_csv([["1", "Excavation", "m3", "abc", "8"]]))
    assert result.positions == []
    assert [e["column"] for e in result.errors] == ["quantity"]


def _row(quantity: str, unit_rate: str) -> dict[str, str]:
    return {"ordinal": "1", "description": "Excavation", "unit": "m3", "quantity": quantity, "unit_rate": unit_rate}


def test_the_round_trip_route_reports_the_same_row_error() -> None:
    prepared, errors, *_ = _prepare_rows([_row("abc", "8")], {}, "bill.xlsx")
    assert prepared == []
    assert [e["column"] for e in errors] == ["quantity"]
    assert errors[0]["data"]["quantity"] == "abc"


def test_the_round_trip_route_keeps_a_placeholder_line() -> None:
    prepared, errors, *_ = _prepare_rows([_row("1", "Inclus")], {}, "bill.xlsx")
    assert errors == []
    assert len(prepared) == 1
