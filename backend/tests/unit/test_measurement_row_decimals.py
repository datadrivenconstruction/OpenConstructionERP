# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A sheet that rounds every line before totalling it.

Italian practice, and the files that come out of it, round each partial
quantity of a measurement sheet to the decimals the bill declares and then
add the rounded partials. Rounding only the total gives a different number:
ten lines of 1.005 total 10.05, while ten partials rounded to 1.01 total
10.10, which is the quantity the file declares. The sheet carries the rule
(``row_decimals``) instead of the rounded figures, so every line keeps its
formula and its dimensions and the total is still the file's own.
"""

from decimal import Decimal

import pytest

from app.modules.measurement import build_sheet, reconcile, render_csv, render_markdown


def _lines(*formulas: str, sign: str = "+") -> list[dict]:
    return [{"description": f"line {n}", "formula": f, "sign": sign} for n, f in enumerate(formulas, start=1)]


def test_each_line_is_rounded_before_the_lines_are_added() -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=_lines(*["1.005"] * 10), row_decimals=2)
    assert sheet.total_quantity == Decimal("10.10")


def test_a_rounded_line_keeps_its_formula_and_shows_its_rounded_value() -> None:
    sheet = build_sheet(
        item_ref="1",
        description="d",
        unit="m2",
        lines=[{"description": "a third", "formula": "L / H", "variables": {"L": "10", "H": "3"}}],
        row_decimals=2,
    )
    line = sheet.to_dict()["lines"][0]
    assert Decimal(line["quantity"]) == Decimal("3.33")
    assert line["formula"] == "L / H"
    assert line["variables"] == {"L": "10", "H": "3"}
    assert sheet.total_quantity == Decimal("3.33")


def test_a_deducted_line_rounds_away_from_zero_like_an_added_one() -> None:
    lines = _lines("2.005") + _lines("1.005", sign="-")
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=lines, row_decimals=2)
    assert [Decimal(ln["quantity"]) for ln in sheet.to_dict()["lines"]] == [Decimal("2.01"), Decimal("-1.01")]
    assert sheet.total_quantity == Decimal("1.00")


def test_the_factor_is_applied_before_the_line_is_rounded() -> None:
    sheet = build_sheet(
        item_ref="1",
        description="d",
        unit="m2",
        lines=[{"description": "x", "formula": "0.3333", "factor": "3"}],
        row_decimals=2,
    )
    # 3 x 0.3333 = 0.9999, rounded as a line to 1.00 (not 3 x 0.33 = 0.99).
    assert sheet.total_quantity == Decimal("1.00")


def test_without_the_rule_the_sheet_totals_exactly_as_before() -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=_lines(*["1.005"] * 10))
    assert sheet.total_quantity == Decimal("10.050")
    assert sheet.to_dict()["row_decimals"] is None


def test_the_reconcile_compares_the_rounded_total() -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=_lines(*["1.005"] * 10), row_decimals=2)
    assert reconcile(sheet, "10.10")["matches"] is True
    assert reconcile(sheet, "10.05")["matches"] is False


def test_the_sheet_reports_its_rule() -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=_lines("1"), row_decimals=3)
    assert sheet.to_dict()["row_decimals"] == 3


@pytest.mark.parametrize("bad", [7, -1, True, "x", 2.5, None, ""])
def test_a_rule_outside_zero_to_six_decimals_is_ignored(bad: object) -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=_lines(*["1.005"] * 10), row_decimals=bad)
    assert sheet.row_decimals is None
    assert sheet.total_quantity == Decimal("10.050")


def test_a_rule_written_as_digits_is_read() -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=_lines(*["1.005"] * 10), row_decimals="2")
    assert sheet.row_decimals == 2


def test_the_written_sheets_show_the_rounded_lines_and_total() -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=_lines(*["1.005"] * 10), row_decimals=2)
    csv = render_csv(sheet)
    assert ",1.010," in csv
    assert ",10.100," in csv
    markdown = render_markdown(sheet)
    assert "| 1.010 |" in markdown
    assert "Total quantity: 10.100 m2" in markdown
