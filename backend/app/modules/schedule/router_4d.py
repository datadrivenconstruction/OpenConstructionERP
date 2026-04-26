"""4D module HTTP API (Section 6 — MVP slice).

Two routers are exported here so :mod:`app.main` can mount them under the
``/api/v2/`` surface called out in the spec:

* :data:`schedules_v2_router`         — ``/api/v2/schedules/...``
* :data:`eac_schedule_links_router`   — ``/api/v2/eac/schedule-links/...``

The router defers business logic to :mod:`service_4d`. Tenant / project
authorisation re-uses the existing helpers from the v1 schedule router.

The routes intentionally cover the MVP surface only. PMXML / MSPDI / video
export / AI auto-suggest are not wired up — see the section deliverables note
for the deferred slice list.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.dependencies import CurrentUserId, SessionDep
from app.modules.schedule.models import (
    EAC_LINK_MODES,
    Activity,
    EacScheduleLink,
    Schedule,
)
from app.modules.schedule.service_4d import (
    EacScheduleLinkService,
    ScheduleDashboardService,
    ScheduleProgressService,
    ScheduleSnapshotService,
    import_schedule_csv,
)

logger = logging.getLogger(__name__)


schedules_v2_router = APIRouter(prefix="/schedules", tags=["4D Schedules"])
eac_schedule_links_router = APIRouter(
    prefix="/eac/schedule-links", tags=["4D EAC Schedule Links"]
)


# ── Pydantic schemas (router-local — kept here to avoid bloating the v1 module) ──


class EacScheduleLinkCreate(BaseModel):
    """Body for POST /api/v2/eac/schedule-links."""

    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    rule_id: uuid.UUID | None = None
    predicate_json: dict[str, Any] | None = None
    mode: str = Field(default="partial_match")
    model_version_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _ensure_selector(self) -> EacScheduleLinkCreate:
        if self.rule_id is None and self.predicate_json is None:
            raise ValueError("either rule_id or predicate_json is required")
        if self.mode not in EAC_LINK_MODES:
            raise ValueError(
                f"mode must be one of {EAC_LINK_MODES}, got {self.mode!r}"
            )
        return self


class EacScheduleLinkResponse(BaseModel):
    """Slim response payload for an :class:`EacScheduleLink`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    rule_id: uuid.UUID | None
    predicate_json: dict[str, Any] | None
    mode: str
    matched_element_count: int
    last_resolved_at: datetime | None


class DryRunRequest(BaseModel):
    """Body for POST /api/v2/eac/schedule-links/{id}:dry-run."""

    model_version_id: uuid.UUID | None = None


class DryRunResponse(BaseModel):
    matched_element_ids: list[str]
    matched_count: int


class CsvImportResponse(BaseModel):
    activities_created: int
    activities_failed: int
    warnings: list[str] = Field(default_factory=list)


class ProgressEntryRequest(BaseModel):
    progress_percent: float = Field(..., ge=0.0, le=100.0)
    notes: str | None = Field(default=None, max_length=4000)
    photo_attachment_ids: list[str] = Field(default_factory=list)
    geolocation: dict[str, Any] | None = None
    device: str = Field(default="desktop")
    actual_start_date: str | None = None
    actual_finish_date: str | None = None


class ProgressEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    recorded_at: datetime
    progress_percent: float
    notes: str | None
    device: str
    actual_start_date: str | None
    actual_finish_date: str | None


# ── Helpers ────────────────────────────────────────────────────────────────


def _link_to_response(link: EacScheduleLink) -> EacScheduleLinkResponse:
    return EacScheduleLinkResponse(
        id=link.id,
        task_id=link.task_id,
        rule_id=link.rule_id,
        predicate_json=link.predicate_json,
        mode=link.mode,
        matched_element_count=link.matched_element_count,
        last_resolved_at=link.last_resolved_at,
    )


def _parse_as_of(as_of_date: str | None) -> date:
    if not as_of_date:
        return date.today()
    try:
        return date.fromisoformat(as_of_date[:10])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"as_of_date must be ISO YYYY-MM-DD, got {as_of_date!r}",
        ) from exc


# ── Schedules v2 router ────────────────────────────────────────────────────


@schedules_v2_router.post(
    "/{schedule_id}/import",
    response_model=CsvImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
) -> CsvImportResponse:
    """Import a CSV schedule (FR-6.1, MVP).

    PMXML / MSPDI / Excel parsing is not wired up in this slice; clients
    should pre-convert to the canonical CSV column set or use the existing
    v1 import endpoints for those formats.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only CSV uploads are supported in this MVP slice. Use the v1 endpoints for PMXML/MSPDI.",
        )
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    try:
        outcome = await import_schedule_csv(
            session, schedule_id=schedule_id, csv_text=text
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await session.commit()
    return CsvImportResponse(
        activities_created=outcome.activities_created,
        activities_failed=outcome.activities_failed,
        warnings=outcome.warnings,
    )


@schedules_v2_router.post(
    "/tasks/{task_id}/progress",
    response_model=ProgressEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_progress(
    task_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: ProgressEntryRequest = Body(...),
) -> ProgressEntryResponse:
    """Append a progress entry to ``task_id`` and roll forward the activity."""
    service = ScheduleProgressService(session)
    try:
        entry = await service.record(
            task_id=task_id,
            progress_percent=body.progress_percent,
            notes=body.notes,
            photo_attachment_ids=body.photo_attachment_ids,
            geolocation=body.geolocation,
            device=body.device,
            recorded_by_user_id=uuid.UUID(user_id) if user_id else None,
            actual_start_date=body.actual_start_date,
            actual_finish_date=body.actual_finish_date,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await session.commit()
    await session.refresh(entry)
    return ProgressEntryResponse(
        id=entry.id,
        task_id=entry.task_id,
        recorded_at=entry.recorded_at,
        progress_percent=float(entry.progress_percent),
        notes=entry.notes,
        device=entry.device,
        actual_start_date=entry.actual_start_date,
        actual_finish_date=entry.actual_finish_date,
    )


@schedules_v2_router.get("/tasks/{task_id}/progress-history")
async def list_progress_history(
    task_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[dict[str, Any]]:
    """Return the append-only progress history for ``task_id``."""
    service = ScheduleProgressService(session)
    entries = await service.history(task_id)
    return [
        {
            "id": str(e.id),
            "task_id": str(e.task_id),
            "recorded_at": e.recorded_at.isoformat() if e.recorded_at else None,
            "progress_percent": float(e.progress_percent),
            "notes": e.notes,
            "device": e.device,
            "actual_start_date": e.actual_start_date,
            "actual_finish_date": e.actual_finish_date,
        }
        for e in entries
    ]


@schedules_v2_router.get("/{schedule_id}/snapshot")
async def get_snapshot(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    as_of_date: str | None = Query(default=None),
    model_version_id: uuid.UUID | None = Query(default=None),
) -> dict[str, Any]:
    """Return ``{element_id: status}`` for every linked element on ``as_of_date``."""
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found",
        )
    target = _parse_as_of(as_of_date)
    service = ScheduleSnapshotService(session)
    statuses = await service.snapshot(
        schedule_id, target, model_version_id
    )
    return {
        "schedule_id": str(schedule_id),
        "as_of_date": target.isoformat(),
        "model_version_id": str(model_version_id) if model_version_id else None,
        "elements": statuses,
    }


@schedules_v2_router.get("/{schedule_id}/dashboard")
async def get_dashboard(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    as_of_date: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return the planned-vs-actual dashboard for ``schedule_id``."""
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found",
        )
    target = _parse_as_of(as_of_date)
    service = ScheduleDashboardService(session)
    return (await service.dashboard(schedule_id, target)).to_json()


# ── EAC schedule links router ──────────────────────────────────────────────


@eac_schedule_links_router.post(
    "",
    response_model=EacScheduleLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_link(
    session: SessionDep,
    user_id: CurrentUserId,
    body: EacScheduleLinkCreate = Body(...),
) -> EacScheduleLinkResponse:
    """Create an EAC schedule link and run a dry-run for the cached count."""
    activity = await session.get(Activity, body.task_id)
    if activity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Activity {body.task_id} not found",
        )

    service = EacScheduleLinkService(session)
    try:
        link, _ = await service.create(
            task_id=body.task_id,
            rule_id=body.rule_id,
            predicate_json=body.predicate_json,
            mode=body.mode,
            updated_by_user_id=uuid.UUID(user_id) if user_id else None,
            model_version_id=body.model_version_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await session.commit()
    await session.refresh(link)
    return _link_to_response(link)


@eac_schedule_links_router.get("/{link_id}", response_model=EacScheduleLinkResponse)
async def get_link(
    link_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> EacScheduleLinkResponse:
    service = EacScheduleLinkService(session)
    link = await service.get(link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Link {link_id} not found",
        )
    return _link_to_response(link)


@eac_schedule_links_router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    service = EacScheduleLinkService(session)
    link = await service.get(link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Link {link_id} not found",
        )
    await service.delete(link_id)
    await session.commit()


@eac_schedule_links_router.post(
    "/{link_id}:dry-run", response_model=DryRunResponse
)
async def dry_run_link(
    link_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: DryRunRequest = Body(default_factory=DryRunRequest),
) -> DryRunResponse:
    """Re-resolve a saved link's selector — no DB writes other than caching."""
    service = EacScheduleLinkService(session)
    link = await service.get(link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Link {link_id} not found",
        )
    outcome = await service.dry_run(link, body.model_version_id)
    link.matched_element_count = outcome.matched_count
    await session.commit()
    return DryRunResponse(
        matched_element_ids=outcome.matched_element_ids,
        matched_count=outcome.matched_count,
    )


__all__ = [
    "eac_schedule_links_router",
    "schedules_v2_router",
]
