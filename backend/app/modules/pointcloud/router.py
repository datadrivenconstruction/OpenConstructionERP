# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud / Reality Capture API routes.

Mounted by the module loader at ``/api/v1/pointcloud/``. All routes are
RBAC-gated; the service layer additionally closes cross-tenant IDOR holes by
404-ing project-mismatched accesses.

Phase 0 wires the read surface (list scans by project, get one scan) and the
presigned-direct-to-MinIO multipart ingest surface (init + complete). The bytes
go straight to object storage; the FastAPI core only mints the key, hands back
presigned part URLs and finalises the multipart upload. The converter wiring and
measurement surface land in later phases.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep
from app.modules.pointcloud.schemas import (
    PresignedPart,
    ScanDatasetList,
    ScanDatasetRead,
    ScanIngestComplete,
    ScanIngestCompleteResponse,
    ScanIngestInit,
    ScanIngestInitResponse,
)
from app.modules.pointcloud.service import PointCloudService

router = APIRouter(tags=["pointcloud"])


def _svc(session: SessionDep) -> PointCloudService:
    return PointCloudService(session)


# ── Scans ─────────────────────────────────────────────────────────────────


@router.get("/scans", response_model=ScanDatasetList)
async def list_scans(
    project_id: uuid.UUID = Query(
        ...,
        description="Project whose reality-capture scans to list.",
    ),
    scan_status: str | None = Query(
        default=None,
        description="Optional lifecycle filter: uploading / uploaded / converting / ready / failed.",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: PointCloudService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("pointcloud.read")),
) -> ScanDatasetList:
    """List reality-capture scans for a project, tenant-scoped.

    Returns an empty list (not a 404) for a project the caller can see but that
    has no scans yet, so the UI renders its guided empty state.
    """
    rows, total = await service.list_scans(
        project_id,
        payload=payload,
        scan_status=scan_status,
        offset=offset,
        limit=limit,
    )
    return ScanDatasetList(
        items=[ScanDatasetRead.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/scans/{scan_id}", response_model=ScanDatasetRead)
async def get_scan(
    scan_id: uuid.UUID,
    service: PointCloudService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("pointcloud.read")),
) -> ScanDatasetRead:
    """Fetch one reality-capture scan, gated by tenant + project access."""
    scan = await service.get_scan(scan_id, payload=payload)
    return ScanDatasetRead.model_validate(scan)


# ── Presigned-direct-to-MinIO multipart ingest ─────────────────────────────


@router.post(
    "/scans/ingest/init",
    response_model=ScanIngestInitResponse,
    status_code=201,
)
async def init_ingest(
    body: ScanIngestInit,
    service: PointCloudService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("pointcloud.write")),
) -> ScanIngestInitResponse:
    """Open a presigned-direct-to-MinIO multipart upload for a new scan.

    Registers the scan in status=uploading and returns one presigned PUT URL per
    part. The browser / CLI uploads each 5-200 GB part straight to object
    storage; the backend never proxies the bytes. Returns 429 when too many
    uploads are being prepared at once (back-pressure), 422 for an unsupported
    or proprietary (ReCap RCP/RCS) format, and 404 when the project is not
    visible to the caller.
    """
    result = await service.init_ingest(body, payload=payload)
    return ScanIngestInitResponse(
        scan_id=result["scan_id"],
        upload_id=result["upload_id"],
        upload_key=result["upload_key"],
        part_size_bytes=result["part_size_bytes"],
        parts=[PresignedPart(**p) for p in result["parts"]],
        expires_at=result["expires_at"],
    )


@router.post(
    "/scans/{scan_id}/ingest/complete",
    response_model=ScanIngestCompleteResponse,
)
async def complete_ingest(
    scan_id: uuid.UUID,
    body: ScanIngestComplete,
    service: PointCloudService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("pointcloud.write")),
) -> ScanIngestCompleteResponse:
    """Finalise the multipart upload and flip the scan to status=uploaded.

    Echo back the ``upload_id`` from init and the list of uploaded parts (each
    with the ETag the storage PUT returned). Returns 404 when the scan is not
    visible to the caller, 409 when the scan is no longer awaiting an upload, and
    422 when the part list is non-contiguous or storage rejects the completion.
    """
    result = await service.complete_ingest(scan_id, body, payload=payload)
    return ScanIngestCompleteResponse(
        scan_id=result["scan_id"],
        upload_key=result["upload_key"],
        status=result["status"],
        size_bytes=result["size_bytes"],
    )
