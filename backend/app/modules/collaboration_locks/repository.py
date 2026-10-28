# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data-access layer for collaboration locks.

All queries are scoped to a single SQLAlchemy session passed in by the
service; no global state.  The only primitive this layer exposes that is
not a plain CRUD call is :meth:`acquire`, which performs a
best-effort "insert if no live lock exists" using a small retry loop so
two concurrent requests cannot both believe they got the lock.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.collaboration_locks.models import CollabLock

logger = logging.getLogger(__name__)

# How many times :meth:`CollabLockRepository.acquire` re-reads and tries again
# after losing a write to a concurrent session.  Every retry follows a state
# change another session actually committed, so the loop drains as soon as the
# contention stops; the bound only exists so a pathological hot row cannot pin
# a request forever.
ACQUIRE_MAX_ATTEMPTS = 5


class _LockContendedError(Exception):
    """Internal signal: the row we read changed under us; re-read and retry.

    Never escapes :meth:`CollabLockRepository.acquire`.
    """


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

        * ``(row, None)`` - the caller now owns the lock.  ``row`` is
          either a freshly-inserted record or the caller's existing
          lock refreshed with a new expiry (idempotent re-acquire).
        * ``(None, row)`` - someone else holds a still-live lock.  The
          caller should 409, naming ``row.user_id`` as the holder.
        * ``(None, None)`` - a race we could not resolve within
          :data:`ACQUIRE_MAX_ATTEMPTS` passes.  The caller should retry or 503.

        Every decision here is made from a row read a moment earlier, so every
        write is issued as a compare-and-swap against the row that was read
        (see :meth:`_attempt_acquire`).  PostgreSQL, not this function,
        arbitrates between two callers reaching for the same row: whoever loses
        the write re-reads and tries again, which is how a holder returning to
        an expired lock that someone else has taken over ends up with the new
        holder as its conflict rather than an exception.

        Args:
            org_id: Tenant scope to stamp on the row, or ``None`` to leave it.
            entity_type: Allowlisted entity family (the service validates it).
            entity_id: Identifier of the entity being locked.
            user_id: The caller claiming the lock.
            ttl_seconds: Lifetime of the lock, measured from ``now``.
            now: Caller-supplied clock, so expiry is testable without sleeping.

        Returns:
            The ``(acquired, conflict)`` pair described above.
        """
        for attempt in range(1, ACQUIRE_MAX_ATTEMPTS + 1):
            try:
                return await self._attempt_acquire(
                    org_id=org_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    user_id=user_id,
                    ttl_seconds=ttl_seconds,
                    now=now,
                )
            except _LockContendedError as exc:
                logger.info(
                    "Collaboration lock %s/%s contended for user %s (attempt %d/%d): %s. Re-reading.",
                    entity_type,
                    entity_id,
                    user_id,
                    attempt,
                    ACQUIRE_MAX_ATTEMPTS,
                    exc,
                )

        logger.warning(
            "Collaboration lock %s/%s stayed contended for user %s after %d attempts; caller must retry.",
            entity_type,
            entity_id,
            user_id,
            ACQUIRE_MAX_ATTEMPTS,
        )
        return None, None

    async def _attempt_acquire(
        self,
        *,
        org_id: uuid.UUID | None,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID,
        ttl_seconds: int,
        now: datetime,
    ) -> tuple[CollabLock | None, CollabLock | None]:
        """Run one pass of :meth:`acquire`.

        Raises:
            _LockContendedError: The row moved between the read and the write.
                :meth:`acquire` catches this and starts another pass.
        """
        expires_at = now + timedelta(seconds=ttl_seconds)

        # 1. Fast path: look for an existing row on this entity.
        existing = await self._get_row(entity_type, entity_id)

        if existing is not None:
            existing_exp = _as_aware(existing.expires_at)
            is_expired = existing_exp <= now
            is_mine = existing.user_id == user_id

            if is_mine:
                # Idempotent re-acquire, live or lapsed: refresh the row in
                # place so the lock id the client already holds stays valid.
                values: dict[str, Any] = {
                    "locked_at": now,
                    "heartbeat_at": now,
                    "expires_at": expires_at,
                }
                if is_expired and org_id is not None:
                    # Only the stale-lock reset re-homes the row, as before.
                    values["org_id"] = org_id

                # Compare-and-swap rather than an ORM attribute write.  While
                # the row was expired anyone could take it over, and a takeover
                # DELETEs this row and INSERTs a new one - so by the time we
                # write, the row we based this branch on may be gone.  Flushing
                # an ORM UPDATE that matches nothing raises StaleDataError,
                # which is not IntegrityError and therefore escaped acquire()
                # as an unhandled 500.  Matching zero rows here is data, not an
                # exception: it means we lost, so re-read and answer properly.
                updated = await self.session.execute(
                    update(CollabLock)
                    .where(
                        CollabLock.id == existing.id,
                        CollabLock.user_id == user_id,
                    )
                    .values(**values),
                    execution_options={"synchronize_session": False},
                )
                if updated.rowcount == 0:
                    self._forget(existing)
                    raise _LockContendedError("the lock was taken over before the re-acquire landed")

                # The UPDATE bypassed the ORM, so the instance still carries the
                # previous expiry; the caller renders exactly these attributes.
                await self.session.refresh(existing)
                return existing, None

            if not is_expired:
                # Someone else still holds it.  Conflict.
                return None, existing

            # Expired lock held by another user.  Delete it first, then fall
            # through to the INSERT path.
            #
            # The DELETE is conditional on the row still being expired.  Under
            # READ COMMITTED a bare "WHERE id = :id" would wait for a
            # concurrent UPDATE by the row's own owner and then re-qualify
            # against the *updated* row - deleting a lock that had just come
            # back to life and leaving two callers each believing they hold it.
            # Re-checking expires_at inside the statement makes PostgreSQL
            # settle it: the refreshed row no longer matches, and we lose.
            deleted = await self.session.execute(
                delete(CollabLock).where(
                    CollabLock.id == existing.id,
                    CollabLock.expires_at <= now,
                ),
                execution_options={"synchronize_session": False},
            )
            self._forget(existing)
            if deleted.rowcount == 0:
                raise _LockContendedError("the expired lock was refreshed or removed before the takeover landed")

        # 2. No row exists (or we just deleted the expired one) - try a
        # straight insert.  If two requests race here, one of them hits
        # the unique constraint; the retry re-reads and reports the winner.
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
        except IntegrityError as exc:
            # Someone committed a row for this entity between our read and our
            # INSERT.  The session is poisoned by the failed flush, so it has
            # to be rolled back before anything else can be read on it.
            await self.session.rollback()
            raise _LockContendedError("lost the unique-constraint race on insert") from exc

        return row, None

    def _forget(self, row: CollabLock) -> None:
        """Detach a row whose in-session copy is no longer trustworthy.

        The conditional UPDATE/DELETE statements deliberately run with
        ``synchronize_session=False``, so the identity map still holds the
        pre-write instance.  Leaving it there would make the retry's ``SELECT``
        hand back the same stale attributes and loop on the same wrong
        decision; detaching forces the next read to build the object from the
        row PostgreSQL actually has.
        """
        if row in self.session:
            self.session.expunge(row)

    # ── Read ────────────────────────────────────────────────────────────

    async def _get_row(self, entity_type: str, entity_id: uuid.UUID) -> CollabLock | None:
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

    async def list_by_user(self, user_id: uuid.UUID, now: datetime) -> Sequence[CollabLock]:
        stmt = select(CollabLock).where(
            and_(
                CollabLock.user_id == user_id,
                CollabLock.expires_at > now,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_expired(self, now: datetime) -> Sequence[CollabLock]:
        """Return every lock whose ``expires_at`` has passed.

        The sweeper reads these rows *before* :meth:`delete_expired` so it
        can publish a ``collab.lock.expired`` event per removed lock.  This
        is the inverse predicate of :meth:`list_by_user` (which keeps only
        live locks), so the two never collapse to an empty intersection.
        """
        stmt = select(CollabLock).where(CollabLock.expires_at <= now)
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
        """Extend an existing lock.

        Returns ``None`` when the lock is gone, is held by somebody else, or
        has already expired - in every one of those cases the caller must
        re-acquire rather than renew, and the service turns it into the same
        "not the holder" answer.

        Holder and liveness are predicates of the UPDATE itself rather than
        checks made beforehand, for the same reason :meth:`acquire` writes
        conditionally: the sweeper deletes a lock the moment it expires, and
        the row this heartbeat is renewing may well have been read (or served
        from the session's identity map) while it was still live.  An ORM
        attribute write would then flush an UPDATE matching zero rows, which
        raises ``StaleDataError`` and reaches the browser as a 500 instead of
        the 404 that tells the tab to acquire the lock again.
        """
        renewed = await self.session.execute(
            update(CollabLock)
            .where(
                CollabLock.id == lock_id,
                CollabLock.user_id == user_id,
                CollabLock.expires_at > now,
            )
            .values(heartbeat_at=now, expires_at=now + timedelta(seconds=extend_seconds)),
            execution_options={"synchronize_session": False},
        )
        if renewed.rowcount == 0:
            return None
        # populate_existing: the UPDATE went round the ORM, so a cached
        # instance would still describe the lock as it was before the renewal.
        return await self.session.get(CollabLock, lock_id, populate_existing=True)

    async def release(self, lock_id: uuid.UUID, *, user_id: uuid.UUID) -> bool:
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
        rows actually removed (best-effort - some dialects do not
        report rowcount, in which case we return ``0``).
        """
        stmt = delete(CollabLock).where(CollabLock.expires_at <= now)
        result = await self.session.execute(stmt, execution_options={"synchronize_session": False})
        await self.session.flush()
        return int(result.rowcount or 0)
