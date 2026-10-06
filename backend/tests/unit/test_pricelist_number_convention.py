"""A table reads "1.250" the way the rest of its file writes numbers, or says it cannot.

"1.250" is 1250 in a list that writes "12,50" and 1.25 in one that writes
"12.50"; on its own it is either. The reader used to take the point as the
decimal separator whatever the file said, so a comma-decimal list priced an
item at a thousandth of its rate without a word. A table now learns its
convention from the cells only one reading fits, and a cell the file cannot
settle is reported as a broken number, never guessed. XML lists are typed by
their schema (a point is always the decimal separator) and are not affected.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest

from app.modules.costs.pricelists import base
from app.modules.costs.pricelists.service import build_preview, plan_upload

HEADER = '"CODICE";"DESCRIZIONE";"UM";"PREZZO";"INCIDENZA MANODOPERA"'


def _csv(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


def _rows(data: bytes, name: str = "elenco_prezzi.csv") -> dict[str, object]:
    plan = plan_upload(io.BytesIO(data), name)
    return {row.code: row for row in plan.rows()}


def _convention(*cells: str):
    convention = base.NumberConvention()
    for cell in cells:
        convention.observe(cell)
    return convention


# ── The number itself ───────────────────────────────────────────────────────


def test_a_comma_decimal_file_reads_a_point_as_grouping() -> None:
    convention = _convention("12,50", "1.826,34")
    assert convention.decimal == ","
    assert base.parse_amount("1.250", convention=convention) == Decimal(1250)
    assert base.parse_amount("1,250", convention=convention) == Decimal("1.25")


def test_a_point_decimal_file_reads_a_comma_as_grouping() -> None:
    convention = _convention("12.50", "1,826.34")
    assert convention.decimal == "."
    assert base.parse_amount("1.250", convention=convention) == Decimal("1.25")
    assert base.parse_amount("1,250", convention=convention) == Decimal(1250)


@pytest.mark.parametrize("cells", [(), ("1.250", "2.500", "125"), ("12,50", "12.50")])
def test_a_file_that_cannot_settle_it_reports_the_cell_as_broken(cells: tuple[str, ...]) -> None:
    convention = _convention(*cells)
    assert convention.decimal is None
    for raw in ("1.250", "1,250", "€ 9.821"):
        with pytest.raises(base.BrokenNumber):
            base.parse_amount(raw, convention=convention)


@pytest.mark.parametrize("raw", ["0.250", "0,250", "1250.000", "12,5", "13.63017", "1 826,34"])
def test_a_cell_only_one_reading_fits_is_read_whatever_the_file_says(raw: str) -> None:
    unknown = base.NumberConvention()
    assert base.parse_amount(raw, convention=unknown) == base.parse_amount(raw)


# ── Through the reader ──────────────────────────────────────────────────────


def test_a_comma_decimal_csv_reads_one_thousand_two_hundred_fifty() -> None:
    rows = _rows(_csv("A.01;Scavo;m3;12,50;40,1", "A.02;Muratura;m2;1.250;35,2"))
    assert rows["A.02"].rate == Decimal(1250)
    assert rows["A.01"].rate == Decimal("12.5")


def test_a_point_decimal_csv_reads_one_thousand_two_hundred_fifty() -> None:
    rows = _rows(_csv("A.01;Scavo;m3;12.50;40.1", "A.02;Muratura;m2;1,250;35.2"))
    assert rows["A.02"].rate == Decimal(1250)


def test_the_evidence_may_come_after_the_cell_it_settles() -> None:
    rows = _rows(_csv("A.01;Muratura;m2;1.250;35", "A.02;Scavo;m3;8;40", "A.03;Intonaco;m2;17,45;61"))
    assert rows["A.01"].rate == Decimal(1250)


def test_a_csv_that_never_settles_it_flags_the_rate_and_the_preview_counts_it() -> None:
    data = _csv("A.01;Muratura;m2;1.250;35", "A.02;Scavo;m3;8;40")
    rows = _rows(data)
    assert rows["A.01"].rate is None
    assert "broken_number:rate" in rows["A.01"].flags
    assert rows["A.02"].rate == Decimal(8)
    preview = build_preview(plan_upload(io.BytesIO(data), "elenco_prezzi.csv"))
    assert preview["counts"]["broken_rows"] == 1


def test_a_workbook_with_numbers_as_text_settles_like_a_csv() -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["CODICE", "DESCRIZIONE", "UM", "PREZZO", "INCIDENZA MANODOPERA"])
    sheet.append(["A.01", "Scavo", "m3", "12,50", "40,1"])
    sheet.append(["A.02", "Muratura", "m2", "1.250", "35,2"])
    # A real number cell is a number: nothing to settle.
    sheet.append(["A.03", "Intonaco", "m2", 1.25, 61])
    buf = io.BytesIO()
    workbook.save(buf)
    rows = _rows(buf.getvalue(), "elenco_prezzi.xlsx")
    assert rows["A.02"].rate == Decimal(1250)
    assert rows["A.03"].rate == Decimal("1.25")


def test_an_xml_list_keeps_reading_a_point_as_the_decimal_separator() -> None:
    # Toscana writes analysis amounts such as "9.821"; its schema types them.
    assert base.parse_amount("9.821") == Decimal("9.821")
