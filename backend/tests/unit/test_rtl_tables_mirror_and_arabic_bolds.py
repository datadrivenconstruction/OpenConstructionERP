# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A right-to-left document lays its tables out right to left, and can be bold.

Shaping already worked: letters joined and each line read in the right order.
What stayed left to right was the layout. An Arabic invoice put the item number
in the leftmost column and the amount in the rightmost one, which is the mirror
image of how the same invoice is laid out on paper in Cairo. And the only face
that draws every Urdu letter had one weight, so bold Urdu printed regular.

Positions are read back from the rendered PDF with pypdfium2, because a table
whose data was reversed but whose widths or rules were not is still wrong on
paper and right in memory.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from app.core import pdf_fonts, pdf_reader
from app.core.pdf_rtl import mirror_table_commands, table_direction
from tests._pdf_probe import embedded_fonts

URDU = "یہ ٹیکس ہے"


def _words(pdf: bytes) -> list[tuple[int, float, float, str]]:
    """Every word as (page, x0, y0, text)."""
    with pdf_reader.open_pdf(pdf) as document:
        return [(n, w[0], w[1], w[4]) for n, page in enumerate(document) for w in page.words()]


def _x(words: list[tuple[int, float, float, str]], text: str, page: int = 0) -> float:
    return next(x for p, x, _y, t in words if t == text and p == page)


def _render(flowables: list) -> bytes:
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer).build(flowables)
    return buffer.getvalue()


def test_a_table_built_right_to_left_puts_its_first_column_on_the_right() -> None:
    with table_direction("rtl"):
        table = Table([["first", "middle", "last"]], colWidths=[60, 120, 200])
    words = _words(_render([table]))
    assert _x(words, "first") > _x(words, "middle") > _x(words, "last")


def test_the_widths_travel_with_their_columns() -> None:
    with table_direction("rtl"):
        table = Table([["first", "middle", "last"]], colWidths=[60, 120, 200])
    assert table._colWidths == [200, 120, 60]


def test_outside_the_context_nothing_moves() -> None:
    table = Table([["first", "middle", "last"]], colWidths=[60, 120, 200])
    words = _words(_render([table]))
    assert _x(words, "first") < _x(words, "middle") < _x(words, "last")


def test_style_commands_are_mirrored_column_for_column() -> None:
    commands = [
        ("SPAN", (0, 0), (1, 0)),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LINEBEFORE", (1, 0), (1, -1), 0.5, colors.black),
        ("BACKGROUND", (-1, 0), (-1, 0), colors.grey),
        ("FONTNAME", (0, "splitlast"), (-1, "splitlast"), "Helvetica-Bold"),
    ]
    assert mirror_table_commands(commands, 3) == [
        ("SPAN", (1, 0), (2, 0)),
        ("ALIGN", (0, 0), (2, -1), "LEFT"),
        ("LINEAFTER", (1, 0), (1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (0, 0), colors.grey),
        ("FONTNAME", (0, "splitlast"), (2, "splitlast"), "Helvetica-Bold"),
    ]


def test_a_plain_cell_in_a_mirrored_table_hugs_the_right_edge() -> None:
    with table_direction("rtl"):
        table = Table([["x", "short"]], colWidths=[200, 200])
    words = _words(_render([table]))
    # Mirrored, "x" sits in the right-hand column (page x 272 to 472 on the
    # default template). Left-aligned it would start near 278.
    assert _x(words, "x") > 400


def test_style_set_after_construction_is_mirrored_too() -> None:
    with table_direction("rtl"):
        table = Table([["a", "b", "c"]], colWidths=[100, 100, 100])
        table.setStyle(TableStyle([("ALIGN", (0, 0), (0, 0), "RIGHT")]))
    alignments = [table._cellStyles[0][col].alignment for col in range(3)]
    # Column 0 moved to index 2 and its RIGHT became LEFT; the rest keep the right-aligned base.
    assert alignments == ["RIGHT", "RIGHT", "LEFT"]


def test_a_table_split_over_pages_is_mirrored_once_on_every_page() -> None:
    rows = [[f"r{i}first", f"r{i}last"] for i in range(120)]
    with table_direction("rtl"):
        table = Table(rows, colWidths=[100, 300], repeatRows=1)
        pdf = _render([table])
    words = _words(pdf)
    pages = {p for p, *_ in words}
    assert len(pages) >= 2
    assert _x(words, "r0first", 0) > _x(words, "r0last", 0)
    last_page = max(pages)
    tail = next(t for p, _x0, _y, t in words if p == last_page and t.endswith("first") and t != "r0first")
    assert _x(words, tail, last_page) > _x(words, tail.replace("first", "last"), last_page)


def test_an_arabic_invoice_lays_its_line_items_out_right_to_left() -> None:
    from app.core.pdf_appearance import resolve_sections
    from app.modules.finance.pdf_export import build_invoice_pdf
    from tests.unit import _record_pdf_samples as samples

    def render(locale: str) -> list[tuple[int, float, float, str]]:
        pdf = build_invoice_pdf(
            samples.invoice(),
            project=samples.PROJECT,
            people=samples.PEOPLE,
            sections=resolve_sections("invoice"),
            locale=locale,
        )
        return _words(pdf)

    def item_row(words: list[tuple[int, float, float, str]]) -> tuple[float, float]:
        page, x_desc, y, _ = next(w for w in words if w[3] == "Ready-mix")
        amount = [x for p, x, yy, t in words if p == page and abs(yy - y) < 2 and t in {"1,234.57", "1.234,57"}]
        assert amount, "the line amount is not on the description's row"
        return x_desc, amount[0]

    desc, amount = item_row(render("en"))
    assert desc < amount, "English keeps the description left of the amount"
    desc, amount = item_row(render("ar"))
    assert desc > amount, "Arabic puts the description right of the amount"


def test_bold_urdu_has_a_bold_face() -> None:
    assert pdf_fonts.pdf_font_for_text(URDU) == pdf_fonts.ARABIC_FONT
    assert pdf_fonts.pdf_font_for_text(URDU, bold=True) == pdf_fonts.ARABIC_BOLD_FONT

    from reportlab.lib.fonts import tt2ps

    assert tt2ps(pdf_fonts.ARABIC_FONT, 1, 0) == pdf_fonts.ARABIC_BOLD_FONT

    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont(pdf_fonts.pdf_font_for_text(URDU, bold=True), 12)
    pdf.drawString(72, 720, URDU)
    pdf.save()
    names = [name for name, _kind in embedded_fonts(buffer.getvalue())]
    assert any("NotoNaskhArabic-Bold" in name for name in names), names
