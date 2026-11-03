# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A throwaway engine for the partner API tests, which need real commits across sessions.

Uses the suite's schema-loaded PostgreSQL clone. With ``OE_TEST_SQLITE=1`` it
builds just the named tables on in-memory SQLite instead (needs ``aiosqlite``),
for a machine that has no PostgreSQL.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Iterable

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.database import Base


@contextlib.asynccontextmanager
async def partner_engine(tables: Iterable[Table]) -> AsyncIterator[AsyncEngine]:
    if os.environ.get("OE_TEST_SQLITE") == "1":
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        wanted = list(tables)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=wanted))
        try:
            yield engine
        finally:
            await engine.dispose()
        return

    from tests._pg import isolated_engine

    async with isolated_engine() as engine:
        yield engine
