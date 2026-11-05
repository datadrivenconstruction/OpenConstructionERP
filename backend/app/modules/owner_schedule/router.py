# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule API routes (mounted at ``/api/v1/owner_schedule``).

Reads need ``owner_schedule.read``; import, addenda, export and saving a
profile need ``owner_schedule.write``. Every BOQ route checks project access.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.boq.models import BOQ
from app.modules.owner_schedule.engine import MAX_FILE_BYTES
from app.modules.owner_schedule.profile import profile_json_schema
from app.modules.owner_schedule.schemas import (
    AddendumApplied,
    AddendumPreview,
    CheckReport,
    DetectCandidate,
    ImportResult,
    PreviewResponse,
    ProfileListResponse,
    ProfileSummary,
    ScheduleStatus,
)
from app.modules.owner_schedule.service import OwnerScheduleService

router = APIRouter(tags=["owner_schedule"])

_READ = Depends(RequirePermission("owner_schedule.read"))
_WRITE = Depends(RequirePermission("owner_schedule.write"))


async def _read(file: UploadFile) -> bytes:
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file is larger than 10 MB")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty file")
    return content


async def _access(session: SessionDep, boq_id: uuid.UUID, user_id: str) -> None:
    boq = await session.get(BOQ, boq_id)
    if boq is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    await verify_project_access(boq.project_id, user_id, session)


@router.get("/profiles", dependencies=[_READ], response_model=ProfileListResponse)
async def list_profiles(
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """Platform, pack and saved profiles."""
    profiles = await OwnerScheduleService(session).profiles()
    page = profiles[offset : offset + limit]
    return {
        "items": [p.model_dump(include={"key", "name", "source", "file_type", "handled_by"}) for p in page],
        "total": len(profiles),
        "offset": offset,
        "limit": limit,
    }


@router.get("/profiles/schema", dependencies=[_READ])
async def get_profile_schema() -> dict[str, Any]:
    """JSON schema of a profile, for packs and the mapping wizard."""
    return profile_json_schema()


@router.post("/profiles", dependencies=[_WRITE], response_model=ProfileSummary, status_code=201)
async def save_profile(definition: dict[str, Any], session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Save a profile built in the mapping wizard, to reuse on the owner's next schedule."""
    try:
        prof = await OwnerScheduleService(session).save_profile(definition, user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    await session.commit()
    return prof.model_dump(include={"key", "name", "source", "file_type", "handled_by"})


@router.post("/detect", dependencies=[_READ], response_model=list[DetectCandidate])
async def detect(session: SessionDep, file: UploadFile = File(...)) -> list[dict[str, Any]]:
    """Score every profile against the file. The user confirms the choice."""
    return await OwnerScheduleService(session).detect(await _read(file), file.filename or "")


@router.post("/preview", dependencies=[_READ], response_model=PreviewResponse)
async def preview(
    session: SessionDep, file: UploadFile = File(...), profile_key: str = Form(..., max_length=80)
) -> dict[str, Any]:
    """Read the pay items under one profile and list the issues. Nothing is stored."""
    res = await OwnerScheduleService(session).preview(await _read(file), file.filename or "", profile_key)
    return {
        "profile_key": res.profile_key,
        "sheet": res.sheet,
        "header_row": res.header_row,
        "columns": res.columns,
        "item_count": len([ln for ln in res.lines if not ln.is_section]),
        "lines": [ln.as_dict() for ln in res.lines],
        "issues": res.issues,
    }


@router.get("/boqs/{boq_id}", dependencies=[_READ], response_model=ScheduleStatus)
async def get_status(boq_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The owner schedule on a BOQ: items, prices, x of y priced, findings."""
    await _access(session, boq_id, user_id)
    return await OwnerScheduleService(session).status_of(boq_id)


@router.post("/boqs/{boq_id}/import", dependencies=[_WRITE], response_model=ImportResult, status_code=201)
async def import_schedule(
    boq_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    profile_key: str = Form(..., max_length=80),
) -> dict[str, Any]:
    """Create the owner's pay items in the BOQ (or link lines whose number already matches)."""
    await _access(session, boq_id, user_id)
    out = await OwnerScheduleService(session).import_schedule(
        boq_id, await _read(file), file.filename or "schedule", profile_key, user_id
    )
    await session.commit()
    return out


@router.post("/boqs/{boq_id}/addendum/preview", dependencies=[_READ], response_model=AddendumPreview)
async def addendum_preview(
    boq_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, file: UploadFile = File(...)
) -> dict[str, Any]:
    """Compare a revised schedule with the one on file: added, removed and changed items."""
    await _access(session, boq_id, user_id)
    return await OwnerScheduleService(session).addendum_preview(boq_id, await _read(file), file.filename or "")


@router.post("/boqs/{boq_id}/addendum/apply", dependencies=[_WRITE], response_model=AddendumApplied)
async def addendum_apply(
    boq_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    item_nos: str | None = Form(default=None, description="JSON list of item numbers to apply; empty = all"),
) -> dict[str, Any]:
    """Apply the chosen addendum changes; the revised file becomes the export template."""
    await _access(session, boq_id, user_id)
    chosen = None
    if item_nos:
        try:
            chosen = [str(x) for x in json.loads(item_nos)]
        except (ValueError, TypeError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="item_nos must be a JSON list") from exc
    out = await OwnerScheduleService(session).apply_addendum(boq_id, await _read(file), file.filename or "", chosen)
    await session.commit()
    return out


@router.get("/boqs/{boq_id}/export", dependencies=[_WRITE])
async def export_schedule(boq_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    """The owner's file with the prices filled in, ready for the owner's portal."""
    await _access(session, boq_id, user_id)
    content, name, _ = await OwnerScheduleService(session).export(boq_id)
    media = (
        "text/csv"
        if name.lower().endswith(".csv")
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(content, media_type=media, headers={"Content-Disposition": attachment_disposition(name)})


@router.get("/boqs/{boq_id}/check", dependencies=[_READ], response_model=CheckReport)
async def check_report(boq_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """What the export writes, cell by cell, the totals and the open findings."""
    await _access(session, boq_id, user_id)
    return await OwnerScheduleService(session).check_report(boq_id)
