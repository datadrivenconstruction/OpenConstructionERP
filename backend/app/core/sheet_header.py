# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Find the header row of an uploaded spreadsheet.

Importers used to take row 1 as the header, always. An export that carries
the company letterhead (:mod:`app.core.xlsx_branding`) has the firm's name,
address and the document title above its table, so a workbook exported with
a letterhead and uploaded again would map no column and import nothing,
without an error. These helpers let an importer read such a file back.

The rule, the same for every importer that uses it:

* row 1 is the header when it names two or more known columns, which is what
  a header this platform maps looks like;
* otherwise the first row below it that names two or more is the header,
  within the first :data:`HEADER_SEARCH_ROWS` rows. One known name in row 1
  does not stop the search, because a firm called "Total" or "Title" puts
  exactly one there;
* when no row qualifies, row 1 stays the header as it always was, and the rows
  looked at are handed back as data, so the importer sees what it saw before.

``match`` is the importer's own header matcher, so each importer keeps its own
column names and aliases.

Pure and stdlib-only: rows are whatever ``iter_rows(values_only=True)`` or
``csv.reader`` yields.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from typing import Any, NamedTuple

#: How far down the sheet the header row is looked for. The letterhead puts at
#: most nine rows above a table.
HEADER_SEARCH_ROWS = 15


class HeaderRow(NamedTuple):
    """The located header and the rows under it."""

    #: The header row's values, ``None`` for an empty sheet.
    values: tuple[Any, ...] | None
    #: Its 1-based row number: ``1`` unless a letterhead pushed it down.
    number: int
    #: The rows under the header, top first.
    rows: Iterator[tuple[Any, ...]]


def find_header_row(
    rows_iter: Iterator[tuple[Any, ...]],
    match: Callable[[str], Any],
) -> HeaderRow:
    """Locate the header row, see the module docstring for the rule.

    Args:
        rows_iter: The sheet's rows, top first.
        match: Maps a header cell's text to a truthy value for a known column,
            e.g. the canonical column name, and to a falsy one otherwise.

    Returns:
        The header, its row number, and an iterator over the rows under it.
    """

    def _known(row: tuple[Any, ...]) -> int:
        return sum(1 for value in row if value is not None and match(str(value)))

    first = next(rows_iter, None)
    if first is None or _known(first) >= 2:
        return HeaderRow(first, 1, rows_iter)
    looked_at: list[tuple[Any, ...]] = []
    for row in rows_iter:
        if _known(row) >= 2:
            return HeaderRow(row, len(looked_at) + 2, rows_iter)
        looked_at.append(row)
        if len(looked_at) >= HEADER_SEARCH_ROWS - 1:
            break
    return HeaderRow(first, 1, itertools.chain(looked_at, rows_iter))


def locate_header_row(
    rows_iter: Iterator[tuple[Any, ...]],
    match: Callable[[str], Any],
) -> tuple[tuple[Any, ...] | None, Iterator[tuple[Any, ...]]]:
    """:func:`find_header_row` without the row number: ``(header, rows under it)``."""
    found = find_header_row(rows_iter, match)
    return found.values, found.rows


__all__ = ["HEADER_SEARCH_ROWS", "HeaderRow", "find_header_row", "locate_header_row"]
