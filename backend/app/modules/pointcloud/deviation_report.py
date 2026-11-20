# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scan-vs-design report as CSV (numbers, then the heat grid) and as a one-page PDF."""

from __future__ import annotations

import csv
import io
from typing import Any
from xml.sax.saxutils import escape

from app.core.validation.messages import translate
from app.modules.pointcloud.scan_design import BAND_RGB
from app.modules.pointcloud.scan_design_schemas import DeviationReportOut

MAP_CELLS = 2500


def _n(value: Any, places: int = 1) -> str:
    return "" if value is None else f"{float(value):.{places}f}"


def _rows(r: DeviationReportOut) -> list[tuple[str, str]]:
    s = r.stats
    return [
        ("surface_code", r.surface_code),
        ("surface_name", r.surface_name),
        ("tolerance_profile", r.tolerance.label),
        ("tolerance_source", r.tolerance.source),
        ("tolerance_mm", _n(r.tolerance.v_mm)),
        ("threshold_pct", _n(r.threshold_pct)),
        ("ground_only", str(r.ground_only).lower()),
        ("points_read", str(s.points_read)),
        ("points_compared", str(s.points_compared)),
        ("points_outside_design", str(s.points_outside)),
        ("mean_mm", _n(s.mean_mm, 2)),
        ("rms_mm", _n(s.rms_mm, 2)),
        ("std_mm", _n(s.std_mm, 2)),
        ("p95_abs_mm", _n(s.p95_mm)),
        ("min_mm", _n(s.min_mm)),
        ("max_mm", _n(s.max_mm)),
        ("within_pct", _n(s.within_pct, 2)),
        ("above_pct", _n(s.high_pct, 2)),
        ("below_pct", _n(s.low_pct, 2)),
        ("out_of_tolerance_points", str(s.out_count)),
        ("coverage_pct", _n(s.coverage_pct, 2)),
        ("severity", r.severity),
    ]


def report_csv(r: DeviationReportOut) -> bytes:
    """Metric/value rows, the findings, then one row per heat cell (E, N, mean dz in mm)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["metric", "value"])
    w.writerows(_rows(r))
    for f in r.findings:
        w.writerow([f"finding_{f.rule_id}", f.message])
    heat = r.heat or {}
    if heat.get("dz_mm"):
        w.writerow([])
        w.writerow(["cell_e", "cell_n", "mean_dz_mm"])
        nx, cell = int(heat["nx"]), float(heat["cell"])
        e0, n0 = float(heat["origin_e"]), float(heat["origin_n"])
        for k, v in enumerate(heat["dz_mm"]):
            if v is None:
                continue
            i, j = k % nx, k // nx
            w.writerow([f"{e0 + (i + 0.5) * cell:.3f}", f"{n0 + (j + 0.5) * cell:.3f}", f"{v:.1f}"])
    return buf.getvalue().encode("utf-8")


def _colour(dz: float, tol: float) -> tuple[int, int, int]:
    if dz > 2 * tol:
        return BAND_RGB["far_high"]
    if dz > tol:
        return BAND_RGB["high"]
    if dz < -2 * tol:
        return BAND_RGB["far_low"]
    if dz < -tol:
        return BAND_RGB["low"]
    return BAND_RGB["within"]


def _heat_drawing(heat: dict[str, Any] | None, tol: float, width: float, max_h: float):  # noqa: ANN202
    import math  # noqa: PLC0415

    from reportlab.graphics.shapes import Drawing, Rect  # noqa: PLC0415
    from reportlab.lib import colors  # noqa: PLC0415

    if not heat or not heat.get("dz_mm"):
        return None
    nx, ny = int(heat["nx"]), int(heat["ny"])
    values = heat["dz_mm"]
    step = max(1, math.ceil(math.sqrt(nx * ny / MAP_CELLS)))
    gx, gy = math.ceil(nx / step), math.ceil(ny / step)
    size = min(width / gx, max_h / gy)
    d = Drawing(gx * size, gy * size)
    for j in range(gy):
        for i in range(gx):
            block = [
                values[jj * nx + ii]
                for jj in range(j * step, min(ny, (j + 1) * step))
                for ii in range(i * step, min(nx, (i + 1) * step))
                if values[jj * nx + ii] is not None
            ]
            if not block:
                continue
            worst = max(block, key=abs)
            r, g, b = _colour(worst, tol)
            d.add(
                Rect(
                    i * size, j * size, size, size, fillColor=colors.Color(r / 255, g / 255, b / 255), strokeColor=None
                )
            )
    return d


def report_pdf(r: DeviationReportOut, scan_name: str, locale: str = "en") -> bytes:
    """One page: what was compared, the numbers, the findings and the plan heatmap."""
    from reportlab.lib import colors  # noqa: PLC0415
    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: PLC0415

    from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts  # noqa: PLC0415

    register_pdf_fonts()

    def tr(key: str) -> str:
        return translate(f"pointcloud_report.{key}", locale=locale)

    body = ParagraphStyle("b", fontName=BODY_FONT, fontSize=9, leading=12)
    head = ParagraphStyle("h", fontName=BOLD_FONT, fontSize=14, leading=18)
    sub = ParagraphStyle("s", fontName=BOLD_FONT, fontSize=10, leading=14)

    def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(str(text if text is not None else "")), style)

    s = r.stats
    tol = r.tolerance
    pct = "%"
    rows = [
        (tr("scan"), scan_name),
        (tr("design"), f"{r.surface_code} {r.surface_name}"),
        (tr("tolerance"), f"+/- {tol.v_mm:g} mm ({tol.label})"),
        (tr("points"), f"{s.points_compared:,} / {s.points_read:,}"),
        (tr("mean"), f"{_n(s.mean_mm, 2)} mm"),
        (tr("rms"), f"{_n(s.rms_mm, 2)} mm"),
        (tr("p95"), f"{_n(s.p95_mm)} mm"),
        (tr("within"), f"{_n(s.within_pct, 2)} {pct}"),
        (tr("high"), f"{_n(s.high_pct, 2)} {pct}"),
        (tr("low"), f"{_n(s.low_pct, 2)} {pct}"),
        (tr("coverage"), f"{_n(s.coverage_pct, 2)} {pct}"),
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm)
    table = Table([[p(a), p(b)] for a, b in rows], colWidths=[60 * mm, 110 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story: list[Any] = [p(tr("title"), head), Spacer(1, 4 * mm), table, Spacer(1, 5 * mm)]
    if r.findings:
        story.append(p(tr("findings"), sub))
        story.extend(p(f"{f.rule_id}: {f.message} {f.suggestion or ''}") for f in r.findings)
        story.append(Spacer(1, 4 * mm))
    drawing = _heat_drawing(r.heat, tol.v_mm, 170 * mm, 110 * mm)
    if drawing is not None:
        story.extend([p(tr("map"), sub), Spacer(1, 2 * mm), drawing])
    doc.build(story)
    return buf.getvalue()


__all__ = ["report_csv", "report_pdf"]
