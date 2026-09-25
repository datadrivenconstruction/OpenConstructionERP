# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Award letter and rejection notice PDF generation for tendering.

After bid analysis a buyer needs two documents to close a tender:

* an **award letter** for the winning bid, and
* a **rejection notice** for every other bidder.

Both are produced here as downloadable PDFs using ``reportlab`` - the same
library and document pattern the platform already uses for the BOQ cost
estimate (see ``backend/app/modules/boq/pdf_export.py``). We deliberately do
not hand-roll a PDF byte stream here (the legacy tender summary in
``router.py`` did that with the stdlib); reusing reportlab gives us Unicode
fonts (via ``app.core.pdf_fonts``), consistent typography, and locale-aware
money formatting for free.

Money correctness: every monetary value arrives as a Decimal-as-string (the
v3 §10 contract used across tendering) and is parsed straight into ``Decimal``
with no float intermediary, so the printed totals match the stored amounts
exactly. Untrusted strings (company names, package names, notes) are escaped
before being handed to reportlab's ``Paragraph`` so a crafted bid company name
cannot inject markup or crash the parser - the same defence boq/pdf_export.py
documents as BUG-PDF01/02.

How many digits follow the decimal separator is a question about the currency
and not about the presentation style, so it is answered by ``app.core.money``
rather than assumed here. A tender settled in forint is written whole, and one
settled in Kuwaiti dinar keeps the fils the bid was actually made in.
"""

from __future__ import annotations

import html
import io
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.money import minor_units, money_quantum
from app.core.pdf_branding import (
    DEFAULT_BRAND,
    branded_cover_brand,
    branded_doc_metadata,
    branded_header_logo,
    branded_letterhead,
)
from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_fit_line,
    pdf_room_beside,
    pdf_style_for_text,
    register_pdf_fonts,
)

# Register the bundled Unicode (DejaVu) faces with reportlab. Idempotent and
# safe at import time because reportlab is imported at module level here.
register_pdf_fonts()

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 22 * mm
MARGIN_RIGHT = 22 * mm
MARGIN_TOP = 24 * mm
MARGIN_BOTTOM = 20 * mm
USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT


def _to_decimal(value: Any) -> Decimal:
    """Parse a money value to Decimal exactly, never raising (defaults to 0)."""
    try:
        if value is None or value == "":
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _fmt_money(value: Decimal, currency: str = "") -> str:
    """Format a Decimal with thousands separators, in its currency's own units.

    Locale style mirrors boq/pdf_export.py: EUR uses ``1.234,56``, CHF uses
    ``1'234.56``, everything else uses ``1,234.56``. That style decides the
    separators. The currency decides how many digits follow them, and
    :func:`app.core.money.minor_units` is the one place that knows, so a letter
    quoting a forint bid does not invent a subunit that left circulation in
    1999. A blank or unregistered code takes that function's own two-decimal
    default rather than a guess made here. The amount stays Decimal until this
    presentation boundary so no float drift is introduced.
    """
    code = (currency or "").strip().upper()
    decimals = minor_units(code)
    quantized = value.quantize(money_quantum(code), rounding=ROUND_HALF_UP)
    raw = f"{quantized:,.{decimals}f}"
    if code == "EUR":
        raw = raw.replace(",", "THOU").replace(".", ",").replace("THOU", ".")
    elif code == "CHF":
        raw = raw.replace(",", "'")
    return f"{raw} {code}".strip()


def _safe_para(text: Any, style: ParagraphStyle) -> Paragraph:
    """Construct a ``Paragraph`` from possibly-untrusted user input.

    HTML metacharacters are escaped so reportlab's paraparser sees inert
    characters, not markup (BUG-PDF01/02 defence). ``None`` becomes empty.
    Newlines in free text are turned into line breaks.

    This is also where the Chinese face is chosen. Every string a Chinese
    tender carries - the bidding company's name, the award reason, the
    signatory - reaches the document through here, so the face is asked for
    once at the funnel. The style is returned unchanged for anything else.
    """
    if text is None:
        rendered = ""
    elif isinstance(text, str):
        rendered = text
    else:
        rendered = str(text)
    escaped = html.escape(rendered, quote=True).replace("\n", "<br/>")
    return Paragraph(escaped, pdf_style_for_text(style, rendered))


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "Brand",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=18,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=2 * mm,
        ),
        "doc_title": ParagraphStyle(
            "DocTitle",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=15,
            textColor=colors.HexColor("#16213e"),
            spaceBefore=6 * mm,
            spaceAfter=4 * mm,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=9,
            textColor=colors.HexColor("#666666"),
            alignment=TA_RIGHT,
            leading=12,
        ),
        "label": ParagraphStyle(
            "Label",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=10,
            textColor=colors.HexColor("#555555"),
            alignment=TA_LEFT,
        ),
        "value": ParagraphStyle(
            "Value",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=10,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_LEFT,
        ),
        "value_right": ParagraphStyle(
            "ValueRight",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=11,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_RIGHT,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=10,
            textColor=colors.HexColor("#1d1d1f"),
            leading=15,
            spaceAfter=3 * mm,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=9,
            textColor=colors.HexColor("#444444"),
            leading=13,
            leftIndent=4 * mm,
        ),
        "signoff": ParagraphStyle(
            "Signoff",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=10,
            textColor=colors.HexColor("#1d1d1f"),
            leading=15,
            spaceBefore=8 * mm,
        ),
    }


def _footer(canvas: Any, doc: Any) -> None:
    generated = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    page_text = f"Page {doc.page}"
    # The brand is the firm's own name: it may be Chinese, and a legal name may
    # be long enough to reach the page number, so the line is fitted into the
    # room beside it. The page number is ours and stays where it is.
    footer_left, face, size = pdf_fit_line(
        branded_cover_brand(),
        pdf_room_beside(PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT, page_text),
        suffix=f"  |  Generated: {generated}",
        base=BODY_FONT,
    )
    canvas.saveState()
    canvas.setFont(face, size)
    canvas.setFillColor(colors.HexColor("#999999"))
    canvas.drawString(MARGIN_LEFT, 12 * mm, footer_left)
    if (face, size) != (BODY_FONT, 7.0):
        canvas.setFont(BODY_FONT, 7)
    canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, 12 * mm, page_text)
    canvas.setStrokeColor(colors.HexColor("#e5e5ea"))
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_LEFT, 15 * mm, PAGE_WIDTH - MARGIN_RIGHT, 15 * mm)
    canvas.restoreState()


def _page_furniture(letterhead_on_first_page: bool) -> Any:
    """``onPage`` callback: the footer, and the workspace logo top right.

    The logo is left off a first page that opens with the letterhead, which
    already carries it.
    """

    def _draw(canvas: Any, doc: Any) -> None:
        _footer(canvas, doc)
        if not (letterhead_on_first_page and doc.page == 1):
            branded_header_logo(canvas, doc)

    return _draw


def _document(buffer: io.BytesIO, title: str, *, letterhead_on_first_page: bool = False) -> BaseDocTemplate:
    frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM + 4 * mm,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM - 4 * mm,
        id="main",
    )
    template = PageTemplate(id="main", frames=[frame], onPage=_page_furniture(letterhead_on_first_page))
    meta = branded_doc_metadata()
    if meta["author"] == DEFAULT_BRAND:
        # An unbranded workspace keeps the properties these letters always had.
        meta = {
            "author": "OpenConstructionERP",
            "subject": "Tender decision · DDC-CWICR-OE",
            "creator": "OpenConstructionERP · DataDrivenConstruction",
            "producer": "OpenConstructionERP / reportlab · datadrivenconstruction.io",
            "keywords": "DDC-CWICR-OE-2026,OpenConstructionERP,Tendering,DataDrivenConstruction",
        }
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=title,
        **meta,
    )
    doc.addPageTemplates([template])
    return doc


def _letterhead() -> Any | None:
    """The firm's letterhead, or ``None``.

    The letter's own tables are the full width between the margins and are
    centred over the frame's 6pt padding, so the letterhead is built to that
    width and centred the same way. At the frame width it sat 6pt inside the
    rule under the reference block, which reads as a misprint.
    """
    letterhead = branded_letterhead(USABLE_WIDTH)
    if letterhead is not None:
        letterhead.hAlign = "CENTER"
    return letterhead


def _header_block(
    styles: dict[str, ParagraphStyle],
    doc_label: str,
    ref: str,
    *,
    letterhead: Any | None = None,
) -> list[Any]:
    """Brand on the left, document label + reference + date on the right.

    With a letterhead, the letterhead heads the page and already names the
    firm, so the brand cell is left empty rather than printing it twice.
    """
    today = datetime.now(tz=UTC).strftime("%d.%m.%Y")
    if letterhead is None:
        brand = branded_cover_brand()
        left: Any = Paragraph(html.escape(brand), pdf_style_for_text(styles["brand"], brand))
    else:
        left = ""
    right = Paragraph(
        f"<b>{html.escape(doc_label)}</b><br/>Ref: {html.escape(ref)}<br/>Date: {today}",
        # The package reference is user data and is Chinese on a Chinese job.
        pdf_style_for_text(styles["meta"], ref),
    )
    table = Table([[left, right]], colWidths=[USABLE_WIDTH * 0.55, USABLE_WIDTH * 0.45])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, -1), 0.8, colors.HexColor("#1a1a2e")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        )
    )
    return [table, Spacer(1, 6 * mm)]


def _info_table(styles: dict[str, ParagraphStyle], rows: list[tuple[str, str]]) -> Table:
    data = [[Paragraph(label, styles["label"]), _safe_para(value, styles["value"])] for label, value in rows]
    table = Table(data, colWidths=[42 * mm, USABLE_WIDTH - 42 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _addressee_rows(label: str, company_name: str, contact_email: str) -> list[tuple[str, str]]:
    """Who the letter is addressed to: the firm, and its contact when there is one.

    The bidder's contact address used to be printed under "Yours faithfully"
    and the signer's name, where it reads as the sender's address: a reader
    replying to the letter was pointed at the bidder's own inbox. It belongs to
    the addressee, and a letter to a bidder may legitimately carry it there, so
    it moves rather than goes.
    """
    rows = [(label, company_name)]
    if contact_email:
        rows.append(("Contact:", contact_email))
    return rows


def generate_award_letter_pdf(
    *,
    package_name: str,
    package_ref: str,
    project_name: str,
    company_name: str,
    contact_email: str,
    awarded_amount: str,
    currency: str,
    awarded_at: str | None = None,
    awarded_by_name: str | None = None,
    notes: str | None = None,
) -> bytes:
    """Render a letter of award for the winning bid.

    All money arrives as Decimal-as-string and is formatted at the
    presentation boundary only.
    """
    buffer = io.BytesIO()
    styles = _build_styles()
    letterhead = _letterhead()
    doc = _document(buffer, f"Letter of Award - {package_name}", letterhead_on_first_page=letterhead is not None)

    amount_dec = _to_decimal(awarded_amount)
    flow: list[Any] = []
    if letterhead is not None:
        flow.append(letterhead)
    flow.extend(_header_block(styles, "LETTER OF AWARD", package_ref, letterhead=letterhead))
    flow.append(Paragraph("Notification of Contract Award", styles["doc_title"]))

    flow.append(
        _info_table(
            styles,
            _addressee_rows("Awarded to:", company_name, contact_email)
            + [
                ("Project:", project_name or "-"),
                ("Tender package:", package_name),
                ("Award date:", _fmt_date(awarded_at)),
            ],
        )
    )
    flow.append(Spacer(1, 5 * mm))

    # Awarded amount, set off in a highlighted band.
    amount_tbl = Table(
        [
            [
                Paragraph("Awarded contract sum", styles["label"]),
                Paragraph(_fmt_money(amount_dec, currency), styles["value_right"]),
            ]
        ],
        colWidths=[USABLE_WIDTH * 0.6, USABLE_WIDTH * 0.4],
    )
    amount_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e8e8ee")),
                ("LINEABOVE", (0, 0), (-1, -1), 1, colors.HexColor("#1a1a2e")),
                ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#1a1a2e")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    flow.append(amount_tbl)
    flow.append(Spacer(1, 6 * mm))

    greeting = f"Dear {company_name}," if company_name else "Dear Sir or Madam,"
    flow.append(_safe_para(greeting, styles["body"]))
    flow.append(
        Paragraph(
            "We are pleased to inform you that, following evaluation of the bids received for the "
            "tender package above, your offer has been selected as the successful bid. The award is "
            "made for the contract sum stated above, subject to the terms of the tender documents and "
            "any agreed clarifications.",
            styles["body"],
        )
    )
    flow.append(
        Paragraph(
            "Please treat this letter as formal notification of our intention to enter into a contract "
            "with you. Our team will be in touch to formalise the contract documentation and confirm "
            "the programme.",
            styles["body"],
        )
    )

    if notes:
        flow.append(Spacer(1, 2 * mm))
        flow.append(Paragraph("<b>Notes</b>", styles["body"]))
        flow.append(_safe_para(notes, styles["note"]))

    flow.append(Paragraph("Yours faithfully,", styles["signoff"]))
    signer = awarded_by_name or project_name or "The Project Team"
    flow.append(_safe_para(signer, styles["value"]))

    doc.build(flow)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_rejection_letter_pdf(
    *,
    package_name: str,
    package_ref: str,
    project_name: str,
    company_name: str,
    contact_email: str,
    bid_amount: str | None = None,
    currency: str = "",
    winning_amount: str | None = None,
    rejected_at: str | None = None,
    signed_by_name: str | None = None,
    reason: str | None = None,
) -> bytes:
    """Render a rejection notice for an unsuccessful bidder.

    Optionally states the bidder's own submitted amount and the awarded sum
    (both Decimal-as-string) for transparency; both are formatted at the
    presentation boundary only.
    """
    buffer = io.BytesIO()
    styles = _build_styles()
    letterhead = _letterhead()
    doc = _document(buffer, f"Notice of Outcome - {package_name}", letterhead_on_first_page=letterhead is not None)

    flow: list[Any] = []
    if letterhead is not None:
        flow.append(letterhead)
    flow.extend(_header_block(styles, "NOTICE OF TENDER OUTCOME", package_ref, letterhead=letterhead))
    flow.append(Paragraph("Notification of Unsuccessful Bid", styles["doc_title"]))

    info_rows = [
        *_addressee_rows("Bidder:", company_name, contact_email),
        ("Project:", project_name or "-"),
        ("Tender package:", package_name),
        ("Date:", _fmt_date(rejected_at)),
    ]
    flow.append(_info_table(styles, info_rows))
    flow.append(Spacer(1, 5 * mm))

    greeting = f"Dear {company_name}," if company_name else "Dear Sir or Madam,"
    flow.append(_safe_para(greeting, styles["body"]))
    flow.append(
        Paragraph(
            "Thank you for the time and effort you invested in preparing your bid for the tender "
            "package above. Following a careful evaluation of all submissions, we regret to inform you "
            "that your bid has not been selected on this occasion.",
            styles["body"],
        )
    )

    # Optional transparency block: bidder's amount and the awarded sum.
    detail_rows: list[tuple[str, str]] = []
    if bid_amount is not None and bid_amount != "":
        detail_rows.append(("Your submitted bid:", _fmt_money(_to_decimal(bid_amount), currency)))
    if winning_amount is not None and winning_amount != "":
        detail_rows.append(("Awarded contract sum:", _fmt_money(_to_decimal(winning_amount), currency)))
    if detail_rows:
        flow.append(_info_table(styles, detail_rows))
        flow.append(Spacer(1, 4 * mm))

    if reason:
        flow.append(Paragraph("<b>Reason</b>", styles["body"]))
        flow.append(_safe_para(reason, styles["note"]))
        flow.append(Spacer(1, 2 * mm))

    flow.append(
        Paragraph(
            "We value your interest in working with us and would welcome your participation in future "
            "tender opportunities. Should you wish to discuss the outcome, please do not hesitate to "
            "contact us.",
            styles["body"],
        )
    )

    flow.append(Paragraph("Yours faithfully,", styles["signoff"]))
    signer = signed_by_name or project_name or "The Project Team"
    flow.append(_safe_para(signer, styles["value"]))

    doc.build(flow)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# ── Award record (Vergabevermerk) ────────────────────────────────────────────
# The filed document itself. Labels are English like every other PDF this
# module produces; "Vergabevermerk" appears as the document's own name, which is
# what an authority files it under.

_RECORD_SECTION_TITLES: dict[str, str] = {
    "subject": "1. Subject of the procurement",
    "estimated_value": "2. Estimated value",
    "procedure_type": "3. Type of procedure",
    "procedure_reason": "4. Reason for the type of procedure",
    "evaluation_criteria": "5. Award criteria",
    "participants": "6. Firms invited, and when the package went out",
    "bids_received": "7. Bids received",
    "exclusions": "8. Bids excluded, and on what ground",
    "evaluation": "9. Evaluation of the bids that remained",
    "award_decision": "10. Award",
    "award_reason": "11. Reason for the award decision",
}

_RECORD_FACT_LABELS: dict[str, str] = {
    "package_name": "Tender package",
    "project_name": "Project",
    "package_description": "Description",
    "bill_name": "Bill of quantities",
    "scope_sections": "Sections in scope",
    "scope_positions": "Positions in scope",
    "bill_positions": "Positions in the bill",
    "covers_whole_bill": "Scope against the bill",
    "deadline": "Submission deadline",
    "estimated_value": "Estimated value",
    "invited": "Invited",
    "invited_count": "Firms invited",
    "issued_at": "Issued",
    "distributed_at": "Sent to bidders",
    "bid": "Bid",
    "bid_count": "Bids received",
    "bid_status": "Bid",
    "excluded_count": "Bids excluded",
    "leveled_bid": "Levelled sum",
    "leveled_lines_imputed": "Lines imputed during levelling",
    "off_currency_excluded": "Bids left out on currency",
    "awarded_to": "Awarded to",
    "awarded_sum": "Awarded sum",
    "awarded_at": "Award date",
    "awarded_by": "Awarded by",
}


# The assembled record carries codes rather than words so that the screen can
# say them in the reader's language. This document is English by module
# convention, so it is where the codes get worded.
_RECORD_STATE_LABELS: dict[str, str] = {
    "whole_bill": "the whole bill",
    "part_of_bill": "part of the bill",
    "pending": "pending",
    "submitted": "submitted",
    "accepted": "accepted",
    "rejected": "rejected",
    "excluded": "excluded",
    "disqualified": "disqualified",
    "withdrawn": "withdrawn",
}

_RECORD_STAGE_LABELS: dict[str, str] = {
    "draft": "Draft",
    "issued": "Issued",
    "collecting": "Collecting bids",
    "evaluating": "Evaluating bids",
    "awarded": "Awarded",
    "closed": "Closed",
}


def _record_fact_value(fact: dict[str, Any]) -> str:
    """Render one assembled fact as a single readable value."""
    parts: list[str] = []
    text = str(fact.get("text") or "")
    if text:
        parts.append(text)
    amount = fact.get("amount")
    if amount not in (None, ""):
        parts.append(_fmt_money(_to_decimal(amount), str(fact.get("currency") or "")))
    count = fact.get("count")
    if count is not None:
        parts.append(str(count))
    at = fact.get("at")
    if at:
        parts.append(_fmt_date(str(at)))
    state = str(fact.get("state") or "")
    if state:
        parts.append(_RECORD_STATE_LABELS.get(state, state))
    return ", ".join(parts)


def generate_award_record_pdf(*, record: dict[str, Any], package_ref: str) -> bytes:
    """Render the award record for filing, at whatever stage it stands.

    Every stage is exportable, gaps included: a record filed halfway through a
    procedure is the normal case, and the open points are printed rather than
    hidden so the document never reads as complete when it is not. All values
    arriving from the procedure (company names, package names, statements) go
    through ``_safe_para`` before reportlab sees them.
    """
    buffer = io.BytesIO()
    styles = _build_styles()
    package_name = str(record.get("package_name") or "")
    letterhead = _letterhead()
    doc = _document(buffer, f"Vergabevermerk - {package_name}", letterhead_on_first_page=letterhead is not None)

    flow: list[Any] = []
    if letterhead is not None:
        flow.append(letterhead)
    flow.extend(_header_block(styles, "VERGABEVERMERK", package_ref, letterhead=letterhead))
    flow.append(Paragraph("Award record of the procurement procedure", styles["doc_title"]))

    gaps = [g for g in (record.get("gaps") or []) if isinstance(g, dict)]
    head_rows = [
        ("Tender package:", package_name),
        ("Project:", str(record.get("project_name") or "-")),
        ("Stage:", _RECORD_STAGE_LABELS.get(str(record.get("stage") or ""), str(record.get("stage") or "-"))),
        (
            "State of the record:",
            "Complete for this stage" if record.get("is_complete") else f"{len(gaps)} point(s) still open",
        ),
    ]
    flow.append(_info_table(styles, head_rows))
    flow.append(Spacer(1, 4 * mm))

    flow.append(
        Paragraph(
            "This record is assembled from the procurement procedure as it was carried out. The facts "
            "below are read from the procedure itself; the statements are those recorded by the "
            "contracting authority at the time. Sections still open at this stage are named as such "
            "rather than left blank.",
            styles["body"],
        )
    )

    if gaps:
        flow.append(Paragraph("<b>Still open at this stage</b>", styles["body"]))
        for gap in gaps:
            title = _RECORD_SECTION_TITLES.get(str(gap.get("section") or ""), str(gap.get("section") or ""))
            flow.append(_safe_para(title, styles["note"]))
        flow.append(Spacer(1, 3 * mm))

    for section in record.get("sections") or []:
        key = str(section.get("key") or "")
        flow.append(Paragraph(html.escape(_RECORD_SECTION_TITLES.get(key, key)), styles["doc_title"]))

        rows = [
            (f"{_RECORD_FACT_LABELS.get(str(fact.get('key') or ''), str(fact.get('key') or ''))}:", value)
            for fact in section.get("facts") or []
            if (value := _record_fact_value(fact))
        ]
        # reportlab raises on a table with no rows, and an early record has
        # several sections with nothing in them yet.
        if rows:
            flow.append(_info_table(styles, rows))

        state = str(section.get("state") or "")
        statement = str(section.get("statement") or "")
        if statement:
            flow.append(Spacer(1, 2 * mm))
            flow.append(_safe_para(statement, styles["note"]))
            recorded = str(section.get("recorded_at") or "")
            if recorded:
                flow.append(_safe_para(f"Recorded {_fmt_date(recorded)}", styles["label"]))
        elif state == "missing":
            flow.append(Paragraph("Not yet recorded.", styles["note"]))
        elif state == "not_due_yet":
            flow.append(Paragraph("The procedure has not reached this stage.", styles["note"]))

        for earlier in section.get("superseded") or []:
            earlier_text = str(earlier.get("text") or "")
            if not earlier_text:
                continue
            earlier_at = str(earlier.get("recorded_at") or "")
            dated = f" of {_fmt_date(earlier_at)}" if earlier_at else ""
            flow.append(_safe_para(f"Superseded statement{dated}: {earlier_text}", styles["label"]))
        flow.append(Spacer(1, 2 * mm))

    doc.build(flow)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def _fmt_date(iso_str: str | None) -> str:
    """Render an ISO timestamp as ``dd.mm.YYYY``; fall back to today / raw."""
    if not iso_str:
        return datetime.now(tz=UTC).strftime("%d.%m.%Y")
    try:
        normalized = iso_str.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return str(iso_str)


__all__ = ["generate_award_letter_pdf", "generate_award_record_pdf", "generate_rejection_letter_pdf"]
