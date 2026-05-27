# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the multi-language xlsx BoQ parser.

Covers MAPPING_PROCESS.md §4.1.5 — the Excel BoQ source path. The
parser must:

* Recognise English / German / Russian / Spanish / CJK column headers.
* Tolerate decimal-comma quantities (``"1.234,56"``).
* Drop rows without a description.
* Reject obviously malformed inputs with a clear ValueError.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.modules.match_elements.excel_import import (
    _match_column,
    _to_float_qty,
    parse_boq_xlsx,
)


def _build_xlsx(rows: list[list]) -> bytes:
    """Build an xlsx workbook from a list of row lists (first row = headers)."""
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ── _match_column ───────────────────────────────────────────────────────


class TestMatchColumn:
    def test_english_canonicals(self):
        assert _match_column("Description") == "description"
        assert _match_column("Qty") == "qty"
        assert _match_column("Unit") == "unit"
        assert _match_column("Code") == "code"
        assert _match_column("Category") == "category"

    def test_german(self):
        assert _match_column("Beschreibung") == "description"
        assert _match_column("Menge") == "qty"
        assert _match_column("Einheit") == "unit"
        assert _match_column("Gewerk") == "category"

    def test_russian(self):
        assert _match_column("Описание") == "description"
        assert _match_column("Количество") == "qty"
        assert _match_column("Ед.изм.") == "unit"
        assert _match_column("Код") == "code"

    def test_cjk(self):
        assert _match_column("描述") == "description"
        assert _match_column("数量") == "qty"
        assert _match_column("単位") == "unit"
        assert _match_column("코드") == "code"

    def test_unknown_returns_none(self):
        assert _match_column("Foobar") is None
        assert _match_column("") is None
        assert _match_column(None) is None
        assert _match_column(42) is None

    def test_whitespace_tolerant(self):
        assert _match_column("  Description  ") == "description"
        assert _match_column("UNIT") == "unit"


# ── _to_float_qty ───────────────────────────────────────────────────────


class TestToFloatQty:
    def test_passthrough(self):
        assert _to_float_qty(12.5) == 12.5
        assert _to_float_qty(7) == 7.0

    def test_european_format(self):
        # German "1.234,56" — dot is thousands sep, comma is decimal.
        assert _to_float_qty("1.234,56") == 1234.56
        assert _to_float_qty("12,5") == 12.5

    def test_us_format(self):
        # US "1,234.56" — comma is thousands, dot is decimal.
        assert _to_float_qty("1,234.56") == 1234.56

    def test_blank_returns_none(self):
        assert _to_float_qty("") is None
        assert _to_float_qty("   ") is None
        assert _to_float_qty(None) is None

    def test_garbage_returns_none(self):
        assert _to_float_qty("not a number") is None

    def test_bool_returns_none(self):
        # bool is an int subclass — explicitly reject so True/False
        # doesn't sneak through as 1.0/0.0.
        assert _to_float_qty(True) is None
        assert _to_float_qty(False) is None


# ── parse_boq_xlsx ──────────────────────────────────────────────────────


class TestParseBoqXlsx:
    def test_minimal_english(self):
        content = _build_xlsx(
            [
                ["Description", "Qty", "Unit"],
                ["Concrete wall C30/37", 25.0, "m3"],
                ["Plaster work", 100, "m2"],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert len(rows) == 2
        assert rows[0] == {
            "description": "Concrete wall C30/37",
            "qty": 25.0,
            "unit": "m3",
        }
        assert rows[1]["qty"] == 100.0

    def test_german_headers(self):
        content = _build_xlsx(
            [
                ["Beschreibung", "Menge", "Einheit", "Gewerk"],
                ["Stahlbetonwand C30/37", "25,5", "m3", "Rohbau"],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert len(rows) == 1
        assert rows[0]["description"] == "Stahlbetonwand C30/37"
        # Decimal-comma must parse as 25.5.
        assert rows[0]["qty"] == 25.5
        assert rows[0]["category"] == "Rohbau"

    def test_russian_headers(self):
        content = _build_xlsx(
            [
                ["Наименование", "Количество", "Ед.изм.", "Код"],
                ["Бетонная стена B25", 12.0, "м3", "ФЕР06-01-001"],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert len(rows) == 1
        assert "Бетонная стена" in rows[0]["description"]
        assert rows[0]["unit"] == "м3"
        assert rows[0]["code"] == "ФЕР06-01-001"

    def test_optional_columns_omitted(self):
        # Description-only spreadsheet — qty/unit absent. Should still
        # produce rows; matchers default to count=1.0 from BoqAdapter.
        content = _build_xlsx(
            [
                ["Description"],
                ["Wall"],
                ["Floor"],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert len(rows) == 2
        assert rows[0] == {"description": "Wall"}
        assert "qty" not in rows[0]

    def test_unknown_columns_dropped(self):
        # Tenant-specific extra columns shouldn't pollute the dict.
        content = _build_xlsx(
            [
                ["Description", "Qty", "Supplier", "DeliveryWeek"],
                ["Wall", 5, "Acme", 12],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert rows[0] == {"description": "Wall", "qty": 5.0}

    def test_blank_description_skipped(self):
        content = _build_xlsx(
            [
                ["Description", "Qty", "Unit"],
                ["Valid wall", 10, "m3"],
                [None, 5, "m2"],  # no description → skip
                ["", 7, "m"],  # blank description → skip
                ["   ", 8, "m"],  # whitespace only → skip
                ["Another row", 1, "m"],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert len(rows) == 2
        assert rows[0]["description"] == "Valid wall"
        assert rows[1]["description"] == "Another row"

    def test_non_numeric_qty_dropped_but_row_kept(self):
        content = _build_xlsx(
            [
                ["Description", "Qty", "Unit"],
                ["Wall", "not-a-number", "m3"],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert len(rows) == 1
        assert rows[0]["description"] == "Wall"
        assert "qty" not in rows[0]

    def test_missing_description_column_raises(self):
        # No alias for "Quantity" matches "description".
        content = _build_xlsx(
            [
                ["Position", "Qty", "Unit"],
                ["Wall", 5, "m3"],
            ]
        )
        with pytest.raises(ValueError) as exc:
            parse_boq_xlsx(content)
        assert "Description" in str(exc.value)

    def test_empty_file_raises(self):
        # Truly empty bytes → not a valid xlsx.
        with pytest.raises(ValueError):
            parse_boq_xlsx(b"")

    def test_non_xlsx_bytes_raises(self):
        with pytest.raises(ValueError):
            parse_boq_xlsx(b"this is not an xlsx file")

    def test_workbook_with_only_headers(self):
        content = _build_xlsx(
            [
                ["Description", "Qty"],
            ]
        )
        # Header-only file → empty result, not an error.
        assert parse_boq_xlsx(content) == []

    def test_string_qty_with_unit_suffix(self):
        # Spreadsheet author put "12.5 m³" instead of just 12.5 in the
        # qty column — parser should still rescue the number.
        content = _build_xlsx(
            [
                ["Description", "Qty"],
                ["Wall", "12.5"],  # clean number works
            ]
        )
        rows = parse_boq_xlsx(content)
        assert rows[0]["qty"] == 12.5

    def test_source_lang_passes_through(self):
        content = _build_xlsx(
            [
                ["Description", "Qty", "Unit", "source_lang"],
                ["Concrete wall", 25, "m3", "de"],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert rows[0]["source_lang"] == "de"

    def test_strings_are_trimmed(self):
        content = _build_xlsx(
            [
                ["Description", "Unit"],
                ["  Concrete wall  ", "  m3  "],
            ]
        )
        rows = parse_boq_xlsx(content)
        assert rows[0]["description"] == "Concrete wall"
        assert rows[0]["unit"] == "m3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
