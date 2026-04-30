"""Unit tests for the 4-level category-tree aggregation.

Covers:
    - The tree nests collection → department → section → subsection.
    - Counts roll up correctly (parent count = sum of children counts).
    - NULL / empty intermediate levels coalesce into ``__unspecified__``.
    - The region filter constrains the aggregation.
    - The cursor codec round-trips and rejects garbage gracefully.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Per-module DB isolation.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-tree-"))
_TMP_DB = _TMP_DIR / "tree.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from app.database import Base  # noqa: E402
from app.modules.costs.models import CostItem  # noqa: E402
from app.modules.costs.repository import CostItemRepository  # noqa: E402
from app.modules.costs.schemas import UNSPECIFIED_CATEGORY  # noqa: E402
from app.modules.costs.service import decode_cursor, encode_cursor  # noqa: E402


def _mk(
    code: str,
    *,
    collection: str | None,
    department: str | None,
    section: str | None,
    subsection: str | None,
    region: str = "DE_BERLIN",
) -> CostItem:
    cls: dict[str, str] = {}
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
        description="x",
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


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    db_path = _TMP_DIR / f"test-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[CostItem.__table__])

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        # 5 fully-qualified rows + 3 sentinel rows.
        s.add_all(
            [
                _mk("A1", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced"),
                _mk("A2", collection="Buildings", department="Concrete", section="Walls", subsection="Reinforced"),
                _mk("A3", collection="Buildings", department="Concrete", section="Walls", subsection="Plain"),
                _mk("A4", collection="Buildings", department="Masonry", section="Walls", subsection="Brick"),
                _mk("A5", collection="Roads", department="Asphalt", section="Surface", subsection="Hot"),
                # NULL department → "__unspecified__" at depth 2.
                _mk("Z1", collection="Buildings", department=None, section="Walls", subsection="Reinforced"),
                # Empty-string section → also coalesces.
                _mk("Z2", collection="Buildings", department="Concrete", section="", subsection="Plain"),
                # Different region → must not show up when region filter set.
                _mk("U1", collection="Buildings", department="Concrete", section="Walls", subsection="Plain", region="GB_LONDON"),
            ]
        )
        await s.commit()
        yield s

    await engine.dispose()


# ── Tree shape ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tree_nests_four_levels(session: AsyncSession) -> None:
    repo = CostItemRepository(session)
    tree = await repo.category_tree(region="DE_BERLIN")

    # Top-level: Buildings + Roads
    names = {n["name"] for n in tree}
    assert names == {"Buildings", "Roads"}

    buildings = next(n for n in tree if n["name"] == "Buildings")
    # 5 named-DE_BERLIN Buildings rows (A1-A4) + Z1 + Z2 = 6 total under Buildings.
    assert buildings["count"] == 6

    # Department-level under Buildings: Concrete, Masonry, __unspecified__ (Z1).
    dept_names = {n["name"] for n in buildings["children"]}
    assert dept_names == {"Concrete", "Masonry", UNSPECIFIED_CATEGORY}

    # Section-level under Buildings/Concrete: Walls + __unspecified__ (Z2).
    concrete = next(n for n in buildings["children"] if n["name"] == "Concrete")
    section_names = {n["name"] for n in concrete["children"]}
    assert section_names == {"Walls", UNSPECIFIED_CATEGORY}


@pytest.mark.asyncio
async def test_tree_count_rollup(session: AsyncSession) -> None:
    """Each parent count must equal the sum of child counts."""
    repo = CostItemRepository(session)
    tree = await repo.category_tree(region="DE_BERLIN")

    def _walk(node: dict) -> None:
        if node["children"]:
            child_sum = sum(c["count"] for c in node["children"])
            assert node["count"] == child_sum, (
                f"rollup broken at {node['name']}: count={node['count']} "
                f"!= sum(children)={child_sum}"
            )
            for c in node["children"]:
                _walk(c)

    for root in tree:
        _walk(root)


@pytest.mark.asyncio
async def test_tree_region_filter(session: AsyncSession) -> None:
    repo = CostItemRepository(session)
    de = await repo.category_tree(region="DE_BERLIN")
    gb = await repo.category_tree(region="GB_LONDON")

    de_total = sum(n["count"] for n in de)
    gb_total = sum(n["count"] for n in gb)
    assert de_total == 7
    assert gb_total == 1


@pytest.mark.asyncio
async def test_tree_no_region_aggregates_all(session: AsyncSession) -> None:
    repo = CostItemRepository(session)
    full = await repo.category_tree(region=None)
    assert sum(n["count"] for n in full) == 8


@pytest.mark.asyncio
async def test_tree_unspecified_sorts_last(session: AsyncSession) -> None:
    """The sentinel must sort after every real label at the same level."""
    repo = CostItemRepository(session)
    tree = await repo.category_tree(region="DE_BERLIN")
    buildings = next(n for n in tree if n["name"] == "Buildings")
    dept_order = [n["name"] for n in buildings["children"]]
    # __unspecified__ must come after the real names.
    assert dept_order[-1] == UNSPECIFIED_CATEGORY


# ── Cursor codec ──────────────────────────────────────────────────────────


def test_cursor_round_trip() -> None:
    encoded = encode_cursor("CWICR-1234", "abcd-1234")
    assert decode_cursor(encoded) == ("CWICR-1234", "abcd-1234")


def test_cursor_decodes_with_or_without_padding() -> None:
    # Encoder emits with padding; manually strip it to mimic a cursor that
    # round-tripped through a URL-safe path that ate the trailing "=".
    full = encode_cursor("X", "Y")
    stripped = full.rstrip("=")
    assert decode_cursor(stripped) == ("X", "Y")


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "not-base64!!!",
        "Zm9vYmFy",  # base64 of "foobar" — valid base64, not JSON
        "eyJjb2RlIjogMX0=",  # JSON {"code": 1} — code is int, not str
        "eyJjb2RlIjoiQSJ9",  # JSON {"code":"A"} — missing id
    ],
)
def test_cursor_decode_returns_none_on_garbage(garbage: str) -> None:
    assert decode_cursor(garbage) is None
