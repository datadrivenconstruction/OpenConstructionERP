# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill priced as material plus labour reads its halves the way the file writes numbers.

The importer decides once per file whether "1.250" or "1,250" groups thousands:
the header language proposes it and one cell that can only be written the
other way vetoes it (``_grouping_conventions``). The material and labour
halves were folded into the line's rate before that decision existed, row by
row and from the header language alone, so a file whose own numbers vetoed the
grouping still had its halves read with it. An English-headed bill typed with
decimal commas imported "1,250" + "2,50" as 1252.50 instead of 3.75, and the
halves kept in the line's metadata were read a third way, so they did not even
add up to the rate stored beside them.

Every test here holds the rate and the halves to one reading, and each one
carries a line the wrong reading changes.

Run::

    cd backend
    python -m pytest tests/unit/test_boq_import_split_rates_follow_the_files_grouping.py -v
"""

from __future__ import annotations

import asyncio
import io

import pytest
from openpyxl import Workbook

from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers.excel import (
    ExcelImporter,
    _parse_rows_from_csv,
    _parse_rows_from_excel,
)


def _import(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content))


def _lines(result: ImportedBOQ) -> dict[str, object]:
    return {p.ordinal: p for p in result.positions if not p.is_section}


def _halves(position: object) -> tuple[float, float]:
    meta = position.metadata  # type: ignore[attr-defined]
    if "hu" in meta:
        return meta["hu"]["material_unit_rate"], meta["hu"]["fee_unit_rate"]
    return meta["rate_split"]["material_unit_rate"], meta["rate_split"]["labour_unit_rate"]


# An English header typed on a machine that writes a decimal comma: the
# semicolon is Excel's list separator there and "2,50" can only be two and a
# half. That one cell says the comma is the decimal point in this file, so
# "1,250" is one and a quarter, not twelve hundred and fifty.
_ENGLISH_HEADER_DECIMAL_COMMA = (
    b"Item;Description;Unit;Quantity;Material rate;Labour rate\n"
    b"1;Facing brickwork;m2;12;1,250;2,50\n"
    b"2;Gypsum plaster;m2;40;3,75;1,25\n"
)


def test_an_english_bill_typed_with_decimal_commas_folds_its_halves_as_decimals() -> None:
    lines = _lines(_import(_ENGLISH_HEADER_DECIMAL_COMMA))

    assert lines["1"].unit_rate == pytest.approx(3.75)  # not 1252.50
    assert lines["2"].unit_rate == pytest.approx(5.0)


def test_the_halves_kept_beside_the_rate_add_up_to_it() -> None:
    lines = _lines(_import(_ENGLISH_HEADER_DECIMAL_COMMA))

    for position in lines.values():
        material, labour = _halves(position)
        assert material + labour == pytest.approx(position.unit_rate)
    assert _halves(lines["1"]) == (pytest.approx(1.25), pytest.approx(2.5))


def test_the_rows_the_legacy_routes_read_carry_the_same_rate() -> None:
    # The deprecated /import/excel/ route and the smart import read
    # ``unit_rate`` straight off these rows, so the fold has to be right here
    # and not only in the positions.
    rows = _parse_rows_from_csv(_ENGLISH_HEADER_DECIMAL_COMMA)

    assert rows[0]["unit_rate"] == pytest.approx(3.75)
    assert rows[1]["unit_rate"] == pytest.approx(5.0)


# The Hungarian mirror. Hungarian proposes dot grouping ("12.500 Ft"), and a
# quantity typed "12.5" can only carry a decimal point, so this file writes
# its numbers the English way and "1.250" is one and a quarter.
_HUNGARIAN_HEADER_DECIMAL_POINT = (
    "Ssz.;Megnevezés;Me.;Mennyiség;Anyag egységár;Díj egységár\n"
    "1;Falazás kisméretű téglából;m2;12.5;1.250;300\n"
    "2;Vakolás;m2;40;2.5;1.5\n"
).encode()


def test_a_hungarian_bill_typed_with_decimal_points_folds_its_halves_as_decimals() -> None:
    lines = _lines(_import(_HUNGARIAN_HEADER_DECIMAL_POINT))

    assert lines["1"].unit_rate == pytest.approx(301.25)  # not 1550
    assert lines["2"].unit_rate == pytest.approx(4.0)
    for position in lines.values():
        material, fee = _halves(position)
        assert material + fee == pytest.approx(position.unit_rate)


# The ordinary Hungarian bill, where the dot does group thousands. The fold
# was right here already; the halves in the metadata were read as 12.5 and 3.
_HUNGARIAN_DOT_THOUSANDS = (
    "Ssz.;Megnevezés;Me.;Mennyiség;Anyag egységár;Díj egységár\n"
    "1;Falazás kisméretű téglából;m2;12;12.500;3.000\n"
    "2;Vakolás;m2;40;2.400;1.600\n"
).encode()


def test_a_hungarian_bill_with_dot_thousands_keeps_its_halves_in_thousands() -> None:
    result = _import(_HUNGARIAN_DOT_THOUSANDS)
    lines = _lines(result)

    assert lines["1"].unit_rate == pytest.approx(15500.0)
    assert lines["2"].unit_rate == pytest.approx(4000.0)
    assert _halves(lines["1"]) == (pytest.approx(12500.0), pytest.approx(3000.0))
    for position in lines.values():
        material, fee = _halves(position)
        assert material + fee == pytest.approx(position.unit_rate)
    # Every cell read with grouping is still reported, halves included.
    noted = {(w["ordinal"], w["column"]) for w in result.warnings if w.get("code") == "dot_read_as_thousands"}
    assert ("1", "material_rate") in noted
    assert ("1", "labour_rate") in noted


def _workbook(*sheets: tuple[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets:
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


_HU_HEADER = ["Ssz.", "Megnevezés", "Me.", "Mennyiség", "Anyag egységár", "Díj egységár"]


def test_the_grouping_is_decided_once_for_the_whole_workbook() -> None:
    # The vetoing cell is on the first trade's sheet and the ambiguous one on
    # the second. Read sheet by sheet, the second trade had no veto of its own
    # and its "1.250" became twelve hundred and fifty.
    content = _workbook(
        ("Építészet", [_HU_HEADER, ["1", "Falazás", "m2", "12.5", "2.5", "1.5"]]),
        ("Gépészet", [_HU_HEADER, ["1", "Csővezeték", "m", "8", "1.250", "0.75"]]),
    )
    result = _import(content)
    priced = [p for p in result.positions if not p.is_section]

    assert [p.unit_rate for p in priced] == [pytest.approx(4.0), pytest.approx(2.0)]
    for position in priced:
        material, fee = _halves(position)
        assert material + fee == pytest.approx(position.unit_rate)

    rows, _ = _parse_rows_from_excel(content)
    rates = [row["unit_rate"] for row in rows if "unit_rate" in row]
    assert rates == [pytest.approx(4.0), pytest.approx(2.0)]


def test_a_contingency_written_with_dot_thousands_keeps_its_amount() -> None:
    # A reserve line carries its amount in the total column alone and comes in
    # as a lump sum. Its amount was read with no grouping at all, so a
    # Hungarian reserve of 250 000 Ft became 250 Ft while the lines beside it
    # were read in thousands; the summary line reported 1 875.5 the same way.
    content = (
        "Ssz.;Megnevezés;Me.;Mennyiség;Egységár;Összesen\n"
        "1;Falazás kisméretű téglából;m2;12;12.500;150.000\n"
        "2;Tartalékkeret 5%;;;;250.000\n"
        ";Összesen;;;;1.875.500\n"
    ).encode()
    result = _import(content)
    lines = _lines(result)

    assert lines["1"].unit_rate == pytest.approx(12500.0)
    assert lines["2"].unit_rate == pytest.approx(250000.0)
    assert lines["2"].quantity == pytest.approx(1.0)
    summary = result.metadata.get("summary_rows") or []
    assert [row["amount"] for row in summary] == [pytest.approx(1875500.0)]


def test_a_half_that_is_not_a_number_still_fails_its_row_rather_than_pricing_it() -> None:
    content = (
        b"Item;Description;Unit;Quantity;Material rate;Labour rate\n"
        b"1;Facing brickwork;m2;12;see note;2,50\n"
        b"2;Gypsum plaster;m2;40;3,75;1,25\n"
    )
    result = _import(content)

    assert [e["row"] for e in result.errors] == [2]
    assert [p.ordinal for p in result.positions] == ["2"]
