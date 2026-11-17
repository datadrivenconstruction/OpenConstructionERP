# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable Gantt chart: activity table, timescale, bars, baseline and legend.

A document for use outside the platform, drawn as vectors, not a screenshot.
Every sheet repeats the activity table (WBS, name, start, finish, days) beside
a two-tier timescale. Each row shows the current plan bar (red when critical,
filled to its progress), the baseline bar under it, the actual bar over it, a
diamond for a milestone and a bracket for a summary. A dashed line marks the
data date.

Pagination is predictable: the scale is the finest of day / week / month /
quarter that fits the whole date range on at most :data:`MAX_SHEETS_WIDE`
sheets; only the quarter scale paginates further. Rows split into bands of
whole rows. Sheets run band by band, each band through every time slice, so
no row and no day is clipped.

Labels are ``document_forms.gantt_pdf.strings`` in ``backend/locales``; dates
print as ISO 8601, which reads the same in every market.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

from app.core import pdf_fonts
from app.core.document_forms_i18n import form_strings
from app.core.paper_size import PAPER_SIZES
from app.core.pdf_rtl import visual_text

__all__ = [
    "MAX_SHEETS_WIDE",
    "GanttMeta",
    "GanttRow",
    "Scale",
    "Sheet",
    "build_rows",
    "choose_scale",
    "labels_for",
    "pdf_locales",
    "plan_sheets",
    "render_gantt_pdf",
]

FORM = "gantt_pdf"
MAX_SHEETS_WIDE = 2

#: (unit, points per calendar day), finest first.
_SCALES: tuple[tuple[str, float], ...] = (("day", 14.0), ("week", 3.0), ("month", 0.9), ("quarter", 0.32))
_MILESTONE_TYPES = frozenset({"milestone", "start_milestone", "finish_milestone"})
_SUMMARY_TYPES = frozenset({"summary", "wbs", "hammock"})

_MARGIN = 24.0
_HEADER_H = 40.0
_FOOTER_H = 26.0
_SCALE_H = 24.0
_ROW_H = 14.0
_COLS_A3 = (
    ("col_wbs", 48.0),
    ("col_activity", 190.0),
    ("col_start", 54.0),
    ("col_finish", 54.0),
    ("col_duration", 30.0),
)
_COLS_SMALL = (
    ("col_wbs", 40.0),
    ("col_activity", 130.0),
    ("col_start", 52.0),
    ("col_finish", 52.0),
    ("col_duration", 26.0),
)

_BLUE = colors.HexColor("#3b82f6")
_BLUE_DARK = colors.HexColor("#1d4ed8")
_RED = colors.HexColor("#dc2626")
_RED_DARK = colors.HexColor("#991b1b")
_GREY = colors.HexColor("#9ca3af")
_GREEN = colors.HexColor("#16a34a")
_ORANGE = colors.HexColor("#f59e0b")
_GRID = colors.HexColor("#e5e7eb")
_ZEBRA = colors.HexColor("#f9fafb")
_INK = colors.HexColor("#111827")
_MUTED = colors.HexColor("#6b7280")


# -- data ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GanttRow:
    """One printed row."""

    key: str
    wbs: str
    name: str
    level: int
    start: date | None
    end: date | None
    duration_days: int | None = None
    baseline_start: date | None = None
    baseline_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    progress: float = 0.0
    critical: bool = False
    milestone: bool = False
    summary: bool = False


@dataclass(frozen=True)
class GanttMeta:
    """What the sheet header says."""

    project_name: str
    schedule_name: str
    baseline_label: str | None
    exported_on: date
    data_date: date | None = None


@dataclass(frozen=True)
class Scale:
    """A timescale: its unit and its width per calendar day."""

    unit: str
    pt_per_day: float


@dataclass(frozen=True)
class Sheet:
    """One page: a band of rows ``[row_start, row_end)`` and days ``day_start..day_end`` inclusive."""

    row_start: int
    row_end: int
    day_start: date
    day_end: date


def _day(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _float(value: Any) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_rows(activities: list[dict[str, Any]], baseline: dict[str, Any] | None) -> list[GanttRow]:
    """Order activities as an outline (parents before children, by sort order) and attach baseline dates.

    Baseline rows match by activity id, else by WBS code, so a baseline captured
    from an import with other ids still lines up. A parent that is missing, or
    a parent cycle, puts the row at the top level rather than losing it.
    """
    by_id = {str(a.get("id")): a for a in activities}
    children: dict[str | None, list[dict[str, Any]]] = {}
    for act in activities:
        parent = str(act.get("parent_id")) if act.get("parent_id") else None
        if parent not in by_id or parent == str(act.get("id")):
            parent = None
        children.setdefault(parent, []).append(act)

    def order(a: dict[str, Any]) -> tuple[int, str, str]:
        return (_int(a.get("sort_order")) or 0, str(a.get("wbs_code") or ""), str(a.get("name") or ""))

    base_by_id: dict[str, dict[str, Any]] = {}
    base_by_wbs: dict[str, dict[str, Any]] = {}
    for row in (baseline or {}).get("activities") or []:
        if isinstance(row, dict):
            if row.get("id"):
                base_by_id[str(row["id"])] = row
            if row.get("wbs_code"):
                base_by_wbs.setdefault(str(row["wbs_code"]), row)

    out: list[GanttRow] = []
    seen: set[str] = set()

    def visit(act: dict[str, Any], level: int) -> None:
        key = str(act.get("id"))
        if key in seen:
            return
        seen.add(key)
        wbs = str(act.get("wbs_code") or "")
        base = base_by_id.get(key) or (base_by_wbs.get(wbs) if wbs else None) or {}
        kind = str(act.get("activity_type") or "task").lower()
        out.append(
            GanttRow(
                key=key,
                wbs=wbs,
                name=str(act.get("name") or ""),
                level=level,
                start=_day(act.get("start_date")),
                end=_day(act.get("end_date")),
                duration_days=_int(act.get("duration_days")),
                baseline_start=_day(base.get("start_date")),
                baseline_end=_day(base.get("end_date")),
                actual_start=_day(act.get("actual_start")),
                actual_end=_day(act.get("actual_end") or act.get("actual_finish")),
                progress=_float(act.get("progress_pct")),
                critical=bool(act.get("is_critical")),
                milestone=kind in _MILESTONE_TYPES,
                summary=kind in _SUMMARY_TYPES,
            )
        )
        for child in sorted(children.get(key, []), key=order):
            visit(child, level + 1)

    for root in sorted(children.get(None, []), key=order):
        visit(root, 0)
    # Rows only reachable through a parent cycle.
    for act in sorted(activities, key=order):
        visit(act, 0)
    return out


def choose_scale(span_days: int, chart_width: float) -> Scale:
    """The finest scale that fits ``span_days`` on at most :data:`MAX_SHEETS_WIDE` sheets."""
    budget = chart_width * MAX_SHEETS_WIDE
    for unit, ppd in _SCALES:
        if span_days * ppd <= budget:
            return Scale(unit, ppd)
    unit, ppd = _SCALES[-1]
    return Scale(unit, ppd)


def plan_sheets(row_count: int, rows_per_sheet: int, start: date, end: date, days_per_sheet: int) -> list[Sheet]:
    """Split rows into bands and days into slices; every band runs through every slice."""
    rows_per_sheet = max(1, rows_per_sheet)
    days_per_sheet = max(1, days_per_sheet)
    total_days = (end - start).days + 1
    slices = [
        (start + timedelta(days=d), start + timedelta(days=min(d + days_per_sheet, total_days) - 1))
        for d in range(0, max(total_days, 1), days_per_sheet)
    ]
    return [
        Sheet(r, min(r + rows_per_sheet, row_count), s, e)
        for r in range(0, max(row_count, 1), rows_per_sheet)
        for s, e in slices
    ]


# -- labels -------------------------------------------------------------------------


@cache
def _catalogue() -> dict[str, dict[str, str]]:
    return form_strings(FORM)


def pdf_locales() -> tuple[str, ...]:
    """Languages the printed Gantt is translated into."""
    return tuple(_catalogue())


def labels_for(locale: str) -> dict[str, str]:
    """The label table for ``locale``, English when it is not translated."""
    table = _catalogue()
    return table.get(locale) or table["en"]


# -- drawing ------------------------------------------------------------------------


def _fit(text: str, width: float, size: float, bold: bool) -> str:
    if pdf_fonts.pdf_text_width(text, size, bold=bold) <= width:
        return text
    while text and pdf_fonts.pdf_text_width(text + "…", size, bold=bold) > width:
        text = text[:-1]
    return text + "…" if text else ""


def _put(
    c: Any,
    x: float,
    y: float,
    text: str,
    size: float,
    *,
    bold: bool = False,
    width: float | None = None,
    align: str = "left",
    color: Any = _INK,
) -> None:
    """Draw one line, run by run in faces that carry its glyphs; RTL is shaped by the canvas hooks."""
    text = str(text or "")
    if not text:
        return
    if width is not None:
        text = _fit(text, width, size, bold)
    total = pdf_fonts.pdf_text_width(text, size, bold=bold)
    if align == "right":
        x -= total
    elif align == "center":
        x -= total / 2
    c.setFillColor(color)
    for face, chunk in pdf_fonts.pdf_font_runs(text, bold=bold):
        c.setFont(face, size)
        c.drawString(x, y, chunk)
        x += stringWidth(visual_text(chunk, face=face), face, size)


def _bounds(rows: list[GanttRow], data_date: date | None, fallback: date) -> tuple[date, date]:
    days: list[date] = []
    for r in rows:
        days += [d for d in (r.start, r.end, r.baseline_start, r.baseline_end, r.actual_start, r.actual_end) if d]
    if not days:
        return fallback, fallback
    lo, hi = min(days), max(days)
    if data_date and lo <= data_date <= hi + timedelta(days=31):
        hi = max(hi, data_date)
    return lo, hi


def _snap(lo: date, hi: date, unit: str) -> tuple[date, date]:
    """Widen the range to whole units so the timescale starts and ends on a boundary."""
    if unit == "week":
        lo -= timedelta(days=lo.weekday())
        hi += timedelta(days=6 - hi.weekday())
    elif unit in ("month", "quarter"):
        first_month = lo.month if unit == "month" else 3 * ((lo.month - 1) // 3) + 1
        lo = date(lo.year, first_month, 1)
        last_month = hi.month if unit == "month" else 3 * ((hi.month - 1) // 3) + 3
        nxt = date(hi.year + (last_month == 12), (last_month % 12) + 1, 1)
        hi = nxt - timedelta(days=1)
    return lo, hi


def _ticks(
    start: date, end: date, unit: str, labels: dict[str, str]
) -> tuple[list[tuple[date, str]], list[tuple[date, str]]]:
    """(major, minor) ticks: each a day where a cell starts and its label."""
    major: list[tuple[date, str]] = []
    minor: list[tuple[date, str]] = []
    d = start
    while d <= end:
        if unit == "day":
            minor.append((d, str(d.day)))
            if d == start or d.day == 1:
                major.append((d, f"{d.year}-{d.month:02d}"))
        elif unit == "week":
            if d == start or d.weekday() == 0:
                minor.append((d, labels["week_short"].format(n=d.isocalendar()[1])))
            if d == start or d.day == 1:
                major.append((d, f"{d.year}-{d.month:02d}"))
        elif unit == "month":
            if d == start or d.day == 1:
                minor.append((d, f"{d.month:02d}"))
            if d == start or (d.day == 1 and d.month == 1):
                major.append((d, str(d.year)))
        else:
            if d == start or (d.day == 1 and d.month in (1, 4, 7, 10)):
                minor.append((d, labels["quarter_short"].format(n=(d.month - 1) // 3 + 1)))
            if d == start or (d.day == 1 and d.month == 1):
                major.append((d, str(d.year)))
        d += timedelta(days=1)
    return major, minor


def _paper(paper: str) -> tuple[float, float]:
    return landscape(PAPER_SIZES.get(paper.upper(), PAPER_SIZES["A3"]))


def render_gantt_pdf(rows: list[GanttRow], meta: GanttMeta, *, paper: str = "A3", locale: str = "en") -> bytes:
    """Render the Gantt chart as a landscape PDF on ``paper`` (A3, A4, LETTER or LEGAL)."""
    pdf_fonts.register_pdf_fonts()
    labels = labels_for(locale)
    page_w, page_h = _paper(paper)
    cols = _COLS_A3 if page_w >= 1000 else _COLS_SMALL
    table_w = sum(w for _, w in cols)
    chart_x = _MARGIN + table_w
    chart_w = page_w - _MARGIN - chart_x
    grid_top = page_h - _MARGIN - _HEADER_H - _SCALE_H
    grid_bottom = _MARGIN + _FOOTER_H
    rows_per_sheet = max(1, int((grid_top - grid_bottom) // _ROW_H))

    data_date = meta.data_date or meta.exported_on
    lo, hi = _bounds(rows, data_date, meta.exported_on)
    scale = choose_scale((hi - lo).days + 1, chart_w)
    lo, hi = _snap(lo, hi, scale.unit)
    days_per_sheet = max(1, math.floor(chart_w / scale.pt_per_day))
    if scale.unit == "week":
        days_per_sheet = max(7, days_per_sheet - days_per_sheet % 7)
    sheets = plan_sheets(len(rows), rows_per_sheet, lo, hi, days_per_sheet)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
    title = f"{labels['title']} - {meta.schedule_name}"
    c.setTitle(title)
    c.setAuthor(meta.project_name)

    for index, sheet in enumerate(sheets, start=1):
        _header(c, meta, labels, page_w, page_h)
        _table_head(c, cols, labels, grid_top)
        x_of = _x_mapper(chart_x, sheet.day_start, scale.pt_per_day)
        sheet_right = x_of(sheet.day_end + timedelta(days=1))
        major, minor = _ticks(sheet.day_start, sheet.day_end, scale.unit, labels)
        _timescale(c, major, minor, x_of, sheet_right, grid_top)
        band = rows[sheet.row_start : sheet.row_end]
        band_bottom = grid_top - max(len(band), 1) * _ROW_H
        for tick, _ in minor:
            c.setStrokeColor(_GRID)
            c.setLineWidth(0.3)
            c.line(x_of(tick), grid_top, x_of(tick), band_bottom)
        for offset, row in enumerate(band):
            y = grid_top - (offset + 1) * _ROW_H
            if offset % 2:
                c.setFillColor(_ZEBRA)
                c.rect(_MARGIN, y, sheet_right - _MARGIN, _ROW_H, stroke=0, fill=1)
            _row_cells(c, cols, row, y)
            _row_bars(c, row, y, x_of, sheet, data_date)
        if not rows:
            _put(c, _MARGIN + 4, grid_top - _ROW_H + 4, labels["no_activities"], 9, color=_MUTED)
        if sheet.day_start <= data_date <= sheet.day_end:
            c.setStrokeColor(_ORANGE)
            c.setLineWidth(0.8)
            c.setDash(3, 2)
            c.line(x_of(data_date), grid_top, x_of(data_date), band_bottom)
            c.setDash()
        c.setStrokeColor(_MUTED)
        c.setLineWidth(0.5)
        c.line(chart_x, grid_top + _SCALE_H, chart_x, band_bottom)
        c.rect(_MARGIN, band_bottom, sheet_right - _MARGIN, grid_top + _SCALE_H - band_bottom, stroke=1, fill=0)
        _legend(c, labels, page_w, index, len(sheets))
        c.showPage()
    c.save()
    return buf.getvalue()


def _x_mapper(chart_x: float, origin: date, ppd: float) -> Any:
    def x_of(day: date) -> float:
        return chart_x + (day - origin).days * ppd

    return x_of


def _header(c: Any, meta: GanttMeta, labels: dict[str, str], page_w: float, page_h: float) -> None:
    top = page_h - _MARGIN
    _put(c, _MARGIN, top - 14, labels["title"], 14, bold=True, width=page_w / 2)
    _put(
        c,
        page_w - _MARGIN,
        top - 12,
        f"{labels['exported']}: {meta.exported_on.isoformat()}",
        8,
        align="right",
        color=_MUTED,
    )
    parts = [
        f"{labels['project']}: {meta.project_name}",
        f"{labels['schedule']}: {meta.schedule_name}",
        f"{labels['baseline']}: {meta.baseline_label or labels['no_baseline']}",
        f"{labels['data_date']}: {(meta.data_date or meta.exported_on).isoformat()}",
    ]
    _put(c, _MARGIN, top - 30, "   |   ".join(parts), 9, width=page_w - 2 * _MARGIN)


def _table_head(c: Any, cols: tuple[tuple[str, float], ...], labels: dict[str, str], grid_top: float) -> None:
    c.setFillColor(colors.HexColor("#f3f4f6"))
    c.rect(_MARGIN, grid_top, sum(w for _, w in cols), _SCALE_H, stroke=0, fill=1)
    x = _MARGIN
    for key, width in cols:
        _put(c, x + 3, grid_top + 8, labels[key], 7.5, bold=True, width=width - 5)
        x += width


def _timescale(c: Any, major: list, minor: list, x_of: Any, right: float, grid_top: float) -> None:
    mid = grid_top + _SCALE_H / 2
    c.setStrokeColor(_GRID)
    c.setLineWidth(0.5)
    c.line(x_of(minor[0][0]) if minor else right, mid, right, mid)
    c.line(x_of(minor[0][0]) if minor else right, grid_top, right, grid_top)
    for ticks, base in ((major, mid), (minor, grid_top)):
        for i, (day, text) in enumerate(ticks):
            x = x_of(day)
            nxt = x_of(ticks[i + 1][0]) if i + 1 < len(ticks) else right
            c.setStrokeColor(_GRID)
            c.line(x, base, x, base + _SCALE_H / 2)
            if nxt - x >= 8:
                _put(c, x + 2, base + 3.5, text, 6.5, width=nxt - x - 3, color=_MUTED)


def _row_cells(c: Any, cols: tuple[tuple[str, float], ...], row: GanttRow, y: float) -> None:
    widths = dict(cols)
    x = _MARGIN
    base = y + 4
    size = 7.0
    _put(c, x + 3, base, row.wbs, size, width=widths["col_wbs"] - 5)
    x += widths["col_wbs"]
    indent = min(row.level, 6) * 6.0
    _put(c, x + 3 + indent, base, row.name, size, bold=row.summary, width=widths["col_activity"] - 5 - indent)
    x += widths["col_activity"]
    _put(c, x + 3, base, row.start.isoformat() if row.start else "", size, width=widths["col_start"] - 5)
    x += widths["col_start"]
    _put(c, x + 3, base, row.end.isoformat() if row.end else "", size, width=widths["col_finish"] - 5)
    x += widths["col_finish"]
    days = row.duration_days
    if days is None and row.start and row.end:
        days = 0 if row.milestone else (row.end - row.start).days + 1
    _put(c, x + widths["col_duration"] - 3, base, "" if days is None else str(days), size, align="right")


def _span(start: date | None, end: date | None, sheet: Sheet, x_of: Any) -> tuple[float, float] | None:
    """The drawn part of ``start..end`` (inclusive) on this sheet, or ``None`` when outside it."""
    if start is None:
        return None
    end = end if end and end >= start else start
    if end < sheet.day_start or start > sheet.day_end:
        return None
    a = max(start, sheet.day_start)
    b = min(end, sheet.day_end) + timedelta(days=1)
    return x_of(a), x_of(b)


def _diamond(c: Any, x: float, y: float, r: float, fill: Any, *, hollow: bool = False) -> None:
    path = c.beginPath()
    path.moveTo(x, y + r)
    path.lineTo(x + r, y)
    path.lineTo(x, y - r)
    path.lineTo(x - r, y)
    path.close()
    c.setStrokeColor(fill)
    c.setFillColor(fill)
    c.drawPath(path, stroke=1, fill=0 if hollow else 1)


def _row_bars(c: Any, row: GanttRow, y: float, x_of: Any, sheet: Sheet, data_date: date) -> None:
    # Baseline: thin grey bar at the bottom of the row.
    if row.baseline_start:
        if row.milestone:
            if sheet.day_start <= row.baseline_start <= sheet.day_end:
                _diamond(c, x_of(row.baseline_start), y + 4, 2.6, _GREY, hollow=True)
        elif span := _span(row.baseline_start, row.baseline_end, sheet, x_of):
            c.setFillColor(_GREY)
            c.rect(span[0], y + 1.5, max(span[1] - span[0], 0.8), 2.5, stroke=0, fill=1)
    # Current plan.
    if row.milestone:
        if row.start and sheet.day_start <= row.start <= sheet.day_end:
            _diamond(c, x_of(row.start), y + 8, 3.6, _RED if row.critical else _INK)
    elif row.summary:
        if span := _span(row.start, row.end, sheet, x_of):
            c.setFillColor(_INK)
            c.rect(span[0], y + 8, max(span[1] - span[0], 0.8), 3, stroke=0, fill=1)
    elif span := _span(row.start, row.end, sheet, x_of):
        fill, done = (_RED, _RED_DARK) if row.critical else (_BLUE, _BLUE_DARK)
        width = max(span[1] - span[0], 0.8)
        c.setFillColor(fill)
        c.rect(span[0], y + 5, width, 6, stroke=0, fill=1)
        if row.progress > 0 and row.start and row.end:
            total = (row.end - row.start).days + 1
            done_until = row.start + timedelta(days=max(0, round(total * row.progress / 100) - 1))
            if done_span := _span(row.start, done_until, sheet, x_of):
                c.setFillColor(done)
                c.rect(done_span[0], y + 5, max(done_span[1] - done_span[0], 0.8), 6, stroke=0, fill=1)
    # Actual: thin green bar at the top of the row, to the finish or the data date.
    if row.actual_start:
        until = row.actual_end or (data_date if data_date > row.actual_start else row.actual_start)
        if span := _span(row.actual_start, until, sheet, x_of):
            c.setFillColor(_GREEN)
            c.rect(span[0], y + 11.6, max(span[1] - span[0], 0.8), 1.8, stroke=0, fill=1)


def _legend(c: Any, labels: dict[str, str], page_w: float, index: int, total: int) -> None:
    y = _MARGIN + 6
    x = _MARGIN
    items: list[tuple[str, str, Any]] = [
        ("bar", labels["legend_current"], _BLUE),
        ("bar", labels["legend_progress"], _BLUE_DARK),
        ("bar", labels["legend_critical"], _RED),
        ("thin", labels["legend_baseline"], _GREY),
        ("thin", labels["legend_actual"], _GREEN),
        ("diamond", labels["legend_milestone"], _INK),
        ("summary", labels["legend_summary"], _INK),
        ("line", labels["data_date"], _ORANGE),
    ]
    for kind, text, colour in items:
        c.setFillColor(colour)
        c.setStrokeColor(colour)
        if kind == "bar":
            c.rect(x, y, 14, 6, stroke=0, fill=1)
        elif kind == "thin":
            c.rect(x, y + 2, 14, 2.5, stroke=0, fill=1)
        elif kind == "summary":
            c.rect(x, y + 1.5, 14, 3, stroke=0, fill=1)
        elif kind == "diamond":
            _diamond(c, x + 7, y + 3, 3.4, colour)
        else:
            c.setLineWidth(0.8)
            c.setDash(3, 2)
            c.line(x + 7, y - 2, x + 7, y + 8)
            c.setDash()
        _put(c, x + 18, y, text, 7, color=_INK)
        x += 18 + pdf_fonts.pdf_text_width(text, 7) + 14
    _put(c, page_w - _MARGIN, y, labels["sheet_of"].format(page=index, total=total), 7, align="right", color=_MUTED)
