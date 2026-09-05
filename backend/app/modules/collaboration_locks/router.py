# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP + WebSocket routes for collaboration locks.

HTTP surface
------------

* ``POST   /``                       - acquire a lock (201 on success, 409 on conflict)
* ``POST   /{lock_id}/heartbeat/``   - extend an existing lock
* ``DELETE /{lock_id}/``             - release a lock
* ``GET    /entity/``                - current holder of an entity, or null
* ``GET    /my/``                    - locks held by the calling user

WebSocket surface
-----------------

* ``WS /presence/?entity_type=...&entity_id=...&token=<jwt>``

  Every connected client subscribed to the same ``(entity_type, entity_id)``
  pair receives JSON envelopes of the form::

      {"event": "lock_acquired", "user_id": "...", "user_name": "...",
       "lock_id": "...", "expires_at": "2026-04-11T12:34:56+00:00",
       "ts": "2026-04-11T12:34:51+00:00"}

  Supported event names:

  * ``presence_snapshot``  - sent once, immediately after join, with
    the full ``users`` roster.
  * ``presence_join``      - another user opened the same entity.
  * ``presence_leave``     - another user closed all their tabs on this entity.
  * ``lock_acquired``      - someone (including you) claimed the lock.
  * ``lock_heartbeat``     - the holder renewed their TTL.
  * ``lock_released``      - the holder released voluntarily.
  * ``lock_expired``       - the sweeper removed a stale lock.

  Clients authenticate by passing the JWT as the ``token`` query
  parameter, the same pattern used by the BIM geometry endpoint (the
  browser ``WebSocket`` API cannot set custom headers).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.dependencies import (
    CurrentUserId,
    SessionDep,
    decode_access_token,
    verify_project_access,
)
from app.modules.collaboration_locks.events import (
    COLLAB_LOCK_ACQUIRED,
    COLLAB_LOCK_EXPIRED,
    COLLAB_LOCK_HEARTBEAT,
    COLLAB_LOCK_RELEASED,
)
from app.modules.collaboration_locks.presence_hub import (
    PresenceKey,
    presence_hub,
)
from app.modules.collaboration_locks.schemas import (
    ALLOWED_LOCK_ENTITY_TYPES,
    CollabLockAcquire,
    CollabLockConflict,
    CollabLockHeartbeat,
    CollabLockResponse,
)
from app.modules.collaboration_locks.service import (
    CollabLockService,
    LockConflictError,
    NotLockHolderError,
    UnknownEntityTypeError,
    _resolve_user_name,
)

router = APIRouter(tags=["collaboration_locks"])
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_service(session: SessionDep) -> CollabLockService:
    return CollabLockService(session)


def _parse_entity_id(entity_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(entity_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity_id: {exc}",
        ) from exc


def _reject_unknown_entity_type(entity_type: str) -> None:
    if entity_type not in ALLOWED_LOCK_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Unsupported entity_type '{entity_type}'. Allowed: {sorted(ALLOWED_LOCK_ENTITY_TYPES)}"),
        )


# ── Tenant isolation ───────────────────────────────────────────────────────
#
# Locks are state about another tenant's rows: who is editing a given entity
# and until when. Without a project gate any authenticated user could read a
# foreign lock (presence/holder leak) or plant one (cross-tenant DoS). Every
# entity_type in ALLOWED_LOCK_ENTITY_TYPES is traceable to a single owning
# project (directly or through one FK hop); we resolve it and reuse the same
# verify_project_access helper the rest of the platform uses (404 on missing
# OR denied, so we never leak UUID existence). A type we cannot resolve to a
# project fails closed.


async def _resolve_lock_entity_project_id(
    entity_type: str,
    entity_id: uuid.UUID,
    session: AsyncSession,
) -> uuid.UUID | None:
    """Map a lockable entity to its owning project's UUID.

    Returns ``None`` when the row does not exist or the type genuinely cannot
    be tied to a project - callers treat ``None`` as fail-closed.
    """
    try:
        from sqlalchemy import select

        # ── Direct project_id on the primary model ──────────────────────
        if entity_type == "project":
            return entity_id
        if entity_type == "boq":
            from app.modules.boq.models import BOQ

            return (await session.execute(select(BOQ.project_id).where(BOQ.id == entity_id))).scalar_one_or_none()
        if entity_type == "document":
            from app.modules.documents.models import Document

            return (
                await session.execute(select(Document.project_id).where(Document.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "task":
            from app.modules.tasks.models import Task

            return (await session.execute(select(Task.project_id).where(Task.id == entity_id))).scalar_one_or_none()
        if entity_type == "rfi":
            from app.modules.rfi.models import RFI

            return (await session.execute(select(RFI.project_id).where(RFI.id == entity_id))).scalar_one_or_none()
        if entity_type == "ncr":
            from app.modules.ncr.models import NCR

            return (await session.execute(select(NCR.project_id).where(NCR.id == entity_id))).scalar_one_or_none()
        if entity_type == "submittal":
            from app.modules.submittals.models import Submittal

            return (
                await session.execute(select(Submittal.project_id).where(Submittal.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "punchlist_item":
            from app.modules.punchlist.models import PunchItem

            return (
                await session.execute(select(PunchItem.project_id).where(PunchItem.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "inspection":
            from app.modules.inspections.models import QualityInspection

            return (
                await session.execute(select(QualityInspection.project_id).where(QualityInspection.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "meeting":
            from app.modules.meetings.models import Meeting

            return (
                await session.execute(select(Meeting.project_id).where(Meeting.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "transmittal":
            from app.modules.transmittals.models import Transmittal

            return (
                await session.execute(select(Transmittal.project_id).where(Transmittal.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "bim_model":
            from app.modules.bim_hub.models import BIMModel

            return (
                await session.execute(select(BIMModel.project_id).where(BIMModel.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "tender_package":
            from app.modules.tendering.models import TenderPackage

            return (
                await session.execute(select(TenderPackage.project_id).where(TenderPackage.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "change_order":
            from app.modules.changeorders.models import ChangeOrder

            return (
                await session.execute(select(ChangeOrder.project_id).where(ChangeOrder.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "risk":
            from app.modules.risk.models import RiskItem

            return (
                await session.execute(select(RiskItem.project_id).where(RiskItem.id == entity_id))
            ).scalar_one_or_none()

        # ── One FK hop to reach project_id ──────────────────────────────
        if entity_type in ("boq_position", "boq_section"):
            from app.modules.boq.models import BOQ, Position

            return (
                await session.execute(
                    select(BOQ.project_id).join(Position, Position.boq_id == BOQ.id).where(Position.id == entity_id)
                )
            ).scalar_one_or_none()
        if entity_type == "bim_element":
            from app.modules.bim_hub.models import BIMElement, BIMModel

            return (
                await session.execute(
                    select(BIMModel.project_id)
                    .join(BIMElement, BIMElement.model_id == BIMModel.id)
                    .where(BIMElement.id == entity_id)
                )
            ).scalar_one_or_none()
        if entity_type == "schedule_activity":
            from app.modules.schedule.models import Activity, Schedule

            return (
                await session.execute(
                    select(Schedule.project_id)
                    .join(Activity, Activity.schedule_id == Schedule.id)
                    .where(Activity.id == entity_id)
                )
            ).scalar_one_or_none()
        if entity_type == "schedule":
            # The schedule-level presence room (T3.4): co-editors of a whole
            # schedule share one room keyed on the schedule id. project_id lives
            # directly on the schedule, so this is a single-table lookup.
            from app.modules.schedule.models import Schedule

            return (
                await session.execute(select(Schedule.project_id).where(Schedule.id == entity_id))
            ).scalar_one_or_none()
        if entity_type == "requirement":
            from app.modules.requirements.models import Requirement, RequirementSet

            return (
                await session.execute(
                    select(RequirementSet.project_id)
                    .join(Requirement, Requirement.requirement_set_id == RequirementSet.id)
                    .where(Requirement.id == entity_id)
                )
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - resolution failed; treat as unresolved (fail closed)
        # Failing closed is right and being quiet about it is not. Returning
        # None here denies access, so a database or import error and a genuinely
        # unreachable entity produce the same refusal; at debug level the
        # difference was invisible in production, which is where the two need
        # telling apart. The traceback is what says which one happened.
        logger.exception("collab-lock entity resolve failed for %s/%s", entity_type, entity_id)
        return None
    return None


async def _verify_lock_entity_access(
    entity_type: str,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession,
) -> None:
    """Fail closed unless the caller can reach the entity's owning project.

    Raises HTTP 404 (matching ``verify_project_access`` and the IDOR-404
    convention) when the entity cannot be resolved to a project, or when the
    caller has no access to that project.
    """
    resolved = await _resolve_lock_entity_project_id(entity_type, entity_id, session)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )
    await verify_project_access(resolved, str(user_id), session)


# ── HTTP: acquire / heartbeat / release ────────────────────────────────────


@router.post(
    "/",
    response_model=CollabLockResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {"model": CollabLockConflict},
    },
)
async def acquire_lock(
    data: CollabLockAcquire,
    user_id: CurrentUserId,
    service: CollabLockService = Depends(_get_service),
) -> CollabLockResponse | JSONResponse:
    """Acquire a pessimistic lock on an entity.

    On success the caller holds the lock until ``expires_at``.  On a
    409 the response body is a :class:`CollabLockConflict` carrying
    the current holder's name and remaining TTL so the frontend can
    render a meaningful toast.
    """
    # Allowlist first, tenant gate second. An off-allowlist entity_type is a
    # malformed request, not a tenancy question: the tenant gate cannot resolve
    # a type it has no handler for, so letting it run first turns every
    # unsupported type into a 404 and hides the 400 this module documents. The
    # allowlist is a static, public product fact already published in the
    # OpenAPI schema, so naming it leaks nothing about any row.
    _reject_unknown_entity_type(data.entity_type)
    # Tenant gate: you may only lock a row in a project you can reach.
    # Prevents cross-tenant lock planting (DoS) on a foreign entity.
    await _verify_lock_entity_access(
        data.entity_type,
        data.entity_id,
        uuid.UUID(user_id),
        service.session,
    )
    try:
        return await service.acquire(
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            user_id=uuid.UUID(user_id),
            ttl_seconds=data.ttl_seconds,
        )
    except UnknownEntityTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LockConflictError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=exc.conflict.model_dump(mode="json"),
        )


@router.post("/{lock_id}/heartbeat/", response_model=CollabLockResponse)
async def heartbeat_lock(
    lock_id: uuid.UUID,
    data: CollabLockHeartbeat,
    user_id: CurrentUserId,
    service: CollabLockService = Depends(_get_service),
) -> CollabLockResponse:
    # Renewing a lock is already holder-gated by the service (only the owner
    # can extend), but a user removed from the project mid-session must not
    # keep a foreign row pinned. Re-verify project access against the locked
    # entity when the row exists; a missing row falls through to the service's
    # own 404 so behaviour for valid holders is unchanged.
    existing = await service.repo.get_by_id(lock_id)
    if existing is not None:
        await _verify_lock_entity_access(
            existing.entity_type,
            existing.entity_id,
            uuid.UUID(user_id),
            service.session,
        )
    try:
        return await service.heartbeat(
            lock_id=lock_id,
            user_id=uuid.UUID(user_id),
            extend_seconds=data.extend_seconds,
        )
    except NotLockHolderError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{lock_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def release_lock(
    lock_id: uuid.UUID,
    user_id: CurrentUserId,
    service: CollabLockService = Depends(_get_service),
) -> Response:
    try:
        await service.release(lock_id=lock_id, user_id=uuid.UUID(user_id))
    except NotLockHolderError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/entity/", response_model=CollabLockResponse | None)
async def get_entity_lock(
    user_id: CurrentUserId,
    entity_type: str = Query(..., min_length=1, max_length=64),
    entity_id: str = Query(..., min_length=1, max_length=36),
    service: CollabLockService = Depends(_get_service),
) -> CollabLockResponse | None:
    parsed = _parse_entity_id(entity_id)
    # Same ordering as acquire: reject an unlockable type as a bad request
    # before the tenant gate, which has no handler for it and would answer 404.
    _reject_unknown_entity_type(entity_type)
    # Tenant gate: reading who holds the lock on an entity leaks the holder's
    # identity and edit activity, so it requires access to the entity's
    # project just like the lock itself.
    await _verify_lock_entity_access(entity_type, parsed, uuid.UUID(user_id), service.session)
    try:
        return await service.get_for_entity(entity_type=entity_type, entity_id=parsed)
    except UnknownEntityTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/my/", response_model=list[CollabLockResponse])
async def list_my_locks(
    user_id: CurrentUserId,
    service: CollabLockService = Depends(_get_service),
) -> list[CollabLockResponse]:
    return await service.list_my_locks(user_id=uuid.UUID(user_id))


# ── WebSocket: presence ────────────────────────────────────────────────────


class _AuthenticationUnavailableError(Exception):
    """The token could not be judged, which is not the same as judging it bad.

    Everything this path is meant to reject arrives as an ``HTTPException``:
    a malformed, expired or wrong-type token, a subject that is not a UUID, a
    user who does not exist or is inactive. Measured, that is the whole of it.
    What reaches the broad clauses below is therefore never an authentication
    failure - it is the database being unreachable, or a settings object that
    cannot produce a secret - and answering those with "unauthenticated" tells
    the caller the one thing that is certainly false.

    It matters more here than it would on an HTTP route because neither
    frontend client reconnects. A socket that closes stays closed, so a
    momentary database fault does not degrade the channel, it ends it, and
    nothing comes back when the database does.
    """


async def _authenticate_ws(token: str | None) -> dict[str, Any] | None:
    """Decode a JWT passed as ``?token=`` on a WebSocket upgrade.

    Returns the payload on success; returns ``None`` when the caller was
    judged and rejected, which the caller answers with a 1008 policy close.
    BUG-323: payload is re-hydrated against the DB so a forged token
    with a fake UUID cannot open a socket.

    Raises:
        _AuthenticationUnavailableError: the caller could not be judged at
            all. Kept distinct from ``None`` so the socket can close 1011
            instead of blaming the user's credentials for a server fault.
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token, get_settings())
    except HTTPException:
        return None
    except Exception as exc:  # noqa: BLE001 - stays broad deliberately, see the class above
        logger.exception("WebSocket token decode failed")
        raise _AuthenticationUnavailableError from exc

    try:
        from app.core.permissions import permission_registry
        from app.dependencies import verify_user_exists_and_active

        user = await verify_user_exists_and_active(
            payload["sub"],
            issued_at=payload.get("iat"),
            session_id=payload.get("sid"),
        )
        payload["role"] = user.role
        payload["permissions"] = permission_registry.get_role_permissions(user.role)
        return payload
    except HTTPException:
        return None
    except Exception as exc:  # noqa: BLE001 - stays broad deliberately, see the class above
        logger.exception("WebSocket user re-hydration failed")
        raise _AuthenticationUnavailableError from exc


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.websocket("/presence/")
async def presence_ws(
    websocket: WebSocket,
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    token: str | None = Query(default=None),
) -> None:
    """Real-time presence channel for a single entity."""
    if entity_type not in ALLOWED_LOCK_ENTITY_TYPES:
        await websocket.close(code=1008, reason="unknown entity_type")
        return

    try:
        parsed_id = uuid.UUID(entity_id)
    except (ValueError, TypeError):
        await websocket.close(code=1008, reason="invalid entity_id")
        return

    # 1008 says "we judged you and the answer is no", 1011 says "we could not
    # judge you". The authorization step further down already draws exactly
    # this line; this is the same distinction applied one step earlier.
    try:
        payload = await _authenticate_ws(token)
    except _AuthenticationUnavailableError:
        await websocket.close(code=1011, reason="authentication unavailable")
        return
    if payload is None:
        await websocket.close(code=1008, reason="unauthenticated")
        return

    user_id_str = payload.get("sub")
    if not isinstance(user_id_str, str):
        await websocket.close(code=1008, reason="invalid token subject")
        return
    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        await websocket.close(code=1008, reason="invalid user id")
        return

    # Tenant gate before anything is sent: the presence_snapshot frame leaks
    # the editing roster and current lock holder of this entity, so the caller
    # must be able to reach the entity's owning project. WebSockets cannot
    # carry a 404, so a failed check closes the socket with 1008 (policy
    # violation) - the same code used for auth failures above - without ever
    # joining the presence hub or sending a frame.
    try:
        async with async_session_factory() as auth_sess:
            await _verify_lock_entity_access(entity_type, parsed_id, user_id, auth_sess)
    except HTTPException:
        await websocket.close(code=1008, reason="forbidden")
        return
    except Exception:  # noqa: BLE001 - never leak presence on an unexpected error
        logger.exception("presence websocket authorization failed")
        await websocket.close(code=1011, reason="authorization error")
        return

    # Resolve the display name in its own session so the connection
    # handshake does not piggyback on a request-scoped session.
    async with async_session_factory() as sess:
        user_name = await _resolve_user_name(sess, user_id)

    await websocket.accept()
    # Tag the socket so PresenceHub.leave() can attribute remaining
    # subscribers back to their user ids without a separate map.
    websocket._collab_lock_user_id = user_id  # type: ignore[attr-defined]

    key: PresenceKey = (entity_type, parsed_id)
    roster = await presence_hub.join(key, websocket, user_id=user_id, user_name=user_name)

    # First frame: full roster + current lock holder (if any) so the
    # client can paint without a follow-up REST round-trip.
    #
    # ``lock`` on its own cannot say what happens when the read fails. Null
    # already means nobody holds it, so a failed read borrowing that value
    # states something false rather than something incomplete, and states it
    # with exactly the confidence of the truth. ``lock_state`` carries the
    # third value so a reader can tell a free lock from one we could not read.
    # That distinction has no consumer today, and the reason to send it anyway
    # is that the component written to read this field, ``PresenceIndicator``,
    # derives its holder from a falsy test on ``lock`` - so a failed read and
    # a genuinely free lock paint the same "nobody is editing" badge. It is
    # not mounted anywhere yet, which is the only reason this has cost nothing
    # so far.
    lock_state = "unknown"
    current_lock = None
    try:
        async with async_session_factory() as sess:
            svc = CollabLockService(sess)
            current_lock = await svc.get_for_entity(entity_type=entity_type, entity_id=parsed_id)
        lock_state = "held" if current_lock is not None else "free"
    except Exception:  # noqa: BLE001 - the snapshot may be incomplete, it may not be wrong
        logger.exception(
            "presence snapshot could not read the current lock for %s/%s",
            entity_type,
            parsed_id,
        )

    try:
        await websocket.send_json(
            {
                "event": "presence_snapshot",
                "users": roster,
                "lock": (current_lock.model_dump(mode="json") if current_lock is not None else None),
                # "held" | "free" | "unknown" - see the read above.
                "lock_state": lock_state,
                "ts": _now_iso(),
            }
        )
        await presence_hub.broadcast(
            key,
            {
                "event": "presence_join",
                "user_id": str(user_id),
                "user_name": user_name,
                "ts": _now_iso(),
            },
            exclude=websocket,
        )

        # Keep the socket open.  We accept incoming text frames as
        # client-side "ping" opportunities but do nothing with them -
        # all interesting traffic is server-push. Anything else is ignored,
        # binary frames included, and that is why this reads the raw message:
        # ``receive_text()`` raises ``KeyError('text')`` on a binary frame,
        # which unwound into the handler below and dropped the connection,
        # taking the caller out of the presence roster. Any client can send
        # one in a line, so losing a roster to it is the wrong trade.
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("text") == "ping":
                await websocket.send_json({"event": "pong", "ts": _now_iso()})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("presence websocket crashed")
    finally:
        # One event per departing user: a single disconnect can be the moment
        # several users stop being accounted for, and announcing only one of
        # them left the rest showing as present in every peer's UI.
        for left_uid in await presence_hub.leave(key, websocket):
            await presence_hub.broadcast(
                key,
                {
                    "event": "presence_leave",
                    "user_id": str(left_uid),
                    "ts": _now_iso(),
                },
            )


# ── Event-bus subscribers: bridge events → presence broadcasts ─────────────


async def _on_lock_acquired(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    entity_type = data.get("entity_type")
    entity_id_raw = data.get("entity_id")
    if not entity_type or not entity_id_raw:
        return
    try:
        entity_id = uuid.UUID(str(entity_id_raw))
    except (ValueError, TypeError):
        return
    await presence_hub.broadcast(
        (entity_type, entity_id),
        {
            "event": "lock_acquired",
            "lock_id": data.get("lock_id"),
            "user_id": data.get("user_id"),
            "user_name": data.get("user_name", ""),
            "expires_at": data.get("expires_at"),
            "ts": _now_iso(),
        },
    )


async def _on_lock_heartbeat(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    entity_type = data.get("entity_type")
    entity_id_raw = data.get("entity_id")
    if not entity_type or not entity_id_raw:
        return
    try:
        entity_id = uuid.UUID(str(entity_id_raw))
    except (ValueError, TypeError):
        return
    await presence_hub.broadcast(
        (entity_type, entity_id),
        {
            "event": "lock_heartbeat",
            "lock_id": data.get("lock_id"),
            "user_id": data.get("user_id"),
            "user_name": data.get("user_name", ""),
            "expires_at": data.get("expires_at"),
            "ts": _now_iso(),
        },
    )


async def _on_lock_released(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    entity_type = data.get("entity_type")
    entity_id_raw = data.get("entity_id")
    if not entity_type or not entity_id_raw:
        return
    try:
        entity_id = uuid.UUID(str(entity_id_raw))
    except (ValueError, TypeError):
        return
    await presence_hub.broadcast(
        (entity_type, entity_id),
        {
            "event": "lock_released",
            "lock_id": data.get("lock_id"),
            "user_id": data.get("user_id"),
            "user_name": data.get("user_name", ""),
            "ts": _now_iso(),
        },
    )


async def _on_lock_expired(event: Any) -> None:
    data = getattr(event, "data", {}) or {}
    entity_type = data.get("entity_type")
    entity_id_raw = data.get("entity_id")
    if not entity_type or not entity_id_raw:
        return
    try:
        entity_id = uuid.UUID(str(entity_id_raw))
    except (ValueError, TypeError):
        return
    await presence_hub.broadcast(
        (entity_type, entity_id),
        {
            "event": "lock_expired",
            "lock_id": data.get("lock_id"),
            "user_id": data.get("user_id"),
            "ts": _now_iso(),
        },
    )


_BROADCAST_SUBSCRIPTIONS: tuple[tuple[str, Any], ...] = (
    (COLLAB_LOCK_ACQUIRED, _on_lock_acquired),
    (COLLAB_LOCK_HEARTBEAT, _on_lock_heartbeat),
    (COLLAB_LOCK_RELEASED, _on_lock_released),
    (COLLAB_LOCK_EXPIRED, _on_lock_expired),
)


def register_broadcast_subscribers() -> None:
    """Wire event-bus handlers.  Called once on module startup."""
    from app.core.events import event_bus as _bus

    for name, handler in _BROADCAST_SUBSCRIPTIONS:
        _bus.subscribe(name, handler)
    logger.info(
        "collaboration_locks: subscribed %d broadcast handler(s)",
        len(_BROADCAST_SUBSCRIPTIONS),
    )
