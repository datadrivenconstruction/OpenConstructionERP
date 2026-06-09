"""‌⁠‍Correspondence data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence


class CorrespondenceRepository:
    """‌⁠‍Data access for Correspondence models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, correspondence_id: uuid.UUID) -> Correspondence | None:
        return await self.session.get(Correspondence, correspondence_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        direction: str | None = None,
        correspondence_type: str | None = None,
    ) -> tuple[list[Correspondence], int]:
        base = select(Correspondence).where(Correspondence.project_id == project_id)
        if direction is not None:
            base = base.where(Correspondence.direction == direction)
        if correspondence_type is not None:
            base = base.where(Correspondence.correspondence_type == correspondence_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Correspondence.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def next_reference_number(self, project_id: uuid.UUID) -> str:
        """‌⁠‍Generate the next reference number using MAX to avoid collisions after deletions.

        Numbers are server-generated as ``COR-%03d``. We select the existing
        numbers for the project and compute the max ordinal in Python rather
        than pushing ``MAX(reference_number)`` into SQL: the column is a string,
        so a SQL ``MAX`` sorts lexically and ``COR-1000`` sorts below
        ``COR-999`` once the suffix grows past three digits, which would pin the
        generator and emit a permanent duplicate stream. Parsing the trailing
        digits in Python keeps the ordinal monotonic and tolerates legacy /
        seed rows whose suffix is not a clean integer. The candidate set is
        scoped to a single project so the read stays small.
        """
        stmt = select(Correspondence.reference_number).where(Correspondence.project_id == project_id)
        numbers = (await self.session.execute(stmt)).scalars().all()

        max_num = 0
        for number in numbers:
            if not number:
                continue
            # Take the trailing run of digits (handles ``COR-007`` and tolerates
            # legacy variants like ``COR-007-A`` by reading the leading numeric
            # part of the suffix); ignore rows with no numeric ordinal at all.
            suffix = number.rsplit("-", 1)[-1]
            digits = ""
            for ch in suffix:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                max_num = max(max_num, int(digits))

        return f"COR-{max_num + 1:03d}"

    async def create(self, correspondence: Correspondence) -> Correspondence:
        """‌⁠‍Persist a new correspondence record.

        Raises :class:`sqlalchemy.exc.IntegrityError` on unique-constraint
        collision - the service layer retries with a fresh reference number
        when this happens (concurrent create race).
        """
        self.session.add(correspondence)
        try:
            await self.session.flush()
        except IntegrityError:
            # Roll back only this flush so the surrounding transaction stays
            # alive for the service-layer retry. The caller decides whether to
            # re-issue with a new number or to surface the error as HTTP 409.
            await self.session.rollback()
            raise
        return correspondence

    async def update_fields(self, correspondence_id: uuid.UUID, **fields: object) -> None:
        stmt = update(Correspondence).where(Correspondence.id == correspondence_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, correspondence_id: uuid.UUID) -> None:
        correspondence = await self.get_by_id(correspondence_id)
        if correspondence is not None:
            await self.session.delete(correspondence)
            await self.session.flush()
