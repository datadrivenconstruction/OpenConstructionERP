"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the measurement (quantity determination) library."""

from decimal import Decimal

import pytest

from app.modules.measurement import (
    MeasurementError,
    build_sheet,
    get_preset,
    list_variables,
    reconcile,
    render_csv,
    render_markdown,
    safe_eval,
)


# ---- formula evaluator -----------------------------------------------------
def test_safe_eval_arithmetic():
    assert safe_eval("3.5 * 2.4") == Decimal("8.40")
    assert safe_eval("2 * (3 + 4)") == Decimal("14")
    assert safe_eval("10 / 4") == Decimal("2.5")
    assert safe_eval("2 ** 3") == Decimal("8")


def test_safe_eval_variables_case_insensitive():
    assert safe_eval("L * B * H", {"L": "3.5", "B": 2.4, "H": Decimal("0.24")}) == Decimal("2.016")
    assert safe_eval("l * b", {"L": 2, "B": 3}) == Decimal("6")


def test_safe_eval_functions():
    assert safe_eval("max(3, 7, 5)") == Decimal("7")
    assert safe_eval("min(3, 7, 5)") == Decimal("3")
    assert safe_eval("abs(0 - 4)") == Decimal("4")
    assert safe_eval("sqrt(9)") == Decimal("3")
    assert safe_eval("round(2.345, 2)") == Decimal("2.35") or safe_eval("round(2.345, 2)") == Decimal("2.34")


def test_safe_eval_rejects_unsafe():
    with pytest.raises(MeasurementError):
        safe_eval("__import__('os').system('x')")
    with pytest.raises(MeasurementError):
        safe_eval("open('x')")
    with pytest.raises(MeasurementError):
        safe_eval("1 / 0")
    with pytest.raises(MeasurementError):
        safe_eval("L + 1")  # unknown variable
    with pytest.raises(MeasurementError):
        safe_eval("")


# ---- sheet -----------------------------------------------------------------
def _sheet():
    return build_sheet(
        item_ref="03.01.010",
        description="Plaster to walls",
        unit="m2",
        lines=[
            {"ref": "1", "description": "Room A wall", "formula": "4.20 * 2.70", "factor": "2"},
            {"ref": "2", "description": "Room A end", "formula": "3.10 * 2.70"},
            {"ref": "3", "description": "Door opening", "formula": "0.90 * 2.10", "sign": "-"},
        ],
    )


def test_sheet_totals_with_deduction():
    sheet = _sheet()
    # 2*(4.20*2.70)=22.68 ; 3.10*2.70=8.37 ; minus 0.90*2.10=1.89
    assert sheet.total_quantity == Decimal("29.16")
    d = sheet.to_dict()
    assert d["total_quantity"] == "29.160"
    assert d["line_count"] == 3
    assert d["has_errors"] is False
    # The deduction line reports a negative quantity.
    assert d["lines"][2]["quantity"] == "-1.890"
    assert d["lines"][2]["sign"] == "-"


def test_variables_line():
    sheet = build_sheet(
        item_ref="1",
        description="Slab",
        unit="m3",
        lines=[{"description": "Slab", "formula": "L * B * T", "variables": {"L": 6, "B": 4, "T": "0.25"}}],
    )
    assert sheet.total_quantity == Decimal("6.000")


def test_non_strict_keeps_bad_line_as_error():
    sheet = build_sheet(
        item_ref="1",
        description="x",
        unit="m",
        lines=[
            {"description": "good", "formula": "2 * 3"},
            {"description": "bad", "formula": "2 * "},  # syntax error
        ],
        strict=False,
    )
    d = sheet.to_dict()
    assert d["has_errors"] is True
    assert d["lines"][1]["error"]
    assert d["lines"][1]["quantity"] == "0.000"
    # The good line still counts.
    assert sheet.total_quantity == Decimal("6.000")


def test_strict_raises_on_bad_formula():
    with pytest.raises(MeasurementError):
        build_sheet(item_ref="1", description="x", unit="m", lines=[{"description": "bad", "formula": "a b c"}])


def test_empty_sheet_raises():
    with pytest.raises(MeasurementError):
        build_sheet(item_ref="1", description="x", unit="m", lines=[])


# ---- presets and export ----------------------------------------------------
def test_markdown_shows_formula_and_total():
    md = render_markdown(_sheet(), preset="reb")
    assert "REB 23.003" in md
    assert "4.20 * 2.70" in md
    assert "Total quantity: 29.160 m2" in md


def test_csv_export_has_header_and_total():
    csv = render_csv(_sheet())
    lines = csv.strip().split("\r\n")
    assert lines[0].startswith("ref,description,formula")
    assert lines[-1].startswith(",TOTAL")
    assert "29.160" in lines[-1]


def test_preset_lookup_defaults_to_international():
    assert get_preset("reb").standard == "REB 23.003"
    assert get_preset("oenorm").region == "AT"
    assert get_preset("nope").name == "international"


# ---- variable listing and reconciliation -----------------------------------
def test_list_variables_first_seen_order_without_functions():
    assert list_variables("L * B * H") == ["L", "B", "H"]
    # A repeated variable appears once; functions are not variables.
    assert list_variables("sqrt(A) + A * n") == ["A", "n"]
    # A pure-number formula needs no variables.
    assert list_variables("3.5 * 2.4") == []


def test_list_variables_tolerates_leading_equals():
    assert list_variables("= L * B") == ["L", "B"]
    assert safe_eval("= 2 * 3") == Decimal("6")


def test_reconcile_within_and_outside_tolerance():
    sheet = _sheet()  # total 29.16
    good = reconcile(sheet, "29.16")
    assert good["matches"] is True
    assert good["difference"] == "0.000"
    assert good["measured_quantity"] == "29.160"

    off = reconcile(sheet, "30.00")
    assert off["matches"] is False
    assert off["difference"] == "-0.840"

    # A generous tolerance accepts the drift.
    assert reconcile(sheet, "29.20", tolerance="0.1")["matches"] is True
