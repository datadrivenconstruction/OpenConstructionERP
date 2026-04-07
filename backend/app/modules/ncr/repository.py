"""NCR data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ncr.models import NCR


class NCRRepository:
    """Data access for NCR models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, ncr_id: uuid.UUID) -> NCR | None:
        return await self.session.get(NCR, ncr_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        ncr_type: str | None = None,
        status: str | None = None,
        severity: str | None = None,
    ) -> tuple[list[NCR], int]:
        base = select(NCR).where(NCR.project_id == project_id)
        if ncr_type is not None:
            base = base.where(NCR.ncr_type == ncr_type)
        if status is not None:
            base = base.where(NCR.status == status)
        if severity is not None:
            base = base.where(NCR.severity == severity)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(NCR.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def next_ncr_number(self, project_id: uuid.UUID) -> str:
        """Generate the next NCR number using MAX to avoid duplicates."""
        from sqlalchemy import Integer as SAInteger
        from sqlalchemy import cast
        from sqlalchemy.sql import func as sqlfunc

        stmt = (
            select(
                sqlfunc.coalesce(
                    sqlfunc.max(
                        cast(
                            func.substr(NCR.ncr_number, 5),
                            SAInteger,
                        )
                    ),
                    0,
                )
            )
            .where(NCR.project_id == project_id)
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"NCR-{max_num + 1:03d}"

    async def create(self, ncr: NCR) -> NCR:
        self.session.add(ncr)
        await self.session.flush()
        return ncr

    async def update_fields(self, ncr_id: uuid.UUID, **fields: object) -> None:
        stmt = update(NCR).where(NCR.id == ncr_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, ncr_id: uuid.UUID) -> None:
        ncr = await self.get_by_id(ncr_id)
        if ncr is not None:
            await self.session.delete(ncr)
            await self.session.flush()
