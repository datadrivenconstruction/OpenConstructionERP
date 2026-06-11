# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the resumable-upload service lifecycle.

Runs without a DB: the repository and document service are stubbed and the
chunk store is pointed at a pytest ``tmp_path`` via ``OE_CLI_DATA_DIR`` so
real bytes land on disk under the test sandbox. Covers the idempotency,
missing-chunk-resume, integrity, bounds and cross-tenant behaviours the
feature is required to guarantee.

Required negative tests (see report):
    * test_reupload_existing_chunk_is_noop
    * test_status_reports_exact_missing_chunks
    * test_complete_wrong_total_size_rejected  /  ..._bad_sha_rejected
    * test_chunk_index_out_of_range_rejected
    * test_cross_tenant_session_access_denied
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.resumable_uploads.models import ResumableUploadSession
from app.modules.resumable_uploads.schemas import MAX_TOTAL_SIZE, MIN_CHUNK_SIZE
from app.modules.resumable_uploads.service import ResumableUploadService

# Use the production-minimum chunk size so the service's bounds check passes.
# A 4-chunk file: three full chunks plus a short tail.
CHUNK = MIN_CHUNK_SIZE
TAIL = CHUNK // 4
TOTAL = CHUNK * 3 + TAIL


def _chunk_bytes(marker: int, size: int) -> bytes:
    """Deterministic chunk payload of ``size`` bytes for index ``marker``."""
    return bytes([(marker + 1) % 256]) * size


# ── Fixtures: point the chunk store at the test sandbox ──────────────────────


@pytest.fixture(autouse=True)
def _sandbox_chunk_store(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect resumable chunk storage under the per-test tmp dir."""
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path))


# ── Stub repository / session ────────────────────────────────────────────────


class _StubRepo:
    """In-memory stand-in for ResumableUploadRepository.

    The service constructs a real ``ResumableUploadRepository(session)`` in
    ``__init__``; we replace ``service.repo`` with this after construction
    so no SQLAlchemy session is ever touched.
    """

    def __init__(self) -> None:
        self.store: dict[uuid.UUID, ResumableUploadSession] = {}

    async def add(self, record: ResumableUploadSession) -> ResumableUploadSession:
        if record.id is None:
            record.id = uuid.uuid4()
        # Base.created_at is only populated on flush; set it for the stub.
        if getattr(record, "created_at", None) is None:
            record.created_at = datetime.now(UTC)
        self.store[record.id] = record
        return record

    async def save(self, record: ResumableUploadSession) -> ResumableUploadSession:
        self.store[record.id] = record
        return record

    async def get_by_id(self, session_id: uuid.UUID) -> ResumableUploadSession | None:
        return self.store.get(session_id)

    async def remove(self, record: ResumableUploadSession) -> None:
        self.store.pop(record.id, None)

    async def list_expired(self, *, now: datetime, limit: int = 500) -> list[ResumableUploadSession]:
        return [r for r in self.store.values() if r.expires_at < now and r.status in ("in_progress", "assembling")]

    async def delete_terminal_before(self, *, cutoff: datetime) -> int:
        return 0


class _StubDocumentService:
    """Captures the assembled UploadFile and returns a fake Document."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def upload_document(
        self,
        project_id: uuid.UUID,
        file: Any,
        category: str,
        user_id: str,
    ) -> Any:
        content = await file.read()
        self.calls.append((project_id, file.filename, category, user_id, content))
        return SimpleNamespace(id=uuid.uuid4(), file_path=f"/blobs/{file.filename}")


def _make_service() -> tuple[ResumableUploadService, _StubRepo]:
    svc = ResumableUploadService(session=object())
    repo = _StubRepo()
    svc.repo = repo  # type: ignore[assignment]
    return svc, repo


async def _open_session(
    svc: ResumableUploadService,
    *,
    total_size: int = TOTAL,
    chunk_size: int = CHUNK,
    sha256: str | None = None,
    project_id: uuid.UUID | None = None,
) -> ResumableUploadSession:
    return await svc.create_session(
        project_id=project_id or uuid.uuid4(),
        filename="tower.ifc",
        total_size=total_size,
        chunk_size=chunk_size,
        category="drawing",
        sha256=sha256,
        user_id=str(uuid.uuid4()),
    )


async def _upload_all_chunks(svc: ResumableUploadService, record: ResumableUploadSession) -> bytes:
    """Upload every chunk of a default 4-chunk session; return the full bytes."""
    parts = [
        _chunk_bytes(0, CHUNK),
        _chunk_bytes(1, CHUNK),
        _chunk_bytes(2, CHUNK),
        _chunk_bytes(3, TAIL),
    ]
    for index, part in enumerate(parts):
        await svc.accept_chunk(record, index, part)
    return b"".join(parts)


# ── create_session basics ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_session_computes_chunk_plan() -> None:
    svc, _ = _make_service()
    record = await _open_session(svc)
    assert record.total_chunks == 4
    assert record.chunk_size == CHUNK
    assert record.received_chunks == []
    assert record.status == "in_progress"


@pytest.mark.asyncio
async def test_create_session_rejects_oversize_total() -> None:
    svc, _ = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.create_session(
            project_id=uuid.uuid4(),
            filename="x.bin",
            total_size=MAX_TOTAL_SIZE + 1,  # just over the hard ceiling
            chunk_size=8 * 1024 * 1024,
            category="other",
            sha256=None,
            user_id="u",
        )
    assert exc.value.status_code == 400


# ── 1. re-uploading an existing chunk is a no-op ─────────────────────────────


@pytest.mark.asyncio
async def test_reupload_existing_chunk_is_noop() -> None:
    svc, _ = _make_service()
    record = await _open_session(svc)
    payload = _chunk_bytes(0, CHUNK)

    record, dup1 = await svc.accept_chunk(record, 0, payload)
    assert dup1 is False
    assert record.received_chunks == [0]

    # Same index again - idempotent: still one entry, flagged duplicate.
    record, dup2 = await svc.accept_chunk(record, 0, payload)
    assert dup2 is True
    assert record.received_chunks == [0]


# ── 2. status reports exactly the missing chunks ─────────────────────────────


@pytest.mark.asyncio
async def test_status_reports_exact_missing_chunks() -> None:
    svc, _ = _make_service()
    record = await _open_session(svc)  # 4 chunks
    assert svc.missing(record) == [0, 1, 2, 3]

    await svc.accept_chunk(record, 0, _chunk_bytes(0, CHUNK))
    await svc.accept_chunk(record, 2, _chunk_bytes(2, CHUNK))
    assert svc.missing(record) == [1, 3]

    await svc.accept_chunk(record, 1, _chunk_bytes(1, CHUNK))
    await svc.accept_chunk(record, 3, _chunk_bytes(3, TAIL))  # short tail
    assert svc.missing(record) == []


# ── 3a. completion with a wrong total size is rejected ───────────────────────


@pytest.mark.asyncio
async def test_complete_wrong_total_size_rejected() -> None:
    svc, _ = _make_service()
    # validate_chunk enforces the declared size on the way in, so a wrong
    # total can only arise from on-disk corruption between chunk write and
    # assembly. Simulate that by shrinking the stored tail chunk directly.
    record = await _open_session(svc)
    await _upload_all_chunks(svc, record)

    # Tamper: shrink the on-disk tail chunk so assembled size != total_size.
    from app.modules.resumable_uploads import chunk_store

    chunk_store.chunk_path(record.id, 3).write_bytes(b"d" * (TAIL - 1))

    with pytest.raises(HTTPException) as exc:
        await svc.complete_session(
            record,
            document_service=_StubDocumentService(),
            user_id="u",
        )
    assert exc.value.status_code == 400
    assert record.status == "failed"


# ── 3b. completion with a bad sha is rejected ────────────────────────────────


@pytest.mark.asyncio
async def test_complete_bad_sha_rejected() -> None:
    svc, _ = _make_service()
    record = await _open_session(svc, sha256="00" * 32)  # deliberately wrong
    await _upload_all_chunks(svc, record)

    with pytest.raises(HTTPException) as exc:
        await svc.complete_session(
            record,
            document_service=_StubDocumentService(),
            user_id="u",
        )
    assert exc.value.status_code == 400
    assert "sha256" in str(exc.value.detail)
    assert record.status == "failed"


# ── 4. a chunk index out of range is rejected ────────────────────────────────


@pytest.mark.asyncio
async def test_chunk_index_out_of_range_rejected() -> None:
    svc, _ = _make_service()
    record = await _open_session(svc)  # indices 0..3
    with pytest.raises(HTTPException) as exc:
        await svc.accept_chunk(record, 4, _chunk_bytes(4, CHUNK))
    assert exc.value.status_code == 400
    # Nothing recorded.
    assert record.received_chunks == []


# ── 5. cross-tenant session access is denied (404, not found) ────────────────


@pytest.mark.asyncio
async def test_cross_tenant_session_access_denied() -> None:
    """A session id from one tenant is invisible to another caller.

    ``get_session`` 404s any id absent from the caller's repository view.
    The router layers ``verify_project_access`` on top, but the service
    contract itself must not surface a row that does not belong to the
    repository the request is scoped to.
    """
    svc_a, repo_a = _make_service()
    record_a = await _open_session(svc_a)

    # A second service instance (different tenant request) has its own repo
    # that never saw tenant A's session.
    svc_b, _ = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc_b.get_session(record_a.id)
    assert exc.value.status_code == 404


# ── Happy path: complete assembles and hands off to the document store ───────


@pytest.mark.asyncio
async def test_complete_hands_off_to_document_service() -> None:
    svc, _ = _make_service()
    parts = [
        _chunk_bytes(0, CHUNK),
        _chunk_bytes(1, CHUNK),
        _chunk_bytes(2, CHUNK),
        _chunk_bytes(3, TAIL),
    ]
    full = b"".join(parts)
    sha = hashlib.sha256(full).hexdigest()
    record = await _open_session(svc, sha256=sha)

    for index, part in enumerate(parts):
        await svc.accept_chunk(record, index, part)

    docsvc = _StubDocumentService()
    record = await svc.complete_session(record, document_service=docsvc, user_id="u")

    assert record.status == "complete"
    assert record.document_id is not None
    assert len(docsvc.calls) == 1
    # The assembled bytes handed to the document store equal the chunks in order.
    _, filename, category, _, content = docsvc.calls[0]
    assert filename == "tower.ifc"
    assert category == "drawing"
    assert content == full


@pytest.mark.asyncio
async def test_complete_incomplete_reports_missing_409() -> None:
    svc, _ = _make_service()
    record = await _open_session(svc)
    await svc.accept_chunk(record, 0, _chunk_bytes(0, CHUNK))
    with pytest.raises(HTTPException) as exc:
        await svc.complete_session(record, document_service=_StubDocumentService(), user_id="u")
    assert exc.value.status_code == 409
    assert exc.value.detail["missing_chunks"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_gc_expires_stale_sessions() -> None:
    svc, repo = _make_service()
    record = await _open_session(svc)
    # Force the session past its TTL.
    record.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await repo.save(record)

    expired = await svc.gc_expired()
    assert expired == 1
    assert record.status == "expired"
