# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud / Reality Capture business logic + IDOR closures.

Phase 0 implements the read + register + presigned-direct ingest surface end to
end:

* ``register_upload`` - mint a ``ScanDataset`` row in ``status='uploading'``
  with a tenant-namespaced MinIO upload key, after resolving and validating the
  tenant, the project access, the upload format and the accuracy tier.
* ``init_ingest`` - register the scan AND open a presigned-direct-to-MinIO
  multipart upload so the browser / CLI streams 5-200 GB straight to object
  storage; the FastAPI core never proxies the bytes. Back-pressured by a
  process-global ingest gate.
* ``complete_ingest`` - finalise the multipart upload
  (``CompleteMultipartUpload``), stamp the ``upload_key`` and flip the scan to
  ``status='uploaded'``.
* ``get_scan`` / ``list_scans`` - tenant-scoped, project-access-gated reads.

The heavy off-core surface (conversion, cut/fill, measurement, AI element
proposals) is declared here as real, clearly-named stubs that raise
``NotImplementedError`` naming the phase that delivers them. They are NOT silent
``pass`` bodies: a raising stub fails loudly if called before its phase ships,
which is the intended behaviour for a foundation gate.

The core never imports a point-cloud library and never proxies cloud bytes; the
upload itself goes presigned-direct-to-MinIO and the converter does the PDAL /
Open3D / py3dtiles work out of process.
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.events import event_bus
from app.core.storage import (
    MultipartSession,
    PartInfo,
    StorageBackend,
    get_storage_backend,
)
from app.modules.pointcloud.models import ScanDataset
from app.modules.pointcloud.repository import (
    ScanDatasetRepository,
    ScanRegistrationRepository,
)
from app.modules.pointcloud.schemas import (
    ScanDatasetCreate,
    ScanIngestComplete,
    ScanIngestInit,
)
from app.modules.pointcloud.validators import (
    format_rejection_reason,
    is_valid_tier,
    normalize_format,
)

logger = logging.getLogger(__name__)

# Largest part count S3 (and MinIO) accept in a single multipart upload. With a
# 64 MiB default part size this supports a single upload up to ~640 GB, well
# above the 200 GB ceiling we target.
_S3_MAX_PARTS = 10000


# ── Process-global ingest back-pressure gate ─────────────────────────────────
#
# Opening a multipart upload touches object storage (a network round-trip) and,
# on a small VPS, a flood of concurrent inits would exhaust the connection pool.
# A single process-wide semaphore caps how many ingest inits run at once; when
# it is full the init endpoint returns 429 with an explanatory reason rather
# than degrade the whole process. The gate is created lazily and rebuilt when
# the configured limit changes (tests flip the setting between cases).

_ingest_gate: asyncio.Semaphore | None = None
_ingest_gate_limit: int = 0


def _get_ingest_gate() -> asyncio.Semaphore:
    """Return the process-global ingest semaphore, rebuilt if the limit changed."""
    global _ingest_gate, _ingest_gate_limit
    limit = int(getattr(get_settings(), "pointcloud_max_concurrent_ingest", 8))
    limit = max(1, limit)
    if _ingest_gate is None or _ingest_gate_limit != limit:
        _ingest_gate = asyncio.Semaphore(limit)
        _ingest_gate_limit = limit
    return _ingest_gate


def reset_ingest_gate() -> None:
    """Clear the cached ingest semaphore (test-only helper)."""
    global _ingest_gate, _ingest_gate_limit
    _ingest_gate = None
    _ingest_gate_limit = 0


def guard_proxied_size(size_bytes: int) -> None:
    """Reject a proxied upload body that exceeds the hard max-proxied-bytes cap.

    The direct presigned path has no size limit - the bytes never touch the
    core. This guard exists only for the rare FALLBACK path where a body would
    be proxied through FastAPI (a worker-less or misrouted deployment). It
    raises 413 with an explanatory reason so a multi-GB body can never push the
    3 GB core into swap. A non-positive cap is treated as "0 allowed" (proxying
    fully disabled) so the safe default never silently lifts the limit.
    """
    cap = int(getattr(get_settings(), "pointcloud_max_proxied_bytes", 0))
    if size_bytes > cap:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "reason": "proxied_upload_too_large",
                "size_bytes": int(size_bytes),
                "max_proxied_bytes": cap,
                "message": (
                    "This upload is too large to proxy through the server. "
                    "Reality-capture scans must be uploaded direct to object "
                    "storage via the presigned multipart URLs from "
                    "/scans/ingest/init."
                ),
            },
        )


@dataclass(frozen=True)
class PointsPayload:
    """Packed viewer buffer plus the counts behind the truncation signal.

    ``total_count`` is the scan's full valid point count; ``returned_count`` is
    how many survived server-side decimation. ``truncated`` lets the router tell
    the client (via a response header) that the preview is a decimated subset, so
    a user never mistakes a decimated cloud for the whole scan.
    """

    buffer: bytes
    total_count: int
    returned_count: int

    @property
    def truncated(self) -> bool:
        return self.returned_count < self.total_count


async def _spill_stream_to_temp(
    stream: AsyncIterator[bytes],
    *,
    suffix: str,
    max_bytes: int,
) -> str:
    """Spool an async byte stream to a temp file, capped at ``max_bytes``.

    Writes each chunk straight to disk so the whole object never lands in RAM
    (reading it all into memory is what OOMs the 3 GB core on a multi-GB scan).
    Raises HTTP 413 - and removes the partial temp file - as soon as the running
    total exceeds ``max_bytes`` (a non-positive cap disables the guard). Returns
    the temp-file path; the caller owns cleanup on the success path.
    """
    import contextlib
    import os
    import tempfile

    fd, tmp_name = tempfile.mkstemp(suffix=suffix)
    written = 0
    capped = max_bytes > 0
    ok = False
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in stream:
                written += len(chunk)
                if capped and written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail={
                            "reason": "scan_too_large_to_preview",
                            "max_bytes": int(max_bytes),
                            "message": (
                                "This scan is too large to preview inline. Very large "
                                "reality-capture scans are handled by the out-of-core "
                                "converter instead of being streamed through the server."
                            ),
                        },
                    )
                out.write(chunk)
        ok = True
    finally:
        if not ok:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
    return tmp_name


class PointCloudService:
    """Business logic + workflow orchestration for reality-capture scans."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: StorageBackend | None = None,
    ) -> None:
        self.session = session
        self.scans = ScanDatasetRepository(session)
        self.registrations = ScanRegistrationRepository(session)
        # The storage backend is injectable so tests can pass a mock S3 client
        # without aioboto3 installed; production resolves the configured
        # singleton (local filesystem or S3/MinIO).
        self._storage = storage

    @property
    def storage(self) -> StorageBackend:
        if self._storage is None:
            self._storage = get_storage_backend()
        return self._storage

    # ── IDOR + tenant helpers ───────────────────────────────────────────

    async def _resolve_tenant_and_verify(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None,
        *,
        not_found_detail: str = "Not found",
    ) -> uuid.UUID:
        """404 cross-tenant accesses and return the project's tenant id.

        The platform is single-tenant-per-project (see ``geo_hub`` notes): the
        project owner is the tenant boundary. This helper mirrors
        ``geo_hub.service._verify_project_owner`` - admins bypass, anonymous
        callers and cross-tenant callers collapse to 404 so the endpoint cannot
        be turned into a UUID-existence oracle - and additionally returns the
        resolved ``tenant_id`` (the project owner) so scans are stamped and
        scoped consistently.
        """
        from app.modules.projects.repository import ProjectRepository
        from app.modules.teams.access import is_project_member

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=not_found_detail,
            )
        tenant_id = project.owner_id

        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=not_found_detail,
            )
        if payload.get("role") == "admin":
            return tenant_id
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=not_found_detail,
            )
        if str(project.owner_id) == str(user_id):
            return tenant_id
        try:
            user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=not_found_detail,
            ) from None
        if await is_project_member(self.session, project_id, user_uuid):
            return tenant_id
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    @staticmethod
    def _upload_key(tenant_id: uuid.UUID, project_id: uuid.UUID, scan_id: uuid.UUID, fmt: str) -> str:
        """Build a tenant-namespaced MinIO key for the raw upload.

        Shape: ``pointcloud/{tenant_id}/{project_id}/{scan_id}/raw.{ext}``. The
        leading ``{tenant_id}`` segment guarantees two tenants can never collide
        even if they upload the same vendor file, and a bucket policy can scope
        access per-tenant on the prefix.
        """
        ext = normalize_format(fmt) or "bin"
        return f"pointcloud/{tenant_id}/{project_id}/{scan_id}/raw.{ext}"

    @staticmethod
    def _validated_format(raw_format: Any) -> str:
        """Normalise + gate an upload format, raising 422 with a reason code.

        Rejects the proprietary ``.rcp`` / ``.rcs`` scan container and any format
        outside the accepted allow-list with an explanatory, translatable
        ``reason`` code.
        """
        fmt = normalize_format(getattr(raw_format, "value", raw_format))
        rejection = format_rejection_reason(fmt)
        if rejection is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "reason": rejection,
                    "format": fmt,
                    "message": (
                        "The proprietary .rcp/.rcs scan container is not accepted - export E57 or LAS instead."
                        if rejection == "format_proprietary_scan"
                        else "Unsupported point-cloud format. Accepted: LAS, LAZ, COPC and E57."
                    ),
                },
            )
        return fmt

    @staticmethod
    def _validated_tier(raw_tier: Any) -> str:
        """Gate an accuracy tier, raising 422 with a reason code on an unknown tier."""
        tier = getattr(raw_tier, "value", raw_tier)
        if not is_valid_tier(tier):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "reason": "invalid_accuracy_tier",
                    "tier": tier,
                    "message": "Accuracy tier must be one of survey, standard, coarse.",
                },
            )
        return tier

    @staticmethod
    def _created_by(payload: dict[str, Any] | None) -> uuid.UUID | None:
        """Resolve the acting user id from a JWT payload, or ``None``."""
        if payload is None:
            return None
        raw_user = payload.get("sub") or payload.get("user_id")
        if raw_user is None:
            return None
        try:
            return raw_user if isinstance(raw_user, uuid.UUID) else uuid.UUID(str(raw_user))
        except (ValueError, TypeError):
            return None

    # ── Phase 0: register + read ────────────────────────────────────────

    async def register_upload(
        self,
        data: ScanDatasetCreate,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ScanDataset:
        """Register a scan and mint its tenant-namespaced upload key.

        Creates a ``ScanDataset`` row in ``status='uploading'``. The caller then
        uploads the bytes presigned-direct-to-MinIO under the returned
        ``upload_key``; ``init_ingest`` opens the multipart upload and
        ``complete_ingest`` finalises it. Raises:

        * 404 - project not found or cross-tenant access.
        * 422 - an unsupported or proprietary (.rcp/.rcs scan container) upload
          format, or an unknown accuracy tier, with an explanatory ``reason``
          code.
        """
        fmt = self._validated_format(data.original_format)
        tier = self._validated_tier(data.accuracy_tier)

        tenant_id = await self._resolve_tenant_and_verify(
            data.project_id,
            payload,
            not_found_detail="Project not found",
        )

        scan_id = uuid.uuid4()
        source_type = getattr(data.source_type, "value", data.source_type)
        retention = getattr(data.retention_policy, "value", data.retention_policy)
        scan = ScanDataset(
            id=scan_id,
            project_id=data.project_id,
            tenant_id=tenant_id,
            source_type=source_type,
            original_format=fmt,
            accuracy_tier=tier,
            registration_status="unregistered",
            crs_epsg=data.crs_epsg,
            point_count=data.point_count,
            upload_key=self._upload_key(tenant_id, data.project_id, scan_id, fmt),
            status="uploading",
            retention_policy=retention,
            created_by=self._created_by(payload),
        )
        await self.scans.create(scan)
        return scan

    # ── Phase 0: presigned-direct multipart ingest ─────────────────────

    @staticmethod
    def _part_count(total_size_bytes: int, part_size_bytes: int) -> int:
        """How many multipart parts a file of ``total_size_bytes`` needs.

        Raises 422 when the file would need more than the S3/MinIO part ceiling
        with the configured part size, with an explanatory reason that tells the
        operator to raise ``OE_POINTCLOUD_PART_SIZE_BYTES``.
        """
        count = max(1, math.ceil(total_size_bytes / part_size_bytes))
        if count > _S3_MAX_PARTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "reason": "too_many_parts",
                    "part_count": count,
                    "max_parts": _S3_MAX_PARTS,
                    "message": (
                        "This file needs more multipart parts than object storage "
                        "allows. Raise the configured part size "
                        "(OE_POINTCLOUD_PART_SIZE_BYTES) for very large scans."
                    ),
                },
            )
        return count

    async def init_ingest(
        self,
        data: ScanIngestInit,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open a presigned-direct-to-MinIO multipart upload for a new scan.

        Registers the ``ScanDataset`` in ``status='uploading'``, opens a
        multipart upload on object storage, and returns one presigned ``PUT``
        URL per part. The browser / CLI uploads the parts straight to storage;
        the FastAPI core never proxies the bytes. Back-pressured by the
        process-global ingest gate - returns 429 when too many inits are in
        flight.

        Raises:

        * 404 - project not found or cross-tenant access.
        * 422 - bad format / tier, or a file too large for the part ceiling.
        * 429 - ingest gate full (too many concurrent inits).
        """
        fmt = self._validated_format(data.original_format)
        tier = self._validated_tier(data.accuracy_tier)
        tenant_id = await self._resolve_tenant_and_verify(
            data.project_id,
            payload,
            not_found_detail="Project not found",
        )

        settings = get_settings()
        part_size = int(getattr(settings, "pointcloud_part_size_bytes", 64 * 1024 * 1024))
        expires_seconds = int(getattr(settings, "pointcloud_presign_expire_seconds", 12 * 3600))
        part_count = self._part_count(data.total_size_bytes, part_size)

        scan_id = uuid.uuid4()
        upload_key = self._upload_key(tenant_id, data.project_id, scan_id, fmt)

        gate = _get_ingest_gate()
        if not self._try_acquire_gate(gate):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "reason": "ingest_capacity_reached",
                    "max_concurrent_ingest": _ingest_gate_limit,
                    "message": (
                        "Too many scan uploads are being prepared right now. "
                        "Wait a moment and retry - this protects the server from "
                        "opening more uploads than it can track at once."
                    ),
                },
            )
        try:
            scan = ScanDataset(
                id=scan_id,
                project_id=data.project_id,
                tenant_id=tenant_id,
                source_type=getattr(data.source_type, "value", data.source_type),
                original_format=fmt,
                accuracy_tier=tier,
                registration_status="unregistered",
                crs_epsg=data.crs_epsg,
                point_count=data.point_count,
                upload_key=upload_key,
                status="uploading",
                retention_policy=getattr(data.retention_policy, "value", data.retention_policy),
                created_by=self._created_by(payload),
            )
            await self.scans.create(scan)

            session_obj = await self.storage.initiate_multipart(upload_key)
            parts: list[dict[str, Any]] = []
            expires_at = None
            for part_number in range(1, part_count + 1):
                presigned = await self.storage.presigned_upload_part_url(
                    session_obj,
                    part_number,
                    expires_seconds=expires_seconds,
                )
                parts.append({"part_number": part_number, "url": presigned.url})
                expires_at = presigned.expires_at
        finally:
            gate.release()

        return {
            "scan_id": scan.id,
            "upload_id": session_obj.upload_id,
            "upload_key": upload_key,
            "part_size_bytes": part_size,
            "parts": parts,
            "expires_at": expires_at,
        }

    @staticmethod
    def _try_acquire_gate(gate: asyncio.Semaphore) -> bool:
        """Acquire ``gate`` without blocking; return False if it is full.

        ``Semaphore.acquire`` would block (queue the caller) when the count is
        zero, but we want explicit back-pressure (429) instead of queueing. In
        single-threaded asyncio nothing else runs between the ``locked()`` probe
        and the synchronous counter decrement, so this take-a-slot-or-fail is
        race-free without awaiting. ``locked()`` is True exactly when the
        internal value is 0.
        """
        if gate.locked():
            return False
        gate._value -= 1  # noqa: SLF001 - non-blocking take, mirrors release()
        return True

    async def complete_ingest(
        self,
        scan_id: uuid.UUID,
        data: ScanIngestComplete,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finalise a presigned-direct multipart upload.

        Verifies project access, calls ``CompleteMultipartUpload`` with the
        reported parts, stamps the ``upload_key`` and flips the scan to
        ``status='uploaded'`` so a later phase can submit the ingest job.

        Raises:

        * 404 - scan not found or cross-tenant access.
        * 409 - the scan is not in ``status='uploading'`` (already finalised).
        * 422 - the part list is empty, non-contiguous, or storage rejects the
          completion, with an explanatory reason.
        """
        scan = await self.get_scan(scan_id, payload=payload)
        if scan.status != "uploading":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "reason": "scan_not_uploading",
                    "status": scan.status,
                    "message": ("This scan is not awaiting an upload. It may have already been finalised."),
                },
            )

        ordered = sorted(data.parts, key=lambda p: p.part_number)
        expected = list(range(1, len(ordered) + 1))
        if [p.part_number for p in ordered] != expected:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "reason": "parts_not_contiguous",
                    "message": "Multipart parts must be contiguous starting at part 1.",
                },
            )

        session_obj = MultipartSession(
            upload_id=data.upload_id,
            key=scan.upload_key,
            backend=self._storage_backend_kind(),
            started_at=datetime.now(UTC),
            metadata={},
        )
        part_infos = [PartInfo(part_number=p.part_number, etag=p.etag, size_bytes=p.size_bytes) for p in ordered]
        try:
            stored = await self.storage.complete_multipart(session_obj, part_infos)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "reason": "multipart_complete_failed",
                    "message": (f"The upload could not be finalised. Re-upload any missing parts and retry. ({exc})"),
                },
            ) from exc

        # Read every scan/stored field the event payload and response need NOW,
        # before the finalise writes below, so both report the scan as it was
        # ingested rather than reloading a half-updated row, where the reload
        # raises MissingGreenlet on the async session.
        project_id = scan.project_id
        tenant_id = scan.tenant_id
        resolved_key = stored.key or scan.upload_key
        size_bytes = int(stored.size_bytes)
        fmt = (scan.original_format or "").lower()
        had_crs = scan.crs_epsg is not None

        # Cheap header sniff (plan section 3 step 1): read only the container
        # header now that the bytes have landed, so the scan list shows real
        # extents and scalar fields immediately - never decode the 5-200 GB
        # payload here. Best-effort: a missing reader or an unreadable header
        # records an honest status and never fails the finalised upload.
        sniff_fields = await self._sniff_header_fields(resolved_key, fmt, had_crs=had_crs)

        await self.scans.update_fields(
            scan_id,
            upload_key=resolved_key,
            status="uploaded",
            **sniff_fields,
        )
        await event_bus.publish(
            "pointcloud.upload.completed",
            {
                "scan_id": str(scan_id),
                "project_id": str(project_id),
                "tenant_id": str(tenant_id),
                "upload_key": resolved_key,
                "size_bytes": size_bytes,
            },
            source_module="oe_pointcloud",
        )
        return {
            "scan_id": scan_id,
            "upload_key": resolved_key,
            "status": "uploaded",
            "size_bytes": size_bytes,
        }

    async def _sniff_header_fields(
        self,
        upload_key: str,
        fmt: str,
        *,
        had_crs: bool,
    ) -> dict[str, Any]:
        """Read the just-uploaded container's header and build the fields to persist.

        Returns a dict ready to splat into ``update_fields``: ``point_count``,
        ``bbox_json``, ``scan_metadata`` and, when the header gives a usable
        bounding box and the row has no CRS yet, a heuristic ``crs_epsg`` /
        ``crs_confidence``. This is the cheap preview half of the pipeline: it
        reads only the header (a few KB), never the point payload, and on the
        object-storage backend it range-reads only a bounded prefix so a 200 GB
        cloud is never pulled into the 3 GB core.

        Best-effort by contract - any failure resolves to an honest
        ``scan_metadata.status`` ("pending" when no reader is installed,
        "unreadable" when the header is corrupt) and never raises, so a
        finalised upload is never rolled back by a metadata read.
        """
        from app.modules.pointcloud.sniff import (
            HeaderSniffError,
            HeaderSniffUnavailable,
        )

        def _meta(status: str, **rest: Any) -> dict[str, Any]:
            return {"status": status, "format": fmt, **rest}

        try:
            header = await self._read_scan_header(upload_key, fmt)
        except HeaderSniffUnavailable as exc:
            # No reader installed on this deployment. The upload is fine; the
            # converter / viewer can still produce metadata later. Surface a
            # clear, non-alarming "pending" state instead of a fake zero.
            return {
                "scan_metadata": _meta(
                    "pending",
                    reason="reader_not_installed",
                    reader=exc.reader,
                    message=(
                        f"Header preview for {exc.fmt.upper()} needs the point-cloud "
                        f"reader ({exc.reader}) on the server. The scan uploaded fine; "
                        "extents and scalar fields will appear once a reader is enabled."
                    ),
                ),
            }
        except HeaderSniffError as exc:
            logger.warning("Point-cloud header sniff failed for key %s: %s", upload_key, exc)
            return {
                "scan_metadata": _meta("unreadable", reason="header_unreadable", message=str(exc)),
            }
        except NotImplementedError:
            # The storage backend cannot range-read (no open_stream / read_bytes).
            # That is a capability gap, not a corrupt file - record it as pending
            # so the UI says "preview not available here" rather than "bad scan".
            logger.info(
                "Point-cloud header sniff skipped for key %s: storage backend has no range read",
                upload_key,
            )
            return {"scan_metadata": _meta("pending", reason="storage_no_range_read")}
        except Exception:  # noqa: BLE001 - sniff is best-effort, never fail the upload
            logger.warning("Unexpected point-cloud header sniff error for key %s", upload_key, exc_info=True)
            return {"scan_metadata": _meta("unreadable", reason="sniff_error")}

        return self._fields_from_header(header, fmt=fmt, had_crs=had_crs)

    async def _read_scan_header(self, upload_key: str, fmt: str) -> Any:
        """Read just the header of the uploaded container, never the points.

        Local backend: hand the reader the file path so laspy/pye57 read only
        the header in place (no copy of a multi-GB file). Object storage:
        range-read a bounded header prefix and sniff that; E57 needs random file
        access, so its prefix is spilled to a small temp file.
        """
        from app.modules.pointcloud.sniff import (
            HEADER_PREFIX_BYTES,
            sniff_header_from_path,
            sniff_header_from_prefix,
        )

        local_path = self._local_path_for(upload_key)
        if local_path is not None:
            return await asyncio.to_thread(sniff_header_from_path, Path(local_path), fmt)

        # Object storage: pull only the leading header prefix, not the whole blob.
        prefix = await self._read_key_prefix(upload_key, HEADER_PREFIX_BYTES)
        if fmt in ("e57",):
            # libE57 needs a seekable file; spill the small prefix to a temp file.
            import tempfile

            def _spill(data: bytes) -> str:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".e57") as fh:
                    fh.write(data)
                    return fh.name

            tmp_path = await asyncio.to_thread(_spill, prefix)
            try:
                return await asyncio.to_thread(sniff_header_from_path, Path(tmp_path), fmt)
            finally:
                import contextlib
                import os

                with contextlib.suppress(OSError):
                    await asyncio.to_thread(os.unlink, tmp_path)
        return await asyncio.to_thread(sniff_header_from_prefix, prefix, fmt)

    async def _read_key_prefix(self, upload_key: str, max_bytes: int) -> bytes:
        """Read at most ``max_bytes`` leading bytes of a stored blob.

        Uses the streaming reader so we stop after the header prefix instead of
        loading the whole object - the point of keeping the core thin. The
        underlying async generator is closed deterministically on the early
        break (``aclosing``) so the S3 response / file handle is released at
        once rather than at GC time.
        """
        from contextlib import aclosing

        chunks: list[bytes] = []
        total = 0
        async with aclosing(self.storage.open_stream(upload_key)) as stream:
            async for chunk in stream:
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break
        data = b"".join(chunks)
        return data[:max_bytes]

    def _fields_from_header(
        self,
        header: Any,
        *,
        fmt: str,
        had_crs: bool,
    ) -> dict[str, Any]:
        """Turn a sniffed :class:`ScanHeader` into persistable column values."""
        ranges = header.coordinate_ranges
        scalar_fields = {
            "rgb": bool(header.has_rgb),
            "intensity": bool(header.has_intensity),
            "classification": bool(header.has_classification),
        }
        scan_metadata: dict[str, Any] = {
            "status": "ok",
            "format": fmt,
            "reader": header.extra.get("reader"),
            "scalar_fields": scalar_fields,
            "units": header.units,
            "coordinate_ranges": ranges,
            **{k: v for k, v in header.extra.items() if k != "reader"},
        }

        fields: dict[str, Any] = {"scan_metadata": scan_metadata}
        if header.point_count > 0:
            fields["point_count"] = int(header.point_count)

        if header.bbox_min is not None and header.bbox_max is not None:
            bbox_json: dict[str, Any] = {
                "min": list(header.bbox_min),
                "max": list(header.bbox_max),
                "units": header.units,
            }
            # Derive a CRS guess from the header bbox (reusing the CAD detector)
            # only when the row carries no explicit CRS yet - never overwrite a
            # human-supplied or already-detected EPSG.
            if not had_crs:
                crs = self._guess_crs_from_bbox(header.bbox_min, header.bbox_max, header.units)
                if crs is not None:
                    epsg, confidence = crs
                    if epsg is not None:
                        fields["crs_epsg"] = int(epsg)
                        bbox_json["crs_epsg"] = int(epsg)
                    if confidence is not None:
                        from decimal import Decimal

                        fields["crs_confidence"] = Decimal(str(round(float(confidence), 3)))
                    scan_metadata["crs_guess"] = {
                        "epsg": epsg,
                        "confidence": confidence,
                        "method": "bbox_heuristic",
                    }
            fields["bbox_json"] = bbox_json
        return fields

    @staticmethod
    def _guess_crs_from_bbox(
        bbox_min: tuple[float, float, float],
        bbox_max: tuple[float, float, float],
        units: str,
    ) -> tuple[int | None, float | None] | None:
        """Heuristic EPSG guess from a header bbox, via the CAD CRS detector.

        Returns ``(epsg, confidence)`` or ``None`` when the detector could not
        decide. The point-cloud module owns no CRS heuristic of its own - it
        reuses ``cad.crs_detector.detect_from_bbox`` so every upload path shares
        one region table. Failure is swallowed (returns ``None``); a CRS guess
        is a nicety, never a blocker.
        """
        try:
            from app.modules.cad.crs_detector import detect_from_bbox

            guess = detect_from_bbox(
                (float(bbox_min[0]), float(bbox_min[1]), float(bbox_max[0]), float(bbox_max[1])),
                units=units or "m",
            )
        except Exception:  # noqa: BLE001 - CRS guess is best-effort
            return None
        return guess.epsg, guess.confidence

    def _storage_backend_kind(self) -> str:
        """Return ``"s3"`` or ``"local"`` for the active backend.

        The multipart session needs the right ``backend`` discriminator so the
        completion routes through the matching code path. We infer it from the
        class name rather than importing the concrete types, so a custom
        community backend that subclasses :class:`S3StorageBackend` still routes
        correctly.
        """
        name = type(self.storage).__name__.lower()
        return "s3" if "s3" in name else "local"

    async def get_scan(
        self,
        scan_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ScanDataset:
        """Fetch one scan, gated by tenant + project access.

        Collapses both "no such scan" and "scan belongs to another tenant" to a
        single 404 so the endpoint never leaks scan existence.
        """
        scan = await self.scans.get_by_id(scan_id)
        if scan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scan not found",
            )
        # Verifying project access also re-resolves the tenant; reject if the
        # row's tenant does not match the caller's project tenant.
        tenant_id = await self._resolve_tenant_and_verify(
            scan.project_id,
            payload,
            not_found_detail="Scan not found",
        )
        if str(scan.tenant_id) != str(tenant_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scan not found",
            )
        return scan

    async def get_points(
        self,
        scan_id: uuid.UUID,
        *,
        max_points: int = 1_500_000,
        payload: dict[str, Any] | None = None,
    ) -> PointsPayload:
        """Decode, decimate and pack a scan's points for the viewer.

        Reads the raw upload (E57 / LAS / LAZ) from storage, decimates it to
        ``max_points`` server-side and returns the compact OEPC binary buffer the
        browser drops into a ``THREE.Points`` geometry, plus the total vs returned
        counts so the caller can flag a decimated preview. Backfills
        ``point_count`` and ``bbox_json`` on the row on first read so the list
        view shows real extents without re-decoding.

        Memory-safe by construction: on a non-local backend the object is
        streamed to a temp file under a hard byte cap (never pulled whole into
        RAM), and the decoder refuses a source whose header declares more points
        than the inline ceiling, so neither a multi-GB blob nor a decompression
        bomb can OOM the core.

        Raises 404 (scan not visible / not uploaded yet), 409 (still uploading),
        413 (too large to preview inline - too many bytes or too many points),
        501 (no reader installed for the format) or 422 (file undecodable).
        """
        from app.modules.pointcloud.decode import (
            DEFAULT_MAX_TOTAL_POINTS,
            PointDecodeError,
            PointDecodeTooLarge,
            PointDecodeUnavailable,
            decode_points,
        )
        from app.modules.pointcloud.wire import pack_points

        scan = await self.get_scan(scan_id, payload=payload)
        # Snapshot every field we need BEFORE any update_fields() call, so the
        # decode path below works from the scan as it was read and never
        # reloads it (MissingGreenlet on the async session).
        upload_key = scan.upload_key
        fmt = (scan.original_format or "").lower()
        scan_status_value = scan.status
        existing_point_count = scan.point_count
        existing_bbox = scan.bbox_json

        if scan_status_value not in ("uploaded", "converting", "ready"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"reason": "scan_not_ready", "status": scan_status_value},
            )

        local_path = self._local_path_for(upload_key)
        tmp_path: str | None = None
        try:
            if local_path is None:
                # Stream the object to a temp file under a hard byte cap instead
                # of pulling the whole (5-200 GB) blob into RAM. Reuse the
                # proxied-bytes ceiling: pulling an object into core to decimate
                # it IS proxying it, so the same cap applies. ``aclosing`` frees
                # the storage stream deterministically even if the cap trips.
                from contextlib import aclosing

                max_bytes = int(getattr(get_settings(), "pointcloud_max_proxied_bytes", 2 * 1024 * 1024 * 1024))
                async with aclosing(self.storage.open_stream(upload_key)) as stream:
                    tmp_path = await _spill_stream_to_temp(stream, suffix=f".{fmt or 'bin'}", max_bytes=max_bytes)
                source_path = tmp_path
            else:
                source_path = str(local_path)

            # Source-size ceiling (header point count) so a huge cloud or a
            # decompression bomb is refused before the decoder materialises it.
            max_total_points = int(getattr(get_settings(), "pointcloud_max_decode_points", DEFAULT_MAX_TOTAL_POINTS))
            try:
                decoded = await asyncio.to_thread(
                    decode_points,
                    Path(source_path),
                    fmt,
                    max_points=max_points,
                    max_total_points=max_total_points,
                )
            except PointDecodeUnavailable as exc:
                # The advice goes through repair_hint because this message is a
                # response detail a user reads, and the desktop build has no pip
                # to act on it with. DESKTOP_NO_EXTRA rather than the repair
                # wording: pye57 is not in requirements-desktop.lock, so a bundle
                # without the reader is lean rather than damaged.
                from app.core.self_upgrade import DESKTOP_NO_EXTRA, repair_hint  # noqa: PLC0415

                raise HTTPException(
                    status_code=status.HTTP_501_NOT_IMPLEMENTED,
                    detail={
                        "reason": "reader_unavailable",
                        "format": exc.fmt,
                        "message": (
                            f"Viewing {exc.fmt.upper()} scans needs the optional {exc.reader} "
                            "reader. LAS, LAZ and COPC work out of the box; "
                            + repair_hint(
                                "install the 'pointcloud' extra "
                                "(pip install openconstructionerp[pointcloud]) to add E57 support.",
                                DESKTOP_NO_EXTRA,
                            )
                        ),
                    },
                ) from exc
            except PointDecodeTooLarge as exc:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={
                        "reason": "scan_too_large_to_preview",
                        "point_count": exc.total_count,
                        "max_points": exc.max_total_points,
                        "message": (
                            "This scan has too many points to preview inline. Very large "
                            "clouds are handled by the out-of-core converter instead of being "
                            "decoded in the server."
                        ),
                    },
                ) from exc
            except PointDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={"reason": "decode_failed", "message": str(exc)},
                ) from exc

            buffer = await asyncio.to_thread(pack_points, decoded)
        finally:
            if tmp_path is not None:
                import contextlib
                import os

                with contextlib.suppress(OSError):
                    await asyncio.to_thread(os.unlink, tmp_path)

        # Backfill real extents on first successful decode so the list view and
        # the federation transforms have a true bbox without re-decoding.
        needs_count = not existing_point_count
        needs_bbox = not existing_bbox
        if needs_count or needs_bbox:
            fields: dict[str, object] = {}
            if needs_count:
                fields["point_count"] = decoded.total_count
            if needs_bbox:
                fields["bbox_json"] = {
                    "min": list(decoded.bbox_min),
                    "max": list(decoded.bbox_max),
                    "center": list(decoded.center),
                }
            try:
                await self.scans.update_fields(scan_id, **fields)
            except Exception:  # noqa: BLE001 - backfill is best-effort, never fail the read
                logger.warning("Point-count/bbox backfill failed for scan %s", scan_id, exc_info=True)

        return PointsPayload(
            buffer=buffer,
            total_count=int(decoded.total_count),
            returned_count=int(decoded.returned_count),
        )

    def _local_path_for(self, upload_key: str):
        """Return the on-disk path for a key when storage is local, else None.

        Lets the decoder read the raw scan in place (no 5-200 GB copy) on the
        embedded/dev filesystem backend while still working against MinIO/S3 via
        the temp-file spill path.
        """
        from app.core.storage import LocalStorageBackend

        backend = self.storage
        if isinstance(backend, LocalStorageBackend):
            try:
                return backend._path_for(upload_key)  # noqa: SLF001 - same package boundary
            except ValueError:
                return None
        return None

    async def list_scans(
        self,
        project_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        scan_status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ScanDataset], int]:
        """List scans for a project, tenant-scoped and project-access-gated.

        Returns ``(rows, total)`` so the router can build a paginated response.
        """
        tenant_id = await self._resolve_tenant_and_verify(
            project_id,
            payload,
            not_found_detail="Project not found",
        )
        rows = await self.scans.list_for_project(
            project_id,
            tenant_id=tenant_id,
            status=scan_status,
            offset=offset,
            limit=limit,
        )
        total = await self.scans.count_for_project(
            project_id,
            tenant_id=tenant_id,
            status=scan_status,
        )
        return rows, total

    # ── Scan-vs-design deviation (viewer overlay) ───────────────────────

    async def list_deviations_for_model(
        self,
        project_id: uuid.UUID,
        model_id: str,
        *,
        payload: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return the scan-vs-design deviation rollup for one design model.

        A deviation registration's ``target_ref`` is the design it was aligned
        to (the BIM model id), so this is "every as-built deviation result for
        this model", classified into the viewer's traffic-light severity. The
        heavy point-to-mesh math is NOT recomputed here - it already lives on
        the ``ScanRegistration`` row; this only reads it, reuses
        ``validators.tier_tolerance_mm`` for the accuracy-tier bound and
        ``deviation.classify_deviation`` for the verdict, and rolls the rows up
        to the model's worst severity for the overlay legend.

        IDOR-safe: ``_resolve_tenant_and_verify`` collapses an unknown or
        cross-tenant project to 404, and the repository query is scoped to BOTH
        that project AND its tenant, so a deviation owned by another tenant can
        never leak even if a model id were shared.

        Returns a dict ready to build :class:`ScanDeviationSummary`. An empty
        result (no aligned scans for this model the caller can see) is a
        well-formed summary with ``has_deviation=False`` and a neutral
        ``unknown`` headline - never a 404 - so the viewer simply shows no
        overlay.
        """
        from app.modules.pointcloud.deviation import (
            classify_deviation,
            severity_color,
            worst_severity,
        )
        from app.modules.pointcloud.validators import tier_tolerance_mm

        tenant_id = await self._resolve_tenant_and_verify(
            project_id,
            payload,
            not_found_detail="Project not found",
        )

        rows = await self.registrations.list_for_target(
            model_id,
            project_id=project_id,
            tenant_id=tenant_id,
            offset=offset,
            limit=limit,
        )

        items: list[dict[str, Any]] = []
        severities: list[str] = []
        for reg, scan in rows:
            tier = scan.accuracy_tier
            tolerance = tier_tolerance_mm(tier)
            severity = classify_deviation(
                rms_mm=reg.rms_error,
                tolerance_mm=tolerance,
                out_of_tolerance_count=reg.out_of_tolerance_count,
                coverage_pct=reg.coverage_pct,
            )
            severities.append(severity)
            items.append(
                {
                    "registration_id": reg.id,
                    "scan_id": reg.scan_id,
                    "target_ref": reg.target_ref,
                    "accuracy_tier": tier,
                    "tier_tolerance_mm": tolerance,
                    "rms_error": reg.rms_error,
                    "out_of_tolerance_count": int(reg.out_of_tolerance_count or 0),
                    "coverage_pct": reg.coverage_pct,
                    "hole_area": reg.hole_area,
                    "confidence": reg.confidence,
                    "deviation_map_uri": reg.deviation_map_uri,
                    "severity": severity,
                    "severity_color": severity_color(severity),
                    "created_at": reg.created_at,
                }
            )

        worst = worst_severity(severities)
        return {
            "model_id": model_id,
            "project_id": project_id,
            "has_deviation": len(items) > 0,
            "worst_severity": worst,
            "worst_severity_color": severity_color(worst),
            "items": items,
            "total": len(items),
        }

    @staticmethod
    def _scan_storage_prefix(upload_key: str) -> str | None:
        """Return the per-scan object-storage prefix to sweep on delete.

        Every artifact of a scan lives under
        ``pointcloud/{tenant_id}/{project_id}/{scan_id}/`` - the raw upload
        (``raw.{ext}``) today, plus the COPC archive / 3D-Tiles / DTM a later
        phase writes. Deleting that whole prefix in one sweep frees the raw
        upload AND any derived artifacts without this method needing to know
        each future filename. The prefix is the upload key with its trailing
        ``raw.{ext}`` filename removed; ``None`` when the key has no path
        separator (nothing safe to sweep).
        """
        if not upload_key or "/" not in upload_key:
            return None
        return upload_key.rsplit("/", 1)[0] + "/"

    async def delete_scan(
        self,
        scan_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Delete a scan, its registrations AND its object-storage artifacts.

        Gated by tenant + project access through :meth:`get_scan`, so a
        cross-tenant or unknown id collapses to 404 and never leaks scan
        existence. The scan's per-scan storage prefix
        (``pointcloud/{tenant}/{project}/{scan}/``) is swept first so the raw
        upload and any derived COPC / tileset / DTM blobs are freed, mirroring
        ``geo_hub.delete_tileset``; a storage failure is logged but never
        aborts the row delete, so a stuck blob can never strand dead metadata
        in the user's scan list. The ``ScanRegistration`` rows cascade away with
        the parent via the ORM relationship.
        """
        scan = await self.get_scan(scan_id, payload=payload)
        # Snapshot every field the cleanup + event need while the row is live;
        # the row is gone after the delete and the event payload must not read
        # an absent row.
        project_id = scan.project_id
        tenant_id = scan.tenant_id
        upload_key = scan.upload_key

        # Storage cleanup runs first. A successful DB delete with a failed blob
        # sweep would leave the user with a "deleted" scan that still consumes
        # bytes, breaking the "delete frees storage" contract; sweeping first
        # means a transient backend error is logged and the row still goes, so
        # the sidebar never shows a ghost the user cannot remove.
        sweep_prefix = self._scan_storage_prefix(upload_key)
        if sweep_prefix:
            try:
                await self.storage.delete_prefix(sweep_prefix)
            except Exception as exc:  # noqa: BLE001 - log + continue, never block the delete
                logger.warning(
                    "pointcloud: storage cleanup failed for scan %s (prefix %s): %s",
                    scan_id,
                    sweep_prefix,
                    exc,
                )

        await self.scans.delete(scan_id)
        await event_bus.publish(
            "pointcloud.scan.deleted",
            {
                "scan_id": str(scan_id),
                "project_id": str(project_id),
                "tenant_id": str(tenant_id),
            },
            source_module="oe_pointcloud",
        )

    # ── Later-phase surface (real stubs, raise loudly) ──────────────────
    #
    # These are deliberately NOT silent passes. Each raises NotImplementedError
    # naming the phase that delivers it, so a premature caller fails loudly
    # instead of silently doing nothing. The heavy work all runs out of core via
    # the converter / job runner; the bodies land with their phases.

    async def submit_ingest_job(
        self,
        scan_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Submit the out-of-core ``pointcloud_ingest`` job for a scan.

        Phase 2: register a ``JobRun(kind=pointcloud_ingest)`` with
        ``idempotency_key=scan_id`` and a size-proportional timeout; the
        converter reprojects, ground-classifies, writes COPC + DTM, and (on
        demand) pnts.
        """
        raise NotImplementedError(
            "submit_ingest_job lands in Phase 2 (converter + job runner). "
            "Phase 0 only registers the upload and reads scans."
        )

    async def on_ingest_complete(
        self,
        scan_id: uuid.UUID,
        result: dict[str, Any],
    ) -> Any:
        """Handle ``pointcloud_ingest`` completion.

        Phase 2: write copc_uri / tileset_uri / point_count / bbox /
        classification_stats, create the geo_hub Tileset(source_kind=
        point_cloud), and publish ``pointcloud.tileset.ready``.
        """
        raise NotImplementedError("on_ingest_complete lands in Phase 2 (converter + job runner).")

    async def compute_cutfill(
        self,
        scan_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Compute earthwork cut/fill from a DTM diff.

        Phase 2: DTM-diff -> volume_m3 + coverage% + hole-area + accuracy_tier,
        shown with an uncertainty band; validation blocks when coverage / RMS /
        tier are out of bounds.
        """
        raise NotImplementedError(
            "compute_cutfill lands in Phase 2 (earthwork). It is gated on the DTM produced by the Phase 2 converter."
        )

    async def create_measurement(
        self,
        scan_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create a 3D measurement against a scan.

        Phase 2: stamp scan_id + accuracy_tier + CRS into a
        TakeoffMeasurement(type=pointcloud_*) geometry JSON and roll it up into
        the BOQ.
        """
        raise NotImplementedError("create_measurement lands in Phase 2 (3D measurement + BOQ rollup).")

    async def propose_elements(
        self,
        scan_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Propose primitive-fit / segmentation elements for human confirm.

        Phase 3: Open3D plane/cylinder/cluster fits with residual-based
        confidence, queued for human confirmation; only accepted fits are
        promoted to canonical elements via bim_hub.
        """
        raise NotImplementedError(
            "propose_elements lands in Phase 3 (AI segmentation + primitive fit, human-confirm queue)."
        )


__all__ = [
    "PointCloudService",
    "PointsPayload",
    "guard_proxied_size",
    "reset_ingest_gate",
]
