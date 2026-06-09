"""‌⁠‍NCR data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ncr.models import NCR

# How many times a colliding number is re-derived before giving up. A handful
# of concurrent writers only ever need one or two retries; the cap stops a
# pathological hot loop.
_NUMBER_RETRY_LIMIT = 5


class NCRRepository:
    """‌⁠‍Data access for NCR models."""

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
        """‌⁠‍Generate the next ``NCR-NNN`` number using MAX to avoid duplicates.

        Only rows whose number matches the canonical ``NCR-<digits>`` shape are
        considered. PostgreSQL casts an empty or non-numeric string to integer
        strictly (``invalid input syntax for type integer``), unlike SQLite
        which silently yielded 0, so the regex filter is required for
        correctness, not cosmetic: one legacy or externally-numbered row (e.g.
        ``"901"`` from a cross-module bridge) would otherwise raise on every new
        NCR for that project.
        """
        from sqlalchemy import Integer as SAInteger
        from sqlalchemy import cast
        from sqlalchemy.sql import func as sqlfunc

        stmt = (
            select(
                sqlfunc.coalesce(
                    sqlfunc.max(cast(func.substr(NCR.ncr_number, 5), SAInteger)),
                    0,
                )
            )
            .where(NCR.project_id == project_id)
            .where(NCR.ncr_number.regexp_match("^NCR-[0-9]+$"))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"NCR-{max_num + 1:03d}"

    async def create(self, ncr: NCR) -> NCR:
        """Insert an NCR, deriving its ``ncr_number`` with a retry on collision.

        The number comes from MAX(suffix)+1, which can race two concurrent
        creates onto the same value. The per-project unique constraint turns
        that race into an IntegrityError; we roll back the failed insert, re-read
        the MAX and try again.
        """
        # Read project_id once: after a savepoint rollback the instance is
        # expired, so reading it inside the loop could trigger a lazy load.
        project_id = ncr.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            ncr.ncr_number = await self.next_ncr_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(ncr)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return ncr
        raise RuntimeError(f"Could not allocate a unique NCR number for project {project_id}")

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
