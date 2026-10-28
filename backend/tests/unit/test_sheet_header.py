# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The shared header-row locator the spreadsheet importers use.

Pure: rows are tuples, the matcher is a small alias table, no workbook needed.
"""

from __future__ import annotations

from typing import Any

from app.core.sheet_header import HEADER_SEARCH_ROWS, find_header_row, locate_header_row

_KNOWN = {"code": "code", "description": "description", "unit": "unit", "total": "total"}


def _match(text: str) -> str | None:
    return _KNOWN.get(text.strip().lower())


def _find(rows: list[tuple[Any, ...]]) -> tuple[tuple[Any, ...] | None, int, list[tuple[Any, ...]]]:
    found = find_header_row(iter(rows), _match)
    return found.values, found.number, list(found.rows)


_HEADER = ("Code", "Description", "Unit")
_DATA = [("01", "Excavation", "m3"), ("02", "Backfill", "m3")]


def test_row_one_is_the_header_when_it_names_known_columns() -> None:
    assert _find([_HEADER, *_DATA]) == (_HEADER, 1, _DATA)


def test_an_empty_sheet_has_no_header() -> None:
    assert _find([]) == (None, 1, [])


def test_a_letterhead_above_the_table_is_skipped() -> None:
    letterhead = [("Acme Construction GmbH",), ("Hauptstrasse 1",), ("+49 30 1",), ("Tender BOQ",), (None,)]

    assert _find([*letterhead, _HEADER, *_DATA]) == (_HEADER, 6, _DATA)


def test_one_known_name_in_row_one_does_not_stop_the_search() -> None:
    # A firm called "Total" names exactly one known column in row 1.
    assert _find([("Total",), ("Tender BOQ",), _HEADER, *_DATA]) == (_HEADER, 3, _DATA)


def test_without_a_better_row_below_row_one_stays_the_header_and_nothing_is_lost() -> None:
    rows = [("Code", "Notes"), ("01", "x"), ("02", "y")]

    assert _find(rows) == (("Code", "Notes"), 1, rows[1:])


def test_the_search_stops_after_the_first_rows() -> None:
    filler = [(f"line {n}",) for n in range(HEADER_SEARCH_ROWS - 1)]

    # Header at the last row looked at: found.
    assert _find([*filler, _HEADER, *_DATA]) == (_HEADER, HEADER_SEARCH_ROWS, _DATA)
    # One row further down: row 1 stays the header, every other row is data.
    late = [*filler, ("one more",), _HEADER, *_DATA]
    assert _find(late) == (late[0], 1, late[1:])


def test_empty_cells_are_not_offered_to_the_matcher() -> None:
    seen: list[str] = []

    def _recording(text: str) -> str | None:
        seen.append(text)
        return _match(text)

    list(find_header_row(iter([(None, "Code", None, "Unit"), ("01", "m3")]), _recording).rows)

    assert seen == ["Code", "Unit"]


def test_locate_header_row_is_find_header_row_without_the_number() -> None:
    rows = [("Acme",), _HEADER, *_DATA]
    header, rest = locate_header_row(iter(rows), _match)

    assert (header, list(rest)) == (_HEADER, _DATA)
