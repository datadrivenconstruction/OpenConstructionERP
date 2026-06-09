# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Tests for the presigned-direct-to-MinIO multipart ingest path.

The storage backend is mocked at the ``StorageBackend`` abstraction level (a
small in-memory fake), so these tests never need ``aioboto3`` / ``boto3`` and
never touch a real bucket - they prove the SERVICE wiring: init opens a
multipart upload and mints one presigned URL per part, complete finalises it and
flips the scan to ``uploaded``, and the back-pressure / size / contiguity guards
all fire with explanatory reason codes.

Every test uses a transaction-isolated PostgreSQL session (rolled back on
teardown) from ``tests._pg`` - never the production / shared test DB.

Coverage
--------
* test_init_ingest_opens_multipart_and_presigns_parts - init creates the scan in
  status=uploading and returns one presigned URL per part.
* test_init_ingest_part_count_tracks_size - a bigger file mints more parts.
* test_complete_ingest_finalises_and_marks_uploaded - complete calls
  CompleteMultipartUpload and flips the scan to uploaded with the stored key.
* test_complete_ingest_rejects_non_contiguous_parts - a gap in the part list is
  rejected 422 before any storage call.
* test_complete_ingest_conflicts_when_not_uploading - completing an
  already-uploaded scan returns 409.
* test_init_ingest_back_pressure_returns_429 - when the ingest gate is full the
  init endpoint sheds load with 429 instead of queueing.
* test_guard_proxied_size_caps_fallback_path - the hard max-proxied-bytes cap
  rejects an oversized proxied body with 413.
* test_init_ingest_rejects_recap - a proprietary ReCap container is rejected with
  an explanatory reason, and no multipart upload is opened.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from tests._pg import transactional_session

from app.config import get_settings
from app.core.storage import (
    MultipartSession,
    PresignedUrl,
    StorageBackend,
    StorageObject,
)
from app.modules.pointcloud.schemas import (
    AccuracyTier,
    CompletedPart,
    ScanIngestComplete,
    ScanIngestInit,
    SourceType,
)
from app.modules.pointcloud.service import (
    PointCloudService,
    guard_proxied_size,
    reset_ingest_gate,
)

# ── In-memory fake storage backend ──────────────────────────────────────────


class FakeS3Backend(StorageBackend):
    """Minimal S3-flavoured storage fake.

    Records the calls the service makes (open multipart, presign each part,
    complete) so a test can assert the wiring without aioboto3 or a real bucket.
    The class name contains ``S3`` so the service's backend-kind inference routes
    the completion through the ``"s3"`` path.
    """

    def __init__(self, *, complete_size: int = 1_500_000_000) -> None:
        self.initiated: list[str] = []
        self.presigned_parts: list[tuple[str, int]] = []
        self.completed: list[tuple[str, str, int]] = []
        self._complete_size = complete_size
        self.fail_complete = False

    # The four methods the ingest path touches.

    async def initiate_multipart(
        self,
        key: str,
        content_type: str | None = None,
    ) -> MultipartSession:
        self.initiated.append(key)
        return MultipartSession(
            upload_id="fake-upload-id",
            key=key,
            backend="s3",
            started_at=datetime.now(UTC),
            metadata={},
        )

    async def presigned_upload_part_url(
        self,
        session: MultipartSession,
        part_number: int,
        expires_seconds: int = 3600,
    ) -> PresignedUrl:
        self.presigned_parts.append((session.upload_id, part_number))
        return PresignedUrl(
            url=f"https://minio.local/{session.key}?partNumber={part_number}&uploadId={session.upload_id}",
            method="PUT",
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_seconds),
            headers={},
        )

    async def complete_multipart(self, session: MultipartSession, parts: list) -> StorageObject:  # type: ignore[type-arg]
        if self.fail_complete:
            raise ValueError("missing part 2")
        self.completed.append((session.key, session.upload_id, len(parts)))
        return StorageObject(
            key=session.key,
            size_bytes=self._complete_size,
            etag="fake-etag",
            sha256=None,
        )

    # Unused abstract surface - the ingest path never calls these.

    async def put(self, key: str, content: bytes) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def get(self, key: str) -> bytes:  # pragma: no cover - unused
        raise NotImplementedError

    async def exists(self, key: str) -> bool:  # pragma: no cover - unused
        return False

    async def delete(self, key: str) -> None:  # pragma: no cover - unused
        return None

    async def delete_prefix(self, prefix: str) -> int:  # pragma: no cover - unused
        return 0

    async def size(self, key: str) -> int:  # pragma: no cover - unused
        return 0


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session with one project pre-seeded."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Owner",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Ingest Project",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.commit()
        s.info["project_id"] = project.id
        s.info["owner_id"] = owner.id
        yield s


@pytest.fixture(autouse=True)
def _fresh_gate() -> None:
    """Reset the process-global ingest gate around every test."""
    reset_ingest_gate()
    yield
    reset_ingest_gate()


def _payload(owner_id: uuid.UUID) -> dict[str, str]:
    return {"sub": str(owner_id), "role": "editor"}


# ── 1. init opens a multipart upload and presigns parts ─────────────────────


@pytest.mark.asyncio
async def test_init_ingest_opens_multipart_and_presigns_parts(session: AsyncSession) -> None:
    """init creates the scan in status=uploading and mints one URL per part."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    service = PointCloudService(session, storage=storage)

    settings = get_settings()
    # 64 MiB parts; a 150 MiB file therefore needs 3 parts.
    part_size = int(settings.pointcloud_part_size_bytes)
    total = part_size * 2 + 1  # forces exactly 3 parts

    result = await service.init_ingest(
        ScanIngestInit(
            project_id=project_id,
            name="Site scan day 1",
            source_type=SourceType.lidar,
            original_format="laz",
            accuracy_tier=AccuracyTier.standard,
            total_size_bytes=total,
        ),
        payload=_payload(owner_id),
    )
    await session.commit()

    assert result["upload_id"] == "fake-upload-id"
    assert result["part_size_bytes"] == part_size
    assert len(result["parts"]) == 3
    assert [p["part_number"] for p in result["parts"]] == [1, 2, 3]
    # Every URL is a direct-to-storage URL, never a proxy through the core.
    assert all(p["url"].startswith("https://minio.local/") for p in result["parts"])
    # The key is tenant-namespaced.
    assert result["upload_key"].startswith(f"pointcloud/{owner_id}/{project_id}/{result['scan_id']}/")
    # Storage was actually driven.
    assert storage.initiated == [result["upload_key"]]
    assert len(storage.presigned_parts) == 3

    # The scan row exists in status=uploading.
    scan = await service.get_scan(result["scan_id"], payload=_payload(owner_id))
    assert scan.status == "uploading"
    assert scan.original_format == "laz"


@pytest.mark.asyncio
async def test_init_ingest_part_count_tracks_size(session: AsyncSession) -> None:
    """A single-part file mints exactly one URL; the count scales with size."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    service = PointCloudService(session, storage=storage)

    result = await service.init_ingest(
        ScanIngestInit(
            project_id=project_id,
            name="Tiny scan",
            original_format="e57",
            total_size_bytes=1,
        ),
        payload=_payload(owner_id),
    )
    await session.commit()
    assert len(result["parts"]) == 1


# ── 2. complete finalises and marks uploaded ────────────────────────────────


@pytest.mark.asyncio
async def test_complete_ingest_finalises_and_marks_uploaded(session: AsyncSession) -> None:
    """complete calls CompleteMultipartUpload and flips the scan to uploaded."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend(complete_size=1_500_000_000)
    service = PointCloudService(session, storage=storage)

    init = await service.init_ingest(
        ScanIngestInit(
            project_id=project_id,
            name="Site scan",
            original_format="laz",
            total_size_bytes=int(get_settings().pointcloud_part_size_bytes) + 1,
        ),
        payload=_payload(owner_id),
    )
    await session.commit()
    scan_id = init["scan_id"]

    done = await service.complete_ingest(
        scan_id,
        ScanIngestComplete(
            upload_id=init["upload_id"],
            parts=[
                CompletedPart(part_number=1, etag="etag-1", size_bytes=100),
                CompletedPart(part_number=2, etag="etag-2", size_bytes=50),
            ],
        ),
        payload=_payload(owner_id),
    )
    await session.commit()

    assert done["status"] == "uploaded"
    assert done["size_bytes"] == 1_500_000_000
    assert storage.completed == [(init["upload_key"], "fake-upload-id", 2)]

    scan = await service.get_scan(scan_id, payload=_payload(owner_id))
    assert scan.status == "uploaded"


@pytest.mark.asyncio
async def test_complete_ingest_rejects_non_contiguous_parts(session: AsyncSession) -> None:
    """A gap in the part list is rejected 422 before any storage call."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    service = PointCloudService(session, storage=storage)

    init = await service.init_ingest(
        ScanIngestInit(
            project_id=project_id,
            name="Gap scan",
            original_format="las",
            total_size_bytes=10,
        ),
        payload=_payload(owner_id),
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.complete_ingest(
            init["scan_id"],
            ScanIngestComplete(
                upload_id=init["upload_id"],
                # parts 1 and 3 - a gap at 2.
                parts=[
                    CompletedPart(part_number=1, etag="a"),
                    CompletedPart(part_number=3, etag="c"),
                ],
            ),
            payload=_payload(owner_id),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "parts_not_contiguous"
    # Storage completion was never attempted.
    assert storage.completed == []


@pytest.mark.asyncio
async def test_complete_ingest_conflicts_when_not_uploading(session: AsyncSession) -> None:
    """Completing a scan that is no longer uploading returns 409."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    service = PointCloudService(session, storage=storage)

    init = await service.init_ingest(
        ScanIngestInit(
            project_id=project_id,
            name="Twice scan",
            original_format="las",
            total_size_bytes=10,
        ),
        payload=_payload(owner_id),
    )
    await session.commit()
    parts = [CompletedPart(part_number=1, etag="a")]

    await service.complete_ingest(
        init["scan_id"],
        ScanIngestComplete(upload_id=init["upload_id"], parts=parts),
        payload=_payload(owner_id),
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.complete_ingest(
            init["scan_id"],
            ScanIngestComplete(upload_id=init["upload_id"], parts=parts),
            payload=_payload(owner_id),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["reason"] == "scan_not_uploading"


@pytest.mark.asyncio
async def test_complete_ingest_surfaces_storage_failure(session: AsyncSession) -> None:
    """A storage completion failure surfaces as a 422 with an explanatory reason."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    storage.fail_complete = True
    service = PointCloudService(session, storage=storage)

    init = await service.init_ingest(
        ScanIngestInit(
            project_id=project_id,
            name="Broken scan",
            original_format="las",
            total_size_bytes=10,
        ),
        payload=_payload(owner_id),
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.complete_ingest(
            init["scan_id"],
            ScanIngestComplete(
                upload_id=init["upload_id"],
                parts=[CompletedPart(part_number=1, etag="a")],
            ),
            payload=_payload(owner_id),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "multipart_complete_failed"
    # The scan stays in uploading so the client can retry.
    scan = await service.get_scan(init["scan_id"], payload=_payload(owner_id))
    assert scan.status == "uploading"


# ── 3. back-pressure gate ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_ingest_back_pressure_returns_429(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the ingest gate is full, init sheds load with 429, not a queue."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    service = PointCloudService(session, storage=storage)

    # Force the gate to a single slot, then occupy it so the next init is shed.
    settings = get_settings()
    monkeypatch.setattr(settings, "pointcloud_max_concurrent_ingest", 1, raising=False)
    reset_ingest_gate()

    import app.modules.pointcloud.service as svc

    gate = svc._get_ingest_gate()
    # Take the only slot, simulating an in-flight init.
    assert svc.PointCloudService._try_acquire_gate(gate) is True

    with pytest.raises(HTTPException) as exc:
        await service.init_ingest(
            ScanIngestInit(
                project_id=project_id,
                name="Shed scan",
                original_format="las",
                total_size_bytes=10,
            ),
            payload=_payload(owner_id),
        )
    assert exc.value.status_code == 429
    assert exc.value.detail["reason"] == "ingest_capacity_reached"
    # No multipart upload was opened for the shed request.
    assert storage.initiated == []

    gate.release()


@pytest.mark.asyncio
async def test_init_ingest_releases_gate_on_success(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful init returns its gate slot so the next caller is not blocked."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    service = PointCloudService(session, storage=storage)

    settings = get_settings()
    monkeypatch.setattr(settings, "pointcloud_max_concurrent_ingest", 1, raising=False)
    reset_ingest_gate()

    for _ in range(3):
        result = await service.init_ingest(
            ScanIngestInit(
                project_id=project_id,
                name="Serial scan",
                original_format="las",
                total_size_bytes=10,
            ),
            payload=_payload(owner_id),
        )
        await session.commit()
        assert result["upload_id"] == "fake-upload-id"


# ── 4. hard max-proxied-bytes cap ───────────────────────────────────────────


def test_guard_proxied_size_caps_fallback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hard cap rejects an oversized proxied body with 413."""
    settings = get_settings()
    monkeypatch.setattr(settings, "pointcloud_max_proxied_bytes", 1024, raising=False)

    # At or below the cap is fine.
    guard_proxied_size(1024)
    guard_proxied_size(0)

    with pytest.raises(HTTPException) as exc:
        guard_proxied_size(1025)
    assert exc.value.status_code == 413
    assert exc.value.detail["reason"] == "proxied_upload_too_large"
    assert exc.value.detail["max_proxied_bytes"] == 1024


# ── 5. format gate ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_ingest_rejects_recap(session: AsyncSession) -> None:
    """A proprietary ReCap container is rejected before any storage call."""
    project_id: uuid.UUID = session.info["project_id"]
    owner_id: uuid.UUID = session.info["owner_id"]
    storage = FakeS3Backend()
    service = PointCloudService(session, storage=storage)

    init = ScanIngestInit(
        project_id=project_id,
        name="ReCap import",
        original_format="e57",
        total_size_bytes=10,
    )
    # ``rcp`` is not in the schema enum; bypass to prove the SERVICE gate also
    # rejects it (defence in depth).
    object.__setattr__(init, "original_format", "rcp")

    with pytest.raises(HTTPException) as exc:
        await service.init_ingest(init, payload=_payload(owner_id))
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "format_proprietary_recap"
    # No multipart upload was opened for the rejected format.
    assert storage.initiated == []
