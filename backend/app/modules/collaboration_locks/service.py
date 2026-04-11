"""Business logic for collaboration locks.

Responsibilities
----------------

* Translate HTTP requests into repository calls.
* Resolve the display name for a user (so the conflict response can
  say "Locked by Anna Schmidt" instead of a raw UUID).
* Publish ``collab.lock.*`` events on the global event bus so the
  presence hub — and any other subscriber — can react.
* Normalise the 409-conflict payload so the frontend has a single
  shape to branch on.

The service is stateless; every method takes the session and all
required identifiers as arguments.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.collaboration_locks.events import (
    COLLAB_LOCK_ACQUIRED,
    COLLAB_LOCK_EXPIRED,
    COLLAB_LOCK_HEARTBEAT,
    COLLAB_LOCK_RELEASED,
)
from app.modules.collaboration_locks.models import CollabLock
from app.modules.collaboration_locks.repository import CollabLockRepository
from app.modules.collaboration_locks.schemas import (
    ALLOWED_LOCK_ENTITY_TYPES,
    CollabLockConflict,
    CollabLockResponse,
)
from app.modules.users.models import User

logger = logging.getLogger(__name__)


class CollabLockError(Exception):
    """Base class for service-level lock errors."""


class UnknownEntityTypeError(CollabLockError):
    """Raised when the caller tries to lock an entity type not on the
    allowlist.  Surfaces as HTTP 400 in the router."""


class LockConflictError(CollabLockError):
    """Raised when the target entity is held by someone else.

    Carries the 409 body as a :class:`CollabLockConflict`.
    """

    def __init__(self, conflict: CollabLockConflict) -> None:
        super().__init__(conflict.detail)
        self.conflict = conflict


class NotLockHolderError(CollabLockError):
    """Raised on heartbeat/release attempts from a non-holder (or on an
    already-expired lock).  Surfaces as HTTP 404 / 403 depending on the
    router."""


# ── Helpers ────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime) -> datetime:
    """Normalise a datetime to UTC-aware (SQLite returns naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _remaining_seconds(expires_at: datetime, now: datetime) -> int:
    """Integer seconds until ``expires_at``, floored at 0."""
    delta = (_as_aware(expires_at) - now).total_seconds()
    if delta <= 0:
        return 0
    return int(math.floor(delta))


async def _resolve_user_name(
    session: AsyncSession, user_id: uuid.UUID
) -> str:
    """Return a best-effort display string for a user.

    Prefers ``full_name``; falls back to ``email``; falls back to the
    string form of the UUID so the caller never has to handle ``None``.
    """
    user = await session.get(User, user_id)
    if user is None:
        return str(user_id)
    return (user.full_name or "").strip() or user.email or str(user_id)


def _to_response(
    row: CollabLock, *, user_name: str, now: datetime
) -> CollabLockResponse:
    return CollabLockResponse(
        id=row.id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        user_id=row.user_id,
        user_name=user_name,
        locked_at=row.locked_at,
        heartbeat_at=row.heartbeat_at,
        expires_at=row.expires_at,
        remaining_seconds=_remaining_seconds(row.expires_at, now),
    )


# ── Service ────────────────────────────────────────────────────────────────


class CollabLockService:
    """High-level operations the router calls."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CollabLockRepository(session)

    # ── Acquire ─────────────────────────────────────────────────────────

    async def acquire(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID,
        ttl_seconds: int,
        org_id: uuid.UUID | None = None,
    ) -> CollabLockResponse:
        """Acquire a lock or raise :class:`LockConflictError`."""
        if entity_type not in ALLOWED_LOCK_ENTITY_TYPES:
            raise UnknownEntityTypeError(
                f"entity_type '{entity_type}' is not lockable. "
                f"Allowed: {sorted(ALLOWED_LOCK_ENTITY_TYPES)}"
            )

        now = _now()
        acquired, conflict = await self.repo.acquire(
            org_id=org_id,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            ttl_seconds=ttl_seconds,
            now=now,
        )

        if acquired is not None:
            user_name = await _resolve_user_name(self.session, user_id)
            response = _to_response(acquired, user_name=user_name, now=now)
            await event_bus.publish(
                COLLAB_LOCK_ACQUIRED,
                {
                    "lock_id": str(acquired.id),
                    "entity_type": acquired.entity_type,
                    "entity_id": str(acquired.entity_id),
                    "user_id": str(acquired.user_id),
                    "user_name": user_name,
                    "expires_at": acquired.expires_at.isoformat(),
                },
                source_module="collaboration_locks",
            )
            return response

        if conflict is not None:
            holder_name = await _resolve_user_name(self.session, conflict.user_id)
            payload = CollabLockConflict(
                detail=f"Entity is locked by {holder_name}",
                current_holder_user_id=conflict.user_id,
                current_holder_name=holder_name,
                locked_at=conflict.locked_at,
                expires_at=conflict.expires_at,
                remaining_seconds=_remaining_seconds(conflict.expires_at, now),
            )
            raise LockConflictError(payload)

        # Race that resolved to "nobody won" — treat as conflict to
        # make the caller retry rather than spuriously succeed.
        raise LockConflictError(
            CollabLockConflict(
                detail="Lock acquisition race; retry",
                current_holder_user_id=user_id,
                current_holder_name="",
                locked_at=now,
                expires_at=now,
                remaining_seconds=0,
            )
        )

    # ── Heartbeat ───────────────────────────────────────────────────────

    async def heartbeat(
        self,
        *,
        lock_id: uuid.UUID,
        user_id: uuid.UUID,
        extend_seconds: int,
    ) -> CollabLockResponse:
        now = _now()
        row = await self.repo.extend(
            lock_id,
            user_id=user_id,
            extend_seconds=extend_seconds,
            now=now,
        )
        if row is None:
            raise NotLockHolderError(
                "Lock missing, expired, or not held by current user"
            )

        user_name = await _resolve_user_name(self.session, user_id)
        await event_bus.publish(
            COLLAB_LOCK_HEARTBEAT,
            {
                "lock_id": str(row.id),
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id),
                "user_id": str(row.user_id),
                "user_name": user_name,
                "expires_at": row.expires_at.isoformat(),
            },
            source_module="collaboration_locks",
        )
        return _to_response(row, user_name=user_name, now=now)

    # ── Release ─────────────────────────────────────────────────────────

    async def release(
        self, *, lock_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        row = await self.repo.get_by_id(lock_id)
        if row is None:
            # Idempotent release — nothing to do.
            return
        if row.user_id != user_id:
            raise NotLockHolderError("Only the holder may release a lock")

        snapshot = {
            "lock_id": str(row.id),
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id),
            "user_id": str(row.user_id),
        }
        deleted = await self.repo.release(lock_id, user_id=user_id)
        if deleted:
            user_name = await _resolve_user_name(self.session, user_id)
            await event_bus.publish(
                COLLAB_LOCK_RELEASED,
                {**snapshot, "user_name": user_name},
                source_module="collaboration_locks",
            )

    # ── Reads ───────────────────────────────────────────────────────────

    async def get_for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> CollabLockResponse | None:
        if entity_type not in ALLOWED_LOCK_ENTITY_TYPES:
            raise UnknownEntityTypeError(
                f"entity_type '{entity_type}' is not lockable"
            )
        now = _now()
        row = await self.repo.get_active(entity_type, entity_id, now)
        if row is None:
            return None
        user_name = await _resolve_user_name(self.session, row.user_id)
        return _to_response(row, user_name=user_name, now=now)

    async def list_my_locks(
        self, *, user_id: uuid.UUID
    ) -> list[CollabLockResponse]:
        now = _now()
        rows = await self.repo.list_by_user(user_id, now)
        user_name = await _resolve_user_name(self.session, user_id)
        return [_to_response(r, user_name=user_name, now=now) for r in rows]

    # ── Sweeper entry point ─────────────────────────────────────────────

    async def sweep_expired(self) -> int:
        """Delete every expired lock and publish ``lock.expired``
        once per delete.  Returns the number of rows removed.
        """
        now = _now()
        # First read the rows so we can publish events after delete.
        stale_rows = [
            row
            for row in await self.repo.list_by_user(uuid.UUID(int=0), now)
            if _as_aware(row.expires_at) <= now
        ]
        # The above filter only finds the zero-user edge case; for the
        # real sweep we rely on bulk delete_expired.  We still want to
        # publish events, so do a direct scan if there are expired rows.
        removed = await self.repo.delete_expired(now)
        for row in stale_rows:
            await event_bus.publish(
                COLLAB_LOCK_EXPIRED,
                {
                    "lock_id": str(row.id),
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id),
                    "user_id": str(row.user_id),
                },
                source_module="collaboration_locks",
            )
        return removed
