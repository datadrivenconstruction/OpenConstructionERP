"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG contract tests for ``resumable_uploads``: chunk order, replay, and integrity.

The module had zero coverage. Its entire reason to exist is surviving an
interrupted upload, so the tests concentrate on the paths an interruption
actually produces: chunks arriving out of order, a chunk replayed after a
dropped connection, a chunk that does not match the size the session
contracted for, a session resumed from a partial state, and the SHA-256 gate
that decides whether the assembled bytes are the file the client meant to send.

Why this lane
~~~~~~~~~~~~~
``tests/pg`` is the only suite the *CI (PostgreSQL)* workflow runs, so it is
the only place a test can block a merge. ``received_chunks`` is also a JSON
column read back as a list, which is a dialect behaviour worth exercising on a
real cluster.

Two seams keep this fast and hermetic:

* ``OE_CLI_DATA_DIR`` is redirected per test. ``chunk_store._resumable_base_dir``
  reads it at call time, so without this the tests would write into the
  developer's real ``~/.openestimator`` and leak chunks between runs.
* Sessions for the chunk/disk tests are constructed directly with a tiny
  ``chunk_size``. ``create_session`` cannot produce one - ``MIN_CHUNK_SIZE`` is
  256 KiB - and a suite that moved a quarter megabyte per chunk would be slow
  for no extra coverage. ``create_session`` is still exercised on its own for
  the bounds it enforces.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.resumable_uploads import chunk_store
from app.modules.resumable_uploads.chunking import (
    ChunkValidationError,
    compute_total_chunks,
    expected_chunk_size,
    validate_chunk,
    verify_assembled,
)
from app.modules.resumable_uploads.models import ResumableUploadSession
from app.modules.resumable_uploads.service import ResumableUploadService
from app.modules.users.models import User

CHUNK_SIZE = 1024
# Three chunks with a short final one, so "every chunk is chunk_size" is wrong
# and an off-by-one in the last-chunk arithmetic has somewhere to show.
TOTAL_SIZE = CHUNK_SIZE * 2 + 300


def _payload(total_size: int = TOTAL_SIZE) -> bytes:
    """Deterministic body whose every chunk differs from every other."""
    return bytes((i * 7 + 11) % 256 for i in range(total_size))


def _slice(body: bytes, index: int, chunk_size: int = CHUNK_SIZE) -> bytes:
    return body[index * chunk_size : (index + 1) * chunk_size]


@pytest.fixture(autouse=True)
def _isolated_chunk_root(tmp_path, monkeypatch) -> None:
    """Point the chunk store at a throwaway directory for every test."""
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_DIR", raising=False)


async def _make_project(session: AsyncSession) -> Project:
    """Insert the owner + project an upload session's FK requires."""
    owner = User(
        email=f"upload-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        full_name="Upload Tester",
    )
    session.add(owner)
    await session.flush()
    project = Project(name=f"Upload project {uuid.uuid4().hex[:6]}", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project


async def _make_upload_session(
    session: AsyncSession,
    *,
    total_size: int = TOTAL_SIZE,
    chunk_size: int = CHUNK_SIZE,
    sha256: str | None = None,
    received: list[int] | None = None,
    status: str = "in_progress",
) -> ResumableUploadSession:
    """Persist an upload session with a test-sized chunk plan."""
    project = await _make_project(session)
    record = ResumableUploadSession(
        project_id=project.id,
        filename="drawing.pdf",
        category="other",
        total_size=total_size,
        chunk_size=chunk_size,
        total_chunks=compute_total_chunks(total_size, chunk_size),
        received_chunks=list(received or []),
        sha256=sha256,
        status=status,
        created_by=str(project.owner_id),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(record)
    await session.flush()
    return record


class _FakeDocument:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.file_path = "documents/assembled.pdf"


class _RecordingDocumentService:
    """Stands in for ``DocumentService`` and keeps the bytes it was handed.

    Completion hands the assembled file to the real documents pipeline, which
    would drag in the magic-byte gate, storage and the conversion chain. What
    these tests need to know is narrower and sharper: exactly which bytes came
    out of assembly, in which order.
    """

    def __init__(self) -> None:
        self.received: bytes | None = None
        self.calls = 0

    async def upload_document(self, project_id, file, category, user_id) -> _FakeDocument:  # noqa: ANN001
        self.calls += 1
        self.received = file.file.read()
        return _FakeDocument()


# ── Chunk math (pure, no DB) ───────────────────────────────────────────────


def test_the_last_chunk_carries_the_remainder_not_a_full_chunk() -> None:
    """Chunk sizing is exact per index, so a partial tail is contracted, not tolerated."""
    total_chunks = compute_total_chunks(TOTAL_SIZE, CHUNK_SIZE)
    assert total_chunks == 3
    assert expected_chunk_size(0, total_size=TOTAL_SIZE, chunk_size=CHUNK_SIZE, total_chunks=3) == CHUNK_SIZE
    assert expected_chunk_size(1, total_size=TOTAL_SIZE, chunk_size=CHUNK_SIZE, total_chunks=3) == CHUNK_SIZE
    assert expected_chunk_size(2, total_size=TOTAL_SIZE, chunk_size=CHUNK_SIZE, total_chunks=3) == 300


def test_an_evenly_dividing_file_has_a_full_final_chunk() -> None:
    """The remainder branch must not turn a clean division into a zero-length tail."""
    total = CHUNK_SIZE * 4
    assert compute_total_chunks(total, CHUNK_SIZE) == 4
    assert expected_chunk_size(3, total_size=total, chunk_size=CHUNK_SIZE, total_chunks=4) == CHUNK_SIZE


def test_a_checksum_is_only_enforced_when_the_client_supplied_one() -> None:
    """Size is always checked; SHA-256 is opt-in and compared case-insensitively."""
    digest = hashlib.sha256(b"abc").hexdigest()
    assert verify_assembled(assembled_size=3, expected_size=3, computed_sha256=digest, expected_sha256=None).ok
    assert verify_assembled(
        assembled_size=3, expected_size=3, computed_sha256=digest, expected_sha256=digest.upper()
    ).ok
    mismatch = verify_assembled(assembled_size=3, expected_size=3, computed_sha256=digest, expected_sha256="0" * 64)
    assert not mismatch.ok
    assert mismatch.reason == "sha256 mismatch"
    wrong_size = verify_assembled(assembled_size=4, expected_size=3, computed_sha256=digest, expected_sha256=digest)
    assert not wrong_size.ok, "a size mismatch must fail even when the hash was never supplied"


@pytest.mark.parametrize("bad_index", [-1, 3, 99])
def test_an_index_outside_the_chunk_plan_is_rejected(bad_index: int) -> None:
    with pytest.raises(ChunkValidationError):
        validate_chunk(bad_index, CHUNK_SIZE, total_size=TOTAL_SIZE, chunk_size=CHUNK_SIZE, total_chunks=3)


# ── Chunk acceptance ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chunks_arriving_out_of_order_assemble_in_index_order(pg_session) -> None:
    """Order of arrival must not decide order on disk.

    The checksum is what makes this test strict: a server that concatenated in
    arrival order would still produce the right byte count and the right chunk
    set, and would pass every assertion except this one.
    """
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)

    for index in (2, 0, 1):
        _, duplicate = await service.accept_chunk(record, index, _slice(body, index))
        assert duplicate is False

    assert service.missing(record) == []

    documents = _RecordingDocumentService()
    completed = await service.complete_session(record, document_service=documents, user_id="tester")

    assert completed.status == "complete"
    assert documents.received == body, "assembly must follow chunk index, not arrival order"


@pytest.mark.asyncio
async def test_replaying_a_chunk_is_a_no_op_that_cannot_corrupt_the_file(pg_session) -> None:
    """A retried chunk is acknowledged without rewriting - even if the bytes differ.

    A dropped connection makes clients resend, and the resend is not always
    byte-identical (a buggy client, a shifted read offset). The contract is that
    the first accepted copy wins, so the replay must change nothing on disk.
    """
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)

    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))

    poison = bytes(255 - b for b in _slice(body, 1))
    assert poison != _slice(body, 1)
    _, duplicate = await service.accept_chunk(record, 1, poison)

    assert duplicate is True, "a chunk already received must be reported as a replay"
    assert sorted(record.received_chunks) == [0, 1, 2], "a replay must not change the received set"

    documents = _RecordingDocumentService()
    await service.complete_session(record, document_service=documents, user_id="tester")
    assert documents.received == body, "the replayed bytes must never reach the assembled file"


@pytest.mark.asyncio
async def test_a_chunk_that_overruns_the_declared_size_is_rejected(pg_session) -> None:
    """The LAST chunk is where an off-by-one hides: it is contracted to 300 bytes, not 1024."""
    body = _payload()
    record = await _make_upload_session(pg_session)
    service = ResumableUploadService(pg_session)

    # A full-size body for the short tail: an implementation that only checked
    # "not larger than chunk_size" would wave this through and overrun the file.
    with pytest.raises(HTTPException) as excinfo:
        await service.accept_chunk(record, 2, _slice(body, 0))
    assert excinfo.value.status_code == 400
    assert "expected 300" in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as overrun:
        await service.accept_chunk(record, 0, _slice(body, 0) + b"extra")
    assert overrun.value.status_code == 400

    assert record.received_chunks == [], "a rejected chunk must not be recorded as received"
    assert not chunk_store.has_chunk(record.id, 0), "a rejected chunk must not reach the disk"


@pytest.mark.asyncio
async def test_an_undersized_or_empty_chunk_is_rejected(pg_session) -> None:
    """A truncated body is the classic interrupted-transfer artefact."""
    body = _payload()
    record = await _make_upload_session(pg_session)
    service = ResumableUploadService(pg_session)

    with pytest.raises(HTTPException) as short:
        await service.accept_chunk(record, 0, _slice(body, 0)[:-1])
    assert short.value.status_code == 400

    with pytest.raises(HTTPException) as empty:
        await service.accept_chunk(record, 0, b"")
    assert empty.value.status_code == 400
    assert record.received_chunks == []


# ── Resume ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_session_resumed_after_an_interruption_only_needs_its_gaps(pg_session) -> None:
    """Resume is the feature: report the gaps, accept only those, then complete.

    The session is reloaded from the database between the two halves, so the
    resume decision is made from persisted state rather than from an object the
    first half happened to leave in memory.
    """
    body = _payload()
    digest = hashlib.sha256(body).hexdigest()
    record = await _make_upload_session(pg_session, sha256=digest)
    session_id = record.id
    service = ResumableUploadService(pg_session)

    # First attempt: chunk 0 lands, then the connection drops.
    await service.accept_chunk(record, 0, _slice(body, 0))
    assert service.missing(record) == [1, 2]

    # The client comes back later and asks what is still outstanding.
    pg_session.expire_all()
    resumed = await service.get_session(session_id)
    assert sorted(resumed.received_chunks) == [0], "the landed chunk must have survived in the database"
    assert service.missing(resumed) == [1, 2]

    for index in service.missing(resumed):
        _, duplicate = await service.accept_chunk(resumed, index, _slice(body, index))
        assert duplicate is False, "a genuinely missing chunk must not be mistaken for a replay"

    documents = _RecordingDocumentService()
    completed = await service.complete_session(resumed, document_service=documents, user_id="tester")
    assert completed.status == "complete"
    assert documents.received == body


@pytest.mark.asyncio
async def test_completing_an_incomplete_upload_reports_exactly_which_chunks_are_missing(pg_session) -> None:
    """The 409 has to carry the gap list, otherwise the client cannot resume."""
    body = _payload()
    record = await _make_upload_session(pg_session)
    service = ResumableUploadService(pg_session)
    await service.accept_chunk(record, 1, _slice(body, 1))

    documents = _RecordingDocumentService()
    with pytest.raises(HTTPException) as excinfo:
        await service.complete_session(record, document_service=documents, user_id="tester")

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["missing_chunks"] == [0, 2]
    assert documents.calls == 0, "an incomplete upload must never reach the document store"
    assert record.status == "in_progress", "a refused completion must leave the session resumable"


# ── Integrity ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_checksum_mismatch_fails_the_session_and_stores_nothing(pg_session) -> None:
    """Right size, wrong bytes: only the hash can tell, and it must stop the hand-off."""
    body = _payload()
    corrupted = bytes(255 - b for b in body)
    assert len(corrupted) == len(body)

    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(corrupted, index))

    documents = _RecordingDocumentService()
    with pytest.raises(HTTPException) as excinfo:
        await service.complete_session(record, document_service=documents, user_id="tester")

    assert excinfo.value.status_code == 400
    assert "sha256 mismatch" in str(excinfo.value.detail)
    assert documents.calls == 0, "corrupt bytes must never be handed to the document store"
    assert record.status == "failed"
    assert record.document_id is None

    # The in-memory object above only proves the service assigned the field. Read
    # the columns back to prove the failure was actually flushed: if it were not,
    # a client polling the session would still see it as uploading and keep
    # retrying a hand-off that can never succeed. Selecting columns rather than
    # the entity is what makes this a real query - and note there is deliberately
    # no expire_all() here, since that would expire ``record`` too and turn the
    # ``record.id`` below into a synchronous lazy refresh (MissingGreenlet).
    record_id = record.id
    persisted = (
        await pg_session.execute(
            select(ResumableUploadSession.status, ResumableUploadSession.document_id).where(
                ResumableUploadSession.id == record_id
            )
        )
    ).one()
    assert persisted.status == "failed", "the failed status must survive as a row, not just in memory"
    assert persisted.document_id is None


@pytest.mark.asyncio
async def test_a_completed_session_is_not_uploaded_twice_on_replay(pg_session) -> None:
    """A retried complete must be idempotent, not a second document."""
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))

    documents = _RecordingDocumentService()
    first = await service.complete_session(record, document_service=documents, user_id="tester")
    second = await service.complete_session(record, document_service=documents, user_id="tester")

    assert documents.calls == 1, "replaying complete must not create a second document"
    assert second.document_id == first.document_id


@pytest.mark.asyncio
async def test_a_finished_session_stops_accepting_chunks(pg_session) -> None:
    """Once terminal, the session is closed: late chunks must not reopen it."""
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))
    await service.complete_session(record, document_service=_RecordingDocumentService(), user_id="tester")

    with pytest.raises(HTTPException) as excinfo:
        await service.accept_chunk(record, 0, _slice(body, 0))
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_completion_clears_the_scratch_chunks(pg_session) -> None:
    """Scratch state must not outlive the upload it belonged to."""
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))
    assert chunk_store.has_chunk(record.id, 0)

    await service.complete_session(record, document_service=_RecordingDocumentService(), user_id="tester")

    for index in range(3):
        assert not chunk_store.has_chunk(record.id, index), "assembled chunks must be cleaned up"


@pytest.mark.asyncio
async def test_aborting_removes_both_the_row_and_the_chunks(pg_session) -> None:
    """Abort is the user's escape hatch; it must not leave the row or the bytes behind."""
    body = _payload()
    record = await _make_upload_session(pg_session)
    session_id = record.id
    service = ResumableUploadService(pg_session)
    await service.accept_chunk(record, 0, _slice(body, 0))
    assert chunk_store.has_chunk(session_id, 0)

    await service.abort_session(record)

    assert not chunk_store.has_chunk(session_id, 0)
    # A column select, not session.get(): the latter answers from the identity
    # map and would still report the deleted row as present.
    found = await pg_session.execute(select(ResumableUploadSession.id).where(ResumableUploadSession.id == session_id))
    assert found.one_or_none() is None


# ── Losing a chunk file: the resume path that does not resume ──────────────


@pytest.mark.asyncio
async def test_a_chunk_lost_from_disk_can_be_re_uploaded(pg_session) -> None:
    """Re-sending a chunk whose bytes vanished must actually restore them."""
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))

    # The bytes disappear while the database still records the chunk as received.
    chunk_store.chunk_path(record.id, 1).unlink()
    assert not chunk_store.has_chunk(record.id, 1)

    _, duplicate = await service.accept_chunk(record, 1, _slice(body, 1))

    assert duplicate is False, "a chunk that is no longer on disk is not a replay"
    assert chunk_store.has_chunk(record.id, 1), "re-uploading must put the bytes back"


@pytest.mark.asyncio
async def test_completing_with_a_chunk_missing_from_disk_is_reported_not_crashed(pg_session) -> None:
    """A lost chunk must surface as a resumable error, not an unhandled exception."""
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))

    chunk_store.chunk_path(record.id, 1).unlink()

    documents = _RecordingDocumentService()
    with pytest.raises(HTTPException) as excinfo:
        await service.complete_session(record, document_service=documents, user_id="tester")

    assert excinfo.value.status_code in (400, 409)
    assert documents.calls == 0


@pytest.mark.asyncio
async def test_an_upload_that_loses_a_chunk_resends_only_that_chunk(pg_session) -> None:
    """The point of the two tests above, end to end: one lost part costs one part.

    Each half is useless alone. Reporting the gap does not help if the resend is
    refused as a replay, and accepting the resend does not help if the refusal
    already deleted every other chunk.
    """
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))

    chunk_store.chunk_path(record.id, 1).unlink()

    documents = _RecordingDocumentService()
    with pytest.raises(HTTPException) as refused:
        await service.complete_session(record, document_service=documents, user_id="tester")

    assert refused.value.status_code == 409
    assert refused.value.detail["missing_chunks"] == [1]
    assert record.received_chunks == [0, 2], "the session must stop claiming a chunk it lost"
    assert record.status == "in_progress", "a resumable refusal must leave the session resumable"
    # The parts still on disk have to survive the refusal, otherwise losing one
    # scratch file costs the client the whole body again.
    assert chunk_store.has_chunk(record.id, 0)
    assert chunk_store.has_chunk(record.id, 2)

    await service.accept_chunk(record, 1, _slice(body, 1))
    await service.complete_session(record, document_service=documents, user_id="tester")

    assert documents.calls == 1
    assert documents.received == body, "the resumed upload must assemble the original bytes"
    assert record.status == "complete"


@pytest.mark.asyncio
async def test_status_reports_a_chunk_whose_bytes_are_gone(pg_session) -> None:
    """The status endpoint's gap list is what a resuming client acts on.

    Answering it from ``received_chunks`` alone claims a completeness the chunk
    store cannot deliver, which strands a polling client: nothing to send, and
    a completion that keeps refusing.
    """
    body = _payload()
    record = await _make_upload_session(pg_session)
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))
    assert service.missing(record) == []

    chunk_store.chunk_path(record.id, 2).unlink()

    assert service.missing(record) == [2]


@pytest.mark.asyncio
async def test_status_does_not_call_a_finished_upload_incomplete(pg_session) -> None:
    """Completion sweeps the scratch chunks on purpose.

    Asking the disk about a session that already finished would report every
    chunk as missing and invite a client to re-upload a stored file.
    """
    body = _payload()
    record = await _make_upload_session(pg_session, sha256=hashlib.sha256(body).hexdigest())
    service = ResumableUploadService(pg_session)
    for index in range(3):
        await service.accept_chunk(record, index, _slice(body, index))
    await service.complete_session(record, document_service=_RecordingDocumentService(), user_id="tester")

    assert record.status == "complete"
    assert not chunk_store.has_chunk(record.id, 0), "the scratch chunks are gone by design"
    assert service.missing(record) == []


# ── Session creation bounds ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_session_rejects_a_chunk_plan_it_cannot_serve(pg_session) -> None:
    """The bounds are re-asserted in the service, not left to the request schema."""
    project = await _make_project(pg_session)
    service = ResumableUploadService(pg_session)

    with pytest.raises(HTTPException) as too_small:
        await service.create_session(
            project_id=project.id,
            filename="a.pdf",
            total_size=1024,
            chunk_size=16,
            category="other",
            sha256=None,
            user_id=str(project.owner_id),
        )
    assert too_small.value.status_code == 400

    with pytest.raises(HTTPException) as no_size:
        await service.create_session(
            project_id=project.id,
            filename="a.pdf",
            total_size=0,
            chunk_size=None,
            category="other",
            sha256=None,
            user_id=str(project.owner_id),
        )
    assert no_size.value.status_code == 400


@pytest.mark.asyncio
async def test_create_session_sanitises_the_filename_and_plans_the_chunks(pg_session) -> None:
    """A traversal-shaped name must not survive into the stored session."""
    project = await _make_project(pg_session)
    service = ResumableUploadService(pg_session)

    record = await service.create_session(
        project_id=project.id,
        filename="../../etc/passwd.pdf",
        total_size=20 * 1024 * 1024,
        chunk_size=None,
        category="drawing",
        sha256=("A" * 64),
        user_id=str(project.owner_id),
    )

    assert "/" not in record.filename and ".." not in record.filename
    assert record.total_chunks == compute_total_chunks(20 * 1024 * 1024, record.chunk_size)
    assert record.sha256 == "a" * 64, "the client hash is normalised to lower case for comparison"
    assert record.status == "in_progress"
    assert record.received_chunks == []
