# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittals data access layer."""

import uuid

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.submittals.models import Submittal

# A project's register is read whole when a filter depends on today's date.
# The cap only keeps a runaway project from loading without bound.
MAX_REGISTER_ROWS = 50000


def register_filters(
    stmt: Select,
    *,
    status: str | None = None,
    submittal_type: str | None = None,
    discipline: str | None = None,
    review_outcome: str | None = None,
    review_code: str | None = None,
    long_lead: bool | None = None,
) -> Select:
    """Narrow a submittal query by the stored register columns.

    ``review_outcome`` also matches a row from before the outcome column
    existed whose status is itself that decision, so an old approved
    submittal is still found under "approved".
    """
    if status is not None:
        stmt = stmt.where(Submittal.status == status)
    if submittal_type is not None:
        stmt = stmt.where(Submittal.submittal_type == submittal_type)
    if discipline is not None:
        stmt = stmt.where(Submittal.discipline == discipline)
    if review_outcome is not None:
        stmt = stmt.where(
            or_(
                Submittal.review_outcome == review_outcome,
                and_(Submittal.review_outcome.is_(None), Submittal.status == review_outcome),
            )
        )
    if review_code is not None:
        stmt = stmt.where(Submittal.review_code == review_code)
    if long_lead is not None:
        stmt = stmt.where(Submittal.long_lead.is_(long_lead))
    return stmt


def register_order(stmt: Select, sort: str | None, descending: bool) -> Select:
    """Order a submittal query by one stored column, empty values last.

    An unknown ``sort`` falls back to newest first, which is what the list
    did before it could be sorted. The id is the tie-break so paging through
    equal values never repeats or drops a row.
    """
    column = getattr(Submittal, sort, None) if sort else None
    if column is None or sort in (None, "created_at"):
        ordering = Submittal.created_at.desc() if descending or sort is None else Submittal.created_at.asc()
        return stmt.order_by(ordering, Submittal.id)
    ordering = column.desc() if descending else column.asc()
    return stmt.order_by(ordering.nulls_last(), Submittal.id)


class SubmittalRepository:
    """Data access for Submittal models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, submittal_id: uuid.UUID) -> Submittal | None:
        return await self.session.get(Submittal, submittal_id)

    async def count_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        submittal_type: str | None = None,
    ) -> int:
        """Single-query count - used by list responses to avoid N+1."""
        base = (
            select(func.count())
            .select_from(Submittal)
            .where(
                Submittal.project_id == project_id,
            )
        )
        if status is not None:
            base = base.where(Submittal.status == status)
        if submittal_type is not None:
            base = base.where(Submittal.submittal_type == submittal_type)
        return (await self.session.execute(base)).scalar_one()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        submittal_type: str | None = None,
        discipline: str | None = None,
        review_outcome: str | None = None,
        review_code: str | None = None,
        long_lead: bool | None = None,
        sort: str | None = None,
        descending: bool = True,
    ) -> tuple[list[Submittal], int]:
        base = register_filters(
            select(Submittal).where(Submittal.project_id == project_id),
            status=status,
            submittal_type=submittal_type,
            discipline=discipline,
            review_outcome=review_outcome,
            review_code=review_code,
            long_lead=long_lead,
        )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = register_order(base, sort, descending).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def register_rows(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        submittal_type: str | None = None,
        discipline: str | None = None,
        review_outcome: str | None = None,
        review_code: str | None = None,
        long_lead: bool | None = None,
        sort: str | None = "submittal_number",
        descending: bool = False,
    ) -> list[Submittal]:
        """Every submittal of a project that passes the stored filters, unpaged.

        For the callers whose question depends on today's date (overdue for
        review, approval needed-by passed, the summary): those figures are
        worked out in Python from the stored dates, because the dates are
        strings and casting them in SQL fails on the first malformed one.
        """
        stmt = register_filters(
            select(Submittal).where(Submittal.project_id == project_id),
            status=status,
            submittal_type=submittal_type,
            discipline=discipline,
            review_outcome=review_outcome,
            review_code=review_code,
            long_lead=long_lead,
        )
        stmt = register_order(stmt, sort, descending).limit(MAX_REGISTER_ROWS)
        return list((await self.session.execute(stmt)).scalars().all())

    async def next_submittal_number(self, project_id: uuid.UUID) -> str:
        """Generate the next submittal number using MAX to avoid duplicates.

        Numbers are server-generated as ``SUB-%03d`` (the ``SUB-`` prefix is
        4 chars, so the numeric ordinal begins at index 4 of the string).

        Dialect-safety: the previous implementation pushed
        ``CAST(substr(number, 5) AS INTEGER)`` into SQL. That diverges by
        backend - SQLite is lenient (``CAST('001-A' AS INTEGER)`` -> 1), but
        embedded PostgreSQL raises ``invalid input syntax for type integer``
        and 500s the whole create path for any row whose suffix is not a clean
        integer (e.g. a legacy import / seed / migrated row like ``SUBM-1`` or
        ``SUB-001-R2``). We instead select the existing numbers for the project
        and compute the max ordinal in Python, parsing the trailing digits
        defensively and skipping anything non-numeric. This is identical on
        every backend and never feeds a non-numeric string to a SQL cast. The
        candidate set is scoped to a single project so the read stays small.
        """
        stmt = select(Submittal.submittal_number).where(Submittal.project_id == project_id)
        numbers = (await self.session.execute(stmt)).scalars().all()

        max_num = 0
        for number in numbers:
            if not number:
                continue
            # Take the trailing run of digits (handles ``SUB-007`` and tolerates
            # legacy variants like ``SUB-007-R2`` by reading the leading numeric
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

        return f"SUB-{max_num + 1:03d}"

    async def create(self, submittal: Submittal) -> Submittal:
        """Persist a new submittal.

        Raises :class:`sqlalchemy.exc.IntegrityError` on unique-constraint
        collision - the service layer retries with a fresh submittal
        number when this happens (concurrent create race).
        """
        self.session.add(submittal)
        try:
            await self.session.flush()
        except IntegrityError:
            # Rollback only the savepoint of this flush so the surrounding
            # transaction stays alive for the service-layer retry. The
            # caller decides whether to re-issue with a new number or to
            # surface the error as HTTP 409.
            await self.session.rollback()
            raise
        return submittal

    async def update_fields(self, submittal_id: uuid.UUID, **fields: object) -> None:
        stmt = update(Submittal).where(Submittal.id == submittal_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Targeted expire: only the row we just touched needs to be
        # re-read. ``session.expire_all()`` previously invalidated every
        # cached attribute on every loaded object (including unrelated
        # rows in long-lived sessions) which forced lazy reloads under
        # async context and risked MissingGreenlet downstream.
        sub = await self.session.get(Submittal, submittal_id)
        if sub is not None:
            self.session.expire(sub)

    async def delete(self, submittal_id: uuid.UUID) -> None:
        submittal = await self.get_by_id(submittal_id)
        if submittal is not None:
            await self.session.delete(submittal)
            await self.session.flush()
