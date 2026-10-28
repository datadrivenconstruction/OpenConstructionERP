"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: walking the progress register's pages returns every entry exactly once.

``ProgressRepository.list_entries_for_project`` pages with OFFSET/LIMIT and
used to order by ``recorded_at`` alone. That is not a total order over this
table: ``recorded_at`` defaults to the DB's ``now()``, which in PostgreSQL is
the TRANSACTION timestamp, so every entry a single write appends carries the
same value - and a bulk field import appends many. Under a partial order the
database may arrange the tied rows differently for each OFFSET it serves, so a
walk through the pages can hand back one entry twice and never return another,
with each page looking perfectly correct on its own.

The fix adds ``seq`` as a second key. It is NOT NULL and unique per INSERT
(see :func:`app.modules.progress.repository._latest_first` and migration
``v3258_progress_entry_seq``), so the order becomes total and the walk exact.

What each test here is worth, measured rather than assumed: the three page
walks all PASS against the unfixed query. ``ix_progress_entry_project_recorded``
covers ``(project_id, recorded_at)``, so PostgreSQL answers them from an index
scan whose tied rows come back in a stable physical order, and the wrong query
returns the right answer at fixture size. They are kept as documentation of
the contract, not as its guard.
:func:`test_the_page_order_ends_on_a_column_that_cannot_tie` is the guard: it
asserts the property OFFSET actually depends on, which is that the last
ordering key cannot tie, and it fails the moment ``seq`` leaves the tuple.

Real PostgreSQL because ``seq`` is a sequence-backed server default: on a
dialect without it the column these tests turn on does not populate at all.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.progress.models import ProgressEntry
from app.modules.progress.repository import ProgressRepository, _oldest_first
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

PERIOD = "2026-W21"


# ── Seeding ────────────────────────────────────────────────────────────────


async def _seed_project(session) -> Project:
    """Insert an owner and one project."""
    owner = User(email=f"walk-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Page walk project", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def _append_batch(session, project_id: uuid.UUID, recorded_at: datetime, count: int) -> list[ProgressEntry]:
    """Append ``count`` entries that all share one ``recorded_at``.

    This is what a bulk field import looks like: the timestamp is the same for
    every row, so the only thing separating them is the insertion counter.
    Flushed one at a time so the sequence hands out ``seq`` in call order, and
    refreshed because ``seq`` is a server default the INSERT does not return.
    """
    written: list[ProgressEntry] = []
    for i in range(count):
        entry = ProgressEntry(
            project_id=project_id,
            period_label=PERIOD,
            percent_complete=float(i % 100),
            recorded_at=recorded_at,
            notes=f"reading {i}",
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        written.append(entry)
    return written


async def _walk(session, project_id: uuid.UUID, *, page_size: int) -> list[uuid.UUID]:
    """Page through the whole register the way a client does, and concatenate."""
    repo = ProgressRepository(session)
    walked: list[uuid.UUID] = []
    offset = 0
    while True:
        rows = await repo.list_entries_for_project(project_id, offset=offset, limit=page_size)
        if not rows:
            return walked
        walked.extend(e.id for e in rows)
        offset += page_size


def _assert_ties_present(entries: list[ProgressEntry]) -> None:
    """Refuse to pass on a scenario that never exercises the tie-breaker.

    A walk test written without this is the easy mistake: give every row its
    own timestamp and the first key alone is already total, so the test reads
    identically before and after the fix and proves nothing.
    """
    stamps = {e.recorded_at for e in entries}
    assert len(stamps) < len(entries), "seeded rows must share a recorded_at, or the tie-breaker is never reached"


# ── The walk ───────────────────────────────────────────────────────────────


async def test_a_page_walk_over_tied_timestamps_returns_every_entry_once(pg_session) -> None:
    """Twenty-five entries on one timestamp, read five at a time, come back whole."""
    project = await _seed_project(pg_session)
    written = await _append_batch(pg_session, project.id, datetime.now(UTC), 25)
    _assert_ties_present(written)

    walked = await _walk(pg_session, project.id, page_size=5)

    assert len(walked) == len(set(walked)), "an entry was served on two pages"
    assert set(walked) == {e.id for e in written}, "an entry was never served on any page"
    assert walked == [e.id for e in written], "tied entries did not come back in insertion order"


async def test_the_page_size_does_not_change_which_entries_come_back(pg_session) -> None:
    """The same register read at three page sizes gives the same sequence.

    A partial order can be arranged differently for each OFFSET the planner
    serves, so disagreement between page sizes is the shape the duplicate-and-
    skip failure takes when it does surface.
    """
    project = await _seed_project(pg_session)
    written = await _append_batch(pg_session, project.id, datetime.now(UTC), 21)
    _assert_ties_present(written)

    expected = [e.id for e in written]
    for page_size in (1, 4, 20):
        assert await _walk(pg_session, project.id, page_size=page_size) == expected, (
            f"page size {page_size} produced a different register"
        )


async def test_the_page_order_ends_on_a_column_that_cannot_tie(pg_session) -> None:
    """The register's ORDER BY must be total, and this is what makes it so.

    The three walks above cannot prove that on their own, and it is worth
    saying why rather than leaving a reader to assume they do. Removing
    ``seq`` from :func:`_oldest_first` leaves all three of them passing:
    ``ix_progress_entry_project_recorded`` covers ``(project_id,
    recorded_at)``, so PostgreSQL answers those queries from an index scan
    that happens to walk tied rows in a stable physical order. The walks
    document the contract and would catch a gross regression; they do not
    catch the one this file was written for, because the wrong query returns
    the right answer on a table this size and this shape.

    What is actually being promised is a property of the statement: OFFSET is
    only meaningful against a total order, and an order is total when its last
    key cannot tie. So that is asserted directly - the final key must be a
    column the database has declared unique and NOT NULL. A planner that stops
    choosing the index, a table that outgrows it, or a filter that defeats it
    all turn the missing key from harmless into rows silently lost, and none
    of those show up in a fixture.
    """
    keys = _oldest_first()

    assert len(keys) >= 2, "a single-key order over a tied column is not total"
    # Identify the key by table and name rather than by object identity.
    # ``ProgressEntry.seq.asc()`` coerces the mapped attribute through
    # ``__clause_element__``, so ``.element`` is the annotated Column, never
    # the InstrumentedAttribute the model exposes and never the plain
    # ``__table__.c.seq`` either. An ``is`` comparison against any of the
    # three fails on a correct ORDER BY, which is what it did.
    last = keys[-1].element
    assert (last.table.name, last.key) == (ProgressEntry.__tablename__, "seq"), (
        f"the register's order must end on {ProgressEntry.__tablename__}.seq, not on {last}"
    )

    # Assert the property seq is relied on FOR, not merely its name: another
    # column could be substituted here and the order would still be total only
    # if that column carried the same guarantees.
    column = ProgressEntry.__table__.c[last.key]
    assert column.unique, "the final ordering key must be unique, or rows can still tie"
    assert not column.nullable, "a nullable final key ties across every NULL row"


async def test_the_order_survives_the_rows_moving_in_the_heap(pg_session) -> None:
    """Rewriting some rows must not reorder the register.

    PostgreSQL implements an UPDATE as a new tuple version, so touching half
    the rows can move them behind the untouched ones physically. This is the
    closest a fixture gets to disturbing the arrangement the tied rows come
    back in; it is kept because the register really is amended in the field,
    not because it is known to separate the two orderings (see the test
    above - on this table PostgreSQL keeps serving the index).
    """
    project = await _seed_project(pg_session)
    written = await _append_batch(pg_session, project.id, datetime.now(UTC), 12)
    _assert_ties_present(written)

    for entry in written[:6]:
        entry.notes = "amended"
    await pg_session.flush()

    walked = await _walk(pg_session, project.id, page_size=5)

    assert walked == [e.id for e in written]
    assert len(walked) == len(set(walked)), "an entry was served on two pages"


async def test_distinct_timestamps_still_lead_the_order(pg_session) -> None:
    """``seq`` breaks ties; it does not outrank the timestamp.

    If the keys were the other way round a back-dated correction would sort
    after the reading it corrects, so the register would stop being
    chronological - which is the thing it is read for.
    """
    project = await _seed_project(pg_session)
    base = datetime.now(UTC)

    # Written newest first, so insertion order and chronological order disagree.
    later = await _append_batch(pg_session, project.id, base, 3)
    earlier = await _append_batch(pg_session, project.id, base - timedelta(hours=1), 3)

    walked = await _walk(pg_session, project.id, page_size=2)

    assert walked == [e.id for e in earlier] + [e.id for e in later]
    assert all(e.seq > later[-1].seq for e in earlier), "the earlier batch must carry the HIGHER seq"
