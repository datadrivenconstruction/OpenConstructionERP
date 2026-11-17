# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out sheet PDF: one request, every stake, its newest measurement and verdict.

Header: project, CRS, request, tolerance with its source, generated date. Then a
table (point, design E/N/Z, measured E/N, d, dZ, verdict, measured by), the pass
and fail counts, and the findings. Pure renderer: the service passes the data.
Labels come from the validation message bundle (``setting_out.sheet.*``).
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
from app.modules.setting_out.schemas import Finding, RequestDetail

PAGE = landscape(A4)
MARGIN = 12 * mm
WIDTH = PAGE[0] - 2 * MARGIN


def _c(v: float | None) -> str:
    return "" if v is None else f"{v:.3f}"


def _mm(v: float | None) -> str:
    return "" if v is None else f"{v:g}"


def build_setting_out_sheet(
    detail: RequestDetail,
    *,
    project_name: str,
    crs_label: str,
    findings: Sequence[Finding],
    locale: str = "en",
) -> bytes:
    """Render the setting-out sheet of one request as PDF bytes."""
    fonts = register_pdf_fonts()
    body_font, bold_font = (BODY_FONT, BOLD_FONT) if fonts else ("Helvetica", "Helvetica-Bold")

    def tr(key: str, **params: object) -> str:
        return translate(f"setting_out.sheet.{key}", locale=locale, **params)

    styles = getSampleStyleSheet()
    base = styles["Normal"].clone("so_body", fontName=body_font, fontSize=8.5, leading=11)
    title = styles["Title"].clone("so_title", fontName=bold_font, fontSize=15, leading=19, alignment=0)

    def p(text: str, style=base) -> Paragraph:  # noqa: ANN001
        return Paragraph(html.escape(text), pdf_style_for_text(style, text))

    flow: list = []
    letterhead = branded_letterhead(WIDTH)
    if letterhead is not None:
        flow.append(letterhead)
    flow.append(p(tr("title"), title))
    tolerance = f"{_mm(detail.tol_h_mm)} mm" if detail.tol_h_mm is not None else tr("no_profile")
    if detail.tol_v_mm is not None:
        tolerance += f" / dZ {_mm(detail.tol_v_mm)} mm"
    meta = [
        [p(tr("project")), p(project_name), p(tr("crs")), p(crs_label or "-")],
        [
            p(tr("request")),
            p(f"{detail.code} {detail.name}"),
            p(tr("tolerance")),
            p(f"{detail.tolerance_label} {tolerance}".strip()),
        ],
        [
            p(tr("element")),
            p(
                " ".join(
                    x for x in (detail.element_ref_type.upper(), detail.element_ref_label or detail.element_ref_id) if x
                )
                or "-"
            ),
            p(tr("generated")),
            p(datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
        ],
    ]
    mt = Table(meta, colWidths=[30 * mm, WIDTH / 2 - 30 * mm, 30 * mm, WIDTH / 2 - 30 * mm])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.grey)]))
    flow += [Spacer(1, 3 * mm), mt, Spacer(1, 4 * mm)]

    head = [
        tr(k)
        for k in ("point", "design_e", "design_n", "design_z", "measured_e", "measured_n", "d", "dz", "verdict", "by")
    ]
    data: list[list] = [[p(h) for h in head]]
    for s in detail.stakes:
        r = s.latest
        data.append(
            [
                p(s.point_id),
                p(_c(s.design_e)),
                p(_c(s.design_n)),
                p(_c(s.design_z)),
                p(_c(r.measured_e) if r else ""),
                p(_c(r.measured_n) if r else ""),
                p(_mm(r.d_mm) if r else ""),
                p(_mm(r.dz_mm) if r else ""),
                p(tr(f"verdict_{s.verdict}")),
                p(f"{r.measured_by} {r.measured_at:%Y-%m-%d}".strip() if r else ""),
            ]
        )
    widths = [22, 28, 30, 20, 28, 30, 16, 16, 24, 0]
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
    flow.append(p(tr("counts", passed=detail.pass_count, failed=detail.fail_count, open=detail.open_count)))
    if findings:
        flow += [Spacer(1, 3 * mm), p(tr("findings"), styles["Heading4"].clone("so_h4", fontName=bold_font))]
        flow += [p(f"{f.rule_id}  {f.message}") for f in findings]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"{detail.code} {detail.name}",
    )  # fmt: skip
    doc.build(flow)
    return buf.getvalue()
