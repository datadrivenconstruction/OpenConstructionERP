"""‌⁠‍Data access layer for the Service & Maintenance module.

One repository class per entity. Each class is a thin async-SQLAlchemy wrapper
that the service layer composes. Kept deliberately dumb — no business logic.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base
from app.modules.service.models import (
    AssetInspectionChecklist,
    DebriefReport,
    ServiceAsset,
    ServiceContract,
    ServiceRecurringSchedule,
    ServiceSchedule,
    ServiceTicket,
    ServiceWorkOrder,
    ServiceWorkOrderItem,
    SLADefinition,
)

ModelT = TypeVar("ModelT", bound=Base)


class _BaseRepo(Generic[ModelT]):
    """‌⁠‍Tiny shared CRUD base for the service module repositories.

    Each subclass declares ``model``; that's enough for the generic helpers.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def create(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update_fields(self, entity_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(self.model).where(self.model.id == entity_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, entity_id: uuid.UUID) -> None:
        obj = await self.get_by_id(entity_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


# ── Contract repository ───────────────────────────────────────────────────


class ContractRepository(_BaseRepo[ServiceContract]):
    """‌⁠‍Data access for ServiceContract."""

    model = ServiceContract

    async def next_contract_number(self) -> str:
        count = (await self.session.execute(select(func.count()).select_from(ServiceContract))).scalar_one()
        return f"SC-{count + 1:04d}"

    async def list_for_customer(
        self,
        customer_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ServiceContract], int]:
        base = select(ServiceContract).where(ServiceContract.customer_id == customer_id)
        if status is not None:
            base = base.where(ServiceContract.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceContract.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ServiceContract], int]:
        base = select(ServiceContract).where(ServiceContract.project_id == project_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceContract.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ServiceContract], int]:
        base = select(ServiceContract)
        if status is not None:
            base = base.where(ServiceContract.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceContract.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)


# ── Asset repository ──────────────────────────────────────────────────────


class AssetRepository(_BaseRepo[ServiceAsset]):
    """Data access for ServiceAsset."""

    model = ServiceAsset

    async def list_for_contract(
        self,
        contract_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[ServiceAsset], int]:
        base = select(ServiceAsset).where(ServiceAsset.contract_id == contract_id)
        if status is not None:
            base = base.where(ServiceAsset.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceAsset.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)


# ── Ticket repository ─────────────────────────────────────────────────────


class TicketRepository(_BaseRepo[ServiceTicket]):
    """Data access for ServiceTicket."""

    model = ServiceTicket

    async def next_ticket_number(self, contract_id: uuid.UUID) -> str:
        count = (
            await self.session.execute(
                select(func.count()).select_from(ServiceTicket).where(ServiceTicket.contract_id == contract_id)
            )
        ).scalar_one()
        return f"T-{count + 1:05d}"

    async def list_for_contract(
        self,
        contract_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        priority: str | None = None,
    ) -> tuple[list[ServiceTicket], int]:
        base = select(ServiceTicket).where(ServiceTicket.contract_id == contract_id)
        if status is not None:
            base = base.where(ServiceTicket.status == status)
        if priority is not None:
            base = base.where(ServiceTicket.priority == priority)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceTicket.reported_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ServiceTicket], int]:
        base = (
            select(ServiceTicket)
            .join(ServiceContract, ServiceContract.id == ServiceTicket.contract_id)
            .where(ServiceContract.project_id == project_id)
        )
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceTicket.reported_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        priority: str | None = None,
    ) -> tuple[list[ServiceTicket], int]:
        """List tickets across every contract (tenant-wide dispatcher view).

        Backs the global ``/tickets/`` listing on the ``/service`` route,
        where there is no contract or project to scope by. Mirrors the
        ``WorkOrderRepository.list_all`` / ``ContractRepository.list_all``
        shape so the page's three list tabs behave consistently.
        """
        base = select(ServiceTicket)
        if status is not None:
            base = base.where(ServiceTicket.status == status)
        if priority is not None:
            base = base.where(ServiceTicket.priority == priority)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceTicket.reported_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)

    async def count_open_for_contract(self, contract_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ServiceTicket)
            .where(
                ServiceTicket.contract_id == contract_id,
                ServiceTicket.status.in_(("new", "assigned", "in_progress")),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_in_progress_for_contract(self, contract_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ServiceTicket)
            .where(
                ServiceTicket.contract_id == contract_id,
                ServiceTicket.status == "in_progress",
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())


# ── ServiceWorkOrder repository ──────────────────────────────────────────────────


class WorkOrderRepository(_BaseRepo[ServiceWorkOrder]):
    """Data access for ServiceWorkOrder."""

    model = ServiceWorkOrder

    async def next_work_order_number(self) -> str:
        count = (await self.session.execute(select(func.count()).select_from(ServiceWorkOrder))).scalar_one()
        return f"WO-{count + 1:06d}"

    async def list_for_ticket(self, ticket_id: uuid.UUID) -> list[ServiceWorkOrder]:
        stmt = (
            select(ServiceWorkOrder)
            .where(ServiceWorkOrder.ticket_id == ticket_id)
            .order_by(ServiceWorkOrder.created_at.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        technician_id: str | None = None,
    ) -> tuple[list[ServiceWorkOrder], int]:
        base = select(ServiceWorkOrder)
        if status is not None:
            base = base.where(ServiceWorkOrder.status == status)
        if technician_id is not None:
            base = base.where(ServiceWorkOrder.technician_id == technician_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceWorkOrder.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)


# ── ServiceWorkOrderItem repository ──────────────────────────────────────────────


class WorkOrderItemRepository(_BaseRepo[ServiceWorkOrderItem]):
    """Data access for ServiceWorkOrderItem."""

    model = ServiceWorkOrderItem

    async def list_for_work_order(self, work_order_id: uuid.UUID) -> list[ServiceWorkOrderItem]:
        stmt = select(ServiceWorkOrderItem).where(ServiceWorkOrderItem.work_order_id == work_order_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)


# ── Debrief repository ────────────────────────────────────────────────────


class DebriefRepository(_BaseRepo[DebriefReport]):
    """Data access for DebriefReport."""

    model = DebriefReport

    async def list_for_work_order(self, work_order_id: uuid.UUID) -> list[DebriefReport]:
        stmt = (
            select(DebriefReport)
            .where(DebriefReport.work_order_id == work_order_id)
            .order_by(DebriefReport.created_at.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)


# ── SLA repository ────────────────────────────────────────────────────────


class SLADefinitionRepository(_BaseRepo[SLADefinition]):
    """Data access for SLADefinition."""

    model = SLADefinition

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        active_only: bool = False,
    ) -> tuple[list[SLADefinition], int]:
        base = select(SLADefinition)
        if active_only:
            base = base.where(SLADefinition.is_active.is_(True))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(SLADefinition.name).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)


# ── Schedule repository ───────────────────────────────────────────────────


class ScheduleRepository(_BaseRepo[ServiceSchedule]):
    """Data access for ServiceSchedule (PPM)."""

    model = ServiceSchedule

    async def list_for_asset(self, asset_id: uuid.UUID) -> list[ServiceSchedule]:
        stmt = (
            select(ServiceSchedule)
            .where(ServiceSchedule.asset_id == asset_id)
            .order_by(ServiceSchedule.next_due_date.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)

    async def list_due_within(
        self,
        contract_id: uuid.UUID,
        due_before: str,
    ) -> list[ServiceSchedule]:
        """Return active schedules of assets in this contract due on/before a given date."""
        stmt = (
            select(ServiceSchedule)
            .join(ServiceAsset, ServiceAsset.id == ServiceSchedule.asset_id)
            .where(
                ServiceAsset.contract_id == contract_id,
                ServiceSchedule.is_active.is_(True),
                ServiceSchedule.next_due_date <= due_before,
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)


# ── Checklist repository ──────────────────────────────────────────────────


class ChecklistRepository(_BaseRepo[AssetInspectionChecklist]):
    """Data access for AssetInspectionChecklist (template)."""

    model = AssetInspectionChecklist

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        asset_type: str | None = None,
        active_only: bool = False,
    ) -> tuple[list[AssetInspectionChecklist], int]:
        base = select(AssetInspectionChecklist)
        if asset_type is not None:
            base = base.where(AssetInspectionChecklist.asset_type == asset_type)
        if active_only:
            base = base.where(AssetInspectionChecklist.is_active.is_(True))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(AssetInspectionChecklist.name).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)


# ── Recurring schedule repository ─────────────────────────────────────────


class RecurringScheduleRepository(_BaseRepo[ServiceRecurringSchedule]):
    """‌⁠‍Data access for the RRULE-driven recurring-ticket schedule (T10)."""

    model = ServiceRecurringSchedule

    async def list_for_project(
        self,
        project_id: uuid.UUID | None,
        *,
        offset: int = 0,
        limit: int = 100,
        enabled: bool | None = None,
    ) -> tuple[list[ServiceRecurringSchedule], int]:
        base = select(ServiceRecurringSchedule)
        if project_id is not None:
            base = base.where(ServiceRecurringSchedule.project_id == project_id)
        if enabled is not None:
            base = base.where(ServiceRecurringSchedule.enabled.is_(enabled))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ServiceRecurringSchedule.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total)

    async def list_due(
        self,
        *,
        now_iso: str,
        limit: int = 100,
    ) -> list[ServiceRecurringSchedule]:
        """Schedules ready to be materialised (enabled + next_run_at <= now)."""
        stmt = (
            select(ServiceRecurringSchedule)
            .where(
                ServiceRecurringSchedule.enabled.is_(True),
                ServiceRecurringSchedule.next_run_at.isnot(None),
                ServiceRecurringSchedule.next_run_at <= now_iso,
            )
            .order_by(ServiceRecurringSchedule.next_run_at)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)
