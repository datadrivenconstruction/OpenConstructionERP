"""RFI data access layer."""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rfi.models import RFI


class RFIRepository:
    """Data access for RFI models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, rfi_id: uuid.UUID) -> RFI | None:
        return await self.session.get(RFI, rfi_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[RFI], int]:
        base = select(RFI).where(RFI.project_id == project_id)
        if status is not None:
            base = base.where(RFI.status == status)

        if search and search.strip():
            pattern = f"%{search.strip()}%"
            base = base.where(
                or_(
                    RFI.subject.ilike(pattern),
                    RFI.question.ilike(pattern),
                    RFI.official_response.ilike(pattern),
                    RFI.rfi_number.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(RFI.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def next_rfi_number(self, project_id: uuid.UUID) -> str:
        """Generate the next RFI number using MAX to avoid duplicates under concurrency."""
        from sqlalchemy import Integer as SAInteger
        from sqlalchemy import cast
        from sqlalchemy.sql import func as sqlfunc

        # Extract numeric suffix from existing RFI numbers (e.g. 'RFI-007' -> 7)
        stmt = (
            select(
                sqlfunc.coalesce(
                    sqlfunc.max(
                        cast(
                            func.substr(RFI.rfi_number, 5),
                            SAInteger,
                        )
                    ),
                    0,
                )
            )
            .where(RFI.project_id == project_id)
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"RFI-{max_num + 1:03d}"

    async def create(self, rfi: RFI) -> RFI:
        self.session.add(rfi)
        await self.session.flush()
        return rfi

    async def update_fields(self, rfi_id: uuid.UUID, **fields: object) -> None:
        stmt = update(RFI).where(RFI.id == rfi_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, rfi_id: uuid.UUID) -> None:
        rfi = await self.get_by_id(rfi_id)
        if rfi is not None:
            await self.session.delete(rfi)
            await self.session.flush()
