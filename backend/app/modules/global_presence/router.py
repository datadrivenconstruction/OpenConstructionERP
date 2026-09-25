# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WebSocket endpoint for app-wide user presence, scoped to a project.

Clients connect to ``/ws/`` and send ``{"type": "auth", "token": "<jwt>"}``
as their first frame (see :mod:`app.core.ws_auth`; the token no longer rides
in the URL, where every access log wrote it down). They then receive a stream
of presence events about the people working in the same project as them: who
joined, who left, and who changed page or went idle. A tab in no project sees
nobody. See :mod:`app.modules.global_presence.hub` for why.

Inbound messages (client -> server)
------------------------------------

* ``{"type": "auth", "token": "<jwt>"}``
  - First frame only. Anything else first closes the socket with 1008.

* ``{"type": "route_update", "route": "/boq/abc123", "project_id": "<uuid>"}``
  - The user navigated, and this is the project the tab is working in
    (``null`` or absent for none). A project the user may not open is
    treated as none.

* ``{"type": "status_update", "status": "idle"}``
  - The user went idle (or came back: ``"active"``).

* ``{"type": "ping"}``
  - Keep-alive. Server replies with ``{"event": "pong", ...}``.

Outbound events (server -> client)
-----------------------------------

* ``presence_snapshot`` - the roster of the tab's project; sent empty on
  connect and again whenever the tab changes project.
* ``presence_join``     - a user's first tab entered this project.
* ``presence_leave``    - a user's last tab left this project or closed.
* ``presence_update``   - a user changed route or status.
* ``pong``              - reply to a client ping.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.ws_auth import refuse_socket, resolve_socket_token
from app.database import async_session_factory
from app.dependencies import decode_access_token
from app.modules.global_presence.hub import global_presence_hub

router = APIRouter(tags=["global_presence"])
logger = logging.getLogger(__name__)


# ── Auth helpers ──────────────────────────────────────────────────────────────


class _AuthenticationUnavailableError(Exception):
    """The token could not be judged, distinct from judging it bad.

    Allows the caller to close 1011 (server error) rather than 1008
    (policy violation) so the client knows the fault is not its credentials.
    """


async def _authenticate_ws(token: str | None) -> dict[str, Any] | None:
    """Judge the access token a WebSocket presented.

    Returns the payload on success, ``None`` when rejected.

    Raises:
        _AuthenticationUnavailableError: the caller could not be judged
            at all (database unreachable, misconfigured secret, etc.).
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token, get_settings())
    except HTTPException:
        return None
    except Exception as exc:  # noqa: BLE001 - stays broad deliberately
        logger.exception("Global presence: WebSocket token decode failed")
        raise _AuthenticationUnavailableError from exc

    try:
        from app.dependencies import verify_user_exists_and_active

        user = await verify_user_exists_and_active(
            payload["sub"],
            issued_at=payload.get("iat"),
            session_id=payload.get("sid"),
        )
        payload["role"] = user.role
        return payload
    except HTTPException:
        return None
    except Exception as exc:  # noqa: BLE001 - stays broad deliberately
        logger.exception("Global presence: WebSocket user re-hydration failed")
        raise _AuthenticationUnavailableError from exc


async def _resolve_user_name(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Return the name other people see on this user's avatar.

    Prefers ``full_name``. Without one it falls back to the part of the email
    before the ``@``: the name is broadcast to everyone in the project, and
    the full address is not something a colleague needs to see on an avatar.
    """
    from app.modules.users.models import User

    user = await session.get(User, user_id)
    if user is None:
        return str(user_id)
    name = (user.full_name or "").strip()
    if name:
        return name
    local = (user.email or "").split("@", 1)[0].strip()
    return local or str(user_id)


async def _accessible_project(user_id: uuid.UUID, raw: object) -> uuid.UUID | None:
    """The project a tab reported, if its user may open it; otherwise ``None``.

    Same rule as every project route (:func:`app.dependencies.verify_project_access`).
    A project the user cannot open is not an error here, it is simply not a
    room they can be in, so the tab is placed in no project.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        project_id = uuid.UUID(raw)
    except (ValueError, TypeError):
        return None
    from app.dependencies import verify_project_access

    try:
        async with async_session_factory() as sess:
            await verify_project_access(project_id, str(user_id), sess)
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001 - never place a tab in a room on an unexpected error
        logger.exception("Global presence: project access check failed")
        return None
    return project_id


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _announce(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    event: str = "presence_update",
    gone: bool = False,
    exclude: WebSocket | None = None,
) -> None:
    """Tell a project's room about one user: gone, or their current entry there.

    A user who still has another tab in the project is not gone; the room gets
    their entry as that tab now makes it.
    """
    entry = None if gone else global_presence_hub.entry(user_id, project_id)
    if entry is None:
        await global_presence_hub.broadcast(
            project_id,
            {"event": "presence_leave", "user_id": str(user_id), "ts": _now_iso()},
            exclude=exclude,
        )
        return
    await global_presence_hub.broadcast(project_id, {"event": event, **entry, "ts": _now_iso()}, exclude=exclude)


# ── WebSocket endpoint ────────────────────────────────────────────────────────


@router.websocket("/ws/")
async def global_presence_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Real-time presence channel, scoped to the tab's project."""

    # ── Authenticate ──────────────────────────────────────────────
    # First frame; ``?token=`` is the previous frontend's spelling, still read
    # for one release (app.core.ws_auth).
    token, accepted = await resolve_socket_token(websocket, token)
    try:
        payload = await _authenticate_ws(token)
    except _AuthenticationUnavailableError:
        await refuse_socket(websocket, code=1011, reason="authentication unavailable")
        return
    if payload is None:
        await refuse_socket(websocket, code=1008, reason="unauthenticated")
        return

    user_id_str = payload.get("sub")
    if not isinstance(user_id_str, str):
        await refuse_socket(websocket, code=1008, reason="invalid token subject")
        return
    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        await refuse_socket(websocket, code=1008, reason="invalid user id")
        return

    # ── Resolve display name ──────────────────────────────────────
    async with async_session_factory() as sess:
        user_name = await _resolve_user_name(sess, user_id)

    if not accepted:
        await websocket.accept()

    # ── Join the hub, outside any project until the tab says which ─
    await global_presence_hub.join(websocket, user_id=user_id, user_name=user_name)
    # The project this tab was last let into, so a route change inside one
    # project does not ask the database again.
    current_project: uuid.UUID | None = None

    try:
        await websocket.send_json({"event": "presence_snapshot", "users": [], "ts": _now_iso()})

        # ── Message loop ─────────────────────────────────────────
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            raw = message.get("text")
            if raw is None:
                continue

            if raw == "ping":
                await websocket.send_json({"event": "pong", "ts": _now_iso()})
                continue

            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict):
                continue

            msg_type = data.get("type")

            if msg_type == "route_update":
                route = data.get("route")
                if not isinstance(route, str) or not route:
                    continue
                requested = data.get("project_id")
                if current_project is not None and requested == str(current_project):
                    project_id: uuid.UUID | None = current_project
                else:
                    project_id = await _accessible_project(user_id, requested)
                current_project = project_id
                change = await global_presence_hub.set_context(websocket, route=route, project_id=project_id)
                if change is None:
                    continue
                if change.old_project != change.new_project:
                    if change.old_project is not None:
                        await _announce(change.old_project, user_id, gone=change.left)
                    await websocket.send_json(
                        {
                            "event": "presence_snapshot",
                            "users": global_presence_hub.roster(change.new_project),
                            "ts": _now_iso(),
                        }
                    )
                    if change.new_project is not None:
                        await _announce(
                            change.new_project,
                            user_id,
                            event="presence_join" if change.entered else "presence_update",
                            exclude=websocket,
                        )
                elif change.new_project is not None:
                    await _announce(change.new_project, user_id, exclude=websocket)

            elif msg_type == "status_update":
                status = data.get("status")
                if isinstance(status, str):
                    where = await global_presence_hub.update_status(websocket, status)
                    if where is not None:
                        await _announce(where[1], user_id, exclude=websocket)

            elif msg_type == "ping":
                await websocket.send_json({"event": "pong", "ts": _now_iso()})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Global presence websocket crashed")
    finally:
        departure = await global_presence_hub.leave(websocket)
        if departure is not None and departure.project_id is not None:
            await _announce(departure.project_id, departure.user_id, gone=departure.left_project)
