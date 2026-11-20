# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Adjustment report of a field traverse as PDF (reportlab, bundled Unicode fonts).

The labels come from the caller in the reader's language (the frontend owns the
strings); a missing label falls back to English. Numbers are printed as the
calculation returned them, so the report and the screen agree to the digit.
"""

from __future__ import annotations

import html
import io
import math
from datetime import UTC, datetime

from reportlab.graphics.shapes import Drawing, Ellipse, Group, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_font_for_text, register_pdf_fonts
from app.modules.survey_core.calc_schemas import FieldTraverseOut

register_pdf_fonts()

DEFAULT_LABELS: dict[str, str] = {
    "title": "Traverse adjustment report",
    "method": "Method",
    "bowditch": "Bowditch (compass rule)",
    "lsq": "Least squares",
    "angular": "Angular misclosure",
    "allowed": "Allowed",
    "linear": "Linear misclosure",
    "ratio": "Relative precision",
    "length": "Length",
    "sigma0": "A posteriori sigma0",
    "chi2": "Chi-square test",
    "pass": "Pass",
    "fail": "Fail",
    "weights": "A priori standard deviations",
    "coordinates": "Coordinates",
    "station": "Station",
    "difference": "LSQ minus Bowditch (mm)",
    "residuals": "Residuals",
    "observation": "Observation",
    "residual": "Residual",
    "standardized": "Standardized",
    "redundancy": "Redundancy",
    "ellipses": "Error ellipses (one sigma)",
    "semi_major": "a (mm)",
    "semi_minor": "b (mm)",
    "orientation": "Azimuth of a",
    "relative": "Relative ellipses per leg",
    "sketch": "Sketch with error ellipses",
    "generated": "Generated",
    "fixed": "fixed",
}


def _style(name: str, size: float, bold: bool = False) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=BOLD_FONT if bold else BODY_FONT, fontSize=size, leading=size * 1.3)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    face = pdf_font_for_text(text, bold=style.fontName == BOLD_FONT)
    return Paragraph(html.escape(text), ParagraphStyle(style.name + face, parent=style, fontName=face))


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    body = _style("cell", 8)
    head = _style("head", 8, bold=True)
    data = [[_p(c, head if i == 0 else body) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8ccd2")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def _f(value: float | None, places: int) -> str:
    return "-" if value is None else f"{value:.{places}f}"


def sketch(out: FieldTraverseOut, width: float = 170 * mm, height: float = 110 * mm) -> Drawing:
    """Traverse polygon with exaggerated error ellipses, north up."""
    pts = [(s.e, s.n) for s in (out.lsq.stations if out.lsq else out.stations)]
    d = Drawing(width, height)
    if len(pts) < 2:
        return d
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    pad = 12 * mm
    scale = min((width - 2 * pad) / span, (height - 2 * pad) / span)

    def at(e: float, n: float) -> tuple[float, float]:
        return pad + (e - min(xs)) * scale, pad + (n - min(ys)) * scale

    ring = [at(*p) for p in pts] + ([at(*pts[0])] if out.shape == "loop" else [])
    d.add(PolyLine([c for xy in ring for c in xy], strokeColor=colors.HexColor("#1f4e9c"), strokeWidth=1))
    for s in out.lsq.stations if out.lsq else out.stations:
        x, y = at(s.e, s.n)
        d.add(String(x + 3, y + 3, s.station_id, fontName=BODY_FONT, fontSize=7))
    if out.lsq and out.lsq.ellipses:
        biggest = max(e.a_m for e in out.lsq.ellipses) or 1e-6
        exaggeration = (span * 0.06) / biggest
        by_id = {s.station_id: s for s in out.lsq.stations}
        for e in out.lsq.ellipses:
            s = by_id.get(e.ref)
            if s is None:
                continue
            x, y = at(s.e, s.n)
            g = Group(
                Ellipse(
                    0,
                    0,
                    e.b_m * exaggeration * scale,
                    e.a_m * exaggeration * scale,
                    fillColor=None,
                    strokeColor=colors.HexColor("#c0392b"),
                )
            )
            # Ellipse drawn with its major axis on y (north); rotate clockwise by the azimuth.
            rad = math.radians(-e.azimuth_deg)
            g.transform = (math.cos(rad), math.sin(rad), -math.sin(rad), math.cos(rad), x, y)
            d.add(g)
    d.add(Line(width - 8 * mm, height - 18 * mm, width - 8 * mm, height - 8 * mm, strokeWidth=1))
    d.add(String(width - 9.5 * mm, height - 6 * mm, "N", fontName=BOLD_FONT, fontSize=8))
    return d


def render(out: FieldTraverseOut, title: str = "", labels: dict[str, str] | None = None) -> bytes:
    """The report as PDF bytes."""
    lab = {**DEFAULT_LABELS, **{k: v for k, v in (labels or {}).items() if isinstance(v, str) and v}}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm
    )
    h1, h2, body = _style("h1", 14, bold=True), _style("h2", 10, bold=True), _style("body", 9)
    story: list = [_p(title or lab["title"], h1), Spacer(1, 2 * mm)]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    story.append(_p(f"{lab['generated']}: {stamp}", body))
    story.append(Spacer(1, 3 * mm))

    verdict = {"pass": lab["pass"], "fail": lab["fail"]}
    summary = [
        [lab["method"], lab["lsq"] if out.lsq else lab["bowditch"]],
        [
            lab["angular"],
            f'{_f(out.angular_misclosure_sec, 1)}"'
            + (f' ({lab["allowed"]} {_f(out.angular_allowed_sec, 1)}")' if out.angular_allowed_sec else ""),
        ],
        [lab["length"], f"{_f(out.length_m, 3)} m"],
        [lab["linear"], f"{_f(out.misclosure_m, 3)} m (fE {_f(out.f_e, 3)}, fN {_f(out.f_n, 3)})"],
        [lab["ratio"], f"1:{out.ratio}" if out.ratio else "-"],
    ]
    if out.lsq:
        q = out.lsq
        summary += [
            [lab["sigma0"], f"{_f(q.sigma0, 3)} (r = {q.redundancy})"],
            [
                lab["chi2"],
                f"{_f(q.vtpv, 2)} in [{_f(q.chi2_lower, 2)}, {_f(q.chi2_upper, 2)}]: "
                + verdict["pass" if q.chi2_pass else "fail"],
            ],
            [
                lab["weights"],
                f'{_f(q.angle_sd_sec, 1)}", {_f(q.dist_sd_mm, 1)} mm + {_f(q.dist_ppm, 1)} ppm, '
                f"{_f(q.centering_sd_mm, 1)} mm",
            ],
        ]
    story += [_table(summary, [60 * mm, 114 * mm]), Spacer(1, 4 * mm)]

    story.append(_p(lab["sketch"], h2))
    story.append(sketch(out))
    story.append(Spacer(1, 3 * mm))

    story.append(_p(lab["coordinates"], h2))
    if out.lsq:
        bow = {s.station_id: s for s in out.stations}
        rows = [[lab["station"], "E (Bowditch)", "N (Bowditch)", "E (LSQ)", "N (LSQ)", lab["difference"]]]
        for s in out.lsq.stations:
            b = bow.get(s.station_id)
            rows.append(
                [
                    s.station_id + (f" ({lab['fixed']})" if s.fixed else ""),
                    _f(b.e if b else None, 4),
                    _f(b.n if b else None, 4),
                    _f(s.e, 4),
                    _f(s.n, 4),
                    f"{_f(s.d_e_mm, 1)} / {_f(s.d_n_mm, 1)}",
                ]
            )
        story.append(_table(rows, [24 * mm, 28 * mm, 30 * mm, 28 * mm, 30 * mm, 34 * mm]))
    else:
        rows = [[lab["station"], "E", "N", "cE (mm)", "cN (mm)"]]
        rows += [[s.station_id, _f(s.e, 4), _f(s.n, 4), _f(s.c_e * 1000, 1), _f(s.c_n * 1000, 1)] for s in out.stations]
        story.append(_table(rows, [30 * mm, 38 * mm, 38 * mm, 34 * mm, 34 * mm]))
    if out.lsq:
        q = out.lsq
        story += [Spacer(1, 4 * mm), _p(lab["residuals"], h2)]
        rows = [[lab["observation"], lab["residual"], "sd", lab["redundancy"], lab["standardized"]]]
        for r in q.residuals:
            unit = '"' if r.kind == "angle" else " mm"
            mark = " !" if r.suspect else (" *" if r.flagged else "")
            rows.append(
                [
                    r.ref,
                    f"{_f(r.residual, 2)}{unit}",
                    f"{_f(r.sd, 2)}{unit}",
                    _f(r.redundancy, 3),
                    ("-" if r.standardized is None else _f(r.standardized, 2)) + mark,
                ]
            )
        story.append(_table(rows, [44 * mm, 34 * mm, 30 * mm, 30 * mm, 36 * mm]))
        story += [Spacer(1, 4 * mm), _p(lab["ellipses"], h2)]
        rows = [[lab["station"], lab["semi_major"], lab["semi_minor"], lab["orientation"], "sE / sN (mm)"]]
        rows += [
            [
                e.ref,
                _f(e.a_m * 1000, 1),
                _f(e.b_m * 1000, 1),
                f"{_f(e.azimuth_deg, 1)}°",
                f"{_f(e.sd_e_m * 1000, 1)} / {_f(e.sd_n_m * 1000, 1)}",
            ]
            for e in q.ellipses
        ]
        story.append(_table(rows, [34 * mm, 30 * mm, 30 * mm, 34 * mm, 46 * mm]))
        story += [Spacer(1, 4 * mm), _p(lab["relative"], h2)]
        rows = [[lab["station"], lab["semi_major"], lab["semi_minor"], lab["orientation"]]]
        rows += [
            [e.ref, _f(e.a_m * 1000, 1), _f(e.b_m * 1000, 1), f"{_f(e.azimuth_deg, 1)}°"] for e in q.relative_ellipses
        ]
        story.append(_table(rows, [44 * mm, 40 * mm, 40 * mm, 50 * mm]))
    doc.build(story)
    return buf.getvalue()


__all__ = ["DEFAULT_LABELS", "render", "sketch"]
