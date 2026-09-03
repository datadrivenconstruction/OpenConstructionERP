# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team metrics routes - mounted INSIDE the Team Standup router.

    POST /api/v1/team-standup/presence/ping     {path, project_id?, seconds}
    POST /api/v1/team-standup/presence/session  {event: login|logout|end, at?}
    GET  /api/v1/team-standup/presence/today?project_id=<uuid?>
    GET  /api/v1/team-standup/metrics?days=30

The package ``__init__`` includes this router into ``router.router`` so
the module loader (which only mounts ``router.py``) picks it up without
that file changing. Permissions come from the module's own registry
entries - and the registration call is repeated here for the same reason
``router.py`` repeats it: an unregistered name fails closed and silently
makes the endpoint admin-only.

Two permissions, not one, and the split is the point:

* the two ``/presence/*`` WRITES are ``team_standup.read`` - every
  signed-in user reports their own presence, and gating them higher
  would leave the table empty for everybody below manager;
* ``GET /presence/today`` is ``team_standup.read`` - who is on RIGHT
  NOW and when they were last seen, for people the caller can already
  see. Ordinary team awareness, and the only thing the project hub's
  team tile ever wanted out of the rollup;
* ``GET /metrics`` is ``team_standup.metrics`` (MANAGER) - it returns
  the whole team's performance and attendance, which is management
  information about people, not a person's own status line.

Do not "tidy" these onto one name. See ``permissions.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.team_standup import metrics_service
from app.modules.team_standup.permissions import register_team_standup_permissions

register_team_standup_permissions()

router = APIRouter(tags=["team_standup"])


class PresencePing(BaseModel):
    path: str = Field(default="/", max_length=2000)
    project_id: str | None = Field(default=None, max_length=36)
    seconds: int = Field(default=0, ge=0)


class PresencePingResult(BaseModel):
    day: str
    module_key: str
    project_id: str | None
    seconds_today: int
    added: int


class JobSeconds(BaseModel):
    project_id: str
    code: str
    name: str
    seconds: int


class PersonToday(BaseModel):
    first_seen: str | None
    last_seen: str | None
    online: bool


class PersonPresence(BaseModel):
    """One person's presence TODAY - and nothing else about them.

    This shape exists so that ``GET /presence/today`` can live at
    ``team_standup.read`` while ``GET /metrics`` stays at MANAGER. Five
    fields, all of them "are they about right now": no task counts, no
    averages, no blockers, no seconds by module or by job, no other day.
    Anything you are tempted to add here is management information about a
    colleague and belongs on ``TeamMetrics`` behind the manager gate.
    """

    user_id: str
    name: str
    online: bool
    first_seen: str | None
    last_seen: str | None


class PersonMetrics(BaseModel):
    user_id: str
    name: str
    tasks_completed: int
    tasks_open: int
    tasks_overdue: int
    avg_days_to_close: float | None
    standups_posted: int
    blockers_raised: int
    seconds_by_module: dict[str, int]
    seconds_by_job: list[JobSeconds]
    today: PersonToday


class AttendanceRow(BaseModel):
    user_id: str
    name: str
    day: str
    first_seen: str | None
    last_seen: str | None
    logins: list[str]
    logouts: list[str]
    ends: list[str]
    active_seconds: int
    still_on: bool


class SessionEventBody(BaseModel):
    event: Literal["login", "logout", "end"]
    at: datetime | None = None
    source: Literal["auth", "window"] | None = None


class SessionEventResult(BaseModel):
    event: str
    at: str
    day: str
    created: bool


class PersonSeconds(BaseModel):
    user_id: str
    name: str
    seconds: int


class JobMetrics(BaseModel):
    project_id: str
    code: str
    name: str
    open_tasks: int
    completed: int
    overdue: int
    seconds_total: int
    people: list[PersonSeconds]


class ModuleSeconds(BaseModel):
    module_key: str
    seconds: int


class TeamMetrics(BaseModel):
    window_days: int
    people: list[PersonMetrics]
    jobs: list[JobMetrics]
    modules: list[ModuleSeconds]
    attendance: list[AttendanceRow]


@router.post("/presence/session", response_model=SessionEventResult)
async def presence_session(
    body: SessionEventBody,
    session: SessionDep,
    user_id: CurrentUserId,
    # WRITE-YOUR-OWN, deliberately viewer-level. The row is keyed by the
    # caller's own token id and can only ever describe the caller, so
    # this stays on ``team_standup.read`` while READING the aggregate is
    # manager-level. Raising it here would silently stop collecting
    # attendance for everyone below manager.
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> SessionEventResult:
    """A client-emitted session event: login, logout or the tab's end."""
    source = body.source or ("window" if body.event == "end" else "auth")
    row, created = await metrics_service.record_session_event(
        session, user_id=str(user_id), event=body.event, at=body.at, source=source
    )
    await session.commit()
    return SessionEventResult(event=row.event, at=row.at.isoformat(), day=row.day, created=created)


@router.post("/presence/ping", response_model=PresencePingResult)
async def presence_ping(
    body: PresencePing,
    session: SessionDep,
    user_id: CurrentUserId,
    # Same rail as /presence/session above: writing your OWN presence is
    # viewer-level on purpose. Do not raise it to team_standup.metrics.
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> PresencePingResult:
    added = metrics_service.clamp_seconds(body.seconds)
    slot = await metrics_service.record_ping(
        session,
        user_id=user_id,
        path=body.path,
        project_id=body.project_id,
        seconds=body.seconds,
    )
    await session.commit()
    return PresencePingResult(
        day=slot.day,
        module_key=slot.module_key,
        project_id=slot.project_id,
        seconds_today=slot.seconds,
        added=added,
    )


class PresenceListResponse(BaseModel):
    """The presence list, in the envelope every list route here answers in.

    ``total`` is the LENGTH of the list the caller is already reading, and
    nothing else. The route never truncates, so it always equals the number
    of items served - which is what keeps this envelope from smuggling a
    figure onto a viewer-level route (see the note on the route below).
    """

    items: list[PersonPresence] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


@router.get("/presence/today", response_model=PresenceListResponse)
async def presence_today(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: str | None = Query(default=None, max_length=36),
    # VIEWER-level, and separate from /metrics on purpose.
    #
    # The project hub's "Project team" tile and its availability popup need
    # exactly one thing out of the old rollup: who is on right now and when
    # they were last seen. That is ordinary team awareness - a colleague
    # being on site, in the office or online is what the tile is FOR - so
    # putting it behind the manager gate blanked the tile for every ordinary
    # team member. Everything in /metrics that is genuinely management
    # information about people (task throughput, average days to close,
    # blockers raised, hours by module and by job, and the multi-day
    # attendance table) stays where it is.
    #
    # So: do NOT merge this back into /metrics, and do not add a counter,
    # an average or a second day to its payload - either would quietly put
    # manager-only figures on a viewer-level route. The response model
    # pins the key set; ``metrics_service.presence_today`` reads only
    # today's session events and never touches tasks or standups.
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> PresenceListResponse:
    """Today's presence for the people the caller can already see.

    With ``project_id`` the list is scoped to that project's members (plus
    the caller); without it, to everyone seen today. ``online`` is a ping
    inside the last three minutes - the same rule the rollup applies.
    """
    rows = await metrics_service.presence_today(session, project_id=project_id, include_user_id=str(user_id))
    return PresenceListResponse(
        items=[PersonPresence(**row) for row in rows[offset : offset + limit]],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get("/metrics", response_model=TeamMetrics)
async def team_metrics(
    session: SessionDep,
    user_id: CurrentUserId,
    days: int = Query(30, ge=metrics_service.MIN_WINDOW_DAYS, le=metrics_service.MAX_WINDOW_DAYS),
    # MANAGER-level: this payload is the whole team's performance and
    # attendance, not the caller's own. Admins pass on the admin bypass.
    _perm: None = Depends(RequirePermission("team_standup.metrics")),
) -> TeamMetrics:
    data = await metrics_service.team_metrics(session, days=days, include_user_id=user_id)
    return TeamMetrics(**data)
