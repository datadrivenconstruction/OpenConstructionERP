# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Point Cloud / Reality Capture API routes.

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

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep
from app.modules.pointcloud.schemas import (
    PresignedPart,
    ScanDatasetList,
    ScanDatasetRead,
    ScanDeviationRead,
    ScanDeviationSummary,
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


@router.delete("/scans/{scan_id}", status_code=204)
async def delete_scan(
    scan_id: uuid.UUID,
    service: PointCloudService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("pointcloud.delete")),
) -> Response:
    """Delete a scan, its registrations and its object-storage artifacts.

    Gated by ``pointcloud.delete`` (MANAGER+) and, in the service, by tenant +
    project access, so a cross-tenant or unknown id collapses to 404 rather than
    leak scan existence. Sweeps the scan's per-scan storage prefix (raw upload
    plus any derived COPC / tileset / DTM blobs) before removing the row, so the
    delete frees storage and never strands a ghost in the scan list. Returns 204
    with no body on success.
    """
    await service.delete_scan(scan_id, payload=payload)
    return Response(status_code=204)


@router.get(
    "/scans/{scan_id}/points",
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "OEPC binary point buffer"},
        409: {"description": "Scan is still uploading"},
        413: {"description": "Scan is too large to preview inline (too many bytes or points)"},
        501: {"description": "No reader installed for the scan format"},
    },
)
async def get_scan_points(
    scan_id: uuid.UUID,
    max_points: int = Query(
        default=1_500_000,
        ge=10_000,
        le=6_000_000,
        description="Server-side decimation cap. The scan is evenly downsampled to at most this many points.",
    ),
    service: PointCloudService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("pointcloud.read")),
) -> Response:
    """Stream a scan's decimated points as a compact binary buffer.

    Decodes E57 / LAS / LAZ server-side, decimates to ``max_points`` and returns
    the OEPC little-endian buffer the viewer reads in one pass. The body is not
    JSON; it is ``application/octet-stream``. Gated by tenant + project access.
    """
    result = await service.get_points(scan_id, max_points=max_points, payload=payload)
    return Response(
        content=result.buffer,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{scan_id}.oepc"',
            # Decimated points are immutable for a given (scan, cap); let the
            # browser cache the buffer so re-opening the viewer is instant.
            "Cache-Control": "private, max-age=3600",
            # Truncation signal: the preview is decimated to at most max_points,
            # so report the full count and whether the buffer is a subsample - a
            # user must never mistake a decimated cloud for the whole scan.
            "X-Point-Count-Total": str(result.total_count),
            "X-Point-Count-Returned": str(result.returned_count),
            "X-Point-Truncated": "true" if result.truncated else "false",
        },
    )


# ── Scan-vs-design deviation overlay ───────────────────────────────────────


@router.get("/deviation", response_model=ScanDeviationSummary)
async def get_model_deviation(
    project_id: uuid.UUID = Query(
        ...,
        description="Project the design model belongs to (IDOR-scoped).",
    ),
    model_id: str = Query(
        ...,
        min_length=1,
        description="Design model id whose as-built scan deviation to fetch.",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: PointCloudService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("pointcloud.read")),
) -> ScanDeviationSummary:
    """Return the scan-vs-design deviation rollup for a design model.

    Drives the viewer's as-built-vs-design deviation overlay + legend: every
    scan aligned to this model contributes a deviation row classified into a
    traffic-light severity (within / warning / over / unknown), rolled up to
    the model's worst severity. Reuses the deviation already computed on each
    ``ScanRegistration`` row - no math is recomputed here.

    Tenant + project access is enforced in the service the IDOR-safe way: an
    unknown or cross-tenant project collapses to 404. A model the caller can
    see but that has no aligned scans yet returns a well-formed summary with
    ``has_deviation=false`` (not a 404), so the viewer simply shows no overlay.
    """
    summary = await service.list_deviations_for_model(
        project_id,
        model_id,
        payload=payload,
        offset=offset,
        limit=limit,
    )
    return ScanDeviationSummary(
        model_id=summary["model_id"],
        project_id=summary["project_id"],
        has_deviation=summary["has_deviation"],
        worst_severity=summary["worst_severity"],
        worst_severity_color=summary["worst_severity_color"],
        items=[ScanDeviationRead(**item) for item in summary["items"]],
        total=summary["total"],
    )


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
    or proprietary (.rcp/.rcs scan container) format, and 404 when the project
    is not visible to the caller.
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
