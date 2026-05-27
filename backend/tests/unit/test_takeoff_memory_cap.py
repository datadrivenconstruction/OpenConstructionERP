# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests — memory cap for large PDFs.

Covers bullet 7 of the R7 hardening sweep:
  * Large PDFs (>50 pages or >100 MB) must not OOM the worker.
  * The ``OE_TAKEOFF_MAX_UPLOAD_MB`` env var is the primary gate.
  * When the limit is set, uploads above the cap return 413.
  * The default (no env var) does NOT cap uploads — memory safety
    comes from streaming I/O upstream, not a hard byte cap.
  * The per-page text extraction budget is bounded so a 5000-page PDF
    with 100 KB of text per page doesn't construct a 500 MB string
    in a single join — we assert the full_text is not absurdly large.

All tests are pure-Python (no real PDF parsing, no filesystem writes
beyond tmp_path).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.takeoff import service as takeoff_service
from app.modules.takeoff.service import _max_upload_bytes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service():
    from app.modules.takeoff.service import TakeoffService

    svc = object.__new__(TakeoffService)
    svc.session = MagicMock()
    svc.measurement_repo = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Upload cap gate
# ---------------------------------------------------------------------------


class TestUploadCap:
    @pytest.mark.asyncio
    async def test_upload_above_100mb_rejected_when_cap_configured(self, monkeypatch, tmp_path) -> None:
        """When OE_TAKEOFF_MAX_UPLOAD_MB=100, a 101 MB payload returns 413."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "100")
        monkeypatch.setattr(
            takeoff_service,
            "_TAKEOFF_DOCUMENTS_DIR",
            tmp_path / "td",
        )
        svc = _make_service()

        payload = b"%PDF-1.4\n" + b"x" * (101 * 1024 * 1024)

        with pytest.raises(HTTPException) as exc:
            await svc.upload_document(
                filename="huge.pdf",
                content=payload,
                size_bytes=len(payload),
                owner_id=str(uuid.uuid4()),
            )
        assert exc.value.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_below_cap_passes_gate(self, monkeypatch, tmp_path) -> None:
        """When OE_TAKEOFF_MAX_UPLOAD_MB=100, a 1 MB payload passes the cap gate."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "100")
        monkeypatch.setattr(
            takeoff_service,
            "_TAKEOFF_DOCUMENTS_DIR",
            tmp_path / "td",
        )
        monkeypatch.setattr(takeoff_service, "_count_pdf_pages", lambda *a, **k: 1)
        monkeypatch.setattr(
            takeoff_service,
            "_extract_pdf_pages",
            lambda *a, **k: [{"page": 1, "text": "hello"}],
        )

        class _AwaitableCreate:
            async def create(self, doc):
                return doc

        svc = _make_service()
        svc.repo = _AwaitableCreate()

        payload = b"%PDF-1.4\n" + b"x" * (1 * 1024 * 1024)
        # Should not raise 413
        try:
            doc = await svc.upload_document(
                filename="small.pdf",
                content=payload,
                size_bytes=len(payload),
                owner_id=str(uuid.uuid4()),
            )
            assert doc is not None
        except HTTPException as exc:
            assert exc.status_code != 413, f"1 MB upload should not trigger 413 with 100 MB cap, got {exc.status_code}"


# ---------------------------------------------------------------------------
# Per-page text extraction budget
# ---------------------------------------------------------------------------


class TestTextExtractionBudget:
    """Verify the extracted text from many pages is bounded in memory."""

    @pytest.mark.asyncio
    async def test_50_page_pdf_text_stays_bounded(self, monkeypatch, tmp_path) -> None:
        """A 50-page PDF with 1 KB text per page should produce <= 100 KB total."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "200")
        monkeypatch.setattr(
            takeoff_service,
            "_TAKEOFF_DOCUMENTS_DIR",
            tmp_path / "td",
        )

        # Stub the page extractor to return 50 pages with 1 KB each.
        page_text = "A" * 1024  # 1 KB per page
        fake_page_data = [{"page": i + 1, "text": page_text, "tables": []} for i in range(50)]

        monkeypatch.setattr(takeoff_service, "_count_pdf_pages", lambda *a, **k: 50)
        monkeypatch.setattr(
            takeoff_service,
            "_extract_pdf_pages",
            lambda *a, **k: fake_page_data,
        )

        class _AwaitableCreate:
            def __init__(self):
                self.persisted_doc = None

            async def create(self, doc):
                self.persisted_doc = doc
                return doc

        repo = _AwaitableCreate()
        svc = _make_service()
        svc.repo = repo

        payload = b"%PDF-1.4\n" + b"x" * (10 * 1024)  # small payload since parser is stubbed
        doc = await svc.upload_document(
            filename="big.pdf",
            content=payload,
            size_bytes=len(payload),
            owner_id=str(uuid.uuid4()),
        )

        # The full_text should be ≤ 50 pages * 1 KB + separators, not 500 MB.
        text_size = len(doc.extracted_text or "")
        assert text_size <= 100 * 1024, f"extracted_text is {text_size} bytes — should be ≤ 100 KB for 50×1 KB pages"

    def test_cap_returns_correct_byte_count(self, monkeypatch) -> None:
        """_max_upload_bytes() returns correct byte count for env var."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "100")
        assert _max_upload_bytes() == 100 * 1024 * 1024

    def test_cap_zero_means_unlimited(self, monkeypatch) -> None:
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "0")
        assert _max_upload_bytes() == 0

    def test_cap_absent_means_unlimited(self, monkeypatch) -> None:
        monkeypatch.delenv("OE_TAKEOFF_MAX_UPLOAD_MB", raising=False)
        assert _max_upload_bytes() == 0


# ---------------------------------------------------------------------------
# Large page count does not cause unreasonable string construction
# ---------------------------------------------------------------------------


class TestLargePageCountMemorySafety:
    """Regression: ensure the text join is not building a pathological string."""

    @pytest.mark.asyncio
    async def test_100_pages_do_not_exhaust_memory(self, monkeypatch, tmp_path) -> None:
        """100 pages with 2 KB text each → total string ≤ 250 KB (+ separators)."""
        monkeypatch.setattr(
            takeoff_service,
            "_TAKEOFF_DOCUMENTS_DIR",
            tmp_path / "td",
        )

        page_text = "B" * 2048  # 2 KB per page
        fake_page_data = [{"page": i + 1, "text": page_text, "tables": []} for i in range(100)]

        monkeypatch.setattr(takeoff_service, "_count_pdf_pages", lambda *a, **k: 100)
        monkeypatch.setattr(
            takeoff_service,
            "_extract_pdf_pages",
            lambda *a, **k: fake_page_data,
        )

        class _AwaitableCreate:
            async def create(self, doc):
                return doc

        svc = _make_service()
        svc.repo = _AwaitableCreate()

        payload = b"%PDF-1.4\n" + b"stub"
        doc = await svc.upload_document(
            filename="hundred.pdf",
            content=payload,
            size_bytes=len(payload),
            owner_id=str(uuid.uuid4()),
        )
        text_size = len(doc.extracted_text or "")
        # 100 pages * 2 KB = 200 KB + 99 * 2-char separators ≈ 200.2 KB
        # We allow up to 300 KB as headroom.
        assert text_size <= 300 * 1024, f"extracted_text is {text_size} bytes — unexpectedly large for 100×2 KB pages"
