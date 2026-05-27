"""‌⁠‍Notification API routes.

Endpoints:
    GET    /                              — list current user's notifications
    GET    /unread-count                  — unread count for current user
    POST   /{notification_id}/read        — mark single as read
    POST   /read-all                      — mark all as read
    DELETE /{notification_id}             — delete single notification

Preferences + digest (Wave 3 / T9):
    GET    /preferences/                  — current user's prefs
    POST   /preferences/                  — upsert a pref row
    POST   /digest/flush                  — admin manual digest flush
    GET    /event-types/                  — known event-type catalogue

Epic B (Notifications Dispatcher):
    WS     /ws/                           — real-time push for current user
    GET    /webhooks/                     — admin list webhook targets
    POST   /webhooks/                     — admin create webhook target
    PATCH  /webhooks/{id}/                — admin update webhook target
    DELETE /webhooks/{id}/                — admin delete webhook target
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
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select

from app.config import get_settings
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    SessionDep,
    decode_access_token,
)
from app.modules.notifications.models import WebhookTarget
from app.modules.notifications.schemas import (
    EventTypeCatalogEntry,
    NotificationListResponse,
    NotificationResponse,
    PreferenceRequest,
    PreferenceResponse,
    WebhookTargetCreate,
    WebhookTargetResponse,
    WebhookTargetUpdate,
)
from app.modules.notifications.service import (
    _DIGEST_FLUSHER,
    KNOWN_EVENT_TYPES,
    NotificationService,
)
from app.modules.notifications.ws_hub import notifications_ws_hub

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> NotificationService:
    return NotificationService(session)


def _to_response(n: object) -> NotificationResponse:
    """‌⁠‍Build a NotificationResponse from a Notification ORM object."""
    return NotificationResponse(
        id=n.id,  # type: ignore[attr-defined]
        user_id=n.user_id,  # type: ignore[attr-defined]
        notification_type=n.notification_type,  # type: ignore[attr-defined]
        entity_type=n.entity_type,  # type: ignore[attr-defined]
        entity_id=n.entity_id,  # type: ignore[attr-defined]
        title_key=n.title_key,  # type: ignore[attr-defined]
        body_key=n.body_key,  # type: ignore[attr-defined]
        body_context=n.body_context or {},  # type: ignore[attr-defined]
        action_url=n.action_url,  # type: ignore[attr-defined]
        is_read=n.is_read,  # type: ignore[attr-defined]
        read_at=n.read_at,  # type: ignore[attr-defined]
        metadata=getattr(n, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=n.created_at,  # type: ignore[attr-defined]
        updated_at=n.updated_at,  # type: ignore[attr-defined]
    )


# ── List ────────────────────────────────────────────────────────────────────


@router.get("", response_model=NotificationListResponse, include_in_schema=False)
@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    user_id: CurrentUserId,
    service: NotificationService = Depends(_get_service),
    is_read: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> NotificationListResponse:
    """‌⁠‍List current user's notifications (paginated)."""
    items, total = await service.list_for_user(user_id, is_read=is_read, limit=limit, offset=offset)
    unread = await service.count_unread(user_id)
    return NotificationListResponse(
        items=[_to_response(i) for i in items],
        total=total,
        unread_count=unread,
    )


# ── Unread count ────────────────────────────────────────────────────────────


@router.get("/unread-count/")
async def unread_count(
    user_id: CurrentUserId,
    service: NotificationService = Depends(_get_service),
) -> dict[str, int]:
    """Get the number of unread notifications for the current user."""
    count = await service.count_unread(user_id)
    return {"count": count}


# ── Mark read ───────────────────────────────────────────────────────────────


@router.post("/{notification_id}/read/")
async def mark_read(
    notification_id: uuid.UUID,
    user_id: CurrentUserId,
    service: NotificationService = Depends(_get_service),
) -> dict[str, bool]:
    """Mark a single notification as read."""
    updated = await service.mark_read(notification_id, user_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found or already read",
        )
    return {"success": True}


@router.post("/read-all/")
async def mark_all_read(
    user_id: CurrentUserId,
    service: NotificationService = Depends(_get_service),
) -> dict[str, int]:
    """Mark all notifications as read for the current user."""
    count = await service.mark_all_read(user_id)
    return {"marked_read": count}


# ── Delete ──────────────────────────────────────────────────────────────────


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: uuid.UUID,
    user_id: CurrentUserId,
    service: NotificationService = Depends(_get_service),
) -> None:
    """Delete a single notification."""
    deleted = await service.delete(notification_id, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )


# ── Preferences + digest (Wave 3 / T9) ─────────────────────────────────────


def _pref_to_response(p: object) -> PreferenceResponse:
    return PreferenceResponse(
        id=p.id,  # type: ignore[attr-defined]
        user_id=p.user_id,  # type: ignore[attr-defined]
        event_type=p.event_type,  # type: ignore[attr-defined]
        channel=p.channel,  # type: ignore[attr-defined]
        enabled=p.enabled,  # type: ignore[attr-defined]
        digest=p.digest,  # type: ignore[attr-defined]
        created_at=p.created_at,  # type: ignore[attr-defined]
        updated_at=p.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/preferences/", response_model=list[PreferenceResponse])
async def list_preferences(
    user_id: CurrentUserId,
    service: NotificationService = Depends(_get_service),
) -> list[PreferenceResponse]:
    """‌⁠‍Return all notification preferences for the current user."""
    prefs = await service.get_preferences(user_id)
    return [_pref_to_response(p) for p in prefs]


@router.post("/preferences/", response_model=PreferenceResponse)
async def upsert_preference(
    body: PreferenceRequest,
    user_id: CurrentUserId,
    service: NotificationService = Depends(_get_service),
) -> PreferenceResponse:
    """‌⁠‍Upsert a single (event_type, channel) preference for the current user."""
    pref = await service.set_preference(
        user_id,
        event_type=body.event_type,
        channel=body.channel,
        enabled=body.enabled,
        digest=body.digest,
    )
    return _pref_to_response(pref)


@router.get("/event-types/", response_model=list[EventTypeCatalogEntry])
async def list_event_types(
    user_id: CurrentUserId,  # noqa: ARG001 — auth gate only
) -> list[EventTypeCatalogEntry]:
    """‌⁠‍Return the catalogue of known event-types the platform may emit."""
    return [EventTypeCatalogEntry(**entry) for entry in KNOWN_EVENT_TYPES]


@router.post("/digest/flush/")
async def flush_digest(
    payload: CurrentUserPayload,
    channel: str = Query(default="email", pattern=r"^(email|inapp|webhook)$"),
) -> dict[str, int | str]:
    """‌⁠‍Manually trigger a digest flush for the given channel.

    Admin-only — guarded inline because ``notifications.admin`` is not yet
    registered with the global permission registry; falling back to the
    ``role == 'admin'`` check matches the pattern used by
    :class:`RequirePermission` for the admin role bypass.
    """
    role = payload.get("role", "")
    permissions = payload.get("permissions", []) or []
    if role != "admin" and "notifications.admin" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required",
        )

    count = await _DIGEST_FLUSHER(channel)
    return {"channel": channel, "rows_sent": count}


# ── WebSocket: real-time notification push (Epic B / B6) ──────────────────


async def _authenticate_ws(token: str | None) -> dict[str, Any] | None:
    """‌⁠‍Decode a JWT passed as ``?token=`` on a WebSocket upgrade.

    Matches the collab-locks pattern: returns the payload on success,
    or ``None`` on any failure (the caller closes the socket with
    1008).  The user-id is re-hydrated against the DB so a forged
    token with a fake UUID cannot open a socket.
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token, get_settings())
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001 — never crash the WS on auth
        logger.exception("notifications WS token decode failed")
        return None

    try:
        from app.dependencies import verify_user_exists_and_active

        user = await verify_user_exists_and_active(payload["sub"])
        payload["role"] = user.role
        return payload
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001
        logger.exception("notifications WS user re-hydration failed")
        return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.websocket("/ws/")
async def notifications_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Real-time push channel for the calling user's notifications.

    Wire frame (server → client)::

        {"event": "notification.created", "data": {...}, "ts": "..."}

    The hub is keyed by user-id (taken from the JWT), so a user with
    multiple tabs gets the same fan-out on every open socket.  No
    server-bound traffic is expected; ``ping`` text frames are echoed
    as ``pong`` so a client can keep the socket warm through proxies.
    """
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

    await websocket.accept()
    await notifications_ws_hub.join(user_id, websocket)

    try:
        # First frame: hello so the client knows the channel is live
        # without waiting for the first notification to fire.
        await websocket.send_json(
            {
                "event": "notifications.hello",
                "user_id": str(user_id),
                "ts": _now_iso(),
            }
        )
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"event": "pong", "ts": _now_iso()})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("notifications websocket crashed")
    finally:
        await notifications_ws_hub.leave(user_id, websocket)


# ── Webhook target CRUD (Epic B / B8) ─────────────────────────────────────


def _require_admin(payload: CurrentUserPayload) -> None:
    role = payload.get("role", "")
    perms = payload.get("permissions", []) or []
    if role != "admin" and "notifications.admin" not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required",
        )


def _webhook_to_response(t: WebhookTarget) -> WebhookTargetResponse:
    """Build the response model with ``has_secret`` derived; never leak
    the secret value.
    """
    return WebhookTargetResponse(
        id=t.id,
        name=t.name,
        url=t.url,
        event_filter=t.event_filter,
        has_secret=bool(t.secret),
        active=t.active,
        last_status=t.last_status,
        last_attempt_at=t.last_attempt_at,
        failure_count=t.failure_count,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("/webhooks/", response_model=list[WebhookTargetResponse])
async def list_webhook_targets(
    payload: CurrentUserPayload,
    session: SessionDep,
) -> list[WebhookTargetResponse]:
    """‌⁠‍Admin-only: list every registered webhook target."""
    _require_admin(payload)
    stmt = select(WebhookTarget).order_by(WebhookTarget.created_at.desc())
    rows = list((await session.execute(stmt)).scalars().all())
    return [_webhook_to_response(t) for t in rows]


@router.post(
    "/webhooks/",
    response_model=WebhookTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook_target(
    body: WebhookTargetCreate,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> WebhookTargetResponse:
    """‌⁠‍Admin-only: register a new webhook target."""
    _require_admin(payload)
    target = WebhookTarget(
        name=body.name,
        url=body.url,
        event_filter=body.event_filter or "*",
        secret=body.secret,
        active=body.active,
    )
    session.add(target)
    await session.flush()
    await session.commit()
    return _webhook_to_response(target)


@router.patch("/webhooks/{target_id}/", response_model=WebhookTargetResponse)
async def update_webhook_target(
    target_id: uuid.UUID,
    body: WebhookTargetUpdate,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> WebhookTargetResponse:
    """‌⁠‍Admin-only: partial update on an existing webhook target."""
    _require_admin(payload)
    target = await session.get(WebhookTarget, target_id)
    if target is None:
        # IDOR-as-404 per project security convention.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook target not found",
        )
    if body.name is not None:
        target.name = body.name
    if body.url is not None:
        target.url = body.url
    if body.event_filter is not None:
        target.event_filter = body.event_filter
    if body.secret is not None:
        # Pass empty string to clear; non-empty to set.
        target.secret = body.secret or None
    if body.active is not None:
        target.active = body.active
    await session.flush()
    await session.commit()
    return _webhook_to_response(target)


@router.delete("/webhooks/{target_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_target(
    target_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> None:
    """‌⁠‍Admin-only: delete a webhook target."""
    _require_admin(payload)
    target = await session.get(WebhookTarget, target_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook target not found",
        )
    await session.delete(target)
    await session.commit()
