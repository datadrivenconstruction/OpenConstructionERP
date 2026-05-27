"""‌⁠‍Bid Management data access layer."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bid_management.models import (
    BidAward,
    BidComparison,
    Bidder,
    BidInvitation,
    BidLeveling,
    BidPackage,
    BidPackageLineItem,
    BidQA,
    BidRejection,
    BidSubmission,
    BidSubmissionLine,
)


class _BaseRepo:
    """‌⁠‍Shared CRUD helpers for a single ORM class."""

    model: type[Any]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> Any | None:
        return await self.session.get(self.model, entity_id)

    async def create(self, obj: Any) -> Any:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_fields(self, entity_id: uuid.UUID, **fields: Any) -> None:
        if not fields:
            return
        stmt = update(self.model).where(self.model.id == entity_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, entity_id: uuid.UUID) -> None:
        obj = await self.get_by_id(entity_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


class BidPackageRepository(_BaseRepo):
    """‌⁠‍Data access for :class:`BidPackage`."""

    model = BidPackage

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[BidPackage], int]:
        base = select(BidPackage).where(BidPackage.project_id == project_id)
        if status is not None:
            base = base.where(BidPackage.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BidPackage.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_by_code(self, code: str) -> BidPackage | None:
        result = await self.session.execute(select(BidPackage).where(BidPackage.code == code))
        return result.scalar_one_or_none()


class BidPackageLineItemRepository(_BaseRepo):
    """Data access for :class:`BidPackageLineItem`."""

    model = BidPackageLineItem

    async def list_for_package(self, package_id: uuid.UUID) -> list[BidPackageLineItem]:
        stmt = (
            select(BidPackageLineItem)
            .where(BidPackageLineItem.package_id == package_id)
            .order_by(BidPackageLineItem.order_index, BidPackageLineItem.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_create(self, items: list[BidPackageLineItem]) -> list[BidPackageLineItem]:
        self.session.add_all(items)
        await self.session.flush()
        return items


class BidInvitationRepository(_BaseRepo):
    """Data access for :class:`BidInvitation`."""

    model = BidInvitation

    async def list_for_package(
        self,
        package_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[BidInvitation]:
        base = select(BidInvitation).where(BidInvitation.package_id == package_id)
        if status is not None:
            base = base.where(BidInvitation.status == status)
        result = await self.session.execute(base)
        return list(result.scalars().all())

    async def invitations_pending(self, package_id: uuid.UUID) -> list[BidInvitation]:
        stmt = select(BidInvitation).where(
            BidInvitation.package_id == package_id,
            BidInvitation.status.in_(("pending", "sent", "opened")),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class BidderRepository(_BaseRepo):
    """Data access for :class:`Bidder`."""

    model = Bidder

    async def list_for_package(self, package_id: uuid.UUID) -> list[Bidder]:
        stmt = select(Bidder).where(Bidder.package_id == package_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class BidSubmissionRepository(_BaseRepo):
    """Data access for :class:`BidSubmission`."""

    model = BidSubmission

    async def submissions_for_package(self, package_id: uuid.UUID) -> list[BidSubmission]:
        # Submissions live under invitations which live under packages.
        stmt = (
            select(BidSubmission)
            .join(BidInvitation, BidInvitation.id == BidSubmission.invitation_id)
            .where(BidInvitation.package_id == package_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_invitation(self, invitation_id: uuid.UUID) -> BidSubmission | None:
        stmt = select(BidSubmission).where(BidSubmission.invitation_id == invitation_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class BidSubmissionLineRepository(_BaseRepo):
    """Data access for :class:`BidSubmissionLine`."""

    model = BidSubmissionLine

    async def list_for_submission(self, submission_id: uuid.UUID) -> list[BidSubmissionLine]:
        stmt = select(BidSubmissionLine).where(BidSubmissionLine.submission_id == submission_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_create(self, items: list[BidSubmissionLine]) -> list[BidSubmissionLine]:
        self.session.add_all(items)
        await self.session.flush()
        return items


class BidQARepository(_BaseRepo):
    """Data access for :class:`BidQA`."""

    model = BidQA

    async def q_and_a_for_package(self, package_id: uuid.UUID) -> list[BidQA]:
        stmt = select(BidQA).where(BidQA.package_id == package_id).order_by(BidQA.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class BidComparisonRepository(_BaseRepo):
    """Data access for :class:`BidComparison`."""

    model = BidComparison

    async def get_for_package(self, package_id: uuid.UUID) -> BidComparison | None:
        stmt = select(BidComparison).where(BidComparison.package_id == package_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class BidLevelingRepository(_BaseRepo):
    """Data access for :class:`BidLeveling`."""

    model = BidLeveling

    async def levelings_for_comparison(self, comparison_id: uuid.UUID) -> list[BidLeveling]:
        stmt = (
            select(BidLeveling)
            .where(BidLeveling.comparison_id == comparison_id)
            .order_by(BidLeveling.rank.asc(), BidLeveling.normalized_total.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_for_comparison(self, comparison_id: uuid.UUID) -> None:
        stmt = select(BidLeveling).where(BidLeveling.comparison_id == comparison_id)
        result = await self.session.execute(stmt)
        for row in result.scalars().all():
            await self.session.delete(row)
        await self.session.flush()


class BidAwardRepository(_BaseRepo):
    """Data access for :class:`BidAward`."""

    model = BidAward

    async def get_for_package(self, package_id: uuid.UUID) -> BidAward | None:
        stmt = select(BidAward).where(BidAward.package_id == package_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class BidRejectionRepository(_BaseRepo):
    """Data access for :class:`BidRejection`."""

    model = BidRejection

    async def list_for_package(self, package_id: uuid.UUID) -> list[BidRejection]:
        stmt = select(BidRejection).where(BidRejection.package_id == package_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
