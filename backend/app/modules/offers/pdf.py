"""Customer offer PDF.

Page one carries the letterhead, the address in the envelope window, the meta block, the title and
the introduction, and no sums. The items follow, then the summary, the "not included" box, the
payment schedule, the terms and the acceptance block. Cost, markup percentages and margins never
reach this module: it prints only what the offer record holds.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

from app.modules.offers import pricing

MM = 72.0 / 25.4
_RTL = frozenset({"ar", "he", "fa", "ur"})
_PAPER = {"A4": (595.2756, 841.8898), "LETTER": (612.0, 792.0)}

# English fallbacks; the locale tables (document_forms.boq_pdf.strings) override them per key.
_DEFAULTS = {
    "offer_item": "Item",
    "offer_description": "Description",
    "offer_qty": "Qty",
    "offer_unit": "Unit",
    "offer_unit_price": "Unit price",
    "offer_total": "Total",
    "offer_page": "Page",
    "offer_optional": "Optional",
    "offer_alternative": "Alternative to {ref}",
    "offer_provisional": "Provisional sum",
    "offer_lump_sum": "Lump sum",
    "offer_daywork": "Day rate",
    "offer_by_others": "by others",
    "offer_not_included": "Not included in the total",
    "offer_schedule": "Payment schedule",
    "offer_instalment": "Instalment",
    "offer_percent": "%",
    "offer_amount": "Net",
    "offer_gross": "Gross",
    "offer_due": "Due",
    "offer_acceptance": "Acceptance",
    "offer_accepted_on": "Date",
    "offer_signature": "Signature and name",
    "offer_number": "Offer no.",
    "offer_date": "Date",
    "offer_valid_until": "Valid until",
    "offer_reference": "Your reference",
    "offer_project": "Project",
    "offer_site": "Site",
    "offer_contact": "Contact",
    "offer_licence": "Licence no.",
    "offer_subtotal": "Subtotal {name}",
    "offer_net_total": "Net total",
    "offer_tax_on": "{label} {rate}% on {base}",
    "offer_exclusions": "Exclusions",
    "offer_assumptions": "Assumptions",
    "offer_preliminaries": "Preliminaries",
    "offer_draft": "DRAFT",
    "offer_attn": "Attn.",
    "offer_reverse_charge": "Reverse charge: tax due by the recipient",
    "offer_tax_exempt": "Tax exempt",
    "offer_signing": "On signing",
    "offer_completion": "On completion",
    "offer_days_after": "{days} days after {event}",
    "offer_page_of": "Page {page} of {total}",
}


def _labels(locale: str) -> dict[str, str]:
    try:
        from app.modules.boq.pdf_export import _get_pdf_labels

        found = _get_pdf_labels(locale or "en")
    except Exception:  # noqa: BLE001 - labels fall back to English rather than losing the document
        found = {}
    return {**_DEFAULTS, **{k: v for k, v in found.items() if k.startswith("offer_")}}


def is_rtl(locale: str) -> bool:
    return (locale or "en").replace("_", "-").split("-")[0].lower() in _RTL


def paper_for(pack: dict[str, Any] | None) -> tuple[float, float]:
    return _PAPER.get(str((pack or {}).get("paper") or "A4").upper(), _PAPER["A4"])


# -- Address window -------------------------------------------------------------------------


def address_fit(lines: list[str], window: dict[str, Any]) -> str:
    """``ok`` at 10 pt, ``small`` when 9 pt fits, ``overflow`` when the block cannot sit in the window."""
    from app.core.pdf_fonts import pdf_text_width

    lines = [ln for ln in lines if ln]
    if not lines:
        return "ok"
    width = float(window.get("width_mm") or 85) * MM
    room = (float(window.get("height_mm") or 45) - float(window.get("return_line_mm") or 5)) * MM
    for size, leading, verdict in ((10.0, 12.0, "ok"), (9.0, 10.5, "small")):
        if len(lines) * leading <= room and max(pdf_text_width(ln, size) for ln in lines) <= width:
            return verdict
    return "overflow"


def _window_x(window: dict[str, Any]) -> float:
    return float(window.get("left_mm") or 20) * MM


# -- Building blocks -----------------------------------------------------------------------


def _fmt_money(value: Any, locale: str) -> str:
    return pricing.format_decimal(str(value), locale) if value not in (None, "") else ""


def _para(text: Any, style: Any, *, bold: bool = False) -> Any:
    from reportlab.platypus import Paragraph

    from app.core.pdf_fonts import pdf_markup, pdf_style_for_text

    raw = "" if text is None else str(text)
    markup = pdf_markup(raw, style)
    return Paragraph(f"<b>{markup}</b>" if bold else markup, pdf_style_for_text(style, raw))


def _body_paras(text: str, style: Any) -> list[Any]:
    return [_para(chunk.strip(), style) for chunk in (text or "").split("\n\n") if chunk.strip()]


def render_offer(
    data: dict[str, Any], *, exclusions: dict[str, list[str]] | None = None, draft: bool = False
) -> tuple[bytes, int]:
    """Render the offer record to PDF bytes. Returns ``(pdf, page_count)``."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        KeepTogether,
        PageTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    from app.core import pdf_branding
    from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_font_for_text

    locale = str(data.get("locale") or "en")
    labels = _labels(locale)
    rtl = is_rtl(locale)
    pack = data.get("pack") or {}
    currency = str(data.get("currency") or "")
    page_w, page_h = paper_for(pack)
    window = pack.get("address_window") or {
        "left_mm": 20,
        "top_mm": 45,
        "width_mm": 85,
        "height_mm": 45,
        "return_line_mm": 5,
    }
    side_l, side_r, top_m, bottom_m = 20 * MM, 15 * MM, 10 * MM, 22 * MM
    frame_w = page_w - side_l - side_r
    appearance = pdf_branding.branded_appearance("customer_offer")
    letterhead = pdf_branding.branded_letterhead(frame_w, "customer_offer")
    # The accent is the letterhead's colour: with no letterhead the offer prints in the neutral blue.
    accent = colors.HexColor((appearance.get("accent_color") if letterhead is not None else None) or "#0b5394")
    muted = colors.HexColor("#666666")
    align = TA_RIGHT if rtl else TA_LEFT

    def style(name: str, size: float = 9.0, bold: bool = False, **kw: Any) -> Any:
        kw.setdefault("leading", size * 1.25)
        kw.setdefault("alignment", align)
        return ParagraphStyle(name, fontName=BOLD_FONT if bold else BODY_FONT, fontSize=size, **kw)

    body = style("OfferBody", 9.5, leading=12.5)
    small = style("OfferSmall", 8.0, textColor=muted)
    cell = style("OfferCell", 8.5, leading=10.5)
    cell_r = style("OfferCellR", 8.5, leading=10.5, alignment=TA_LEFT if rtl else TA_RIGHT)
    head = style("OfferHead", 8.0, bold=True, textColor=colors.white)
    title_style = style("OfferTitle", 15.0, bold=True, textColor=accent, spaceAfter=6)
    h2 = style("OfferH2", 10.5, bold=True, textColor=accent, spaceBefore=10, spaceAfter=4)

    story: list[Any] = []
    lh_height = 0.0
    if letterhead is not None:
        story.append(letterhead)
        lh_height = letterhead.wrap(frame_w, page_h)[1] + 5 * MM
    window_top = float(window.get("top_mm") or 45) * MM
    window_h = float(window.get("height_mm") or 45) * MM
    gap = max(0.0, window_top - top_m - lh_height)
    if gap:
        story.append(Spacer(1, gap))

    # -- meta block beside the window
    meta_rows = [
        (labels["offer_number"], f"{data.get('number', '')}-{data.get('revision', 'A')}"),
        (labels["offer_date"], pricing.format_date(data.get("issue_date"), locale)),
    ]
    if data.get("valid_until"):
        meta_rows.append((labels["offer_valid_until"], pricing.format_date(data.get("valid_until"), locale)))
    if data.get("reference"):
        meta_rows.append((labels["offer_reference"], data["reference"]))
    person = data.get("contact_person") or {}
    if person.get("name"):
        meta_rows.append(
            (
                labels["offer_contact"],
                " / ".join(x for x in (person.get("name"), person.get("phone") or person.get("email")) if x),
            )
        )
    if data.get("licence_number"):
        meta_rows.append((labels["offer_licence"], data["licence_number"]))
    meta = Table(
        [[_para(k, small), _para(v, cell)] for k, v in meta_rows],
        colWidths=[26 * MM, None],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )
    window_right = (float(window.get("left_mm") or 20) + float(window.get("width_mm") or 85)) * MM
    meta_left = max(window_right + 8 * MM, page_w * 0.58)
    left_w = meta_left - side_l
    if float(window.get("left_mm") or 20) * MM > page_w / 2:
        left_w, meta_left = frame_w * 0.4, side_l
        meta.hAlign = "LEFT"
        top_block = Table([[meta, ""]], colWidths=[left_w, frame_w - left_w])
    else:
        meta._argW = [26 * MM, page_w - side_r - meta_left - 26 * MM]
        top_block = Table([["", meta]], colWidths=[left_w, frame_w - left_w], rowHeights=[window_h])
    top_block.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(top_block)
    story.append(Spacer(1, 6 * MM))

    # -- title, project, intro (no amounts on page one)
    story.append(_para(data.get("title") or "", title_style))
    project_line = data.get("project_name") or ""
    site = data.get("site_address") or {}
    if project_line:
        story.append(_para(f"{labels['offer_project']}: {project_line}", body))
    site_text = ", ".join(
        x for x in (site.get("street"), " ".join(p for p in (site.get("postcode"), site.get("city")) if p)) if x
    )
    if site_text and not data.get("site_same_as_billing"):
        story.append(_para(f"{labels['offer_site']}: {site_text}", body))
    story.append(Spacer(1, 3 * MM))
    texts = data.get("texts") or {}

    def text_of(kind: str) -> str:
        return str((texts.get(kind) or {}).get("resolved") or "")

    story.extend(_body_paras(text_of("intro"), body))
    story.append(Spacer(1, 4 * MM))

    # -- items
    lines = data.get("lines") or []
    totals = data.get("totals") or {}
    subtotals = totals.get("section_subtotals") or {}
    cols = [
        labels["offer_item"],
        labels["offer_description"],
        labels["offer_qty"],
        labels["offer_unit"],
        labels["offer_unit_price"],
        labels["offer_total"],
    ]
    rows: list[list[Any]] = [[_para(c, head) for c in cols]]
    styles_cmds: list[tuple[Any, ...]] = []
    open_section: dict[str, Any] | None = None

    def close_section() -> None:
        nonlocal open_section
        if open_section is None:
            return
        amount = subtotals.get(open_section["ordinal"])
        if amount not in (None, "") and Decimal(str(amount)) != 0:
            name = open_section["description"] or open_section["ordinal"]
            rows.append(
                [
                    "",
                    _para(labels["offer_subtotal"].format(name=name), cell, bold=True),
                    "",
                    "",
                    "",
                    _para(_fmt_money(amount, locale), cell_r, bold=True),
                ]
            )
            styles_cmds.append(("LINEABOVE", (0, len(rows) - 1), (-1, len(rows) - 1), 0.4, muted))
        open_section = None

    for ln in lines:
        if ln.get("kind") == "section":
            close_section()
            open_section = ln
            title = f"{ln.get('ordinal', '')} {ln.get('description', '')}".strip()
            if ln.get("ordinal") == "M" and ln.get("description"):
                title = ln["description"]
            rows.append([_para(title, cell, bold=True), "", "", "", "", ""])
            idx = len(rows) - 1
            styles_cmds += [
                ("SPAN", (0, idx), (-1, idx)),
                ("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#eef2f7")),
            ]
            continue
        role = ln.get("role") or "base"
        desc = str(ln.get("description") or "")
        tag = ""
        if role == "optional":
            tag = labels["offer_optional"]
        elif role == "alternative":
            tag = labels["offer_alternative"].format(ref=ln.get("alternative_of") or "")
        elif role == "provisional_sum":
            tag = labels["offer_provisional"]
        elif role == "daywork_rate":
            tag = labels["offer_daywork"]
        if ln.get("by_others"):
            tag = f"{tag}, {labels['offer_by_others']}" if tag else labels["offer_by_others"]
        total = _fmt_money(ln.get("total"), locale)
        if role in ("optional", "alternative") and total:
            total = f"({total})"
        unit = labels["offer_lump_sum"] if role == "lump_sum" else str(ln.get("unit") or "")
        cell_desc = [_para(desc, cell)]
        if tag:
            cell_desc.append(_para(tag, style("OfferTag", 7.5, textColor=muted)))
        qty = "" if role == "lump_sum" else _fmt_money(ln.get("quantity"), locale)
        rows.append(
            [
                _para(ln.get("ordinal"), cell),
                cell_desc,
                _para(qty, cell_r),
                _para(unit, cell),
                _para(_fmt_money(ln.get("unit_rate"), locale), cell_r),
                _para(total, cell_r),
            ]
        )
    close_section()

    widths = [16 * MM, None, 20 * MM, 14 * MM, 24 * MM, 26 * MM]
    widths[1] = frame_w - sum(w for w in widths if w)
    table_rows = [list(reversed(r)) for r in rows] if rtl else rows
    if rtl:
        widths = list(reversed(widths))
    items = Table(table_rows, colWidths=widths, repeatRows=1, splitByRow=1)
    items.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), accent),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dddddd")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                *styles_cmds,
            ]
        )
    )
    story.append(items)

    # -- summary
    story.append(Spacer(1, 5 * MM))
    summary_rows = [
        [
            _para(labels["offer_net_total"], cell, bold=True),
            _para(f"{_fmt_money(totals.get('net'), locale)} {currency}", cell_r, bold=True),
        ]
    ]
    tax_label = str(data.get("tax_label") or "")
    mode = str(data.get("tax_mode") or "standard")
    if mode == "reverse_charge":
        summary_rows.append([_para(labels["offer_reverse_charge"], cell), ""])
    elif mode == "exempt":
        summary_rows.append([_para(labels["offer_tax_exempt"], cell), ""])
    else:
        for grp in totals.get("tax_groups") or []:
            text = labels["offer_tax_on"].format(
                label=tax_label, rate=grp.get("rate"), base=_fmt_money(grp.get("base"), locale)
            )
            summary_rows.append([_para(text, cell), _para(f"{_fmt_money(grp.get('tax'), locale)} {currency}", cell_r)])
    summary_rows.append(
        [
            _para(labels["offer_gross"], cell, bold=True),
            _para(f"{_fmt_money(totals.get('gross'), locale)} {currency}", cell_r, bold=True),
        ]
    )
    summary = Table(summary_rows, colWidths=[frame_w * 0.6, frame_w * 0.4 - 0], hAlign="RIGHT" if not rtl else "LEFT")
    summary.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, accent),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(KeepTogether([summary]))

    not_included = totals.get("not_included") or []
    if not_included:
        box_rows = [[_para(labels["offer_not_included"], cell, bold=True), ""]]
        for n in not_included:
            tag = (
                labels["offer_optional"]
                if n.get("role") == "optional"
                else labels["offer_alternative"].format(ref=n.get("alternative_of") or "")
            )
            box_rows.append(
                [
                    _para(f"{n.get('ordinal', '')} {n.get('description', '')} ({tag})", cell),
                    _para(f"{_fmt_money(n.get('total'), locale)} {currency}", cell_r),
                ]
            )
        box = Table(box_rows, colWidths=[frame_w * 0.75, frame_w * 0.25])
        box.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, muted),
                    ("SPAN", (0, 0), (-1, 0)),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(Spacer(1, 4 * MM))
        story.append(KeepTogether([box]))

    # -- payment schedule
    schedule = data.get("schedule") or []
    if schedule:
        story.append(_para(labels["offer_schedule"], h2))
        srows = [
            [
                _para(c, head)
                for c in (
                    labels["offer_instalment"],
                    labels["offer_due"],
                    labels["offer_percent"],
                    labels["offer_amount"],
                    labels["offer_gross"],
                )
            ]
        ]
        for r in schedule:
            srows.append(
                [
                    _para(r.get("name") or r.get("code"), cell),
                    _para(_due_text(r, labels), cell),
                    _para(_fmt_money(r.get("percent"), locale), cell_r),
                    _para(_fmt_money(r.get("net"), locale), cell_r),
                    _para(_fmt_money(r.get("gross"), locale), cell_r),
                ]
            )
        sw = [frame_w * 0.34, frame_w * 0.26, frame_w * 0.1, frame_w * 0.15, frame_w * 0.15]
        if rtl:
            srows = [list(reversed(r)) for r in srows]
            sw = list(reversed(sw))
        sched = Table(srows, colWidths=sw, repeatRows=1)
        sched.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), accent),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dddddd")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(sched)

    # -- terms
    for heading_key, kind in (
        ("", "payment_terms"),
        ("", "validity"),
        ("", "conditions"),
        ("", "warranty"),
        ("", "closing"),
        ("", "legal_notice"),
    ):
        chunk = _body_paras(text_of(kind), small if kind == "legal_notice" else body)
        if chunk:
            story.append(Spacer(1, 3 * MM))
            story.extend(chunk)
    ex = exclusions or {}
    for key, label in (("exclusions", "offer_exclusions"), ("assumptions", "offer_assumptions")):
        if ex.get(key):
            story.append(_para(labels[label], h2))
            story.extend(_para(f"- {item}", body) for item in ex[key])

    # -- acceptance, kept whole
    sign = Table(
        [[_para(labels["offer_accepted_on"], small), _para(labels["offer_signature"], small)], ["", ""]],
        colWidths=[frame_w * 0.3, frame_w * 0.6],
        rowHeights=[None, 16 * MM],
    )
    sign.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.black),
                ("LINEABOVE", (1, 0), (1, 0), 0.5, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(Spacer(1, 6 * MM))
    story.append(KeepTogether([_para(labels["offer_acceptance"], h2), sign]))

    # -- pages
    buffer = io.BytesIO()
    footer_label = f"{data.get('number', '')}-{data.get('revision', 'A')}"
    mirror = rtl

    def furniture(canvas: Any, doc: Any, first: bool) -> None:
        pdf_branding._draw_page_furniture(canvas, doc, header=not first, caller="offer_pdf", doc_type="customer_offer")
        if first:
            _draw_address(canvas, data, window, page_h, page_w, labels, mirror)
        canvas.saveState()
        canvas.setFont(pdf_font_for_text(footer_label), 7)
        canvas.setFillColor(muted)
        canvas.drawString(side_l, 9 * MM, footer_label)
        canvas.restoreState()
        if draft:
            pdf_branding.draw_watermark(
                canvas, {"watermark_text": labels["offer_draft"], "watermark_opacity": 12}, page_w=page_w, page_h=page_h
            )

    doc = BaseDocTemplate(
        buffer,
        pagesize=(page_w, page_h),
        leftMargin=side_l,
        rightMargin=side_r,
        topMargin=top_m,
        bottomMargin=bottom_m,
        title=str(data.get("title") or ""),
    )
    first_frame = Frame(
        side_l,
        bottom_m,
        frame_w,
        page_h - top_m - bottom_m,
        id="first",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    later_frame = Frame(
        side_l,
        bottom_m,
        frame_w,
        page_h - 22 * MM - bottom_m,
        id="later",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="First", frames=[first_frame], onPage=lambda c, d: furniture(c, d, True)),
            PageTemplate(id="Later", frames=[later_frame], onPage=lambda c, d: furniture(c, d, False)),
        ]
    )
    from reportlab.platypus import NextPageTemplate

    story.insert(0, NextPageTemplate("Later"))
    pdf_branding.build_with_page_count(doc, story)
    return buffer.getvalue(), int(getattr(doc, "page", 0) or 1)


def _due_text(row: dict[str, Any], labels: dict[str, str]) -> str:
    due = row.get("due") or {}
    kind = due.get("type")
    if kind == "signing":
        return labels["offer_signing"]
    if kind == "completion":
        return labels["offer_completion"]
    if kind == "date" and due.get("date"):
        return str(due["date"])
    days = row.get("payment_terms_days") or row.get("lag_days") or 0
    return labels["offer_days_after"].format(days=days, event=str(kind or ""))


def _draw_address(
    canvas: Any,
    data: dict[str, Any],
    window: dict[str, Any],
    page_h: float,
    page_w: float,
    labels: dict[str, str],
    rtl: bool,
) -> None:
    from app.core.pdf_fonts import pdf_font_for_text
    from app.modules.offers.service import address_lines

    customer = data.get("customer") or {}
    lines = address_lines(customer, home_country=str(data.get("home_country") or ""), attn_label=labels["offer_attn"])
    fit = address_fit(lines, window)
    size, leading = (10.0, 12.0) if fit != "small" else (9.0, 10.5)
    x = _window_x(window)
    top = page_h - float(window.get("top_mm") or 45) * MM
    return_h = float(window.get("return_line_mm") or 5) * MM
    sender = _sender_line()
    canvas.saveState()
    if sender:
        canvas.setFont(pdf_font_for_text(sender), 6.5)
        canvas.setFillGray(0.4)
        canvas.drawString(x, top - return_h + 1.5 * MM, sender)
        canvas.setLineWidth(0.3)
        canvas.line(
            x, top - return_h + 0.6 * MM, x + float(window.get("width_mm") or 85) * MM, top - return_h + 0.6 * MM
        )
    canvas.setFillGray(0)
    y = top - return_h - leading
    for ln in lines:
        canvas.setFont(pdf_font_for_text(ln), size)
        canvas.drawString(x, y, ln)
        y -= leading
    canvas.restoreState()


def _sender_line() -> str:
    try:
        from app.core.pdf_branding import _letterhead_profile, _profile_text

        profile = _letterhead_profile() or {}
        parts = [_profile_text(profile, "legal_name")] + [
            ln.strip() for ln in _profile_text(profile, "address").split("\n")[:2] if ln.strip()
        ]
        return " - ".join(p for p in parts if p)
    except Exception:  # noqa: BLE001 - a missing return line must not stop the offer
        return ""
