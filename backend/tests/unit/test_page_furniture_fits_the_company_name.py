# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The company name in a header band or a footer is drawn in a face that can
draw it, and fits the room it is given.

The name printed there is the firm's own. It reaches these lines through the
company profile, whose legal name may be 120 characters long and in any script,
while the bands were written for a workspace name of 60 Latin ones. Two
failures followed and both are asserted here on the rendered page:

  * The shared footer and the header band picked their face by name rather than
    by text, so a Chinese or Korean legal name came out as a row of empty
    boxes. The instrument is the glyph id: a character drawn as glyph zero is
    the box, and the page's text objects report it, which the extracted text
    does not - the string comes back intact from a document that prints nothing
    but boxes.
  * A long name ran into the page number and off the right edge of the sheet.

The population is every document that prints a running footer, plus the
settings samples, and it is asserted in both directions: a document listed as
having no page number, or no name in its footer, is checked for the absence, so
a renderer that grows one silently is a failure rather than a quiet exemption.

:mod:`tests.unit.test_generated_documents_render_chinese` asks the same
question of the document's body, which reaches the page as a paragraph. This
file is about the furniture, which does not.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.core import app_branding, company_profile, pdf_appearance
from app.core.pdf_branding import render_sample_pdf
from app.core.pdf_fonts import (
    BODY_FONT,
    CJK_FONT,
    KOREAN_FONT,
    MIN_FURNITURE_SIZE,
    pdf_fit_line,
    register_cjk_font,
    register_pdf_fonts,
)
from app.modules.finance.br_invoice_pdf import render_br_invoice_pdf
from app.modules.meetings import router as meetings_router
from app.modules.methodology.pdf_export import generate_methodology_pdf
from tests._pdf_probe import text_runs
from tests.unit.test_outgoing_documents_print_the_company_letterhead import EXPORTERS
from tests.unit.test_pdf_document_type_overrides import _rfi

PAGE_NUMBER = re.compile(r"^\s*Page\s*\d")

#: The two scripts the CID packs cover, with the face each has to be drawn in.
SCRIPTS = {
    "chinese": ("中国建筑第八工程局有限公司", CJK_FONT),
    "korean": ("현대건설 주식회사", KOREAN_FONT),
}

#: A legal name at the full length the profile allows (MAX_LEGAL_NAME is 120).
#: The Latin one fits the band once it is set smaller; the Chinese one is twice
#: as wide per character and has to lose its tail, so the two exercise both
#: halves of the fit.
LATIN_120 = (
    "Northern Coastal Infrastructure Development and Civil Engineering Construction "
    "Partners Holding Group International Limited"
)[:120]
CHINESE_120 = ("中国建筑第八工程局有限公司" * 10)[:120]
FULL_LENGTH = {"latin": LATIN_120, "chinese": CHINESE_120}


def _br_invoice() -> bytes:
    """A Brazilian service invoice, the other generator that builds on the shared footer."""
    return render_br_invoice_pdf(
        invoice={
            "invoice_number": "RPS-2026-0042",
            "invoice_direction": "receivable",
            "invoice_date": "2026-05-27",
            "due_date": "2026-06-15",
            "amount_subtotal": "10000.00",
            "tax_amount": "500.00",
            "amount_total": "10500.00",
            "metadata": {"br_fields": {"codigo_servico": "7.02"}},
        },
        line_items=[
            {
                "description": f"Concreto estrutural fck 30 MPa, lote {index}",
                "unit": "m3",
                "quantity": "50.000000",
                "unit_rate": "200.000000",
                "amount": "10000.00",
            }
            for index in range(40)
        ],
        project={"name": "Obra Vila Madalena", "code": "VM-2026"},
    )


def _methodology() -> bytes:
    """A markup methodology sheet, which draws its own footer rather than the shared one."""
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
            "steps": [],
        }
    )


#: Every generator that prints page furniture carrying the company name, long
#: enough to run past its first page, plus the four settings samples. It holds
#: both callers of the shared footer (the project report and the Brazilian
#: invoice) and every generator that draws a footer of its own.
DOCUMENTS: dict[str, Callable[[], bytes]] = {
    **{name: (lambda make=make: make(long=True)) for name, make in EXPORTERS.items()},
    "br_invoice": _br_invoice,
    "methodology": _methodology,
    "rfi": _rfi,
    "sample": render_sample_pdf,
    "sample_rfi": lambda: render_sample_pdf("rfi"),
    "sample_minutes": lambda: render_sample_pdf("meeting_minutes"),
    "sample_diary": lambda: render_sample_pdf("daily_report"),
}

#: These print the letterhead on page one and nothing at the foot of the pages
#: after it: the dashboard report and the quarterly disclosure lay out their own
#: sheets, the regulator disclosure is a form. They are kept in the population
#: because the letterhead has to carry a Chinese name too.
NO_RUNNING_FOOTER = {"dashboard_report", "quarterly_disclosure", "regulator_disclosure"}

#: Of the rest, these print a page number and no name: the minutes are
#: circulated to the people who were in the room, so their footer stays empty
#: unless the workspace saves a line for it, and their sample follows them.
NO_NAME_IN_FOOTER = NO_RUNNING_FOOTER | {"meeting_minutes", "meeting_export", "sample_minutes"}


class Span(NamedTuple):
    """One run of text as it was drawn, with the face and the glyph ids it used."""

    page: int
    font: str
    size: float
    text: str
    boxes: int
    x0: float
    x1: float
    top_gap: float
    bottom_gap: float
    page_width: float


def _spans(pdf: bytes) -> list[Span]:
    """Every run of text in the document, in drawing order.

    ``boxes`` counts the characters that reached the page as glyph zero, which
    is what a face without the script draws and the only way to tell a rendered
    name from a boxed one.
    """
    return [
        Span(
            page=run.page,
            font=run.font,
            size=run.size,
            text=run.text,
            boxes=run.boxes,
            x0=run.x0,
            x1=run.x1,
            top_gap=run.top,
            bottom_gap=run.bottom_gap,
            page_width=run.page_width,
        )
        for run in text_runs(pdf)
    ]


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data dir, so a profile on the machine running the tests never reaches a document."""
    for module in (app_branding, company_profile, pdf_appearance):
        monkeypatch.setattr(module, "resolve_data_dir", lambda: tmp_path)
    monkeypatch.setenv("BI_REPORTS_DIR", str(tmp_path / "bi_reports"))

    async def _allowed(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(meetings_router, "verify_project_access", _allowed)
    return tmp_path


def _profile(data_dir: Path, legal_name: str) -> None:
    """A profile with a legal name and no logo, so the header band draws the name as text."""
    company_profile.write_company_profile(
        {"legal_name": legal_name, "address": "Hauptstrasse 12\n10115 Berlin"},
        data_dir,
    )


# ── The face ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("document", sorted(DOCUMENTS))
@pytest.mark.parametrize("script", sorted(SCRIPTS))
def test_a_chinese_or_korean_company_name_is_drawn_in_a_face_that_has_its_glyphs(
    document: str, script: str, data_dir: Path
) -> None:
    """No character of the name reaches the page as a box, in any band of any page."""
    name, expected = SCRIPTS[script]
    # The Korean name has a space in it, and a marker containing one would match
    # every Latin span on the page.
    marker = name.split(" ")[0]
    _profile(data_dir, name)

    spans = _spans(DOCUMENTS[document]())
    carrying = [span for span in spans if marker in span.text]
    assert carrying, (
        f"{document}: none of the {len(spans)} runs of text on its pages carry the company name, "
        "so this case says nothing about the face it would be drawn in"
    )
    faces = sorted({span.font for span in carrying})
    assert faces == [expected], (
        f"{document}: {len(carrying)} runs carry the {script} company name, drawn in {faces} rather than in {expected}"
    )
    boxed = [span for span in spans if span.boxes]
    assert not boxed, (
        f"{document}: {sum(span.boxes for span in boxed)} characters were drawn as empty boxes, "
        f"first in {boxed[0].font} on page {boxed[0].page}: {boxed[0].text[:40]!r}"
    )


# ── The room ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("document", sorted(DOCUMENTS))
@pytest.mark.parametrize("script", sorted(FULL_LENGTH))
def test_a_company_name_at_its_full_length_stays_clear_of_the_page_number(
    document: str, script: str, data_dir: Path
) -> None:
    """A 120-character legal name keeps off the page number and off the edges of the sheet."""
    name = FULL_LENGTH[script]
    # A prefix: the fit cuts the tail of a name it cannot set small enough.
    marker = name[:8]
    _profile(data_dir, name)

    spans = _spans(DOCUMENTS[document]())
    footer = [span for span in spans if span.bottom_gap < 60]
    numbers = [span for span in footer if PAGE_NUMBER.match(span.text)]
    named = [span for span in footer if marker in span.text]
    pages = max((span.page for span in spans), default=0)

    if document in NO_RUNNING_FOOTER:
        assert not numbers, f"{document} is listed as printing no running footer, yet it printed {len(numbers)}"
    else:
        assert numbers, f"{document}: no page number in the foot of any of its {pages} pages"
    if document in NO_NAME_IN_FOOTER:
        assert not named, f"{document} is listed as printing no company name in its footer, yet it printed one"
        return
    assert named, f"{document}: the company name is in none of the {len(footer)} runs at the foot of {pages} pages"

    for line in named:
        assert line.x1 <= line.page_width - 1.0, (
            f"{document} p{line.page}: the name runs to {line.x1:.1f} on a sheet {line.page_width:.1f} wide"
        )
        assert line.bottom_gap >= 4.0, (
            f"{document} p{line.page}: the name sits {line.bottom_gap:.1f}pt from the bottom edge of the sheet"
        )
        beside = [
            number for number in numbers if number.page == line.page and abs(number.bottom_gap - line.bottom_gap) < 3.0
        ]
        for number in beside:
            assert line.x1 <= number.x0 - 1.0, (
                f"{document} p{line.page}: the name ends at {line.x1:.1f} and {number.text.strip()!r} "
                f"starts at {number.x0:.1f}, so they overprint"
            )


def test_the_minutes_sample_prints_the_footer_the_minutes_print(data_dir: Path) -> None:
    """The settings sample is a promise about the document, in both directions.

    The minutes carry no footer line of their own, so the sample must not
    promise the brand and the date that every other type prints there; and when
    a line is saved for the type, both have to show it.
    """
    _profile(data_dir, "Bau GmbH Mueller")
    saved = "Bau GmbH Mueller - confidential"

    def foot(pdf: bytes) -> str:
        return " ".join(span.text for span in _spans(pdf) if span.bottom_gap < 60)

    sample, minutes = foot(render_sample_pdf("meeting_minutes")), foot(EXPORTERS["meeting_minutes"]())
    assert "Page 1" in sample and "Page 1" in minutes, f"sample {sample!r}, minutes {minutes!r}"
    assert "Generated" not in minutes, f"the minutes grew a generated line: {minutes!r}"
    assert "Generated" not in sample, f"the sample promises a line the minutes do not print: {sample!r}"

    pdf_appearance.write_override("meeting_minutes", {"footer_text": saved}, data_dir)
    sample, minutes = foot(render_sample_pdf("meeting_minutes")), foot(EXPORTERS["meeting_minutes"]())
    assert saved in minutes, f"the saved footer line did not reach the minutes: {minutes!r}"
    assert saved in sample, f"the saved footer line did not reach the sample: {sample!r}"


# ── The fit itself ────────────────────────────────────────────────────────


def test_a_line_that_already_fits_is_handed_back_unchanged() -> None:
    """The guarantee every unchanged document rests on: same text, same face, same size."""
    register_pdf_fonts()
    suffix = "  |  Generated: 2026-09-22"
    assert pdf_fit_line("Short GmbH", 400.0, suffix=suffix, base=BODY_FONT) == (
        f"Short GmbH{suffix}",
        BODY_FONT,
        7.0,
    )


def test_a_line_too_wide_is_set_smaller_down_to_the_legible_floor() -> None:
    """Shrinking comes before cutting, and stops where a footer stops being readable."""
    register_pdf_fonts()
    width = stringWidth(LATIN_120, BODY_FONT, 7.0) * 0.9
    line, face, size = pdf_fit_line(LATIN_120, width, base=BODY_FONT)
    assert line == LATIN_120, "a name that fits once it is set smaller keeps every character"
    assert MIN_FURNITURE_SIZE <= size < 7.0, f"set at {size}"
    assert stringWidth(line, face, size) <= width


def test_a_line_too_wide_even_at_the_floor_loses_its_tail_and_keeps_its_suffix() -> None:
    """The date is worth more than the last words of the name, so the name gives."""
    register_pdf_fonts()
    suffix = "  |  Generated: 2026-09-22"
    width = stringWidth(f"{LATIN_120}{suffix}", BODY_FONT, MIN_FURNITURE_SIZE) / 3
    line, face, size = pdf_fit_line(LATIN_120, width, suffix=suffix, base=BODY_FONT)
    assert size == MIN_FURNITURE_SIZE
    assert line.endswith(suffix), f"the suffix was cut into: {line!r}"
    assert "…" in line, f"the cut is not marked: {line!r}"
    assert line.startswith(LATIN_120[:10]), f"the name lost its head rather than its tail: {line!r}"
    assert stringWidth(line, face, size) <= width


def test_a_chinese_name_is_measured_in_the_face_it_will_be_drawn_in() -> None:
    """The width of the line the reader sees, not of the boxes a Latin face would draw."""
    register_pdf_fonts()
    assert register_cjk_font(), "the Chinese CID pack is not available in this environment"
    name = CHINESE_120[:40]
    assert stringWidth(name, BODY_FONT, 7.0) < stringWidth(name, CJK_FONT, 7.0), (
        "the Latin face measures this name narrower than it will be drawn, which is what made measuring in it wrong"
    )
    width = stringWidth(name, CJK_FONT, 7.0) * 0.8
    line, face, size = pdf_fit_line(name, width, base=BODY_FONT)
    assert face == CJK_FONT
    assert stringWidth(line, face, size) <= width
