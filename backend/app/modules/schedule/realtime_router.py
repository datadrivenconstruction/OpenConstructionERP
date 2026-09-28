# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Real-time collaboration API + event bridge (T3.4).

Mounted under the same ``/api/v1/schedule`` prefix as the core schedule router.

Surface:
    * ``GET   /schedules/{id}/presence/``        - REST snapshot of who is in
      the schedule's presence room (the live channel is the collaboration-locks
      ``/presence/`` WebSocket with ``entity_type=schedule``).
    * ``PATCH /activities/{id}/guarded/``        - optimistic-concurrency guarded
      activity patch (409 on a stale base, 422 on a malformed base / field).
    * ``GET   /activities/{id}/revision/``       - the activity's current
      revision token, so a client can rebase before retrying.

Every endpoint resolves the owning project from the activity / schedule and runs
``verify_project_access`` (404 on cross-tenant access, existence-oracle safe)
before any work. Permissions reuse the existing ``schedule.read`` /
``schedule.update`` grants - no new permission keys.

The event bridge subscribes to the schedule activity events and fans them out to
the presence room ``("schedule", schedule_id)`` so every connected co-editor
sees creates / updates / deletes / progress in real time. It is modelled on the
collaboration-locks ``register_broadcast_subscribers`` bridge.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.collaboration_locks.presence_hub import presence_hub
from app.modules.schedule.realtime_math import MergeOutcome
from app.modules.schedule.realtime_schemas import (
    ActivityRevisionResponse,
    GuardedActivityUpdate,
    GuardedUpdateResponse,
    RevisionConflict,
    SchedulePresenceResponse,
)
from app.modules.schedule.realtime_service import (
    ScheduleRealtimeService,
    UnknownGuardedFieldError,
)

realtime_router = APIRouter(tags=["schedule"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ScheduleRealtimeService:
    return ScheduleRealtimeService(session)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── IDOR helpers (resolve project, then verify_project_access) ────────────────


async def _verify_activity(
    service: ScheduleRealtimeService,
    session: SessionDep,
    activity_id: uuid.UUID,
    user_id: str,
) -> object:
    activity = await service.base.get_activity(activity_id)
    schedule = await service.base.get_schedule(activity.schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return activity


async def _verify_schedule(
    service: ScheduleRealtimeService,
    session: SessionDep,
    schedule_id: uuid.UUID,
    user_id: str,
) -> object:
    schedule = await service.base.get_schedule(schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return schedule


def _serialize_activity(activity: object) -> dict[str, Any]:
    """Serialise an activity to the canonical ActivityResponse dict shape.

    Reuses the core router's mapper so the guarded surface returns exactly the
    same activity shape as every other schedule endpoint (imported lazily to
    avoid a router import cycle).
    """
    from app.modules.schedule.router import _activity_to_response

    return _activity_to_response(activity).model_dump(mode="json")


# ── Presence (REST snapshot) ──────────────────────────────────────────────────


@realtime_router.get(
    "/schedules/{schedule_id}/presence/",
    response_model=SchedulePresenceResponse,
    summary="Who is currently editing this schedule (presence snapshot)",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def schedule_presence(
    schedule_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleRealtimeService = Depends(_get_service),
) -> SchedulePresenceResponse:
    await _verify_schedule(service, session, schedule_id, user_id)
    roster = presence_hub.roster(("schedule", schedule_id))
    return SchedulePresenceResponse(schedule_id=schedule_id, users=roster)


# ── Revision read ─────────────────────────────────────────────────────────────


@realtime_router.get(
    "/activities/{activity_id}/revision/",
    response_model=ActivityRevisionResponse,
    summary="Current optimistic-concurrency revision of an activity",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def activity_revision(
    activity_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleRealtimeService = Depends(_get_service),
) -> ActivityRevisionResponse:
    await _verify_activity(service, session, activity_id, user_id)
    revision = await service.revision_of(activity_id)
    return ActivityRevisionResponse(activity_id=activity_id, revision=revision)


# ── Guarded update ─────────────────────────────────────────────────────────────


@realtime_router.patch(
    "/activities/{activity_id}/guarded/",
    response_model=GuardedUpdateResponse,
    responses={
        status.HTTP_409_CONFLICT: {"model": RevisionConflict},
    },
    summary="Optimistic-concurrency guarded activity update",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def guarded_update(
    activity_id: uuid.UUID,
    body: GuardedActivityUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleRealtimeService = Depends(_get_service),
) -> GuardedUpdateResponse | JSONResponse:
    """Patch an activity only if the client's base revision is still current.

    * APPLY / NOOP -> 200 with the current activity + revision.
    * STALE        -> 409 with the authoritative revision + current state so the
      client can rebase (the lost-update guard).
    * INVALID      -> 422 (malformed base revision).
    A field outside the editable allowlist is 422 (unprocessable, not a leak).
    """
    await _verify_activity(service, session, activity_id, user_id)

    try:
        activity, check = await service.guarded_update(
            activity_id,
            client_base_revision=body.base_revision,
            fields=body.fields,
            user_id=user_id,
        )
    except UnknownGuardedFieldError as exc:
        raise _unprocessable(str(exc)) from exc

    if check.outcome is MergeOutcome.STALE:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=RevisionConflict(
                current_revision=check.current_revision,
                current_state=_serialize_activity(activity),
            ).model_dump(mode="json"),
        )
    if check.outcome is MergeOutcome.INVALID:
        raise _unprocessable(f"Invalid base revision: {check.reason}")

    # APPLY or NOOP - both return the up-to-date activity.
    return GuardedUpdateResponse(
        activity=_serialize_activity(activity),
        revision=activity.revision,
    )


def _unprocessable(detail: str):
    from fastapi import HTTPException

    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


# ── Event bridge: schedule activity events -> presence broadcasts ─────────────


async def _resolve_schedule_id(activity_id_raw: Any) -> uuid.UUID | None:
    """Resolve the schedule id of an activity in its own session.

    Used by the progress handler, whose event payload carries only the activity
    id. Opens a short-lived session so the bridge never piggybacks on a
    request-scoped one. Returns ``None`` if the activity is gone.
    """
    try:
        activity_id = uuid.UUID(str(activity_id_raw))
    except (ValueError, TypeError):
        return None
    try:
        from app.database import async_session_factory
        from app.modules.schedule.models import Activity

        async with async_session_factory() as sess:
            activity = await sess.get(Activity, activity_id)
            return activity.schedule_id if activity is not None else None
    except Exception:  # noqa: BLE001 - never crash the bridge on a lookup error
        logger.debug("schedule realtime bridge: schedule_id resolve failed for %s", activity_id_raw)
        return None


def _coerce_schedule_id(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


async def _on_activity_created(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    schedule_id = _coerce_schedule_id(data.get("schedule_id"))
    if schedule_id is None:
        return
    await presence_hub.broadcast(
        ("schedule", schedule_id),
        {
            "event": "activity_created",
            "activity_id": data.get("activity_id"),
            "schedule_id": str(schedule_id),
            "wbs_code": data.get("wbs_code"),
            "ts": _now_iso(),
        },
    )


async def _on_activity_updated(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    schedule_id = _coerce_schedule_id(data.get("schedule_id"))
    if schedule_id is None:
        return
    await presence_hub.broadcast(
        ("schedule", schedule_id),
        {
            "event": "activity_updated",
            "activity_id": data.get("activity_id"),
            "schedule_id": str(schedule_id),
            "revision": data.get("revision"),
            "fields": data.get("fields", []),
            "actor_id": data.get("actor_id"),
            "ts": _now_iso(),
        },
    )


async def _on_activity_deleted(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    schedule_id = _coerce_schedule_id(data.get("schedule_id"))
    if schedule_id is None:
        return
    await presence_hub.broadcast(
        ("schedule", schedule_id),
        {
            "event": "activity_deleted",
            "activity_id": data.get("activity_id"),
            "schedule_id": str(schedule_id),
            "ts": _now_iso(),
        },
    )


async def _on_activity_progress(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    # The progress event carries only the activity id; resolve its schedule.
    schedule_id = _coerce_schedule_id(data.get("schedule_id"))
    if schedule_id is None:
        schedule_id = await _resolve_schedule_id(data.get("activity_id"))
    if schedule_id is None:
        return
    await presence_hub.broadcast(
        ("schedule", schedule_id),
        {
            "event": "activity_progress",
            "activity_id": data.get("activity_id"),
            "schedule_id": str(schedule_id),
            "percent_complete": data.get("progress_pct"),
            "status": data.get("status"),
            "source": data.get("source", event.source_module if hasattr(event, "source_module") else None),
            "ts": _now_iso(),
        },
    )


_BROADCAST_SUBSCRIPTIONS: tuple[tuple[str, Any], ...] = (
    ("schedule.activity.created", _on_activity_created),
    ("schedule.activity.updated", _on_activity_updated),
    ("schedule.activity.deleted", _on_activity_deleted),
    ("schedule.activity.progress_updated", _on_activity_progress),
)

# Idempotency guard so repeated startups (test app re-creation, reload) do not
# stack duplicate handlers on the bus - matching the collab-locks bridge intent.
_SUBSCRIBED = False


def register_schedule_realtime_subscribers() -> None:
    """Wire the schedule -> presence event bridge once. Idempotent."""
    global _SUBSCRIBED
    if _SUBSCRIBED:
        return
    from app.core.events import event_bus as _bus

    for name, handler in _BROADCAST_SUBSCRIPTIONS:
        _bus.subscribe(name, handler)
    _SUBSCRIBED = True
    logger.info(
        "schedule realtime: subscribed %d presence-bridge handler(s)",
        len(_BROADCAST_SUBSCRIPTIONS),
    )
