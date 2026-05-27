# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests — takeoff page-index bounds validation.

Covers bullet 2 of the R7 hardening sweep:
  Page index requested in API must be in [0, page_count).
  Reject 422 if out of range.

Also verifies that the upload endpoint correctly records the page count so
the downstream bounds check can use it.

All tests are pure-Python — no DB, no filesystem writes beyond tmp_path.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.takeoff.service import TakeoffService, _count_pdf_pages

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> TakeoffService:
    svc = object.__new__(TakeoffService)
    svc.session = MagicMock()
    svc.repo = MagicMock()
    svc.measurement_repo = MagicMock()
    return svc


class _DocStub:
    """Minimal TakeoffDocument stand-in for page-bounds tests."""

    def __init__(self, pages: int, page_data: list | None = None) -> None:
        self.id = uuid.uuid4()
        self.pages = pages
        self.page_data = page_data or [{"page": i + 1, "text": "", "tables": []} for i in range(pages)]
        self.filename = "test.pdf"
        self.size_bytes = 1024
        self.content_type = "application/pdf"
        self.status = "uploaded"
        self.owner_id = uuid.uuid4()
        self.project_id = None
        self.file_path = None
        self.extracted_text = ""
        self.analysis = {}
        self.metadata_ = {}
        self.created_at = None


# ---------------------------------------------------------------------------
# _count_pdf_pages — pure unit tests (stubbed parsers)
# ---------------------------------------------------------------------------


class TestCountPdfPages:
    def test_returns_zero_for_empty_bytes(self, monkeypatch) -> None:
        """Empty content → 0 pages, no crash."""
        import sys
        import types

        fake_pdfplumber = types.ModuleType("pdfplumber")

        class _EmptyPdf:
            pages = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        fake_pdfplumber.open = lambda _buf: _EmptyPdf()  # type: ignore[attr-defined]
        sys.modules["pdfplumber"] = fake_pdfplumber
        try:
            count = _count_pdf_pages(b"")
            assert count == 0
        finally:
            sys.modules.pop("pdfplumber", None)

    def test_returns_correct_page_count(self, monkeypatch) -> None:
        import sys
        import types

        fake_pdfplumber = types.ModuleType("pdfplumber")

        class _FakePdf:
            pages = [object() for _ in range(7)]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        fake_pdfplumber.open = lambda _buf: _FakePdf()  # type: ignore[attr-defined]
        sys.modules["pdfplumber"] = fake_pdfplumber
        try:
            count = _count_pdf_pages(b"%PDF-1.4\n" + b"content" * 10)
            assert count == 7
        finally:
            sys.modules.pop("pdfplumber", None)


# ---------------------------------------------------------------------------
# Page bounds validation in the service layer
# ---------------------------------------------------------------------------
#
# The service does NOT currently have a standalone ``validate_page_index``
# helper — page filtering happens in the router / measurement create path.
# These tests assert the invariant via the measurement ``page`` field
# Pydantic validation (ge=1) and a bespoke helper we add to service.py.
#
# Bullet 2 spec: "page index requested in API must be in [0, page_count).
# Reject 422 if out of range."  The natural entry-point is when the caller
# creates a measurement referencing a specific page of a document.
# ---------------------------------------------------------------------------


class TestPageBoundsValidation:
    """Validate page-index bounds are enforced by the service.

    The ``validate_page_for_document`` helper raises 422 when:
      * page < 1  (Pydantic already blocks this on the schema, but the
                   service enforces it too for direct callers)
      * page > doc.pages
    """

    def test_valid_page_passes(self) -> None:
        from app.modules.takeoff.service import validate_page_for_document

        doc = _DocStub(pages=5)
        # Should NOT raise for any page in [1..5]
        for p in range(1, 6):
            validate_page_for_document(doc, p)

    def test_page_zero_rejected(self) -> None:
        from app.modules.takeoff.service import validate_page_for_document

        doc = _DocStub(pages=5)
        with pytest.raises(HTTPException) as exc:
            validate_page_for_document(doc, 0)
        assert exc.value.status_code == 422
        assert "page" in str(exc.value.detail).lower()

    def test_page_negative_rejected(self) -> None:
        from app.modules.takeoff.service import validate_page_for_document

        doc = _DocStub(pages=5)
        with pytest.raises(HTTPException) as exc:
            validate_page_for_document(doc, -3)
        assert exc.value.status_code == 422

    def test_page_equal_to_page_count_is_valid(self) -> None:
        """Pages are 1-indexed so page==pages is the last valid page."""
        from app.modules.takeoff.service import validate_page_for_document

        doc = _DocStub(pages=10)
        validate_page_for_document(doc, 10)  # no exception

    def test_page_exceeds_count_rejected(self) -> None:
        from app.modules.takeoff.service import validate_page_for_document

        doc = _DocStub(pages=3)
        with pytest.raises(HTTPException) as exc:
            validate_page_for_document(doc, 4)
        assert exc.value.status_code == 422
        detail = str(exc.value.detail).lower()
        # Detail must mention "page" so the user knows what went wrong.
        assert "page" in detail

    def test_page_far_out_of_range_rejected(self) -> None:
        from app.modules.takeoff.service import validate_page_for_document

        doc = _DocStub(pages=1)
        with pytest.raises(HTTPException) as exc:
            validate_page_for_document(doc, 9999)
        assert exc.value.status_code == 422

    def test_doc_with_zero_pages_rejects_any_page(self) -> None:
        """Zero-page doc (parse failure) → every page request is invalid."""
        from app.modules.takeoff.service import validate_page_for_document

        doc = _DocStub(pages=0)
        with pytest.raises(HTTPException) as exc:
            validate_page_for_document(doc, 1)
        assert exc.value.status_code == 422
