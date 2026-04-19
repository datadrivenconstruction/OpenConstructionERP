"""HTTP + WebSocket routes for collaboration locks.

HTTP surface
------------

* ``POST   /``                       — acquire a lock (201 on success, 409 on conflict)
* ``POST   /{lock_id}/heartbeat/``   — extend an existing lock
* ``DELETE /{lock_id}/``             — release a lock
* ``GET    /entity/``                — current holder of an entity, or null
* ``GET    /my/``                    — locks held by the calling user

WebSocket surface
-----------------

* ``WS /presence/?entity_type=...&entity_id=...&token=<jwt>``

  Every connected client subscribed to the same ``(entity_type, entity_id)``
  pair receives JSON envelopes of the form::

      {"event": "lock_acquired", "user_id": "...", "user_name": "...",
       "lock_id": "...", "expires_at": "2026-04-11T12:34:56+00:00",
       "ts": "2026-04-11T12:34:51+00:00"}

  Supported event names:

  * ``presence_snapshot``  — sent once, immediately after join, with
    the full ``users`` roster.
  * ``presence_join``      — another user opened the same entity.
  * ``presence_leave``     — another user closed all their tabs on this entity.
  * ``lock_acquired``      — someone (including you) claimed the lock.
  * ``lock_heartbeat``     — the holder renewed their TTL.
  * ``lock_released``      — the holder released voluntarily.
  * ``lock_expired``       — the sweeper removed a stale lock.

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

from app.config import get_settings
from app.database import async_session_factory
from app.dependencies import CurrentUserId, SessionDep, decode_access_token
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

router = APIRouter()
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
            detail=(
                f"Unsupported entity_type '{entity_type}'. "
                f"Allowed: {sorted(ALLOWED_LOCK_ENTITY_TYPES)}"
            ),
        )


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
    try:
        return await service.acquire(
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            user_id=uuid.UUID(user_id),
            ttl_seconds=data.ttl_seconds,
        )
    except UnknownEntityTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
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
    try:
        return await service.heartbeat(
            lock_id=lock_id,
            user_id=uuid.UUID(user_id),
            extend_seconds=data.extend_seconds,
        )
    except NotLockHolderError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/{lock_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def release_lock(
    lock_id: uuid.UUID,
    user_id: CurrentUserId,
    service: CollabLockService = Depends(_get_service),
) -> Response:
    try:
        await service.release(lock_id=lock_id, user_id=uuid.UUID(user_id))
    except NotLockHolderError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/entity/", response_model=CollabLockResponse | None)
async def get_entity_lock(
    entity_type: str = Query(..., min_length=1, max_length=64),
    entity_id: str = Query(..., min_length=1, max_length=36),
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: CollabLockService = Depends(_get_service),
) -> CollabLockResponse | None:
    parsed = _parse_entity_id(entity_id)
    try:
        return await service.get_for_entity(
            entity_type=entity_type, entity_id=parsed
        )
    except UnknownEntityTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/my/", response_model=list[CollabLockResponse])
async def list_my_locks(
    user_id: CurrentUserId,
    service: CollabLockService = Depends(_get_service),
) -> list[CollabLockResponse]:
    return await service.list_my_locks(user_id=uuid.UUID(user_id))


# ── WebSocket: presence ────────────────────────────────────────────────────


async def _authenticate_ws(token: str | None) -> dict[str, Any] | None:
    """Decode a JWT passed as ``?token=`` on a WebSocket upgrade.

    Returns the payload on success; returns ``None`` on any failure —
    the caller is responsible for closing the socket with 1008.
    BUG-323: payload is re-hydrated against the DB so a forged token
    with a fake UUID cannot open a socket.
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token, get_settings())
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001 — never crash the WS on auth
        logger.exception("WebSocket token decode failed")
        return None

    try:
        from app.core.permissions import permission_registry
        from app.dependencies import verify_user_exists_and_active

        user = await verify_user_exists_and_active(payload["sub"])
        payload["role"] = user.role
        payload["permissions"] = permission_registry.get_role_permissions(user.role)
        return payload
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket user re-hydration failed")
        return None


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

    payload = await _authenticate_ws(token)
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

    # Resolve the display name in its own session so the connection
    # handshake does not piggyback on a request-scoped session.
    async with async_session_factory() as sess:
        user_name = await _resolve_user_name(sess, user_id)

    await websocket.accept()
    # Tag the socket so PresenceHub.leave() can attribute remaining
    # subscribers back to their user ids without a separate map.
    websocket._collab_lock_user_id = user_id  # type: ignore[attr-defined]

    key: PresenceKey = (entity_type, parsed_id)
    roster = await presence_hub.join(
        key, websocket, user_id=user_id, user_name=user_name
    )

    # First frame: full roster + current lock holder (if any) so the
    # client can paint without a follow-up REST round-trip.
    try:
        async with async_session_factory() as sess:
            svc = CollabLockService(sess)
            current_lock = await svc.get_for_entity(
                entity_type=entity_type, entity_id=parsed_id
            )
    except Exception:
        current_lock = None

    try:
        await websocket.send_json(
            {
                "event": "presence_snapshot",
                "users": roster,
                "lock": (
                    current_lock.model_dump(mode="json")
                    if current_lock is not None
                    else None
                ),
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
        # client-side "ping" opportunities but do nothing with them —
        # all interesting traffic is server-push.
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json(
                    {"event": "pong", "ts": _now_iso()}
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("presence websocket crashed")
    finally:
        left_uid = await presence_hub.leave(key, websocket)
        if left_uid is not None:
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
