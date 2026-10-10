# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The hakediş (Turkish progress payment certificate) as a PDF.

Two parts, the way the certificate is filed in Türkiye:

* page one, portrait A4: the "Hakediş Raporu" summary. The header block, the
  lettered lines with their formulas, the deductions and set-offs, the amount
  payable and, in the same frame as on the official form, the signatures;
* the following pages, landscape A4: the "Yapılan İşler Listesi", one row per
  work item with the column header repeated on every page, section subtotals,
  the total and the signatures.

The document is drawn in Turkish, in English, or bilingual with the English
beside the Turkish, which is how international projects in Türkiye print it.
Every word comes from :data:`app.modules.contracts.hakedis_layout.HAKEDIS_LABELS`
and every number from the print model in :mod:`app.modules.contracts.hakedis`,
which the workbook renderer shares, so this module only places what it is
given. Numbers and dates follow the project's country (``1.234,56`` and
``10.10.2026`` for Türkiye) whatever the label language.

Three rules of placement hold for every certificate:

* a signature block never stands on a page of its own. It is a row of the
  table it signs, tied to the rows above it, so when the page runs out the
  last rows move to the next page together with it;
* a number is never broken. The works list measures every printed value and
  gives each column the width of its widest one; the description takes what
  is left;
* every page carries the document's name, its number, the page counter and
  the time it was generated, in the same header and footer the registers use.

A certificate with a held line, an unconfirmed rate or an overridden figure is
not final. It says so in a banner and a watermark on every page, prints a
marker where the missing figure would be, and lists the reasons in a notes
block under the summary.
"""

from __future__ import annotations

import html
import io
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
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
from reportlab.platypus.doctemplate import LayoutError

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
    pdf_font_for_text,
    pdf_room_beside,
    pdf_style_for_text,
    register_pdf_fonts,
)
from app.core.regional_format import format_date, number_style
from app.modules.contracts.hakedis import (
    Certificate,
    CertificateParty,
    PrintedSummaryLine,
    note_text,
    printed_summary,
    printed_works,
)
from app.modules.contracts.hakedis_layout import (
    DEFAULT_LAYOUTS,
    ColumnDef,
    HakedisSettings,
    contractor_label_key,
    currency_label,
    is_foreign_currency,
    label,
    locale_languages,
    upper_for,
)

register_pdf_fonts()

# The sheet, the colours and the footer are the ones of the register and
# record documents (app.core.register_export), so a certificate filed beside a
# log reads as part of the same set.
_SIDE_MARGIN = 15 * mm
_TOP_MARGIN = 18 * mm
_BOTTOM_MARGIN = 18 * mm

_INK = "#16213e"
_MUTED = "#666666"
_ALERT = "#b91c1c"
_FOOTER = "#999999"
_RULE = colors.HexColor("#cccccc")
_FRAME_RULE = colors.HexColor("#9ca3af")
_FILL = colors.HexColor("#f4f5f7")

_DASH = "-"

#: Floors of the works list columns by kind, in millimetres. A column is as
#: wide as its widest printed value and never narrower than this; the
#: description takes whatever the sheet has left.
_COLUMN_FLOOR_MM: dict[str, float] = {
    "seq": 8,
    "unit": 10,
    "quantity": 17,
    "unit_price": 18,
    "money": 22,
    "percent": 17,
}
_CODE_FLOOR_MM = 14
#: A code is kept on one line up to this width; a longer one may wrap, but
#: only at a space.
_CODE_WHOLE_MM = 42
_MIN_DESCRIPTION_MM = 40
_LEAST_DESCRIPTION_MM = 25
#: Cell sizes tried in turn until the measured columns leave the description
#: its room.
_CELL_SIZES: tuple[float, ...] = (6.5, 6.0, 5.5, 5.0)
_CELL_PADDING = 2.5

_NUMERIC_KINDS = frozenset({"quantity", "unit_price", "money", "percent"})
#: Kinds whose values carry a varying number of decimals. Their decimal
#: separators are lined up by padding, never by printing zeros nobody entered.
_ALIGNED_KINDS = frozenset({"quantity", "unit_price", "percent"})

#: How many signature blocks fit beside each other on a portrait and on a
#: landscape sheet.
_SIGNATURES_PER_ROW = 4
_SIGNATURES_PER_WIDE_ROW = 6

#: Roles whose block names a party of the header.
_ROLE_PARTY: dict[str, str] = {"contractor": "contractor", "subcontractor": "contractor", "employer": "employer"}

#: The room kept clear at the top right of every page for the workspace logo.
_LOGO_ROOM = 52 * mm

#: How tightly the rows are tied together, tried in turn. A block that cannot
#: fit a page whole would stop the document, so each step ties less.
_TIE_BLOCKS, _TIE_SIGNATURES, _TIE_NOTHING = 0, 1, 2


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


def _title(parts: Sequence[str], style: ParagraphStyle) -> Paragraph:
    """A document title on one line: the first language, then the others smaller and muted."""
    rest = "".join(
        f' <font size="{style.fontSize - 3:g}" color="{_MUTED}">/ {_esc(part)}</font>' for part in parts[1:] if part
    )
    return Paragraph(_esc(parts[0]) + rest, pdf_style_for_text(style, " ".join(parts)))


def _width(text: str, size: float, *, bold: bool = False) -> float:
    """The width of one line of text in the face that will draw it."""
    return stringWidth(text, pdf_font_for_text(text, bold=bold), size)


class _Styles:
    """The paragraph styles of one document."""

    def __init__(self) -> None:
        base = getSampleStyleSheet()["Normal"]
        ink = colors.HexColor(_INK)
        self.title = ParagraphStyle(
            "HakTitle", parent=base, fontName=BOLD_FONT, fontSize=13, leading=16, textColor=ink, alignment=TA_CENTER
        )
        self.subtitle = ParagraphStyle(
            "HakSub", parent=base, fontName=BODY_FONT, fontSize=8.5, leading=11, alignment=TA_CENTER
        )
        self.body = ParagraphStyle("HakBody", parent=base, fontName=BODY_FONT, fontSize=8, leading=10)
        self.label = ParagraphStyle(
            "HakLabel", parent=self.body, fontSize=7.5, leading=9.5, textColor=colors.HexColor(_MUTED)
        )
        self.strong = ParagraphStyle("HakStrong", parent=self.body, fontName=BOLD_FONT)
        self.head = ParagraphStyle("HakHeading", parent=self.strong, textColor=ink)
        self.head_r = ParagraphStyle("HakHeadingR", parent=self.head, alignment=TA_RIGHT)
        self.second = ParagraphStyle(
            "HakSecond", parent=self.body, fontSize=7, leading=9, textColor=colors.HexColor(_MUTED)
        )
        self.second_strong = ParagraphStyle("HakSecondB", parent=self.second, fontName=BOLD_FONT)
        self.letter = ParagraphStyle("HakLetter", parent=self.body, alignment=TA_CENTER)
        self.letter_strong = ParagraphStyle("HakLetterB", parent=self.letter, fontName=BOLD_FONT)
        self.money = ParagraphStyle("HakMoney", parent=self.body, alignment=TA_RIGHT, splitLongWords=0)
        self.money_strong = ParagraphStyle("HakMoneyB", parent=self.money, fontName=BOLD_FONT)
        self.held = ParagraphStyle("HakHeld", parent=self.money_strong, textColor=colors.HexColor(_ALERT))
        self.note = ParagraphStyle("HakNote", parent=self.body, fontSize=7, leading=9)
        self.sign = ParagraphStyle("HakSign", parent=self.body, fontName=BOLD_FONT, alignment=TA_CENTER)
        self.sign_name = ParagraphStyle("HakSignName", parent=self.body, fontSize=7.5, leading=9.5)
        self.sign_name.alignment = TA_CENTER
        self.sign_small = ParagraphStyle(
            "HakSignS", parent=self.body, fontSize=7, leading=10, alignment=TA_LEFT, splitLongWords=0
        )


class _CellStyles:
    """The works list styles at one cell size."""

    def __init__(self, size: float) -> None:
        base = getSampleStyleSheet()["Normal"]
        leading = size + 1.5
        self.size = size
        self.cell = ParagraphStyle("HakCell", parent=base, fontName=BODY_FONT, fontSize=size, leading=leading)
        self.cell_b = ParagraphStyle("HakCellB", parent=self.cell, fontName=BOLD_FONT)
        # A number, a unit and a code are single tokens: they are given the
        # room they need and are never cut to fit.
        self.token = ParagraphStyle("HakToken", parent=self.cell, splitLongWords=0)
        self.token_b = ParagraphStyle("HakTokenB", parent=self.token, fontName=BOLD_FONT)
        self.cell_r = ParagraphStyle("HakCellR", parent=self.token, alignment=TA_RIGHT)
        self.cell_br = ParagraphStyle("HakCellBR", parent=self.cell_r, fontName=BOLD_FONT)
        self.cell_c = ParagraphStyle("HakCellC", parent=self.token, alignment=TA_CENTER)
        self.head = ParagraphStyle(
            "HakHead", parent=self.cell_c, fontName=BOLD_FONT, textColor=colors.HexColor(_INK), splitLongWords=0
        )


class _NumberedCanvas(Canvas):
    """A canvas that knows the page count, so each page can print "x / y".

    The pages are kept and replayed at ``save``, which is the first moment the
    total is known. The running header, the footer, the draft banner and the
    draft watermark are drawn in that replay.
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
        usable = width - 2 * _SIDE_MARGIN
        self.saveState()

        # Running header: what the document is and which one, on every page,
        # so a page that leaves the file can be put back. The room on the
        # right belongs to the logo.
        room = usable - _LOGO_ROOM
        fixed, face, size = pdf_fit_line(
            furniture["running_wide"] if width > height else furniture["running"], room, size=7.5, bold=True
        )
        self.setFillColor(colors.HexColor(_INK))
        self.setFont(face, size)
        self.drawString(_SIDE_MARGIN, height - 10 * mm, fixed)
        taken = stringWidth(fixed, face, size)
        tail = furniture["running_tail"]
        if tail and room - taken > 30 * mm:
            text, face, size = pdf_fit_line(f"  |  {tail}", room - taken, size=size)
            self.setFont(face, size)
            self.drawString(_SIDE_MARGIN + taken, height - 10 * mm, text)

        banner = furniture["banner"]
        if banner:
            self.setFillColor(colors.HexColor(_ALERT))
            self.setFont(pdf_font_for_text(banner, bold=True), 8)
            self.drawString(_SIDE_MARGIN, height - 14.5 * mm, banner)

        # Footer: the registers' own, a rule over the firm, the time the file
        # was generated and the page counter.
        self.setStrokeColor(_RULE)
        self.setLineWidth(0.5)
        self.line(_SIDE_MARGIN, 13 * mm, width - _SIDE_MARGIN, 13 * mm)
        page_text = " - ".join(part.format(page=self._pageNumber, pages=total) for part in furniture["page_of"])
        left, face, left_size = pdf_fit_line(
            furniture["footer_left"],
            pdf_room_beside(usable, page_text),
            suffix=furniture["footer_suffix"],
            base=BODY_FONT,
        )
        self.setFillColor(colors.HexColor(furniture["footer_color"]))
        self.setFont(face, left_size)
        self.drawString(_SIDE_MARGIN, 9 * mm, left)
        self.setFont(pdf_font_for_text(page_text), 7)
        self.drawRightString(width - _SIDE_MARGIN, 9 * mm, page_text)

        # Over the rule, in the margin: the form the summary follows (bottom
        # left, where the form itself prints it) and how the numbers are
        # written. Drawn here so that it can never start a page of its own.
        fine = "  |  ".join(furniture["fine"] if width > height else furniture["fine_summary"])
        if fine:
            text, face, fine_size = pdf_fit_line(fine, usable, size=6.0)
            self.setFillColor(colors.HexColor(_MUTED))
            self.setFont(face, fine_size)
            self.drawString(_SIDE_MARGIN, 14.3 * mm, text)

        watermark = furniture["watermark"]
        if watermark:
            # Across the sheet, so a draft cannot be signed for a certificate.
            face = pdf_font_for_text(watermark, bold=True)
            diagonal = math.hypot(width, height)
            mark_size = min(96.0, 0.62 * diagonal / max(stringWidth(watermark, face, 1.0), 0.01))
            self.setFillColor(colors.HexColor(_ALERT))
            self.setFillAlpha(0.09)
            self.translate(width / 2, height / 2)
            self.rotate(math.degrees(math.atan2(height, width)))
            self.setFont(face, mark_size)
            self.drawCentredString(0, -0.35 * mark_size, watermark)
        self.restoreState()


# ── Header block ──────────────────────────────────────────────────────────


def _contractor_words(
    cert: Certificate, languages: Sequence[str], overrides: Any, *, upper: bool = False
) -> tuple[str, ...]:
    """What the paid party is called, the same in the header as under its signature.

    A contract whose signature block is signed by the "subcontractor" names
    the party that way in the header too; one document, one name.
    """
    key = contractor_label_key(cert.inp.signature_roles)
    words = tuple(label(key, language, overrides) for language in languages)
    return tuple(upper_for(language, word) for language, word in zip(languages, words, strict=True)) if upper else words


def _party_cell(party: CertificateParty, languages: Sequence[str], overrides: Any, s: _Styles) -> Paragraph:
    """A party on three short lines: its name, its tax office and number, its address.

    A detail that was not given prints a dash, so the reader sees that it is
    missing and not that the form has no place for it.
    """

    def words(key: str) -> str:
        return " / ".join(dict.fromkeys(label(key, language, overrides) for language in languages))

    tax = (
        f"{words('header.tax_office')}: {party.tax_office or _DASH}"
        f"  -  {words('header.tax_number')}: {party.tax_number or _DASH}"
    )
    address = f"{words('header.address')}: {party.address or _DASH}"
    text = f'{_esc(party.name or _DASH)}<br/><font size="7" color="{_MUTED}">{_esc(tax)}<br/>{_esc(address)}</font>'
    return Paragraph(text, pdf_style_for_text(s.body, f"{party.name} {tax} {address}"))


def _header_table(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    issue: date | None,
    s: _Styles,
    width: float,
) -> Table:
    """The job, the certificate and the two parties, compact enough to leave the page to the figures."""
    inp = cert.inp
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None

    def parts(key: str) -> tuple[str, ...]:
        return tuple(label(key, language, overrides) for language in languages)

    def name(words: Sequence[str]) -> Paragraph:
        return _stacked(words, s.label, small=0.5)

    def day(value: date) -> str:
        return format_date(value, inp.country_code)

    kind = "title.final" if inp.is_final else "title.interim"
    number = f"{inp.certificate_number} ({' / '.join(parts(kind))})"
    currency = currency_label(inp.currency, languages[0], overrides)

    rows: list[list[Any]] = []
    commands: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.5, _RULE),
        ("BACKGROUND", (0, 0), (0, -1), _FILL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]

    def wide(key: str, value: str) -> None:
        index = len(rows)
        rows.append([name(parts(key)), _para(value or _DASH, s.body), "", ""])
        commands.append(("SPAN", (1, index), (3, index)))

    def pair(left: tuple[Sequence[str], Any], right: tuple[Sequence[str], Any]) -> None:
        index = len(rows)
        rows.append([name(left[0]), left[1], name(right[0]), right[1]])
        commands.append(("BACKGROUND", (2, index), (2, index), _FILL))

    wide("header.project", inp.project_name)
    if inp.contract_title:
        wide("header.contract", inp.contract_title)
    pair(
        (parts("header.contract_number"), _para(inp.contract_number or _DASH, s.body)),
        (parts("header.certificate_number"), _para(number, s.strong)),
    )
    pair(
        (parts("header.period"), _para(f"{day(inp.period_start)} - {day(inp.period_end)}", s.body)),
        (parts("header.issue_date"), _para(day(issue) if issue is not None else _DASH, s.body)),
    )
    if _lira_equivalent_missing(cert):
        # A certificate in a foreign currency owes its reader the lira
        # equivalent. The rate is not an input of the certificate, so no
        # figure is made up: the line says what is missing.
        pair(
            (parts("header.currency"), _para(currency, s.body)),
            (parts("fx.title"), _para(" / ".join(parts("fx.rate_missing")), s.strong)),
        )
    pair(
        (parts("header.employer"), _party_cell(inp.employer, languages, overrides, s)),
        (_contractor_words(cert, languages, overrides), _party_cell(inp.contractor, languages, overrides, s)),
    )

    label_width = 27 * mm
    table = Table(rows, colWidths=[label_width, width / 2 - label_width] * 2)
    table.setStyle(TableStyle(commands))
    return table


def _lira_equivalent_missing(cert: Certificate) -> bool:
    """Whether the certificate is in a currency other than its country's own."""
    return is_foreign_currency(cert.inp.country_code, cert.inp.currency)


# ── Signatures ────────────────────────────────────────────────────────────


def _caption_lines(languages: Sequence[str], overrides: Any, room: float, s: _Styles) -> Paragraph:
    """Name, signature and date, each followed by dots up to the edge of its block."""
    size = s.sign_small.fontSize
    dot = _width(".", size)
    lines: list[str] = []
    for key in ("sign.name", "sign.signature", "sign.date"):
        caption = f"{' / '.join(label(key, language, overrides) for language in languages)}:"
        if key == "sign.date":
            dots = "..../..../........"
        else:
            dots = "." * max(8, min(40, int((room - _width(f"{caption} ", size)) / dot) - 1))
        if _width(f"{caption} {dots}", size) > room:
            # Too narrow for both on one line: the caption, then the dots
            # under it, never a caption cut off from a few stray dots.
            lines.append(f"{_esc(caption)}<br/>{dots}")
        else:
            lines.append(f"{_esc(caption)} {dots}")
    return Paragraph("<br/>".join(lines), s.sign_small)


def _signature_tables(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    s: _Styles,
    width: float,
    *,
    per_row: int,
) -> list[Table]:
    """The signature blocks, in rows of equal blocks: five roles print as three and two."""
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    roles = list(cert.inp.signature_roles)
    if not roles:
        return []
    row_count = math.ceil(len(roles) / per_row)
    size = math.ceil(len(roles) / row_count)
    tables: list[Table] = []
    for start in range(0, len(roles), size):
        chunk = roles[start : start + size]
        column = width / len(chunk)
        titles: list[Any] = []
        names: list[Any] = []
        for role in chunk:
            if role in ("contractor", "subcontractor"):
                parts = _contractor_words(cert, languages, overrides, upper=True)
            else:
                parts = tuple(upper_for(language, label(f"role.{role}", language, overrides)) for language in languages)
            titles.append(_stacked(parts, s.sign))
            party = getattr(cert.inp, _ROLE_PARTY[role], None) if role in _ROLE_PARTY else None
            names.append(_para(party.name if party is not None else "", s.sign_name))
        captions = _caption_lines(languages, overrides, column - 12, s)
        table = Table(
            [titles, names, [""] * len(chunk), [captions] * len(chunk)],
            colWidths=[column] * len(chunk),
            rowHeights=[None, None, 4.5 * mm, None],
        )
        commands: list[tuple[Any, ...]] = [
            ("LINEAFTER", (0, 0), (-2, -1), 0.4, _RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        if tables:
            commands.append(("LINEABOVE", (0, 0), (-1, 0), 0.6, _FRAME_RULE))
        table.setStyle(TableStyle(commands))
        tables.append(table)
    return tables


# ── Summary ───────────────────────────────────────────────────────────────


def _amount_text(line: PrintedSummaryLine, currency: str) -> str:
    refs = "".join(f" ({number})" for number in line.notes)
    if line.status == "held":
        return f"{line.text}{refs}"
    return f"{line.text} {currency}{refs}" if line.status == "value" else line.text


def _amount_cell(line: PrintedSummaryLine, currency: str, s: _Styles) -> Paragraph:
    text = _amount_text(line, currency)
    if line.status == "held":
        return _para(text, s.held)
    return _para(text, s.money_strong if line.emphasis else s.money)


def _label_cell(name: str, formula: str, detail: str, style: ParagraphStyle) -> Paragraph:
    """A line's label with its formula, and what it rests on in small print under it."""
    text = _esc(name) + (f" {_esc(formula)}" if formula else "")
    if detail:
        text += f'<br/><font size="6.5" color="{_MUTED}">{_esc(detail)}</font>'
    return Paragraph(text, pdf_style_for_text(style, f"{name} {detail}"))


def _summary_table(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    s: _Styles,
    width: float,
    *,
    heading: Sequence[str] = (),
    remarks: Sequence[Any] = (),
    signatures: Sequence[Any] = (),
    tie: int = _TIE_BLOCKS,
) -> Table:
    """The lettered lines in one frame with their heading and their signatures.

    One language prints letter, label and amount. Two print the English label
    in a column of its own beside the Turkish one, so a bilingual certificate
    is no taller than a Turkish one and keeps to the same page.

    The heading is the table's first row and is repeated when the table runs
    onto another page. The rows are tied in blocks (the work, the
    certificate, the deductions, the result with the signatures), so a page
    break falls between blocks and the signatures are never alone.
    """
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    currency = currency_label(cert.inp.currency, languages[0], overrides)
    lines = printed_summary(cert, locale, settings)
    last = len(languages) + 1

    amount_head = f"{' / '.join(label('header.amount', language, overrides) for language in languages)} ({currency})"
    first_row: list[Any] = [_para(heading[0] if heading else "", s.head), ""]
    first_row += [_para(part, s.second_strong) for part in heading[1:]] or [""] * (len(languages) - 1)
    first_row.append(_para(amount_head, s.head_r))
    rows: list[list[Any]] = [first_row[: last + 1]]
    commands: list[tuple[Any, ...]] = [
        ("BOX", (0, 0), (-1, -1), 0.8, _FRAME_RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), _FILL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, _FRAME_RULE),
    ]
    blocks: list[list[int]] = []
    previous_section = ""
    reasoned = {computed.key for computed in cert.summary if computed.basis.get("remark")}
    for line in lines:
        if line.section != previous_section:
            index = len(rows)
            blocks.append([index, index])
            if line.section == "deductions":
                band = " / ".join(
                    upper_for(language, label("section.deductions", language, overrides)) for language in languages
                )
                rows.append([_para(band, s.head), *[""] * last])
                commands += [("SPAN", (0, index), (-1, index)), ("BACKGROUND", (0, index), (-1, index), _FILL)]
            elif index > 1:
                commands.append(("LINEABOVE", (0, index), (-1, index), 0.8, _FRAME_RULE))
            previous_section = line.section
        deduction = line.section == "deductions"
        letter = f"{line.letter})" if deduction and line.letter else line.letter
        cells: list[Any] = [_para(letter, s.letter_strong if line.emphasis else s.letter)]
        for position, name in enumerate(line.labels):
            if position == 0:
                style = s.strong if line.emphasis else s.body
            else:
                style = s.second_strong if line.emphasis else s.second
            # The formula, the code and the legal basis are the same in every
            # language and are printed once, on the line a Turkish reader
            # checks. A reason is a sentence, and is printed in each language
            # under that language's label.
            first = position == 0
            detail = line.details[position] if first or line.key in reasoned else ""
            if not first and detail == line.details[0]:
                detail = ""
            cells.append(_label_cell(name, line.formulas[0] if first else "", detail, style))
        cells.append(_amount_cell(line, currency, s))
        rows.append(cells)
        blocks[-1][1] = len(rows) - 1
        if line.emphasis:
            commands.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), _FILL))

    for flowables, padding in ((list(remarks), 3), (list(signatures), 0)):
        if not flowables:
            continue
        index = len(rows)
        rows.append([flowables, *[""] * last])
        commands += [
            ("SPAN", (0, index), (-1, index)),
            ("LINEABOVE", (0, index), (-1, index), 0.8, _FRAME_RULE),
            ("LEFTPADDING", (0, index), (-1, index), padding),
            ("RIGHTPADDING", (0, index), (-1, index), padding),
            ("TOPPADDING", (0, index), (-1, index), padding),
            ("BOTTOMPADDING", (0, index), (-1, index), padding),
        ]
        if blocks:
            blocks[-1][1] = index
    if tie == _TIE_BLOCKS:
        commands += [("NOSPLIT", (0, start), (-1, end)) for start, end in blocks if end > start]
    elif tie == _TIE_SIGNATURES and blocks and blocks[-1][1] > blocks[-1][0]:
        commands.append(("NOSPLIT", (0, blocks[-1][0]), (-1, blocks[-1][1])))

    letter_width = 9 * mm
    widest = max((_width(_amount_text(line, currency), 8, bold=True) for line in lines), default=0.0)
    amount_width = min(max(widest + 14, 32 * mm), 60 * mm)
    labels_width = width - letter_width - amount_width
    if len(languages) == 1:
        widths = [letter_width, labels_width, amount_width]
    else:
        widths = [letter_width, labels_width * 0.58, labels_width * 0.42, amount_width]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(commands))
    return table


def _notes_block(cert: Certificate, locale: str, settings: HakedisSettings | None, s: _Styles) -> list[Any]:
    """The reasons a certificate is a draft, one paragraph per reason.

    Lines held for the same reason share a paragraph: four tax lines waiting
    for one calculation are one thing to act on, not four.
    """
    notes = cert.notes
    if not notes:
        return []
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    title = " / ".join(upper_for(language, label("draft.notes_title", language, overrides)) for language in languages)
    flowables: list[Any] = [Spacer(1, 2.5 * mm)]
    paragraphs: list[Any] = []
    groups: dict[tuple[Any, ...], list[Any]] = {}
    for note in notes:
        groups.setdefault((note.reason_key, tuple(sorted(note.params.items()))), []).append(note)
    for group in groups.values():
        numbers = " ".join(f"({note.number})" for note in group)
        parts = []
        for language in languages:
            names = ", ".join(
                f"{note.letter}) " * bool(note.letter) + label(f"line.{note.line_key}", language, overrides)
                for note in group
            )
            parts.append(f"{names}: {note_text(group[0], cert, language, settings)}")
        paragraphs.append(_stacked((f"{numbers} {parts[0]}", *parts[1:]), s.note, small=0.5))
    # The title never stays behind at the foot of a page without a note under it.
    flowables.append(KeepTogether([_para(title, s.head), *paragraphs[:1]]))
    flowables.extend(paragraphs[1:])
    return flowables


# ── Works list ────────────────────────────────────────────────────────────


def _fraction_digits(text: str, decimal: str) -> int:
    """How many digits a printed number carries after its decimal separator."""
    number = text.rsplit(" ", 1)[-1]
    return len(number.rsplit(decimal, 1)[1]) if decimal in number else 0


def _longest_word(text: str, size: float, *, bold: bool = False) -> float:
    return max((_width(word, size, bold=bold) for word in text.split()), default=0.0)


def _measured_widths(
    columns: Sequence[ColumnDef],
    heads: Sequence[Sequence[str]],
    body: Sequence[tuple[Sequence[str], bool, Sequence[float]]],
    width: float,
    size: float,
) -> tuple[list[float], bool]:
    """A width per column from what it prints, and whether the description kept its room.

    A number, a unit and a sequence number need their whole printed value on
    one line; a code needs its longest unbroken part and, while it stays
    short, the whole of it; a header needs its longest word. The description
    takes what is left of the sheet.
    """
    slack = 2 * _CELL_PADDING + 1.5
    needed: list[float] = []
    for position, column in enumerate(columns):
        if column.key == "description":
            needed.append(0.0)
            continue
        head = max((_longest_word(text, size, bold=True) for text in (column.letter, *heads[position])), default=0.0)
        values = 0.0
        for cells, bold, extra in body:
            text = cells[position]
            if not text:
                continue
            if column.kind == "text":
                whole = _width(text, size, bold=bold)
                token = _longest_word(text, size, bold=bold)
                values = max(values, whole if whole <= _CODE_WHOLE_MM * mm else token)
            else:
                values = max(values, _width(text, size, bold=bold) + extra[position])
        floor = (_CODE_FLOOR_MM if column.kind == "text" else _COLUMN_FLOOR_MM.get(column.kind, 0)) * mm
        needed.append(max(head + slack, values + slack, floor))
    if not any(column.key == "description" for column in columns):
        scale = width / sum(needed)
        return [value * scale for value in needed], scale >= 1.0
    room = width - sum(needed)
    fits = room >= _MIN_DESCRIPTION_MM * mm
    description = max(room, _LEAST_DESCRIPTION_MM * mm)
    widths = [
        description if column.key == "description" else value for column, value in zip(columns, needed, strict=True)
    ]
    total = sum(widths)
    if total > width:
        # Only a sheet that cannot hold its own numbers gets here; the columns
        # give way together and the numbers still print on one line each.
        widths = [value * width / total for value in widths]
    return widths, fits


def _works_table(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    width: float,
    *,
    footnotes: Sequence[Any] = (),
    signatures: Sequence[Any] = (),
    tie: int = _TIE_BLOCKS,
) -> Table:
    """The works list with its total, its footnotes and its signatures in one frame.

    The last work item, the subtotal, the total and the signatures are tied
    together, so the signatures always stand under figures, and the column
    header is repeated above them when they move to a new page.
    """
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    inp = cert.inp
    flavour = inp.flavour
    columns, rows = printed_works(cert, locale, settings)
    decimal = number_style(inp.country_code, inp.currency).decimal
    flag_column = _flag_column(cert, columns)
    title_column = next((i for i, column in enumerate(columns) if column.key == "description"), 0)
    heads = [
        tuple(label(f"col.{flavour}.{column.key}", language, overrides) for language in languages) for column in columns
    ]

    # What every row prints, before anything is measured.
    printed: list[tuple[str, list[str], bool]] = []
    for row in rows:
        if row.kind == "section":
            printed.append(("section", [row.title], True))
            continue
        bold = row.kind != "line"
        cells = list(row.cells)
        if bold:
            cells[title_column] = row.title
        if row.kind == "line" and row.flagged and flag_column is not None and cells[flag_column]:
            # The marker stands in front, so the number stays in its column.
            cells[flag_column] = f"(!) {cells[flag_column]}"
        printed.append((row.kind, cells, bold))

    # Decimal separators of a column line up: a value with fewer decimals than
    # its neighbours is moved left by the width of the digits it does not have.
    most = [
        max(
            (_fraction_digits(cells[i], decimal) for kind, cells, _ in printed if kind != "section" and cells[i]),
            default=0,
        )
        if column.kind in _ALIGNED_KINDS
        else 0
        for i, column in enumerate(columns)
    ]

    def paddings(cells: Sequence[str], size: float) -> list[float]:
        extra: list[float] = []
        for position, text in enumerate(cells):
            missing = most[position] - _fraction_digits(text, decimal) if text and most[position] else 0
            pad = missing * _width("0", size)
            if missing and missing == most[position]:
                pad += _width(decimal, size)
            extra.append(pad)
        return extra

    widths: list[float] = []
    c = _CellStyles(_CELL_SIZES[0])
    for size in _CELL_SIZES:
        c = _CellStyles(size)
        body = [(cells, bold, paddings(cells, size)) for kind, cells, bold in printed if kind != "section"]
        widths, fits = _measured_widths(columns, heads, body, width, size)
        if fits:
            break

    data: list[list[Any]] = [
        [_para(column.letter, c.head) for column in columns],
        [_stacked(names, c.head, small=0.5) for names in heads],
    ]
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 1), _FILL),
        ("BOX", (0, 0), (-1, -1), 0.6, _FRAME_RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _RULE),
        ("LINEBELOW", (0, 1), (-1, 1), 0.6, _FRAME_RULE),
        ("VALIGN", (0, 0), (-1, 1), "MIDDLE"),
        ("VALIGN", (0, 2), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), _CELL_PADDING),
        ("RIGHTPADDING", (0, 0), (-1, -1), _CELL_PADDING),
    ]
    last_line = total_row = None
    for kind, cells, bold in printed:
        index = len(data)
        if kind == "section":
            data.append([_para(cells[0], c.cell_b), *[""] * (len(columns) - 1)])
            commands += [("SPAN", (0, index), (-1, index)), ("BACKGROUND", (0, index), (-1, index), _FILL)]
            continue
        extra = paddings(cells, c.size)
        drawn: list[Any] = []
        for position, (column, text) in enumerate(zip(columns, cells, strict=True)):
            if column.kind in _NUMERIC_KINDS:
                style = c.cell_br if bold else c.cell_r
            elif column.kind in ("seq", "unit"):
                style = c.cell_c
            elif column.key == "description":
                style = c.cell_b if bold else c.cell
            else:
                style = c.token_b if bold else c.token
            drawn.append(_para(text, style))
            if extra[position]:
                commands.append(("RIGHTPADDING", (position, index), (position, index), _CELL_PADDING + extra[position]))
        data.append(drawn)
        if kind == "line":
            last_line = index
        else:
            commands.append(("LINEABOVE", (0, index), (-1, index), 0.6, _FRAME_RULE))
            if kind == "total":
                total_row = index
                commands.append(("BACKGROUND", (0, index), (-1, index), _FILL))

    for flowables, padding in ((list(footnotes), 3), (list(signatures), 0)):
        if not flowables:
            continue
        index = len(data)
        data.append([flowables, *[""] * (len(columns) - 1)])
        commands += [
            ("SPAN", (0, index), (-1, index)),
            ("LINEABOVE", (0, index), (-1, index), 0.6, _FRAME_RULE),
            ("LEFTPADDING", (0, index), (-1, index), padding),
            ("RIGHTPADDING", (0, index), (-1, index), padding),
            ("TOPPADDING", (0, index), (-1, index), padding),
            ("BOTTOMPADDING", (0, index), (-1, index), padding),
        ]
    end = len(data) - 1
    tied_from = last_line if tie == _TIE_BLOCKS else total_row if tie == _TIE_SIGNATURES else None
    if tied_from is not None and end > tied_from:
        commands.append(("NOSPLIT", (0, tied_from), (-1, end)))

    table = Table(data, colWidths=widths, repeatRows=2)
    table.setStyle(TableStyle(commands))
    return table


def _flag_column(cert: Certificate, columns: Sequence[ColumnDef]) -> int | None:
    """The column an over-measured row is marked in, when the list shows what it is measured against."""
    if cert.inp.flavour != "lump_sum" and not any(column.key == "contract_quantity" for column in columns):
        return None
    return next(
        (i for i, column in enumerate(columns) if column.key in ("cumulative_quantity", "cumulative_pct")), None
    )


def _works_footnotes(cert: Certificate, locale: str, settings: HakedisSettings | None, s: _Styles) -> list[Any]:
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    columns, rows = printed_works(cert, locale, settings)
    lump_sum = cert.inp.flavour == "lump_sum"
    keys: list[str] = []
    if lump_sum and any(column.key == "weight_pct" for column in columns):
        keys.append("works.weight_note")
    if _flag_column(cert, columns) is not None and any(row.kind == "line" and row.flagged for row in rows):
        keys.append("works.over_complete_note" if lump_sum else "works.over_measured_note")
    period = [i for i, column in enumerate(columns) if column.key.startswith("period_")]
    if any(
        row.kind == "line" and any(value is not None and value < 0 for value in (row.values[i] for i in period))
        for row in rows
    ):
        keys.append("works.negative_note")
    return [
        _stacked(tuple(label(key, language, overrides) for language in languages), s.note, small=0.5) for key in keys
    ]


# ── The document ──────────────────────────────────────────────────────────


def _stamp(moment: datetime, country_code: str) -> str:
    """The moment a file was generated, the date written the document's way."""
    utc = moment.astimezone(UTC) if moment.tzinfo is not None else moment
    return f"{format_date(utc.date(), country_code)} {utc:%H:%M} UTC"


def render_hakedis_pdf(
    cert: Certificate,
    *,
    locale: str = "tr",
    settings: HakedisSettings | None = None,
    issue_date: date | None = None,
    generated_at: datetime | None = None,
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
        generated_at: The moment printed in the footer as the time the file
            was generated. ``None`` is now.

    Raises:
        ValueError: ``locale`` is not one of the three.
    """
    locale_languages(locale)
    moment = generated_at if generated_at is not None else datetime.now(tz=UTC)
    for tie in (_TIE_BLOCKS, _TIE_SIGNATURES):
        try:
            return _render(cert, locale, settings, issue_date, moment, tie)
        except LayoutError:
            # A tied block taller than a page: tie less and lay out again.
            continue
    return _render(cert, locale, settings, issue_date, moment, _TIE_NOTHING)


def _render(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None,
    issue_date: date | None,
    moment: datetime,
    tie: int,
) -> bytes:
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
    summary_width = portrait_w - 2 * _SIDE_MARGIN
    works_width = land_w - 2 * _SIDE_MARGIN
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
    letterhead = branded_letterhead(summary_width)

    def on_page(canvas: Any, page_doc: Any) -> None:
        if letterhead is not None and canvas.getPageNumber() == 1:
            # The letterhead under it already carries the logo.
            return
        # The logo is placed from the sheet this page is actually drawn on:
        # the document's own page size is the portrait one of page one.
        sheet = SimpleNamespace(
            pagesize=tuple(canvas._pagesize),
            leftMargin=_SIDE_MARGIN,
            rightMargin=_SIDE_MARGIN,
            page=canvas.getPageNumber(),
        )
        branded_header_logo(canvas, sheet)

    def frame(page_w: float, page_h: float, name: str) -> Frame:
        return Frame(
            _SIDE_MARGIN,
            _BOTTOM_MARGIN,
            page_w - 2 * _SIDE_MARGIN,
            page_h - _TOP_MARGIN - _BOTTOM_MARGIN,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id=name,
        )

    doc.addPageTemplates(
        [
            PageTemplate(id="summary", frames=[frame(portrait_w, portrait_h, "summary")], pagesize=A4, onPage=on_page),
            PageTemplate(id="works", frames=[frame(land_w, land_h, "works")], pagesize=landscape(A4), onPage=on_page),
        ]
    )

    day = format_date(inp.period_end, inp.country_code)
    work_to_date = tuple(
        upper_for(language, label("header.work_to_date", language, overrides, date=day)) for language in languages
    )
    number = f"{' / '.join(words('header.certificate_number'))}: {inp.certificate_number}"
    currency = currency_label(inp.currency, languages[0], overrides)
    project_line = f"{inp.project_name} - {number} - {' / '.join(words('header.currency'))}: {currency}"

    story: list[Any] = []
    if letterhead is not None:
        story.append(letterhead)
    story += [
        _title(upper("title.report"), s.title),
        Spacer(1, 1.5 * mm),
        _header_table(cert, locale, settings, issue_date, s, summary_width),
        Spacer(1, 1.5 * mm),
        _summary_table(
            cert,
            locale,
            settings,
            s,
            summary_width,
            heading=work_to_date,
            remarks=[_stacked(words("fx.explanation", currency=currency), s.note, small=0.5)]
            if _lira_equivalent_missing(cert)
            else (),
            signatures=_signature_tables(cert, locale, settings, s, summary_width, per_row=_SIGNATURES_PER_ROW),
            tie=tie,
        ),
    ]
    fine: list[str] = []
    fine_summary: list[str] = []
    standard = DEFAULT_LAYOUTS.get((inp.country_code or "").strip().upper())
    if standard is not None and [(line.key, line.letter) for line in inp.layout] == [
        (line.key, line.letter) for line in standard
    ]:
        # The lines and letters are the official form's: say which form.
        fine_summary.append(label("form.reference.summary", languages[0], overrides))
    if "en" in languages and number_style(inp.country_code, inp.currency).decimal != ".":
        fine.append(label("note.number_format", "en", overrides))
    story += [
        *_notes_block(cert, locale, settings, s),
        NextPageTemplate("works"),
        PageBreak(),
        _title(upper("title.works_list"), s.title),
        _stacked(words(f"subtitle.{inp.flavour}"), s.subtitle),
        _para(project_line, s.subtitle),
        Spacer(1, 3 * mm),
        _works_table(
            cert,
            locale,
            settings,
            works_width,
            footnotes=_works_footnotes(cert, locale, settings, s),
            signatures=_signature_tables(cert, locale, settings, s, works_width, per_row=_SIGNATURES_PER_WIDE_ROW),
            tie=tie,
        ),
    ]

    reference = number
    if inp.contract_number:
        reference = f"{reference} - {inp.contract_number}"
    look = branded_appearance() or {}
    custom_footer = str(look.get("footer_text") or "").strip()
    generated = label("footer.generated", languages[0], overrides, timestamp=_stamp(moment, inp.country_code))
    furniture = {
        "page_of": words("page.of"),
        # The title in the first language only: the line shares the top of
        # the sheet with the logo and must keep the number whole.
        "running": f"{upper('title.report')[0]}  |  {reference}",
        "running_wide": f"{upper('title.works_list')[0]}  |  {reference}",
        "running_tail": inp.project_name,
        "banner": " / ".join(words("draft.banner")) if cert.is_draft else "",
        "watermark": " / ".join(upper("status.draft")) if cert.is_draft else "",
        # A workspace that saved its own footer line means it: it replaces
        # the firm and the time, as on the registers.
        "footer_left": custom_footer[:160] or branded_cover_brand(),
        "footer_suffix": "" if custom_footer else f"  |  {generated}",
        "footer_color": look.get("footer_color") or _FOOTER,
        "fine": fine,
        "fine_summary": [*fine_summary, *fine],
    }
    canvas_class = type("HakedisCanvas", (_NumberedCanvas,), {"furniture": furniture})
    doc.build(story, canvasmaker=canvas_class)
    return buf.getvalue()


__all__ = ["render_hakedis_pdf"]
