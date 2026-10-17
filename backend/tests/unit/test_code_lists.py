# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Code lists: order, placement, validation of uploads, and the shipped data."""

from __future__ import annotations

import io

import pytest

from app.core import code_lists as cl
from app.core.code_lists import (
    CodeListParseError,
    build_entries,
    code_sort_key,
    get_code_list,
    parent_for,
    parse_code_list_file,
    validate_code,
)

# ── Order ────────────────────────────────────────────────────────────────────


def test_numbers_sort_by_value_segment_by_segment() -> None:
    codes = ["2.10", "2.9", "2", "10", "1"]
    assert sorted(codes, key=code_sort_key) == ["1", "2", "2.9", "2.10", "10"]


def test_digits_sort_before_letters_and_letters_ignore_case() -> None:
    codes = ["b", "A10", "A2", "9", "a1"]
    assert sorted(codes, key=code_sort_key) == ["9", "a1", "A2", "A10", "b"]


def test_spaced_codes_sort_by_their_groups() -> None:
    codes = ["03 30 00", "03 10 00", "03", "02"]
    assert sorted(codes, key=code_sort_key) == ["02", "03", "03 10 00", "03 30 00"]


# ── Code shape ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", ["300", "2.6.1", "03 30 00", "B2010", "KG-300", "ГЭСН.01", "A"])
def test_valid_codes(code: str) -> None:
    assert validate_code(code) is None


@pytest.mark.parametrize(
    ("code", "problem"),
    [
        ("", "code_missing"),
        ("  ", "code_missing"),
        ("3..1", "code_invalid"),
        (" 300", "code_invalid"),
        ("300/", "code_invalid"),
        ("x" * 81, "code_too_long"),
    ],
)
def test_invalid_codes(code: str, problem: str) -> None:
    assert validate_code(code) == problem


# ── Placement ────────────────────────────────────────────────────────────────


def test_parent_is_the_most_specific_coarser_code() -> None:
    assert parent_for("331", ["300", "330", "340"]) == "330"
    assert parent_for("330", ["300", "330", "340"]) == "300"
    assert parent_for("300", ["300", "330"]) is None


def test_parent_by_segments_and_by_spaced_groups() -> None:
    assert parent_for("2.6.1", ["2", "2.6", "2.60"]) == "2.6"
    assert parent_for("03 31 00", ["03", "03 30 00", "03 40 00"]) == "03 30 00"


def test_parent_of_an_unrelated_code_is_none() -> None:
    assert parent_for("440", ["300", "330"]) is None


# ── Building a list from rows ────────────────────────────────────────────────


def test_rows_without_parents_nest_by_shape_and_come_out_in_tree_order() -> None:
    entries, issues = build_entries([(2, "331", "a", None), (3, "300", "b", None), (4, "330", "c", None)])
    assert issues == []
    assert [(e.code, e.parent, e.level) for e in entries] == [("300", None, 1), ("330", "300", 2), ("331", "330", 3)]


def test_explicit_parent_wins_over_shape_for_custom_structures() -> None:
    entries, issues = build_entries(
        [(1, "BA1", "Building A", None), (2, "SHELL", "Shell", "BA1"), (3, "ROOF", "Roof", "SHELL")]
    )
    assert issues == []
    assert [(e.code, e.parent, e.level) for e in entries] == [
        ("BA1", None, 1),
        ("SHELL", "BA1", 2),
        ("ROOF", "SHELL", 3),
    ]


def test_every_bad_row_is_reported_against_its_own_row() -> None:
    entries, issues = build_entries(
        [
            (2, "100", "Land", None),
            (3, "100", "Twice", None),
            (4, "", "No code", None),
            (5, "200", "Orphan", "999"),
            (6, "300", "Self", "300"),
        ]
    )
    problems = {(i.row, i.problem) for i in issues}
    assert problems == {(3, "duplicate_code"), (4, "code_missing"), (5, "parent_unknown"), (6, "parent_self")}
    assert [e.code for e in entries] == ["100", "200"]


def test_a_cycle_is_reported_and_kept_out_of_the_tree() -> None:
    entries, issues = build_entries([(1, "A", "", "B"), (2, "B", "", "A"), (3, "C", "", None)])
    assert {(i.code, i.problem) for i in issues} == {("A", "parent_cycle"), ("B", "parent_cycle")}
    assert [e.code for e in entries] == ["C"]


# ── Shipped lists ────────────────────────────────────────────────────────────


def test_the_shipped_lists_are_the_ones_the_picker_carried() -> None:
    cl.reset_cache()
    keys = {c.key for c in cl.builtin_code_lists()}
    assert {"din276", "nrm", "masterformat", "uniformat", "sinapi", "gb50500"} <= keys
    din = get_code_list("din276")
    assert din is not None
    assert len(din.entries) == 83
    assert din.depth == 3
    assert [e.code for e in din.entries if e.level == 1] == ["100", "200", "300", "400", "500", "600", "700", "800"]
    assert din.find("331") is not None and din.find("331").parent == "330"


def test_uniformat_ships_its_top_level_only() -> None:
    uni = get_code_list("uniformat")
    assert uni is not None
    assert uni.depth == 1
    assert [e.code for e in uni.entries][:3] == ["A", "B", "C"]


def test_a_spaced_division_finds_the_division_the_list_spells_short() -> None:
    mf = get_code_list("masterformat")
    assert mf is not None
    assert mf.find("03 00 00") is not None and mf.find("03 00 00").code == "03"
    assert [e.code for e in mf.ancestors("03 30 00")] == ["03"]


# ── Reading uploads ──────────────────────────────────────────────────────────


def test_csv_with_a_header_in_any_column_order() -> None:
    raw = b"title;parent;code\nLand;;100\nValue;100;110\n"
    assert parse_code_list_file("list.csv", raw) == [(2, "100", "Land", ""), (3, "110", "Value", "100")]


def test_csv_without_a_header_is_read_by_position() -> None:
    raw = b"100,Land\n110,Value,100\n"
    assert parse_code_list_file("list.csv", raw) == [(1, "100", "Land", None), (2, "110", "Value", "100")]


def test_csv_with_named_columns_but_no_code_column_is_refused() -> None:
    with pytest.raises(CodeListParseError) as err:
        parse_code_list_file("list.csv", b"title,parent\nLand,\n")
    assert err.value.problem == "missing_code_column"


def test_xlsx_numbers_read_as_codes() -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["code", "title", "parent"])
    ws.append([300, "Building", None])
    ws.append([330, "Walls", 300])
    buf = io.BytesIO()
    wb.save(buf)
    rows = parse_code_list_file("list.xlsx", buf.getvalue())
    assert rows == [(2, "300", "Building", None), (3, "330", "Walls", "300")]


def test_unknown_file_type_is_refused() -> None:
    with pytest.raises(CodeListParseError) as err:
        parse_code_list_file("list.pdf", b"%PDF")
    assert err.value.problem == "unsupported_file_type"
