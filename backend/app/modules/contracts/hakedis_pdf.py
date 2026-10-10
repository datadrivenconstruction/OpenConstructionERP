# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The hakediş (Turkish progress payment certificate) as a PDF.

Two parts, the way the certificate is filed in Türkiye:

* page one, portrait A4: the "Hakediş Raporu" summary. The header block, the
  lettered lines with their formulas, the deductions and set-offs, the amount
  payable and the signature block;
* the following pages, landscape A4: the "Yapılan İşler Listesi", one row per
  work item with the column header repeated on every page, section subtotals
  and the total.

The document is drawn in Turkish, in English, or bilingual with the English
under the Turkish, which is how international projects in Türkiye print it.
Every word comes from :data:`app.modules.contracts.hakedis_layout.HAKEDIS_LABELS`
and every number from the print model in :mod:`app.modules.contracts.hakedis`,
which the workbook renderer shares, so this module only places what it is
given. Numbers and dates follow the project's country (``1.234,56`` and
``10.10.2026`` for Türkiye) whatever the label language.

A certificate with a held line, an unconfirmed rate or an overridden figure is
not final. It says so in a banner on every page, prints a marker where the
missing figure would be, and lists the reasons in a notes block under the
summary.
"""

from __future__ import annotations

import html
import io
from collections.abc import Sequence
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.pdf_branding import branded_doc_metadata, branded_header_logo
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_font_for_text, pdf_style_for_text, register_pdf_fonts
from app.core.regional_format import format_date
from app.modules.contracts.hakedis import (
    Certificate,
    PrintedSummaryLine,
    header_columns,
    note_text,
    printed_summary,
    printed_works,
)
from app.modules.contracts.hakedis_layout import ColumnDef, HakedisSettings, label, locale_languages, upper_for

register_pdf_fonts()

_SIDE_MARGIN = 14 * mm
_TOP_MARGIN = 16 * mm
_BOTTOM_MARGIN = 16 * mm
#: The padding a reportlab frame keeps on every side, in points.
_FRAME_PADDING = 6.0

_MUTED = "#555555"
_ALERT = "#b91c1c"
_RULE = colors.HexColor("#9ca3af")
_FILL = colors.HexColor("#f3f4f6")

#: Works list column widths by kind, in millimetres. The description takes
#: whatever the sheet has left.
_COLUMN_MM: dict[str, float] = {
    "seq": 9,
    "unit": 12,
    "quantity": 20,
    "unit_price": 21,
    "money": 26,
    "percent": 18,
}
_CODE_MM = 24
_MIN_DESCRIPTION_MM = 40

#: How many signature blocks fit beside each other.
_SIGNATURES_PER_ROW = 4

#: Roles whose block names a party of the header.
_ROLE_PARTY: dict[str, str] = {"contractor": "contractor", "subcontractor": "contractor", "employer": "employer"}


def _esc(text: Any) -> str:
    return html.escape("" if text is None else str(text))


def _para(text: Any, style: ParagraphStyle) -> Paragraph:
    """An escaped paragraph, faced for the script of its text."""
    raw = "" if text is None else str(text)
    return Paragraph(_esc(raw).replace("\n", "<br/>"), pdf_style_for_text(style, raw))


def _stacked(parts: Sequence[str], style: ParagraphStyle, *, suffix: str = "", small: float = 1.5) -> Paragraph:
    """The first language at full size and the others under it, smaller and muted.

    ``suffix`` (a formula) follows the first language only: it is the same in
    every language and belongs on the line a Turkish reader checks.
    """
    first = _esc(parts[0]) + (f" {_esc(suffix)}" if suffix else "")
    rest = "".join(
        f'<br/><font size="{style.fontSize - small:g}" color="{_MUTED}">{_esc(part)}</font>'
        for part in parts[1:]
        if part
    )
    return Paragraph(first + rest, pdf_style_for_text(style, " ".join(parts)))


class _Styles:
    """The paragraph styles of one document."""

    def __init__(self) -> None:
        base = getSampleStyleSheet()["Normal"]
        self.title = ParagraphStyle("HakTitle", parent=base, fontName=BOLD_FONT, fontSize=13, leading=16)
        self.title.alignment = TA_CENTER
        self.subtitle = ParagraphStyle("HakSub", parent=base, fontName=BODY_FONT, fontSize=8.5, leading=11)
        self.subtitle.alignment = TA_CENTER
        self.body = ParagraphStyle("HakBody", parent=base, fontName=BODY_FONT, fontSize=8, leading=10)
        self.label = ParagraphStyle("HakLabel", parent=self.body, fontName=BOLD_FONT)
        self.strong = ParagraphStyle("HakStrong", parent=self.body, fontName=BOLD_FONT)
        self.letter = ParagraphStyle("HakLetter", parent=self.body, alignment=TA_CENTER)
        self.letter_strong = ParagraphStyle("HakLetterB", parent=self.letter, fontName=BOLD_FONT)
        self.money = ParagraphStyle("HakMoney", parent=self.body, alignment=TA_RIGHT)
        self.money_strong = ParagraphStyle("HakMoneyB", parent=self.money, fontName=BOLD_FONT)
        self.held = ParagraphStyle("HakHeld", parent=self.money_strong, textColor=colors.HexColor(_ALERT))
        self.note = ParagraphStyle("HakNote", parent=self.body, fontSize=7, leading=9)
        self.sign = ParagraphStyle("HakSign", parent=self.body, fontName=BOLD_FONT, alignment=TA_CENTER)
        self.sign_small = ParagraphStyle("HakSignS", parent=self.body, fontSize=7, leading=11, alignment=TA_LEFT)
        self.cell = ParagraphStyle("HakCell", parent=base, fontName=BODY_FONT, fontSize=6.5, leading=8)
        self.cell_r = ParagraphStyle("HakCellR", parent=self.cell, alignment=TA_RIGHT)
        self.cell_c = ParagraphStyle("HakCellC", parent=self.cell, alignment=TA_CENTER)
        self.cell_b = ParagraphStyle("HakCellB", parent=self.cell, fontName=BOLD_FONT)
        self.cell_br = ParagraphStyle("HakCellBR", parent=self.cell_r, fontName=BOLD_FONT)
        self.head = ParagraphStyle("HakHead", parent=self.cell_c, fontName=BOLD_FONT)


class _NumberedCanvas(Canvas):
    """A canvas that knows the page count, so each page can print "x / y".

    The pages are kept and replayed at ``save``, which is the first moment the
    total is known. The footer and the draft banner are drawn in that replay.
    """

    furniture: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 - reportlab's name
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._draw_furniture(total)
            super().showPage()
        super().save()

    def _draw_furniture(self, total: int) -> None:
        furniture = self.furniture
        width, height = self._pagesize
        page_text = " - ".join(part.format(page=self._pageNumber, pages=total) for part in furniture["page_of"])
        self.saveState()
        self.setFillColor(colors.HexColor(_MUTED))
        self.setFont(pdf_font_for_text(page_text), 7)
        self.drawRightString(width - _SIDE_MARGIN, 9 * mm, page_text)
        reference = furniture["reference"]
        self.setFont(pdf_font_for_text(reference), 7)
        self.drawString(_SIDE_MARGIN, 9 * mm, reference)
        banner = furniture["banner"]
        if banner:
            self.setFillColor(colors.HexColor(_ALERT))
            self.setFont(pdf_font_for_text(banner, bold=True), 8)
            self.drawString(_SIDE_MARGIN, height - 11 * mm, banner)
        self.restoreState()


def _header_table(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    issue: date | None,
    s: _Styles,
    width: float,
) -> Table:
    # The job and the certificate on the left, the two parties on the right,
    # so the whole summary keeps to one page.
    left, right = (
        [(_stacked(names, s.label, small=1.0), _para(value, s.body)) for names, value in half]
        for half in header_columns(cert, locale, settings, issue)
    )
    blank = ("", "")
    rows = [
        [*(left[index] if index < len(left) else blank), *(right[index] if index < len(right) else blank)]
        for index in range(max(len(left), len(right)))
    ]
    label_width = 36 * mm
    table = Table(rows, colWidths=[label_width, width / 2 - label_width] * 2)
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("LINEAFTER", (1, 0), (1, -1), 0.6, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]
        )
    )
    return table


def _amount_cell(line: PrintedSummaryLine, currency: str, s: _Styles) -> Paragraph:
    refs = "".join(f" ({number})" for number in line.notes)
    if line.status == "held":
        return _para(f"{line.text}{refs}", s.held)
    text = f"{line.text} {currency}{refs}" if line.status == "value" else line.text
    return _para(text, s.money_strong if line.emphasis else s.money)


def _summary_table(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    s: _Styles,
    width: float,
) -> Table:
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    rows: list[list[Any]] = []
    commands: list[tuple[Any, ...]] = [
        ("BOX", (0, 0), (-1, -1), 0.8, _RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    previous_section = ""
    for line in printed_summary(cert, locale, settings):
        if line.section != previous_section:
            if line.section == "deductions":
                heading = tuple(
                    upper_for(language, label("section.deductions", language, overrides)) for language in languages
                )
                rows.append([_stacked(heading, s.strong), "", ""])
                index = len(rows) - 1
                commands += [("SPAN", (0, index), (-1, index)), ("BACKGROUND", (0, index), (-1, index), _FILL)]
            elif rows:
                commands.append(("LINEABOVE", (0, len(rows)), (-1, len(rows)), 0.8, _RULE))
            previous_section = line.section
        deduction = line.section == "deductions"
        letter = f"{line.letter})" if deduction and line.letter else line.letter
        style = s.strong if line.emphasis else s.body
        label_cell = _stacked(line.labels, style, suffix=line.formulas[0])
        if any(line.details):
            detail = "".join(
                f'<br/><font size="6.5" color="{_MUTED}">{_esc(part)}</font>' for part in line.details if part
            )
            label_cell = Paragraph(label_cell.text + detail, label_cell.style)
        rows.append(
            [
                _para(letter, s.letter_strong if line.emphasis else s.letter),
                label_cell,
                _amount_cell(line, cert.inp.currency, s),
            ]
        )
        if line.emphasis:
            commands.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), _FILL))
    letter_width, amount_width = 11 * mm, 46 * mm
    table = Table(rows, colWidths=[letter_width, width - letter_width - amount_width, amount_width])
    table.setStyle(TableStyle(commands))
    return table


def _notes_block(cert: Certificate, locale: str, settings: HakedisSettings | None, s: _Styles) -> list[Any]:
    notes = cert.notes
    if not notes:
        return []
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    title = " / ".join(upper_for(language, label("draft.notes_title", language, overrides)) for language in languages)
    flowables: list[Any] = [Spacer(1, 3 * mm), _para(title, s.strong)]
    for note in notes:
        lettered = f"{note.letter}) " if note.letter else ""
        parts = tuple(
            f"{lettered}{label(f'line.{note.line_key}', language, overrides)}: "
            f"{note_text(note, cert, language, settings)}"
            for language in languages
        )
        flowables.append(_stacked((f"({note.number}) {parts[0]}", *parts[1:]), s.note, small=0.5))
    return flowables


def _signature_block(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    s: _Styles,
    width: float,
) -> list[Any]:
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    roles = list(cert.inp.signature_roles)
    if not roles:
        return []
    captions = "<br/>".join(
        f"{_esc(' / '.join(label(key, language, overrides) for language in languages))}: {dots}"
        for key, dots in (
            ("sign.name", "." * 22),
            ("sign.signature", "." * 22),
            ("sign.date", "..../..../........"),
        )
    )
    blocks: list[Any] = []
    for start in range(0, len(roles), _SIGNATURES_PER_ROW):
        chunk = roles[start : start + _SIGNATURES_PER_ROW]
        titles: list[Any] = []
        names: list[Any] = []
        for role in chunk:
            parts = tuple(upper_for(language, label(f"role.{role}", language, overrides)) for language in languages)
            titles.append(_stacked(parts, s.sign))
            party = getattr(cert.inp, _ROLE_PARTY[role], None) if role in _ROLE_PARTY else None
            names.append(_para(party.name if party is not None else "", s.letter))
        table = Table(
            [titles, names, [""] * len(chunk), [Paragraph(captions, s.sign_small)] * len(chunk)],
            colWidths=[width / len(chunk)] * len(chunk),
            rowHeights=[None, None, 9 * mm, None],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
                    ("LINEAFTER", (0, 0), (-2, -1), 0.25, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        blocks.append(table)
    return [Spacer(1, 3 * mm), KeepTogether(blocks)]


def _column_widths(columns: Sequence[ColumnDef], width: float) -> list[float]:
    fixed = [
        (_CODE_MM if column.key == "code" else _COLUMN_MM.get(column.kind, 0)) * mm
        if column.key != "description"
        else 0.0
        for column in columns
    ]
    if not any(column.key == "description" for column in columns):
        scale = width / sum(fixed)
        return [value * scale for value in fixed]
    description = max(width - sum(fixed), _MIN_DESCRIPTION_MM * mm)
    widths = [
        description if column.key == "description" else value for column, value in zip(columns, fixed, strict=True)
    ]
    scale = width / sum(widths)
    return [value * scale for value in widths]


def _works_table(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    s: _Styles,
    width: float,
) -> tuple[Table, bool]:
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    flavour = cert.inp.flavour
    columns, rows = printed_works(cert, locale, settings)
    show_flag = flavour == "lump_sum" or any(column.key == "contract_quantity" for column in columns)
    flag_column = next(
        (i for i, column in enumerate(columns) if column.key in ("cumulative_quantity", "cumulative_pct")), None
    )
    title_column = next((i for i, column in enumerate(columns) if column.key == "description"), 0)

    data: list[list[Any]] = [
        [_para(column.letter, s.head) for column in columns],
        [
            _stacked(
                tuple(label(f"col.{flavour}.{column.key}", language, overrides) for language in languages),
                s.head,
                small=1.0,
            )
            for column in columns
        ],
    ]
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 1), _FILL),
        ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LINEBELOW", (0, 1), (-1, 1), 0.6, _RULE),
        ("VALIGN", (0, 0), (-1, 1), "MIDDLE"),
        ("VALIGN", (0, 2), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
    ]
    flagged_any = False
    for row in rows:
        index = len(data)
        if row.kind == "section":
            data.append([_para(row.title, s.cell_b), *[""] * (len(columns) - 1)])
            commands += [("SPAN", (0, index), (-1, index)), ("BACKGROUND", (0, index), (-1, index), _FILL)]
            continue
        bold = row.kind != "line"
        cells: list[Any] = []
        for position, (column, text) in enumerate(zip(columns, row.cells, strict=True)):
            if bold and position == title_column:
                text = row.title
            if row.kind == "line" and row.flagged and show_flag and position == flag_column:
                text = f"{text} (!)"
                flagged_any = True
            if column.kind in ("quantity", "unit_price", "money", "percent"):
                style = s.cell_br if bold else s.cell_r
            elif column.kind in ("seq", "unit"):
                style = s.cell_c
            else:
                style = s.cell_b if bold else s.cell
            cells.append(_para(text, style))
        data.append(cells)
        if bold:
            commands.append(("LINEABOVE", (0, index), (-1, index), 0.6, _RULE))
            if row.kind == "total":
                commands.append(("BACKGROUND", (0, index), (-1, index), _FILL))
    table = Table(data, colWidths=_column_widths(columns, width), repeatRows=2)
    table.setStyle(TableStyle(commands))
    return table, flagged_any and show_flag


def render_hakedis_pdf(
    cert: Certificate,
    *,
    locale: str = "tr",
    settings: HakedisSettings | None = None,
    issue_date: date | None = None,
) -> bytes:
    """Render a computed certificate to PDF bytes.

    Args:
        cert: The certificate from :func:`app.modules.contracts.hakedis.compute_certificate`.
        locale: ``tr``, ``en`` or ``tr-en`` (bilingual, Turkish first).
        settings: The contract's resolved configuration, for its label
            overrides and its choice of works list columns. ``None`` prints
            the standard columns and the built-in labels.
        issue_date: The date the certificate is issued. The certificate input
            carries the period, not this date, so it is printed only when given.

    Raises:
        ValueError: ``locale`` is not one of the three.
    """
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    inp = cert.inp
    s = _Styles()

    def words(key: str, **params: str) -> tuple[str, ...]:
        return tuple(label(key, language, overrides, **params) for language in languages)

    def upper(key: str) -> tuple[str, ...]:
        return tuple(upper_for(language, label(key, language, overrides)) for language in languages)

    portrait_w, portrait_h = A4
    land_w, land_h = landscape(A4)
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_SIDE_MARGIN,
        rightMargin=_SIDE_MARGIN,
        topMargin=_TOP_MARGIN,
        bottomMargin=_BOTTOM_MARGIN,
        title=" / ".join(words("title.report")),
        **branded_doc_metadata(),
    )

    def on_page(canvas: Any, page_doc: Any) -> None:
        branded_header_logo(canvas, page_doc)

    def frame(page_w: float, page_h: float, name: str) -> Frame:
        return Frame(
            _SIDE_MARGIN,
            _BOTTOM_MARGIN,
            page_w - 2 * _SIDE_MARGIN,
            page_h - _TOP_MARGIN - _BOTTOM_MARGIN,
            id=name,
        )

    doc.addPageTemplates(
        [
            PageTemplate(id="summary", frames=[frame(portrait_w, portrait_h, "summary")], pagesize=A4, onPage=on_page),
            PageTemplate(id="works", frames=[frame(land_w, land_h, "works")], pagesize=landscape(A4), onPage=on_page),
        ]
    )
    summary_width = portrait_w - 2 * _SIDE_MARGIN - 2 * _FRAME_PADDING
    works_width = land_w - 2 * _SIDE_MARGIN - 2 * _FRAME_PADDING

    day = format_date(inp.period_end, inp.country_code)
    work_to_date = tuple(
        upper_for(language, label("header.work_to_date", language, overrides, date=day)) for language in languages
    )
    project_line = f"{inp.project_name} - {' / '.join(words('header.certificate_number'))}: {inp.certificate_number}"

    story: list[Any] = [
        _stacked(upper("title.report"), s.title, small=3.0),
        Spacer(1, 3 * mm),
        _header_table(cert, locale, settings, issue_date, s, summary_width),
        Spacer(1, 3 * mm),
        _stacked(work_to_date, s.strong),
        Spacer(1, 1.5 * mm),
        _summary_table(cert, locale, settings, s, summary_width),
        *_notes_block(cert, locale, settings, s),
        *_signature_block(cert, locale, settings, s, summary_width),
        NextPageTemplate("works"),
        PageBreak(),
        _stacked(upper("title.works_list"), s.title, small=3.0),
        _stacked(words(f"subtitle.{inp.flavour}"), s.subtitle),
        _para(project_line, s.subtitle),
        Spacer(1, 3 * mm),
    ]
    works, flagged = _works_table(cert, locale, settings, s, works_width)
    story.append(works)
    footnotes: list[tuple[str, ...]] = []
    if inp.flavour == "lump_sum" and any(
        column.key == "weight_pct" for column in printed_works(cert, locale, settings)[0]
    ):
        footnotes.append(words("works.weight_note"))
    if flagged:
        footnotes.append(words("works.over_measured_note"))
    if footnotes:
        story.append(Spacer(1, 2 * mm))
        story.extend(_stacked(parts, s.note, small=0.5) for parts in footnotes)
    story.extend(_signature_block(cert, locale, settings, s, works_width))

    reference = f"{' / '.join(words('header.certificate_number'))}: {inp.certificate_number}"
    if inp.contract_number:
        reference = f"{reference} - {inp.contract_number}"
    furniture = {
        "page_of": words("page.of"),
        "reference": reference,
        "banner": " / ".join(words("draft.banner")) if cert.is_draft else "",
    }
    canvas_class = type("HakedisCanvas", (_NumberedCanvas,), {"furniture": furniture})
    doc.build(story, canvasmaker=canvas_class)
    return buf.getvalue()


__all__ = ["render_hakedis_pdf"]
