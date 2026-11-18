# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read the activity table of a printed schedule PDF into spreadsheet rows.

Subcontractor programmes often arrive as a PDF printed from a planning tool:
a table of ID, name, duration, start, finish and predecessors, usually with a
bar chart to its right. When the PDF keeps its text layer, the table can be
read back without OCR: words are grouped into lines by their vertical
position, a line is cut into cells at wide gaps, the header line is the one
whose cells read as known schedule headers, and every later cell is placed
under the header label it overlaps. The rows go through the same parser as an
Excel or CSV upload (:mod:`app.modules.schedule.tabular_import`), so column
mapping, date order, durations, links and every check are shared.

What is not attempted: scanned pages (no text layer) are refused with a coded
reason pointing to the MS Project XML, XER and Excel imports, and the bar
chart is never read, only the table.

Pure and synchronous; the caller runs it in a worker thread.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from app.core.pdf_reader import PdfReaderError, open_pdf
from app.modules.schedule.tabular_headers import known_header

#: Pages read; a printed programme longer than this is better exported as XML.
MAX_PAGES = 200
#: Lines of a page searched for the header row.
_HEADER_SEARCH_LINES = 25
#: Known header cells a line needs to count as the table header.
_MIN_HEADER_HITS = 2
#: Horizontal snap for indent offsets, in points: glyph side bearings move a
#: tight word box by a point or so, an outline level moves it by ten or more.
_INDENT_SNAP = 3.0
#: Room right of the last header label still read as table, in points.
_RIGHT_MARGIN = 40.0
#: A vertical gap this many times the usual row pitch ends the table on a page.
_TABLE_END_GAP = 3.0

Word = tuple[float, float, float, float, str]


class PdfTableError(Exception):
    """The PDF holds no readable activity table; ``code`` is stable for the UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _Cell:
    x0: float
    x1: float
    text: str


@dataclass
class _Line:
    top: float
    bottom: float
    cells: list[_Cell] = field(default_factory=list)

    @property
    def middle(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class PdfTable:
    """The table as rows of text, header first, with the left offset of each cell."""

    rows: list[tuple[str, ...]]
    indents: list[tuple[float, ...]]
    pages: int


def _lines(words: list[Word]) -> list[_Line]:
    """Words grouped into lines by vertical overlap, then cut into cells at wide gaps."""
    lines: list[tuple[float, float, list[Word]]] = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        middle = (word[1] + word[3]) / 2
        if lines:
            top, bottom, members = lines[-1]
            height = max(bottom - top, word[3] - word[1], 1.0)
            if abs(middle - (top + bottom) / 2) <= height * 0.5:
                members.append(word)
                lines[-1] = (min(top, word[1]), max(bottom, word[3]), members)
                continue
        lines.append((word[1], word[3], [word]))

    out: list[_Line] = []
    for top, bottom, members in lines:
        members.sort(key=lambda w: w[0])
        # Tight glyph boxes: a space between words is about a third of the
        # line height, a column gap well over half of it.
        gap_limit = max(2.0, (bottom - top) * 0.75)
        line = _Line(top, bottom)
        for word in members:
            last = line.cells[-1] if line.cells else None
            if last is not None and word[0] - last.x1 <= gap_limit:
                last.text = f"{last.text} {word[4]}"
                last.x1 = max(last.x1, word[2])
            else:
                line.cells.append(_Cell(word[0], word[2], word[4]))
        out.append(line)
    return out


def _header_index(lines: list[_Line]) -> int | None:
    """The line among the first ones with the most known header cells, at least two."""
    best: tuple[int, int] | None = None
    for index, line in enumerate(lines[:_HEADER_SEARCH_LINES]):
        hits = sum(1 for cell in line.cells if known_header(cell.text))
        if hits >= _MIN_HEADER_HITS and (best is None or hits > best[0]):
            best = (hits, index)
    return best[1] if best else None


def _columns(header: _Line) -> list[_Cell]:
    """Header cells from the first to the last known header; timescale labels to the right are dropped."""
    known = [index for index, cell in enumerate(header.cells) if known_header(cell.text)]
    return header.cells[: known[-1] + 1]


def _column_of(cell: _Cell, columns: list[_Cell]) -> int | None:
    """The column whose header label the cell overlaps most, else the one whose span holds its left edge."""
    best, best_overlap = None, 0.0
    for index, column in enumerate(columns):
        overlap = min(cell.x1, column.x1) - max(cell.x0, column.x0)
        if overlap > best_overlap:
            best, best_overlap = index, overlap
    if best is not None:
        return best
    if cell.x0 > columns[-1].x1 + _RIGHT_MARGIN:
        return None
    for index in range(len(columns) - 1, -1, -1):
        if cell.x0 >= columns[index].x0 - 2.0:
            return index
    return 0


def _pitch(lines: list[_Line]) -> float:
    gaps = [b.middle - a.middle for a, b in zip(lines, lines[1:], strict=False) if b.middle > a.middle]
    return statistics.median(gaps) if gaps else 0.0


def _snap(offsets: list[float]) -> dict[float, float]:
    """Each offset to the smallest offset of its cluster."""
    snapped: dict[float, float] = {}
    anchor: float | None = None
    for value in sorted(set(offsets)):
        if anchor is None or value - anchor > _INDENT_SNAP:
            anchor = value
        snapped[value] = anchor
    return snapped


def read_pdf_table(data: bytes) -> PdfTable:
    """Read the activity table of a text-layer schedule PDF.

    Raises:
        PdfTableError: ``file_unreadable`` when the PDF cannot be opened,
            ``pdf_no_text_layer`` when no page has text (a scan), and
            ``pdf_table_not_found`` when no page has a schedule table header.
    """
    try:
        document = open_pdf(data)
    except PdfReaderError as exc:
        raise PdfTableError("file_unreadable", f"The PDF could not be read: {exc}") from exc
    with document:
        pages = [document[index].words() for index in range(min(document.page_count, MAX_PAGES))]
    if not any(pages):
        raise PdfTableError(
            "pdf_no_text_layer",
            "The PDF has no text layer (it is a scan or an image); import the schedule as MS Project XML, "
            "XER or Excel instead",
        )

    columns: list[_Cell] | None = None
    name_column: int | None = None
    id_column: int | None = None
    body: list[tuple[list[str], list[float]]] = []
    for words in pages:
        lines = _lines(words)
        found = _header_index(lines)
        if found is not None:
            columns = _columns(lines[found])
            fields = [known_header(cell.text) for cell in columns]
            name_column = fields.index("name") if "name" in fields else None
            id_column = fields.index("id") if "id" in fields else None
            lines = lines[found + 1 :]
        if columns is None:
            continue
        pitch = _pitch(lines)
        previous: _Line | None = None
        for line in lines:
            if previous is not None and pitch and line.middle - previous.middle > pitch * _TABLE_END_GAP:
                break
            values = [""] * len(columns)
            lefts = [0.0] * len(columns)
            for cell in line.cells:
                index = _column_of(cell, columns)
                if index is None:
                    continue
                if values[index]:
                    values[index] = f"{values[index]} {cell.text}"
                else:
                    values[index], lefts[index] = cell.text, cell.x0
            filled = [index for index, value in enumerate(values) if value]
            if not filled:
                continue
            previous = line
            # A name wrapped onto a second line carries no id and no dates.
            if (
                filled == [name_column]
                and id_column is not None
                and body
                and body[-1][0][id_column]
                and name_column is not None
            ):
                body[-1][0][name_column] = f"{body[-1][0][name_column]} {values[name_column]}"
                continue
            body.append((values, lefts))

    if columns is None:
        raise PdfTableError(
            "pdf_table_not_found",
            "No page of the PDF has a schedule table header (ID, name, start, finish, duration)",
        )

    snapped = [_snap([lefts[index] for values, lefts in body if values[index]]) for index in range(len(columns))]
    indents: list[tuple[float, ...]] = [tuple(0.0 for _ in columns)]
    for values, lefts in body:
        row: list[float] = []
        for index, value in enumerate(values):
            if not value:
                row.append(0.0)
                continue
            base = min(snapped[index].values())
            row.append(round(snapped[index][lefts[index]] - base, 1))
        indents.append(tuple(row))
    rows = [tuple(cell.text for cell in columns), *(tuple(values) for values, _ in body)]
    return PdfTable(rows=rows, indents=indents, pages=len(pages))
