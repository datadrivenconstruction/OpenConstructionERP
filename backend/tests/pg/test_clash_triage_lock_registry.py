"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The per-subject triage lock registry must give its entries back.

``_subject_locks`` maps a clash id to an :class:`asyncio.Lock` so two callers
triaging the same clash in one process serialise and the second one hits the
cache instead of paying for another LLM call. The registry used to be
write-only: every subject ever triaged left an entry behind for the life of the
worker, which is a leak rather than a cache, because the entry is only useful
while somebody is actually inside it.

Nothing about this needs a database. It lives in the PG lane because that lane
is a merge gate and the default unit lane is only run by a job that is
chronically red for unrelated reasons, so a guard placed there is a guard
nobody reads.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest

from app.modules.clash_ai_triage import service as triage_service

SUBJECT = uuid.UUID("11111111-2222-3333-4444-555555555555")
OTHER_SUBJECT = uuid.UUID("66666666-7777-8888-9999-000000000000")


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Leave the module-level registry as it was found."""
    triage_service._subject_locks.clear()
    triage_service._subject_lock_users.clear()
    yield
    triage_service._subject_locks.clear()
    triage_service._subject_lock_users.clear()


@pytest.mark.asyncio
async def test_entry_is_released_after_a_single_use() -> None:
    """One caller in and out leaves nothing behind."""
    async with triage_service._subject_lock(SUBJECT):
        assert SUBJECT in triage_service._subject_locks

    assert triage_service._subject_locks == {}
    assert triage_service._subject_lock_users == {}


@pytest.mark.asyncio
async def test_entry_is_released_when_the_body_raises() -> None:
    """A failing triage must not strand its entry.

    The count is decremented in a ``finally``, so this is the test that pins
    it there rather than at the end of the happy path.
    """
    with pytest.raises(RuntimeError):
        async with triage_service._subject_lock(SUBJECT):
            raise RuntimeError("triage blew up")

    assert triage_service._subject_locks == {}
    assert triage_service._subject_lock_users == {}


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_lock_and_serialise() -> None:
    """Two callers on the same subject must not overlap.

    This is the behaviour the registry exists for, and it is what a naive
    "delete the entry on release" implementation breaks: the second caller
    would build a fresh lock and both would run at once.
    """
    seen: list[str] = []

    async def caller(tag: str) -> None:
        async with triage_service._subject_lock(SUBJECT):
            seen.append(f"{tag}:in")
            await asyncio.sleep(0.01)
            seen.append(f"{tag}:out")

    await asyncio.gather(caller("a"), caller("b"))

    # Whoever went first, the pairs must not interleave.
    assert seen[0].endswith(":in")
    assert seen[1] == seen[0].replace(":in", ":out")
    assert seen[2].endswith(":in")
    assert seen[3] == seen[2].replace(":in", ":out")
    assert triage_service._subject_locks == {}
    assert triage_service._subject_lock_users == {}


@pytest.mark.asyncio
async def test_a_caller_arriving_after_the_first_one_leaves_still_shares_the_lock() -> None:
    """Eviction must not hand a late caller a lock of its own.

    Two callers overlapping is not enough to prove this, because the second
    one looks the lock up before the first one releases and keeps its own
    reference to the object. The failure only appears with a third caller
    that arrives AFTER the first has released but while the second is still
    inside: a registry that drops the entry on every release gives that
    caller a brand new lock, and it runs straight through alongside the one
    already holding.
    """
    live = 0
    peak = 0

    async def caller(delay: float) -> None:
        nonlocal live, peak
        await asyncio.sleep(delay)
        async with triage_service._subject_lock(SUBJECT):
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    await asyncio.gather(*(caller(i * 0.01) for i in range(5)))

    assert peak == 1, f"{peak} callers were inside the subject at once"
    assert triage_service._subject_locks == {}
    assert triage_service._subject_lock_users == {}


@pytest.mark.asyncio
async def test_distinct_subjects_do_not_block_each_other() -> None:
    """Serialising is per subject, not global."""
    order: list[str] = []

    async def slow() -> None:
        async with triage_service._subject_lock(SUBJECT):
            await asyncio.sleep(0.05)
            order.append("slow")

    async def quick() -> None:
        await asyncio.sleep(0.01)
        async with triage_service._subject_lock(OTHER_SUBJECT):
            order.append("quick")

    await asyncio.gather(slow(), quick())

    assert order == ["quick", "slow"]
    assert triage_service._subject_locks == {}
