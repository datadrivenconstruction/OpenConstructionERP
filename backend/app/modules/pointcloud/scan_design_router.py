# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scan to surface, scan against design, and cloud to quantities; included by the pointcloud router.

Endpoints (under ``/api/v1/pointcloud``):
    POST /scans/{scan_id}/surface                   - grid a stored scan (E57/LAS/LAZ) into a survey surface
    POST /projects/{project_id}/surfaces/cloud      - an uploaded E57/LAS/LAZ file straight to a surface
    POST /scans/{scan_id}/deviation-reports         - compare against a design surface, store the report
    GET  /scans/{scan_id}/deviation-reports         - the scan's comparisons
    GET  /deviation-reports/{report_id}             - one report with its heat grid
    GET  /deviation-reports/{report_id}/points      - the cloud coloured by deviation band (OEPC)
    GET  /deviation-reports/{report_id}/export      - CSV or PDF
    POST /scans/{scan_id}/cutfill/preview           - cut and fill against the design, nothing stored
    POST /scans/{scan_id}/cutfill                   - scan surface + draft volume for confirm and send-to-BOQ
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.pointcloud.scan_design_schemas import (
    CutFillCreated,
    CutFillPreview,
    CutFillRequest,
    DeviationReportList,
    DeviationReportOut,
    DeviationRequest,
    ScanSurfaceRequest,
)
from app.modules.pointcloud.scan_design_service import ScanDesignService
from app.modules.surfaces_volumes.schemas import CloudImportResult

router = APIRouter(tags=["pointcloud"])

_READ = [Depends(RequirePermission("pointcloud.read"))]
_WRITE = [Depends(RequirePermission("pointcloud.write"))]
_SURVEY = [Depends(RequirePermission("pointcloud.write")), Depends(RequirePermission("survey.write"))]
MAX_CLOUD_BYTES = 2 * 1024 * 1024 * 1024
_SUFFIXES = (".e57", ".las", ".laz")


@router.post(
    "/scans/{scan_id}/surface",
    response_model=CloudImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=_SURVEY,
)
async def scan_to_surface(
    scan_id: uuid.UUID,
    body: ScanSurfaceRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    locale: str = Query("en", max_length=10),
) -> CloudImportResult:
    return await ScanDesignService(session).scan_surface(scan_id, body, payload, user_id, locale)


@router.post(
    "/projects/{project_id}/surfaces/cloud",
    response_model=CloudImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("survey.write"))],
)
async def upload_cloud_surface(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    name: str = Form("", max_length=255),
    cell_size_m: float = Form(0.5, gt=0, le=100),
    stat: str = Form("min"),
    ground_only: bool = Form(True),
    locale: str = Query("en", max_length=10),
) -> CloudImportResult:
    await verify_project_access(project_id, user_id, session)
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(_SUFFIXES):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Upload an .e57, .las or .laz file"
        )
    if stat not in ("min", "mean", "max"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="stat is min, mean or max")
    if file.size is not None and file.size > MAX_CLOUD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is over 2 GB")
    body = ScanSurfaceRequest(name=name, cell_size_m=cell_size_m, stat=stat, ground_only=ground_only)  # type: ignore[arg-type]
    return await ScanDesignService(session).upload_surface(project_id, file.file, filename[:255], body, user_id, locale)


@router.post(
    "/scans/{scan_id}/deviation-reports",
    response_model=DeviationReportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def compare_scan(
    scan_id: uuid.UUID,
    body: DeviationRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    markets: ActiveMarkets,
    locale: str = Query("en", max_length=10),
) -> DeviationReportOut:
    return await ScanDesignService(session).compare(scan_id, body, payload, user_id, markets, locale)


@router.get("/scans/{scan_id}/deviation-reports", response_model=DeviationReportList, dependencies=_READ)
async def list_reports(
    scan_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    locale: str = Query("en", max_length=10),
) -> DeviationReportList:
    return await ScanDesignService(session).list_reports(scan_id, payload, locale)


@router.get("/deviation-reports/{report_id}", response_model=DeviationReportOut, dependencies=_READ)
async def get_report(
    report_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    locale: str = Query("en", max_length=10),
) -> DeviationReportOut:
    return await ScanDesignService(session).get_report(report_id, payload, locale)


@router.get(
    "/deviation-reports/{report_id}/points",
    dependencies=_READ,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "OEPC buffer, colour = band"}},
)
async def report_points(
    report_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    max_points: int = Query(1_000_000, ge=10_000, le=6_000_000),
) -> Response:
    buffer, total, returned = await ScanDesignService(session).report_points(report_id, payload, max_points)
    return Response(
        content=buffer,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Point-Count-Total": str(total),
            "X-Point-Count-Returned": str(returned),
            "X-Point-Truncated": "true" if returned < total else "false",
        },
    )


@router.get("/deviation-reports/{report_id}/export", dependencies=_READ, response_model=None)
async def export_report(
    report_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    format: str = Query("pdf", pattern="^(pdf|csv)$"),  # noqa: A002 - public query name
    locale: str = Query("en", max_length=10),
) -> Response:
    content, media, name = await ScanDesignService(session).report_export(report_id, payload, format, locale)
    return Response(
        content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.post("/scans/{scan_id}/cutfill/preview", response_model=CutFillPreview, dependencies=_READ)
async def cutfill_preview(
    scan_id: uuid.UUID, body: CutFillRequest, session: SessionDep, payload: CurrentUserPayload
) -> CutFillPreview:
    return await ScanDesignService(session).cutfill_preview(scan_id, body, payload)


@router.post(
    "/scans/{scan_id}/cutfill",
    response_model=CutFillCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=_SURVEY,
)
async def cutfill_create(
    scan_id: uuid.UUID,
    body: CutFillRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    locale: str = Query("en", max_length=10),
) -> CutFillCreated:
    return await ScanDesignService(session).cutfill_create(scan_id, body, payload, user_id, locale)
