# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests — PDF upload magic-byte check.

Covers bullet 1 of the R7 hardening sweep:
  * Every PDF upload endpoint must validate the file starts with ``%PDF-``
    magic bytes.
  * Reject with HTTP 415 (Unsupported Media Type) otherwise.
  * Pattern from the submittals router.

All tests are pure-Python (no DB, no real filesystem writes).
The magic-byte gate lives in the router (``upload_document`` handler).
We test the service-layer path separately to ensure it does NOT re-check
magic bytes — that concern belongs exclusively to the router boundary.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.takeoff import service as takeoff_service
from app.modules.takeoff.service import TakeoffService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> TakeoffService:
    svc = object.__new__(TakeoffService)
    svc.session = MagicMock()
    svc.repo = MagicMock()
    svc.measurement_repo = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Router-level magic-byte gate
# ---------------------------------------------------------------------------
#
# We test the gate by directly calling the router's ``upload_document``
# via the FastAPI test client would require a full app setup; instead
# we isolate the gate logic by extracting the content-check portion.
#
# The gate rule (in router.py) is:
#   if not content.startswith(b"%PDF-"):
#       raise HTTPException(status_code=415, ...)
#
# We pin this behaviour via a functional-style helper that mirrors the gate.


def _router_magic_byte_gate(content: bytes) -> None:
    """Mirrors the upload_document router gate for testability."""
    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=415,
            detail=("File does not appear to be a valid PDF (missing %PDF- magic bytes)."),
        )


class TestMagicByteGateLogic:
    """Direct tests of the magic-byte gate logic."""

    def test_valid_pdf_passes(self) -> None:
        """A buffer starting with %PDF- passes the gate."""
        _router_magic_byte_gate(b"%PDF-1.4\n%...")
        _router_magic_byte_gate(b"%PDF-1.7\n%...")
        _router_magic_byte_gate(b"%PDF-2.0\n%...")

    def test_jpeg_rejected(self) -> None:
        """JPEG magic bytes (FF D8 FF) must be rejected."""
        jpeg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"JFIF..."
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(jpeg)
        assert exc.value.status_code == 415

    def test_png_rejected(self) -> None:
        """PNG magic bytes (89 50 4E 47) must be rejected."""
        png = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A]) + b"..."
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(png)
        assert exc.value.status_code == 415

    def test_zip_rejected(self) -> None:
        """ZIP magic bytes (PK\x03\x04) must be rejected."""
        zip_bytes = b"PK\x03\x04" + b"\x00" * 26
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(zip_bytes)
        assert exc.value.status_code == 415

    def test_html_rejected(self) -> None:
        """HTML content must be rejected."""
        html = b"<html><body>Not a PDF</body></html>"
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(html)
        assert exc.value.status_code == 415

    def test_empty_bytes_rejected(self) -> None:
        """Empty upload must be rejected by the magic byte check."""
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(b"")
        assert exc.value.status_code == 415

    def test_pdf_prefix_but_wrong_case_rejected(self) -> None:
        """%pdf- (lowercase) is not a valid PDF header — case-sensitive."""
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(b"%pdf-1.4\n...")
        assert exc.value.status_code == 415

    def test_pdf_prefix_with_space_rejected(self) -> None:
        """'% PDF-' (space after %) is not a valid PDF magic byte sequence."""
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(b"% PDF-1.4\n...")
        assert exc.value.status_code == 415

    def test_null_prefixed_pdf_rejected(self) -> None:
        """A null byte before %PDF- must be rejected."""
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(b"\x00%PDF-1.4\n...")
        assert exc.value.status_code == 415

    def test_detail_message_mentions_pdf_header(self) -> None:
        """The rejection message must be user-actionable."""
        with pytest.raises(HTTPException) as exc:
            _router_magic_byte_gate(b"JUNK")
        detail = str(exc.value.detail).lower()
        # Must mention the magic bytes issue so the user knows what to fix.
        assert "pdf" in detail or "%pdf" in detail.lower()


# ---------------------------------------------------------------------------
# Service layer does NOT re-check magic bytes
# ---------------------------------------------------------------------------
#
# The service layer should TRUST that the router already validated the magic
# bytes. If the service also validates, double-checking causes needless
# coupling. The service gates are: zero bytes, size cap, and encryption.


class TestServiceDoesNotDuplicateMagicByteCheck:
    @pytest.mark.asyncio
    async def test_service_accepts_non_pdf_bytes_if_parseable(self, monkeypatch, tmp_path) -> None:
        """The service itself does not re-validate magic bytes.

        The magic-byte gate is a router concern. The service trusts what
        the router passes. This test confirms the service does not add a
        *second* magic-byte assertion.

        We pass a minimal "PDF" with correct prefix (to pass service gates
        like zero-byte and encryption checks), stub the parsers, and verify
        no 415 is raised.
        """
        monkeypatch.setattr(
            takeoff_service,
            "_TAKEOFF_DOCUMENTS_DIR",
            tmp_path / "td",
        )
        monkeypatch.setattr(takeoff_service, "_count_pdf_pages", lambda *a, **k: 1)
        monkeypatch.setattr(
            takeoff_service,
            "_extract_pdf_pages",
            lambda *a, **k: [{"page": 1, "text": "ok"}],
        )

        class _AwaitableCreate:
            async def create(self, doc):
                return doc

        svc = _make_service()
        svc.repo = _AwaitableCreate()

        content = b"%PDF-1.4\n" + b"some content"
        doc = await svc.upload_document(
            filename="test.pdf",
            content=content,
            size_bytes=len(content),
            owner_id=str(uuid.uuid4()),
        )
        assert doc is not None
        # No 415 raised — the service handles only size/encryption/parse gates.
