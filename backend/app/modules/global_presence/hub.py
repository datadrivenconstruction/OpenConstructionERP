# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""In-memory hub for app-wide user presence, one room per project.

Every authenticated tab holds one socket. A tab reports the project it is
working in, and it sees exactly the people whose tabs report the same project:
who they are, which page they are on, whether they are idle. A tab that is in
no project (the dashboard, settings, the project list) sees nobody and is seen
by nobody.

It used to be a single room shared by every socket on the server, so the
avatar stack in the header showed every signed-in account to every other one,
with the page each was on. Two customers on one server saw each other's names;
an estimator saw a manager working in a project the estimator had never been
invited to. "Shares some project with me" would not have been enough either:
an admin can reach every project, so an admin would still have seen everyone.
The question the avatars answer is "who is in here with me", so the room is
the project the viewer is in, and the router only lets a tab into a project
its user may open.

Design choices
--------------

* **Pure asyncio / stdlib.**  No Redis, no Celery.  Single-worker
  deployments get full fan-out; multi-worker gets correct but
  worker-local presence.  Upgrade path: Postgres LISTEN/NOTIFY.

* **Per-tab state, per-project views.**  ``_connections`` maps each socket to
  its tab state, project included; ``_user_sockets`` maps each user to their
  tabs.  A user's entry in a project's roster is built from that user's tabs
  in the project only, so a second tab elsewhere never leaks its page.

* **Dead-socket scrub on every broadcast.**  If a tab closes without a
  graceful close frame, ``send_json`` raises; we catch it and drop the
  socket so stale entries cannot leak memory.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Per-socket state kept by the hub."""

    user_id: uuid.UUID
    user_name: str
    route: str
    status: str  # "active" | "idle"
    connected_at: datetime
    last_active_at: datetime
    project_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ContextChange:
    """What moving one tab to another project meant for its user.

    ``left`` is True when the user no longer has any tab in ``old_project``,
    ``entered`` when this tab is the user's first in ``new_project``.
    """

    user_id: uuid.UUID
    old_project: uuid.UUID | None
    new_project: uuid.UUID | None
    left: bool
    entered: bool


@dataclass(frozen=True)
class Departure:
    """A closed tab: its user, the project it was in, and whether that was the
    user's last tab there."""

    user_id: uuid.UUID
    project_id: uuid.UUID | None
    left_project: bool


class GlobalPresenceHub:
    """Subscribe / broadcast / disconnect, scoped by project."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, ConnectionInfo] = {}
        self._user_sockets: dict[uuid.UUID, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────

    async def join(
        self,
        ws: WebSocket,
        *,
        user_id: uuid.UUID,
        user_name: str,
        route: str = "/",
    ) -> None:
        """Register ``ws`` outside any project. It sees nobody until it reports one."""
        now = datetime.now(UTC)
        info = ConnectionInfo(
            user_id=user_id,
            user_name=user_name,
            route=route,
            status="active",
            connected_at=now,
            last_active_at=now,
        )
        async with self._lock:
            self._connections[ws] = info
            self._user_sockets.setdefault(user_id, set()).add(ws)

    async def set_context(self, ws: WebSocket, *, route: str, project_id: uuid.UUID | None) -> ContextChange | None:
        """Record the page and project a tab is on.

        ``project_id`` must already be checked against the user's access; the
        hub trusts it. Returns ``None`` for an unknown socket.
        """
        async with self._lock:
            info = self._connections.get(ws)
            if info is None:
                return None
            old = info.project_id
            entered = project_id is not None and project_id != old and not self._user_in(info.user_id, project_id)
            info.route = route
            info.project_id = project_id
            info.last_active_at = datetime.now(UTC)
            left = old is not None and old != project_id and not self._user_in(info.user_id, old)
            return ContextChange(
                user_id=info.user_id,
                old_project=old,
                new_project=project_id,
                left=left,
                entered=entered,
            )

    async def update_status(self, ws: WebSocket, status: str) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Mark a tab active or idle.

        Returns ``(user_id, project_id)`` for the caller to broadcast the
        user's entry into that project, or ``None`` when the socket is unknown,
        the status is not one we accept, or the tab is in no project.
        """
        if status not in ("active", "idle"):
            return None
        async with self._lock:
            info = self._connections.get(ws)
            if info is None:
                return None
            info.status = status
            info.last_active_at = datetime.now(UTC)
            if info.project_id is None:
                return None
            return info.user_id, info.project_id

    async def leave(self, ws: WebSocket) -> Departure | None:
        """Remove ``ws``. ``None`` if it was not registered."""
        async with self._lock:
            info = self._connections.pop(ws, None)
            if info is None:
                return None
            sockets = self._user_sockets.get(info.user_id)
            if sockets is not None:
                sockets.discard(ws)
                if not sockets:
                    del self._user_sockets[info.user_id]
            left = info.project_id is not None and not self._user_in(info.user_id, info.project_id)
            return Departure(user_id=info.user_id, project_id=info.project_id, left_project=left)

    def roster(self, project_id: uuid.UUID | None) -> list[dict[str, Any]]:
        """Everyone with a tab in ``project_id``, one entry each. Empty for ``None``."""
        if project_id is None:
            return []
        entries = []
        for user_id in list(self._user_sockets):
            entry = self.entry(user_id, project_id)
            if entry is not None:
                entries.append(entry)
        return entries

    def entry(self, user_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any] | None:
        """One user as seen from ``project_id``, built from their tabs there only."""
        tabs = [
            info
            for ws in self._user_sockets.get(user_id, ())
            if (info := self._connections.get(ws)) is not None and info.project_id == project_id
        ]
        if not tabs:
            return None
        best = max(tabs, key=lambda i: i.last_active_at)
        return {
            "user_id": str(user_id),
            "user_name": best.user_name,
            "route": best.route,
            "status": "active" if any(i.status == "active" for i in tabs) else "idle",
            "connected_at": min(i.connected_at for i in tabs).isoformat(),
        }

    async def broadcast(
        self,
        project_id: uuid.UUID | None,
        event: dict[str, Any],
        *,
        exclude: WebSocket | None = None,
    ) -> int:
        """Send ``event`` to every tab in ``project_id``; nothing for ``None``.

        Returns the number of successful sends. Dead sockets are scrubbed.
        """
        if project_id is None:
            return 0
        async with self._lock:
            targets = [ws for ws, info in self._connections.items() if info.project_id == project_id]

        sent = 0
        dead: list[WebSocket] = []
        for ws in targets:
            if ws is exclude:
                continue
            try:
                await ws.send_json(event)
                sent += 1
            except Exception:  # noqa: BLE001 - dead socket
                dead.append(ws)

        for ws in dead:
            await self.leave(ws)
        return sent

    # ── Diagnostics ───────────────────────────────────────────────────

    def connection_count(self) -> int:
        """Total number of open WebSocket connections."""
        return len(self._connections)

    def user_count(self) -> int:
        """Number of distinct users connected."""
        return len(self._user_sockets)

    def reset(self) -> None:
        """Drop everything. Used by test teardown."""
        self._connections.clear()
        self._user_sockets.clear()

    # ── Internals ─────────────────────────────────────────────────────

    def _user_in(self, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Whether any of the user's tabs is in ``project_id``."""
        return any(
            (info := self._connections.get(ws)) is not None and info.project_id == project_id
            for ws in self._user_sockets.get(user_id, ())
        )


# Module-level singleton. Each worker process has its own instance.
global_presence_hub = GlobalPresenceHub()
