"""Takeoff data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement


class TakeoffRepository:
    """Data access for TakeoffDocument model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, doc_id: uuid.UUID) -> TakeoffDocument | None:
        return await self.session.get(TakeoffDocument, doc_id)

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[TakeoffDocument]:
        stmt = select(TakeoffDocument).where(TakeoffDocument.owner_id == owner_id)
        if project_id:
            stmt = stmt.where(TakeoffDocument.project_id == project_id)
        stmt = stmt.order_by(TakeoffDocument.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, doc: TakeoffDocument) -> TakeoffDocument:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_fields(self, doc_id: uuid.UUID, **fields: object) -> None:
        stmt = update(TakeoffDocument).where(TakeoffDocument.id == doc_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, doc_id: uuid.UUID) -> None:
        doc = await self.get_by_id(doc_id)
        if doc is not None:
            await self.session.delete(doc)
            await self.session.flush()


class MeasurementRepository:
    """Data access for TakeoffMeasurement models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, measurement_id: uuid.UUID) -> TakeoffMeasurement | None:
        """Get a measurement by ID."""
        return await self.session.get(TakeoffMeasurement, measurement_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        document_id: str | None = None,
        page: int | None = None,
        group_name: str | None = None,
        measurement_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[TakeoffMeasurement]:
        """List measurements for a project with optional filters."""
        stmt = select(TakeoffMeasurement).where(
            TakeoffMeasurement.project_id == project_id
        )
        if document_id is not None:
            stmt = stmt.where(TakeoffMeasurement.document_id == document_id)
        if page is not None:
            stmt = stmt.where(TakeoffMeasurement.page == page)
        if group_name is not None:
            stmt = stmt.where(TakeoffMeasurement.group_name == group_name)
        if measurement_type is not None:
            stmt = stmt.where(TakeoffMeasurement.type == measurement_type)

        stmt = (
            stmt.order_by(TakeoffMeasurement.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, measurement: TakeoffMeasurement) -> TakeoffMeasurement:
        """Insert a new measurement."""
        self.session.add(measurement)
        await self.session.flush()
        return measurement

    async def create_bulk(
        self, measurements: list[TakeoffMeasurement]
    ) -> list[TakeoffMeasurement]:
        """Insert multiple measurements at once."""
        self.session.add_all(measurements)
        await self.session.flush()
        return measurements

    async def update_fields(
        self, measurement_id: uuid.UUID, **fields: object
    ) -> None:
        """Update specific fields on a measurement."""
        stmt = (
            update(TakeoffMeasurement)
            .where(TakeoffMeasurement.id == measurement_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, measurement_id: uuid.UUID) -> None:
        """Hard delete a measurement."""
        item = await self.get_by_id(measurement_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def all_for_project(
        self, project_id: uuid.UUID
    ) -> list[TakeoffMeasurement]:
        """Return all measurements for a project (used for summary/export)."""
        stmt = select(TakeoffMeasurement).where(
            TakeoffMeasurement.project_id == project_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
