"""Unit tests for SQL ILIKE substring search on CostItemRepository.

Pins the BUG-012 / IMP-016 contract: ``q``, ``name`` and ``description``
filters must always evaluate as case-insensitive substring matches at
the SQL layer, regardless of whether LanceDB is installed.

The repository is the source of truth — the API boundary aliases
``search`` / ``query`` to ``q`` and forwards ``name`` / ``description``
through unchanged, so testing the repo directly is enough to assert
that "Beton" finds the seeded "Beton wall, 240mm" row.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Per-module DB isolation BEFORE any app imports ─────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-textsearch-"))
_TMP_DB = _TMP_DIR / "textsearch.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from app.database import Base  # noqa: E402
from app.modules.costs.models import CostItem  # noqa: E402
from app.modules.costs.repository import CostItemRepository  # noqa: E402


def _row(code: str, description: str) -> CostItem:
    return CostItem(
        id=uuid.uuid4(),
        code=code,
        description=description,
        unit="m2",
        rate="100.00",
        currency="EUR",
        source="cwicr",
        classification={},
        components=[],
        tags=[],
        region="DE_BERLIN",
        is_active=True,
        metadata_={},
    )


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    db_path = _TMP_DIR / f"test-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[CostItem.__table__])

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add_all(
            [
                _row("01.001", "Stahlbeton C30/37 Wand 240mm"),
                _row("01.002", "Beton C25/30 Decke 200mm"),
                _row("01.003", "Mauerwerk Kalksandstein"),
                _row("02.001", "Bewehrung BSt 500"),
                _row("02.002", "Schalung Wandschalung beton"),  # lowercase -> ILIKE
                _row("99.NOT", "Asphalt surface"),
            ]
        )
        await s.commit()
        yield s

    await engine.dispose()


# ── q (canonical free-text) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_q_finds_substring_in_description(session: AsyncSession) -> None:
    """BUG-012 root case — ``q=Beton`` must match every row containing 'beton'."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(q="Beton", limit=50)
    assert total is not None and total >= 3, "expected matches: Stahlbeton, Beton C25/30, Wandschalung beton"
    descriptions = [it.description.lower() for it in items]
    assert any("stahlbeton" in d for d in descriptions)
    assert any("beton c25/30" in d for d in descriptions)
    assert any("wandschalung beton" in d for d in descriptions), (
        "case-insensitive — lowercase 'beton' must still match 'Beton'"
    )


@pytest.mark.asyncio
async def test_q_matches_code_too(session: AsyncSession) -> None:
    """``q`` must OR across code AND description."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(q="01.001", limit=50)
    assert total == 1
    assert items[0].code == "01.001"


@pytest.mark.asyncio
async def test_q_empty_returns_all(session: AsyncSession) -> None:
    """No filter → no narrowing. Sanity check for the seed."""
    repo = CostItemRepository(session)
    _, total, _ = await repo.search(limit=100)
    assert total == 6


@pytest.mark.asyncio
async def test_q_with_no_matches(session: AsyncSession) -> None:
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(q="nonexistent-string-xyz", limit=50)
    assert total == 0
    assert items == []


# ── name (alias for code-only filter) ───────────────────────────────────


@pytest.mark.asyncio
async def test_name_filters_only_on_code(session: AsyncSession) -> None:
    """``name`` must match the code column, not description."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(name="01.", limit=50)
    assert total == 3
    assert {it.code for it in items} == {"01.001", "01.002", "01.003"}


@pytest.mark.asyncio
async def test_name_ignores_description(session: AsyncSession) -> None:
    """A token that lives only in description must not match via ``name``."""
    repo = CostItemRepository(session)
    _, total, _ = await repo.search(name="Stahlbeton", limit=50)
    assert total == 0, "Stahlbeton is in description, not in any code"


# ── description (description-only filter) ───────────────────────────────


@pytest.mark.asyncio
async def test_description_filters_only_on_description(session: AsyncSession) -> None:
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(description="Bewehrung", limit=50)
    assert total == 1
    assert items[0].code == "02.001"


@pytest.mark.asyncio
async def test_description_ignores_code(session: AsyncSession) -> None:
    repo = CostItemRepository(session)
    _, total, _ = await repo.search(description="01.001", limit=50)
    assert total == 0, "code values should not match the description filter"


# ── AND-combination ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_q_and_description_combine(session: AsyncSession) -> None:
    """``q`` (substring on code OR desc) AND ``description`` (desc only)
    must intersect, not OR."""
    repo = CostItemRepository(session)
    items, total, _ = await repo.search(q="01.", description="Beton", limit=50)
    # 01.001 (Stahlbeton) and 01.002 (Beton C25/30) — Mauerwerk is excluded.
    assert total == 2
    codes = {it.code for it in items}
    assert codes == {"01.001", "01.002"}
