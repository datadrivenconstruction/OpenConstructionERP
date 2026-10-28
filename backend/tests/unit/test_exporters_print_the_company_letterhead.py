# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The pay application, closeout cover, punch list and transmittal carry the letterhead.

These four generators ignored workspace branding entirely: no logo, no company
name, and the transmittal stamped the platform name into its author field
whatever the workspace was called. A firm that has to send its formal
letterhead could not send any of them.

Every assertion is made on the rendered PDF, never on the code path: the legal
name has to come back out of the page text, and the logo has to be an image
XObject on the page it belongs to. The profile is written to a per-test data
dir before anything reads it, so the (mtime, size) cache in
:mod:`app.core.company_profile` never sees two versions of one path.

The legal name carries a non-Latin letter on purpose. The letterhead escapes
and faces each line itself, and a name that came out as a box or an entity
would still pass a test written with ASCII.
"""

from __future__ import annotations

import base64
import io
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pypdf
import pytest
from PIL import Image
from reportlab.platypus import Spacer

import app.modules.contracts.aia_pdf as aia_pdf
from app.core.paper_size import PAPER_SIZES
from app.modules.closeout.cover_pdf import render_cover_pdf
from app.modules.file_transmittals.models import (
    FileTransmittal,
    FileTransmittalItem,
    FileTransmittalRecipient,
)
from app.modules.file_transmittals.service import _build_cover_pdf
from app.modules.punchlist.service import _build_reportlab_pdf

LEGAL_NAME = "Bau GmbH Müller"


def _png_data_url() -> str:
    """A small wordmark-shaped PNG. Large enough to be drawn at a visible size,
    because the letterhead never scales a raster up past one pixel per point."""
    buf = io.BytesIO()
    Image.new("RGB", (120, 40), "#0b5394").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data dir: no company profile, no app branding, no appearance."""
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def profile(data_dir: Path) -> Path:
    """A filled company profile with a document logo, written before any read."""
    record = {
        "legal_name": LEGAL_NAME,
        "address": "Hauptstraße 12\n10115 Berlin\nGermany",
        "registration_line": "HRB 123456 B, VAT DE123456789",
        "phone": "+49 30 1234567",
        "email": "info@mueller-bau.example",
        "document_logo_data_url": _png_data_url(),
    }
    (data_dir / "company_profile.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return data_dir


# ── Documents ─────────────────────────────────────────────────────────────


def _aia(lines: int = 1) -> bytes:
    line = {
        "description": "Substructure and foundations",
        "scheduled_value": "1000.00",
        "previous_value": "0.00",
        "this_period_value": "1000.00",
        "materials_stored": "0.00",
        "total_completed_stored": "1000.00",
        "percent_complete": "100",
        "balance_to_finish": "0.00",
        "retainage": "0.00",
    }
    return aia_pdf.render_aia_application_pdf(
        {
            "application_number": "APP-014",
            "claim_date": "2026-04-15",
            "period_end": "2026-04-30",
            "currency": "USD",
            "certification": {
                "architect_certified_by": "Ortega Architects",
                "architect_certified_at": "2026-05-01",
                "owner_certified_by": "Harbour Estates",
                "owner_certified_at": "2026-05-02",
                "certified_amount": "1000.00",
            },
            "summary": {"contract_sum_to_date": "1000.00", "total_completed_stored": "1000.00"},
            "lines": [line | {"item_number": f"{index:02d}"} for index in range(1, lines + 1)],
        }
    )


def _closeout() -> bytes:
    return render_cover_pdf(
        {
            "project_name": "Harbour Tower",
            "project_type": "commercial",
            "title": "Digital handover package",
            "completeness_pct": 60,
            "required_slot_count": 5,
            "delivered_slot_count": 3,
            "ready": False,
            "gaps": ["Fire certificate"],
            "slots": [{"title": "O&M manuals", "status": "verified", "evidence": "doc-1", "verified_at": "2026-04-01"}],
            "built_at": "2026-04-15 09:00 UTC",
        }
    )


def _punch_list() -> bytes:
    item = SimpleNamespace(
        title="Cracked tile",
        status="open",
        priority="high",
        category="finishes",
        trade="tiling",
        assigned_to=None,
        due_date=None,
        description="Crack in sector B",
        metadata_={},
        document_id=None,
        location_x=None,
        location_y=None,
        page=None,
        photos=[],
        resolution_notes=None,
        reopen_history=[],
    )
    return _build_reportlab_pdf(uuid.uuid4(), [item], {})


def _transmittal() -> bytes:
    transmittal = FileTransmittal(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        number="TR-2026-0041",
        subject="Issue for construction",
        reason_code="for_construction",
        sent_at=datetime(2026, 3, 14, 9, 30, tzinfo=UTC),
        status="sent",
    )
    transmittal.items = [
        FileTransmittalItem(
            file_kind="drawing",
            file_id="file-1",
            file_version_snapshot="C",
            canonical_name_snapshot="A-101 Ground floor plan.pdf",
            sort_order=0,
        )
    ]
    transmittal.recipients = [
        FileTransmittalRecipient(email="site@example.com", display_name="Site", role="contractor")
    ]
    pdf = _build_cover_pdf(transmittal, PAPER_SIZES["A4"])
    assert pdf is not None, "the cover sheet fell back to text, so there is no page to read"
    return pdf


EXPORTERS: dict[str, Callable[[], bytes]] = {
    "aia_g702": _aia,
    "closeout_cover": _closeout,
    "punch_list": _punch_list,
    "transmittal_cover": _transmittal,
}


# ── Reading the page ──────────────────────────────────────────────────────


def _pages(pdf: bytes) -> list[pypdf.PageObject]:
    return list(pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _images_on(page: pypdf.PageObject) -> int:
    """How many times the page draws an image, counted as ``Do`` operators.

    Draws rather than the page's resource dictionary, because a resource is
    declared once however often it is drawn: a logo printed twice from the
    same bytes could list a single XObject and pass a count of declarations.
    """
    xobjects = page["/Resources"].get("/XObject") or {}
    images = {name for name, ref in xobjects.items() if ref.get_object().get("/Subtype") == "/Image"}
    contents = page.get_contents()
    if contents is None:
        return 0
    return sum(1 for operands, operator in contents.operations if operator == b"Do" and operands[0] in images)


# ── With a profile ────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(EXPORTERS))
def test_page_one_carries_the_letterhead_and_prints_the_logo_once(name: str, profile: Path) -> None:
    """The legal name reaches the page text, and the logo is on page one exactly
    once: the letterhead draws it, so the header copy must stand down."""
    first = _pages(EXPORTERS[name]())[0]
    assert LEGAL_NAME in first.extract_text(), f"{name}: the legal name is not on page one"
    assert _images_on(first) == 1, f"{name}: page one carries {_images_on(first)} images, expected the one logo"


@pytest.mark.parametrize("name", list(EXPORTERS))
def test_without_a_profile_the_document_still_builds_with_no_letterhead(name: str, data_dir: Path) -> None:
    """A workspace that never filled the profile in gets the document it got
    before: no name, no logo, and still a PDF."""
    pages = _pages(EXPORTERS[name]())
    assert pages, f"{name}: no pages"
    assert LEGAL_NAME not in pages[0].extract_text()
    assert _images_on(pages[0]) == 0, f"{name}: an image appeared with no logo configured"


def test_later_pages_carry_the_header_logo(profile: Path) -> None:
    """Only page one has the letterhead; every page after it still says whose
    document it is. The punch list always runs to a second page (cover, then
    items) and the pay application does with a real schedule of values."""
    for name, pdf in (("punch_list", _punch_list()), ("aia_g702", _aia(lines=20))):
        pages = _pages(pdf)
        assert len(pages) > 1, f"{name}: expected a second page to look at"
        for number, page in enumerate(pages[1:], start=2):
            assert _images_on(page) == 1, f"{name}: page {number} has no header logo"
            assert LEGAL_NAME not in page.extract_text(), f"{name}: page {number} repeated the letterhead"


@pytest.mark.parametrize("name", list(EXPORTERS))
def test_document_properties_follow_the_workspace_brand(name: str, data_dir: Path) -> None:
    """The file's properties name the workspace. The transmittal used to write
    the platform name into its author field whatever the workspace was called."""
    (data_dir / "app_branding.json").write_text(
        json.dumps({"mode": "text", "company_name": LEGAL_NAME}, ensure_ascii=False), encoding="utf-8"
    )
    metadata = pypdf.PdfReader(io.BytesIO(EXPORTERS[name]())).metadata
    assert metadata is not None
    assert metadata.author == LEGAL_NAME, f"{name}: author is {metadata.author!r}"
    assert metadata.creator == LEGAL_NAME, f"{name}: creator is {metadata.creator!r}"


# ── The pay application's fixed form ──────────────────────────────────────


def test_the_g702_face_stays_on_page_one_under_a_full_letterhead(profile: Path) -> None:
    """The face is the sheet that gets signed, so the letterhead is placed only
    when the certification still ends on page one. Asserted with a twenty line
    schedule of values, which is what pushes the continuation sheet over."""
    first = _pages(_aia(lines=20))[0].extract_text()
    assert LEGAL_NAME in first
    assert "Amount certified" in first, "the letterhead pushed the certification off page one"


def test_a_letterhead_too_tall_for_the_face_falls_back_to_the_name_line(
    profile: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other branch of the choice. A letterhead that would split the face is
    not placed; the legal name takes one line and the logo moves to the header
    band, so the page still says whose it is and the certification stays put."""
    tall: list[Any] = []

    def too_tall(width: float, doc_type: str | None = None) -> Spacer:
        spacer = Spacer(width, 400)
        tall.append(spacer)
        return spacer

    monkeypatch.setattr(aia_pdf, "branded_letterhead", too_tall)
    first = _pages(_aia())[0]
    text = first.extract_text()
    assert tall, "the generator never asked for a letterhead, so the fallback was not exercised"
    assert LEGAL_NAME in text, "the fallback dropped the legal name"
    assert "Amount certified" in text, "the certification left page one"
    assert _images_on(first) == 1, "the header logo did not take the letterhead's place"
