# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A Hungarian költségvetés imports with its quantities, its rates and its totals left out.

A tester in Hungary imported their bills and "did not get a good result".
Run through the spreadsheet importer, a bill in the everyday Hungarian layout
came back with every quantity and every rate at zero: "Menny." is how the
quantity column is headed and the table only knew "Mennyiség", and the rate
is quoted as material plus fee in two columns with no single rate column at
all. The chapter totals ("... összesen:") became empty sections because
Hungarian puts the total word at the end, a workbook that opens on its cover
sheet imported nothing, and a Windows-1250 CSV lost its ő and ű.

Every variant in :mod:`tests.fixtures.hu_boq` has to come out the same:
eight priced lines, two chapter headings, five summary lines left out.
"""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Callable

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers.excel import (
    ExcelImporter,
    _infer_classification,
    _sniff_delimiter,
    summary_label_kind,
)
from app.modules.boq.units import is_lump_sum_unit
from tests.fixtures import hu_boq


def _parse(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content))


_VARIANTS: dict[str, Callable[[], bytes]] = {
    "flat_xlsx": hu_boq.flat_xlsx,
    "two_row_header_xlsx": hu_boq.two_row_header_xlsx,
    "cover_first_xlsx": hu_boq.cover_first_xlsx,
    "cp1250_csv": hu_boq.cp1250_csv,
    "utf8_csv": hu_boq.utf8_csv,
    "single_rate_xlsx": hu_boq.single_rate_xlsx,
}


@pytest.mark.parametrize("variant", sorted(_VARIANTS))
def test_every_priced_line_imports_with_its_quantity_unit_and_full_rate(variant: str) -> None:
    result = _parse(_VARIANTS[variant]())

    assert result.errors == []
    lines = [position for position in result.positions if not position.is_section]
    got = [(p.ordinal, p.unit, p.quantity, p.unit_rate) for p in lines]
    want = [(ssz, unit, qty, pytest.approx(material + fee)) for ssz, unit, qty, material, fee in hu_boq.EXPECTED_LINES]
    assert got == want


@pytest.mark.parametrize("variant", sorted(_VARIANTS))
def test_chapter_headings_stay_sections_and_every_total_line_is_left_out(variant: str) -> None:
    result = _parse(_VARIANTS[variant]())

    sections = [position.description for position in result.positions if position.is_section]
    assert sections == ["21 Irtás, föld- és sziklamunka", "31 Helyszíni beton és vasbeton munkák"]
    summary = [(w["label"], w["kind"]) for w in result.warnings if w.get("code") == "summary_row_skipped"]
    assert summary == hu_boq.EXPECTED_SUMMARY


@pytest.mark.parametrize("variant", sorted(_VARIANTS))
def test_the_item_number_is_the_lines_code_and_not_its_ordinal(variant: str) -> None:
    result = _parse(_VARIANTS[variant]())

    panel = next(p for p in result.positions if p.description == hu_boq.PANEL)
    assert panel.ordinal == "3"
    assert panel.classification == {"code": "31-011-1.1.1"}


def test_the_two_row_header_rate_is_material_plus_fee_not_the_material_half() -> None:
    """The parent "Egységár" sits over the material column; reading it as the rate halves the bill."""
    result = _parse(hu_boq.two_row_header_xlsx())

    panel = next(p for p in result.positions if p.description == hu_boq.PANEL)
    assert panel.unit_rate == pytest.approx(97_700.0)
    assert result.metadata["column_mapping"]["5"] == "unit_rate"
    assert result.metadata["column_mapping"]["6"] == "unit_rate"


def test_the_split_is_kept_where_the_hungarian_material_and_fee_rule_reads_it() -> None:
    result = _parse(hu_boq.flat_xlsx())

    panel = next(p for p in result.positions if p.description == hu_boq.PANEL)
    assert panel.metadata["hu"]["material_unit_rate"] == pytest.approx(85_400.0)
    assert panel.metadata["hu"]["fee_unit_rate"] == pytest.approx(12_300.0)
    assert result.metadata["header_language"] == "hu"


def test_a_workbook_opening_on_its_cover_sheet_reads_the_item_sheet() -> None:
    result = _parse(hu_boq.cover_first_xlsx())

    assert result.metadata["item_sheet"] == "Költségvetés"


def test_a_windows_1250_csv_keeps_its_long_double_accents() -> None:
    result = _parse(hu_boq.cp1250_csv())

    descriptions = {position.description for position in result.positions}
    assert hu_boq.PANEL in descriptions
    assert "Előregyártott vasbeton födémpanel elhelyezése, hőszigeteléssel" in descriptions
    assert result.metadata["encoding"] == "cp1250"
    assert result.metadata["delimiter"] == ";"


def test_a_western_windows_1252_csv_is_not_read_as_central_european() -> None:
    """Portuguese õ is byte 0xF5, which Windows-1250 would read as ő."""
    text = "Descrição;Unidade;Quantidade;Preço Unitário\r\nInstalações elétricas;un;3;150,00\r\n"
    result = _parse(text.encode("cp1252"))

    assert [p.description for p in result.positions] == ["Instalações elétricas"]
    assert result.metadata["encoding"] == "cp1252"


def test_the_delimiter_is_the_one_the_table_is_laid_out_in() -> None:
    """Title lines above, decimal commas and commas inside descriptions do not win."""
    text = "Költségvetés\r\nSsz.;Tétel szövege;Menny.;Egység\r\n1;Tükörkészítés, tömörítéssel;340,5;m2\r\n"
    assert _sniff_delimiter(text) == ";"
    quoted = 'Pos,Description,Qty,Unit\r\n1,"Wall, internal","12,5",m2\r\n2,"Door, single","1",pcs\r\n'
    assert _sniff_delimiter(quoted) == ","


def test_an_english_provisional_sum_with_only_an_amount_is_not_a_total_line() -> None:
    """Trailing total words are read in Hungarian only; "sum" at the end of English is work."""
    assert summary_label_kind("Provisional sum for utility connections") is None
    assert summary_label_kind("PC sum") is None
    assert summary_label_kind("Irtás, föld- és sziklamunka összesen:") == ("subtotal", False)
    assert summary_label_kind("Bruttó összesen") == ("grand_total", True)


def test_an_english_bill_priced_as_material_plus_labour_imports_at_the_sum() -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Item", "Description", "Unit", "Qty", "Material rate", "Labour rate"])
    worksheet.append(["1", "Blockwork wall 100 mm", "m2", 40, 22.5, 18.0])
    buffer = io.BytesIO()
    workbook.save(buffer)

    result = _parse(buffer.getvalue())

    (line,) = result.positions
    assert line.unit_rate == pytest.approx(40.5)
    assert line.metadata["rate_split"]["material_unit_rate"] == pytest.approx(22.5)
    assert line.metadata["rate_split"]["labour_unit_rate"] == pytest.approx(18.0)
    assert "hu" not in line.metadata


def test_an_unreadable_half_of_the_rate_is_reported_not_guessed() -> None:
    rows = [hu_boq.HEADER, ["1", "", "Falazás", "10", "m2", "12 000", "n/a", "", ""]]
    content = "".join(";".join(row) + "\r\n" for row in rows).encode("utf-8")

    result = _parse(content)

    assert result.positions == []
    assert len(result.errors) == 1
    assert "unit_rate" in result.errors[0]["error"]


def test_an_engy_style_item_number_is_not_read_as_masterformat() -> None:
    assert _infer_classification("21-003-5.1.1", "Földkiemelés") == {"code": "21-003-5.1.1"}


@pytest.mark.parametrize("unit", ["klt", "Klt.", "átalány"])
def test_hungarian_lump_sum_units_are_lump_sums(unit: str) -> None:
    assert is_lump_sum_unit(unit)


def test_a_legacy_xls_upload_is_refused_with_what_to_do() -> None:
    from app.modules.boq.router import _refuse_legacy_xls

    ole_head = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
    with pytest.raises(HTTPException) as refused:
        _refuse_legacy_xls("koltsegvetes.xls", ole_head)
    assert refused.value.status_code == 400
    assert ".xlsx" in str(refused.value.detail)

    _refuse_legacy_xls("koltsegvetes.xlsx", b"PK\x03\x04" + b"\x00" * 60)
    _refuse_legacy_xls("model.rvt", ole_head)


def test_the_cp1250_fixture_really_is_not_utf8() -> None:
    """Guards the fixture: a CSV that decodes as UTF-8 would not test the code page at all."""
    content = hu_boq.cp1250_csv()
    with pytest.raises(UnicodeDecodeError):
        content.decode("utf-8")
    assert list(csv.reader(io.StringIO(content.decode("cp1250")), delimiter=";"))[4][2] == "Tétel szövege"
