# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sensor evidence routes (included in the site sensors router).

POST /devices/{id}/evidence?from=&to=   - Cut the window, hash it, file CSV and PDF as project documents
GET  /strips/bim-status/                - BIM element id to strike status, for a viewer overlay
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.register_context import AcceptLanguageHeader, LocaleQuery, generated_now, load_project_header
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.site_sensors import evidence
from app.modules.site_sensors.service import SiteSensorsService

router = APIRouter()

_STATUS = {"window_reversed": 422, "window_too_long": 422, "no_readings": 404}


class EvidenceFiled(BaseModel):
    """The two documents an export filed and the integrity code of the CSV."""

    device_id: uuid.UUID
    csv_document_id: uuid.UUID
    pdf_document_id: uuid.UUID
    csv_sha256: str
    readings: int


@router.post("/devices/{device_id}/evidence", response_model=EvidenceFiled, status_code=201)
async def file_evidence(
    device_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    start: datetime = Query(alias="from"),
    end: datetime = Query(alias="to"),
    claim_ref: str = Query(default="", max_length=200),
    alert_id: uuid.UUID | None = Query(default=None),
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
    _perm: None = Depends(RequirePermission("site_sensors.record")),
) -> EvidenceFiled:
    """Export a device's readings for a window as a hashed CSV and a PDF, filed under Monitoring evidence."""
    service = SiteSensorsService(session)
    try:
        device = await service.get_device(device_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await verify_project_access(device.project_id, user_id, session)
    doc_locale = evidence._catalogue().resolve(locale, accept_language)
    project = await load_project_header(session, device.project_id)
    limit, _ = await service.limit_of(device)
    try:
        filed = await evidence.file_device_evidence(
            session,
            device,
            start,
            end,
            user_id=str(user_id),
            locale=doc_locale,
            claim_ref=claim_ref.strip(),
            alert_id=alert_id,
            generated=generated_now(evidence._catalogue().tr(doc_locale, "datetime_format"), project),
            project=project,
            limit=limit,
        )
    except evidence.EvidenceError as exc:
        key = str(exc.args[0])
        raise HTTPException(status_code=_STATUS.get(key, 422), detail=key) from exc
    return EvidenceFiled(
        device_id=device.id,
        csv_document_id=filed.csv_document.id,
        pdf_document_id=filed.pdf_document.id,
        csv_sha256=filed.csv_sha256,
        readings=filed.reading_count,
    )


@router.get("/strips/bim-status/")
async def strip_bim_status(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> dict[str, str]:
    """BIM element id to the status of its latest formwork strike."""
    await verify_project_access(project_id, user_id, session)
    return await evidence.strike_status_by_element(session, project_id)
