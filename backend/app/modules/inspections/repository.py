"""‌⁠‍Inspections data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inspections.models import QualityInspection

# How many times a colliding number is re-derived before giving up. A handful
# of concurrent writers only ever need one or two retries; the cap stops a
# pathological hot loop.
_NUMBER_RETRY_LIMIT = 5


def _next_suffix(numbers: list[str]) -> int:
    """Return MAX(trailing integer) + 1 over a list of ``PREFIX-NNN`` codes.

    Robust to deletions (the highest issued suffix is never reused) and to
    rows whose number doesn't match the expected ``PREFIX-<int>`` shape
    (those are simply ignored). Returns 1 when nothing parseable exists.
    """
    highest = 0
    for number in numbers:
        if not number:
            continue
        suffix = number.rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


class InspectionRepository:
    """‌⁠‍Data access for QualityInspection models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, inspection_id: uuid.UUID) -> QualityInspection | None:
        """‌⁠‍Get inspection by ID."""
        return await self.session.get(QualityInspection, inspection_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        inspection_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[QualityInspection], int]:
        """List inspections for a project with pagination and filters."""
        base = select(QualityInspection).where(QualityInspection.project_id == project_id)
        if inspection_type is not None:
            base = base.where(QualityInspection.inspection_type == inspection_type)
        if status is not None:
            base = base.where(QualityInspection.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(QualityInspection.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def next_inspection_number(self, project_id: uuid.UUID) -> str:
        """Generate the next inspection number (INS-001, INS-002, ...).

        Derived from MAX(numeric suffix)+1 rather than COUNT(*)+1: a COUNT
        drops after any delete, so the next create would re-issue an already
        used INS- number, and a failed insert never moves the count so a retry
        could not advance. Scanning the existing numbers and taking the highest
        suffix keeps the sequence monotonic and lets a collision retry progress.
        """
        stmt = select(QualityInspection.inspection_number).where(QualityInspection.project_id == project_id)
        numbers = (await self.session.execute(stmt)).scalars().all()
        return f"INS-{_next_suffix(numbers):03d}"

    async def create(self, inspection: QualityInspection) -> QualityInspection:
        """Insert an inspection, deriving its number with a retry on collision.

        The number comes from MAX(suffix)+1, which can race two concurrent
        creates onto the same value. The per-project unique constraint turns
        that race into an IntegrityError; we roll back the failed insert, re-read
        the MAX and try again.
        """
        # Read project_id once: after a savepoint rollback the instance is
        # expired, so reading it inside the loop could trigger a lazy load.
        project_id = inspection.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            inspection.inspection_number = await self.next_inspection_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(inspection)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return inspection
        raise RuntimeError(f"Could not allocate a unique inspection number for project {project_id}")

    async def update_fields(self, inspection_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an inspection."""
        stmt = update(QualityInspection).where(QualityInspection.id == inspection_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, inspection_id: uuid.UUID) -> None:
        """Hard delete an inspection."""
        inspection = await self.get_by_id(inspection_id)
        if inspection is not None:
            await self.session.delete(inspection)
            await self.session.flush()
