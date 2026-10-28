"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG contract tests for ``collaboration_locks``: races, expiry, and ownership.

The module had zero coverage. Its whole purpose is arbitrating between two
people who reach for the same row at the same moment, so the interesting
behaviour only exists under real concurrency: the ``acquire`` fast path, the
``IntegrityError`` recovery after losing the unique constraint, takeover of an
expired lock, and the holder-only gate on heartbeat / release.

Why this lane
~~~~~~~~~~~~~
``uq_collab_lock_entity`` is what makes ``acquire`` safe, and only a real
PostgreSQL cluster raises on it the way production does. ``tests/pg`` is also
the single suite the *CI (PostgreSQL)* workflow runs, so a regression here
blocks a merge.

Two isolation styles are used deliberately:

* ``pg_session`` (savepoint-isolated) for everything single-connection.
* ``committed_locks`` for the genuine two-connection races. The savepoint
  fixture cannot express those: a second connection never sees its uncommitted
  rows, and ``repository.acquire`` calls ``session.rollback()`` on conflict,
  which on a savepoint-joined session would unwind the seeded fixture data
  along with the failed INSERT.

Clock handling: expiry is driven through the explicit ``now`` argument the
repository already takes, and by seeding locks with a non-positive
``ttl_seconds`` (neither the service nor the repository re-validates the
Pydantic bounds). Nothing here sleeps.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import event_bus
from app.modules.collaboration_locks.events import (
    COLLAB_LOCK_EXPIRED,
    COLLAB_LOCK_RELEASED,
)
from app.modules.collaboration_locks.models import CollabLock
from app.modules.collaboration_locks.repository import CollabLockRepository
from app.modules.collaboration_locks.service import (
    CollabLockService,
    LockConflictError,
    NotLockHolderError,
    UnknownEntityTypeError,
)
from app.modules.users.models import User

ENTITY_TYPE = "boq"


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime) -> datetime:
    """Make a stored timestamp comparable to ``_now()``.

    PostgreSQL hands these back tz-aware, but the models are also exercised
    through dialects that do not, and a naive/aware comparison raises rather
    than failing an assertion - which would read as a broken test, not a
    broken lock.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _make_user(session: AsyncSession, label: str) -> User:
    """Insert a user whose display name is distinctive enough to assert on."""
    user = User(
        email=f"lock-{label}-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        full_name=f"Lock Tester {label}",
    )
    session.add(user)
    await session.flush()
    return user


async def _lock_snapshot(session: AsyncSession, entity_id: uuid.UUID):
    """Read ``(id, user_id, expires_at)`` for an entity's lock, or ``None``.

    Selecting COLUMNS rather than the entity is what makes this trustworthy:
    ``session.get()`` (and an entity ``select`` that hits a live identity map)
    can answer without touching SQL, so a row deleted in this same session
    still looks present. A column select always emits the query, and autoflush
    pushes any pending delete first, so absence here means genuinely absent.
    """
    result = await session.execute(
        select(CollabLock.id, CollabLock.user_id, CollabLock.expires_at).where(
            CollabLock.entity_type == ENTITY_TYPE, CollabLock.entity_id == entity_id
        )
    )
    return result.one_or_none()


async def _count_rows(session: AsyncSession, entity_id: uuid.UUID) -> int:
    result = await session.execute(
        select(CollabLock.id).where(CollabLock.entity_type == ENTITY_TYPE, CollabLock.entity_id == entity_id)
    )
    return len(list(result.scalars().all()))


async def _seed_expired_lock(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
) -> CollabLock:
    """Create a lock that is already past its expiry, without touching the clock."""
    repo = CollabLockRepository(session)
    acquired, _ = await repo.acquire(
        org_id=None,
        entity_type=ENTITY_TYPE,
        entity_id=entity_id,
        user_id=user_id,
        ttl_seconds=-5,
        now=_now(),
    )
    assert acquired is not None, "seeding an expired lock must still insert the row"
    return acquired


class _Recorder:
    """Captured bus payloads, queryable by the ids the test itself created.

    ``event_bus`` is process-global and the loop is session-scoped, so a
    recorder leaked by another test must not be able to corrupt this one's
    assertions - hence filtering by entity id rather than trusting isolation.
    """

    def __init__(self) -> None:
        self.events: list[dict] = []

    def lock_ids_for(self, entity_id: uuid.UUID) -> list[str]:
        return [e.get("lock_id", "") for e in self.events if e.get("entity_id") == str(entity_id)]


@pytest.fixture
def recorder(request: pytest.FixtureRequest) -> Iterator[_Recorder]:
    """Subscribe an event recorder for the event name given via indirect param.

    The handler must be a real ``async def`` function: ``EventBus.publish``
    branches on ``inspect.iscoroutinefunction``, and a callable object fails
    that check, so it would be dispatched to a thread and its coroutine
    dropped un-awaited.
    """
    event_name = getattr(request, "param", COLLAB_LOCK_EXPIRED)
    rec = _Recorder()

    async def record(event: object) -> None:
        rec.events.append(dict(getattr(event, "data", {}) or {}))

    event_bus.subscribe(event_name, record)
    try:
        yield rec
    finally:
        event_bus.unsubscribe(event_name, record)


class _CommittedLocks:
    """Hands out independent, committing sessions and cleans up after itself."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self.user_ids: list[uuid.UUID] = []

    def session(self) -> AsyncSession:
        return self._factory()

    async def seed_users(self, count: int) -> list[uuid.UUID]:
        """Create and COMMIT ``count`` users so every connection can see them."""
        async with self.session() as session:
            users = [await _make_user(session, f"c{i}") for i in range(count)]
            ids = [u.id for u in users]
            await session.commit()
        self.user_ids.extend(ids)
        return ids

    async def cleanup(self) -> None:
        """Delete the committed users; locks follow via ON DELETE CASCADE."""
        if not self.user_ids:
            return
        async with self.session() as session:
            for user in list(await session.execute(select(User).where(User.id.in_(self.user_ids)))):
                await session.delete(user[0])
            await session.commit()


@pytest_asyncio.fixture
async def committed_locks(pg_engine):
    """Two-connection harness with real commits (see the module docstring)."""
    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    harness = _CommittedLocks(factory)
    try:
        yield harness
    finally:
        await harness.cleanup()


# ── Conflict: the fast path ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_holder_is_refused_and_told_who_holds_it(pg_session) -> None:
    """A live lock blocks everyone else, and the 409 body names the real holder."""
    holder = await _make_user(pg_session, "holder")
    rival = await _make_user(pg_session, "rival")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)

    granted = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=60)
    assert granted.user_id == holder.id

    with pytest.raises(LockConflictError) as excinfo:
        await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=rival.id, ttl_seconds=60)

    conflict = excinfo.value.conflict
    # Naming the holder is the point of the payload: a stub that raised a bare
    # 409 without identifying anyone would pass a weaker assertion.
    assert conflict.current_holder_user_id == holder.id
    assert conflict.current_holder_name == "Lock Tester holder"
    assert "Lock Tester holder" in conflict.detail
    assert 0 < conflict.remaining_seconds <= 60
    assert await _count_rows(pg_session, entity_id) == 1, "a refused acquire must not leave a second row"


@pytest.mark.asyncio
async def test_reacquiring_your_own_lock_reuses_the_row_and_extends_it(pg_session) -> None:
    """Re-acquire is idempotent: same row id, later expiry, still exactly one row."""
    holder = await _make_user(pg_session, "holder")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)

    first = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=30)
    second = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=120)

    assert second.id == first.id, "re-acquire must refresh the existing row, not mint a new one"
    assert second.expires_at > first.expires_at
    assert await _count_rows(pg_session, entity_id) == 1


# ── Conflict: losing the unique-constraint race ────────────────────────────


@pytest.mark.asyncio
async def test_losing_the_unique_constraint_race_returns_the_committed_winner(committed_locks) -> None:
    """The INSERT branch must recover from a real ``uq_collab_lock_entity`` violation.

    Reaching that branch deterministically needs the fast-path lookup to miss
    while a committed row exists - exactly the window two racing requests hit.
    We force it by blinding ``_get_row`` for one call, so the INSERT goes to the
    database and PostgreSQL, not the test, produces the conflict.
    """
    holder_id, rival_id = await committed_locks.seed_users(2)
    entity_id = uuid.uuid4()

    async with committed_locks.session() as winner_session:
        winner_repo = CollabLockRepository(winner_session)
        won, _ = await winner_repo.acquire(
            org_id=None,
            entity_type=ENTITY_TYPE,
            entity_id=entity_id,
            user_id=holder_id,
            ttl_seconds=120,
            now=_now(),
        )
        assert won is not None
        winner_lock_id = won.id
        await winner_session.commit()

    async with committed_locks.session() as loser_session:
        loser_repo = CollabLockRepository(loser_session)
        real_get_row = loser_repo._get_row
        calls = {"n": 0}

        async def blind_first_lookup(entity_type: str, eid: uuid.UUID) -> CollabLock | None:
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_get_row(entity_type, eid)

        loser_repo._get_row = blind_first_lookup  # type: ignore[method-assign]
        acquired, conflict = await loser_repo.acquire(
            org_id=None,
            entity_type=ENTITY_TYPE,
            entity_id=entity_id,
            user_id=rival_id,
            ttl_seconds=120,
            now=_now(),
        )

        # Guard the scaffolding: if a refactor stops routing through _get_row,
        # this test must fail loudly rather than quietly retest the fast path.
        assert calls["n"] >= 2, "acquire must re-read the winner after the IntegrityError"
        assert acquired is None, "the loser must not believe it holds the lock"
        assert conflict is not None, "the loser must be handed the winning row"
        assert conflict.user_id == holder_id
        assert conflict.id == winner_lock_id
        assert await _count_rows(loser_session, entity_id) == 1


@pytest.mark.asyncio
async def test_two_connections_racing_produce_exactly_one_holder(committed_locks) -> None:
    """A genuine two-connection race resolves to one winner both sides agree on."""
    user_a, user_b = await committed_locks.seed_users(2)
    entity_id = uuid.uuid4()

    async def contend(user_id: uuid.UUID) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """Return (holder_id_if_won, holder_id_if_conflicted)."""
        async with committed_locks.session() as session:
            repo = CollabLockRepository(session)
            acquired, conflict = await repo.acquire(
                org_id=None,
                entity_type=ENTITY_TYPE,
                entity_id=entity_id,
                user_id=user_id,
                ttl_seconds=120,
                now=_now(),
            )
            won = acquired.user_id if acquired is not None else None
            lost_to = conflict.user_id if conflict is not None else None
            await session.commit()
            return won, lost_to

    # Bounded: the losing INSERT blocks on the winner's uncommitted row, and the
    # PG lane runs without a global pytest timeout, so a regression that
    # deadlocks must fail the test rather than hang the gate.
    results = await asyncio.wait_for(
        asyncio.gather(contend(user_a), contend(user_b)),
        timeout=30,
    )

    winners = [won for won, _ in results if won is not None]
    assert len(winners) == 1, f"exactly one connection may hold the lock, got {results}"
    losers = [lost_to for _, lost_to in results if lost_to is not None]
    for lost_to in losers:
        assert lost_to == winners[0], "the loser must be pointed at the actual winner"

    async with committed_locks.session() as session:
        assert await _count_rows(session, entity_id) == 1


@pytest.mark.asyncio
async def test_two_connections_racing_to_take_over_the_same_expired_lock(committed_locks) -> None:
    """Racing takeovers of one STALE lock must resolve, not explode.

    This is the intersection of the two hazards the module exists for: a holder
    who vanished, and two people reaching for the freed row at once.

    Left to chance the two callers do not actually collide - the first finishes
    its whole takeover before the second reads, so the second just sees a fresh
    live lock and takes the ordinary conflict fast path. The barrier removes
    that luck: both callers complete their SELECT of the expired row before
    either writes, which is precisely the interleaving the delete-then-insert
    takeover exists to survive - both hold a snapshot that says the row is free.
    """
    stale_owner, user_a, user_b = await committed_locks.seed_users(3)
    entity_id = uuid.uuid4()

    # The stale lock belongs to a THIRD user, so both racers take the
    # delete-then-insert takeover branch rather than one of them re-acquiring
    # its own row through the in-place reset branch.
    async with committed_locks.session() as seed_session:
        await _seed_expired_lock(seed_session, entity_id=entity_id, user_id=stale_owner)
        await seed_session.commit()

    # Both callers must hold the same pre-delete snapshot before either writes.
    # Only the FIRST lookup waits: acquire() calls _get_row again on its
    # IntegrityError recovery path, and a second wait would never be matched.
    barrier = asyncio.Barrier(2)

    async def take_over(user_id: uuid.UUID) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        async with committed_locks.session() as session:
            repo = CollabLockRepository(session)
            real_get_row = repo._get_row
            seen = {"first": True}

            async def synchronised_get_row(entity_type: str, eid: uuid.UUID) -> CollabLock | None:
                row = await real_get_row(entity_type, eid)
                if seen["first"]:
                    seen["first"] = False
                    await barrier.wait()
                return row

            repo._get_row = synchronised_get_row  # type: ignore[method-assign]
            acquired, conflict = await repo.acquire(
                org_id=None,
                entity_type=ENTITY_TYPE,
                entity_id=entity_id,
                user_id=user_id,
                ttl_seconds=120,
                now=_now(),
            )
            won = acquired.user_id if acquired is not None else None
            lost_to = conflict.user_id if conflict is not None else None
            await session.commit()
            return won, lost_to

    # Bounded: the PG lane runs without a global pytest timeout, so a blocked
    # row lock must fail this test rather than hang the gate.
    results = await asyncio.wait_for(
        asyncio.gather(take_over(user_a), take_over(user_b)),
        timeout=30,
    )

    winners = [won for won, _ in results if won is not None]
    assert len(winners) == 1, f"exactly one caller may take over the lock, got {results}"
    assert stale_owner not in winners, "the vanished holder must not keep the lock"
    async with committed_locks.session() as session:
        assert await _count_rows(session, entity_id) == 1, "takeover must leave exactly one row"


async def _take_the_lock_over(
    committed_locks: _CommittedLocks,
    *,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Claim ``entity_id`` for ``user_id`` on its own connection and COMMIT.

    Returns the id of the row now holding the lock, so a caller can assert that
    the takeover really replaced the row it was racing against.
    """
    async with committed_locks.session() as rival_session:
        taken, _ = await CollabLockRepository(rival_session).acquire(
            org_id=None,
            entity_type=ENTITY_TYPE,
            entity_id=entity_id,
            user_id=user_id,
            ttl_seconds=120,
            now=_now(),
        )
        assert taken is not None, "the rival must win the freed lock"
        taken_id = taken.id
        await rival_session.commit()
    return taken_id


def _pin_the_stale_snapshot(
    repo: CollabLockRepository,
    snapshot: CollabLock,
) -> dict[str, int]:
    """Make the repository's FIRST row lookup return a pre-takeover view.

    This is the whole TOCTOU window in one line: the returning tab decided what
    to do from a row that no longer exists. Only the first call is blinded -
    the real world does not freeze the row forever, and a repository that
    re-reads after losing must be able to see what actually happened. The
    returned counter lets the test prove the re-read happened.
    """
    real_get_row = repo._get_row
    calls = {"n": 0}

    async def stale_first_lookup(entity_type: str, eid: uuid.UUID) -> CollabLock | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return snapshot
        return await real_get_row(entity_type, eid)

    repo._get_row = stale_first_lookup  # type: ignore[method-assign]
    return calls


@pytest.mark.asyncio
async def test_stale_owner_reacquiring_a_lock_someone_else_took_over(committed_locks) -> None:
    """The vanished holder coming back must lose gracefully, not crash.

    The realistic story: a tab sleeps, its lock expires, a colleague claims the
    freed row, and the first tab wakes and re-acquires. The returning holder
    still carries a pre-takeover view of the row, which is exactly the TOCTOU
    window ``repository.py`` describes - and the branch it lands in, "my own
    stale lock, reset it in place", used to write through the ORM against a row
    that had already been deleted, which raises ``StaleDataError`` and reaches
    the client as a 500.

    The contract asserted here is deliberately strict. Returning ``(None,
    None)`` would also avoid the crash, but the service turns that into an
    anonymous "retry" 409 - the returning tab must instead be handed the rival's
    live row, because naming the new holder is the only answer the UI can use.

    Sequenced rather than raced: the outcome of a bare ``gather`` depends on
    which coroutine the loop resumes first. Pinning the stale holder's snapshot
    reproduces the same interleaving every run.
    """
    returning_owner, rival = await committed_locks.seed_users(2)
    entity_id = uuid.uuid4()

    async with committed_locks.session() as seed_session:
        await _seed_expired_lock(seed_session, entity_id=entity_id, user_id=returning_owner)
        await seed_session.commit()

    async with committed_locks.session() as owner_session:
        owner_repo = CollabLockRepository(owner_session)
        # The returning holder reads the row BEFORE the takeover lands.
        stale_snapshot = await owner_repo._get_row(ENTITY_TYPE, entity_id)
        assert stale_snapshot is not None

        rival_lock_id = await _take_the_lock_over(committed_locks, entity_id=entity_id, user_id=rival)
        assert rival_lock_id != stale_snapshot.id, "a takeover replaces the row, it does not reassign it"

        calls = _pin_the_stale_snapshot(owner_repo, stale_snapshot)
        acquired, conflict = await owner_repo.acquire(
            org_id=None,
            entity_type=ENTITY_TYPE,
            entity_id=entity_id,
            user_id=returning_owner,
            ttl_seconds=120,
            now=_now(),
        )

        # Guard the scaffolding: losing the row has to send acquire back to the
        # database. If a refactor stops re-reading, this test must fail loudly
        # rather than quietly assert on a lucky first read.
        assert calls["n"] >= 2, "acquire must re-read the row after losing it"
        assert acquired is None, "the returning holder must not reclaim a lock someone else owns"
        assert conflict is not None, "losing the row must produce a named holder, not a bare retry"
        assert conflict.user_id == rival
        assert conflict.id == rival_lock_id
        assert _as_aware(conflict.expires_at) > _now(), "the conflict must be the rival's LIVE lock"
        assert await _count_rows(owner_session, entity_id) == 1, "a lost re-acquire must not add a row"


@pytest.mark.asyncio
async def test_the_returning_tab_is_handed_a_conflict_body_naming_the_new_holder(committed_locks) -> None:
    """The service layer turns the lost race into the 409 payload, not a 500.

    Same interleaving as the test above, one layer up, because the repository's
    ``(None, row)`` is only useful if it survives the trip to something the
    browser can render. ``LockConflictError`` is what the router answers 409
    with, so asserting the holder's *name* here is asserting what the user sees.
    """
    returning_owner, rival = await committed_locks.seed_users(2)
    entity_id = uuid.uuid4()

    async with committed_locks.session() as seed_session:
        await _seed_expired_lock(seed_session, entity_id=entity_id, user_id=returning_owner)
        await seed_session.commit()

    async with committed_locks.session() as owner_session:
        service = CollabLockService(owner_session)
        stale_snapshot = await service.repo._get_row(ENTITY_TYPE, entity_id)
        assert stale_snapshot is not None

        await _take_the_lock_over(committed_locks, entity_id=entity_id, user_id=rival)
        rival_user = await owner_session.get(User, rival)
        assert rival_user is not None
        rival_name = rival_user.full_name

        calls = _pin_the_stale_snapshot(service.repo, stale_snapshot)
        with pytest.raises(LockConflictError) as excinfo:
            await service.acquire(
                entity_type=ENTITY_TYPE,
                entity_id=entity_id,
                user_id=returning_owner,
                ttl_seconds=120,
            )

    assert calls["n"] >= 2, "acquire must re-read the row after losing it"
    conflict = excinfo.value.conflict
    assert conflict.current_holder_user_id == rival
    # An empty name is what the unresolvable-race payload carries, so asserting
    # the real one separates "we know who has it" from "we gave up".
    assert conflict.current_holder_name == rival_name
    assert rival_name in conflict.detail
    assert conflict.remaining_seconds > 0


@pytest.mark.asyncio
async def test_a_returning_owner_and_a_rival_racing_for_one_stale_row(committed_locks) -> None:
    """The asymmetric race: one caller resets the row, the other replaces it.

    The sibling race above gives the stale lock to a THIRD user, so both racers
    take the delete-then-insert path. Here the stale lock belongs to one of the
    two racers, so the returning owner takes the in-place reset branch while the
    rival takes the takeover branch - two different writes aimed at the same
    row, which is the interleaving neither of the existing races covers.

    Both orderings must resolve to one holder. If the owner's reset lands first
    the rival must not delete the lock that is now live again; if the rival's
    takeover lands first the owner's reset must not update a row that is gone.
    """
    returning_owner, rival = await committed_locks.seed_users(2)
    entity_id = uuid.uuid4()

    async with committed_locks.session() as seed_session:
        await _seed_expired_lock(seed_session, entity_id=entity_id, user_id=returning_owner)
        await seed_session.commit()

    # Both callers must hold the same pre-write snapshot before either writes.
    # Only the FIRST lookup waits: acquire() re-reads when it loses, and a
    # second wait would never be matched.
    barrier = asyncio.Barrier(2)

    async def contend(user_id: uuid.UUID) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        async with committed_locks.session() as session:
            repo = CollabLockRepository(session)
            real_get_row = repo._get_row
            seen = {"first": True}

            async def synchronised_get_row(entity_type: str, eid: uuid.UUID) -> CollabLock | None:
                row = await real_get_row(entity_type, eid)
                if seen["first"]:
                    seen["first"] = False
                    await barrier.wait()
                return row

            repo._get_row = synchronised_get_row  # type: ignore[method-assign]
            acquired, conflict = await repo.acquire(
                org_id=None,
                entity_type=ENTITY_TYPE,
                entity_id=entity_id,
                user_id=user_id,
                ttl_seconds=120,
                now=_now(),
            )
            won = acquired.user_id if acquired is not None else None
            lost_to = conflict.user_id if conflict is not None else None
            await session.commit()
            return won, lost_to

    # Bounded: the loser blocks on the winner's row lock, and the PG lane runs
    # without a global pytest timeout, so a regression must fail rather than hang.
    results = await asyncio.wait_for(
        asyncio.gather(contend(returning_owner), contend(rival)),
        timeout=30,
    )

    winners = [won for won, _ in results if won is not None]
    assert len(winners) == 1, f"exactly one caller may hold the lock, got {results}"
    losers = [lost_to for _, lost_to in results if lost_to is not None]
    assert losers, "the caller that lost must be told who won, not left empty-handed"
    for lost_to in losers:
        assert lost_to == winners[0], "the loser must be pointed at the actual winner"

    async with committed_locks.session() as session:
        assert await _count_rows(session, entity_id) == 1, "the race must leave exactly one row"
        snapshot = await _lock_snapshot(session, entity_id)
        assert snapshot is not None
        assert snapshot.user_id == winners[0], "the surviving row must belong to the reported winner"
        assert _as_aware(snapshot.expires_at) > _now(), "the surviving lock must be live"


@pytest.mark.asyncio
async def test_a_stale_takeover_must_not_delete_a_lock_that_came_back_to_life(committed_locks) -> None:
    """The other half of the same race, with the writes in the opposite order.

    Here the rival is the one holding a pre-write snapshot: it read the row
    while it was expired, and by the time it writes, the original holder has
    reclaimed it. Deleting by primary key alone is not safe under READ
    COMMITTED - the rival's DELETE waits for the owner's UPDATE and is then
    re-checked against the *updated* row, so it would remove a lock that is
    live again and leave two clients each believing they hold it.

    Sequenced rather than raced, for the same reason as the sibling above: the
    order of the two writes is the whole point, so it must not be left to the
    scheduler.
    """
    returning_owner, rival = await committed_locks.seed_users(2)
    entity_id = uuid.uuid4()

    async with committed_locks.session() as seed_session:
        seeded_id = (await _seed_expired_lock(seed_session, entity_id=entity_id, user_id=returning_owner)).id
        await seed_session.commit()

    async with committed_locks.session() as rival_session:
        rival_repo = CollabLockRepository(rival_session)
        # The rival reads the row while it is still expired...
        stale_snapshot = await rival_repo._get_row(ENTITY_TYPE, entity_id)
        assert stale_snapshot is not None

        # ...and the owner reclaims it in place before the rival gets to write.
        async with committed_locks.session() as owner_session:
            reclaimed, _ = await CollabLockRepository(owner_session).acquire(
                org_id=None,
                entity_type=ENTITY_TYPE,
                entity_id=entity_id,
                user_id=returning_owner,
                ttl_seconds=120,
                now=_now(),
            )
            assert reclaimed is not None, "the owner must be able to reclaim its own lapsed lock"
            assert reclaimed.id == seeded_id, "an in-place reset keeps the row"
            await owner_session.commit()

        calls = _pin_the_stale_snapshot(rival_repo, stale_snapshot)
        acquired, conflict = await rival_repo.acquire(
            org_id=None,
            entity_type=ENTITY_TYPE,
            entity_id=entity_id,
            user_id=rival,
            ttl_seconds=120,
            now=_now(),
        )
        await rival_session.commit()

    assert acquired is None, "the rival must not take over a lock that is live again"
    assert calls["n"] >= 2, "a takeover that matched nothing must re-read before answering"
    assert conflict is not None, "the rival must be told who holds it now"
    assert conflict.user_id == returning_owner
    assert conflict.id == seeded_id

    async with committed_locks.session() as session:
        assert await _count_rows(session, entity_id) == 1
        snapshot = await _lock_snapshot(session, entity_id)
        assert snapshot is not None
        assert snapshot.id == seeded_id, "the reclaimed lock must survive the stale takeover"
        assert snapshot.user_id == returning_owner
        assert _as_aware(snapshot.expires_at) > _now(), "the surviving lock must still be live"


@pytest.mark.asyncio
async def test_reclaiming_your_own_expired_lock_keeps_the_row(pg_session) -> None:
    """Uncontended, a lapsed holder simply gets its own row back.

    The negative direction of the race fix: guarding the in-place reset must not
    turn it into a refusal. Keeping the row id matters - the client is still
    holding that id, and minting a new one would silently invalidate its
    heartbeat and release calls.
    """
    holder = await _make_user(pg_session, "holder")
    entity_id = uuid.uuid4()
    stale = await _seed_expired_lock(pg_session, entity_id=entity_id, user_id=holder.id)
    stale_id, stale_expiry = stale.id, _as_aware(stale.expires_at)

    service = CollabLockService(pg_session)
    reclaimed = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=60)

    assert reclaimed.id == stale_id, "reclaiming my own lapsed lock must reuse the row"
    assert _as_aware(reclaimed.expires_at) > stale_expiry
    assert reclaimed.remaining_seconds > 0, "the reclaimed lock must read as live, not as the old expiry"
    snapshot = await _lock_snapshot(pg_session, entity_id)
    assert snapshot is not None
    assert snapshot.user_id == holder.id
    assert _as_aware(snapshot.expires_at) == _as_aware(reclaimed.expires_at), "the row must carry the new expiry"
    assert await _count_rows(pg_session, entity_id) == 1


# ── Expiry ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_expired_lock_is_taken_over_by_a_different_user(pg_session) -> None:
    """A stale holder cannot keep an entity hostage: the row is replaced, not shared."""
    stale = await _make_user(pg_session, "stale")
    fresh = await _make_user(pg_session, "fresh")
    entity_id = uuid.uuid4()

    old = await _seed_expired_lock(pg_session, entity_id=entity_id, user_id=stale.id)
    old_id = old.id

    service = CollabLockService(pg_session)
    granted = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=fresh.id, ttl_seconds=60)

    assert granted.user_id == fresh.id
    assert granted.id != old_id, "takeover replaces the stale row rather than reassigning it"
    assert granted.remaining_seconds > 0
    snapshot = await _lock_snapshot(pg_session, entity_id)
    assert snapshot is not None
    assert snapshot.user_id == fresh.id
    assert await _count_rows(pg_session, entity_id) == 1


@pytest.mark.asyncio
async def test_expiry_hides_the_lock_before_the_row_is_deleted(pg_session) -> None:
    """``get_active`` is the live view; the row itself survives until swept."""
    holder = await _make_user(pg_session, "holder")
    entity_id = uuid.uuid4()
    await _seed_expired_lock(pg_session, entity_id=entity_id, user_id=holder.id)

    repo = CollabLockRepository(pg_session)
    assert await repo.get_active(ENTITY_TYPE, entity_id, _now()) is None, "an expired lock must not read as held"
    assert await _count_rows(pg_session, entity_id) == 1, "expiry is logical; only the sweeper deletes"

    service = CollabLockService(pg_session)
    assert await service.get_for_entity(entity_type=ENTITY_TYPE, entity_id=entity_id) is None


@pytest.mark.asyncio
async def test_list_my_locks_omits_expired_ones(pg_session) -> None:
    """The "what am I holding" view must not report locks the user already lost."""
    holder = await _make_user(pg_session, "holder")
    live_entity, dead_entity = uuid.uuid4(), uuid.uuid4()
    service = CollabLockService(pg_session)

    await service.acquire(entity_type=ENTITY_TYPE, entity_id=live_entity, user_id=holder.id, ttl_seconds=60)
    await _seed_expired_lock(pg_session, entity_id=dead_entity, user_id=holder.id)

    mine = await service.list_my_locks(user_id=holder.id)
    held = {lock.entity_id for lock in mine}
    assert live_entity in held
    assert dead_entity not in held


@pytest.mark.parametrize("recorder", [COLLAB_LOCK_EXPIRED], indirect=True)
@pytest.mark.asyncio
async def test_sweep_removes_only_expired_locks_and_announces_each(pg_session, recorder) -> None:
    """The sweep deletes every stale lock, spares live ones, and emits one event per delete."""
    holder = await _make_user(pg_session, "holder")
    live_entity = uuid.uuid4()
    dead_entities = [uuid.uuid4(), uuid.uuid4()]
    service = CollabLockService(pg_session)

    await service.acquire(entity_type=ENTITY_TYPE, entity_id=live_entity, user_id=holder.id, ttl_seconds=600)
    dead_ids = [(await _seed_expired_lock(pg_session, entity_id=eid, user_id=holder.id)).id for eid in dead_entities]

    removed = await service.sweep_expired()
    await asyncio.sleep(0)

    assert removed == 2, "only the two expired rows may be removed"
    assert await _count_rows(pg_session, live_entity) == 1, "a live lock must survive the sweep"
    for eid in dead_entities:
        assert await _count_rows(pg_session, eid) == 0

    # One event per removed lock, carrying the id that was actually deleted.
    announced = [lid for eid in dead_entities for lid in recorder.lock_ids_for(eid)]
    assert sorted(announced) == sorted(str(i) for i in dead_ids)
    assert recorder.lock_ids_for(live_entity) == [], "a surviving lock must not be announced as expired"


# ── Heartbeat: holder-only, and measured from now ──────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_extends_from_now_not_from_the_previous_expiry(pg_session) -> None:
    """A renew sets ``expires_at = now + extend_seconds``, it does not stack onto the old TTL."""
    holder = await _make_user(pg_session, "holder")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)

    granted = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=600)
    before = _now()
    renewed = await service.heartbeat(lock_id=granted.id, user_id=holder.id, extend_seconds=30)

    # The original lock had 600s left. Stacking (old + 30) would push the expiry
    # further out; measuring from now must pull it much closer in.
    assert renewed.expires_at < granted.expires_at, "extend must be measured from now, not added to the old expiry"
    assert before + timedelta(seconds=25) <= renewed.expires_at <= _now() + timedelta(seconds=31)
    assert renewed.id == granted.id


@pytest.mark.asyncio
async def test_heartbeat_from_a_non_holder_is_refused_and_changes_nothing(pg_session) -> None:
    """Someone else's renew must neither succeed nor move the holder's expiry."""
    holder = await _make_user(pg_session, "holder")
    rival = await _make_user(pg_session, "rival")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)

    granted = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=60)
    original_expiry = granted.expires_at

    with pytest.raises(NotLockHolderError):
        await service.heartbeat(lock_id=granted.id, user_id=rival.id, extend_seconds=600)

    snapshot = await _lock_snapshot(pg_session, entity_id)
    assert snapshot is not None
    assert snapshot.user_id == holder.id, "a rejected heartbeat must not transfer ownership"
    assert snapshot.expires_at == original_expiry, "a rejected heartbeat must not extend the lock"


@pytest.mark.asyncio
async def test_heartbeat_on_a_lock_the_sweeper_already_removed_is_refused(committed_locks) -> None:
    """A renew that races the sweeper is refused, not crashed.

    Same shape of race as the acquire tests, on the endpoint every open tab
    calls every few seconds: the row is read while it is still live, the
    sweeper removes it the moment it expires, and only then does the renew
    write. The session's identity map makes this easy to hit for real - the
    router looks the lock up for its tenant check before the service asks for
    it again, so the second lookup answers from memory without touching SQL.

    ``NotLockHolderError`` is the right answer because it is the one the tab
    can act on: the router renders it as a 404, and the client re-acquires.
    """
    holder = (await committed_locks.seed_users(1))[0]
    entity_id = uuid.uuid4()

    async with committed_locks.session() as holder_session:
        service = CollabLockService(holder_session)
        granted = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder, ttl_seconds=60)
        await holder_session.commit()

        # The lock is read while it is still live - this is what the router's
        # own tenant check does, and it leaves the row cached in this session.
        cached = await service.repo.get_by_id(granted.id)
        assert cached is not None

        async with committed_locks.session() as sweeper_session:
            swept = await sweeper_session.execute(delete(CollabLock).where(CollabLock.id == granted.id))
            assert swept.rowcount == 1, "the sweeper must actually remove the row"
            await sweeper_session.commit()

        with pytest.raises(NotLockHolderError):
            await service.heartbeat(lock_id=granted.id, user_id=holder, extend_seconds=60)

        assert await _count_rows(holder_session, entity_id) == 0, "a refused heartbeat must not resurrect the lock"


@pytest.mark.asyncio
async def test_heartbeat_on_an_expired_lock_is_refused(pg_session) -> None:
    """Past expiry the holder must re-acquire; renewing a dead lock would resurrect it."""
    holder = await _make_user(pg_session, "holder")
    entity_id = uuid.uuid4()
    stale = await _seed_expired_lock(pg_session, entity_id=entity_id, user_id=holder.id)
    service = CollabLockService(pg_session)

    with pytest.raises(NotLockHolderError):
        await service.heartbeat(lock_id=stale.id, user_id=holder.id, extend_seconds=60)

    snapshot = await _lock_snapshot(pg_session, entity_id)
    assert snapshot is not None
    assert snapshot.expires_at <= _now(), "the refused heartbeat must leave the lock expired"


# ── Release: holder-only ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_releasing_a_lock_you_do_not_hold_is_refused_and_the_lock_survives(pg_session) -> None:
    """Release is the dangerous verb: a non-holder must not be able to free the entity."""
    holder = await _make_user(pg_session, "holder")
    rival = await _make_user(pg_session, "rival")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)

    granted = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=60)

    with pytest.raises(NotLockHolderError):
        await service.release(lock_id=granted.id, user_id=rival.id)

    snapshot = await _lock_snapshot(pg_session, entity_id)
    assert snapshot is not None, "the lock must still exist after a refused release"
    assert snapshot.user_id == holder.id


@pytest.mark.asyncio
async def test_the_holder_can_release_and_the_row_is_gone(pg_session) -> None:
    """A released entity is immediately free for the next person."""
    holder = await _make_user(pg_session, "holder")
    other = await _make_user(pg_session, "other")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)

    granted = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=60)
    await service.release(lock_id=granted.id, user_id=holder.id)

    assert await _lock_snapshot(pg_session, entity_id) is None, "release must delete the row, not just expire it"

    # The freed entity must be immediately claimable by someone else.
    taken = await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=other.id, ttl_seconds=60)
    assert taken.user_id == other.id


@pytest.mark.parametrize("recorder", [COLLAB_LOCK_RELEASED], indirect=True)
@pytest.mark.asyncio
async def test_releasing_an_unknown_lock_is_a_silent_no_op(pg_session, recorder) -> None:
    """Idempotent release: no error, and crucially no phantom ``released`` broadcast."""
    holder = await _make_user(pg_session, "holder")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)
    await service.acquire(entity_type=ENTITY_TYPE, entity_id=entity_id, user_id=holder.id, ttl_seconds=60)

    await service.release(lock_id=uuid.uuid4(), user_id=holder.id)
    await asyncio.sleep(0)

    assert recorder.lock_ids_for(entity_id) == [], "nothing was released, so nothing may be announced"
    assert await _count_rows(pg_session, entity_id) == 1, "an unrelated lock must be untouched"


# ── Allowlist ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_entity_type_off_the_allowlist_cannot_be_locked_or_read(pg_session) -> None:
    """The allowlist is what stops the lock table accumulating orphan references."""
    holder = await _make_user(pg_session, "holder")
    entity_id = uuid.uuid4()
    service = CollabLockService(pg_session)

    with pytest.raises(UnknownEntityTypeError):
        await service.acquire(entity_type="wallet", entity_id=entity_id, user_id=holder.id, ttl_seconds=60)
    with pytest.raises(UnknownEntityTypeError):
        await service.get_for_entity(entity_type="wallet", entity_id=entity_id)

    session_rows = await pg_session.execute(select(CollabLock.id).where(CollabLock.entity_type == "wallet"))
    assert list(session_rows.scalars().all()) == [], "a rejected type must never reach the table"
