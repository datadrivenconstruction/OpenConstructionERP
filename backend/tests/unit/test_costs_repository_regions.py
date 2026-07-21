# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the multibase ``regions`` filter on the cost repository.

The v3-P8 multibase wave adds a repeated ``regions`` filter to
:meth:`CostItemRepository.search` so a project scoped to several loaded
catalogues (DE_BERLIN + CH_ZURICH) can browse the union in one query. The
precedence rule is ``regions`` (plural union) wins over ``region``
(singular), which wins over "no filter" (every region).

These tests run against a throwaway PostgreSQL database (cloned from the
schema-loaded template by :func:`tests._pg.isolated_engine`) so the SQL is
exercised for real, not mocked. The HTTP surface of the same filter is
covered by ``tests/integration/test_costs_regions_filter.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests._pg import isolated_engine

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_session() -> AsyncGenerator[AsyncSession, None]:
    """A session pre-seeded with cost items across three regions.

    DE_BERLIN: D1, D2, D3   CH_ZURICH: C1, C2   GB_LONDON: G1
    """
    from app.modules.costs.models import CostItem

    def _row(code: str, region: str) -> CostItem:
        return CostItem(
            id=uuid.uuid4(),
            code=code,
            description=f"desc {code}",
            unit="m3",
            rate="100.00",
            currency="EUR",
            source="cwicr",
            classification={"collection": "Buildings"},
            components=[],
            tags=[],
            region=region,
            is_active=True,
            metadata_={},
        )

    rows = [
        _row("D1", "DE_BERLIN"),
        _row("D2", "DE_BERLIN"),
        _row("D3", "DE_BERLIN"),
        _row("C1", "CH_ZURICH"),
        _row("C2", "CH_ZURICH"),
        _row("G1", "GB_LONDON"),
    ]

    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            session.add_all(rows)
            await session.commit()
            yield session


def _codes(items: list) -> set[str]:
    return {i.code for i in items}


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regions_union_returns_both_catalogues(seeded_session: AsyncSession) -> None:
    """``regions=[DE_BERLIN, CH_ZURICH]`` returns the union of both, and
    nothing from the un-scoped GB_LONDON catalogue."""
    from app.modules.costs.repository import CostItemRepository

    repo = CostItemRepository(seeded_session)
    items, total, _ = await repo.search(regions=["DE_BERLIN", "CH_ZURICH"], limit=100)

    assert _codes(items) == {"D1", "D2", "D3", "C1", "C2"}
    assert total == 5
    assert "G1" not in _codes(items)


@pytest.mark.asyncio
async def test_regions_single_element_scopes_to_that_catalogue(seeded_session: AsyncSession) -> None:
    """A one-element ``regions`` list behaves like the singular filter."""
    from app.modules.costs.repository import CostItemRepository

    repo = CostItemRepository(seeded_session)
    items, total, _ = await repo.search(regions=["CH_ZURICH"], limit=100)

    assert _codes(items) == {"C1", "C2"}
    assert total == 2


@pytest.mark.asyncio
async def test_regions_plural_takes_precedence_over_region_singular(
    seeded_session: AsyncSession,
) -> None:
    """Precedence: ``regions`` (plural) wins over ``region`` (singular).

    When both are supplied the union from ``regions`` is authoritative and
    the singular ``region`` is ignored - never AND-combined into an empty
    intersection."""
    from app.modules.costs.repository import CostItemRepository

    repo = CostItemRepository(seeded_session)
    items, total, _ = await repo.search(
        regions=["DE_BERLIN"],
        region="GB_LONDON",
        limit=100,
    )

    assert _codes(items) == {"D1", "D2", "D3"}
    assert total == 3


@pytest.mark.asyncio
async def test_no_region_filter_returns_every_region(seeded_session: AsyncSession) -> None:
    """Neither ``regions`` nor ``region`` set => the whole catalogue."""
    from app.modules.costs.repository import CostItemRepository

    repo = CostItemRepository(seeded_session)
    items, total, _ = await repo.search(limit=100)

    assert _codes(items) == {"D1", "D2", "D3", "C1", "C2", "G1"}
    assert total == 6


@pytest.mark.asyncio
async def test_duplicate_region_ids_collapse(seeded_session: AsyncSession) -> None:
    """A ``regions`` list with a repeated id must not double-count - the
    IN-filter is set-like, so the result equals the de-duplicated scope."""
    from app.modules.costs.repository import CostItemRepository

    repo = CostItemRepository(seeded_session)
    items, total, _ = await repo.search(regions=["DE_BERLIN", "DE_BERLIN"], limit=100)

    assert _codes(items) == {"D1", "D2", "D3"}
    assert total == 3


@pytest.mark.asyncio
async def test_sequential_region_queries_are_isolated(seeded_session: AsyncSession) -> None:
    """Two back-to-back queries with different scopes must each return their
    own rows - no state bleeds from the first query into the second."""
    from app.modules.costs.repository import CostItemRepository

    repo = CostItemRepository(seeded_session)

    de_items, _, _ = await repo.search(regions=["DE_BERLIN"], limit=100)
    ch_items, _, _ = await repo.search(regions=["CH_ZURICH"], limit=100)

    assert _codes(de_items) == {"D1", "D2", "D3"}
    assert _codes(ch_items) == {"C1", "C2"}
    assert _codes(de_items).isdisjoint(_codes(ch_items))
