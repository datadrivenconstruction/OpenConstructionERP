# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Programme baselines and the printable Gantt chart.

Mounted into the schedule module's main router, so these share the
``/api/v1/schedule`` prefix:

* ``POST /schedules/{id}/baselines/capture``          - snapshot the live schedule as B0, B1, ...;
* ``POST /schedules/{id}/baselines/{bid}/approve``    - make it the one approved baseline;
* ``GET  /schedules/{id}/gantt.pdf``                  - the Gantt chart as a printable PDF.

The older ``POST /baselines/`` (client-supplied snapshot) stays for
compatibility; this capture is server-authoritative.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update

from app.core.document_locale import resolve_document_locale
from app.core.register_context import document_download
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule.baseline_revisions import effective_baseline, next_baseline_label
from app.modules.schedule.schemas import BaselineCaptureRequest, BaselineResponse
from app.modules.schedule.service import ScheduleService

baseline_router = APIRouter(tags=["schedule"])

_PDF_FIELDS = (
    "id",
    "parent_id",
    "wbs_code",
    "name",
    "start_date",
    "end_date",
    "duration_days",
    "actual_start",
    "actual_end",
    "progress_pct",
    "is_critical",
    "activity_type",
    "sort_order",
)


async def _owned_schedule(session: SessionDep, schedule_id: uuid.UUID, user_id: str) -> Any:
    schedule = await ScheduleService(session).get_schedule(schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return schedule


async def _schedule_baselines(session: SessionDep, schedule_id: uuid.UUID) -> list[Any]:
    from app.modules.schedule.models import ScheduleBaseline

    rows = await session.execute(
        select(ScheduleBaseline)
        .where(ScheduleBaseline.schedule_id == schedule_id)
        .order_by(ScheduleBaseline.created_at)
    )
    return list(rows.scalars().all())


def _as_row(baseline: Any) -> dict[str, Any]:
    return {
        "id": baseline.id,
        "name": baseline.name,
        "is_active": baseline.is_active,
        "metadata": baseline.metadata_ or {},
        "created_at": baseline.created_at.isoformat() if baseline.created_at else "",
    }


async def _approve(session: SessionDep, schedule_id: uuid.UUID, baseline: Any, user_id: str) -> None:
    """Make ``baseline`` the schedule's only approved one; the snapshots stay as they were."""
    from app.modules.schedule.models import ScheduleBaseline

    await session.execute(
        update(ScheduleBaseline)
        .where(ScheduleBaseline.schedule_id == schedule_id, ScheduleBaseline.id != baseline.id)
        .values(is_active=False)
    )
    meta = dict(baseline.metadata_ or {})
    meta["approval"] = {"approved_by": user_id, "approved_at": datetime.now(UTC).isoformat(timespec="seconds")}
    baseline.metadata_ = meta
    baseline.is_active = True
    await session.flush()


@baseline_router.post(
    "/schedules/{schedule_id}/baselines/capture",
    response_model=BaselineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Capture the live schedule as the next baseline (B0, B1, ...)",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def capture_baseline(
    schedule_id: uuid.UUID,
    data: BaselineCaptureRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> BaselineResponse:
    """Snapshot activities and logic on the server, label it, optionally approve it."""
    from app.modules.schedule.models import ScheduleBaseline
    from app.modules.schedule.router import _load_activities_relationships
    from app.modules.schedule.snapshot_envelope import live_envelope

    schedule = await _owned_schedule(session, schedule_id, user_id)
    acts, rels = await _load_activities_relationships(session, schedule_id)
    if not acts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The schedule has no activities to capture.",
        )
    existing = await _schedule_baselines(session, schedule_id)
    label = next_baseline_label(b.name for b in existing)
    now = datetime.now(UTC)
    meta: dict[str, Any] = {
        "kind": "programme_baseline",
        "label": label,
        "captured_by": user_id,
        "captured_at": now.isoformat(timespec="seconds"),
        "activity_count": len(acts),
    }
    if data.note:
        meta["note"] = data.note
    baseline = ScheduleBaseline(
        schedule_id=schedule_id,
        project_id=schedule.project_id,
        name=data.name or label,
        baseline_date=(schedule.data_date or now.date().isoformat())[:20],
        snapshot_data=live_envelope(acts, rels),
        is_active=False,
        created_by=uuid.UUID(user_id),
        metadata_=meta,
    )
    session.add(baseline)
    await session.flush()
    if data.approve:
        await _approve(session, schedule_id, baseline, user_id)
    await session.refresh(baseline)
    return BaselineResponse.model_validate(baseline)


@baseline_router.post(
    "/schedules/{schedule_id}/baselines/{baseline_id}/approve",
    response_model=BaselineResponse,
    summary="Approve a baseline as the schedule's current one",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def approve_baseline(
    schedule_id: uuid.UUID,
    baseline_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> BaselineResponse:
    """Approve one baseline; every other baseline of the schedule stops being approved."""
    from app.modules.schedule.models import ScheduleBaseline

    await _owned_schedule(session, schedule_id, user_id)
    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None or baseline.schedule_id != schedule_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline not found")
    await _approve(session, schedule_id, baseline, user_id)
    await session.refresh(baseline)
    return BaselineResponse.model_validate(baseline)


def _filename(name: str, on: date) -> str:
    slug = re.sub(r"[^\w-]+", "_", name, flags=re.UNICODE).strip("_")[:60] or "schedule"
    return f"gantt_{slug}_{on.isoformat()}.pdf"


@baseline_router.get(
    "/schedules/{schedule_id}/gantt.pdf",
    summary="Export the Gantt chart as a printable PDF",
    dependencies=[Depends(RequirePermission("schedule.read"))],
    response_class=StreamingResponse,
)
async def export_gantt_pdf(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    baseline_id: uuid.UUID | None = Query(default=None, description="Defaults to the approved baseline"),
    include_baseline: bool = Query(default=True),
    paper: Literal["A3", "A4", "LETTER", "LEGAL"] = Query(default="A3"),
    locale: str | None = Query(default=None, max_length=16),
    accept_language: str | None = Header(default=None),
) -> StreamingResponse:
    """Activity table, timescale, current / baseline / actual bars, critical path and legend, landscape."""
    from app.modules.projects.models import Project
    from app.modules.schedule.gantt_pdf import GanttMeta, build_rows, pdf_locales, render_gantt_pdf
    from app.modules.schedule.models import Activity, ScheduleBaseline
    from app.modules.schedule.snapshot_envelope import normalize_envelope

    schedule = await _owned_schedule(session, schedule_id, user_id)
    project = await session.get(Project, schedule.project_id)

    chosen: Any = None
    if include_baseline:
        if baseline_id is not None:
            chosen = await session.get(ScheduleBaseline, baseline_id)
            if (
                chosen is None
                or chosen.project_id != schedule.project_id
                or chosen.schedule_id not in (None, schedule_id)
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline not found")
        else:
            rows = await _schedule_baselines(session, schedule_id)
            picked = effective_baseline([_as_row(b) for b in rows])
            chosen = next((b for b in rows if picked and b.id == picked["id"]), None)

    acts = (await session.execute(select(Activity).where(Activity.schedule_id == schedule_id))).scalars().all()
    activities = [{key: getattr(a, key, None) for key in _PDF_FIELDS} for a in acts]
    rows_out = build_rows(activities, normalize_envelope(chosen.snapshot_data) if chosen else None)

    today = datetime.now(UTC).date()
    data_date: date | None = None
    if schedule.data_date:
        try:
            data_date = date.fromisoformat(str(schedule.data_date)[:10])
        except ValueError:
            data_date = None
    lang = resolve_document_locale(locale, accept_language, pdf_locales(), "en")
    meta = GanttMeta(
        project_name=project.name if project else "",
        schedule_name=schedule.name,
        baseline_label=chosen.name if chosen else None,
        exported_on=today,
        data_date=data_date,
    )
    pdf = render_gantt_pdf(rows_out, meta, paper=paper, locale=lang)
    return document_download(pdf, _filename(schedule.name, today), lang, "application/pdf")
