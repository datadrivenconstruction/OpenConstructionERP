"""Tendering data access layer.

All database queries for tender packages and bids live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.tendering.models import TenderBid, TenderPackage


class TenderingRepository:
    """Data access for TenderPackage and TenderBid models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Packages ─────────────────────────────────────────────────────────

    async def get_package_by_id(self, package_id: uuid.UUID) -> TenderPackage | None:
        """Get a package by ID with bids eagerly loaded."""
        stmt = (
            select(TenderPackage)
            .where(TenderPackage.id == package_id)
            .options(selectinload(TenderPackage.bids))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_packages(
        self,
        *,
        project_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TenderPackage], int]:
        """List packages with optional project filter and pagination."""
        base = select(TenderPackage)
        if project_id is not None:
            base = base.where(TenderPackage.project_id == project_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch with bids
        stmt = (
            base.options(selectinload(TenderPackage.bids))
            .order_by(TenderPackage.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        packages = list(result.scalars().all())

        return packages, total

    async def create_package(self, package: TenderPackage) -> TenderPackage:
        """Insert a new tender package."""
        self.session.add(package)
        await self.session.flush()
        return package

    async def update_package_fields(
        self, package_id: uuid.UUID, **fields: object
    ) -> None:
        """Update specific fields on a package."""
        stmt = (
            update(TenderPackage)
            .where(TenderPackage.id == package_id)
            .values(**fields)
        )
        await self.session.execute(stmt)

    async def delete_package(self, package_id: uuid.UUID) -> None:
        """Hard delete a package and its bids."""
        package = await self.get_package_by_id(package_id)
        if package is not None:
            await self.session.delete(package)
            await self.session.flush()

    # ── Bids ─────────────────────────────────────────────────────────────

    async def get_bid_by_id(self, bid_id: uuid.UUID) -> TenderBid | None:
        """Get a bid by ID."""
        return await self.session.get(TenderBid, bid_id)

    async def list_bids_for_package(
        self, package_id: uuid.UUID
    ) -> list[TenderBid]:
        """List all bids for a package."""
        stmt = (
            select(TenderBid)
            .where(TenderBid.package_id == package_id)
            .order_by(TenderBid.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_bid(self, bid: TenderBid) -> TenderBid:
        """Insert a new bid."""
        self.session.add(bid)
        await self.session.flush()
        return bid

    async def update_bid_fields(self, bid_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a bid."""
        stmt = update(TenderBid).where(TenderBid.id == bid_id).values(**fields)
        await self.session.execute(stmt)

    async def delete_bid(self, bid_id: uuid.UUID) -> None:
        """Hard delete a bid."""
        bid = await self.get_bid_by_id(bid_id)
        if bid is not None:
            await self.session.delete(bid)
            await self.session.flush()
