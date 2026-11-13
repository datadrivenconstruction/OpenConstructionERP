"""Give projects that have a region but no country the country the region names."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update

from app.modules.projects.models import Project
from app.modules.projects.service import country_from_region

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def backfill_country_from_region(session: AsyncSession) -> int:
    """Set ``country_code`` on projects whose region names exactly one country.

    Only rows with a NULL or empty country are touched, so a second pass finds
    nothing and a country somebody chose is never overwritten.

    Args:
        session: An open session. The caller commits.

    Returns:
        Number of projects updated.
    """
    rows = (
        await session.execute(
            select(Project.id, Project.region).where(
                or_(Project.country_code.is_(None), Project.country_code == ""),
                Project.region != "",
            )
        )
    ).all()
    changed = 0
    for project_id, region in rows:
        country = country_from_region(region)
        if not country:
            continue
        result = await session.execute(
            update(Project)
            .where(
                Project.id == project_id,
                or_(Project.country_code.is_(None), Project.country_code == ""),
            )
            .values(country_code=country)
        )
        changed += result.rowcount or 0
    return changed
