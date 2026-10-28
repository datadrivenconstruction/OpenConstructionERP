"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Text drawn on a dark filled rectangle has to be light enough to read.

A ``TableStyle`` command cannot reach a cell that holds a flowable. A table
that fills its header row dark and then says ``("TEXTCOLOR", (0, 0), (-1, 0),
colors.white)`` gets the fill and not the colour, so the header renders in
whatever its paragraph style happens to carry. On this codebase that was
``#1a1a2e`` text on a ``#1a1a2e`` fill: not low contrast, the same colour, the
heading simply absent from the page.

Nothing else catches this. The characters are all present, correctly ordered
and correctly spelled, so ``extract_text`` returns them and every assertion
written against extracted text passes. Ruff and the type checker see a valid
command list. The only witness is the rendered page.

So this reads the page. For every run of text in the document it finds the
filled rectangle drawn under it, and where that rectangle is dark it requires
the text to contrast against it. There is deliberately no list of headings and
no list of table names here: a table added tomorrow with the same mistake fails
on arrival, which a list of the six known ones would not do.

The contrast floor is the WCAG AA ratio for normal size text. White on
``#1a1a2e`` scores about 17 and passes with room to spare; the defect this was
written for scores 1.0, the ratio of a colour with itself.
"""

from __future__ import annotations

import io
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pypdf
import pytest

# A rectangle this dark counts as a dark background. #1a1a2e and #1f2937, the
# two header fills in this codebase, both land near 0.01.
DARK_FILL_LUMINANCE = 0.25

# WCAG AA for normal size text. The headers in question are 9pt.
CONTRAST_FLOOR = 4.5

# Rules and hairlines are stroked rather than filled in every document here, so
# nothing thin is currently a candidate. The floor is kept anyway so that a
# table which draws its rules as filled rectangles cannot be mistaken for the
# background behind a baseline that happens to fall inside one.
MINIMUM_BACKGROUND_HEIGHT = 3.0

TOKEN = re.compile(rb"\[(?:[^\[\]\\]|\\.)*\]|\((?:[^()\\]|\\.)*\)|<[^>]*>|[^\s\[\]()<>]+")
PIECE = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")
ESCAPE = re.compile(rb"\\(.)")
UNIT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def times(first: tuple[float, ...], then: tuple[float, ...]) -> tuple[float, ...]:
    """The matrix that applies *first* and then *then*."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = then
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def apply(matrix: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def walk(data: bytes):
    """Yield the filled rectangles and the text runs of one content stream.

    Both come back in page coordinates. Cell contents are drawn inside their
    own ``cm`` transform, so a text matrix read on its own reports where the
    run sits within its cell rather than where it sits on the page, and the
    rectangle it is standing on would never be found.
    """
    operands: list[bytes] = []
    saved: list[tuple[float, ...]] = []
    saved_colours: list[tuple[float, ...]] = []
    ctm = UNIT
    text_matrix = UNIT
    colour = (0.0, 0.0, 0.0)
    box: tuple[float, ...] | None = None

    def number(token: bytes) -> float:
        try:
            return float(token)
        except ValueError:
            return 0.0

    for match in TOKEN.finditer(data):
        token = match.group()
        if token == b"q":
            saved.append(ctm)
            saved_colours.append(colour)
        elif token == b"Q":
            if saved:
                ctm = saved.pop()
            if saved_colours:
                colour = saved_colours.pop()
        elif token == b"cm" and len(operands) >= 6:
            ctm = times(tuple(number(n) for n in operands[-6:]), ctm)
        elif token == b"rg" and len(operands) >= 3:
            colour = tuple(number(n) for n in operands[-3:])
        elif token == b"g" and operands:
            grey = number(operands[-1])
            colour = (grey, grey, grey)
        elif token == b"re" and len(operands) >= 4:
            box = tuple(number(n) for n in operands[-4:])
        elif token in (b"f", b"f*", b"F") and box is not None:
            x0, y0 = apply(ctm, box[0], box[1])
            x1, y1 = apply(ctm, box[0] + box[2], box[1] + box[3])
            yield "rect", (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), colour
            box = None
        elif token == b"BT":
            text_matrix = UNIT
        elif token == b"Tm" and len(operands) >= 6:
            text_matrix = tuple(number(n) for n in operands[-6:])
        elif token in (b"Td", b"TD") and len(operands) >= 2:
            shift = (1.0, 0.0, 0.0, 1.0, number(operands[-2]), number(operands[-1]))
            text_matrix = times(shift, text_matrix)
        elif token in (b"Tj", b"TJ") and operands:
            raw = ESCAPE.sub(rb"\1", b"".join(PIECE.findall(operands[-1])))
            text = raw.decode("latin-1", "replace").strip()
            if text:
                x, y = apply(times(text_matrix, ctm), 0.0, 0.0)
                yield "text", text, x, y, colour
        if token[:1] in b"-.0123456789" or token[:1] in b"([<":
            operands.append(token)
        else:
            operands.clear()


def luminance(colour: tuple[float, ...]) -> float:
    """Relative luminance, as WCAG defines it."""
    channels = []
    for raw in colour[:3]:
        value = min(max(raw, 0.0), 1.0)
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: tuple[float, ...], other: tuple[float, ...]) -> float:
    first, second = luminance(one), luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def as_hex(colour: tuple[float, ...]) -> str:
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in colour[:3])


def unreadable_runs(pdf_bytes: bytes) -> list[str]:
    """Every run of text drawn too dark on a dark fill to be read."""
    complaints: list[str] = []
    for number, page in enumerate(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages):
        rectangles: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
        for event in walk(page["/Contents"].get_data()):
            if event[0] == "rect":
                _, box, fill = event
                if box[3] - box[1] >= MINIMUM_BACKGROUND_HEIGHT:
                    rectangles.append((box, fill))
                continue
            _, text, x, y, ink = event
            behind = [fill for box, fill in rectangles if box[0] <= x <= box[2] and box[1] <= y <= box[3]]
            if not behind:
                continue
            fill = behind[-1]
            if luminance(fill) >= DARK_FILL_LUMINANCE:
                continue
            ratio = contrast(ink, fill)
            if ratio < CONTRAST_FLOOR:
                complaints.append(
                    f"page {number}: {text!r} drawn {as_hex(ink)} on {as_hex(fill)}, contrast {ratio:.2f}"
                )
    return complaints


# ── The documents ───────────────────────────────────────────────────────────


def boq_data() -> Any:
    def position(ordinal: str, description: str) -> Any:
        return SimpleNamespace(
            id=uuid.uuid4(),
            boq_id=uuid.uuid4(),
            ordinal=ordinal,
            description=description,
            unit="m3",
            quantity=Decimal("4"),
            unit_rate=Decimal("25"),
            total=Decimal("100"),
        )

    sections = [
        SimpleNamespace(
            id=uuid.uuid4(),
            ordinal=str(index).zfill(2),
            description=f"Section {index}",
            positions=[position(f"{index:02d}.001", "Concrete wall")],
            subtotal=Decimal("100"),
        )
        for index in (1, 2)
    ]
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Readability BOQ",
        status="draft",
        currency="USD",
        sections=sections,
        positions=[],
        direct_cost=Decimal("200"),
        markups=[],
        net_total=Decimal("200"),
        grand_total=Decimal("200"),
    )


def boq_pdf() -> bytes:
    from app.modules.boq.pdf_export import generate_boq_pdf

    return generate_boq_pdf(boq_data(), project_name="Readability", currency="USD")


def large_boq_pdf() -> bytes:
    """The other BOQ builder, the one the router picks above 500 positions.

    Its section summary table is a second table with the same defect, and it
    lives in this entry point rather than the one above, so a payload rendered
    only through ``generate_boq_pdf`` never draws it and reports it clean.
    """
    from app.modules.boq.pdf_export import generate_boq_pdf_simple

    return generate_boq_pdf_simple(boq_data(), project_name="Readability", currency="USD")


def methodology_pdf() -> bytes:
    from app.modules.methodology.pdf_export import generate_methodology_pdf

    return generate_methodology_pdf(
        {
            "project_name": "Riverside Tower",
            "methodology_name": "Unit rate method",
            "methodology_slug": "unit-rate",
            "currency": "EUR",
            "decimals": 2,
            "direct_total": "1000000.00",
            "markup_total": "235000.00",
            "grand_total": "1235000.00",
            "prepared_by": "Cost Engineer",
            "bases": {"direct_cost": "1000000.00"},
            "composites": {"works_base": ["direct_cost"]},
            "steps": [
                {
                    "key": "overheads",
                    "kind": "percentage",
                    "category": "overhead",
                    "label": "Overheads",
                    "rate": "15.00",
                    "base_amount": "1000000.00",
                    "amount": "150000.00",
                    "running_total": "1150000.00",
                }
            ],
        }
    )


def report_pdf() -> bytes:
    """A report whose section is a list of records rather than a mapping.

    The record list is the branch that fills a header row dark. The key and
    value branch below it draws no dark fill at all, so a mapping here would
    render a document with nothing for this to look at and report it clean.
    """
    from app.modules.reporting.exporters import _export_pdf

    return _export_pdf(
        title="Cost summary",
        project_name="Riverside Tower",
        report_type="boq_summary",
        currency="EUR",
        generated_at="2026-08-23T09:15:00+00:00",
        template_data={},
        data_snapshot={"summary": [{"trade": "Concrete", "amount": "1000.00"}]},
        # Pinned rather than parametrised: the contrast of a fill against the
        # text drawn on it is a property of the palette, and the palette does
        # not vary by language. A second locale here would render the same
        # colours and assert the same thing twice.
        locale="en",
    )


def sales_contract_pdf() -> bytes:
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    def stub(**fields: Any) -> Any:
        holder = SimpleNamespace()
        holder.__dict__.update(fields)
        return holder

    contract = stub(
        id=uuid.uuid4(),
        contract_number="SPA-2026-001",
        signing_date="2026-06-01",
        currency="EUR",
        total_value=Decimal("450000"),
        status="draft",
        total_price_breakdown={"base": "450000", "vat": "0"},
        metadata_={},
    )
    instalments = [
        stub(
            sequence=1,
            milestone_label="Reservation",
            milestone_event="reservation",
            due_date="2026-06-01",
            amount=Decimal("10000"),
        )
    ]
    parties = [
        stub(
            buyer_id=uuid.uuid4(),
            party_role="primary",
            ownership_pct=Decimal("100"),
            full_name="Buyer One",
            email="one@example.com",
        )
    ]
    plot = stub(plot_number="A-01", area_m2=Decimal("120"), currency="EUR", metadata_={})
    development = stub(name="Marina Heights", code="MAR01", metadata_={"regulator": "NONE"})
    return render_sales_contract_pdf(
        contract, stub(currency="EUR"), instalments, parties, plot, development, locale="en"
    )


def regulator_report_pdf() -> bytes:
    """The skeleton every regulator generator funnels through.

    Its heading cells became Paragraphs when the report was taught to wrap, so
    the colour that keeps them legible now lives in a ParagraphStyle where a
    TableStyle command can no longer reach it.
    """
    from app.modules.property_dev.regulatory import _render_pdf

    return _render_pdf(
        title="RERA Quarterly Project Disclosure",
        subtitle="Marina Heights (MH-001) - 2026-Q2",
        sections=[("Escrow activity (Article 11)", [("ESCROW-8871-004", "Bank Emirates NBD | Balance 1200.00 AED")])],
        signature_line="Developer authorised signatory",
        qr_payload="RERA|MH-001|2026-Q2",
    )


DOCUMENTS = {
    "bill of quantities": boq_pdf,
    "bill of quantities, large": large_boq_pdf,
    "methodology": methodology_pdf,
    "report": report_pdf,
    "regulator report": regulator_report_pdf,
    "sales contract": sales_contract_pdf,
}


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_no_document_draws_dark_text_on_a_dark_fill(name: str) -> None:
    complaints = unreadable_runs(DOCUMENTS[name]())
    assert not complaints, f"the {name} draws text too dark to read on its own dark fill:\n  " + "\n  ".join(complaints)


def test_the_instrument_reports_a_heading_drawn_in_its_own_background_colour() -> None:
    """The control, on a table built to carry the defect.

    Without this the suite above could pass by measuring nothing: a document
    that renders no dark fill at all, or an instrument that never finds the
    rectangle under a run, both report clean. This asserts the same reader
    fires on a page known to be wrong, and goes quiet once the colour is the
    one the table asked for.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    def build(text_colour: Any) -> bytes:
        buffer = io.BytesIO()
        style = ParagraphStyle("probe", fontName="Helvetica", fontSize=9, textColor=text_colour)
        table = Table([[Paragraph("Heading", style)], ["body"]], colWidths=[200])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                    # The command the defect is made of: it cannot reach the
                    # Paragraph above, and it is left here so the control is
                    # built the same way the real tables were.
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ]
            )
        )
        SimpleDocTemplate(buffer, pagesize=A4).build([table])
        return buffer.getvalue()

    invisible = unreadable_runs(build(colors.HexColor("#1a1a2e")))
    assert len(invisible) == 1, f"expected exactly the heading, got {invisible}"
    assert "'Heading'" in invisible[0] and "contrast 1.00" in invisible[0], invisible[0]

    assert not unreadable_runs(build(colors.white)), "still complaining once the heading is white"


def test_light_text_on_a_light_fill_is_not_this_test_s_business() -> None:
    """The other half of the control: the reader is not a general contrast gate.

    Text on a pale background is out of scope by design. Reporting it here
    would bury the defect that matters under every muted caption in the
    codebase, and the fix for a pale caption is not the fix for a heading that
    cannot be seen at all.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    buffer = io.BytesIO()
    style = ParagraphStyle("pale", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#f0f0f0"))
    table = Table([[Paragraph("Barely there", style)]], colWidths=[200])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff"))]))
    SimpleDocTemplate(buffer, pagesize=A4).build([table])

    assert not unreadable_runs(buffer.getvalue())
