"""LED Display data access layer."""

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.led_display.models import (
    LEDBudget,
    LEDController,
    LEDDocument,
    LEDInstallation,
    LEDInventory,
    LEDMaintenanceLog,
    LEDMilestone,
    LEDPanel,
    LEDProject,
)


class LEDProjectRepository:
    """Data access for LEDProject models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, project_id: uuid.UUID) -> LEDProject | None:
        return await self.session.get(LEDProject, project_id)

    async def list_for_project(
        self,
        parent_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[LEDProject], int]:
        base = select(LEDProject).where(LEDProject.project_id == parent_project_id)
        if status is not None:
            base = base.where(LEDProject.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDProject.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[LEDProject], int]:
        base = select(LEDProject)
        if status is not None:
            base = base.where(LEDProject.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDProject.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, project: LEDProject) -> LEDProject:
        self.session.add(project)
        await self.session.flush()
        return project

    async def update_fields(self, project_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDProject)
            .where(LEDProject.id == project_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, project_id: uuid.UUID) -> None:
        project = await self.get_by_id(project_id)
        if project is not None:
            await self.session.delete(project)
            await self.session.flush()


class LEDPanelRepository:
    """Data access for LEDPanel models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, panel_id: uuid.UUID) -> LEDPanel | None:
        return await self.session.get(LEDPanel, panel_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[LEDPanel], int]:
        base = select(LEDPanel).where(LEDPanel.led_project_id == led_project_id)
        if status is not None:
            base = base.where(LEDPanel.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDPanel.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, panel: LEDPanel) -> LEDPanel:
        self.session.add(panel)
        await self.session.flush()
        return panel

    async def update_fields(self, panel_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDPanel)
            .where(LEDPanel.id == panel_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, panel_id: uuid.UUID) -> None:
        panel = await self.get_by_id(panel_id)
        if panel is not None:
            await self.session.delete(panel)
            await self.session.flush()


class LEDControllerRepository:
    """Data access for LEDController models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, controller_id: uuid.UUID) -> LEDController | None:
        return await self.session.get(LEDController, controller_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[LEDController], int]:
        base = select(LEDController).where(LEDController.led_project_id == led_project_id)
        if status is not None:
            base = base.where(LEDController.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDController.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, controller: LEDController) -> LEDController:
        self.session.add(controller)
        await self.session.flush()
        return controller

    async def update_fields(self, controller_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDController)
            .where(LEDController.id == controller_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, controller_id: uuid.UUID) -> None:
        controller = await self.get_by_id(controller_id)
        if controller is not None:
            await self.session.delete(controller)
            await self.session.flush()


class LEDInventoryRepository:
    """Data access for LEDInventory models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, inventory_id: uuid.UUID) -> LEDInventory | None:
        return await self.session.get(LEDInventory, inventory_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        item_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDInventory], int]:
        base = select(LEDInventory).where(LEDInventory.led_project_id == led_project_id)
        if item_type is not None:
            base = base.where(LEDInventory.item_type == item_type)
        if status is not None:
            base = base.where(LEDInventory.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDInventory.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        item_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDInventory], int]:
        base = select(LEDInventory)
        if item_type is not None:
            base = base.where(LEDInventory.item_type == item_type)
        if status is not None:
            base = base.where(LEDInventory.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDInventory.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, inventory: LEDInventory) -> LEDInventory:
        self.session.add(inventory)
        await self.session.flush()
        return inventory

    async def update_fields(self, inventory_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDInventory)
            .where(LEDInventory.id == inventory_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, inventory_id: uuid.UUID) -> None:
        inventory = await self.get_by_id(inventory_id)
        if inventory is not None:
            await self.session.delete(inventory)
            await self.session.flush()


class LEDInstallationRepository:
    """Data access for LEDInstallation models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, installation_id: uuid.UUID) -> LEDInstallation | None:
        return await self.session.get(LEDInstallation, installation_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        installation_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDInstallation], int]:
        base = select(LEDInstallation).where(
            LEDInstallation.led_project_id == led_project_id
        )
        if installation_type is not None:
            base = base.where(LEDInstallation.installation_type == installation_type)
        if status is not None:
            base = base.where(LEDInstallation.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDInstallation.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, installation: LEDInstallation) -> LEDInstallation:
        self.session.add(installation)
        await self.session.flush()
        return installation

    async def update_fields(self, installation_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDInstallation)
            .where(LEDInstallation.id == installation_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, installation_id: uuid.UUID) -> None:
        installation = await self.get_by_id(installation_id)
        if installation is not None:
            await self.session.delete(installation)
            await self.session.flush()


class LEDMilestoneRepository:
    """Data access for LEDMilestone models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, milestone_id: uuid.UUID) -> LEDMilestone | None:
        return await self.session.get(LEDMilestone, milestone_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        milestone_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDMilestone], int]:
        base = select(LEDMilestone).where(LEDMilestone.led_project_id == led_project_id)
        if milestone_type is not None:
            base = base.where(LEDMilestone.milestone_type == milestone_type)
        if status is not None:
            base = base.where(LEDMilestone.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDMilestone.planned_date.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, milestone: LEDMilestone) -> LEDMilestone:
        self.session.add(milestone)
        await self.session.flush()
        return milestone

    async def update_fields(self, milestone_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDMilestone)
            .where(LEDMilestone.id == milestone_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, milestone_id: uuid.UUID) -> None:
        milestone = await self.get_by_id(milestone_id)
        if milestone is not None:
            await self.session.delete(milestone)
            await self.session.flush()


class LEDMaintenanceLogRepository:
    """Data access for LEDMaintenanceLog models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, log_id: uuid.UUID) -> LEDMaintenanceLog | None:
        return await self.session.get(LEDMaintenanceLog, log_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        maintenance_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDMaintenanceLog], int]:
        base = select(LEDMaintenanceLog).where(
            LEDMaintenanceLog.led_project_id == led_project_id
        )
        if maintenance_type is not None:
            base = base.where(LEDMaintenanceLog.maintenance_type == maintenance_type)
        if status is not None:
            base = base.where(LEDMaintenanceLog.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDMaintenanceLog.scheduled_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_upcoming(
        self,
        led_project_id: uuid.UUID | None = None,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[LEDMaintenanceLog], int]:
        base = select(LEDMaintenanceLog).where(
            LEDMaintenanceLog.next_maintenance_date.isnot(None),
            LEDMaintenanceLog.status == "scheduled",
        )
        if led_project_id is not None:
            base = base.where(LEDMaintenanceLog.led_project_id == led_project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDMaintenanceLog.next_maintenance_date.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, log: LEDMaintenanceLog) -> LEDMaintenanceLog:
        self.session.add(log)
        await self.session.flush()
        return log

    async def update_fields(self, log_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDMaintenanceLog)
            .where(LEDMaintenanceLog.id == log_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, log_id: uuid.UUID) -> None:
        log = await self.get_by_id(log_id)
        if log is not None:
            await self.session.delete(log)
            await self.session.flush()


class LEDDocumentRepository:
    """Data access for LEDDocument models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, document_id: uuid.UUID) -> LEDDocument | None:
        return await self.session.get(LEDDocument, document_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        document_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDDocument], int]:
        base = select(LEDDocument).where(LEDDocument.led_project_id == led_project_id)
        if document_type is not None:
            base = base.where(LEDDocument.document_type == document_type)
        if status is not None:
            base = base.where(LEDDocument.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDDocument.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, document: LEDDocument) -> LEDDocument:
        self.session.add(document)
        await self.session.flush()
        return document

    async def update_fields(self, document_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDDocument)
            .where(LEDDocument.id == document_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, document_id: uuid.UUID) -> None:
        document = await self.get_by_id(document_id)
        if document is not None:
            await self.session.delete(document)
            await self.session.flush()


class LEDBudgetRepository:
    """Data access for LEDBudget models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, budget_id: uuid.UUID) -> LEDBudget | None:
        return await self.session.get(LEDBudget, budget_id)

    async def list_for_led_project(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDBudget], int]:
        base = select(LEDBudget).where(LEDBudget.led_project_id == led_project_id)
        if category is not None:
            base = base.where(LEDBudget.category == category)
        if status is not None:
            base = base.where(LEDBudget.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(LEDBudget.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, budget: LEDBudget) -> LEDBudget:
        self.session.add(budget)
        await self.session.flush()
        return budget

    async def update_fields(self, budget_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(LEDBudget)
            .where(LEDBudget.id == budget_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, budget_id: uuid.UUID) -> None:
        budget = await self.get_by_id(budget_id)
        if budget is not None:
            await self.session.delete(budget)
            await self.session.flush()