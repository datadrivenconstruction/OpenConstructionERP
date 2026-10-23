# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Import of Statistics South Africa release P0151.1, Table 1, into cost-index series.

P0151.1 "Construction Material Price Indices" publishes, each month, one
material price index per work group of the contract price adjustment
provisions (CPAP). Table 1 lists the work groups as rows (a numeric work
group code and its description) and the months as columns. The Haylett
formula (regime ``za_cpap_haylett``) reads its ``M`` term from these.

The user uploads the release as Stats SA distributes it (``.xlsx`` or
``.csv``); nothing is fetched from the network. Each work group becomes one
cost-index series named ``ZA P0151.1 WG<code> <description>``, whose
description carries the Stats SA acknowledgement. A re-import of a later
release adds the new months and overwrites revised values, because Stats SA
publishes preliminary figures that are revised later.

The parser does not know the work group list or any index value: it reads
whatever the file holds, so a new or renamed work group needs no code change.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.price_index.models import CostIndexPoint, CostIndexSeries

SERIES_PREFIX = "ZA P0151.1 WG"
ACKNOWLEDGEMENT = (
    "Source: Statistics South Africa, statistical release P0151.1 Construction Material Price Indices, "
    "Table 1 (CPAP work group indices). Reproduced with acknowledgement of Stats SA."
)
MAX_BYTES = 5 * 1024 * 1024

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
_CODE = re.compile(r"^(?:wg\s*)?(\d{2,4})(?:\s*[-:.]?\s*(.*))?$", re.IGNORECASE)


class P0151ImportError(ValueError):
    """The file cannot be read as P0151.1 Table 1. ``problem`` names why."""

    def __init__(self, problem: str, message: str) -> None:
        self.problem = problem
        super().__init__(message)


@dataclass
class WorkGroupRow:
    """One work group of Table 1 with its monthly indices."""

    code: str
    description: str
    points: dict[str, Decimal] = field(default_factory=dict)

    @property
    def series_name(self) -> str:
        return f"{SERIES_PREFIX}{self.code} {self.description}".strip()[:255]


@dataclass
class P0151Table:
    """Table 1 as read, plus the cells skipped and why."""

    work_groups: list[WorkGroupRow]
    skipped: list[str] = field(default_factory=list)


def parse_period(cell: Any) -> str | None:
    """A month header as ``YYYY-MM``, or ``None`` when the cell is not a month."""
    if isinstance(cell, datetime | date):
        return f"{cell.year:04d}-{cell.month:02d}"
    text = str(cell or "").strip().lower().replace(" ", " ")
    if not text:
        return None
    m = re.fullmatch(r"(\d{4})\s*[-/.]\s*(\d{1,2})(?:[-/.]\d{1,2})?(?:\s.*)?", text)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"([a-z]+)\.?[\s\-/']*(\d{2}|\d{4})", text) or re.fullmatch(r"(\d{4})[\s\-/]*([a-z]+)\.?", text)
    if not m:
        return None
    word, year = (m.group(1), m.group(2)) if m.group(1).isalpha() else (m.group(2), m.group(1))
    month = _MONTHS.get(word)
    if month is None:
        return None
    y = int(year)
    if y < 100:
        y += 2000
    return f"{y:04d}-{month:02d}"


def _value(cell: Any) -> Decimal | None:
    if cell is None or isinstance(cell, bool):
        return None
    text = str(cell).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _rows(content: bytes, filename: str) -> list[list[Any]]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook  # noqa: PLC0415

        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # openpyxl raises many types on a damaged file
            raise P0151ImportError("unreadable_file", f"cannot open workbook: {exc}") from exc
        sheet = next((ws for ws in wb.worksheets if "1" in ws.title), None) or wb.worksheets[0]
        return [list(r) for r in sheet.iter_rows(values_only=True)]
    if name.endswith((".csv", ".txt")):
        text = content.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
        return [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    raise P0151ImportError("unsupported_format", "upload the release as .xlsx or .csv")


def parse_p0151_table1(content: bytes, filename: str) -> P0151Table:
    """Read Table 1 of a P0151.1 release.

    The header row is the first row with at least one month cell; the work
    group rows are the rows below it whose first non-empty cell is a work
    group code. Empty, non-numeric (``..``) and non-positive cells are skipped
    and reported, never guessed.

    Raises:
        P0151ImportError: The file is too large, unreadable, has no month
            header or no work group row.
    """
    if len(content) > MAX_BYTES:
        raise P0151ImportError("file_too_large", f"file is larger than {MAX_BYTES} bytes")
    rows = _rows(content, filename)
    header_index, periods = -1, {}
    for i, row in enumerate(rows):
        found = {j: p for j, cell in enumerate(row) if (p := parse_period(cell))}
        if found:
            header_index, periods = i, found
            break
    if header_index < 0:
        raise P0151ImportError("no_month_header", "no row with month headings was found")
    groups: dict[str, WorkGroupRow] = {}
    skipped: list[str] = []
    first_period_col = min(periods)
    for row in rows[header_index + 1 :]:
        cells = [(j, c) for j, c in enumerate(row[:first_period_col]) if str(c or "").strip()]
        if not cells:
            continue
        m = _CODE.match(str(cells[0][1]).strip().removesuffix(".0"))
        if not m:
            continue
        code = m.group(1)
        description = (m.group(2) or "").strip() or " ".join(str(c).strip() for _, c in cells[1:])
        group = groups.setdefault(code, WorkGroupRow(code=code, description=description))
        for j, period in periods.items():
            raw = row[j] if j < len(row) else None
            value = _value(raw)
            if value is None or value <= 0:
                if str(raw or "").strip():
                    skipped.append(f"WG{code} {period}: {str(raw).strip()!r}")
                continue
            group.points[period] = value
    work_groups = [g for g in groups.values() if g.points]
    if not work_groups:
        raise P0151ImportError("no_work_groups", "no work group row with index values was found")
    return P0151Table(work_groups=work_groups, skipped=skipped)


@dataclass
class P0151ImportSummary:
    series_created: int = 0
    points_created: int = 0
    points_updated: int = 0
    points_unchanged: int = 0
    skipped: list[str] = field(default_factory=list)
    series: list[str] = field(default_factory=list)


async def import_p0151_table(session: AsyncSession, table: P0151Table) -> P0151ImportSummary:
    """Create or extend one cost-index series per work group. The caller commits."""
    summary = P0151ImportSummary(skipped=list(table.skipped))
    for group in table.work_groups:
        series = (
            await session.execute(select(CostIndexSeries).where(CostIndexSeries.name == group.series_name))
        ).scalar_one_or_none()
        if series is None:
            series = CostIndexSeries(name=group.series_name, description=ACKNOWLEDGEMENT)
            session.add(series)
            await session.flush()
            summary.series_created += 1
            existing: dict[str, CostIndexPoint] = {}
        else:
            if ACKNOWLEDGEMENT not in (series.description or ""):
                series.description = f"{series.description}\n{ACKNOWLEDGEMENT}".strip()
            points = await session.execute(select(CostIndexPoint).where(CostIndexPoint.series_id == series.id))
            existing = {p.period: p for p in points.scalars()}
        for period, value in sorted(group.points.items()):
            point = existing.get(period)
            if point is None:
                session.add(CostIndexPoint(series_id=series.id, period=period, factor=value))
                summary.points_created += 1
            elif Decimal(str(point.factor)) != value:
                point.factor = value
                summary.points_updated += 1
            else:
                summary.points_unchanged += 1
        summary.series.append(group.series_name)
    await session.flush()
    return summary
