# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring alarm report PDF: every point, its latest displacement, rate and level.

Header: project, CRS, threshold profile with its source, generated date. Then a
table (point, baseline, latest, displacement, rate, level, acknowledged), the
count per level, and the findings. Pure renderer: the service passes the data.
Labels come from the validation message bundle (``monitoring.report.*``).
"""

from __future__ import annotations

import html
import io
from collections.abc import Sequence
from datetime import UTC, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import branded_letterhead
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_style_for_text, register_pdf_fonts
from app.core.validation.messages import translate
from app.modules.monitoring.schemas import Finding, PointOut, ProfileOut

PAGE = landscape(A4)
MARGIN = 12 * mm
WIDTH = PAGE[0] - 2 * MARGIN


def _v(v: float | None, places: int) -> str:
    return "" if v is None else f"{v:.{places}f}"


def build_alarm_report(
    points: Sequence[PointOut],
    *,
    project_name: str,
    crs_label: str,
    profile: ProfileOut | None,
    findings: Sequence[Finding],
    locale: str = "en",
) -> bytes:
    """Render the monitoring alarm report as PDF bytes."""
    fonts = register_pdf_fonts()
    body_font, bold_font = (BODY_FONT, BOLD_FONT) if fonts else ("Helvetica", "Helvetica-Bold")

    def tr(key: str, **params: object) -> str:
        return translate(f"monitoring.report.{key}", locale=locale, **params)

    def level(name: str) -> str:
        return translate(f"monitoring.level.{name}", locale=locale) if name != "none" else tr("no_profile")

    styles = getSampleStyleSheet()
    base = styles["Normal"].clone("mon_body", fontName=body_font, fontSize=8.5, leading=11)
    title = styles["Title"].clone("mon_title", fontName=bold_font, fontSize=15, leading=19, alignment=0)

    def p(text: str, style=base) -> Paragraph:  # noqa: ANN001
        return Paragraph(html.escape(text), pdf_style_for_text(style, text))

    flow: list = []
    letterhead = branded_letterhead(WIDTH)
    if letterhead is not None:
        flow.append(letterhead)
    flow.append(p(tr("title"), title))
    profile_text = (
        f"{profile.name} ({profile.reference})".replace(" ()", "") if profile is not None else tr("no_profile")
    )
    meta = [
        [p(tr("project")), p(project_name), p(tr("crs")), p(crs_label or "-")],
        [p(tr("profile")), p(profile_text), p(tr("generated")), p(datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"))],
    ]
    mt = Table(meta, colWidths=[30 * mm, WIDTH / 2 - 30 * mm, 30 * mm, WIDTH / 2 - 30 * mm])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.grey)]))
    flow += [Spacer(1, 3 * mm), mt, Spacer(1, 4 * mm)]

    head = [tr(k) for k in ("point", "baseline", "latest", "displacement", "rate", "level", "acknowledged")]
    data: list[list] = [[p(h) for h in head]]
    for pt in points:
        ack = {"pending": tr("ack_no"), "done": tr("ack_yes")}.get(pt.ack_state, "-")
        data.append(
            [
                p(pt.code),
                p(_v(pt.baseline_value, 3)),
                p(_v(pt.latest_value, 3)),
                p(_v(pt.displacement_mm, 1)),
                p(_v(pt.rate_mm_day, 2)),
                p(level(pt.level)),
                p(ack),
            ]
        )
    widths = [34, 30, 30, 34, 30, 40, 0]
    widths[-1] = WIDTH / mm - sum(widths)
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    flow += [table, Spacer(1, 3 * mm)]
    count = {name: sum(1 for pt in points if pt.level == name) for name in ("alert", "action", "alarm")}
    flow.append(p(tr("counts", ok=len(points) - sum(count.values()), **count)))
    if findings:
        flow += [Spacer(1, 3 * mm), p(tr("findings"), styles["Heading4"].clone("mon_h4", fontName=bold_font))]
        flow += [p(f"{f.rule_id}  {f.message}") for f in findings]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        title=tr("title"),
    )  # fmt: skip
    doc.build(flow)
    return buf.getvalue()
