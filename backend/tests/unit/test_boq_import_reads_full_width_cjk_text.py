# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill typed with full-width characters imports as the same bill typed without.

Chinese, Japanese and Korean input methods type brackets, digits, separators
and unit squares in their full-width forms, and an estimator's workbook mixes
them freely with the ASCII ones. The importer only knew the ASCII forms:

* the header matcher stripped "(元)" but not "（元）", so the GB 50500 money
  heading "金额（元）" matched no column, and the two-row header under it was
  refused, which imported every line of the bill at a rate of zero;
* a quantity typed "１２．５" was not a number at all, so its row failed;
* a unit written "㎡" failed the unit check when the line was saved, row by
  row, although it is plainly m2;
* a code typed in full-width digits kept them, so the same code typed two
  ways was two codes.

The fold is narrow on purpose: the full-width ASCII block, the ideographic
space and the CJK unit squares. "m²" is a unit the platform keeps as typed and
stays "m²".

Run::

    cd backend
    python -m pytest tests/unit/test_boq_import_reads_full_width_cjk_text.py -v
"""

from __future__ import annotations

import asyncio
import io

import pytest
from openpyxl import Workbook

from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers._encoding import fold_width, parse_numeric_cell
from app.modules.boq.importers.excel import (
    ExcelImporter,
    _compose_two_row_header,
    _match_column,
    normalise_label,
)


def _import(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content))


def _xlsx(rows: list[list[object]], merges: tuple[str, ...] = ()) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    for cells in merges:
        sheet.merge_cells(cells)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ── The fold itself ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("typed", "folded"),
    [
        ("１２．５", "12.5"),
        ("（元）", "(元)"),
        ("ｍ３", "m3"),
        ("㎡", "m2"),
        ("㎥", "m3"),
        ("㎏", "kg"),
        ("０１０１０１００１００１", "010101001001"),
        ("１　２５０", "1 250"),
        ("￥１２，５００", "¥12,500"),
    ],
)
def test_full_width_forms_fold_to_their_ascii_twins(typed: str, folded: str) -> None:
    assert fold_width(typed) == folded


@pytest.mark.parametrize("kept", ["m²", "m³", "№", "½", "混凝土", "콘크리트", "Beton C25/30"])
def test_everything_outside_the_full_width_blocks_is_left_as_typed(kept: str) -> None:
    assert fold_width(kept) == kept


# ── Headers ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "header",
    ["金额（元）", "金额(元)", "金额【元】", "金额〔元〕", "金额［元］", "金额 ( 元 )"],
)
def test_a_bracketed_currency_is_dropped_whatever_brackets_hold_it(header: str) -> None:
    assert normalise_label(header) == "金额"
    assert _match_column(header) == "total"


@pytest.mark.parametrize(("header", "canonical"), [("单价（元）", "unit_rate"), ("数量（ｍ３）", "quantity")])
def test_a_full_width_bracket_after_a_column_name_still_names_the_column(header: str, canonical: str) -> None:
    assert _match_column(header) == canonical


def test_the_numero_sign_folds_to_the_same_key_however_it_is_cased() -> None:
    # NFKD turned "№" into "No" after the label had been lowercased, so its key
    # kept a capital the matcher never meets anywhere else.
    assert normalise_label("№ п/п") == normalise_label("no п/п")


# ── Numbers ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("typed", "comma_thousands", "expected"),
    [
        ("１２．５", False, 12.5),
        ("１，２５０", True, 1250.0),
        ("￥１２，５００", True, 12500.0),
        ("１　２５０．５", False, 1250.5),
    ],
)
def test_a_number_typed_full_width_is_a_number(typed: str, comma_thousands: bool, expected: float) -> None:
    assert parse_numeric_cell(typed, comma_thousands=comma_thousands) == (pytest.approx(expected), None)


# ── A GB 50500 bill (表-08) ────────────────────────────────────────────────

# The priced bill of quantities of GB 50500-2013, form 08: the money block is
# headed "金额（元）" over three columns, unit rate, amount and the part of it
# that is a provisional sum. The rest of the header spans both rows.
_GB50500_HEADER = [
    ["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "金额（元）", None, None],
    [None, None, None, None, None, None, "综合单价", "合价", "其中：暂估价"],
]
_GB50500_LINES = [
    ["１", "010101001001", "平整场地", "土壤类别：三类土", "㎡", "１２５０．００", "５．２０", "６５００．００", None],
    ["２", "010501003001", "独立基础", "混凝土强度等级：C30", "㎥", "86.5", "612.40", "52972.60", None],
]


def test_the_money_block_under_a_full_width_bracket_is_read_from_its_second_row() -> None:
    composed = _compose_two_row_header(tuple(_GB50500_HEADER[0]), tuple(_GB50500_HEADER[1]))

    assert composed is not None
    assert _match_column(composed[6]) == "unit_rate"
    assert _match_column(composed[7]) == "total"


def test_a_gb50500_bill_imports_its_rates_quantities_and_units() -> None:
    content = _xlsx(_GB50500_HEADER + _GB50500_LINES, merges=("G1:I1",))
    result = _import(content)

    assert result.errors == []
    lines = {p.ordinal: p for p in result.positions if not p.is_section}
    assert set(lines) == {"1", "2"}
    assert (lines["1"].quantity, lines["1"].unit_rate, lines["1"].unit) == (
        pytest.approx(1250.0),
        pytest.approx(5.2),
        "m2",
    )
    assert (lines["2"].quantity, lines["2"].unit_rate, lines["2"].unit) == (
        pytest.approx(86.5),
        pytest.approx(612.4),
        "m3",
    )
    # The amounts the bill states are what the lines come to.
    assert lines["1"].quantity * lines["1"].unit_rate == pytest.approx(6500.0)
    assert lines["2"].quantity * lines["2"].unit_rate == pytest.approx(52972.6)


def test_the_same_bill_as_csv_imports_the_same_lines() -> None:
    rows = [*_GB50500_HEADER, *_GB50500_LINES]
    text = "\n".join(",".join("" if cell is None else f'"{cell}"' for cell in row) for row in rows) + "\n"
    result = _import(text.encode("utf-8"))

    lines = {p.ordinal: p for p in result.positions if not p.is_section}
    assert (lines["1"].quantity, lines["1"].unit_rate, lines["1"].unit) == (
        pytest.approx(1250.0),
        pytest.approx(5.2),
        "m2",
    )
    assert lines["2"].unit_rate == pytest.approx(612.4)


# ── A Korean 내역서 ────────────────────────────────────────────────────────

# Each cost block (material, labour, expense, sum) is headed once over a unit
# price and an amount. The sum block is the line's own rate and amount; the
# importer has no third split component for expense (경비), so the three
# component blocks stay unread and only the sum block is taken.
_NAEYEOKSEO = [
    ["번호", "품명", "규격", "단위", "수량", "재료비", None, "노무비", None, "경비", None, "합계", None],
    [None, None, None, None, None, "단가", "금액", "단가", "금액", "단가", "금액", "단가", "금액"],
    ["1", "레미콘 타설", "25-24-150", "㎥", "40", "80000", "3200000", "20000", "800000", "5000", "200000",
     "105000", "4200000"],
]  # fmt: skip


def test_a_korean_bill_takes_the_sum_block_as_the_line_rate() -> None:
    result = _import(_xlsx(_NAEYEOKSEO, merges=("F1:G1", "H1:I1", "J1:K1", "L1:M1")))

    lines = [p for p in result.positions if not p.is_section]
    assert len(lines) == 1
    assert (lines[0].quantity, lines[0].unit_rate, lines[0].unit) == (
        pytest.approx(40.0),
        pytest.approx(105000.0),
        "m3",
    )


def test_a_split_header_still_composes_its_sub_columns_under_the_parent() -> None:
    # The Hungarian shape the composition was written for: the sub-columns
    # name a half of the parent, and none of them is a column on its own.
    composed = _compose_two_row_header(
        ("Ssz.", "Megnevezés", "Me.", "Mennyiség", "Egységár", None),
        (None, None, None, None, "Anyag", "Díj"),
    )
    assert composed is not None
    assert [_match_column(cell) for cell in composed[4:]] == ["material_rate", "labour_rate"]
