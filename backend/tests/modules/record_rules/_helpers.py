"""Helpers shared by the quality rule-set tests."""

from __future__ import annotations

import uuid


async def force_update(model, row_id: str, **values) -> None:
    """Write columns straight to the table: the way a record saved before the rules existed looks."""
    from sqlalchemy import update

    from app.database import async_session_factory

    async with async_session_factory() as session:
        await session.execute(update(model).where(model.id == uuid.UUID(row_id)).values(**values))
        await session.commit()
