# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The relevance search puts the hazard flag first in its ordering.

The relevance branch runs only on PostgreSQL with pg_trgm, which the embedded
test cluster does not ship, so the PG test of the ranking skips there. This
test covers the wiring instead: it captures the statement the repository
builds and reads its ORDER BY.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.costs.repository import CostItemRepository


class _Result:
    def scalar_one(self) -> int:
        return 0

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return []


class _Session:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result()


async def _order_by_of(q: str, monkeypatch: pytest.MonkeyPatch) -> str:
    session = _Session()
    repo = CostItemRepository(session)  # type: ignore[arg-type]

    async def _enabled(self: CostItemRepository, q: str | None, fuzzy: bool) -> bool:
        return True

    monkeypatch.setattr(CostItemRepository, "fuzzy_search_enabled", _enabled)
    await repo.search(q=q, skip_count=True)
    sql = str(session.statements[-1].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    return sql.split("ORDER BY", 1)[1]


@pytest.mark.asyncio
async def test_an_ordinary_search_ranks_hazardous_items_last(monkeypatch: pytest.MonkeyPatch) -> None:
    order_by = await _order_by_of("frame walls", monkeypatch)
    assert order_by.lstrip().startswith("CASE WHEN")
    assert "chrysotile" in order_by.split(" END", 1)[0]


@pytest.mark.asyncio
async def test_a_search_for_the_hazard_is_not_reordered(monkeypatch: pytest.MonkeyPatch) -> None:
    order_by = await _order_by_of("asbestos sheets", monkeypatch)
    assert "chrysotile" not in order_by
