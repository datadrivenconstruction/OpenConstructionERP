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
    2 GB core into swap. A non-positive cap is treated as "0 allowed" (proxying
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

        Rejects proprietary ReCap RCP/RCS and any format outside the accepted
        allow-list with an explanatory, translatable ``reason`` code.
        """
        fmt = normalize_format(getattr(raw_format, "value", raw_format))
        rejection = format_rejection_reason(fmt)
        if rejection is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "reason": rejection,
                    "format": fmt,
                    "message": (
                        "Autodesk ReCap RCP/RCS is proprietary and not accepted - export E57 or LAS instead."
                        if rejection == "format_proprietary_recap"
                        else "Unsupported point-cloud format. Accepted: E57, LAS, LAZ, COPC, PLY, PCD, PTS, XYZ."
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
        * 422 - an unsupported or proprietary (ReCap RCP/RCS) upload format, or
          an unknown accuracy tier, with an explanatory ``reason`` code.
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "reason": "multipart_complete_failed",
                    "message": (f"The upload could not be finalised. Re-upload any missing parts and retry. ({exc})"),
                },
            ) from exc

        # Read every scan/stored field the event payload and response need NOW,
        # while the ORM row is still live. update_fields() ends with
        # session.expire_all(), which marks scan's attributes expired; reading
        # scan.project_id / scan.tenant_id / scan.upload_key afterwards would
        # trigger an implicit lazy reload, and an async session forbids implicit
        # IO outside a greenlet (MissingGreenlet) - that surfaced as a 500 on
        # ingest/complete. Snapshotting first keeps the finalise path off the
        # expired row entirely.
        project_id = scan.project_id
        tenant_id = scan.tenant_id
        resolved_key = stored.key or scan.upload_key
        size_bytes = int(stored.size_bytes)

        await self.scans.update_fields(
            scan_id,
            upload_key=resolved_key,
            status="uploaded",
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
    ) -> bytes:
        """Decode, decimate and pack a scan's points for the viewer.

        Reads the raw upload (E57 / LAS / LAZ) from storage, decimates it to
        ``max_points`` server-side and returns the compact OEPC binary buffer the
        browser drops into a ``THREE.Points`` geometry. Backfills ``point_count``
        and ``bbox_json`` on the row on first read so the list view shows real
        extents without re-decoding.

        Raises 404 (scan not visible / not uploaded yet), 409 (still uploading),
        501 (no reader installed for the format) or 422 (file undecodable).
        """
        from app.modules.pointcloud.decode import (
            PointDecodeError,
            PointDecodeUnavailable,
            decode_points,
        )
        from app.modules.pointcloud.wire import pack_points

        scan = await self.get_scan(scan_id, payload=payload)
        # Snapshot every field we need BEFORE any update_fields() call: that ends
        # in expire_all(), and re-reading an expired attribute on an async
        # session triggers an implicit lazy load (MissingGreenlet -> 500).
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
                raw = await self.storage.read_bytes(upload_key)
                import tempfile

                def _spill(data: bytes, suffix: str) -> str:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
                        fh.write(data)
                        return fh.name

                tmp_path = await asyncio.to_thread(_spill, raw, f".{fmt or 'bin'}")
                source_path = tmp_path
            else:
                source_path = str(local_path)

            try:
                decoded = await asyncio.to_thread(decode_points, Path(source_path), fmt, max_points=max_points)
            except PointDecodeUnavailable as exc:
                raise HTTPException(
                    status_code=status.HTTP_501_NOT_IMPLEMENTED,
                    detail={
                        "reason": "reader_unavailable",
                        "format": exc.fmt,
                        "message": (
                            f"Viewing {exc.fmt.upper()} scans needs the point-cloud reader "
                            f"({exc.reader}). Install the 'pointcloud' extra to enable it."
                        ),
                    },
                ) from exc
            except PointDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

        return buffer

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
    "guard_proxied_size",
    "reset_ingest_gate",
]
