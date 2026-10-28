# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site Logistics data access layer.

Pure data access for gates, laydown zones, delivery bookings and the bill
positions those deliveries are booked against - no business logic. All queries
are project-scoped by the caller.
"""

import uuid
from datetime import datetime

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.boq.models import BOQ, Position
from app.modules.site_logistics.models import DeliveryBooking, DeliveryLine, Gate, LaydownZone


class GateRepository:
    """Data access for Gate models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, gate_id: uuid.UUID) -> Gate | None:
        """Get a gate by ID."""
        return await self.session.get(Gate, gate_id)

    async def list_for_project(self, project_id: uuid.UUID) -> list[Gate]:
        """List all gates for a project, ordered by name."""
        stmt = select(Gate).where(Gate.project_id == project_id).order_by(Gate.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, gate: Gate) -> Gate:
        """Insert a new gate."""
        self.session.add(gate)
        await self.session.flush()
        return gate

    async def update_fields(self, gate_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a gate."""
        stmt = update(Gate).where(Gate.id == gate_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(Gate, gate_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, gate: Gate) -> None:
        """Delete a gate."""
        await self.session.delete(gate)
        await self.session.flush()


class LaydownZoneRepository:
    """Data access for LaydownZone models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, zone_id: uuid.UUID) -> LaydownZone | None:
        """Get a laydown zone by ID."""
        return await self.session.get(LaydownZone, zone_id)

    async def list_for_project(self, project_id: uuid.UUID) -> list[LaydownZone]:
        """List all laydown zones for a project, ordered by name."""
        stmt = select(LaydownZone).where(LaydownZone.project_id == project_id).order_by(LaydownZone.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, zone: LaydownZone) -> LaydownZone:
        """Insert a new laydown zone."""
        self.session.add(zone)
        await self.session.flush()
        return zone

    async def update_fields(self, zone_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a laydown zone."""
        stmt = update(LaydownZone).where(LaydownZone.id == zone_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(LaydownZone, zone_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, zone: LaydownZone) -> None:
        """Delete a laydown zone."""
        await self.session.delete(zone)
        await self.session.flush()


class DeliveryRepository:
    """Data access for DeliveryBooking models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, delivery_id: uuid.UUID) -> DeliveryBooking | None:
        """Get a delivery by ID."""
        return await self.session.get(DeliveryBooking, delivery_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        day_start: datetime | None = None,
        day_end: datetime | None = None,
        gate_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[DeliveryBooking]:
        """List deliveries for a project, chronologically, with optional filters.

        When ``day_start`` / ``day_end`` are supplied, only deliveries whose
        window touches that half-open range ``[day_start, day_end)`` are
        returned (a delivery is "on" a day if its window overlaps the day).
        """
        stmt = select(DeliveryBooking).where(DeliveryBooking.project_id == project_id)
        if gate_id is not None:
            stmt = stmt.where(DeliveryBooking.gate_id == gate_id)
        if status is not None:
            stmt = stmt.where(DeliveryBooking.status == status)
        if day_start is not None and day_end is not None:
            # Window overlaps the day: starts before the day ends AND ends after
            # the day begins.
            stmt = stmt.where(
                DeliveryBooking.window_start < day_end,
                DeliveryBooking.window_end > day_start,
            )
        stmt = stmt.order_by(DeliveryBooking.window_start.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_approved_for_gate(
        self,
        gate_id: uuid.UUID,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> list[tuple[uuid.UUID, datetime, datetime]]:
        """Return ``(id, window_start, window_end)`` for approved gate deliveries.

        Used to detect clashes before approving another delivery. ``exclude_id``
        drops the delivery being (re)approved so it never clashes with itself.
        """
        stmt = select(
            DeliveryBooking.id,
            DeliveryBooking.window_start,
            DeliveryBooking.window_end,
        ).where(
            DeliveryBooking.gate_id == gate_id,
            DeliveryBooking.status == "approved",
        )
        if exclude_id is not None:
            stmt = stmt.where(DeliveryBooking.id != exclude_id)
        result = await self.session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def create(self, delivery: DeliveryBooking) -> DeliveryBooking:
        """Insert a new delivery booking."""
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def update_fields(self, delivery_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a delivery."""
        stmt = update(DeliveryBooking).where(DeliveryBooking.id == delivery_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(DeliveryBooking, delivery_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, delivery: DeliveryBooking) -> None:
        """Delete a delivery."""
        await self.session.delete(delivery)
        await self.session.flush()

    async def status_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        """Count deliveries grouped by status for a project."""
        stmt = (
            select(DeliveryBooking.status, func.count())
            .where(DeliveryBooking.project_id == project_id)
            .group_by(DeliveryBooking.status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: row[1] for row in rows}

    async def count_upcoming_approved(self, project_id: uuid.UUID, now: datetime) -> int:
        """Count approved deliveries whose window has not yet started."""
        stmt = (
            select(func.count())
            .select_from(DeliveryBooking)
            .where(
                DeliveryBooking.project_id == project_id,
                DeliveryBooking.status == "approved",
                DeliveryBooking.window_start >= now,
            )
        )
        return (await self.session.execute(stmt)).scalar_one()


class DeliveryLineRepository:
    """Data access for the bill positions carried by a delivery."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_for_delivery(self, delivery_id: uuid.UUID, lines: list[DeliveryLine]) -> None:
        """Swap a delivery's lines for the supplied list.

        A booking is always saved whole (see ``DeliveryUpdate.lines``), so the
        write is a delete-then-insert rather than a per-line diff.
        """
        await self.session.execute(delete(DeliveryLine).where(DeliveryLine.delivery_id == delivery_id))
        for line in lines:
            line.delivery_id = delivery_id
            self.session.add(line)
        await self.session.flush()

    async def list_for_delivery(self, delivery_id: uuid.UUID) -> list[DeliveryLine]:
        """List one delivery's lines in their stored order."""
        stmt = (
            select(DeliveryLine).where(DeliveryLine.delivery_id == delivery_id).order_by(DeliveryLine.sort_order.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_project_line_facts(
        self,
        project_id: uuid.UUID,
    ) -> list[tuple[uuid.UUID, str, str]]:
        """Return ``(position_id, quantity, delivery_status)`` for a project.

        Only lines that still point at a bill position are returned - a line
        whose position was deleted covers nothing, and is counted separately by
        :meth:`count_detached_lines`.
        """
        stmt = (
            select(DeliveryLine.boq_position_id, DeliveryLine.quantity, DeliveryBooking.status)
            .join(DeliveryBooking, DeliveryLine.delivery_id == DeliveryBooking.id)
            .where(
                DeliveryBooking.project_id == project_id,
                DeliveryLine.boq_position_id.is_not(None),
            )
        )
        return [(row[0], row[1], row[2]) for row in (await self.session.execute(stmt)).all()]

    async def count_detached_lines(self, project_id: uuid.UUID) -> int:
        """Count lines whose bill position has since been deleted.

        The discriminator is the ``position_ordinal`` snapshot: it is written
        only when a line is linked to a position, so "no position id but an
        ordinal on record" means the link existed and the database nulled it on
        delete. A line that never had a position (a skip, a welfare unit) has
        neither, and is not counted here.
        """
        stmt = (
            select(func.count())
            .select_from(DeliveryLine)
            .join(DeliveryBooking, DeliveryLine.delivery_id == DeliveryBooking.id)
            .where(
                DeliveryBooking.project_id == project_id,
                DeliveryLine.boq_position_id.is_(None),
                DeliveryLine.position_ordinal.is_not(None),
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_linked_deliveries(self, project_id: uuid.UUID) -> tuple[int, int]:
        """Return ``(deliveries carrying a bill line, distinct positions covered)``."""
        deliveries_stmt = (
            select(func.count(func.distinct(DeliveryLine.delivery_id)))
            .select_from(DeliveryLine)
            .join(DeliveryBooking, DeliveryLine.delivery_id == DeliveryBooking.id)
            .where(
                DeliveryBooking.project_id == project_id,
                DeliveryLine.boq_position_id.is_not(None),
            )
        )
        positions_stmt = (
            select(func.count(func.distinct(DeliveryLine.boq_position_id)))
            .select_from(DeliveryLine)
            .join(DeliveryBooking, DeliveryLine.delivery_id == DeliveryBooking.id)
            .where(
                DeliveryBooking.project_id == project_id,
                DeliveryLine.boq_position_id.is_not(None),
            )
        )
        deliveries = (await self.session.execute(deliveries_stmt)).scalar_one()
        positions = (await self.session.execute(positions_stmt)).scalar_one()
        return deliveries, positions


class BillPositionRepository:
    """Read-only access to the project's bill, for booking deliveries against it.

    Site logistics never writes to the BOQ tables. It reads them because the
    estimate is the source of truth for what the work is: a delivery is the
    arrival of a position that is already priced, so the picker and the
    coverage table both read the same bill rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _deliverable_positions(project_id: uuid.UUID) -> Select:
        """Select the project's leaf positions - the lines a lorry can deliver.

        Structural rows are excluded two ways because the tree spells a heading
        in two ways: ``BOQService.create_section`` writes ``unit="section"``,
        while an imported or seeded bill leaves the unit blank on a parent row.
        Anything that owns children is a heading whatever its unit says, so the
        NOT IN sub-select is the reliable half and the unit check catches a
        childless heading someone has not filled in yet.
        """
        parent_alias = aliased(Position)
        parents = (
            select(parent_alias.parent_id)
            .join(BOQ, parent_alias.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id, parent_alias.parent_id.is_not(None))
            .scalar_subquery()
        )
        return (
            select(Position, BOQ.id.label("owning_boq_id"))
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(
                BOQ.project_id == project_id,
                Position.unit != "section",
                Position.id.not_in(parents),
            )
        )

    async def count_deliverable(
        self,
        project_id: uuid.UUID,
        *,
        boq_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> int:
        """Count the positions a coverage query would return before its cap."""
        stmt = self._deliverable_positions(project_id)
        if boq_id is not None:
            stmt = stmt.where(Position.boq_id == boq_id)
        if search:
            stmt = stmt.where(self._search_clause(search))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        return (await self.session.execute(count_stmt)).scalar_one()

    async def list_deliverable(
        self,
        project_id: uuid.UUID,
        *,
        boq_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 200,
    ) -> list[tuple[Position, uuid.UUID]]:
        """List the project's deliverable positions in bill order."""
        stmt = self._deliverable_positions(project_id)
        if boq_id is not None:
            stmt = stmt.where(Position.boq_id == boq_id)
        if search:
            stmt = stmt.where(self._search_clause(search))
        stmt = stmt.order_by(Position.boq_id.asc(), Position.sort_order.asc()).limit(limit)
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]

    @staticmethod
    def _search_clause(search: str) -> ClauseElement:
        """Match a search term against a position's ordinal or description."""
        term = f"%{search.strip()}%"
        return or_(Position.ordinal.ilike(term), Position.description.ilike(term))

    async def project_ids_for_positions(self, position_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        """Map each position id to the id of the project whose bill owns it."""
        if not position_ids:
            return {}
        stmt = (
            select(Position.id, BOQ.project_id)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(Position.id.in_(position_ids))
        )
        return {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}

    async def get_positions(self, position_ids: list[uuid.UUID]) -> dict[uuid.UUID, Position]:
        """Load positions by id, keyed by id, for snapshotting a delivery line."""
        if not position_ids:
            return {}
        stmt = select(Position).where(Position.id.in_(position_ids))
        return {p.id: p for p in (await self.session.execute(stmt)).scalars().all()}
