# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The company letterhead and the document logo, as they reach the printed page.

Some firms may not send an RFI without their formal logo and registered
details on it. These tests look at the produced PDF, not at the settings: the
text a reader sees, and which images the page actually draws.

Images are counted by *draws* (``/Name Do`` in the page content), not by the
page's image resources. reportlab stores one image once however often it is
drawn, so a page with the same logo in the letterhead and in the header would
list one resource and still print the logo twice.

``branded_letterhead`` returns ``None`` on any failure, which makes every "no
letterhead here" assertion pass on its own when the builder is broken. So each
suppression below is paired with the positive case in the same setup.

Every test writes its settings into a throwaway data dir; the branding, the
appearance and the company profile each resolve that dir on their own, so all
three are pointed at it.
"""

from __future__ import annotations

import base64
import io
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pypdf import PdfReader

from app.core import app_branding, company_profile, pdf_appearance
from app.core.pdf_branding import branded_header_footer, branded_letterhead, render_sample_pdf
from app.modules.rfi.pdf_export import USABLE_WIDTH, build_rfi_pdf

MM = 72.0 / 25.4
_DO = re.compile(rb"/([A-Za-z0-9_.+-]+)\s+Do\b")

LEGAL_NAME = "ООО «Строймонтаж»"
ADDRESS = "1200 Harbor Boulevard, Suite 400\nOakland, CA 94607"
#: Printed by the letterhead and nothing else. The legal name is not a marker
#: for the letterhead: the footer prints it too when the app has no name.
LETTERHEAD_ONLY = "Oakland, CA 94607"
REGISTRATION = "CA License #1034567 · EIN 94-3456789"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for module in (app_branding, company_profile, pdf_appearance):
        monkeypatch.setattr(module, "resolve_data_dir", lambda: tmp_path)
    return tmp_path


def _png(width: int, height: int, colour: tuple[int, int, int] = (200, 30, 60)) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _svg() -> str:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80"><rect width="240" height="80" fill="#1f6f43"/></svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


def _profile(data_dir: Path, **overrides: Any) -> None:
    payload = {
        "legal_name": LEGAL_NAME,
        "address": ADDRESS,
        "registration_line": REGISTRATION,
        "phone": "+1 (510) 555-0142",
        "email": "rfi@builders.example",
        "website": "",
    }
    payload.update(overrides)
    company_profile.write_company_profile(payload, data_dir)


def _app_logo(data_dir: Path, data_url: str) -> None:
    app_branding.write_branding({"mode": "logo", "logo_data_url": data_url}, data_dir)


def _rfi(**overrides: Any) -> SimpleNamespace:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "rfi_number": "RFI-007",
        "subject": "External walls - lintel detail at grid C/4",
        "question": "Drawing A-201 shows a precast lintel. Which governs?",
        "raised_by": None,
        "assigned_to": None,
        "ball_in_court": None,
        "status": "open",
        "official_response": None,
        "responded_by": None,
        "responded_at": None,
        "cost_impact": False,
        "cost_impact_value": None,
        "schedule_impact": False,
        "schedule_impact_days": None,
        "date_required": None,
        "response_due_date": None,
        "attachments": [],
        "priority": "high",
        "discipline": "structural",
        "created_at": datetime(2026, 9, 10, 8, 15, tzinfo=UTC),
    }
    row.update(overrides)
    return SimpleNamespace(**row)


def _rfi_pdf(**overrides: Any) -> bytes:
    return build_rfi_pdf(_rfi(**overrides), project_name="Residential House", currency="USD")


def _pages(pdf: bytes) -> list[Any]:
    return list(PdfReader(io.BytesIO(pdf)).pages)


def _text(pdf: bytes, page: int | None = None) -> str:
    pages = _pages(pdf)
    chosen = pages if page is None else [pages[page]]
    return "\n".join(p.extract_text() or "" for p in chosen)


def _image_draws(pdf: bytes, page: int = 0) -> list[tuple[int, int]]:
    """``(width, height)`` in pixels of every image the page draws, in order."""
    target = _pages(pdf)[page]
    xobjects = target["/Resources"].get("/XObject") or {}
    sizes: dict[str, tuple[int, int]] = {}
    for name, ref in xobjects.items():
        obj = ref.get_object()
        if obj.get("/Subtype") == "/Image":
            sizes[str(name).lstrip("/")] = (int(obj["/Width"]), int(obj["/Height"]))
    content = target.get_contents().get_data()
    return [sizes[name.decode()] for name in _DO.findall(content) if name.decode() in sizes]


def _image_boxes(pdf: bytes) -> list[tuple[float, float, float, float]]:
    """Bounding boxes (points, top-left origin) of the images on page one."""
    from tests._pdf_probe import image_boxes

    return [tuple(box) for box in image_boxes(pdf)]


# ── The RFI carries the letterhead ──────────────────────────────────────


def test_an_rfi_carries_the_firm_letterhead(data_dir: Path) -> None:
    _profile(data_dir, document_logo_data_url=_png(40, 10))
    pdf = _rfi_pdf()
    text = _text(pdf)
    for expected in (LEGAL_NAME, "Oakland, CA 94607", "CA License #1034567", "rfi@builders.example"):
        assert expected in text, expected
    # The logo is drawn once, in the letterhead; the small header logo that
    # would repeat it is left off page one.
    assert _image_draws(pdf) == [(40, 10)]
    assert len(_pages(pdf)) == 1


def test_later_pages_keep_the_small_header_logo(data_dir: Path) -> None:
    _profile(data_dir, document_logo_data_url=_png(40, 10))
    long_question = ("Please confirm the lintel detail at every opening on the east elevation. " * 12 + "\n") * 40
    pdf = _rfi_pdf(question=long_question)
    assert len(_pages(pdf)) > 1
    assert _image_draws(pdf, 0) == [(40, 10)]
    assert _image_draws(pdf, 1) == [(40, 10)]
    assert LETTERHEAD_ONLY in _text(pdf, 0)
    assert LETTERHEAD_ONLY not in _text(pdf, 1)


def test_without_a_profile_the_rfi_is_what_it_was(data_dir: Path) -> None:
    """No profile: no letterhead, and an app logo still sits in the header."""
    _app_logo(data_dir, _png(20, 5))
    before = _rfi_pdf()
    assert branded_letterhead(USABLE_WIDTH) is None
    assert _image_draws(before) == [(20, 5)]
    assert "Oakland" not in _text(before)

    # The same workspace once the profile is filled in: the letterhead appears,
    # which is what makes the absence above mean something.
    _profile(data_dir)
    after = _rfi_pdf()
    assert LETTERHEAD_ONLY in _text(after)
    # The letterhead has no logo of its own, so it takes the app logo, and the
    # header does not repeat it.
    assert _image_draws(after) == [(20, 5)]


def test_turning_the_letterhead_off_suppresses_it(data_dir: Path) -> None:
    _profile(data_dir, document_logo_data_url=_png(40, 10))
    assert LETTERHEAD_ONLY in _text(_rfi_pdf())

    pdf_appearance.write_appearance({"show_letterhead": False}, data_dir)
    assert branded_letterhead(USABLE_WIDTH) is None
    pdf = _rfi_pdf()
    assert LETTERHEAD_ONLY not in _text(pdf)
    # With no letterhead on page one, the header logo is back there.
    assert _image_draws(pdf) == [(40, 10)]


def test_the_document_logo_wins_over_the_app_logo(data_dir: Path) -> None:
    _app_logo(data_dir, _png(4, 1))
    _profile(data_dir, document_logo_data_url=_png(40, 10))
    pdf_appearance.write_appearance({"show_letterhead": False}, data_dir)
    assert _image_draws(_rfi_pdf()) == [(40, 10)]

    # And in the shared header every other generator draws.
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf)
    doc.addPageTemplates([PageTemplate(frames=[Frame(56, 56, 480, 700)], onPage=branded_header_footer)])
    doc.build([Paragraph("body", getSampleStyleSheet()["Normal"])])
    assert _image_draws(buf.getvalue()) == [(40, 10)]


def test_a_document_logo_that_does_not_decode_falls_back_to_the_app_logo(data_dir: Path) -> None:
    _app_logo(data_dir, _png(4, 1))
    _profile(data_dir, document_logo_data_url="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==")
    pdf = _rfi_pdf()
    assert LETTERHEAD_ONLY in _text(pdf)
    assert _image_draws(pdf) == [(4, 1)]


def test_a_logo_without_a_name_is_still_a_letterhead(data_dir: Path) -> None:
    """A document logo alone switches the letterhead on; it then prints alone."""
    company_profile.write_company_profile({"document_logo_data_url": _png(40, 10)}, data_dir)
    assert branded_letterhead(USABLE_WIDTH) is not None
    pdf = _rfi_pdf()
    assert _image_draws(pdf) == [(40, 10)]
    assert len(_pages(pdf)) == 1


def test_an_svg_document_logo_is_drawn_as_the_png_the_browser_made_of_it(data_dir: Path) -> None:
    """The server does not rasterise SVG: the PNG stored next to it is what prints."""
    _profile(data_dir, document_logo_data_url=_svg(), document_logo_png_data_url=_png(60, 20))
    assert _image_draws(_rfi_pdf()) == [(60, 20)]


def test_an_svg_document_logo_without_a_png_prints_the_name_and_no_picture(data_dir: Path) -> None:
    """An SVG saved before the PNG existed cannot be drawn; the letterhead still prints."""
    _profile(data_dir, document_logo_data_url=_svg())
    pdf = _rfi_pdf()
    assert _image_draws(pdf) == []
    assert LEGAL_NAME in _text(pdf)
    assert LETTERHEAD_ONLY in _text(pdf)


def test_an_svg_document_logo_without_a_png_leaves_the_app_logo_in_the_header(data_dir: Path) -> None:
    _app_logo(data_dir, _png(20, 5))
    _profile(data_dir, document_logo_data_url=_svg())
    assert _image_draws(_rfi_pdf()) == [(20, 5)]


@pytest.mark.parametrize(
    "logo",
    [
        "data:image/png;base64,@@@not-base64@@@",
        # A real PNG cut short: the header reads, the pixels do not.
        None,
    ],
)
def test_a_corrupt_logo_never_breaks_the_letterhead(data_dir: Path, logo: str | None) -> None:
    if logo is None:
        full = base64.b64decode(_png(40, 10).split("base64,", 1)[1])
        logo = "data:image/png;base64," + base64.b64encode(full[:60]).decode()
    _profile(data_dir, document_logo_data_url=logo)
    assert branded_letterhead(USABLE_WIDTH) is not None
    pdf = _rfi_pdf()
    assert LETTERHEAD_ONLY in _text(pdf)
    assert _image_draws(pdf) == []


def test_a_profile_read_that_raises_costs_the_letterhead_not_the_rfi(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _profile(data_dir)
    assert branded_letterhead(USABLE_WIDTH) is not None

    def _boom() -> dict[str, str]:
        raise RuntimeError("profile unavailable")

    monkeypatch.setattr(company_profile, "read_company_profile", _boom)
    assert branded_letterhead(USABLE_WIDTH) is None
    assert "Request for Information" in _text(_rfi_pdf())


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_the_logo_follows_the_alignment_setting(data_dir: Path, align: str) -> None:
    _profile(data_dir, document_logo_data_url=_png(120, 40))
    pdf_appearance.write_appearance({"logo_align": align}, data_dir)
    pdf = _rfi_pdf()
    assert LETTERHEAD_ONLY in _text(pdf)
    boxes = _image_boxes(pdf)
    assert len(boxes) == 1
    x0, _, x1, _ = boxes[0]
    left, right = 20 * MM, 210 * MM - 20 * MM
    if align == "left":
        assert x0 == pytest.approx(left, abs=1.0)
    elif align == "right":
        assert x1 == pytest.approx(right, abs=1.0)
    else:
        assert (x0 + x1) / 2 == pytest.approx((left + right) / 2, abs=1.0)


# ── The RFI footer follows the document appearance ─────────────────────


def test_the_rfi_footer_follows_the_saved_footer_line_and_page_numbers(data_dir: Path) -> None:
    default = _text(_rfi_pdf())
    assert "Generated" in default
    assert "Page 1" in default

    pdf_appearance.write_appearance(
        {"footer_text": "Pacific Builders Inc. - Controlled copy", "show_page_numbers": False}, data_dir
    )
    text = _text(_rfi_pdf())
    assert "Pacific Builders Inc. - Controlled copy" in text
    assert "Generated" not in text
    assert "Page 1" not in text


def test_the_rfi_footer_is_painted_in_the_saved_footer_colour(data_dir: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.rl_accel import fp_str

    colour = colors.HexColor("#aa0044")
    fill = f"{fp_str(colour.red, colour.green, colour.blue)} rg".encode()
    assert fill not in _pages(_rfi_pdf())[0].get_contents().get_data()

    pdf_appearance.write_appearance({"footer_color": "#aa0044"}, data_dir)
    assert fill in _pages(_rfi_pdf())[0].get_contents().get_data()


# ── The brand name: app name, else legal name, else the platform ────────


def _metadata(pdf: bytes) -> Any:
    return PdfReader(io.BytesIO(pdf)).metadata


def _shared_header_footer_pdf() -> bytes:
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph

    from app.core.pdf_branding import branded_doc_metadata

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, **branded_doc_metadata())
    doc.addPageTemplates([PageTemplate(frames=[Frame(56, 56, 480, 700)], onPage=branded_header_footer)])
    doc.build([Paragraph("body", getSampleStyleSheet()["Normal"])])
    return buf.getvalue()


def test_the_legal_name_brands_a_workspace_whose_app_has_no_name(data_dir: Path) -> None:
    """A formal document must not be credited to the platform once the firm is known."""
    before = _rfi_pdf()
    assert "OpenConstructionERP" in _text(before)
    assert _metadata(before).author == "OpenConstructionERP"

    _profile(data_dir)
    # With the letterhead off, the legal name can only have come from the
    # footer, not from the letterhead printing it.
    pdf_appearance.write_appearance({"show_letterhead": False}, data_dir)
    pdf = _rfi_pdf()
    assert LEGAL_NAME in _text(pdf)
    assert "OpenConstructionERP" not in _text(pdf)
    assert _metadata(pdf).author == LEGAL_NAME
    assert "OpenConstructionERP" not in (_metadata(pdf).producer or "")

    # The shared header band and footer every other generator draws follow too.
    shared = _shared_header_footer_pdf()
    assert LEGAL_NAME in _text(shared)
    assert "OpenConstructionERP" not in _text(shared)
    assert _metadata(shared).author == LEGAL_NAME


def test_the_app_name_still_wins_over_the_legal_name(data_dir: Path) -> None:
    app_branding.write_branding({"mode": "text", "company_name": "Acme Builders"}, data_dir)
    _profile(data_dir)
    pdf_appearance.write_appearance({"show_letterhead": False}, data_dir)
    pdf = _rfi_pdf()
    assert "Acme Builders" in _text(pdf)
    assert LEGAL_NAME not in _text(pdf)
    assert _metadata(pdf).author == "Acme Builders"


def test_a_logo_only_app_brand_takes_the_legal_name_in_its_metadata(data_dir: Path) -> None:
    """Logo-only used to mean neutral metadata; with a legal name known, it names the firm."""
    _app_logo(data_dir, _png(4, 1))
    assert _metadata(_rfi_pdf()).author == "Construction cost management"
    _profile(data_dir)
    assert _metadata(_rfi_pdf()).author == LEGAL_NAME


# ── The settings preview ─────────────────────────────────────────────────


def test_the_sample_carries_the_letterhead_and_one_logo(data_dir: Path) -> None:
    _profile(data_dir, document_logo_data_url=_png(40, 10))
    pdf = render_sample_pdf()
    assert len(_pages(pdf)) == 1
    text = _text(pdf)
    assert "Sample document" in text
    assert LETTERHEAD_ONLY in text
    assert _image_draws(pdf) == [(40, 10)]


def test_the_sample_without_a_profile_shows_the_header_band(data_dir: Path) -> None:
    _app_logo(data_dir, _png(20, 5))
    pdf = render_sample_pdf()
    assert "Sample document" in _text(pdf)
    assert _image_draws(pdf) == [(20, 5)]


def test_the_sample_follows_the_saved_page_size(data_dir: Path) -> None:
    pdf_appearance.write_appearance({"page_size": "LETTER"}, data_dir)
    box = _pages(render_sample_pdf())[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (612, 792)


def _client() -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.branding_router import router
    from app.dependencies import get_current_user_payload

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(uuid.uuid4())}
    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/v1/document-appearance/sample.pdf", "/api/v1/document-appearance/sample.pdf/"])
def test_the_sample_endpoint_returns_an_inline_pdf(data_dir: Path, path: str) -> None:
    _profile(data_dir)
    response = _client().get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["cache-control"] == "no-store"
    # The placeholder text is English; the header must say so rather than
    # echo whatever language the reader asked for.
    assert response.headers["content-language"] == "en"
    assert response.content.startswith(b"%PDF")
    assert LETTERHEAD_ONLY in _text(response.content)


def test_the_sample_endpoint_needs_a_signed_in_user(data_dir: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.branding_router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    assert TestClient(app).get("/api/v1/document-appearance/sample.pdf").status_code == 401


# ── The appearance flag lands everywhere it is read ─────────────────────


def test_the_letterhead_flag_is_in_every_appearance_shape() -> None:
    from app.core.branding_router import DocumentAppearanceResponse, DocumentAppearanceUpdate

    assert pdf_appearance.DEFAULT_APPEARANCE["show_letterhead"] is True
    assert set(DocumentAppearanceResponse.model_fields) == set(pdf_appearance.DEFAULT_APPEARANCE)
    assert set(DocumentAppearanceUpdate.model_fields) == set(pdf_appearance.DEFAULT_APPEARANCE)


def test_the_put_endpoint_persists_the_letterhead_switch(data_dir: Path) -> None:
    import asyncio

    from app.core.branding_router import DocumentAppearanceUpdate, put_document_appearance

    stored = asyncio.run(put_document_appearance(DocumentAppearanceUpdate(show_letterhead=False)))
    assert stored.show_letterhead is False
    assert pdf_appearance.read_appearance(data_dir)["show_letterhead"] is False
    # Sending an unrelated field leaves it off: the PUT merges.
    asyncio.run(put_document_appearance(DocumentAppearanceUpdate(accent_color="#123456")))
    assert pdf_appearance.read_appearance(data_dir)["show_letterhead"] is False
