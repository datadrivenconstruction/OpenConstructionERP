# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PDF report generation for BOQ cost estimates.

Produces a professional multi-page PDF document with:
- Cover page: project name, BOQ title, cost summary, date, status
- BOQ table pages: sections, positions, subtotals, markups, totals
- Running headers/footers with page numbering

Security note (BUG-PDF01 / BUG-PDF02):
    ReportLab's ``Paragraph`` parses a subset of HTML (``<b>``, ``<i>``,
    ``<font color>``, ``<para>``, etc.). Passing a user-supplied string
    that contains unknown HTML attributes (``onerror``, ``onclick``)
    crashes ``paraparser`` with a ``ValueError``, which propagated as a
    500 from the ``/export/pdf`` endpoint and made the entire reporting
    feature DoSable by anyone with ``boq.update`` rights. Worse, valid
    markup like ``<font color="white">hidden</font>`` rendered in the
    output, allowing a malicious description to hide content in print.

    The fix is to escape every user-controlled string with ``html.escape``
    before handing it to ``Paragraph``. The helper below ``_safe_para``
    does both: coerces non-strings, escapes, then constructs the
    paragraph. Internal labels that legitimately use ReportLab markup
    (``<b>Pos.</b>``, ``&nbsp;`` indentation) bypass it and continue to
    use ``Paragraph`` directly.
"""

import html
import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.pdf_branding import branded_cover_brand, branded_doc_metadata, branded_header_logo
from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_font_for_text,
    pdf_style_for_text,
    register_pdf_fonts,
)
from app.core.unit_conversion import convert as convert_units
from app.core.unit_conversion import display_rate

# Register the bundled Unicode (DejaVu) faces with reportlab. Idempotent and
# safe at import time because reportlab is imported at module level here.
register_pdf_fonts()

# Page dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 20 * mm
MARGIN_RIGHT = 20 * mm
MARGIN_TOP = 25 * mm
MARGIN_BOTTOM = 20 * mm
USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

# Column widths for the BOQ table (Pos | Description | Unit | Qty | Rate | Total)
COL_POS = 35 * mm
COL_DESC = USABLE_WIDTH - 35 * mm - 20 * mm - 25 * mm - 30 * mm - 30 * mm
COL_UNIT = 20 * mm
COL_QTY = 25 * mm
COL_RATE = 30 * mm
COL_TOTAL = 30 * mm
TABLE_COL_WIDTHS = [COL_POS, COL_DESC, COL_UNIT, COL_QTY, COL_RATE, COL_TOTAL]


def _fmt(value: float, decimals: int = 2, currency: str = "") -> str:
    """Format a number with thousands separator and fixed decimals.

    When *currency* is provided, uses locale-aware formatting:
    - EUR (German/DACH): 1.234,56  (dot=thousands, comma=decimal)
    - USD/GBP (Anglo):   1,234.56  (comma=thousands, dot=decimal)
    - CHF (Swiss):       1'234.56  (apostrophe=thousands, dot=decimal)

    Falls back to international style (comma thousands, dot decimal) when
    the currency is unknown or empty.
    """
    if currency and currency.upper() == "EUR":
        raw = f"{value:,.{decimals}f}"
        return raw.replace(",", "THOU").replace(".", ",").replace("THOU", ".")
    if currency and currency.upper() == "CHF":
        raw = f"{value:,.{decimals}f}"
        return raw.replace(",", "'")
    return f"{value:,.{decimals}f}"


def _safe_para(text: Any, style: ParagraphStyle) -> "Paragraph":
    """Construct a ``Paragraph`` from possibly-untrusted user input.

    HTML metacharacters in ``text`` are escaped via ``html.escape`` so
    ReportLab's paraparser sees inert characters, not markup. ``None``
    becomes empty; other non-string values are rendered through ``str``
    before escaping. Use this anywhere a value originated outside the
    application's control (BOQ position descriptions, ordinals, units,
    section titles, the ``prepared_by`` field, project names, etc.).

    Internal labels that need ReportLab inline markup such as ``<b>...</b>``
    or ``&nbsp;`` indentation construct ``Paragraph`` directly - that text
    is checked into source and trusted.

    This is also where the Chinese face is chosen. Every string a Chinese bill
    of quantities carries - the section titles, the item descriptions, the unit
    labels, the markup names - reaches the document through here, so asking
    ``pdf_style_for_text`` for the face once, at the funnel, wires the whole
    generator rather than each call site. The style handed in is returned
    unchanged for anything that is not Chinese.
    """
    if text is None:
        rendered = ""
    elif isinstance(text, str):
        rendered = text
    else:
        rendered = str(text)
    return Paragraph(html.escape(rendered, quote=True), pdf_style_for_text(style, rendered))


def _fmt_currency(value: float, currency: str, decimals: int = 2) -> str:
    """Format a monetary amount with currency code appended.

    Examples:
        _fmt_currency(1234.56, "EUR") -> "1.234,56 EUR"
        _fmt_currency(1234.56, "USD") -> "1,234.56 USD"
        _fmt_currency(1234.56, "GBP") -> "1,234.56 GBP"
    """
    formatted = _fmt(value, decimals, currency)
    return f"{formatted} {currency}"


def _tax_label(markup: Any, currency: str) -> str:
    """A tax line's own name and rate, so a stack of several stays readable.

    Two decimals rather than the one the other markup rows use, because a rate
    like Brazil's 3.65 loses its meaning when rounded to 3.7.
    """
    if getattr(markup, "markup_type", "") == "percentage":
        return f"{markup.name} ({_fmt(markup.percentage, 2, currency)}%)"
    return str(markup.name)


def _tax_split(boq_data: Any) -> tuple[list[Any], Decimal, Decimal, Decimal]:
    """Split a priced bill into its pre-tax subtotal, its tax lines and its total.

    The tax is already inside ``net_total``. ``get_boq_structured`` computes
    ``net_total = direct_cost + sum(every active markup)`` and sets
    ``grand_total`` to exactly that, and the markup calculator has no notion of
    a tax category, so a VAT line is one markup among the others. The exports
    here used to read that figure as if it were net OF tax and add a tax on top
    of it, which overstated a German bill by the whole nineteen per cent and
    printed a Gross Total the application itself never agreed with.

    Two things follow and both are the caller's to honour: the pre-tax subtotal
    is ``net_total`` MINUS the tax rather than plus, and the total of everything
    is ``net_total`` unchanged.

    ``tax_lines`` is every active tax markup rather than the first one found.
    Brazil's stack carries two, PIS + COFINS and ISS, and stopping at the first
    dropped the second from the tax section while its money stayed inside the
    total, so the printed figures did not add up down the column.

    Returns ``(tax_lines, tax_amount, subtotal_excluding_tax, gross_total)``.
    """
    markups = getattr(boq_data, "markups", None) or []
    tax_lines = [m for m in markups if getattr(m, "category", "") == "tax" and m.is_active]
    tax_amount = sum((Decimal(str(m.amount)) for m in tax_lines), Decimal("0"))
    gross_total = Decimal(str(boq_data.net_total))
    return tax_lines, tax_amount, gross_total - tax_amount, gross_total


def _build_styles() -> dict[str, ParagraphStyle]:
    """Build the set of paragraph styles used throughout the PDF."""
    base = getSampleStyleSheet()

    return {
        "brand": ParagraphStyle(
            "Brand",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=6 * mm,
        ),
        "title": ParagraphStyle(
            "CoverTitle",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=18,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#16213e"),
            spaceAfter=4 * mm,
        ),
        "subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"),
            spaceAfter=2 * mm,
        ),
        "info_label": ParagraphStyle(
            "InfoLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=10,
            textColor=colors.HexColor("#666666"),
            alignment=TA_LEFT,
        ),
        "info_value": ParagraphStyle(
            "InfoValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=10,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_LEFT,
        ),
        "summary_label": ParagraphStyle(
            "SummaryLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=11,
            textColor=colors.HexColor("#333333"),
            alignment=TA_LEFT,
        ),
        "summary_value": ParagraphStyle(
            "SummaryValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=11,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_RIGHT,
        ),
        "summary_total_label": ParagraphStyle(
            "SummaryTotalLabel",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=12,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_LEFT,
        ),
        "summary_total_value": ParagraphStyle(
            "SummaryTotalValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=12,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_RIGHT,
        ),
        "section_header": ParagraphStyle(
            "SectionHeader",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=9,
            textColor=colors.HexColor("#1a1a2e"),
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            leading=10,
        ),
        "cell_right": ParagraphStyle(
            "CellRight",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        "cell_bold_right": ParagraphStyle(
            "CellBoldRight",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        # The header row of the position table and of the section summary. A
        # TableStyle TEXTCOLOR cannot reach a cell that holds a Paragraph, so
        # the colour of a header has to live on the header's own style. It did
        # not, and the row was drawn in the colour of the text below it: on the
        # #1a1a2e header fill, "Pos.", "Description" and "Unit" came out
        # #1a1a2e, the same colour they were standing on.
        #
        # Sizes are the ones these two rows already rendered at, 9pt on the
        # left and 8pt on the right to match their columns. The table style
        # also carried a FONTSIZE of 9 for the whole row, equally unable to
        # act; honouring that as well would resize the right hand headings and
        # move the table without making anything more readable.
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=9,
            textColor=colors.white,
        ),
        "table_header_right": ParagraphStyle(
            "TableHeaderRight",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.white,
            alignment=TA_RIGHT,
            leading=10,
        ),
        "subtotal_label": ParagraphStyle(
            "SubtotalLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#444444"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        "subtotal_value": ParagraphStyle(
            "SubtotalValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=7,
            textColor=colors.HexColor("#999999"),
        ),
    }


def _make_header_footer(
    project_name: str,
    boq_name: str,
    generated_date: str,
) -> tuple[Any, Any]:
    """Return (header_func, footer_func) for table pages.

    These callables follow the reportlab PageTemplate onPage signature:
    ``func(canvas, doc)``.
    """

    def _header(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#666666"))
        # Plain hyphen separator (never an em dash) per the project text rule.
        text = f"{project_name}  -  {boq_name}"
        # The running header carries the project and bill names, which are the
        # two strings most likely to be Chinese on a Chinese job, so the face
        # is picked from the text rather than fixed to the Latin body face.
        canvas.setFont(pdf_font_for_text(text), 8)
        canvas.drawString(MARGIN_LEFT, PAGE_HEIGHT - 15 * mm, text)
        # Thin line under header
        canvas.setStrokeColor(colors.HexColor("#cccccc"))
        canvas.setLineWidth(0.5)
        line_y = PAGE_HEIGHT - 17 * mm
        canvas.line(MARGIN_LEFT, line_y, PAGE_WIDTH - MARGIN_RIGHT, line_y)
        canvas.restoreState()
        # White-label logo (if configured) top-right, clearing the header title.
        branded_header_logo(canvas, doc)

    def _footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        # Left side: brand (follows the workspace white-label, issue #284)
        canvas.setFillColor(colors.HexColor("#999999"))
        brand_text = f"{branded_cover_brand()}  |  Generated: {generated_date}"
        # A white-labelled Chinese workspace puts its own name here.
        canvas.setFont(pdf_font_for_text(brand_text), 7)
        canvas.drawString(MARGIN_LEFT, 10 * mm, brand_text)
        # Right side: page number
        if getattr(doc, "page_count", 0) > 0:
            page_text = f"Page {doc.page} of {doc.page_count}"
        else:
            page_text = f"Page {doc.page}"
        canvas.setFont(BODY_FONT, 7)
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, 10 * mm, page_text)
        canvas.restoreState()

    return _header, _footer


class _NumberedDocTemplate(BaseDocTemplate):
    """DocTemplate that tracks total page count for 'Page X of Y' footers.

    Uses a two-pass approach: the first build counts pages, then we store
    the total so the footer can reference it.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.page_count = 0

    def afterFlowable(self, flowable: Any) -> None:  # noqa: N802
        """Track page count after each flowable is placed."""
        # page_count is updated after the full build via handle_documentEnd

    def afterPage(self) -> None:  # noqa: N802
        """Called after each page is completed."""
        self.page_count = max(self.page_count, self.page)


def _build_cover_page(
    boq_data: Any,
    project_name: str,
    currency: str,
    prepared_by: str,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    """Build the list of flowables for the cover page."""
    elements: list[Any] = []

    # Top spacing
    elements.append(Spacer(1, 30 * mm))

    # Brand (workspace white-label name, falls back to the default; issue #284)
    elements.append(_safe_para(branded_cover_brand(), styles["brand"]))
    elements.append(Spacer(1, 10 * mm))

    # Decorative line
    line_table = Table(
        [[""]],
        colWidths=[120 * mm],
        rowHeights=[0.8 * mm],
    )
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1a1a2e")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    line_wrapper = Table([[line_table]], colWidths=[USABLE_WIDTH])
    line_wrapper.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    elements.append(line_wrapper)
    elements.append(Spacer(1, 4 * mm))

    # Title
    elements.append(Paragraph("COST ESTIMATE", styles["title"]))

    elements.append(Spacer(1, 2 * mm))
    elements.append(line_wrapper)
    elements.append(Spacer(1, 12 * mm))

    # Project info
    info_rows = [
        ("Project:", project_name),
        ("BOQ:", boq_data.name),
        ("Date:", datetime.now(tz=UTC).strftime("%d.%m.%Y")),
        ("Status:", (boq_data.status or "Draft").capitalize()),
    ]

    info_table_data = []
    for label, value in info_rows:
        info_table_data.append(
            [
                # Labels are first-party constants, values come from the
                # project / BOQ records and may contain HTML - escape only
                # the dynamic side.
                Paragraph(label, styles["info_label"]),
                _safe_para(value, styles["info_value"]),
            ]
        )

    info_table = Table(
        info_table_data,
        colWidths=[30 * mm, 100 * mm],
        hAlign="CENTER",
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 12 * mm))

    # Separator
    sep_table = Table([[""]], colWidths=[130 * mm], rowHeights=[0.3 * mm])
    sep_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#cccccc")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    sep_wrapper = Table([[sep_table]], colWidths=[USABLE_WIDTH])
    sep_wrapper.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    elements.append(sep_wrapper)
    elements.append(Spacer(1, 6 * mm))

    # Summary heading
    elements.append(
        Paragraph(
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;SUMMARY",
            styles["title"],
        )
    )
    elements.append(Spacer(1, 4 * mm))

    # Cost summary. The tax is already inside ``net_total``, so the pre-tax
    # subtotal is that figure minus the tax and the total of everything is that
    # figure itself. See :func:`_tax_split`.
    direct_cost = boq_data.direct_cost
    tax_lines, tax_amount, subtotal_ex_tax, gross_total = _tax_split(boq_data)
    markup_total = subtotal_ex_tax - Decimal(str(direct_cost))

    summary_rows: list[tuple[str, str, bool]] = [
        ("Direct Cost:", _fmt_currency(direct_cost, currency), False),
        ("Markups (excl. tax):", _fmt_currency(markup_total, currency), False),
        ("Net Total (excl. tax):", _fmt_currency(subtotal_ex_tax, currency), False),
    ]
    # One row per tax line, named and rated as the bill carries it. A stack with
    # no tax at all still prints a zero row, so the summary keeps its shape and
    # an untaxed bill is visibly untaxed rather than silently missing a row.
    tax_rows = [(f"{_tax_label(m, currency)}:", Decimal(str(m.amount))) for m in tax_lines]
    if not tax_rows:
        tax_rows = [("VAT 0%:", Decimal("0"))]
    summary_rows.extend((label, _fmt_currency(amount, currency), False) for label, amount in tax_rows)
    summary_rows.append(("Gross Total:", _fmt_currency(gross_total, currency), True))

    summary_table_data = []
    for label, value, is_total in summary_rows:
        lbl_style = styles["summary_total_label"] if is_total else styles["summary_label"]
        val_style = styles["summary_total_value"] if is_total else styles["summary_value"]
        summary_table_data.append(
            [
                Paragraph(label, lbl_style),
                Paragraph(value, val_style),
            ]
        )

    summary_table = Table(
        summary_table_data,
        colWidths=[50 * mm, 80 * mm],
        hAlign="CENTER",
    )

    # Style the summary table with a line above the Gross Total
    summary_style_commands: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]
    # Add top border on the Gross Total row (last row)
    last_row = len(summary_rows) - 1
    summary_style_commands.append(("LINEABOVE", (0, last_row), (-1, last_row), 1, colors.HexColor("#1a1a2e")))
    summary_table.setStyle(TableStyle(summary_style_commands))
    elements.append(summary_table)

    elements.append(Spacer(1, 10 * mm))
    elements.append(sep_wrapper)
    elements.append(Spacer(1, 6 * mm))

    # Prepared by
    if prepared_by:
        # ``prepared_by`` is user-supplied; escape it before splicing into
        # the cover-page paragraph or a payload like
        # ``<font color="white">x</font>`` would render as styled text and
        # ``<img onerror=...>`` would crash paraparser (BUG-PDF01).
        elements.append(
            Paragraph(
                "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Prepared by: " + html.escape(prepared_by, quote=True),
                # The estimator who signs a Chinese bill has a Chinese name.
                pdf_style_for_text(styles["subtitle"], prepared_by),
            )
        )

    return elements


def _build_boq_table(
    boq_data: Any,
    currency: str,
    styles: dict[str, ParagraphStyle],
    measurement_system: str = "metric",
) -> list[Any]:
    """Build the BOQ table flowables (sections, positions, totals).

    Improvements:
    - Locale-aware currency formatting for all monetary values
    - Conditional page break before each major section (60mm threshold)
    - Grand total block wrapped in KeepTogether

    ``measurement_system`` controls the physical quantity column: when
    ``"imperial"`` each ``pos.quantity`` is scaled and its unit relabelled
    (m -> ft, m² -> ft² ...). The paired per-unit RATE is then restated
    reciprocally against the same displayed unit (50 / m -> 15.24 / ft) so a
    converted line still reconciles (qty_shown * rate_shown == line total).
    Line / project totals (total / subtotals / markups / VAT) are NEVER
    converted or recomputed - they are invariant amounts in the project
    currency, not measurements.
    """
    elements: list[Any] = []

    # Locale-aware formatting shortcuts
    def _fv(value: float, decimals: int = 2) -> str:
        return _fmt(value, decimals, currency)

    def _fc(value: float) -> str:
        return _fmt_currency(value, currency)

    def _qty_cell(pos: Any) -> tuple[str, str]:
        """Return (quantity_text, unit_label) for a position row.

        Honours ``measurement_system``: the quantity is converted and the unit
        relabelled for imperial; metric tidies the label only. The numeric
        value is formatted with the same locale-aware helper as before so
        thousands / decimal separators stay consistent.
        """
        result = convert_units(pos.quantity, pos.unit, measurement_system)
        return _fv(result.value), result.display_unit

    def _rate_cell(pos: Any) -> str:
        """Return the per-unit rate text for a position row.

        The rate is money per ONE metric unit. When ``_qty_cell`` shows the
        quantity converted (m -> ft ...) the rate is restated reciprocally
        against the SAME displayed unit (50 / m -> 15.24 / ft) via
        :func:`display_rate`, so ``qty_shown * rate_shown`` reconciles to the
        invariant line total. Metric and unmapped units return the rate
        unchanged. The line total is never recomputed from this - only the
        printed per-unit basis is restated.
        """
        rate = display_rate(pos.unit_rate, pos.unit, measurement_system)
        return _fv(rate)

    # Table header row
    header_row = [
        Paragraph("<b>Pos.</b>", styles["table_header"]),
        Paragraph("<b>Description</b>", styles["table_header"]),
        Paragraph("<b>Unit</b>", styles["table_header"]),
        Paragraph("<b>Qty</b>", styles["table_header_right"]),
        Paragraph(f"<b>Rate ({currency})</b>", styles["table_header_right"]),
        Paragraph(f"<b>Total ({currency})</b>", styles["table_header_right"]),
    ]

    table_data: list[list[Any]] = [header_row]
    row_styles: list[tuple[int, str]] = []  # (row_index, type) for custom styling

    row_idx = 1  # 0 = header

    # Sections with positions
    for section in boq_data.sections:
        # Section header row
        table_data.append(
            [
                _safe_para(section.ordinal, styles["section_header"]),
                _safe_para(section.description, styles["section_header"]),
                "",
                "",
                "",
                "",
            ]
        )
        row_styles.append((row_idx, "section"))
        row_idx += 1

        # Position rows within section
        for pos in section.positions:
            qty_text, unit_label = _qty_cell(pos)
            table_data.append(
                [
                    _safe_para(pos.ordinal, styles["cell"]),
                    _safe_para(pos.description, styles["cell"]),
                    _safe_para(unit_label, styles["cell"]),
                    Paragraph(qty_text, styles["cell_right"]),
                    Paragraph(_rate_cell(pos), styles["cell_right"]),
                    Paragraph(_fv(pos.total), styles["cell_right"]),
                ]
            )
            row_styles.append((row_idx, "item"))
            row_idx += 1

        # Section subtotal
        table_data.append(
            [
                "",
                "",
                Paragraph("Subtotal:", styles["subtotal_label"]),
                "",
                "",
                Paragraph(_fv(section.subtotal), styles["subtotal_value"]),
            ]
        )
        row_styles.append((row_idx, "subtotal"))
        row_idx += 1

    # Ungrouped positions
    if boq_data.positions:
        table_data.append(
            [
                Paragraph("", styles["section_header"]),
                Paragraph("Other Positions", styles["section_header"]),
                "",
                "",
                "",
                "",
            ]
        )
        row_styles.append((row_idx, "section"))
        row_idx += 1

        ungrouped_total = 0.0
        for pos in boq_data.positions:
            qty_text, unit_label = _qty_cell(pos)
            table_data.append(
                [
                    _safe_para(pos.ordinal, styles["cell"]),
                    _safe_para(pos.description, styles["cell"]),
                    _safe_para(unit_label, styles["cell"]),
                    Paragraph(qty_text, styles["cell_right"]),
                    Paragraph(_rate_cell(pos), styles["cell_right"]),
                    Paragraph(_fv(pos.total), styles["cell_right"]),
                ]
            )
            row_styles.append((row_idx, "item"))
            row_idx += 1
            # ``pos.total`` is a SQLAlchemy Numeric (Decimal); the
            # accumulator is a float - mixing the two raises TypeError and
            # crashed PDF export for any BOQ with ungrouped positions.
            ungrouped_total += float(pos.total or 0)

        table_data.append(
            [
                "",
                "",
                Paragraph("Subtotal:", styles["subtotal_label"]),
                "",
                "",
                Paragraph(_fv(ungrouped_total), styles["subtotal_value"]),
            ]
        )
        row_styles.append((row_idx, "subtotal"))
        row_idx += 1

    # Blank spacer row
    table_data.append(["", "", "", "", "", ""])
    row_styles.append((row_idx, "spacer"))
    row_idx += 1

    # Direct cost
    table_data.append(
        [
            "",
            "",
            Paragraph("<b>Direct Cost:</b>", styles["cell_bold_right"]),
            "",
            "",
            Paragraph(f"<b>{_fc(boq_data.direct_cost)}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "total_line"))
    row_idx += 1

    # Markup lines. Tax is not one of them here: it is printed below the pre-tax
    # subtotal, which is where the reader of a bill looks for it, and printing it
    # in both places counted its money twice.
    for markup in boq_data.markups:
        if not markup.is_active or markup.category == "tax":
            continue
        label = markup.name
        if markup.markup_type == "percentage":
            label = f"{markup.name} ({_fv(markup.percentage, 1)}%)"
        table_data.append(
            [
                "",
                "",
                _safe_para(label, styles["cell_right"]),
                "",
                "",
                Paragraph(_fc(markup.amount), styles["cell_right"]),
            ]
        )
        row_styles.append((row_idx, "markup"))
        row_idx += 1

    # Net total, before tax, then the tax lines, then the total of everything.
    # See :func:`_tax_split` for why the tax is subtracted and not added.
    tax_lines, tax_amount, subtotal_ex_tax, gross_total = _tax_split(boq_data)
    table_data.append(
        [
            "",
            "",
            Paragraph("<b>Net Total (excl. tax):</b>", styles["cell_bold_right"]),
            "",
            "",
            Paragraph(f"<b>{_fc(subtotal_ex_tax)}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "grand_total"))
    row_idx += 1

    tax_rows = [(f"{_tax_label(m, currency)}:", Decimal(str(m.amount))) for m in tax_lines]
    if not tax_rows:
        tax_rows = [("VAT 0%:", Decimal("0"))]
    for tax_label, tax_line_amount in tax_rows:
        table_data.append(
            [
                "",
                "",
                Paragraph(tax_label, styles["cell_right"]),
                "",
                "",
                Paragraph(_fc(tax_line_amount), styles["cell_right"]),
            ]
        )
        row_styles.append((row_idx, "vat"))
        row_idx += 1

    table_data.append(
        [
            "",
            "",
            Paragraph(f"<b>Gross Total ({currency}):</b>", styles["cell_bold_right"]),
            "",
            "",
            Paragraph(f"<b>{_fc(gross_total)}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "grand_total"))
    row_idx += 1

    # Build the table
    table = Table(table_data, colWidths=TABLE_COL_WIDTHS, repeatRows=1)

    # Base table style
    style_commands: list[Any] = [
        # Header row. The fill only: every cell in this table is a Paragraph
        # and carries its own face, size and colour, so a TEXTCOLOR, FONTNAME
        # or FONTSIZE command here would read as authoritative and change
        # nothing on the page.
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        # Global
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        # Grid lines
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
    ]

    # Per-row styling
    for ri, row_type in row_styles:
        if row_type == "section":
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#e8e8ee")))
            style_commands.append(("LINEBELOW", (0, ri), (-1, ri), 0.5, colors.HexColor("#cccccc")))
        elif row_type == "subtotal":
            style_commands.append(("LINEABOVE", (0, ri), (-1, ri), 0.5, colors.HexColor("#cccccc")))
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#f0f0f5")))
        elif row_type == "total_line":
            style_commands.append(("LINEABOVE", (0, ri), (-1, ri), 1, colors.HexColor("#1a1a2e")))
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.white))
        elif row_type == "grand_total":
            style_commands.append(("LINEABOVE", (0, ri), (-1, ri), 1.5, colors.HexColor("#1a1a2e")))
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#e8e8ee")))
        elif row_type == "spacer":
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.white))

    table.setStyle(TableStyle(style_commands))
    elements.append(table)

    return elements


def generate_boq_pdf(
    boq_data: Any,
    project_name: str,
    currency: str = "",
    prepared_by: str = "",
    measurement_system: str = "metric",
) -> bytes:
    """Generate a professional PDF cost estimate report.

    Args:
        boq_data: BOQWithSections schema instance with sections, positions,
                  markups, direct_cost, net_total, grand_total.
        project_name: Name of the parent project (for the cover page).
        currency: Currency code (e.g. "EUR", "GBP", "USD").
        prepared_by: Full name of the person who prepared the estimate.
        measurement_system: ``"metric"`` (default) renders quantities
            canonical; ``"imperial"`` converts the physical quantity column +
            its unit label (m -> ft, m² -> ft² ...) and restates the paired
            per-unit rate reciprocally so each converted line still reconciles.
            Line / project totals are never converted or recomputed.

    Returns:
        PDF file contents as bytes.
    """
    buffer = io.BytesIO()
    styles = _build_styles()
    generated_date = datetime.now(tz=UTC).strftime("%d.%m.%Y")

    header_func, footer_func = _make_header_footer(project_name, boq_data.name, generated_date)

    # -- Page templates --
    # Cover page: no header/footer
    cover_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
        id="cover",
    )

    # Table pages: with header and footer
    table_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM + 5 * mm,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM - 12 * mm,
        id="table",
    )

    def _table_page_handler(canvas: Any, doc: Any) -> None:
        header_func(canvas, doc)
        footer_func(canvas, doc)

    cover_template = PageTemplate(id="cover", frames=[cover_frame])
    table_template = PageTemplate(
        id="table",
        frames=[table_frame],
        onPage=_table_page_handler,
    )

    doc = _NumberedDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"Cost Estimate - {boq_data.name}",
        author=branded_doc_metadata()["author"],
        subject="Bill of Quantities",
        creator=branded_doc_metadata()["creator"],
        producer=branded_doc_metadata()["producer"],
        keywords=branded_doc_metadata()["keywords"],
    )
    doc.addPageTemplates([cover_template, table_template])

    # -- Build flowables --
    flowables: list[Any] = []

    # Cover page
    flowables.extend(_build_cover_page(boq_data, project_name, currency, prepared_by, styles))

    # Switch to table template and page break
    flowables.append(NextPageTemplate("table"))
    flowables.append(PageBreak())

    # BOQ table pages
    flowables.extend(_build_boq_table(boq_data, currency, styles, measurement_system))

    # Two-pass build: first pass counts pages, second pass renders with totals
    doc.build(flowables)
    total_pages = doc.page_count

    # Second pass with correct page count
    buffer.seek(0)
    buffer.truncate()

    doc2 = _NumberedDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"Cost Estimate - {boq_data.name}",
        author=branded_doc_metadata()["author"],
        subject="Bill of Quantities",
        creator=branded_doc_metadata()["creator"],
        producer=branded_doc_metadata()["producer"],
        keywords=branded_doc_metadata()["keywords"],
    )
    doc2.page_count = total_pages
    doc2.addPageTemplates([cover_template, table_template])

    # Rebuild flowables (they are consumed by the first build)
    flowables2: list[Any] = []
    flowables2.extend(_build_cover_page(boq_data, project_name, currency, prepared_by, styles))
    flowables2.append(NextPageTemplate("table"))
    flowables2.append(PageBreak())
    flowables2.extend(_build_boq_table(boq_data, currency, styles, measurement_system))

    doc2.build(flowables2)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def count_boq_positions(boq_data: Any) -> int:
    """Count the total number of line-item positions in a BOQWithSections.

    Counts positions inside sections plus ungrouped positions.
    Section headers themselves are not counted.

    Args:
        boq_data: BOQWithSections schema instance.

    Returns:
        Total number of line-item positions.
    """
    total = 0
    for section in boq_data.sections:
        total += len(section.positions)
    total += len(boq_data.positions)
    return total


# ── Large BOQ threshold ──────────────────────────────────────────────────────

LARGE_BOQ_THRESHOLD = 500


def generate_boq_pdf_simple(
    boq_data: Any,
    project_name: str,
    currency: str = "",
    prepared_by: str = "",
    measurement_system: str = "metric",
) -> bytes:
    """Generate a simplified PDF for large BOQs (> 500 positions).

    Uses a single-pass build (no two-pass page counting) and a compact
    table layout to reduce memory usage and generation time on Windows.

    The simplified report includes:
    - Cover page with summary
    - Section-level summary table (no individual positions)
    - Cost summary with markups

    Args:
        boq_data: BOQWithSections schema instance.
        project_name: Name of the parent project.
        currency: Currency code (e.g. "EUR").
        prepared_by: Full name of the person who prepared the estimate.
        measurement_system: Accepted for signature parity with
            :func:`generate_boq_pdf` so the router can call either uniformly.
            The summary report carries no physical-quantity column (only item
            counts and money subtotals), so there is nothing to convert and
            the value is otherwise unused.

    Returns:
        PDF file contents as bytes.
    """
    buffer = io.BytesIO()
    styles = _build_styles()
    generated_date = datetime.now(tz=UTC).strftime("%d.%m.%Y")

    header_func, footer_func = _make_header_footer(project_name, boq_data.name, generated_date)

    cover_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
        id="cover",
    )
    table_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM + 5 * mm,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM - 12 * mm,
        id="table",
    )

    def _table_page_handler(canvas: Any, doc: Any) -> None:
        header_func(canvas, doc)
        footer_func(canvas, doc)

    cover_template = PageTemplate(id="cover", frames=[cover_frame])
    table_template = PageTemplate(
        id="table",
        frames=[table_frame],
        onPage=_table_page_handler,
    )

    doc = _NumberedDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"Cost Estimate - {boq_data.name} (Summary)",
        author=branded_doc_metadata()["author"],
        subject="Bill of Quantities",
        creator=branded_doc_metadata()["creator"],
        producer=branded_doc_metadata()["producer"],
        keywords=branded_doc_metadata()["keywords"],
    )
    doc.addPageTemplates([cover_template, table_template])

    flowables: list[Any] = []

    # Cover page
    flowables.extend(_build_cover_page(boq_data, project_name, currency, prepared_by, styles))

    # Switch to table template
    flowables.append(NextPageTemplate("table"))
    flowables.append(PageBreak())

    # Section-level summary table instead of full position listing
    total_positions = count_boq_positions(boq_data)
    flowables.append(
        Paragraph(
            f"<b>Summary Report</b> &mdash; {total_positions} positions (full detail omitted for performance)",
            styles["section_header"],
        )
    )
    flowables.append(Spacer(1, 4 * mm))

    # Build a compact section summary table
    header_row = [
        Paragraph("<b>Section</b>", styles["table_header"]),
        Paragraph("<b>Description</b>", styles["table_header"]),
        Paragraph("<b>Items</b>", styles["table_header_right"]),
        Paragraph("<b>Subtotal</b>", styles["table_header_right"]),
    ]
    summary_col_widths = [35 * mm, USABLE_WIDTH - 35 * mm - 25 * mm - 35 * mm, 25 * mm, 35 * mm]
    table_data: list[list[Any]] = [header_row]

    for section in boq_data.sections:
        table_data.append(
            [
                _safe_para(section.ordinal, styles["cell"]),
                _safe_para(section.description, styles["cell"]),
                Paragraph(str(len(section.positions)), styles["cell_right"]),
                Paragraph(_fmt_currency(section.subtotal, currency), styles["cell_right"]),
            ]
        )

    if boq_data.positions:
        ungrouped_total = sum(p.total for p in boq_data.positions)
        table_data.append(
            [
                Paragraph("", styles["cell"]),
                Paragraph("Other Positions", styles["cell"]),
                Paragraph(str(len(boq_data.positions)), styles["cell_right"]),
                Paragraph(_fmt_currency(ungrouped_total, currency), styles["cell_right"]),
            ]
        )

    summary_table = Table(table_data, colWidths=summary_col_widths, repeatRows=1)
    summary_style_commands: list[Any] = [
        # The fill only, for the same reason as the position table above.
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
    ]
    summary_table.setStyle(TableStyle(summary_style_commands))
    flowables.append(summary_table)
    flowables.append(Spacer(1, 6 * mm))

    # Direct cost, markups, net total, VAT, gross total
    flowables.append(Paragraph("<b>Cost Summary</b>", styles["section_header"]))
    flowables.append(Spacer(1, 3 * mm))

    cost_rows: list[list[Any]] = []
    cost_rows.append(
        [
            Paragraph("<b>Direct Cost:</b>", styles["cell_bold_right"]),
            Paragraph(f"<b>{_fmt_currency(boq_data.direct_cost, currency)}</b>", styles["cell_bold_right"]),
        ]
    )

    # Tax is excluded here and printed under the pre-tax subtotal instead, so
    # its money is stated once. See :func:`_tax_split`.
    for markup in boq_data.markups:
        if not markup.is_active or markup.category == "tax":
            continue
        label = markup.name
        if markup.markup_type == "percentage":
            label = f"{markup.name} ({_fmt(markup.percentage, 1, currency)}%)"
        cost_rows.append(
            [
                _safe_para(label, styles["cell_right"]),
                Paragraph(_fmt_currency(markup.amount, currency), styles["cell_right"]),
            ]
        )

    tax_lines, tax_amount, subtotal_ex_tax, gross_total = _tax_split(boq_data)
    cost_rows.append(
        [
            Paragraph("<b>Net Total (excl. tax):</b>", styles["cell_bold_right"]),
            Paragraph(f"<b>{_fmt_currency(subtotal_ex_tax, currency)}</b>", styles["cell_bold_right"]),
        ]
    )

    tax_rows = [(f"{_tax_label(m, currency)}:", Decimal(str(m.amount))) for m in tax_lines]
    if not tax_rows:
        tax_rows = [("VAT 0%:", Decimal("0"))]
    for tax_label, tax_line_amount in tax_rows:
        cost_rows.append(
            [
                Paragraph(tax_label, styles["cell_right"]),
                Paragraph(_fmt_currency(tax_line_amount, currency), styles["cell_right"]),
            ]
        )
    cost_rows.append(
        [
            Paragraph(f"<b>Gross Total ({currency}):</b>", styles["cell_bold_right"]),
            Paragraph(f"<b>{_fmt_currency(gross_total, currency)}</b>", styles["cell_bold_right"]),
        ]
    )

    cost_table = Table(
        cost_rows,
        colWidths=[USABLE_WIDTH * 0.6, USABLE_WIDTH * 0.4],
    )
    cost_style: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]
    # Gross total row styling
    last_row = len(cost_rows) - 1
    cost_style.append(("LINEABOVE", (0, last_row), (-1, last_row), 1.5, colors.HexColor("#1a1a2e")))
    cost_style.append(("BACKGROUND", (0, last_row), (-1, last_row), colors.HexColor("#e8e8ee")))
    cost_table.setStyle(TableStyle(cost_style))
    flowables.append(cost_table)

    # Single-pass build (no two-pass for page count - acceptable trade-off
    # for large BOQs; footer shows "Page X" without " of Y")
    doc.page_count = 0  # Will not display " of 0" - see footer_func logic
    doc.build(flowables)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
