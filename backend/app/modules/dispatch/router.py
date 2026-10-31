# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board API routes (auto-mounted at /api/v1/dispatch).

Endpoints:
    GET/POST   /locations, PATCH /locations/{id}   board columns
    GET/POST   /crews, PATCH /crews/{id}           crews of people
    GET        /cards?kind=&q=                     cards to drag on, paginated
    GET        /board?day=                         one day: columns, cards, conflicts, moves to come
    GET        /week?start=                        seven days
    POST       /placements                         put cards on a column (multi-select)
    POST       /placements/move                    drag cards to another column
    PATCH      /placements/{id}                    start time, notes, operator
    POST       /placements/remove                  take cards off the board
    POST       /copy-day                           repeat a day (yesterday) on another
    GET/POST   /moves, POST /moves/{id}/cancel     moves booked ahead
    POST       /moves/apply                        apply due moves now (also runs on board reads)
    GET        /plan?day=, /plan/pdf?day=          daily plan per foreman, printable
    POST       /plan/share?day=                    notify foremen through the platform channels
    POST       /timesheet-prefill                  draft the site timesheet from the board
    GET        /utilisation?start=&end=            days on a job vs idle per unit
    GET        /validate?day=                      run the dispatch rule set
    GET/PUT    /preferences                        per-user card density
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.dispatch.schemas import (
    BoardResponse,
    CardListResponse,
    CopyDayRequest,
    CrewCreate,
    CrewResponse,
    CrewUpdate,
    DailyPlanResponse,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    MoveRequest,
    PlacementUpdate,
    PlaceRequest,
    PrefillRequest,
    PrefillResponse,
    RemoveRequest,
    ScheduledMoveResponse,
    ScheduleMoveRequest,
    ShareResponse,
    UtilisationResponse,
    ValidationResponse,
    ViewPref,
    WeekResponse,
)
from app.modules.dispatch.service import DispatchService, _today

router = APIRouter(tags=["dispatch"])

_READ = Depends(RequirePermission("dispatch.read"))
_WRITE = Depends(RequirePermission("dispatch.update"))
_MANAGE = Depends(RequirePermission("dispatch.manage"))


def _uid(user_id: str | None) -> str | None:
    return str(user_id) if user_id else None


@router.get("/locations", response_model=list[LocationResponse])
async def list_locations(
    session: SessionDep, include_inactive: bool = False, _perm: None = _READ
) -> list[LocationResponse]:
    """Board columns in display order."""
    rows = await DispatchService(session).repo.list_locations(include_inactive=include_inactive)
    return [LocationResponse.model_validate(r) for r in rows]


@router.post("/locations", response_model=LocationResponse, status_code=201)
async def create_location(
    data: LocationCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,
    _perm: None = _MANAGE,  # type: ignore[assignment]
) -> LocationResponse:
    """Add a column: a project site, the yard, the shop or rental returned."""
    if data.project_id:
        await verify_project_access(data.project_id, user_id or "", session)
    return LocationResponse.model_validate(await DispatchService(session).create_location(data))


@router.patch("/locations/{location_id}", response_model=LocationResponse)
async def update_location(
    location_id: uuid.UUID, data: LocationUpdate, session: SessionDep, _perm: None = _MANAGE
) -> LocationResponse:
    """Rename, reorder or hide a column."""
    return LocationResponse.model_validate(await DispatchService(session).update_location(location_id, data))


@router.get("/crews", response_model=list[CrewResponse])
async def list_crews(
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _perm: None = _READ,
) -> list[CrewResponse]:
    """Active crews."""
    rows = await DispatchService(session).repo.list_crews(limit=limit, offset=offset)
    return [CrewResponse.model_validate(r) for r in rows]


@router.post("/crews", response_model=CrewResponse, status_code=201)
async def create_crew(data: CrewCreate, session: SessionDep, _perm: None = _MANAGE) -> CrewResponse:
    """Create a crew from resources people."""
    return CrewResponse.model_validate(await DispatchService(session).create_crew(data))


@router.patch("/crews/{crew_id}", response_model=CrewResponse)
async def update_crew(crew_id: uuid.UUID, data: CrewUpdate, session: SessionDep, _perm: None = _MANAGE) -> CrewResponse:
    """Change members, foreman or minimum size."""
    return CrewResponse.model_validate(await DispatchService(session).update_crew(crew_id, data))


@router.get("/cards", response_model=CardListResponse)
async def list_cards(
    session: SessionDep,
    kind: str = Query(default="worker", pattern="^(crew|worker|equipment|rental)$"),
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _perm: None = _READ,
) -> CardListResponse:
    """Cards of one kind the dispatcher can drag onto the board."""
    items, total = await DispatchService(session).cards(kind, q, limit=limit, offset=offset)
    return CardListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/board", response_model=BoardResponse)
async def get_board(session: SessionDep, day: date | None = None, _perm: None = _READ) -> BoardResponse:
    """One day's board. Moves booked for today or earlier are applied first."""
    return BoardResponse.model_validate(await DispatchService(session).board(day or _today()), from_attributes=True)


@router.get("/week", response_model=WeekResponse)
async def get_week(session: SessionDep, start: date | None = None, _perm: None = _READ) -> WeekResponse:
    """Seven days from ``start`` (default: this Monday)."""
    today = _today()
    return WeekResponse.model_validate(
        await DispatchService(session).week(start or today - timedelta(days=today.weekday())), from_attributes=True
    )


@router.post("/placements", status_code=201)
async def place_cards(
    data: PlaceRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,
    _perm: None = _WRITE,  # type: ignore[assignment]
) -> dict:
    """Put one or more cards on a column for a day."""
    rows = await DispatchService(session).place(data, _uid(user_id))
    return {"created": len(rows), "ids": [str(r.id) for r in rows]}


@router.post("/placements/move")
async def move_cards(data: MoveRequest, session: SessionDep, _perm: None = _WRITE) -> dict:
    """Move cards to another column on the same day."""
    rows = await DispatchService(session).move(data)
    return {"moved": len(rows)}


@router.patch("/placements/{placement_id}")
async def update_placement(
    placement_id: uuid.UUID, data: PlacementUpdate, session: SessionDep, _perm: None = _WRITE
) -> dict:
    """Start time, notes or operator on a card."""
    p = await DispatchService(session).update_placement(placement_id, data)
    return {"id": str(p.id), "start_time": p.start_time, "notes": p.notes, "operator_ref": p.operator_ref}


@router.post("/placements/remove")
async def remove_cards(data: RemoveRequest, session: SessionDep, _perm: None = _WRITE) -> dict:
    """Take cards off the board."""
    return {"removed": await DispatchService(session).remove(list(data.placement_ids))}


@router.post("/copy-day")
async def copy_day(
    data: CopyDayRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,
    _perm: None = _WRITE,  # type: ignore[assignment]
) -> dict:
    """Repeat one day's board on another, e.g. yesterday onto today."""
    return {"copied": await DispatchService(session).copy_day(data, _uid(user_id))}


@router.get("/moves", response_model=list[ScheduledMoveResponse])
async def list_moves(
    session: SessionDep,
    status: str | None = Query(default="pending", pattern="^(pending|applied|cancelled)$"),
    _perm: None = _READ,
) -> list[ScheduledMoveResponse]:
    """Moves booked ahead."""
    rows = await DispatchService(session).repo.list_moves(status=status)
    return [ScheduledMoveResponse.model_validate(r) for r in rows]


@router.post("/moves", response_model=ScheduledMoveResponse, status_code=201)
async def schedule_move(
    data: ScheduleMoveRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,
    _perm: None = _WRITE,  # type: ignore[assignment]
) -> ScheduledMoveResponse:
    """Book a move for a date; it is applied that day."""
    return ScheduledMoveResponse.model_validate(await DispatchService(session).schedule_move(data, _uid(user_id)))


@router.post("/moves/{move_id}/cancel", response_model=ScheduledMoveResponse)
async def cancel_move(move_id: uuid.UUID, session: SessionDep, _perm: None = _WRITE) -> ScheduledMoveResponse:
    """Cancel a pending move."""
    return ScheduledMoveResponse.model_validate(await DispatchService(session).cancel_move(move_id))


@router.post("/moves/apply")
async def apply_moves(session: SessionDep, _perm: None = _WRITE) -> dict:
    """Apply every move dated today or earlier."""
    return {"applied": await DispatchService(session).apply_due_moves(_today())}


@router.get("/plan", response_model=DailyPlanResponse)
async def daily_plan(session: SessionDep, day: date | None = None, _perm: None = _READ) -> DailyPlanResponse:
    """Per foreman: who, which machine, where, start time, notes (default: tomorrow)."""
    d = day or _today() + timedelta(days=1)
    return DailyPlanResponse(day=d, plans=await DispatchService(session).daily_plan(d))


@router.get("/plan/pdf")
async def daily_plan_pdf(session: SessionDep, day: date | None = None, _perm: None = _READ) -> Response:
    """The daily plan as a printable PDF, a page per foreman."""
    d = day or _today() + timedelta(days=1)
    pdf = await DispatchService(session).daily_plan_pdf(d)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="daily-plan-{d.isoformat()}.pdf"'},
    )


@router.post("/plan/share", response_model=ShareResponse)
async def share_plan(session: SessionDep, day: date | None = None, _perm: None = _WRITE) -> ShareResponse:
    """Notify each foreman; email and other channels follow their notification settings."""
    d = day or _today() + timedelta(days=1)
    return ShareResponse.model_validate(await DispatchService(session).share_plan(d))


@router.post("/timesheet-prefill", response_model=PrefillResponse)
async def timesheet_prefill(
    data: PrefillRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,
    _perm: None = _WRITE,  # type: ignore[assignment]
) -> PrefillResponse:
    """Draft the site's field timesheet with the dispatched crew and machines."""
    svc = DispatchService(session)
    loc = await svc.repo.get_location(data.location_id)
    if loc is not None and loc.project_id is not None:
        await verify_project_access(loc.project_id, user_id or "", session)
    return PrefillResponse.model_validate(await svc.prefill_timesheet(data, _uid(user_id)))


@router.get("/utilisation", response_model=UtilisationResponse)
async def utilisation(
    session: SessionDep,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _perm: None = _READ,
) -> UtilisationResponse:
    """Working days on a job vs idle per unit (default: this week)."""
    today = _today()
    s = start or today - timedelta(days=today.weekday())
    e = end or s + timedelta(days=6)
    items = await DispatchService(session).utilisation(s, e, limit=limit, offset=offset)
    return UtilisationResponse(start=s, end=e, items=items)


@router.get("/validate", response_model=ValidationResponse)
async def validate_day(session: SessionDep, day: date | None = None, _perm: None = _READ) -> ValidationResponse:
    """Run the dispatch rule set over one day."""
    return ValidationResponse.model_validate(
        await DispatchService(session).validate_day(day or _today()), from_attributes=True
    )


@router.get("/preferences", response_model=ViewPref)
async def get_preferences(session: SessionDep, user_id: CurrentUserId = None, _perm: None = _READ) -> ViewPref:  # type: ignore[assignment]
    """The caller's board view preference."""
    return await DispatchService(session).get_pref(_uid(user_id) or "")


@router.put("/preferences", response_model=ViewPref)
async def set_preferences(
    data: ViewPref,
    session: SessionDep,
    user_id: CurrentUserId = None,
    _perm: None = _READ,  # type: ignore[assignment]
) -> ViewPref:
    """Save the caller's board view preference."""
    return await DispatchService(session).set_pref(_uid(user_id) or "", data)
