# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable PDF for a single RFI.

An RFI leaves the platform as a document: it is sent to the design team,
printed for a coordination meeting and filed with the contract. Before this
module the only way to get one on paper was the browser's print command on
the detail page, which printed the web layout over three A4 sheets for a
short RFI, dropped the project name (it lives in the breadcrumb, which the
print stylesheet hides) and split the meta panel across page breaks.

The layout is a conventional RFI form, black on white so it prints well on
an office printer:

- The firm's letterhead, when the company profile has one (some firms may not
  send an RFI without their formal logo and registered details on it).
- Header: document title, RFI number and project, status on the right.
- Subject, then a label/value grid: project, raised by, assigned to, dates,
  ball in court, priority and discipline.
- Question, boxed.
- Referenced documents and the number of attached files, when present.
- Impact: cost (with the project's currency) and schedule (in days).
- Official response, boxed, with who answered and when. An RFI without an
  answer gets an empty box instead, so a printed copy can be answered by hand.
- Linked change order, when one was raised from the answer.
- Signature lines for the person who raised the RFI and the one who answered.
- Footer: workspace brand, generated timestamp and page number, following the
  workspace's document appearance (its own footer line, footer colour, page
  numbers on or off); the workspace logo, if any, sits top right, except on a
  first page that already carries it in the letterhead.

The renderer is pure: it takes the RFI row plus already-resolved names and
never touches the database, so the service does the lookups and the tests can
drive it with a plain namespace.

Every string that comes from a user (subject, question, response, names,
document names) is escaped before it reaches reportlab's Paragraph parser and
gets its face from :func:`app.core.pdf_fonts.pdf_style_for_text`, so markup is
printed inert and Chinese, Thai or Arabic text renders as glyphs.
"""

from __future__ import annotations

import html
import io
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.pdf_branding import (
    branded_appearance,
    branded_cover_brand,
    branded_doc_metadata,
    branded_header_logo,
    branded_letterhead,
)
from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_fit_line,
    pdf_fitted_style,
    pdf_style_for_text,
    pdf_table_paragraph_rows,
    register_pdf_fonts,
)
from app.core.regional_format import number_style
from app.core.register_export import FURNITURE, country_date_format, format_amount, printed_currency
from app.modules.rfi.intl import localize_discipline, localize_status
from app.modules.rfi.pdf_translations import (
    DEFAULT_PDF_LOCALE,
    days_text,
    format_date,
    normalize_pdf_locale,
    page_of_total,
    priority_label,
    status_caps,
    tr,
)

register_pdf_fonts()

# Always A4 with these margins, whatever the document appearance holds: the
# column widths below are millimetre literals summing to this usable width.
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 20 * mm
MARGIN_RIGHT = 20 * mm
# The workspace logo is drawn from 8 mm below the top edge and is at most
# 22 pt (about 7.8 mm) tall, so the body can start at 18 mm without touching it.
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 18 * mm
USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

_INK = colors.HexColor("#16213e")
_MUTED = colors.HexColor("#666666")
_RULE = colors.HexColor("#cccccc")
_LABEL_FILL = colors.HexColor("#f4f5f7")

# Height of the empty answer box printed for an RFI nobody has answered yet,
# enough for a few handwritten lines.
_BLANK_ANSWER_HEIGHT = 35 * mm
# Height of a signature row, enough to sign in.
_SIGNATURE_ROW_HEIGHT = 10 * mm
# Space a section that may run long needs left on the page before it starts
# there: its heading plus the first few lines of the box under it.
_LONG_SECTION_MIN_ROOM = 30 * mm


def _styles() -> dict[str, ParagraphStyle]:
    """Paragraph styles for the RFI form."""
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("RfiTitle", parent=base, fontName=BOLD_FONT, fontSize=17, leading=21, textColor=_INK),
        "sub": ParagraphStyle("RfiSub", parent=base, fontName=BODY_FONT, fontSize=10, leading=13, textColor=_MUTED),
        "status": ParagraphStyle(
            "RfiStatus", parent=base, fontName=BOLD_FONT, fontSize=10, leading=12, textColor=_INK, alignment=TA_CENTER
        ),
        "subject": ParagraphStyle(
            "RfiSubject",
            parent=base,
            fontName=BOLD_FONT,
            fontSize=13,
            leading=17,
            textColor=_INK,
            spaceBefore=5 * mm,
            spaceAfter=4 * mm,
        ),
        "section": ParagraphStyle(
            "RfiSection",
            parent=base,
            fontName=BOLD_FONT,
            fontSize=11,
            leading=14,
            textColor=_INK,
            spaceBefore=4 * mm,
            spaceAfter=1.8 * mm,
        ),
        "label": ParagraphStyle(
            "RfiLabel", parent=base, fontName=BODY_FONT, fontSize=8.5, leading=11, textColor=_MUTED
        ),
        "value": ParagraphStyle("RfiValue", parent=base, fontName=BODY_FONT, fontSize=9.5, leading=12, textColor=_INK),
        "body": ParagraphStyle(
            "RfiBody",
            parent=base,
            fontName=BODY_FONT,
            fontSize=10,
            leading=14,
            textColor=colors.black,
            alignment=TA_LEFT,
        ),
        "muted": ParagraphStyle("RfiMuted", parent=base, fontName=BODY_FONT, fontSize=9, leading=12, textColor=_MUTED),
        "head": ParagraphStyle("RfiHead", parent=base, fontName=BOLD_FONT, fontSize=8.5, leading=11, textColor=_INK),
    }


def _para(text: Any, style: ParagraphStyle) -> Paragraph:
    """A Paragraph for user-supplied text: escaped, newlines kept, face per script."""
    rendered = "" if text is None else str(text)
    markup = html.escape(rendered, quote=True).replace("\n", "<br/>")
    return Paragraph(markup, pdf_style_for_text(style, rendered))


def _section(
    title: str, body: list[Any], styles: dict[str, ParagraphStyle], *, may_run_long: bool = False
) -> list[Any]:
    """A section heading plus its body, never with the heading orphaned.

    A short section is one KeepTogether. A section that may run long (the
    question, the answer, a list of documents) cannot be: reportlab moves a
    KeepTogether that does not fit to the next page however much room is
    left, and a question longer than the rest of page one then left page one
    empty below the grid. It starts where it is instead, once there is room
    for the heading and the first lines under it, and splits across pages.

    Args:
        title: The heading text.
        body: Flowables under the heading.
        styles: The form's paragraph styles.
        may_run_long: Whether the body can be taller than a page.

    Returns:
        Flowables to append to the story.
    """
    heading = Paragraph(html.escape(title), pdf_style_for_text(styles["section"], title))
    if may_run_long:
        return [CondPageBreak(_LONG_SECTION_MIN_ROOM), heading, *body]
    return [KeepTogether([heading, *body])]


def _person(value: Any, people: Mapping[str, str]) -> str:
    """Display name for a stored user id.

    An id the lookup could not resolve (a deleted account) prints a dash, as
    it does on the registers: any part of a UUID is a machine identifier, and
    on a document meant for people it reads as a broken export.
    """
    if value is None or str(value).strip() == "":
        return "-"
    key = str(value)
    return people.get(key) or "-"


def _boxed(flowables: list[Any], *, min_height: float | None = None) -> Table:
    """One bordered cell holding ``flowables``; long content splits across pages."""
    table = Table(
        [[flowables]],
        colWidths=[USABLE_WIDTH],
        rowHeights=[min_height] if min_height else None,
        # A question or an answer is Text with no length limit. reportlab
        # refuses a row taller than the frame unless it may split it, and the
        # export would answer 500 instead of printing a long RFI.
        splitInRow=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
                # A box cut by a page break is closed at the cut and opened
                # again on the next page, so neither half reads as running
                # off the sheet.
                ("LINEBELOW", (0, "splitlast"), (-1, "splitlast"), 0.6, _RULE),
                ("LINEABOVE", (0, "splitfirst"), (-1, "splitfirst"), 0.6, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    return table


def _label_value_table(rows: list[list[str]], styles: dict[str, ParagraphStyle], col_widths: list[float]) -> Table:
    """A grid whose even columns are labels and odd columns are values."""

    def _style_for(_row: int, col: int) -> ParagraphStyle:
        return styles["label"] if col % 2 == 0 else styles["value"]

    table = Table(
        pdf_table_paragraph_rows(rows, styles["value"], style_for=_style_for),
        colWidths=col_widths,
    )
    commands: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.5, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]
    for col in range(0, len(col_widths), 2):
        commands.append(("BACKGROUND", (col, 0), (col, -1), _LABEL_FILL))
    table.setStyle(TableStyle(commands))
    return table


def _yes_no(flag: Any, detail: str | None, locale: str) -> str:
    if not flag:
        return tr(locale, "no")
    return tr(locale, "yes_with", detail=detail) if detail else tr(locale, "yes")


def _make_page_callback(
    generated: str,
    locale: str,
    *,
    appearance: Mapping[str, Any] | None = None,
    letterhead_on_first_page: bool = False,
    total_pages: int = 0,
    running_title: str = "",
) -> Any:
    """``onPage`` callback: footer on every page, workspace logo top right.

    The footer stays this module's own rather than the shared one because it is
    translated, but it follows the workspace's document appearance: a saved
    footer line replaces the brand and timestamp, the footer colour colours it,
    and page numbers can be switched off.

    Args:
        generated: The timestamp printed in the default footer line.
        locale: Document language.
        appearance: The document appearance, read once for the whole document.
        letterhead_on_first_page: Whether page one opens with the letterhead,
            decided once by the caller. The letterhead already carries the
            logo, so the small header logo is left off that page.
        total_pages: The page count from the first build pass, printed as
            "page x of y" like every other document of the set.
        running_title: The form's title and RFI number, printed top left on
            every page after the first so a loose sheet can be put back.
    """
    look = appearance or {}
    running_style = ParagraphStyle("RfiRunningTitle", fontName=BOLD_FONT, fontSize=8, leading=10, textColor=_MUTED)
    footer_left = ParagraphStyle(
        "RfiFooter",
        fontName=BODY_FONT,
        fontSize=7,
        leading=8,
        textColor=colors.HexColor(look.get("footer_color") or "#999999"),
    )
    footer_right = ParagraphStyle("RfiFooterRight", parent=footer_left, alignment=TA_RIGHT)
    page_box = 40 * mm
    custom_footer = str(look.get("footer_text") or "").strip()
    show_page_numbers = look.get("show_page_numbers", True) is not False

    def _draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_LEFT, 13 * mm, PAGE_WIDTH - MARGIN_RIGHT, 13 * mm)
        # Paragraphs rather than drawString, so a Thai or Devanagari brand
        # name is shaped instead of mis-arranged. A saved footer line is the
        # workspace's own words, so it is printed as saved, untranslated.
        # Fitted onto one line rather than wrapped: the paragraph is anchored by
        # its top, so a legal name long enough to take a second line would put
        # that line on the bottom edge of the sheet.
        left_text, _left_face, left_size = pdf_fit_line(
            custom_footer or branded_cover_brand(),
            USABLE_WIDTH - page_box - 2 * mm,
            suffix="" if custom_footer else f"  |  {tr(locale, 'footer_generated', timestamp=generated)}",
            base=BODY_FONT,
        )
        left = Paragraph(html.escape(left_text, quote=True), pdf_fitted_style(footer_left, left_text, left_size))
        _, left_h = left.wrapOn(canvas, USABLE_WIDTH - page_box - 2 * mm, 20)
        left.drawOn(canvas, MARGIN_LEFT, 9 * mm - left_h + 2)
        if show_page_numbers:
            page_text = page_of_total(doc.page, max(total_pages, doc.page), locale)
            right = Paragraph(html.escape(page_text, quote=True), pdf_style_for_text(footer_right, page_text))
            _, right_h = right.wrapOn(canvas, page_box, 20)
            right.drawOn(canvas, PAGE_WIDTH - MARGIN_RIGHT - page_box, 9 * mm - right_h + 2)
        if running_title and doc.page > 1:
            head_text, _head_face, head_size = pdf_fit_line(
                running_title, USABLE_WIDTH - 50 * mm, size=8.0, bold=True, base=BOLD_FONT
            )
            head = Paragraph(html.escape(head_text, quote=True), pdf_fitted_style(running_style, head_text, head_size))
            _, head_h = head.wrapOn(canvas, USABLE_WIDTH, 20)
            head.drawOn(canvas, MARGIN_LEFT, PAGE_HEIGHT - 9 * mm - head_h)
        canvas.restoreState()
        if not (letterhead_on_first_page and doc.page == 1):
            branded_header_logo(canvas, doc)

    return _draw


def build_rfi_pdf(
    rfi: Any,
    *,
    project_name: str,
    project_code: str | None = None,
    currency: str = "",
    country: str | None = None,
    people: Mapping[str, str] | None = None,
    documents: Sequence[str] = (),
    unavailable_documents: int = 0,
    variation: str | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
) -> bytes:
    """Render one RFI as a printable PDF.

    Args:
        rfi: The :class:`~app.modules.rfi.models.RFI` row, or any object with
            the same attributes.
        project_name: Owning project's name, printed in the header and grid.
        project_code: Project code, appended to the name when set.
        currency: ISO code of the project's currency. The cost impact amount
            is stored in that currency, so it is printed next to it.
        country: ISO 3166-1 alpha-2 of the project's country, when known. It
            decides the separators the amount is written with; without it the
            currency does.
        people: Display names keyed by ``str(user_id)`` for everyone the RFI
            names (raised by, assigned to, ball in court, answered by).
        documents: Names of the linked documents that still exist.
        unavailable_documents: How many linked ids no longer resolve.
        variation: Label of the change order raised from this RFI, if any.
        locale: Document language; unsupported values fall back to English.

    Returns:
        The PDF as bytes, starting with ``b"%PDF"``.
    """
    locale = normalize_pdf_locale(locale)
    context = {
        "project_name": project_name,
        "project_code": project_code,
        "currency": currency,
        "country": country,
        "people": people,
        "documents": documents,
        "unavailable_documents": unavailable_documents,
        "variation": variation,
        "locale": locale,
    }
    # The footer stamp writes its date like every other date on the form.
    stamp_format = tr(locale, "datetime_format")
    country_format = country_date_format(country) if locale in FURNITURE else None
    if country_format:
        stamp_format = stamp_format.replace("%Y-%m-%d", country_format)
    generated = datetime.now(tz=UTC).strftime(stamp_format)
    meta = branded_doc_metadata()
    appearance = branded_appearance(doc_type="rfi")
    # Built twice, like the registers: the first pass counts the pages, the
    # second prints "page x of y" with the real total.
    total_pages = 0
    output = b""
    for _pass in range(2):
        flow, has_letterhead, rfi_number, subject, project_label = _rfi_flow(rfi, **context)
        title = f"{tr(locale, 'doc_title')} {rfi_number}".strip()
        buffer = io.BytesIO()
        doc = BaseDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=MARGIN_LEFT,
            rightMargin=MARGIN_RIGHT,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            title=title,
            author=meta["author"],
            subject=subject,
            creator=meta["creator"],
            producer=meta["producer"],
            keywords=meta["keywords"],
        )
        # No inner padding: a Frame pads by 6 pt by default, which set every
        # paragraph 6 pt to the right of the full-width tables under it.
        frame = Frame(
            MARGIN_LEFT,
            MARGIN_BOTTOM,
            USABLE_WIDTH,
            PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="body",
        )
        on_page = _make_page_callback(
            generated,
            locale,
            appearance=appearance,
            letterhead_on_first_page=has_letterhead,
            total_pages=total_pages,
            running_title=" · ".join(part for part in (title, project_label) if part and part != "-"),
        )
        doc.addPageTemplates([PageTemplate(id="body", frames=[frame], onPage=on_page)])
        doc.build(flow)
        total_pages = doc.page
        output = buffer.getvalue()
    return output


def _rfi_flow(
    rfi: Any,
    *,
    project_name: str,
    project_code: str | None,
    currency: str,
    country: str | None,
    people: Mapping[str, str] | None,
    documents: Sequence[str],
    unavailable_documents: int,
    variation: str | None,
    locale: str,
) -> tuple[list[Any], bool, str, str, str]:
    """The form's flowables for one build pass; see :func:`build_rfi_pdf` for the arguments.

    Returns:
        The story, whether it opens with the letterhead, the RFI number, the
        subject and the project label.
    """
    people = people or {}
    styles = _styles()
    # Figures follow the project's market, words follow the language: with a
    # country on file the dates are written its way, as the registers do.
    # Only in the languages the registers print in: the other thirty-one
    # write a date in their own script, which a numeric pattern would undo.
    date_format = country_date_format(country) if locale in FURNITURE else None

    rfi_number = str(getattr(rfi, "rfi_number", "") or "")
    subject = str(getattr(rfi, "subject", "") or "")
    status = str(getattr(rfi, "status", "") or "draft")
    project_label = project_name or "-"
    if project_code:
        project_label = f"{project_label} ({project_code})"

    flow: list[Any] = []

    # The firm's letterhead, when the company profile has one. Decided here,
    # once: the page callback reads this answer rather than asking again, so
    # page one can never end up with the logo twice or not at all.
    letterhead = branded_letterhead(USABLE_WIDTH, doc_type="rfi")
    if letterhead is not None:
        flow.append(letterhead)

    # Header: title and "RFI-007 · Project" on the left, status on the right.
    header_left = [
        Paragraph(html.escape(tr(locale, "doc_title")), pdf_style_for_text(styles["title"], tr(locale, "doc_title"))),
        _para(f"{rfi_number} · {project_label}", styles["sub"]),
    ]
    status_text = status_caps(localize_status(status, locale), locale)
    header = Table(
        [[header_left, _para(status_text, styles["status"])]],
        colWidths=[USABLE_WIDTH - 38 * mm, 38 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("BOX", (1, 0), (1, 0), 0.8, _INK),
                ("TOPPADDING", (1, 0), (1, 0), 2 * mm),
                ("BOTTOMPADDING", (1, 0), (1, 0), 2 * mm),
                ("LINEBELOW", (0, 0), (-1, 0), 1.5, _INK),
                ("BOTTOMPADDING", (0, 0), (0, 0), 3 * mm),
            ]
        )
    )
    flow.append(header)
    flow.append(_para(subject, styles["subject"]))

    # Label/value grid.
    discipline = getattr(rfi, "discipline", None)
    priority = getattr(rfi, "priority", None)
    grid_rows = [
        [tr(locale, "project"), project_label, "", ""],
        [
            tr(locale, "raised_by"),
            _person(getattr(rfi, "raised_by", None), people),
            tr(locale, "assigned_to"),
            _person(getattr(rfi, "assigned_to", None), people),
        ],
        [
            tr(locale, "date_raised"),
            format_date(getattr(rfi, "created_at", None), locale, date_format),
            tr(locale, "response_due"),
            format_date(getattr(rfi, "response_due_date", None), locale, date_format),
        ],
        [
            tr(locale, "date_required"),
            format_date(getattr(rfi, "date_required", None), locale, date_format),
            tr(locale, "ball_in_court"),
            _person(getattr(rfi, "ball_in_court", None), people),
        ],
        [
            tr(locale, "priority"),
            priority_label(priority, locale) if priority else "-",
            tr(locale, "discipline"),
            localize_discipline(discipline, locale) if discipline else "-",
        ],
    ]
    grid = _label_value_table(grid_rows, styles, [32 * mm, 53 * mm, 32 * mm, 53 * mm])
    # The project row spans the three value columns; the label fill that
    # column 2 carries elsewhere must not show through the span.
    grid.setStyle(TableStyle([("SPAN", (1, 0), (3, 0)), ("BACKGROUND", (1, 0), (3, 0), colors.white)]))
    flow.append(grid)

    # Question.
    question_box = _boxed([_para(getattr(rfi, "question", "") or "", styles["body"])])
    flow.extend(_section(tr(locale, "question"), [question_box], styles, may_run_long=True))

    # Referenced documents and attached files.
    attachment_count = len(getattr(rfi, "attachments", None) or [])
    if documents or unavailable_documents or attachment_count:
        refs: list[Any] = [_para(f"•  {name}", styles["value"]) for name in documents]
        if unavailable_documents:
            refs.append(_para(tr(locale, "references_unavailable", count=unavailable_documents), styles["muted"]))
        if attachment_count:
            if refs:
                refs.append(Spacer(1, 1.5 * mm))
            refs.append(_para(f"{tr(locale, 'attachments')}: {attachment_count}", styles["value"]))
        flow.extend(_section(tr(locale, "references"), refs, styles, may_run_long=True))

    # Impact.
    cost_value = str(getattr(rfi, "cost_impact_value", None) or "").strip()
    cost_detail = None
    if cost_value:
        # Written the way the project's market writes an amount (1.234,56 for
        # a lira or a euro). The column is free text, so a value that is not a
        # number is printed as it was typed.
        cost_detail = format_amount(cost_value, number_style(country, currency), currency, locale=locale)
        if cost_detail == "-":
            cost_detail = f"{cost_value} {printed_currency(currency, locale)}".strip()
    schedule_days = getattr(rfi, "schedule_impact_days", None)
    schedule_detail = days_text(int(schedule_days), locale) if isinstance(schedule_days, int) else None
    impact_rows = [
        [tr(locale, "cost_impact"), _yes_no(getattr(rfi, "cost_impact", False), cost_detail, locale)],
        [tr(locale, "schedule_impact"), _yes_no(getattr(rfi, "schedule_impact", False), schedule_detail, locale)],
    ]
    impact_table = _label_value_table(impact_rows, styles, [45 * mm, USABLE_WIDTH - 45 * mm])
    flow.extend(_section(tr(locale, "impact"), [impact_table], styles))

    # Official response.
    response = str(getattr(rfi, "official_response", None) or "")
    if response.strip():
        response_box = _boxed([_para(response, styles["body"])])
    else:
        response_box = _boxed([_para(tr(locale, "no_response"), styles["muted"])], min_height=_BLANK_ANSWER_HEIGHT)
    flow.extend(_section(tr(locale, "response"), [response_box], styles, may_run_long=True))
    responded_by = getattr(rfi, "responded_by", None)
    responded_at = getattr(rfi, "responded_at", None)
    if responded_by or responded_at:
        flow.append(Spacer(1, 2 * mm))
        flow.append(
            _label_value_table(
                [
                    [
                        tr(locale, "answered_by"),
                        _person(responded_by, people),
                        tr(locale, "answer_date"),
                        format_date(responded_at, locale, date_format),
                    ]
                ],
                styles,
                [32 * mm, 53 * mm, 32 * mm, 53 * mm],
            )
        )

    if variation:
        flow.append(Spacer(1, 3 * mm))
        flow.append(_para(f"{tr(locale, 'variation')}: {variation}", styles["value"]))

    # Signatures, prefilled with the names the platform knows.
    answered_name = _person(responded_by, people) if responded_by else ""
    sign_rows = [
        ["", tr(locale, "name"), tr(locale, "signature"), tr(locale, "date")],
        [tr(locale, "raised_by"), _person(getattr(rfi, "raised_by", None), people), "", ""],
        [tr(locale, "answered_by"), answered_name, "", ""],
    ]

    def _sign_style(row: int, col: int) -> ParagraphStyle | None:
        if row == 0:
            return styles["head"]
        return styles["label"] if col == 0 else styles["value"]

    signatures = Table(
        pdf_table_paragraph_rows(sign_rows, styles["value"], style_for=_sign_style),
        colWidths=[32 * mm, 55 * mm, 53 * mm, 30 * mm],
        rowHeights=[None, _SIGNATURE_ROW_HEIGHT, _SIGNATURE_ROW_HEIGHT],
    )
    signatures.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, _RULE),
                ("BACKGROUND", (0, 0), (-1, 0), _LABEL_FILL),
                ("BACKGROUND", (0, 1), (0, -1), _LABEL_FILL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ]
        )
    )
    flow.extend(_section(tr(locale, "signatures"), [signatures], styles))
    return flow, letterhead is not None, rfi_number, subject, project_label
