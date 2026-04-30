"""Unit tests for keyset pagination + classification_path on CostItemRepository.

Covers:
    - First-page-then-cursor pagination yields every row exactly once.
    - ``has_more`` flips correctly at the boundary.
    - ``skip_count=True`` returns ``None`` for ``total``.
    - ``classification_path`` filters at all four depths.
    - Empty middle segments in the path act as wildcards.
    - Trailing/leading slashes are tolerated.

We use a real (file-backed) SQLite DB to exercise the json_extract path —
the dialect-aware ``_classification_expr`` is the riskiest part of the
patch, so an in-memory metadata.create_all + 20 fixture rows beats a
mock-heavy test for confidence per second of runtime.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Per-module DB isolation BEFORE any app imports ─────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-keyset-"))
_TMP_DB = _TMP_DIR / "keyset.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from app.database import Base  # noqa: E402
from app.modules.costs.models import CostItem  # noqa: E402
from app.modules.costs.repository import CostItemRepository  # noqa: E402


# ── Fixture catalog ────────────────────────────────────────────────────────
#
# 20 rows across two regions (DACH + UK) and a deliberately uneven
# classification tree so depth-by-depth filters have something to bite on.
#
#   collection / department / section      / subsection
#   Buildings / Concrete   / Walls         / Reinforced
#   Buildings / Concrete   / Walls         / Plain
#   Buildings / Concrete   / Floors        / Slab
#   Buildings / Masonry    / Walls         / Brick
#   Buildings / Masonry    / Walls         / Block
#   Roads     / Asphalt    / Surface       / Hot
#   Roads     / Asphalt    / Surface       / Cold
#   Roads     / Asphalt    / Subbase       / Crushed
#   Roads     / Concrete   / Surface       / CRCP
#   ...with one row per leaf, replicated across 2 regions, plus a few
#   "missing intermediate level" rows.
def _seed_rows() -> list[CostItem]:
    rows: list[CostItem] = []

    def _mk(
        code: str,
        *,
        collection: str | None,
        department: str | None,
        section: str | None,
        subsection: str | None,
        region: str,
    ) -> CostItem:
        cls = {}
        if collection is not None:
            cls["collection"] = collection
        if department is not None:
            cls["department"] = department
        if section is not None:
            cls["section"] = section
        if subsection is not None:
            cls["subsection"] = subsection
        return CostItem(
            id=uuid.uuid4(),
            code=code,
            description=f"desc {code}",
            unit="m2",
            rate="100.00",
            currency="EUR",
            source="cwicr",
            classification=cls,
            components=[],
            tags=[],
            region=region,
            is_active=True,
            metadata_={},
        )

    # DE_BERLIN — covers all four depths fully.
    rows.append(_mk("A001", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced", region="DE_BERLIN"))
    rows.append(_mk("A002", collection="Buildings", department="Concrete", section="Walls", subsection="Plain", region="DE_BERLIN"))
    rows.append(_mk("A003", collection="Buildings", department="Concrete", section="Floors", subsection="Slab", region="DE_BERLIN"))
    rows.append(_mk("A004", collection="Buildings", department="Masonry", section="Walls", subsection="Brick", region="DE_BERLIN"))
    rows.append(_mk("A005", collection="Buildings", department="Masonry", section="Walls", subsection="Block", region="DE_BERLIN"))
    rows.append(_mk("A006", collection="Roads", department="Asphalt", section="Surface", subsection="Hot", region="DE_BERLIN"))
    rows.append(_mk("A007", collection="Roads", department="Asphalt", section="Surface", subsection="Cold", region="DE_BERLIN"))
    rows.append(_mk("A008", collection="Roads", department="Asphalt", section="Subbase", subsection="Crushed", region="DE_BERLIN"))
    rows.append(_mk("A009", collection="Roads", department="Concrete", section="Surface", subsection="CRCP", region="DE_BERLIN"))

    # GB_LONDON — fewer rows, lets us pin region filter.
    rows.append(_mk("B001", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced", region="GB_LONDON"))
    rows.append(_mk("B002", collection="Buildings", department="Concrete", section="Floors", subsection="Slab", region="GB_LONDON"))
    rows.append(_mk("B003", collection="Roads", department="Asphalt", section="Surface", subsection="Hot", region="GB_LONDON"))

    # Rows with NULL intermediate levels — must coalesce into the sentinel
    # at category_tree, and must still match a wildcard middle segment in
    # classification_path.
    rows.append(_mk("Z001", collection="Buildings", department=None, section="Walls", subsection="Reinforced", region="DE_BERLIN"))
    rows.append(_mk("Z002", collection="Buildings", department="Concrete", section=None, subsection="Plain", region="DE_BERLIN"))
    rows.append(_mk("Z003", collection=None, department="Concrete", section="Walls", subsection="Reinforced", region="DE_BERLIN"))
    rows.append(_mk("Z004", collection="Buildings", department="Concrete", section="Walls", subsection=None, region="DE_BERLIN"))

    # Plus four extra Buildings rows so the total Buildings count is
    # large enough to verify pagination boundaries (limit=5 paged twice).
    rows.append(_mk("A010", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced", region="DE_BERLIN"))
    rows.append(_mk("A011", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced", region="DE_BERLIN"))
    rows.append(_mk("A012", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced", region="DE_BERLIN"))
    rows.append(_mk("A013", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced", region="DE_BERLIN"))

    return rows


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Fresh per-test SQLite DB seeded with 20 cost items."""
    db_path = _TMP_DIR / f"test-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[CostItem.__table__]
        )

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add_all(_seed_rows())
        await s.commit()
        yield s

    await engine.dispose()


# ── Pagination ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keyset_pagination_yields_all_rows_exactly_once(session: AsyncSession) -> None:
    """First page → next_cursor → ... → null cursor must cover every row."""
    repo = CostItemRepository(session)
    seen_codes: list[str] = []
    seen_ids: set[str] = set()
    cursor: tuple[str, str] | None = None
    total_first_page: int | None = None

    while True:
        items, total, has_more = await repo.search(
            limit=5,
            cursor=cursor,
            skip_count=cursor is not None,
        )
        if cursor is None:
            assert total is not None, "first page must return a total"
            total_first_page = total
        else:
            assert total is None, "subsequent pages must skip count"

        for it in items:
            assert str(it.id) not in seen_ids, f"row {it.code} returned twice"
            seen_ids.add(str(it.id))
            seen_codes.append(it.code)

        if not has_more or not items:
            break

        last = items[-1]
        cursor = (last.code, str(last.id))

    # Total seen must equal the first-page total.
    assert total_first_page == 20
    assert len(seen_codes) == 20
    # Order must be ascending by code (id tiebreaker is unobservable here
    # because we don't seed duplicate codes).
    assert seen_codes == sorted(seen_codes)


@pytest.mark.asyncio
async def test_has_more_flag_at_boundary(session: AsyncSession) -> None:
    """``has_more`` must be False on the final page only."""
    repo = CostItemRepository(session)
    # Page size that divides evenly: 20/4 = 5 → page 4 is the last.
    items_p1, _, has_more_p1 = await repo.search(limit=5)
    assert has_more_p1 is True
    assert len(items_p1) == 5

    # Walk to the end.
    cursor: tuple[str, str] = (items_p1[-1].code, str(items_p1[-1].id))
    for _ in range(2):
        page, _, more = await repo.search(limit=5, cursor=cursor, skip_count=True)
        assert more is True
        cursor = (page[-1].code, str(page[-1].id))

    # Last page.
    last_page, _, more_last = await repo.search(limit=5, cursor=cursor, skip_count=True)
    assert more_last is False
    assert len(last_page) == 5


@pytest.mark.asyncio
async def test_skip_count_returns_none(session: AsyncSession) -> None:
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(limit=3, cursor=None, skip_count=True)
    assert total is None
    assert len(items) == 3


# ── classification_path filter ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classification_path_depth_1(session: AsyncSession) -> None:
    """Filter at depth 1 (collection only) returns the whole branch (DE only)."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(
        classification_path="Buildings", region="DE_BERLIN", limit=100
    )
    # DE_BERLIN Buildings: A001-A005 (5) + A010-A013 (4) + Z001 + Z002 + Z004 = 12.
    # Z003 has collection=None so excluded.
    assert total == 12
    assert len(items) == 12
    for it in items:
        assert (it.classification or {}).get("collection") == "Buildings"


@pytest.mark.asyncio
async def test_classification_path_depth_2(session: AsyncSession) -> None:
    """Filter at depth 2 (collection/department)."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(
        classification_path="Buildings/Concrete", region="DE_BERLIN", limit=100
    )
    # DE_BERLIN Buildings + Concrete: A001, A002, A003, A010-A013, Z002, Z004 = 9.
    # Z001 has department=None → excluded. Z003 has collection=None → excluded.
    assert total == 9
    for it in items:
        cls = it.classification or {}
        assert cls.get("collection") == "Buildings"
        assert cls.get("department") == "Concrete"


@pytest.mark.asyncio
async def test_classification_path_depth_3(session: AsyncSession) -> None:
    """Filter at depth 3 (collection/department/section)."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(
        classification_path="Buildings/Concrete/Walls", region="DE_BERLIN", limit=100
    )
    # DE_BERLIN Buildings/Concrete/Walls: A001, A002, A010-A013 + Z004
    # (subsection=None still matches because depth-4 isn't constrained) = 7.
    # Z002 (section=None) excluded.
    assert total == 7


@pytest.mark.asyncio
async def test_classification_path_depth_4(session: AsyncSession) -> None:
    """Filter at depth 4 (full path) returns leaf rows only."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(
        classification_path="Buildings/Concrete/Walls/Reinforced",
        region="DE_BERLIN",
        limit=100,
    )
    # DE_BERLIN: A001, A010-A013 = 5
    assert total == 5
    for it in items:
        cls = it.classification or {}
        assert cls.get("subsection") == "Reinforced"


@pytest.mark.asyncio
async def test_classification_path_wildcard_middle_segment(session: AsyncSession) -> None:
    """Empty middle segment matches anything at that depth."""
    repo = CostItemRepository(session)
    # Buildings // Walls = any department, but section must be Walls
    items, total, _ = await repo.search(
        classification_path="Buildings//Walls", region="DE_BERLIN", limit=100
    )
    # DE_BERLIN Buildings, any department, section==Walls:
    # A001, A002, A004, A005, A010-A013, Z001 (dept=None passes wildcard),
    # Z004 (subsection=None still matches — only 3 depths constrained) = 10.
    # NOT Z002 (section=None), NOT Z003 (collection=None).
    assert total == 10


@pytest.mark.asyncio
async def test_classification_path_strips_slashes(session: AsyncSession) -> None:
    """Leading/trailing slashes must be tolerated."""
    repo = CostItemRepository(session)
    a, total_a, _ = await repo.search(
        classification_path="/Buildings/", region="DE_BERLIN", limit=100
    )
    b, total_b, _ = await repo.search(
        classification_path="Buildings", region="DE_BERLIN", limit=100
    )
    assert total_a == total_b
    assert {x.code for x in a} == {x.code for x in b}


@pytest.mark.asyncio
async def test_classification_path_combined_with_region(session: AsyncSession) -> None:
    """classification_path must AND-combine with the region filter."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(
        classification_path="Buildings", region="GB_LONDON", limit=100
    )
    # GB_LONDON Buildings rows: B001, B002 = 2.
    assert total == 2
    assert {x.code for x in items} == {"B001", "B002"}


@pytest.mark.asyncio
async def test_classification_path_empty_string_is_no_op(session: AsyncSession) -> None:
    """An empty classification_path must NOT filter anything out."""
    repo = CostItemRepository(session)
    items_a, total_a, _ = await repo.search(classification_path="", limit=100)
    items_b, total_b, _ = await repo.search(classification_path=None, limit=100)
    assert total_a == total_b == 20
    assert len(items_a) == len(items_b) == 20
