"""Integration: storage multipart upload (RFC 34 §4 W0.5).

Covers the multipart_upload + presigned_put_url surface added to
:mod:`app.core.storage` for browser-direct uploads of files >100 MB.

The local backend gets full lifecycle, abort, concurrent, and resume
coverage.  The S3 backend gets a single lifecycle test guarded behind
``importlib.util.find_spec('aioboto3')`` because the optional dep is
typically not installed in the dev environment.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.storage import (
    LocalStorageBackend,
    MultipartSession,
    PartInfo,
    PresignedUrl,
    StorageObject,
    _verify_local_upload_token,
)

pytestmark = pytest.mark.integration


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalStorageBackend:
    """Fresh LocalStorageBackend rooted at a per-test tmpdir."""
    return LocalStorageBackend(tmp_path)


def _random_block(size: int) -> bytes:
    """5 MiB of random data — but seeded per call so tests stay
    reproducible enough to compare hashes between sub-steps."""
    return secrets.token_bytes(size)


# ── 1. Full lifecycle ─────────────────────────────────────────────────────


async def test_local_multipart_full_lifecycle(local_backend: LocalStorageBackend) -> None:
    """Initiate, upload 5 parts × 5 MiB, complete, read back, verify SHA-256."""
    key = "uploads/big-file.bin"
    five_mb = 5 * 1024 * 1024
    chunks = [_random_block(five_mb) for _ in range(5)]
    full_payload = b"".join(chunks)
    expected_sha = hashlib.sha256(full_payload).hexdigest()

    session = await local_backend.initiate_multipart(key, content_type="application/octet-stream")
    assert isinstance(session, MultipartSession)
    assert session.backend == "local"
    assert session.key == key
    assert session.upload_id  # non-empty
    assert isinstance(session.started_at, datetime)

    # Stash expected SHA in metadata so complete_multipart verifies.
    session = MultipartSession(
        upload_id=session.upload_id,
        key=session.key,
        backend=session.backend,
        started_at=session.started_at,
        metadata={**session.metadata, "sha256": expected_sha},
    )

    parts: list[PartInfo] = []
    for i, chunk in enumerate(chunks, start=1):
        part = await local_backend.upload_part(session, i, chunk)
        assert part.part_number == i
        assert part.size_bytes == five_mb
        # Local backend uses sha256 hex as the etag.
        assert part.etag == hashlib.sha256(chunk).hexdigest()
        parts.append(part)

    obj = await local_backend.complete_multipart(session, parts)
    assert isinstance(obj, StorageObject)
    assert obj.key == key
    assert obj.size_bytes == 5 * five_mb
    assert obj.sha256 == expected_sha

    # Read back and re-hash to confirm bytes survived the round trip.
    read_back = await local_backend.get(key)
    assert len(read_back) == len(full_payload)
    assert hashlib.sha256(read_back).hexdigest() == expected_sha

    # Staging dir is gone.
    staging = local_backend.base_dir / ".multipart" / session.upload_id
    assert not staging.exists()


# ── 2. Abort cleans tempdir ────────────────────────────────────────────────


async def test_local_multipart_abort_cleans_tempdir(local_backend: LocalStorageBackend) -> None:
    key = "uploads/aborted.bin"
    session = await local_backend.initiate_multipart(key)
    staging = local_backend.base_dir / ".multipart" / session.upload_id
    assert staging.is_dir()

    await local_backend.upload_part(session, 1, b"some bytes")
    assert (staging / "part-00001").is_file()

    await local_backend.abort_multipart(session)
    assert not staging.exists()
    # And the canonical key was never written.
    assert not await local_backend.exists(key)


# ── 3. Concurrent part uploads ────────────────────────────────────────────


async def test_local_multipart_concurrent_parts(local_backend: LocalStorageBackend) -> None:
    """Upload 4 parts via asyncio.gather, complete, verify integrity."""
    key = "uploads/concurrent.bin"
    one_mb = 1024 * 1024  # smaller — these tests must run fast
    chunks = [_random_block(one_mb) for _ in range(4)]
    full = b"".join(chunks)

    session = await local_backend.initiate_multipart(key)

    # Send out-of-order to stress sort + concurrent writes.
    coros = [
        local_backend.upload_part(session, 3, chunks[2]),
        local_backend.upload_part(session, 1, chunks[0]),
        local_backend.upload_part(session, 4, chunks[3]),
        local_backend.upload_part(session, 2, chunks[1]),
    ]
    parts = await asyncio.gather(*coros)
    assert {p.part_number for p in parts} == {1, 2, 3, 4}

    obj = await local_backend.complete_multipart(session, parts)
    assert obj.size_bytes == 4 * one_mb

    read_back = await local_backend.get(key)
    assert read_back == full


# ── 4. Resume from a different session reference ─────────────────────────


async def test_local_multipart_resume(local_backend: LocalStorageBackend) -> None:
    """Initiate session A, upload part 1, "lose" it, reconstruct session B
    with the same upload_id, upload part 2, complete with both parts.
    """
    key = "uploads/resume.bin"
    chunk_a = b"AAAAAAAAAA" * 100  # 1 KiB
    chunk_b = b"BBBBBBBBBB" * 100

    session_a = await local_backend.initiate_multipart(key)
    part1 = await local_backend.upload_part(session_a, 1, chunk_a)

    # "Lose" the original session reference (e.g. worker restart) and
    # rebuild a session with the same upload_id from a persisted job row.
    session_b = MultipartSession(
        upload_id=session_a.upload_id,
        key=key,
        backend="local",
        started_at=session_a.started_at,
        metadata=session_a.metadata,
    )
    part2 = await local_backend.upload_part(session_b, 2, chunk_b)

    obj = await local_backend.complete_multipart(session_b, [part1, part2])
    assert obj.size_bytes == len(chunk_a) + len(chunk_b)

    read_back = await local_backend.get(key)
    assert read_back == chunk_a + chunk_b


# ── 5. Presigned PUT URL ──────────────────────────────────────────────────


async def test_local_presigned_put_url_returns_token_url(
    local_backend: LocalStorageBackend,
) -> None:
    """Returned URL is well-formed, expires_at is in the future, and the
    token can be re-verified via the helper that the (yet-to-be-built)
    router endpoint will use.
    """
    presigned = await local_backend.presigned_put_url(
        key="uploads/direct.bin",
        content_type="application/zip",
        expires_seconds=600,
    )
    assert isinstance(presigned, PresignedUrl)
    assert presigned.method == "PUT"
    assert presigned.url.startswith("/api/v1/uploads/local/")
    assert presigned.headers.get("Content-Type") == "application/zip"

    # expires_at strictly in the future.
    assert presigned.expires_at > datetime.now(UTC)

    # Token round-trips through the verifier with the right key.
    token = presigned.url.rsplit("/", 1)[-1]
    payload = _verify_local_upload_token(token)
    assert payload is not None
    assert payload["key"] == "uploads/direct.bin"
    assert payload["content_type"] == "application/zip"

    # Tampered token is rejected.
    tampered = token[:-2] + ("00" if not token.endswith("00") else "ff")
    assert _verify_local_upload_token(tampered) is None


# ── 6. SHA-256 mismatch refuses to commit ─────────────────────────────────


async def test_local_multipart_sha_mismatch_keeps_staging(
    local_backend: LocalStorageBackend,
) -> None:
    """If the caller asserts a SHA-256 that doesn't match the assembled
    payload, complete_multipart MUST raise and leave staging in place
    so the caller can retry without re-uploading the parts."""
    key = "uploads/sha-bad.bin"
    chunk = b"hello world" * 1000

    session = await local_backend.initiate_multipart(key)
    session = MultipartSession(
        upload_id=session.upload_id,
        key=session.key,
        backend=session.backend,
        started_at=session.started_at,
        metadata={"sha256": "deadbeef" * 8},  # 64 hex chars, definitely wrong
    )
    part = await local_backend.upload_part(session, 1, chunk)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        await local_backend.complete_multipart(session, [part])

    # Staging area survives so a retry is possible.
    staging = local_backend.base_dir / ".multipart" / session.upload_id
    assert staging.is_dir()
    assert (staging / "part-00001").is_file()
    # And the canonical key was NOT written.
    assert not await local_backend.exists(key)


# ── 7. S3 lifecycle (skipped without aioboto3) ────────────────────────────


@pytest.mark.skipif(
    importlib.util.find_spec("aioboto3") is None,
    reason="aioboto3 not installed (optional [s3] extra)",
)
async def test_s3_multipart_lifecycle() -> None:
    """Round-trip a multipart upload against a moto-backed S3.

    Skipped automatically if the ``aioboto3`` extra isn't available.
    Even when ``aioboto3`` is present we additionally need ``moto`` for
    the in-memory S3 server — guarded the same way.
    """
    if importlib.util.find_spec("moto") is None:
        pytest.skip("moto not installed — cannot exercise S3 in-memory")

    from moto import mock_aws  # type: ignore[import-untyped]

    from app.core.storage import S3StorageBackend

    with mock_aws():
        # moto creates the bucket lazily for many APIs but multipart
        # specifically requires it to exist.
        import boto3

        boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        ).create_bucket(Bucket="oce-test")

        backend = S3StorageBackend(
            endpoint="",
            access_key="testing",
            secret_key="testing",
            bucket="oce-test",
            region="us-east-1",
        )

        five_mb = 5 * 1024 * 1024
        chunks = [_random_block(five_mb), _random_block(1024)]  # last < 5 MiB OK

        session = await backend.initiate_multipart("multipart/object.bin")
        assert session.backend == "s3"
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            parts.append(await backend.upload_part(session, i, chunk))

        obj = await backend.complete_multipart(session, parts)
        assert obj.key == "multipart/object.bin"
        assert obj.size_bytes == sum(len(c) for c in chunks)

        # Round-trip
        read_back = await backend.get("multipart/object.bin")
        assert read_back == b"".join(chunks)

        # Presigned PUT URL is well-formed.
        presigned = await backend.presigned_put_url(
            "multipart/direct.bin", content_type="application/zip"
        )
        assert presigned.method == "PUT"
        assert "multipart/direct.bin" in presigned.url
