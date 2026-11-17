# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Scan-to-email intake: one capture per attachment, source and sender recorded, duplicates skipped.

No database: the session, storage backend and extraction are faked, so the outcome of each
worked example (two scans in one mail, the same scan sent twice, a non-invoice attachment) is
asserted exactly.
"""

from __future__ import annotations

import hashlib
import uuid
from email.message import EmailMessage
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.finance import invoice_capture_service as svc_mod
from app.modules.finance import router as _finance_router  # noqa: F401  (import order: router first)
from app.modules.finance.invoice_capture_models import CapturedInvoice
from app.modules.finance.invoice_capture_router import _to_response
from app.modules.finance.invoice_capture_service import InvoiceCaptureService
from app.modules.inbound_email.eml_parser import extract_attachment_payloads

PDF_A = b"%PDF-1.4\n% scan A\n%%EOF"
PDF_B = b"%PDF-1.4\n% scan B\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _mail(*attachments: tuple[str, str, bytes], sender: str = "Scanner <scan@office.example>") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "invoices@company.example"
    msg["Subject"] = "Scan"
    msg.set_content("Scanned documents attached.")
    for name, ctype, data in attachments:
        main, sub = ctype.split("/")
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return msg.as_bytes()


class _Storage:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def put_stream(self, key: str, _path: Any) -> None:
        self.keys.append(key)


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._row


class _Session:
    """Remembers added rows; ``execute`` answers the duplicate-hash lookup from them."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def add(self, row: Any) -> None:
        # Emulate the INSERT-time column defaults the real flush would apply.
        for col in CapturedInvoice.__table__.columns:
            if getattr(row, col.key, None) is None and col.default is not None and not col.default.is_sequence:
                arg = col.default.arg
                setattr(row, col.key, arg({}) if callable(arg) else arg)
        self.rows.append(row)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        sha = stmt.compile().params.get("content_sha256_1")
        return _Result(next((r for r in self.rows if r.content_sha256 == sha), None))


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> InvoiceCaptureService:
    storage = _Storage()
    monkeypatch.setattr(svc_mod, "get_storage_backend", lambda: storage)
    monkeypatch.setattr(InvoiceCaptureService, "_extract", lambda _s, _p, _m: ("none", "", {}, {}))

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(InvoiceCaptureService, "_resolve_po_reference", _noop)
    monkeypatch.setattr(InvoiceCaptureService, "_log", _noop)
    s = InvoiceCaptureService.__new__(InvoiceCaptureService)
    s.session = _Session()
    return s


def test_payloads_are_extracted_with_name_type_and_bytes() -> None:
    got = extract_attachment_payloads(_mail(("a.pdf", "application/pdf", PDF_A), ("b.png", "image/png", PNG)))
    assert [(n, t, d) for n, t, d in got] == [
        ("a.pdf", "application/pdf", PDF_A),
        ("b.png", "image/png", PNG),
    ]


def test_garbage_input_yields_no_payloads() -> None:
    assert extract_attachment_payloads(b"") == []


@pytest.mark.asyncio
async def test_two_scans_in_one_mail_make_two_email_captures(service: InvoiceCaptureService) -> None:
    project = uuid.uuid4()
    raw = _mail(("a.pdf", "application/pdf", PDF_A), ("b.png", "image/png", PNG))
    out = await service.capture_from_email(project_id=project, raw=raw, user_id=None)

    assert out["sender"] == "scan@office.example"
    assert len(out["created"]) == 2 and not out["duplicates"] and not out["rejected"]
    first = out["created"][0]
    assert first.status == "captured"  # fields stay suggestions until a human confirms
    assert first.content_sha256 == hashlib.sha256(PDF_A).hexdigest()
    assert first.original_filename == "a.pdf" and first.storage_key
    resp = _to_response(first)
    assert (resp.source, resp.source_sender, resp.has_document) == ("email", "scan@office.example", True)


@pytest.mark.asyncio
async def test_the_same_scan_sent_twice_is_skipped(service: InvoiceCaptureService) -> None:
    project = uuid.uuid4()
    raw = _mail(("a.pdf", "application/pdf", PDF_A))
    first = await service.capture_from_email(project_id=project, raw=raw, user_id=None)
    again = await service.capture_from_email(project_id=project, raw=raw, user_id=None)

    assert len(first["created"]) == 1
    assert again["created"] == [] and len(again["duplicates"]) == 1
    assert again["duplicates"][0].id == first["created"][0].id
    assert len(service.session.rows) == 1


@pytest.mark.asyncio
async def test_same_bytes_twice_in_one_mail_count_once(service: InvoiceCaptureService) -> None:
    raw = _mail(("a.pdf", "application/pdf", PDF_A), ("copy.pdf", "application/pdf", PDF_A))
    out = await service.capture_from_email(project_id=uuid.uuid4(), raw=raw, user_id=None)
    assert len(out["created"]) == 1 and not out["duplicates"]


@pytest.mark.asyncio
async def test_a_non_invoice_attachment_is_reported_not_captured(service: InvoiceCaptureService) -> None:
    raw = _mail(
        ("tool.exe", "application/octet-stream", b"MZ\x90\x00" + b"\x00" * 20), ("b.pdf", "application/pdf", PDF_B)
    )
    out = await service.capture_from_email(project_id=uuid.uuid4(), raw=raw, user_id=None)
    assert [c.original_filename for c in out["created"]] == ["b.pdf"]
    assert [r["filename"] for r in out["rejected"]] == ["tool.exe"]


@pytest.mark.asyncio
async def test_camera_upload_records_its_source(service: InvoiceCaptureService) -> None:
    import io

    from fastapi import UploadFile

    row = await service.capture_from_upload(
        project_id=uuid.uuid4(),
        file=UploadFile(file=io.BytesIO(PNG), filename="shot.png"),
        user_id=None,
        source="camera",
    )
    assert _to_response(row).source == "camera"


def test_unknown_source_falls_back_to_upload() -> None:
    assert svc_mod._source_metadata("fax", None) == {"source": "upload"}
    assert SimpleNamespace(**svc_mod._source_metadata("email", "a@b.c")).sender == "a@b.c"
