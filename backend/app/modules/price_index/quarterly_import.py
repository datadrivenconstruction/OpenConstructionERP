# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Import a quarterly published index (year, quarter, value) into one cost-index series.

Many official tender price and construction cost indices are published per
quarter as three columns: year, quarter, index value. This reads that shape from
CSV or from JSON rows and writes it to one :class:`CostIndexSeries`, with the
publisher's attribution on the series. An official index is redistributed under
its publisher's terms, which nearly always ask for credit, so the import refuses
a series without an attribution.

A quarter is stored on the period of its first month (Q1 -> ``YYYY-01``, Q2 ->
``YYYY-04``, Q3 -> ``YYYY-07``, Q4 -> ``YYYY-10``): the series key is a
year-month, and escalation only ever uses the ratio between two periods.

Values that are not a positive number ("-", "Not Available", a provisional
marker the publisher left blank) are skipped and reported, never stored as zero.
A re-import overwrites revised values and adds new quarters.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.price_index.models import CostIndexPoint, CostIndexSeries

MAX_BYTES = 2 * 1024 * 1024
_QUARTER_MONTH = {1: "01", 2: "04", 3: "07", 4: "10"}
_QUARTER_RE = re.compile(r"^\s*Q?\s*([1-4])\s*$", re.IGNORECASE)


class QuarterlyImportError(ValueError):
    """The input cannot be read as a quarterly series; ``problem`` is a stable code."""

    def __init__(self, problem: str, message: str) -> None:
        super().__init__(message)
        self.problem = problem


@dataclass
class QuarterlyImportSummary:
    series_id: str = ""
    created: bool = False
    points_created: int = 0
    points_updated: int = 0
    points_unchanged: int = 0
    skipped: list[str] = field(default_factory=list)


def quarter_period(year: Any, quarter: Any) -> str | None:
    """``"2026-04"`` for (2026, "Q2"); None when either part is unreadable."""
    try:
        y = int(str(year).strip())
    except (TypeError, ValueError):
        return None
    match = _QUARTER_RE.match(str(quarter or ""))
    if not match or not 1000 <= y <= 9999:
        return None
    return f"{y:04d}-{_QUARTER_MONTH[int(match.group(1))]}"


def _value(raw: Any) -> Decimal | None:
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


def _value_key(row: Mapping[str, Any], value_column: str | None) -> str | None:
    if value_column and value_column in row:
        return value_column
    others = [k for k in row if str(k).strip().lower() not in ("year", "quarter")]
    return others[0] if len(others) == 1 else None


def parse_quarterly_rows(
    rows: Iterable[Mapping[str, Any]], value_column: str | None = None
) -> tuple[dict[str, Decimal], list[str]]:
    """``{period: value}`` from rows with ``Year``, ``Quarter`` and one value column.

    The value column is named by ``value_column`` or, when the rows carry exactly
    one column besides year and quarter, taken to be that one.
    """
    points: dict[str, Decimal] = {}
    skipped: list[str] = []
    for row in rows:
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        period = quarter_period(lowered.get("year"), lowered.get("quarter"))
        key = _value_key(row, value_column)
        if period is None or key is None:
            skipped.append(f"unreadable row {dict(row)}")
            continue
        value = _value(row.get(key))
        if value is None:
            skipped.append(f"{period}: {str(row.get(key)).strip()!r}")
            continue
        points[period] = value
    return points, skipped


def parse_quarterly_file(content: bytes, value_column: str | None = None) -> tuple[dict[str, Decimal], list[str]]:
    """Read CSV, a JSON list of rows, or a JSON list wrapping ``{"content": [rows]}``."""
    if len(content) > MAX_BYTES:
        raise QuarterlyImportError("too_large", "The file is larger than 2 MB")
    text = content.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise QuarterlyImportError("empty", "The file is empty")
    rows: list[Mapping[str, Any]]
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QuarterlyImportError("unreadable", f"The file is not valid JSON ({exc.msg})") from exc
        if isinstance(data, dict):
            data = [data]
        rows = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and isinstance(item.get("content"), list):
                rows.extend(r for r in item["content"] if isinstance(r, dict))
            elif isinstance(item, dict):
                rows.append(item)
    else:
        rows = list(csv.DictReader(io.StringIO(text)))
    points, skipped = parse_quarterly_rows(rows, value_column)
    if not points:
        raise QuarterlyImportError("no_values", "No row holds a year, a quarter and a positive index value")
    return points, skipped


async def import_quarterly_series(
    session: AsyncSession,
    *,
    name: str,
    points: Mapping[str, Decimal],
    source_attribution: str,
    source_url: str = "",
    description: str = "",
) -> QuarterlyImportSummary:
    """Create or update the series ``name`` with ``points``. The caller owns the transaction."""
    attribution = (source_attribution or "").strip()
    if not attribution:
        raise QuarterlyImportError("attribution_required", "An imported index needs its source attribution")
    summary = QuarterlyImportSummary()
    series = (await session.execute(select(CostIndexSeries).where(CostIndexSeries.name == name))).scalar_one_or_none()
    if series is None:
        series = CostIndexSeries(name=name, description=description)
        session.add(series)
        summary.created = True
    series.source_attribution = attribution
    series.source_url = (source_url or "").strip()
    if description:
        series.description = description
    await session.flush()
    existing = {
        p.period: p
        for p in (await session.execute(select(CostIndexPoint).where(CostIndexPoint.series_id == series.id))).scalars()
    }
    for period, value in sorted(points.items()):
        point = existing.get(period)
        if point is None:
            session.add(CostIndexPoint(series_id=series.id, period=period, factor=value))
            summary.points_created += 1
        elif Decimal(str(point.factor)) != value:
            point.factor = value
            summary.points_updated += 1
        else:
            summary.points_unchanged += 1
    await session.flush()
    summary.series_id = str(series.id)
    return summary


__all__ = [
    "MAX_BYTES",
    "QuarterlyImportError",
    "QuarterlyImportSummary",
    "import_quarterly_series",
    "parse_quarterly_file",
    "parse_quarterly_rows",
    "quarter_period",
]
