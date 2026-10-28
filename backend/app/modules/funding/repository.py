# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Public funding data access layer.

Two shapes of repository live here. ``ProgrammeRepository`` reads reference
data shared by every project. The other four read records that belong to one
application, and they are alike enough that they share a base class rather
than repeating the same six methods four times.

Every method that returns records belonging to an application takes the
application id, never an optional filter. A list endpoint whose scope is
optional eventually gets called without it, and in this module that would
hand one applicant another applicant's award.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funding.models import (
    FundingApplication,
    FundingCostAllocation,
    FundingDisbursement,
    FundingObligation,
    FundingProgramme,
    FundingProofOfUse,
)

T = TypeVar("T")


def _to_decimal(value: object) -> Decimal:
    """Coerce a stored money value to exact Decimal, degrading to zero.

    Routes via ``str()`` so a stray legacy float does not poison a rollup,
    and swallows junk so one malformed row cannot blow up a dashboard that
    summarises a hundred.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


class ProgrammeRepository:
    """The catalogue of programmes, shared across projects."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, programme_id: uuid.UUID) -> FundingProgramme | None:
        return await self.session.get(FundingProgramme, programme_id)

    async def list(
        self,
        *,
        country: str | None = None,
        status: str | None = None,
        authority_level: str | None = None,
        instrument: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[FundingProgramme], int]:
        """Programmes matching the filters, plus the unpaged total.

        The total is counted rather than inferred from the page length, so a
        catalogue browser can say "showing 20 of 340" instead of leaving the
        reader to find out by paging to the end.
        """
        conditions = []
        if country:
            conditions.append(FundingProgramme.country == country.upper())
        if status:
            conditions.append(FundingProgramme.status == status)
        if authority_level:
            conditions.append(FundingProgramme.authority_level == authority_level)
        if instrument:
            conditions.append(FundingProgramme.instrument == instrument)
        if search:
            like = f"%{search.lower()}%"
            conditions.append(
                func.lower(FundingProgramme.name).like(like) | func.lower(FundingProgramme.code).like(like)
            )

        stmt = select(FundingProgramme)
        count_stmt = select(func.count()).select_from(FundingProgramme)
        for condition in conditions:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        stmt = stmt.order_by(FundingProgramme.country, FundingProgramme.code).limit(limit).offset(offset)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    async def get_by_code(self, code: str, country: str) -> FundingProgramme | None:
        stmt = select(FundingProgramme).where(
            FundingProgramme.code == code,
            FundingProgramme.country == country.upper(),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def count_applications(self, programme_id: uuid.UUID) -> int:
        """How many applications point at this programme.

        Asked with a query rather than by reading ``programme.applications``.
        That attribute is a lazy relationship, and touching it on an async
        session raises MissingGreenlet at runtime while looking perfectly
        correct in the source.
        """
        stmt = (
            select(func.count()).select_from(FundingApplication).where(FundingApplication.programme_id == programme_id)
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def create(self, **values: Any) -> FundingProgramme:
        row = FundingProgramme(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: FundingProgramme) -> None:
        await self.session.delete(row)
        await self.session.flush()


class ApplicationRepository:
    """Applications, always scoped to one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, application_id: uuid.UUID) -> FundingApplication | None:
        return await self.session.get(FundingApplication, application_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[FundingApplication]:
        stmt = select(FundingApplication).where(FundingApplication.project_id == project_id)
        if status:
            stmt = stmt.where(FundingApplication.status == status)
        stmt = stmt.order_by(FundingApplication.code)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_code(self, project_id: uuid.UUID, code: str) -> FundingApplication | None:
        stmt = select(FundingApplication).where(
            FundingApplication.project_id == project_id,
            FundingApplication.code == code,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def create(self, **values: Any) -> FundingApplication:
        row = FundingApplication(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: FundingApplication) -> None:
        await self.session.delete(row)
        await self.session.flush()


class _ApplicationChildRepository(Generic[T]):
    """Records that belong to exactly one application.

    The four children differ only in their model and their sort key, so the
    shared parts live here. ``model`` and ``order_by_column`` are set by
    subclasses rather than passed in, because a repository whose table is an
    argument is one refactor away from reading the wrong one.

    The sort key is the column's **name** and not the column itself. A mapped
    column assigned to an ordinary class is a descriptor, and reading it back
    off an instance makes SQLAlchemy try to treat that instance as a mapped
    row, which fails with UnmappedInstanceError at query time rather than at
    import time. Holding the name costs a ``getattr`` and cannot misfire;
    ``test_every_child_repository_sorts_by_a_column_its_model_has`` buys back
    the spelling check that storing a string gives up.
    """

    model: type[Any]
    order_by_column: str

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @property
    def order_by(self) -> Any:
        """The column rows are sorted by, resolved on the model."""
        return getattr(self.model, self.order_by_column)

    async def get(self, row_id: uuid.UUID) -> Any | None:
        return await self.session.get(self.model, row_id)

    async def list_for_application(self, application_id: uuid.UUID) -> list[Any]:
        stmt = select(self.model).where(self.model.application_id == application_id).order_by(self.order_by)
        return list((await self.session.execute(stmt)).scalars().all())

    async def page_for_application(
        self,
        application_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        """One page of an application's children, and how many there are in all.

        The total counts what the scope matched rather than what the page
        holds, so a reader is told there is a second page instead of finding
        out by asking for one.

        The count and the page are built from a single ``where`` held in a
        local, not from two clauses written out one after the other. Two
        clauses drift the moment somebody narrows one of them, and the drift
        is silent: a total taken over a wider set than the page reads as
        "there is more" forever, and a total taken over a narrower one hides
        rows the page is already returning.

        ``list_for_application`` is deliberately left answering with
        everything. The application detail response embeds all four child
        lists at once and the project calendar crosses applications, so
        giving the unpaged method a default limit would have cut those down
        to a page without any caller asking for one.

        The sort gets ``id`` as a tie-break, which the unpaged read does not
        need. Three of the four registers sort on a date or a cost group, and
        rows sharing one of those come back in whatever order the database
        chose; under a LIMIT that ordering is free to differ between two
        requests, which is how a row appears on both pages while another
        appears on neither.

        Args:
            application_id: The application whose children are wanted.
            limit: How many rows the page holds.
            offset: How many rows to skip before it starts.

        Returns:
            The page, and the number of rows the scope matched.
        """
        where = self.model.application_id == application_id
        count_stmt = select(func.count()).select_from(self.model).where(where)
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        stmt = select(self.model).where(where).order_by(self.order_by, self.model.id).limit(limit).offset(offset)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    async def list_for_applications(self, application_ids: list[uuid.UUID]) -> list[Any]:
        """Every child row of several applications, in one query.

        A project summary needs the children of every application on the
        project. Asking per application turns one screen into one query per
        application, which is the shape that makes a dashboard slow only
        after a customer has enough data to care.
        """
        if not application_ids:
            return []
        stmt = select(self.model).where(self.model.application_id.in_(application_ids)).order_by(self.order_by)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, **values: Any) -> Any:
        row = self.model(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()


class DisbursementRepository(_ApplicationChildRepository[FundingDisbursement]):
    """Draws against an award."""

    model = FundingDisbursement
    order_by_column = "sequence"

    async def next_sequence(self, application_id: uuid.UUID) -> int:
        """The number the next draw gets.

        Counted from the highest existing number rather than from how many
        rows there are, so deleting a draft draw does not hand its number to
        the next one and leave two records in the file with the same name.
        """
        stmt = select(func.max(FundingDisbursement.sequence)).where(
            FundingDisbursement.application_id == application_id
        )
        highest = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(highest or 0) + 1

    async def totals(self, application_id: uuid.UUID) -> dict[str, Decimal]:
        """Requested, approved and received, added up in the database."""
        stmt = select(
            func.coalesce(func.sum(FundingDisbursement.amount_requested), 0),
            func.coalesce(func.sum(FundingDisbursement.amount_approved), 0),
            func.coalesce(func.sum(FundingDisbursement.amount_received), 0),
        ).where(FundingDisbursement.application_id == application_id)
        requested, approved, received = (await self.session.execute(stmt)).one()
        return {
            "requested": _to_decimal(requested),
            "approved": _to_decimal(approved),
            "received": _to_decimal(received),
        }


class ProofOfUseRepository(_ApplicationChildRepository[FundingProofOfUse]):
    """Interim and final accounts of where the money went."""

    model = FundingProofOfUse
    order_by_column = "due_on"


class ObligationRepository(_ApplicationChildRepository[FundingObligation]):
    """Dated things somebody is answerable for."""

    model = FundingObligation
    order_by_column = "due_on"

    async def delete_derived(self, application_id: uuid.UUID, kinds: list[str]) -> int:
        """Remove obligations this module generated, leaving human ones alone.

        Recording a new award regenerates the deadlines that follow from it.
        Only rows whose source is the programme's own rules are replaced: a
        condition typed in by a person, or copied out of the notice, is
        theirs and survives, because regenerating it would silently drop
        work somebody did by hand.
        """
        if not kinds:
            return 0
        stmt = select(FundingObligation).where(
            FundingObligation.application_id == application_id,
            FundingObligation.source == "programme_rule",
            FundingObligation.kind.in_(kinds),
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        for row in rows:
            await self.session.delete(row)
        await self.session.flush()
        return len(rows)


class CostAllocationRepository(_ApplicationChildRepository[FundingCostAllocation]):
    """Which costs the programme will count."""

    model = FundingCostAllocation
    order_by_column = "cost_group"

    async def totals(self, application_id: uuid.UUID) -> dict[str, Decimal]:
        """Allocated and eligible amounts, added up in the database."""
        stmt = select(
            func.coalesce(func.sum(FundingCostAllocation.amount), 0),
            func.coalesce(func.sum(FundingCostAllocation.eligible_amount), 0),
        ).where(FundingCostAllocation.application_id == application_id)
        amount, eligible = (await self.session.execute(stmt)).one()
        return {"amount": _to_decimal(amount), "eligible": _to_decimal(eligible)}
