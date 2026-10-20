# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""OOM hardening for the match_elements file-upload endpoints.

The from-excel and from-pdf session-creation handlers used to read the whole
request body into RAM with ``await file.read()`` and had no spreadsheet-bomb
guard or PDF page cap, so a single oversized upload could OOM-kill the
single-worker container on the 3 GB target box (a decompression-bomb .xlsx and
a page-dense PDF are the same class that took down the takeoff container).

These tests pin the front-door guards added to the router, without touching the
downstream 7-stage pipeline:

* an oversized upload is streamed to a temp file, aborts past the byte cap, and
  surfaces a clean 413 (never a 500 / OOM) - proven by shrinking the cap;
* a PDF with more pages than the cap is rejected 413 before any per-page table
  extraction, and a file the PDF reader cannot open is deferred, not blocked;
* a normal .xlsx and a normal .pdf still parse to rows and reach create_session
  exactly as before (identical match semantics for good files).

Pure unit tests: no DB, no app boot. ``verify_project_access`` and
``get_service`` are stubbed so the handler runs to its guard / parse logic.
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("openpyxl")

from fastapi import HTTPException  # noqa: E402

from app.modules.match_elements import router  # noqa: E402


class _FakeUpload:
    """Minimal UploadFile stand-in: serves ``data`` in chunks via ``read``."""

    def __init__(self, data: bytes, filename: str) -> None:
        self.filename = filename
        self._buf = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Description", "Qty", "Unit"])
    ws.append(["Reinforced concrete wall C30/37", 125.5, "m3"])
    ws.append(["Formwork to walls", 410.0, "m2"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_bytes(n_pages: int) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    for _ in range(n_pages):
        c.drawString(72, 842 - 72, "Reinforced concrete wall C30 12.5 m3")
        c.showPage()
    c.save()
    return buf.getvalue()


def _stub_access_and_service(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stub the DB-touching deps; return a dict that captures the created spec."""
    monkeypatch.setattr(router, "verify_project_access", AsyncMock(return_value=None))
    captured: dict = {}

    class _Svc:
        async def create_session(self, session, spec, user_id):  # noqa: ANN001, ARG002
            captured["spec"] = spec
            return MagicMock()

    monkeypatch.setattr(router, "get_service", lambda: _Svc())
    return captured


async def _call_excel(upload: _FakeUpload):
    return await router.create_session_from_excel(
        session=AsyncMock(),
        current_user_id=str(uuid.uuid4()),
        project_id=uuid.uuid4(),
        file=upload,
        name=None,
        catalogue_id=None,
        construction_stage=None,
    )


async def _call_pdf(upload: _FakeUpload):
    return await router.create_session_from_pdf(
        session=AsyncMock(),
        current_user_id=str(uuid.uuid4()),
        project_id=uuid.uuid4(),
        file=upload,
        name=None,
        catalogue_id=None,
        construction_stage=None,
    )


# ── PDF page-count guard (direct) ─────────────────────────────────────────


def test_pdf_page_guard_rejects_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "_MAX_PDF_PAGES", 2)
    with pytest.raises(HTTPException) as exc:
        router._reject_if_too_many_pdf_pages(_pdf_bytes(5))
    assert exc.value.status_code == 413
    assert "pages" in exc.value.detail.lower()


def test_pdf_page_guard_allows_under_cap() -> None:
    router._reject_if_too_many_pdf_pages(_pdf_bytes(1))  # no raise


def test_pdf_page_guard_defers_unreadable_bytes() -> None:
    # Bytes the PDF reader cannot open must NOT be blocked here - the parser surfaces
    # its own error for unreadable content.
    router._reject_if_too_many_pdf_pages(b"not a pdf at all")  # no raise


# ── from-excel handler ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_excel_oversized_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_access_and_service(monkeypatch)
    monkeypatch.setattr(router, "_MAX_EXCEL_BYTES", 16)  # tiny cap for the test
    upload = _FakeUpload(b"PK\x03\x04" + b"\x00" * 200, "big.xlsx")
    with pytest.raises(HTTPException) as exc:
        await _call_excel(upload)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_excel_normal_file_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub_access_and_service(monkeypatch)
    await _call_excel(_FakeUpload(_xlsx_bytes(), "boq.xlsx"))
    assert "spec" in captured, "create_session was not reached for a valid .xlsx"
    assert len(captured["spec"].boq_rows) >= 2


# ── from-pdf handler ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_oversized_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_access_and_service(monkeypatch)
    monkeypatch.setattr(router, "_MAX_PDF_BYTES", 16)  # tiny cap for the test
    upload = _FakeUpload(b"%PDF-1.7\n" + b"\x00" * 200, "big.pdf")
    with pytest.raises(HTTPException) as exc:
        await _call_pdf(upload)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_pdf_too_many_pages_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_access_and_service(monkeypatch)
    monkeypatch.setattr(router, "_MAX_PDF_PAGES", 2)
    with pytest.raises(HTTPException) as exc:
        await _call_pdf(_FakeUpload(_pdf_bytes(5), "big.pdf"))
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_pdf_normal_file_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub_access_and_service(monkeypatch)
    await _call_pdf(_FakeUpload(_pdf_bytes(2), "boq.pdf"))
    assert "spec" in captured, "create_session was not reached for a valid .pdf"
    assert len(captured["spec"].pdf_rows) >= 1
