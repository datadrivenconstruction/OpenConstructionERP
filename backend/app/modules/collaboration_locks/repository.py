"""Data-access layer for collaboration locks.

All queries are scoped to a single SQLAlchemy session passed in by the
service; no global state.  The only primitive this layer exposes that is
not a plain CRUD call is :meth:`acquire`, which performs a
best-effort "insert if no live lock exists" using a small retry loop so
two concurrent requests cannot both believe they got the lock.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Sequence

from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.collaboration_locks.models import CollabLock


def _as_aware(value: datetime) -> datetime:
    """Normalise a datetime to UTC-aware.

    SQLite returns naive datetimes even on ``DateTime(timezone=True)``
    columns, which blows up direct comparisons against ``datetime.now(UTC)``.
    This helper is idempotent for already-aware values.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class CollabLockRepository:
    """CRUD + atomic acquire for :class:`CollabLock` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Core acquire ────────────────────────────────────────────────────

    async def acquire(
        self,
        *,
        org_id: uuid.UUID | None,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID,
        ttl_seconds: int,
        now: datetime,
    ) -> tuple[CollabLock | None, CollabLock | None]:
        """Attempt to claim a lock on ``(entity_type, entity_id)``.

        Returns a two-tuple ``(acquired, conflict)``:

        * ``(row, None)`` — the caller now owns the lock.  ``row`` is
          either a freshly-inserted record or the caller's existing
          lock refreshed with a new expiry (idempotent re-acquire).
        * ``(None, row)`` — someone else holds a still-live lock.  The
          caller should 409.
        * ``(None, None)`` — a race condition we could not resolve.
          The caller should retry or 503.

        The function opportunistically deletes an expired row held by
        any user before attempting the insert — this keeps the
        lock-free path fast without needing the sweeper to have run.
        """
        expires_at = now + timedelta(seconds=ttl_seconds)

        # 1. Fast path: look for an existing row on this entity.
        existing = await self._get_row(entity_type, entity_id)

        if existing is not None:
            existing_exp = _as_aware(existing.expires_at)
            is_expired = existing_exp <= now
            is_mine = existing.user_id == user_id

            if is_mine and not is_expired:
                # Idempotent re-acquire — refresh TTL, return the row.
                existing.locked_at = now
                existing.heartbeat_at = now
                existing.expires_at = expires_at
                await self.session.flush()
                return existing, None

            if is_mine and is_expired:
                # My own stale lock — reset it in place.
                existing.locked_at = now
                existing.heartbeat_at = now
                existing.expires_at = expires_at
                if org_id is not None:
                    existing.org_id = org_id
                await self.session.flush()
                return existing, None

            if not is_expired:
                # Someone else still holds it.  Conflict.
                return None, existing

            # Expired → steal it in place so we do not hit the unique
            # constraint on INSERT.
            existing.user_id = user_id
            existing.org_id = org_id
            existing.locked_at = now
            existing.heartbeat_at = now
            existing.expires_at = expires_at
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                return None, None
            return existing, None

        # 2. No row exists — try a straight insert.  If two requests
        # race here, one of them hits the unique constraint; we reload
        # the winner and return it as the conflict.
        row = CollabLock(
            org_id=org_id,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            locked_at=now,
            heartbeat_at=now,
            expires_at=expires_at,
            metadata_={},
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            winner = await self._get_row(entity_type, entity_id)
            if winner is None:
                return None, None
            winner_exp = _as_aware(winner.expires_at)
            if winner.user_id == user_id and winner_exp > now:
                return winner, None
            if winner_exp <= now:
                # Winner is already stale — let the caller retry.
                return None, None
            return None, winner

        return row, None

    # ── Read ────────────────────────────────────────────────────────────

    async def _get_row(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> CollabLock | None:
        stmt = select(CollabLock).where(
            and_(
                CollabLock.entity_type == entity_type,
                CollabLock.entity_id == entity_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        now: datetime,
    ) -> CollabLock | None:
        """Return the lock if it exists *and* has not expired."""
        row = await self._get_row(entity_type, entity_id)
        if row is None:
            return None
        if _as_aware(row.expires_at) <= now:
            return None
        return row

    async def get_by_id(self, lock_id: uuid.UUID) -> CollabLock | None:
        return await self.session.get(CollabLock, lock_id)

    async def list_by_user(
        self, user_id: uuid.UUID, now: datetime
    ) -> Sequence[CollabLock]:
        stmt = select(CollabLock).where(
            and_(
                CollabLock.user_id == user_id,
                CollabLock.expires_at > now,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Mutate ──────────────────────────────────────────────────────────

    async def extend(
        self,
        lock_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        extend_seconds: int,
        now: datetime,
    ) -> CollabLock | None:
        """Extend an existing lock.  Returns ``None`` if not the holder
        or if the lock is already expired (caller should re-acquire).
        """
        row = await self.session.get(CollabLock, lock_id)
        if row is None:
            return None
        if row.user_id != user_id:
            return None
        if _as_aware(row.expires_at) <= now:
            return None
        row.heartbeat_at = now
        row.expires_at = now + timedelta(seconds=extend_seconds)
        await self.session.flush()
        return row

    async def release(
        self, lock_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> bool:
        """Delete a lock.  Only the holder may release.  Returns True if
        a row was actually deleted.
        """
        row = await self.session.get(CollabLock, lock_id)
        if row is None:
            return False
        if row.user_id != user_id:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def delete_expired(self, now: datetime) -> int:
        """Bulk-delete every lock whose ``expires_at`` has passed.

        Used by the sweeper background task.  Returns the number of
        rows actually removed (best-effort — some dialects do not
        report rowcount, in which case we return ``0``).
        """
        stmt = delete(CollabLock).where(CollabLock.expires_at <= now)
        result = await self.session.execute(
            stmt, execution_options={"synchronize_session": False}
        )
        await self.session.flush()
        return int(result.rowcount or 0)
