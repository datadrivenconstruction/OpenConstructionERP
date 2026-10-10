# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure unit tests for the shared PDF branding helper (``app.core.pdf_branding``).

These tests import NO database and NO module ORM models - only the branding
core and reportlab, which is a base dependency. They assert the documented
contracts: the company-name fallback, the document-metadata fallback, and the
never-raise / graceful-degrade promise (a malformed logo data URL or a broken
branding read must not crash a PDF export). Where they build a PDF they do so
entirely in memory.

The workspace branding is monkeypatched at the source -
``app.core.app_branding.read_branding`` - which the helper imports lazily, so
nothing touches the persisted file or the data dir.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from app.core import pdf_branding
from app.core.pdf_branding import (
    DEFAULT_BRAND,
    branded_cover_brand,
    branded_doc_metadata,
    branded_header_footer,
    branded_header_logo,
)


@pytest.fixture(autouse=True)
def _no_company_profile(monkeypatch):
    """Keep a company profile on the machine running the tests out of them.

    The header prefers the profile's document logo, and the profile is read
    from the real data dir; a test here that sets one patches this again.
    """
    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda: {})


def _set_branding(monkeypatch, branding: dict) -> None:
    """Patch the lazily-imported ``read_branding`` to return *branding*."""
    monkeypatch.setattr("app.core.app_branding.read_branding", lambda: branding)


def _make_doc(buffer: BytesIO):
    """Build a tiny A4 doc whose page template draws the brand header/footer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

    frame = Frame(20 * mm, 18 * mm, A4[0] - 40 * mm, A4[1] - 40 * mm, id="body")
    template = PageTemplate(id="body", frames=[frame], onPage=branded_header_footer)
    doc = BaseDocTemplate(buffer, pagesize=A4, **branded_doc_metadata())
    doc.addPageTemplates([template])
    return doc


# A valid 1x1 transparent PNG, base64-encoded (exercises the real logo path).
_PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


# -- branded_cover_brand --------------------------------------------------------


def test_branded_cover_brand_defaults_when_unset(monkeypatch):
    _set_branding(monkeypatch, {"mode": "default", "logo_data_url": None, "company_name": ""})
    assert branded_cover_brand() == DEFAULT_BRAND


def test_branded_cover_brand_uses_company_name(monkeypatch):
    _set_branding(monkeypatch, {"mode": "text", "logo_data_url": None, "company_name": "Acme Builders"})
    assert branded_cover_brand() == "Acme Builders"


def test_branded_cover_brand_trims_whitespace_only_name(monkeypatch):
    _set_branding(monkeypatch, {"mode": "text", "logo_data_url": None, "company_name": "   "})
    assert branded_cover_brand() == DEFAULT_BRAND


def test_branded_cover_brand_does_not_raise_when_read_fails(monkeypatch):
    """A broken branding read degrades to the default brand, never raises."""

    def _boom():
        raise RuntimeError("branding read exploded")

    monkeypatch.setattr("app.core.app_branding.read_branding", _boom)
    assert branded_cover_brand() == DEFAULT_BRAND


# -- branded_doc_metadata -------------------------------------------------------


def test_branded_doc_metadata_fallback_when_unset(monkeypatch):
    _set_branding(monkeypatch, {"mode": "default", "logo_data_url": None, "company_name": ""})
    meta = branded_doc_metadata()
    assert meta["author"] == DEFAULT_BRAND
    assert meta["creator"] == DEFAULT_BRAND
    # The static fields are always present so callers can splat the dict.
    assert set(meta) >= {"author", "creator", "subject", "producer", "keywords"}
    assert all(isinstance(v, str) and v for v in meta.values())


def test_branded_doc_metadata_uses_company_name(monkeypatch):
    _set_branding(monkeypatch, {"mode": "text", "logo_data_url": None, "company_name": "Acme Builders"})
    meta = branded_doc_metadata()
    assert meta["author"] == "Acme Builders"
    assert meta["creator"] == "Acme Builders"


def test_branded_doc_metadata_does_not_raise_when_read_fails(monkeypatch):
    def _boom():
        raise ValueError("nope")

    monkeypatch.setattr("app.core.app_branding.read_branding", _boom)
    meta = branded_doc_metadata()
    assert meta["author"] == DEFAULT_BRAND


# -- branded_header_footer (renders a real PDF, must never raise) ---------------


def test_header_footer_renders_with_text_brand(monkeypatch):
    _set_branding(monkeypatch, {"mode": "text", "logo_data_url": None, "company_name": "Acme Builders"})
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph

    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = _make_doc(buf)
    doc.build([Paragraph("page one", styles["Normal"]), PageBreak(), Paragraph("page two", styles["Normal"])])
    out = buf.getvalue()
    assert out.startswith(b"%PDF")


def test_header_footer_renders_with_valid_logo(monkeypatch):
    _set_branding(
        monkeypatch,
        {"mode": "logo", "logo_data_url": f"data:image/png;base64,{_PNG_1PX}", "company_name": "Acme"},
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph

    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = _make_doc(buf)
    doc.build([Paragraph("body", styles["Normal"])])
    assert buf.getvalue().startswith(b"%PDF")


def test_header_footer_malformed_logo_does_not_raise(monkeypatch):
    """A malformed logo data URL must fall back to text, not crash the export."""
    _set_branding(
        monkeypatch,
        {
            "mode": "logo",
            "logo_data_url": "data:image/png;base64,@@@@not-valid-base64@@@@",
            "company_name": "Acme",
        },
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph

    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = _make_doc(buf)
    # Must not raise - the broken logo degrades to the company-name text.
    doc.build([Paragraph("body", styles["Normal"])])
    assert buf.getvalue().startswith(b"%PDF")


def test_header_footer_never_raises_when_branding_read_fails(monkeypatch):
    """Even a broken branding read leaves a valid (default-branded) PDF."""

    def _boom():
        raise RuntimeError("branding unavailable")

    monkeypatch.setattr("app.core.app_branding.read_branding", _boom)
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph

    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = _make_doc(buf)
    doc.build([Paragraph("body", styles["Normal"])])
    assert buf.getvalue().startswith(b"%PDF")


def test_draw_logo_returns_false_on_garbage_without_raising(monkeypatch):
    """``_draw_logo`` reports failure (False) and never raises on bad input."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(BytesIO(), pagesize=A4)
    assert pdf_branding._draw_logo(c, {"logo_data_url": None}, x=50, top_y=800) is False
    assert pdf_branding._draw_logo(c, {"logo_data_url": "not-a-data-url"}, x=50, top_y=800) is False
    assert (
        pdf_branding._draw_logo(
            c,
            {"logo_data_url": "data:image/png;base64,@@@bad@@@"},
            x=50,
            top_y=800,
        )
        is False
    )
    # A valid PNG draws successfully.
    assert (
        pdf_branding._draw_logo(
            c,
            {"logo_data_url": f"data:image/png;base64,{_PNG_1PX}"},
            x=50,
            top_y=800,
        )
        is True
    )


# -- brand-aware metadata: a white label must never leak the platform name -----


def test_branded_doc_metadata_custom_name_never_leaks_platform(monkeypatch):
    """A workspace company name owns every metadata field; no platform leak."""
    _set_branding(monkeypatch, {"mode": "text", "logo_data_url": None, "company_name": "Acme Build Co"})
    meta = branded_doc_metadata()
    assert meta["producer"] == "Acme Build Co"
    assert meta["keywords"] == "Acme Build Co"
    assert meta["subject"] == "Generated by Acme Build Co"
    for value in meta.values():
        assert "OpenConstructionERP" not in value
        assert "DataDrivenConstruction" not in value


def test_branded_doc_metadata_logo_only_is_brand_neutral(monkeypatch):
    """A logo-only white label (no name) stays brand-neutral, never the default."""
    _set_branding(
        monkeypatch,
        {"mode": "logo", "logo_data_url": f"data:image/png;base64,{_PNG_1PX}", "company_name": ""},
    )
    meta = branded_doc_metadata()
    for value in meta.values():
        assert "OpenConstructionERP" not in value
        assert "DataDrivenConstruction" not in value


# -- branded_header_logo (header-only logo for generators with their own text) --


class _RecordingCanvas:
    """Minimal canvas that records ``drawImage`` calls for assertions."""

    def __init__(self) -> None:
        self.images: list[dict] = []

    def drawImage(self, reader, x, y, **kwargs):  # noqa: N802
        self.images.append({"x": x, "y": y, **kwargs})


class _FakeDoc:
    # Attribute names mirror reportlab's DocTemplate API (mixedCase), which the
    # helper reads via getattr; hence the N815 suppressions.
    pagesize = (595.0, 842.0)
    leftMargin = 56.0  # noqa: N815
    rightMargin = 56.0  # noqa: N815


def test_branded_header_logo_noop_without_logo(monkeypatch):
    """No configured logo: draw nothing and report False (text brand stays)."""
    _set_branding(monkeypatch, {"mode": "text", "logo_data_url": None, "company_name": "Acme"})
    canvas = _RecordingCanvas()
    assert branded_header_logo(canvas, _FakeDoc()) is False
    assert canvas.images == []


def test_branded_header_logo_draws_right_aligned_when_set(monkeypatch):
    """A configured logo draws once, right-aligned to clear a left header title."""
    _set_branding(
        monkeypatch,
        {"mode": "logo", "logo_data_url": f"data:image/png;base64,{_PNG_1PX}", "company_name": ""},
    )
    canvas = _RecordingCanvas()
    assert branded_header_logo(canvas, _FakeDoc()) is True
    assert len(canvas.images) == 1
    img = canvas.images[0]
    # Right-aligned: the logo's right edge sits at page_w - rightMargin = 539.
    assert img["x"] + img["width"] == pytest.approx(539.0, abs=0.5)


def test_branded_header_logo_draws_a_document_logo_without_an_app_logo(monkeypatch):
    """A firm that uploaded only its formal logo still gets it in the header.

    The helper used to return early on "no app logo" before looking anywhere
    else, so a document logo alone drew nothing.
    """
    _set_branding(monkeypatch, {"mode": "text", "logo_data_url": None, "company_name": "Acme"})
    monkeypatch.setattr(
        "app.core.company_profile.read_company_profile",
        lambda: {"document_logo_data_url": f"data:image/png;base64,{_PNG_1PX}"},
    )
    canvas = _RecordingCanvas()
    assert branded_header_logo(canvas, _FakeDoc()) is True
    assert len(canvas.images) == 1


def test_branded_header_logo_never_raises_when_profile_read_fails(monkeypatch):
    """A broken profile read costs the document logo, never the app logo."""
    _set_branding(
        monkeypatch,
        {"mode": "logo", "logo_data_url": f"data:image/png;base64,{_PNG_1PX}", "company_name": ""},
    )

    def _boom():
        raise RuntimeError("profile unavailable")

    monkeypatch.setattr("app.core.company_profile.read_company_profile", _boom)
    canvas = _RecordingCanvas()
    assert branded_header_logo(canvas, _FakeDoc()) is True
    assert len(canvas.images) == 1


def test_branded_header_logo_never_raises_when_branding_read_fails(monkeypatch):
    """A broken branding read leaves the header without a logo, never raises."""

    def _boom():
        raise RuntimeError("branding unavailable")

    monkeypatch.setattr("app.core.app_branding.read_branding", _boom)
    canvas = _RecordingCanvas()
    assert branded_header_logo(canvas, _FakeDoc()) is False


class _LandscapeCanvas(_RecordingCanvas):
    """A canvas on a landscape sheet of a document that was opened in portrait."""

    _pagesize = (842.0, 595.0)


def test_page_size_asks_the_canvas_before_the_document():
    """A landscape template inside a portrait document reports the sheet in hand."""
    assert pdf_branding._page_size(_FakeDoc(), _LandscapeCanvas()) == (842.0, 595.0)
    assert pdf_branding._page_size(_FakeDoc()) == (595.0, 842.0)
    # A stand-in canvas with no real page size falls through to the document.
    assert pdf_branding._page_size(_FakeDoc(), _RecordingCanvas()) == (595.0, 842.0)
    assert pdf_branding._page_size(_FakeDoc(), MagicMock()) == (595.0, 842.0)
    assert pdf_branding._page_size(object(), None) == pytest.approx((595.28, 841.89), abs=0.01)


def test_header_logo_lands_inside_a_landscape_template_page(monkeypatch):
    """Positioned from the portrait size, the logo was drawn above a landscape sheet."""
    _set_branding(
        monkeypatch,
        {"mode": "logo", "logo_data_url": f"data:image/png;base64,{_PNG_1PX}", "company_name": ""},
    )
    canvas = _LandscapeCanvas()
    assert branded_header_logo(canvas, _FakeDoc()) is True
    assert len(canvas.images) == 1
    image = canvas.images[0]
    assert 0 <= image["y"] < 595.0
    assert image["y"] + image["height"] <= 595.0
    assert image["x"] + image["width"] <= 842.0 - 56.0 + 0.01
    # Right of where a portrait sheet ends: the corner of the landscape one.
    assert image["x"] > 595.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
