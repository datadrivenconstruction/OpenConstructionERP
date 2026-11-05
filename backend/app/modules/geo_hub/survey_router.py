# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Site survey capture endpoints, mounted by ``router.py`` under ``/surveys``."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep
from app.modules.geo_hub import survey_service
from app.modules.geo_hub.schemas import (
    SurveyCaptureListResponse,
    SurveyCapturePatch,
    SurveyCaptureResponse,
    SurveyFromScan,
    SurveyObservationResponse,
    SurveyObservationUpsert,
    SurveyProgressListResponse,
)
from app.modules.geo_hub.survey_service import SurveyService

survey_router = APIRouter(tags=["geo_hub_surveys"])


def _svc(session: SessionDep) -> SurveyService:
    return SurveyService(session)


async def _read_capped(file: UploadFile) -> bytes:
    """Read an upload in chunks and refuse it as soon as it passes the ceiling."""
    limit = survey_service.MAX_SURVEY_UPLOAD_BYTES
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The GeoTIFF is over the upload limit")
        chunks.append(chunk)
    return b"".join(chunks)


@survey_router.post("/orthophoto", response_model=SurveyCaptureResponse, status_code=201)
async def upload_orthophoto(
    project_id: uuid.UUID = Form(...),
    captured_on: date = Form(...),
    platform: Literal["drone", "aircraft", "ground", "other"] = Form(default="drone"),
    name: str | None = Form(default=None),
    file: UploadFile = File(...),
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.create")),
) -> SurveyCaptureResponse:
    """Upload a GeoTIFF orthophoto; the header is read for CRS, footprint and GSD."""
    content = await _read_capped(file)
    return await service.create_orthophoto(
        project_id,
        filename=file.filename or "orthophoto.tif",
        content=content,
        captured_on=captured_on,
        platform=platform,
        name=name,
        payload=payload,
    )


@survey_router.post("/from-scan", response_model=SurveyCaptureResponse, status_code=201)
async def survey_from_scan(
    body: SurveyFromScan,
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.create")),
) -> SurveyCaptureResponse:
    """Register an existing point cloud scan as a dated survey."""
    return await service.create_from_scan(body, payload)


@survey_router.get("/", response_model=SurveyCaptureListResponse)
async def list_surveys(
    project_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> SurveyCaptureListResponse:
    return await service.list_captures(project_id, payload, offset=offset, limit=limit)


@survey_router.get("/{survey_id}", response_model=SurveyCaptureResponse)
async def get_survey(
    survey_id: uuid.UUID,
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> SurveyCaptureResponse:
    return await service.get_response(survey_id, payload)


@survey_router.patch("/{survey_id}", response_model=SurveyCaptureResponse)
async def update_survey(
    survey_id: uuid.UUID,
    body: SurveyCapturePatch,
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.update")),
) -> SurveyCaptureResponse:
    return await service.update_capture(survey_id, body, payload)


@survey_router.delete("/{survey_id}", status_code=204)
async def delete_survey(
    survey_id: uuid.UUID,
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.delete")),
) -> None:
    """Remove the survey and the overlay it created; a linked scan stays."""
    await service.delete_capture(survey_id, payload)


@survey_router.put("/{survey_id}/observations/{activity_id}", response_model=SurveyObservationResponse)
async def put_observation(
    survey_id: uuid.UUID,
    activity_id: uuid.UUID,
    body: SurveyObservationUpsert,
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.update")),
) -> SurveyObservationResponse:
    """Record, or replace, the observed percentage for one activity (stamps who and when)."""
    row = await service.upsert_observation(survey_id, activity_id, body, payload)
    return SurveyObservationResponse.model_validate(row)


@survey_router.get("/{survey_id}/progress", response_model=SurveyProgressListResponse)
async def survey_progress(
    survey_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    service: SurveyService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> SurveyProgressListResponse:
    """Planned vs observed progress per schedule activity on the capture date."""
    return await service.progress(survey_id, payload, offset=offset, limit=limit)
