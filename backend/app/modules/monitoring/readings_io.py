# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reading monitoring readings from CSV/TXT (no database).

One header row names the columns: a point id, a date, and any of E, N, Z or a
value (metres). The delimiter is detected, a decimal comma is accepted, dates
are ISO (``2026-10-09``, with an optional time) or ``09.10.2026``. A bad row is
reported with its line number and the rest of the file still reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.modules.survey_core.point_io import detect_delimiter, split_line

MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_ROWS = 100_000
_FOUR = Decimal("0.0001")
_LIMIT = Decimal("1000000000")

_HEADER_WORDS: dict[str, tuple[str, ...]] = {
    "point": ("point", "pointid", "point_id", "id", "name", "pt", "code"),
    "date": ("date", "epoch", "observedat", "observed_at", "time", "datetime", "observed"),
    "e": ("e", "east", "easting"),
    "n": ("n", "north", "northing"),
    "z": ("z", "h", "height", "elev", "elevation", "level"),
    "value": ("value", "v", "reading", "length"),
}
_DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y")


@dataclass
class ParsedReading:
    """One reading of one point at one time."""

    line: int
    point: str
    at: datetime
    e: Decimal | None = None
    n: Decimal | None = None
    z: Decimal | None = None
    value: Decimal | None = None


@dataclass
class Problem:
    """Something wrong with a row."""

    line: int
    point_id: str
    message: str


@dataclass
class ParseResult:
    """The readings read, every problem found, and how many data rows the file had."""

    rows_read: int = 0
    readings: list[ParsedReading] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def _field(cell: str) -> str | None:
    word = re.sub(r"[^a-z0-9_]", "", cell.strip().casefold().lstrip("﻿"))
    return next((name for name, words in _HEADER_WORDS.items() if word in words), None)


def parse_decimal(raw: str) -> Decimal | None:
    """A finite metre value to 0.0001, accepting a decimal comma; None when blank or not a number."""
    s = raw.strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    if not value.is_finite() or abs(value) >= _LIMIT:
        return None
    return value.quantize(_FOUR, rounding=ROUND_HALF_UP)


def parse_when(raw: str) -> datetime | None:
    """A date or date-time as UTC; None when it is neither."""
    s = raw.strip()
    if not s:
        return None
    try:
        parsed = datetime.fromisoformat(s)
    except ValueError:
        parsed = None
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(s, fmt)  # noqa: DTZ007 - made aware below
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def parse_readings(text: str) -> ParseResult:
    """Read a readings file; the first non-blank line must be the header."""
    if len(text.encode("utf-8", errors="ignore")) > MAX_TEXT_BYTES:
        raise ValueError("file larger than 5 MB")
    result = ParseResult()
    lines = [(i + 1, ln) for i, ln in enumerate(text.lstrip("﻿").splitlines()) if ln.strip() and not ln.startswith("#")]
    if not lines:
        result.problems.append(Problem(1, "", "The file is empty."))
        return result
    delimiter, _ = detect_delimiter(text)
    header_line, header_text = lines[0]
    columns = [_field(c) for c in split_line(header_text, delimiter)]
    for needed, label in (("point", "a point id"), ("date", "a date")):
        if needed not in columns:
            result.problems.append(Problem(header_line, "", f"The header has no column for {label}."))
    if not any(c in columns for c in ("e", "n", "z", "value")):
        result.problems.append(Problem(header_line, "", "The header has no E, N, Z or value column."))
    if result.problems:
        return result
    seen: set[tuple[str, datetime]] = set()
    for number, raw in lines[1 : MAX_ROWS + 1]:
        result.rows_read += 1
        cells = split_line(raw, delimiter)
        row = {name: cells[i] for i, name in enumerate(columns) if name and i < len(cells)}
        point = row.get("point", "").strip()
        if not point or len(point) > 64:
            result.problems.append(Problem(number, point[:64], "The point id is empty or longer than 64 characters."))
            continue
        at = parse_when(row.get("date", ""))
        if at is None:
            result.problems.append(Problem(number, point, f"'{row.get('date', '')}' is not a date."))
            continue
        numbers: dict[str, Decimal | None] = {}
        bad = ""
        for name in ("e", "n", "z", "value"):
            text_value = row.get(name, "")
            numbers[name] = parse_decimal(text_value)
            if text_value.strip() and numbers[name] is None:
                bad = name.upper()
        if bad:
            result.problems.append(Problem(number, point, f"Column {bad} is not a number."))
            continue
        if all(v is None for v in numbers.values()):
            result.problems.append(Problem(number, point, "The row has no E, N, Z or value."))
            continue
        if (point, at) in seen:
            result.problems.append(Problem(number, point, "The same point and date appear twice in the file."))
            continue
        seen.add((point, at))
        result.readings.append(ParsedReading(number, point, at, **numbers))
    if len(lines) - 1 > MAX_ROWS:
        result.problems.append(Problem(0, "", f"Only the first {MAX_ROWS} rows were read."))
    return result
