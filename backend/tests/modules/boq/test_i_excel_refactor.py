"""Epic I3 — Excel/CSV importer regression tests.

Pins that the refactored ``ExcelImporter`` still handles the canonical
column-alias lookup, locale-tolerant numeric parsing, section-row
detection, and per-row error reporting that the legacy inline parser
in ``router.py`` used to do.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.modules.boq.importers import ImporterParseError
from app.modules.boq.importers.excel import (
    ExcelImporter,
    _match_column,
    _parse_rows_from_csv,
    _parse_rows_from_excel,
)

# ── Column-alias mapping ───────────────────────────────────────────────────


class TestColumnAliasMap:
    def test_english_headers(self) -> None:
        assert _match_column("Position") == "ordinal"
        assert _match_column("Description") == "description"
        assert _match_column("Unit") == "unit"
        assert _match_column("Quantity") == "quantity"
        assert _match_column("Unit Rate") == "unit_rate"

    def test_german_headers(self) -> None:
        assert _match_column("Beschreibung") == "description"
        assert _match_column("Einheit") == "unit"
        assert _match_column("Menge") == "quantity"
        assert _match_column("Einheitspreis") == "unit_rate"

    def test_spanish_headers(self) -> None:
        assert _match_column("Cantidad") == "quantity"
        assert _match_column("Precio") == "unit_rate"
        # ud / uds (unidad) maps to unit.
        assert _match_column("Ud") == "unit"

    def test_french_headers(self) -> None:
        assert _match_column("Quantité") == "quantity"
        assert _match_column("Prix") == "unit_rate"

    def test_case_and_whitespace_insensitive(self) -> None:
        assert _match_column("  QUANTITY  ") == "quantity"
        assert _match_column("description") == "description"

    def test_unknown_header_returns_none(self) -> None:
        assert _match_column("Some random column") is None


# ── CSV / Excel parsing ─────────────────────────────────────────────────────


def _build_csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
    w.writerow(["1", "Concrete C30/37", "m3", "10.0", "150.0"])
    w.writerow(["2", "Reinforcement", "kg", "1200", "1.85"])
    return buf.getvalue().encode("utf-8")


def _build_excel() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
    ws.append([1, "Concrete C30/37", "m3", 10.0, 150.0])
    ws.append([2, "Reinforcement", "kg", 1200, 1.85])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestExcelImporterRegression:
    @pytest.mark.asyncio
    async def test_csv_round_trip(self) -> None:
        result = await ExcelImporter.parse(_build_csv())
        assert result.source_format == "csv"
        assert len(result.positions) == 2
        assert result.positions[0].description == "Concrete C30/37"
        assert result.positions[0].unit == "m3"
        assert result.positions[0].quantity == 10.0
        assert result.positions[0].unit_rate == 150.0
        assert result.positions[1].quantity == 1200.0

    @pytest.mark.asyncio
    async def test_xlsx_round_trip(self) -> None:
        result = await ExcelImporter.parse(_build_excel())
        assert result.source_format == "xlsx"
        assert len(result.positions) == 2
        assert result.positions[0].description == "Concrete C30/37"
        # XLSX preserves original column ordering for round-trip export.
        assert "original_columns" in result.metadata
        assert result.metadata["original_columns"][0] == "Pos"

    @pytest.mark.asyncio
    async def test_european_decimal_comma(self) -> None:
        """A CSV with German decimal-comma numbers must parse correctly."""
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Pos", "Beschreibung", "Einheit", "Menge", "Einheitspreis"])
        w.writerow(["1", "Stahlbeton", "m3", "44,30", "185,00"])
        csv_bytes = buf.getvalue().encode("utf-8")
        result = await ExcelImporter.parse(csv_bytes)
        assert len(result.positions) == 1
        assert result.positions[0].quantity == 44.30
        assert result.positions[0].unit_rate == 185.00

    @pytest.mark.asyncio
    async def test_section_header_row_detected(self) -> None:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
        w.writerow(["A", "Earthworks", "", "", ""])  # section row
        w.writerow(["1", "Excavation", "m3", "100.0", "5.0"])
        result = await ExcelImporter.parse(buf.getvalue().encode("utf-8"))
        sections = [p for p in result.positions if p.is_section]
        assert len(sections) == 1
        assert sections[0].description == "Earthworks"
        assert sections[0].unit == "section"

    @pytest.mark.asyncio
    async def test_summary_row_skipped(self) -> None:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
        w.writerow(["1", "Item A", "m", "10.0", "5.0"])
        w.writerow(["", "Total", "", "", ""])
        w.writerow(["", "Gesamtsumme", "", "", ""])
        result = await ExcelImporter.parse(buf.getvalue().encode("utf-8"))
        # Two summary rows skipped, one partida imported.
        assert len(result.positions) == 1
        assert result.skipped == 2

    @pytest.mark.asyncio
    async def test_invalid_quantity_collected_as_error(self) -> None:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
        w.writerow(["1", "Item A", "m", "not-a-number", "5.0"])
        w.writerow(["2", "Item B", "m", "10.0", "5.0"])
        result = await ExcelImporter.parse(buf.getvalue().encode("utf-8"))
        # The malformed row goes into errors, the clean row is imported.
        assert len(result.positions) == 1
        assert len(result.errors) == 1
        assert result.errors[0]["row"] == 2

    @pytest.mark.asyncio
    async def test_zero_quantity_warning(self) -> None:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
        w.writerow(["1", "Item A", "m", "0.0", "5.0"])
        result = await ExcelImporter.parse(buf.getvalue().encode("utf-8"))
        assert len(result.positions) == 1
        assert any(w["severity"] == "info" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_empty_file_raises(self) -> None:
        with pytest.raises(ImporterParseError):
            await ExcelImporter.parse(b"")

    @pytest.mark.asyncio
    async def test_only_header_no_data_raises(self) -> None:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
        with pytest.raises(ImporterParseError):
            await ExcelImporter.parse(buf.getvalue().encode("utf-8"))

    def test_detect_xlsx_extension(self) -> None:
        xlsx = _build_excel()
        assert ExcelImporter.detect(xlsx[:4096], "boq.xlsx") is True

    def test_detect_csv_extension(self) -> None:
        csv_bytes = _build_csv()
        assert ExcelImporter.detect(csv_bytes[:4096], "boq.csv") is True

    def test_detect_rejects_xlsx_with_csv_content(self) -> None:
        # File renamed .xlsx but is actually CSV — must NOT claim it.
        assert ExcelImporter.detect(b"a,b,c\n1,2,3\n", "fake.xlsx") is False


# ── Direct helper tests ────────────────────────────────────────────────────


def test_parse_rows_from_csv_alias_map() -> None:
    """Polish header (``Ilość``) is recognised via the alias map."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Nr.", "Opis", "Jed", "Ilość", "Cena"])
    w.writerow(["1", "Beton C25/30", "m3", "10.5", "120.00"])
    rows = _parse_rows_from_csv(buf.getvalue().encode("utf-8"))
    assert len(rows) == 1
    assert rows[0]["description"] == "Beton C25/30"
    assert rows[0]["quantity"] == "10.5"


def test_parse_rows_from_excel_metadata() -> None:
    xlsx = _build_excel()
    rows, meta = _parse_rows_from_excel(xlsx)
    assert len(rows) == 2
    assert meta["sheet_names"]
    assert meta["original_columns"] == ["Pos", "Description", "Unit", "Quantity", "Unit Rate"]
    assert meta["total_rows"] == 2
