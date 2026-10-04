# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The BOQ estimate, the diary, the minutes, the dashboard report, the project
report, the regulator disclosures and the tender letters carry the letterhead.

These are the documents a firm sends out under its own name: an estimate to a
client, a daily report to the owner, minutes to everyone at the table, a
project report to a lender, a quarterly disclosure to a regulator, an award or
a rejection to a bidder. None
of them printed the company profile, and the tender letters printed the
platform's name as the brand at the head of the letter whatever the workspace
was called.

Every assertion is made on the rendered PDF. The address line is the marker
for the letterhead, not the legal name: the footer of several of these prints
the brand, and the brand falls back to the legal name. Images are counted as
draws (``Do`` operators), because a logo drawn twice from the same bytes is one
resource. Each "no letterhead" assertion is paired with the positive case in
the same setup, since a broken builder returns ``None`` and would pass it.

The settings are written into a throwaway data dir that the branding, the
appearance and the company profile are each pointed at, so a profile on the
machine running the tests never reaches them.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import io
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymupdf
import pypdf
import pytest
from PIL import Image

from app.core import app_branding, company_profile, pdf_appearance
from app.modules.bi_dashboards.report_builder import build_pdf_report
from app.modules.boq.pdf_export import generate_boq_pdf, generate_boq_pdf_simple
from app.modules.daily_diary.pdf_export import generate_diary_pdf
from app.modules.meetings import router as meetings_router
from app.modules.meetings.pdf import build_minutes_pdf
from app.modules.property_dev import document_templates
from app.modules.property_dev.document_templates import render_reservation_receipt_pdf
from app.modules.property_dev.regulatory import _render_pdf as render_regulator_disclosure
from app.modules.property_dev.service import _render_regulator_pdf
from app.modules.reporting.exporters import _export_pdf as export_report_pdf
from app.modules.tendering.pdf_documents import (
    generate_award_letter_pdf,
    generate_award_record_pdf,
    generate_rejection_letter_pdf,
)

LEGAL_NAME = "Müller Bau GmbH"
#: Printed by the letterhead and by nothing else in these documents.
LETTERHEAD_ONLY = "10115 Berlin"
PLATFORM = "OpenConstructionERP"


def _png_data_url() -> str:
    """A wordmark-shaped PNG, large enough to be drawn at a visible size."""
    buf = io.BytesIO()
    Image.new("RGB", (120, 40), "#0b5394").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data dir: no company profile, no app branding, no appearance."""
    for module in (app_branding, company_profile, pdf_appearance):
        monkeypatch.setattr(module, "resolve_data_dir", lambda: tmp_path)
    monkeypatch.setenv("BI_REPORTS_DIR", str(tmp_path / "bi_reports"))

    async def _allowed(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(meetings_router, "verify_project_access", _allowed)
    return tmp_path


def _write_profile(data_dir: Path) -> None:
    company_profile.write_company_profile(
        {
            "legal_name": LEGAL_NAME,
            "address": "Hauptstraße 12\n10115 Berlin\nGermany",
            "registration_line": "HRB 123456 B, VAT DE123456789",
            "phone": "+49 30 1234567",
            "email": "info@mueller-bau.example",
            "document_logo_data_url": _png_data_url(),
        },
        data_dir,
    )


# ── Documents ─────────────────────────────────────────────────────────────


def _diary(long: bool = False) -> bytes:
    diary = SimpleNamespace(
        diary_date="2026-09-21",
        status="approved",
        labour_count=14,
        equipment_count=3,
        weather_summary={"temp_c": 18, "conditions": "clear"},
        notes="Crane operated without restriction.",
    )
    entries = [
        SimpleNamespace(
            entry_type="work",
            entry_time=datetime(2026, 9, 21, 7, 30, tzinfo=UTC),
            title=f"Level {index} slab poured",
            description="C30/37, 55 m3, pump from grid A to D.",
        )
        for index in range(60 if long else 2)
    ]
    return generate_diary_pdf(diary, project_name="Harbour Tower", entries=entries, supervisor_name="Maria Keller")


def _action_items(long: bool) -> list[dict[str, Any]]:
    return [
        {"description": f"Issue revised facade drawings, sheet {index}", "owner": "Tom Ortega", "status": "open"}
        for index in range(60 if long else 2)
    ]


def _minutes(long: bool = False) -> bytes:
    content = {
        "title": "Site coordination meeting 14",
        "meeting_date": "2026-09-18",
        "location": "Site office",
        "meeting_type": "site_meeting",
        "meeting_number": "014",
        "attendees_present": [{"name": "Maria Keller"}],
        "action_items": _action_items(long),
        "summary": "Programme on track.",
    }
    meeting = SimpleNamespace(title=content["title"], meeting_number="014", meeting_date="2026-09-18")
    minutes = SimpleNamespace(content=content, status="issued", issued_at=datetime(2026, 9, 19, 9, tzinfo=UTC))
    return build_minutes_pdf(meeting, minutes, "Harbour Tower")


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    """Answers the two reads the export makes: the meeting, then the project name."""

    def __init__(self, *answers: Any) -> None:
        self._answers = list(answers)

    async def execute(self, _statement: Any) -> _Result:
        return _Result(self._answers.pop(0))


def _meeting_export(long: bool = False) -> bytes:
    meeting = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="Site coordination meeting 14",
        meeting_date="2026-09-18",
        location="Site office",
        meeting_type="site_meeting",
        meeting_number="014",
        status="completed",
        attendees=[{"name": "Maria Keller", "company": "Harbour Estates", "status": "present"}],
        agenda_items=[{"topic": "Programme"}],
        action_items=_action_items(long),
    )

    async def _export() -> bytes:
        response = await meetings_router.export_meeting_pdf(
            meeting.id, session=_Session(meeting, "Harbour Tower"), _user=uuid.uuid4()
        )
        return b"".join([chunk async for chunk in response.body_iterator])

    return asyncio.run(_export())


def _dashboard_report(long: bool = False) -> bytes:
    rows = [
        {"project": f"Project {index}", "bac": "12500000.00", "ac": "6120000.00", "cpi": "1.05"}
        for index in range(120 if long else 2)
    ]
    path, _size = build_pdf_report(report_name="Portfolio cost performance", rows=rows)
    return Path(path).read_bytes()


def _regulator_disclosure(long: bool = False) -> bytes:
    sections = [
        (f"Section {index}", [(f"Field {row}", "Value of the field") for row in range(8)])
        for index in range(12 if long else 2)
    ]
    return render_regulator_disclosure(
        title="RERA quarterly developer disclosure",
        subtitle="Marina Heights - 2026-Q3",
        sections=sections,
        signature_line="Authorised signatory",
        qr_payload="RERA-2026Q3-MH-0001",
    )


def _quarterly_disclosure(long: bool = False) -> bytes:
    summary = {f"metric_{index}": "value" for index in range(90 if long else 3)}
    return _render_regulator_pdf(
        regulator="RERA",
        development_name="Marina Heights",
        development_code="MH-001",
        quarter="2026-Q3",
        summary=summary,
    )


def _award_letter(long: bool = False) -> bytes:
    return generate_award_letter_pdf(
        package_name="Roofing works",
        package_ref="PKG-2026-0001",
        project_name="Riverside Gardens",
        company_name="Kreuzer Roofing GmbH",
        contact_email="tender@example.com",
        awarded_amount="1245000.00",
        currency="EUR",
        awarded_at="2026-06-01T09:00:00+00:00",
    )


def _rejection_letter(long: bool = False) -> bytes:
    return generate_rejection_letter_pdf(
        package_name="Roofing works",
        package_ref="PKG-2026-0001",
        project_name="Riverside Gardens",
        company_name="Second Place Bau",
        contact_email="tender@example.com",
    )


def _award_record(long: bool = False) -> bytes:
    gaps = [{"section": "subject"} for _ in range(90 if long else 1)]
    return generate_award_record_pdf(
        record={"package_name": "Roofing works", "project_name": "Riverside Gardens", "gaps": gaps, "sections": []},
        package_ref="PKG-2026-0001",
    )


def _bill(long: bool) -> SimpleNamespace:
    """A priced bill shaped like ``BOQWithSections``."""
    positions = [
        SimpleNamespace(
            id=uuid.uuid4(),
            boq_id=uuid.uuid4(),
            ordinal=f"01.{index + 1:03d}",
            description="Reinforced concrete wall C30/37",
            unit="m3",
            quantity=Decimal("100"),
            unit_rate=Decimal("1000"),
            total=Decimal("100000.00"),
        )
        for index in range(60 if long else 1)
    ]
    direct = Decimal("100000.00") * len(positions)
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Tender BOQ",
        description="",
        status="draft",
        currency="EUR",
        sections=[
            SimpleNamespace(
                id=uuid.uuid4(), ordinal="01", description="Structure", positions=positions, subtotal=direct
            )
        ],
        positions=[],
        direct_cost=direct,
        markups=[],
        net_total=direct,
        grand_total=direct,
    )


def _boq_estimate(long: bool = False) -> bytes:
    return generate_boq_pdf(_bill(long), "Harbour Tower", currency="EUR", prepared_by="Maria Keller")


def _boq_summary(long: bool = False) -> bytes:
    return generate_boq_pdf_simple(_bill(long), "Harbour Tower", currency="EUR", prepared_by="Maria Keller")


def _project_report(long: bool = False) -> bytes:
    return export_report_pdf(
        title="Cost summary",
        project_name="Harbour Tower",
        report_type="boq_summary",
        currency="EUR",
        generated_at="2026-09-21T09:15:00+00:00",
        template_data={},
        data_snapshot={
            "summary": [{"trade": f"Trade {index}", "amount": "1000.00"} for index in range(80 if long else 2)]
        },
        locale="en",
    )


EXPORTERS: dict[str, Callable[..., bytes]] = {
    "boq_estimate": _boq_estimate,
    "boq_summary": _boq_summary,
    "daily_diary": _diary,
    "meeting_minutes": _minutes,
    "meeting_export": _meeting_export,
    "dashboard_report": _dashboard_report,
    "project_report": _project_report,
    "regulator_disclosure": _regulator_disclosure,
    "quarterly_disclosure": _quarterly_disclosure,
    "award_letter": _award_letter,
    "rejection_letter": _rejection_letter,
    "award_record": _award_record,
}

#: The ones that draw the small header logo on the pages after the first. The
#: dashboard report does not: its 1 cm top margin leaves no band for it.
WITH_HEADER_LOGO = [
    "boq_estimate",
    "boq_summary",
    "daily_diary",
    "meeting_minutes",
    "meeting_export",
    "project_report",
    "regulator_disclosure",
    "award_record",
]

TENDER_LETTERS = ["award_letter", "rejection_letter", "award_record"]


# ── Reading the page ──────────────────────────────────────────────────────


def _pages(pdf: bytes) -> list[pypdf.PageObject]:
    return list(pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _text(page: pypdf.PageObject) -> str:
    return page.extract_text() or ""


def _images_on(page: pypdf.PageObject) -> int:
    """How many times the page draws an image, counted as ``Do`` operators."""
    xobjects = page["/Resources"].get("/XObject") or {}
    images = {name for name, ref in xobjects.items() if ref.get_object().get("/Subtype") == "/Image"}
    contents = page.get_contents()
    if contents is None:
        return 0
    return sum(1 for operands, operator in contents.operations if operator == b"Do" and operands[0] in images)


# ── With and without a profile ────────────────────────────────────────────


@pytest.mark.parametrize("name", list(EXPORTERS))
def test_page_one_carries_the_letterhead_and_prints_the_logo_once(name: str, data_dir: Path) -> None:
    """The letterhead reaches page one, its logo is drawn exactly once, and the
    document is no longer than it was without it."""
    without = _pages(EXPORTERS[name]())
    assert LETTERHEAD_ONLY not in _text(without[0])

    _write_profile(data_dir)
    pages = _pages(EXPORTERS[name]())
    first = _text(pages[0])
    assert LEGAL_NAME in first, f"{name}: the legal name is not on page one"
    assert LETTERHEAD_ONLY in first, f"{name}: the letterhead's address is not on page one"
    assert _images_on(pages[0]) == 1, f"{name}: page one draws {_images_on(pages[0])} images, expected the one logo"
    assert len(pages) == len(without), f"{name}: the letterhead pushed the document from {len(without)} pages"


@pytest.mark.parametrize("name", list(EXPORTERS))
def test_without_a_profile_the_page_is_what_it_was(name: str, data_dir: Path) -> None:
    """No profile, no branding: no letterhead, no name, no image, still a PDF."""
    pages = _pages(EXPORTERS[name]())
    assert pages, f"{name}: no pages"
    assert LETTERHEAD_ONLY not in _text(pages[0])
    assert LEGAL_NAME not in _text(pages[0])
    assert _images_on(pages[0]) == 0, f"{name}: an image appeared with no logo configured"


@pytest.mark.parametrize("name", list(EXPORTERS))
def test_turning_the_letterhead_off_suppresses_it(name: str, data_dir: Path) -> None:
    _write_profile(data_dir)
    assert LETTERHEAD_ONLY in _text(_pages(EXPORTERS[name]())[0])

    pdf_appearance.write_appearance({"show_letterhead": False}, data_dir)
    assert LETTERHEAD_ONLY not in _text(_pages(EXPORTERS[name]())[0])


@pytest.mark.parametrize("name", WITH_HEADER_LOGO)
def test_later_pages_carry_the_header_logo_and_not_the_letterhead(name: str, data_dir: Path) -> None:
    _write_profile(data_dir)
    pages = _pages(EXPORTERS[name](long=True))
    assert len(pages) > 1, f"{name}: expected a second page to look at"
    for number, page in enumerate(pages[1:], start=2):
        assert _images_on(page) == 1, f"{name}: page {number} has no header logo"
        assert LETTERHEAD_ONLY not in _text(page), f"{name}: page {number} repeated the letterhead"


def test_the_dashboard_report_keeps_its_later_pages_clear(data_dir: Path) -> None:
    """The other side of the list above. A logo in a 1 cm margin would sit on
    the repeated table header, so the report prints the letterhead once."""
    _write_profile(data_dir)
    pages = _pages(_dashboard_report(long=True))
    assert len(pages) > 1
    assert _images_on(pages[0]) == 1
    assert all(_images_on(page) == 0 for page in pages[1:])


@pytest.mark.parametrize("name", list(EXPORTERS))
def test_document_properties_follow_the_workspace_brand(name: str, data_dir: Path) -> None:
    app_branding.write_branding({"mode": "text", "company_name": LEGAL_NAME}, data_dir)
    metadata = pypdf.PdfReader(io.BytesIO(EXPORTERS[name]())).metadata
    assert metadata is not None
    assert metadata.author == LEGAL_NAME, f"{name}: author is {metadata.author!r}"
    assert metadata.creator == LEGAL_NAME, f"{name}: creator is {metadata.creator!r}"


# ── The tender letters ────────────────────────────────────────────────────


@pytest.mark.parametrize("name", TENDER_LETTERS)
def test_a_tender_letter_no_longer_goes_out_under_the_platform_name(name: str, data_dir: Path) -> None:
    """The letters printed the platform's name as the brand at their head and in
    their footer. An unbranded workspace still does; a firm never does."""
    assert PLATFORM in _text(_pages(EXPORTERS[name]())[0])

    app_branding.write_branding({"mode": "text", "company_name": LEGAL_NAME}, data_dir)
    named = "\n".join(_text(page) for page in _pages(EXPORTERS[name]()))
    assert LEGAL_NAME in named
    assert PLATFORM not in named, f"{name}: the platform name is still printed on a named workspace's letter"

    _write_profile(data_dir)
    lettered = "\n".join(_text(page) for page in _pages(EXPORTERS[name]()))
    assert LETTERHEAD_ONLY in lettered
    assert PLATFORM not in lettered


def test_an_unbranded_tender_letter_keeps_its_document_properties(data_dir: Path) -> None:
    metadata = pypdf.PdfReader(io.BytesIO(_award_letter())).metadata
    assert metadata is not None
    assert metadata.author == PLATFORM
    assert metadata.subject == "Tender decision · DDC-CWICR-OE"


def _horizontal_rules(pdf: bytes, page: int = 0) -> dict[tuple[float, float, float], tuple[float, float]]:
    """``colour -> (x0, x1)`` of every horizontal line on a page, page one by default."""
    rules: dict[tuple[float, float, float], tuple[float, float]] = {}
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for drawing in doc[page].get_drawings():
            for item in drawing["items"]:
                if item[0] == "l" and abs(item[1].y - item[2].y) < 0.1 and drawing.get("color"):
                    colour = tuple(round(channel, 2) for channel in drawing["color"])
                    rules[colour] = (round(min(item[1].x, item[2].x), 1), round(max(item[1].x, item[2].x), 1))
    return rules


def test_the_tender_letterhead_lines_up_with_the_rule_under_the_reference(data_dir: Path) -> None:
    """The letter's tables span the margins, 6pt past the frame's padding. At the
    frame width the letterhead's rule stopped short of the one under it."""
    _write_profile(data_dir)
    rules = _horizontal_rules(_award_letter())
    letterhead_rule = rules[(0.8, 0.8, 0.8)]  # #cccccc
    reference_rule = rules[(0.1, 0.1, 0.18)]  # #1a1a2e
    assert letterhead_rule == reference_rule


# ── The quarterly disclosure's credit line ────────────────────────────────


def test_the_quarterly_disclosure_credits_the_developer_that_files_it(data_dir: Path) -> None:
    unbranded = "\n".join(_text(page) for page in _pages(_quarterly_disclosure()))
    assert "generated by OpenConstructionERP (DataDrivenConstruction)" in " ".join(unbranded.split())

    _write_profile(data_dir)
    branded = " ".join("\n".join(_text(page) for page in _pages(_quarterly_disclosure())).split())
    assert f"generated by {LEGAL_NAME}" in branded
    assert PLATFORM not in branded


# ── The diary footer ──────────────────────────────────────────────────────


def test_the_diary_page_number_sits_at_the_right_margin(data_dir: Path) -> None:
    """A Paragraph wraps to the width it is offered, so offsetting by that width
    drew the page number at the left margin, over the supervisor line."""
    with pymupdf.open(stream=_diary(), filetype="pdf") as doc:
        page = doc[0]
        words = page.get_text("words")
        page_word = next(word for word in words if word[4] == "Page")
        supervisor = next(word for word in words if word[4].startswith("Supervisor"))
        assert page_word[0] > page.rect.width / 2, f"the page number starts at {page_word[0]:.0f}pt"
        assert page_word[0] > supervisor[2], "the page number overlaps the supervisor line"


# ── The project report footer ─────────────────────────────────────────────


def _footer_band(pdf: bytes) -> list[str]:
    """The text of each page's bottom 14 mm, where the footer line is drawn."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return [
            page.get_text("text", clip=pymupdf.Rect(0, page.rect.height - 40, page.rect.width, page.rect.height))
            for page in doc
        ]


def test_the_project_report_footer_names_the_firm_on_every_page(data_dir: Path) -> None:
    """Page one trades the header band for the letterhead but keeps its footer,
    and the footer's brand falls back to the legal name, so a firm that filled
    in only its profile never sends a report footed with the platform's name."""
    assert all(PLATFORM in footer for footer in _footer_band(_project_report(long=True)))

    _write_profile(data_dir)
    footers = _footer_band(_project_report(long=True))
    assert len(footers) > 1, "expected a second page to look at"
    for number, footer in enumerate(footers, start=1):
        assert LEGAL_NAME in footer, f"page {number}: the footer does not name the firm: {footer!r}"
        assert PLATFORM not in footer, f"page {number}: the footer names the platform"


def test_the_project_report_letterhead_spans_what_the_header_band_spans(data_dir: Path) -> None:
    """Page two's header band rules the full width between the margins. At the
    frame width the letterhead's rule on page one stopped 6pt short at each end."""
    _write_profile(data_dir)
    pdf = _project_report(long=True)
    grey = (0.8, 0.8, 0.8)  # #cccccc, the letterhead rule and the header band rule alike
    assert _horizontal_rules(pdf, page=0)[grey] == _horizontal_rules(pdf, page=1)[grey]


# ── The BOQ cover ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["boq_estimate", "boq_summary"])
def test_the_boq_cover_names_the_firm_once(name: str, data_dir: Path) -> None:
    """The cover printed the brand in large type at its head. Under a letterhead
    that brand is the legal name again, so the letterhead takes its place."""
    _write_profile(data_dir)
    cover = _text(_pages(EXPORTERS[name]())[0])
    assert LETTERHEAD_ONLY in cover
    assert cover.count(LEGAL_NAME) == 1, f"{name}: the cover names the firm {cover.count(LEGAL_NAME)} times"


def _ink_centre(page: pymupdf.Page, first_word: str) -> float:
    """The x-centre of the printed glyphs on the line that starts with ``first_word``.

    Spaces, non-breaking ones included, are left out: a run of them is what
    pushed these lines off the axis, and a measure that counted them would
    call the old layout centred.
    """
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            chars = [char for span in line["spans"] for char in span["chars"]]
            if "".join(char["c"] for char in chars).strip().startswith(first_word):
                ink = [char["bbox"] for char in chars if not char["c"].isspace()]
                return (min(box[0] for box in ink) + max(box[2] for box in ink)) / 2
    raise AssertionError(f"no line on the cover starts with {first_word!r}")


@pytest.mark.parametrize("letterhead", [False, True], ids=["plain", "letterhead"])
@pytest.mark.parametrize("name", ["boq_estimate", "boq_summary"])
def test_the_boq_cover_centres_its_summary_heading_and_signature(name: str, letterhead: bool, data_dir: Path) -> None:
    """The summary heading and the prepared-by line were pushed right with runs of
    non-breaking spaces off the axis of the centred title and table, the heading
    by some 70pt. Their styles centre them now, with or without a letterhead.

    The prepared-by line has an approved-by beside it now, a column each over
    a line to sign on, so it is the pair that sits on the axis: the two columns
    are mirror images of each other about the middle of the page."""
    if letterhead:
        _write_profile(data_dir)
    with pymupdf.open(stream=EXPORTERS[name](), filetype="pdf") as doc:
        page = doc[0]
        axis = page.rect.width / 2
        centre = _ink_centre(page, "SUMMARY")
        assert abs(centre - axis) < 1, f"{name}: 'SUMMARY' is centred at {centre:.1f}pt, the page at {axis:.1f}pt"
        prepared, approved = _ink_centre(page, "Prepared"), _ink_centre(page, "Approved")
        assert prepared < axis < approved, f"{name}: the sign-off columns are not either side of the axis"
        pair = (prepared + approved) / 2
        assert abs(pair - axis) < 1, f"{name}: the sign-off pair is centred at {pair:.1f}pt, the page at {axis:.1f}pt"


# ── Property documents with no development name ───────────────────────────


def _reservation_receipt() -> bytes:
    reservation = SimpleNamespace(
        id=uuid.uuid4(),
        reservation_number="RES-2026-001",
        deposit_amount=Decimal("5000"),
        currency="EUR",
        expires_at=None,
        cooling_off_until=None,
        cooling_off_days=0,
        created_at=None,
    )
    plot = SimpleNamespace(
        id=uuid.uuid4(), plot_number="A-42", area_m2=Decimal("80"), asking_price=Decimal("250000"), currency="EUR"
    )
    development = SimpleNamespace(id=uuid.uuid4(), name="", logo_url=None)
    buyer = SimpleNamespace(full_name="Alice Tester", email="alice@example.com")
    return render_reservation_receipt_pdf(reservation, plot, development, [buyer])


def test_a_property_document_with_no_development_name_is_headed_by_the_workspace(data_dir: Path) -> None:
    """The page header fell back to the platform's name for a development with
    no name. It now falls back through the shared brand chain, which still ends
    at the platform name for a workspace that has set nothing."""
    assert PLATFORM in _text(_pages(_reservation_receipt())[0])

    app_branding.write_branding({"mode": "text", "company_name": LEGAL_NAME}, data_dir)
    header = _text(_pages(_reservation_receipt())[0])
    assert LEGAL_NAME in header
    assert PLATFORM not in header


def test_a_property_document_with_no_development_name_is_authored_by_the_workspace(data_dir: Path) -> None:
    """The same fallback in the document properties: the author named the
    platform for a development with no name, whatever the workspace was called."""
    unbranded = pypdf.PdfReader(io.BytesIO(_reservation_receipt())).metadata
    assert unbranded is not None
    assert unbranded.author == PLATFORM

    app_branding.write_branding({"mode": "text", "company_name": LEGAL_NAME}, data_dir)
    branded = pypdf.PdfReader(io.BytesIO(_reservation_receipt())).metadata
    assert branded is not None
    assert branded.author == LEGAL_NAME


def test_every_property_document_takes_its_author_from_the_one_fallback() -> None:
    """The twelve property documents each spelled the platform's name as their
    author fallback. Rendering all twelve takes a stub world per document, so
    this reads the module instead: every document hands ``_build_doc`` an
    author from ``_document_author``, which the test above renders, and no
    string in the module spells the platform's name."""
    tree = ast.parse(Path(document_templates.__file__).read_text(encoding="utf-8"))
    authors = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_build_doc"
        for keyword in node.keywords
        if keyword.arg == "author"
    ]
    assert len(authors) >= 12, f"found {len(authors)} documents built with an author, the module has twelve"
    for value in authors:
        assert isinstance(value, ast.Call) and getattr(value.func, "id", None) == "_document_author", (
            f"line {value.lineno}: author= is {ast.unparse(value)}, not the shared fallback"
        )
    spelled = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and PLATFORM in node.value
    ]
    assert not spelled, f"the platform's name is spelled out on lines {spelled}"
