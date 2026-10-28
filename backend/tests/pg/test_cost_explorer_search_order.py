"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost Explorer candidate pool ordering on real PostgreSQL (PG lane only).

``CostExplorerRepository.search_work`` fetches a pool of candidates and cuts it
with ``LIMIT``; the service then re-ranks only what survived. So the cut decides
what an estimator can see, and it has to be reproducible.

It was not. The pool was ordered by concept-match count alone, and for a
one-word query every row that got past the WHERE matches exactly one concept, so
the sort key was a constant. PostgreSQL is then free to return whichever rows the
plan produced, and the same search run twice returned different work items at
different rates - a rate nobody could cite, because nobody could find it again.

These tests assert an EXPLICIT expected sequence rather than running the query
twice and comparing. Two runs in one session share a plan and an identity map,
so they can agree while the order is still undefined; only naming the rows in
advance pins it down.

PostgreSQL because the whole-word synonym branch uses ``~*``, which SQLite has
no operator for.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

# A token that exists in no cost base and expands to no synonym, so these tests
# see only their own rows even if the lane ever seeds a catalogue.
MARKER = "zzqxmark"


async def _seed(pg_session, rows: list[tuple[str, str, str | None]]) -> None:
    """Insert cost items as ``(code, description, region)``."""
    from app.modules.costs.models import CostItem

    for code, description, region in rows:
        pg_session.add(
            CostItem(
                id=uuid.uuid4(),
                code=code,
                description=description,
                unit="m2",
                rate="100.00",
                currency="EUR",
                source="test",
                region=region,
                is_active=True,
            )
        )
    await pg_session.flush()


async def _codes(pg_session, tokens, *, region=None, limit=3) -> list[str]:
    from app.modules.cost_explorer.repository import CostExplorerRepository

    items, _suggestion = await CostExplorerRepository(pg_session).search_work(tokens, region, None, limit)
    return [item.code for item in items]


async def test_pool_cut_follows_the_declared_order_not_the_plan(pg_session) -> None:
    """The three rows that survive a limit of 3 are named in advance.

    Nine rows match, all with the same concept-match count, so the count cannot
    order them. The expected sequence contradicts both insertion order and code
    order on its own, which is what makes it worth asserting: shortest
    description first, ties broken by code.
    """
    await _seed(
        pg_session,
        [
            ("C-900", f"{MARKER}", "XX_ALPHA"),
            ("C-100", f"{MARKER} wall panel system extended", "XX_ALPHA"),
            ("C-500", f"{MARKER} slab", "XX_BETA"),
            ("C-050", f"{MARKER} slab", "XX_BETA"),
            ("C-800", f"{MARKER} beam and column assembly", "XX_ALPHA"),
            ("C-200", f"{MARKER} raft foundation to detail", "XX_BETA"),
            ("C-300", f"{MARKER} screed laid to falls here", "XX_ALPHA"),
            ("C-400", f"{MARKER} blinding under pad bases", "XX_BETA"),
            ("C-600", f"{MARKER} topping bonded to the deck", "XX_ALPHA"),
        ],
    )

    # C-900 is the shortest description. C-050 and C-500 tie on length, so the
    # code breaks it. Pure code order would have started C-050, C-100, C-500.
    assert await _codes(pg_session, [MARKER]) == ["C-900", "C-050", "C-500"]


async def test_the_typed_word_survives_the_cut_over_a_synonym(pg_session) -> None:
    """A row carrying the word the user typed outranks one carrying a synonym.

    The literal row is given the LONGEST description here on purpose. Length is
    the next term in the order, so if the literal preference were missing the
    short synonym rows would take the whole pool and the service would never see
    the row the estimator actually asked for.
    """
    await _seed(
        pg_session,
        [
            ("S-010", "reinforcement", "XX_SYN"),
            ("S-020", "reinforcement mesh", "XX_SYN"),
            ("S-030", "reinforcement steel bar", "XX_SYN"),
            ("S-040", "high yield rebar fixed in position to the deck slab", "XX_SYN"),
        ],
    )

    assert await _codes(pg_session, ["rebar"], region="XX_SYN", limit=1) == ["S-040"]


async def test_an_empty_query_is_ordered_too(pg_session) -> None:
    """A query with no usable tokens builds no predicates and so had no ORDER BY.

    That path cut an unordered result set with the same LIMIT, so browsing a
    region returned an arbitrary handful. It is ordered by the same terminal key
    as every other path now.
    """
    await _seed(
        pg_session,
        [
            # Equal-length descriptions, so the code is what orders them.
            ("E-300", "ccc", "XX_EMPTY"),
            ("E-100", "aaa", "XX_EMPTY"),
            ("E-200", "bbb", "XX_EMPTY"),
        ],
    )

    assert await _codes(pg_session, [], region="XX_EMPTY") == ["E-100", "E-200", "E-300"]
