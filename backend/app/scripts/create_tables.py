"""Create all database tables.

Usage: python -m app.scripts.create_tables

For development with SQLite — creates tables directly from models.
For production with PostgreSQL — use Alembic migrations instead.
"""

import asyncio

from app.database import Base, engine

# Import all models to register them with Base.metadata
from app.modules.users import models as _users_models  # noqa: F401


async def create_all() -> None:
    """Create all tables that don't exist yet."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_all())
