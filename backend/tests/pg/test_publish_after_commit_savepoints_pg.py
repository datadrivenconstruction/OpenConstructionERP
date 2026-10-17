# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``publish_after_commit`` over a real ``AsyncSession`` and real PostgreSQL SAVEPOINTs.

The unit file (tests/unit/test_publish_after_commit_savepoints.py) covers the
full matrix over SQLite through a synchronous session. This one repeats the
cases that matter on the production stack: asyncpg, ``AsyncSession`` and
``begin_nested()`` issuing real ``SAVEPOINT`` / ``ROLLBACK TO SAVEPOINT``.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events as events_mod
from app.core.events import publish_after_commit


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def _record(event_name: str, data: dict[str, Any] | None = None, *, source_module: str | None = None) -> None:
        seen.append(event_name)

    monkeypatch.setattr(events_mod.event_bus, "publish_detached", _record)
    return seen


async def test_rolled_back_savepoint_drops_its_event_on_pg(pg_engine, published):
    async with AsyncSession(pg_engine) as session:
        await session.execute(text("SELECT 1"))
        nested = await session.begin_nested()
        publish_after_commit(session, "pg.in_rolled_back_savepoint")
        await nested.rollback()
        publish_after_commit(session, "pg.outer")
        await session.commit()

    assert published == ["pg.outer"]


async def test_released_savepoint_keeps_its_event_until_the_outer_commit_on_pg(pg_engine, published):
    async with AsyncSession(pg_engine) as session:
        await session.execute(text("SELECT 1"))
        async with session.begin_nested():
            publish_after_commit(session, "pg.in_released_savepoint")
        assert published == []
        await session.commit()

    assert published == ["pg.in_released_savepoint"]


async def test_outer_rollback_drops_released_savepoint_events_on_pg(pg_engine, published):
    async with AsyncSession(pg_engine) as session:
        await session.execute(text("SELECT 1"))
        async with session.begin_nested():
            publish_after_commit(session, "pg.released")
        await session.rollback()

        await session.execute(text("SELECT 1"))
        await session.commit()

    assert published == []
