"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for labor rate tests.

The top-level ``tests/conftest.py`` binds the engine to the PostgreSQL it
provisions but only eagerly registers a handful of model modules, so the labor
rate tables are not on the bound database until something asks for them. The
module tests that need a real database boot the whole app for this; these tests
only exercise a seeder, so the three tables are created directly instead. None
of them carries a foreign key outside the module, so they stand alone.
"""

from __future__ import annotations

import pytest_asyncio

_TABLES = (
    "oe_labor_rates_template",
    "oe_labor_rates_oncost",
    "oe_labor_rates_crew_member",
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _labor_rate_tables():
    """Create the labor rate tables on the engine the conftest bound."""
    import app.modules.labor_rates.models  # noqa: F401  registers the tables on Base.metadata
    from app.database import Base, engine

    tables = [Base.metadata.tables[name] for name in _TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    yield
