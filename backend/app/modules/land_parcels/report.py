# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcel schedule PDF: header with project, CRS, method and who printed it, the
schedule table, totals and the open findings. Company letterhead when set."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from app.core.pdf_branding import branded_doc_metadata, branded_footer, branded_header_footer, branded_letterhead
from app.core.pdf_fonts import pdf_font
from app.core.validation.messages import translate


def _t(key: str, locale: str, **params: Any) -> str:
    return translate(f"land_parcels.pdf.{key}", locale=locale, **params)


def build_schedule_pdf(
    *,
    project: str,
    crs: str,
    decimals: int,
    parcels: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    summary: dict[str, Any],
    locale: str,
    printed_by: str,
    id_label: str,
) -> bytes:
    """The schedule as PDF bytes (A4 landscape)."""
    from reportlab.lib import colors  # noqa: PLC0415
    from reportlab.lib.pagesizes import A4, landscape  # noqa: PLC0415
    from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: PLC0415

    body, bold = pdf_font("Helvetica"), pdf_font("Helvetica", bold=True)
    small = ParagraphStyle("small", fontName=body, fontSize=8.5, leading=11)
    head = ParagraphStyle("head", fontName=bold, fontSize=15, leading=19, spaceAfter=4)
    sect = ParagraphStyle("sect", fontName=bold, fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=3)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=16 * mm, bottomMargin=14 * mm,
        title=_t("title", locale), **branded_doc_metadata(),
    )  # fmt: skip

    def p(text: Any, style: ParagraphStyle = small) -> Paragraph:
        return Paragraph(escape(str(text if text is not None else "")), style)

    status_label = {s: _t(f"status_{s}", locale) for s in ("needed", "negotiating", "acquired", "expropriation")}
    story: list[Any] = [p(_t("title", locale), head)]
    meta = [
        [p(_t("project", locale)), p(project)],
        [p(_t("crs", locale)), p(crs)],
        [p(_t("method", locale)), p(_t("method_value", locale, decimals=decimals))],
        [p(_t("printed", locale)), p(f"{printed_by} · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")],
    ]
    mt = Table(meta, colWidths=[45 * mm, 200 * mm])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [mt, Spacer(1, 4 * mm)]

    cur = summary.get("currency") or ""
    header = [id_label, _t("legal", locale), _t("computed", locale), _t("diff", locale), _t("status", locale),
              _t("rights", locale), _t("cost", locale), _t("findings", locale)]  # fmt: skip
    data = [[p(h, ParagraphStyle("h", parent=small, fontName=bold)) for h in header]]
    for row in parcels:
        cost = row.get("acquisition_cost")
        data.append(
            [
                p(row.get("parcel_ref")),
                p(row.get("legal_area") or "-"),
                p(row.get("computed_area") or "-"),
                p(row.get("area_diff") or "-"),
                p(status_label.get(row.get("status") or "", row.get("status"))),
                p(", ".join(row.get("rights_kinds") or []) or "-"),
                p(f"{cost} {cur}".strip() if cost else "-"),
                p(", ".join(sorted({f["rule_id"] for f in row.get("findings") or []})) or "-"),
            ]
        )
    data.append(
        [p(_t("total", locale, count=summary.get("parcels", 0))), p(""), p(summary.get("total_area")), p(""),
         p(_t("acquired_of", locale, acquired=summary.get("acquired", 0), total=summary.get("parcels", 0))), p(""),
         p(f"{summary.get('cost_to_acquire')} {cur}".strip()), p("")]
    )  # fmt: skip
    widths = [40, 28, 28, 22, 30, 45, 36, 40]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c8ccd4")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f6f7f9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)

    story.append(p(_t("findings_title", locale), sect))
    if findings:
        for f in findings:
            story.append(p(f"{f.get('rule_id')} · {f.get('message')}"))
    else:
        story.append(p(_t("no_findings", locale)))
    story += [Spacer(1, 3 * mm), p(_t("disclaimer", locale))]

    letterhead = branded_letterhead(doc.width - 12, doc_type="land_parcel_schedule")
    if letterhead is not None:
        story.insert(0, letterhead)
    doc.build(
        story,
        onFirstPage=branded_footer if letterhead is not None else branded_header_footer,
        onLaterPages=branded_header_footer,
    )
    return buf.getvalue()
