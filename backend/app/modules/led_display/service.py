"""LED Display service — business logic for LED project management."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
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
from app.modules.led_display.repository import (
    LEDBudgetRepository,
    LEDControllerRepository,
    LEDDocumentRepository,
    LEDInstallationRepository,
    LEDInventoryRepository,
    LEDMaintenanceLogRepository,
    LEDMilestoneRepository,
    LEDPanelRepository,
    LEDProjectRepository,
)
from app.modules.led_display.schemas import (
    LEDBudgetCreate,
    LEDBudgetUpdate,
    LEDControllerCreate,
    LEDControllerUpdate,
    LEDDocumentCreate,
    LEDDocumentUpdate,
    LEDInstallationCreate,
    LEDInstallationUpdate,
    LEDInventoryCreate,
    LEDInventoryUpdate,
    LEDMaintenanceLogCreate,
    LEDMaintenanceLogUpdate,
    LEDMilestoneCreate,
    LEDMilestoneUpdate,
    LEDPanelCreate,
    LEDPanelUpdate,
    LEDProjectCreate,
    LEDProjectStatsResponse,
    LEDProjectSummaryResponse,
    LEDProjectUpdate,
)

logger = logging.getLogger(__name__)


def _calculate_budget_totals(budgets: list[LEDBudget]) -> tuple[str, str, str]:
    """Calculate total, spent, and remaining budget."""
    total = Decimal("0")
    spent = Decimal("0")
    for budget in budgets:
        total += Decimal(budget.planned_amount or "0")
        spent += Decimal(budget.actual_amount or "0")
    remaining = total - spent
    return (
        str(total.quantize(Decimal("0.01"))),
        str(spent.quantize(Decimal("0.01"))),
        str(remaining.quantize(Decimal("0.01"))),
    )


class LEDProjectService:
    """Business logic for LED display projects."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.project_repo = LEDProjectRepository(session)
        self.panel_repo = LEDPanelRepository(session)
        self.controller_repo = LEDControllerRepository(session)
        self.inventory_repo = LEDInventoryRepository(session)
        self.installation_repo = LEDInstallationRepository(session)
        self.milestone_repo = LEDMilestoneRepository(session)
        self.maintenance_repo = LEDMaintenanceLogRepository(session)
        self.document_repo = LEDDocumentRepository(session)
        self.budget_repo = LEDBudgetRepository(session)

    # ── LED Projects ─────────────────────────────────────────────────────────

    async def create_project(
        self,
        data: LEDProjectCreate,
        user_id: str | None = None,
    ) -> LEDProject:
        """Create a new LED display project."""
        project = LEDProject(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            display_type=data.display_type,
            screen_width_mm=data.screen_width_mm,
            screen_height_mm=data.screen_height_mm,
            pixel_pitch_mm=data.pixel_pitch_mm,
            resolution_width=data.resolution_width,
            resolution_height=data.resolution_height,
            brightness_nits=data.brightness_nits,
            refresh_rate_hz=data.refresh_rate_hz,
            installation_location=data.installation_location,
            installation_address=data.installation_address,
            planned_start_date=data.planned_start_date,
            planned_end_date=data.planned_end_date,
            vendor_id=data.vendor_id,
            owner_id=uuid.UUID(user_id) if user_id else None,
            metadata_=data.metadata,
        )
        project = await self.project_repo.create(project)
        logger.info("LED project created: %s (%s)", project.name, project.id)
        return project

    async def get_project(self, project_id: uuid.UUID) -> LEDProject | None:
        """Get an LED project by ID."""
        return await self.project_repo.get_by_id(project_id)

    async def update_project(
        self,
        project_id: uuid.UUID,
        data: LEDProjectUpdate,
    ) -> LEDProject:
        """Update an LED project."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.project_repo.update_fields(project_id, **update_data)
        await self.session.commit()
        project = await self.project_repo.get_by_id(project_id)
        if project is None:
            raise ValueError(f"LED project {project_id} not found")
        return project

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Delete an LED project."""
        await self.project_repo.delete(project_id)
        await self.session.commit()

    async def list_projects_for_parent(
        self,
        parent_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[LEDProject], int]:
        """List LED projects for a parent construction project."""
        return await self.project_repo.list_for_project(
            parent_project_id,
            offset=offset,
            limit=limit,
            status=status,
        )

    async def list_all_projects(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[LEDProject], int]:
        """List all LED projects."""
        return await self.project_repo.list_all(
            offset=offset,
            limit=limit,
            status=status,
        )

    async def get_project_summary(self, project_id: uuid.UUID) -> LEDProjectSummaryResponse:
        """Get a summary of an LED project for listing."""
        project = await self.project_repo.get_by_id(project_id)
        if project is None:
            raise ValueError(f"LED project {project_id} not found")

        # Get panel count
        panels, _ = await self.panel_repo.list_for_led_project(project_id)
        
        # Get installation progress
        installations, _ = await self.installation_repo.list_for_led_project(project_id)
        progress = 0
        if installations:
            progress = sum(i.progress_pct for i in installations) // len(installations)

        return LEDProjectSummaryResponse(
            id=project.id,
            project_id=project.project_id,
            name=project.name,
            display_type=project.display_type,
            status=project.status,
            screen_width_mm=project.screen_width_mm,
            screen_height_mm=project.screen_height_mm,
            installation_location=project.installation_location,
            planned_end_date=project.planned_end_date,
            panels_count=len(panels),
            installation_progress_pct=progress,
            created_at=project.created_at,
        )

    async def get_project_stats(self, project_id: uuid.UUID) -> LEDProjectStatsResponse:
        """Get dashboard KPIs for an LED project."""
        # Get counts from all related entities
        panels, _ = await self.panel_repo.list_for_led_project(project_id)
        controllers, _ = await self.controller_repo.list_for_led_project(project_id)
        installations, _ = await self.installation_repo.list_for_led_project(project_id)
        milestones, _ = await self.milestone_repo.list_for_led_project(project_id)
        maintenance_logs, _ = await self.maintenance_repo.list_for_led_project(project_id)
        documents, _ = await self.document_repo.list_for_led_project(project_id)
        inventory_items, _ = await self.inventory_repo.list_for_led_project(project_id)
        budgets, _ = await self.budget_repo.list_for_led_project(project_id)

        # Calculate panel stats
        total_panels = len(panels)
        installed_panels = sum(1 for p in panels if p.status in ("installed", "tested", "operational"))
        operational_panels = sum(1 for p in panels if p.status == "operational")
        damaged_panels = sum(1 for p in panels if p.status == "damaged")

        # Calculate controller stats
        total_controllers = len(controllers)
        operational_controllers = sum(1 for c in controllers if c.status == "operational")
        faulty_controllers = sum(1 for c in controllers if c.status == "fault")

        # Calculate budget
        total_budget, spent_budget, remaining_budget = _calculate_budget_totals(budgets)

        # Calculate milestone stats
        completed_milestones = sum(1 for m in milestones if m.status == "completed")
        pending_milestones = sum(1 for m in milestones if m.status in ("pending", "in_progress"))

        # Calculate installation progress
        installation_progress_pct = 0
        if installations:
            installation_progress_pct = sum(i.progress_pct for i in installations) // len(installations)

        # Calculate maintenance stats
        maintenance_logs_count = len(maintenance_logs)
        upcoming_maintenance = sum(
            1 for m in maintenance_logs 
            if m.status == "scheduled" and m.next_maintenance_date is not None
        )

        # Calculate inventory stats
        inventory_items_count = len(inventory_items)
        low_stock_items = sum(
            1 for i in inventory_items 
            if i.quantity_in_stock < i.quantity_ordered - i.quantity_used and i.status != "used"
        )

        return LEDProjectStatsResponse(
            total_panels=total_panels,
            installed_panels=installed_panels,
            operational_panels=operational_panels,
            damaged_panels=damaged_panels,
            total_controllers=total_controllers,
            operational_controllers=operational_controllers,
            faulty_controllers=faulty_controllers,
            total_budget=total_budget,
            spent_budget=spent_budget,
            remaining_budget=remaining_budget,
            completed_milestones=completed_milestones,
            pending_milestones=pending_milestones,
            installation_progress_pct=installation_progress_pct,
            maintenance_logs_count=maintenance_logs_count,
            upcoming_maintenance=upcoming_maintenance,
            documents_count=len(documents),
            inventory_items_count=inventory_items_count,
            low_stock_items=low_stock_items,
        )

    # ── LED Panels ───────────────────────────────────────────────────────────

    async def create_panel(
        self,
        data: LEDPanelCreate,
    ) -> LEDPanel:
        """Create a new LED panel."""
        panel = LEDPanel(
            led_project_id=data.led_project_id,
            panel_id=data.panel_id,
            serial_number=data.serial_number,
            manufacturer=data.manufacturer,
            model=data.model,
            width_mm=data.width_mm,
            height_mm=data.height_mm,
            depth_mm=data.depth_mm,
            weight_kg=data.weight_kg,
            pixel_pitch_mm=data.pixel_pitch_mm,
            resolution_width=data.resolution_width,
            resolution_height=data.resolution_height,
            brightness_nits=data.brightness_nits,
            position_row=data.position_row,
            position_col=data.position_col,
            status=data.status,
            unit_cost=data.unit_cost,
            currency=data.currency,
            metadata_=data.metadata,
        )
        panel = await self.panel_repo.create(panel)
        logger.info("LED panel created: %s", panel.panel_id)
        return panel

    async def update_panel(
        self,
        panel_id: uuid.UUID,
        data: LEDPanelUpdate,
    ) -> LEDPanel:
        """Update an LED panel."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.panel_repo.update_fields(panel_id, **update_data)
        await self.session.commit()
        panel = await self.panel_repo.get_by_id(panel_id)
        if panel is None:
            raise ValueError(f"LED panel {panel_id} not found")
        return panel

    async def delete_panel(self, panel_id: uuid.UUID) -> None:
        """Delete an LED panel."""
        await self.panel_repo.delete(panel_id)
        await self.session.commit()

    async def list_panels(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[LEDPanel], int]:
        """List LED panels for a project."""
        return await self.panel_repo.list_for_led_project(
            led_project_id,
            offset=offset,
            limit=limit,
            status=status,
        )

    # ── LED Controllers ──────────────────────────────────────────────────────

    async def create_controller(
        self,
        data: LEDControllerCreate,
    ) -> LEDController:
        """Create a new LED controller."""
        controller = LEDController(
            led_project_id=data.led_project_id,
            controller_id=data.controller_id,
            serial_number=data.serial_number,
            manufacturer=data.manufacturer,
            model=data.model,
            controller_type=data.controller_type,
            input_connections=data.input_connections,
            output_connections=data.output_connections,
            max_loaded_panels=data.max_loaded_panels,
            ip_address=data.ip_address,
            mac_address=data.mac_address,
            status=data.status,
            unit_cost=data.unit_cost,
            currency=data.currency,
            metadata_=data.metadata,
        )
        controller = await self.controller_repo.create(controller)
        logger.info("LED controller created: %s", controller.controller_id)
        return controller

    async def update_controller(
        self,
        controller_id: uuid.UUID,
        data: LEDControllerUpdate,
    ) -> LEDController:
        """Update an LED controller."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.controller_repo.update_fields(controller_id, **update_data)
        await self.session.commit()
        controller = await self.controller_repo.get_by_id(controller_id)
        if controller is None:
            raise ValueError(f"LED controller {controller_id} not found")
        return controller

    async def delete_controller(self, controller_id: uuid.UUID) -> None:
        """Delete an LED controller."""
        await self.controller_repo.delete(controller_id)
        await self.session.commit()

    async def list_controllers(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[LEDController], int]:
        """List LED controllers for a project."""
        return await self.controller_repo.list_for_led_project(
            led_project_id,
            offset=offset,
            limit=limit,
            status=status,
        )

    # ── LED Inventory ────────────────────────────────────────────────────────

    async def create_inventory(
        self,
        data: LEDInventoryCreate,
    ) -> LEDInventory:
        """Create a new LED inventory item."""
        inventory = LEDInventory(
            led_project_id=data.led_project_id,
            item_name=data.item_name,
            item_type=data.item_type,
            manufacturer=data.manufacturer,
            model=data.model,
            sku=data.sku,
            serial_number=data.serial_number,
            quantity_ordered=data.quantity_ordered,
            quantity_received=data.quantity_received,
            quantity_used=data.quantity_used,
            quantity_in_stock=data.quantity_in_stock,
            warehouse_location=data.warehouse_location,
            unit_cost=data.unit_cost,
            total_cost=data.total_cost,
            currency=data.currency,
            status=data.status,
            supplier_id=data.supplier_id,
            order_date=data.order_date,
            expected_delivery=data.expected_delivery,
            received_date=data.received_date,
            metadata_=data.metadata,
        )
        inventory = await self.inventory_repo.create(inventory)
        logger.info("LED inventory item created: %s", inventory.item_name)
        return inventory

    async def update_inventory(
        self,
        inventory_id: uuid.UUID,
        data: LEDInventoryUpdate,
    ) -> LEDInventory:
        """Update an LED inventory item."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.inventory_repo.update_fields(inventory_id, **update_data)
        await self.session.commit()
        inventory = await self.inventory_repo.get_by_id(inventory_id)
        if inventory is None:
            raise ValueError(f"LED inventory {inventory_id} not found")
        return inventory

    async def delete_inventory(self, inventory_id: uuid.UUID) -> None:
        """Delete an LED inventory item."""
        await self.inventory_repo.delete(inventory_id)
        await self.session.commit()

    async def list_inventory(
        self,
        led_project_id: uuid.UUID | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        item_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDInventory], int]:
        """List LED inventory items."""
        if led_project_id is not None:
            return await self.inventory_repo.list_for_led_project(
                led_project_id,
                offset=offset,
                limit=limit,
                item_type=item_type,
                status=status,
            )
        return await self.inventory_repo.list_all(
            offset=offset,
            limit=limit,
            item_type=item_type,
            status=status,
        )

    # ── LED Installation ─────────────────────────────────────────────────────

    async def create_installation(
        self,
        data: LEDInstallationCreate,
    ) -> LEDInstallation:
        """Create a new LED installation record."""
        installation = LEDInstallation(
            led_project_id=data.led_project_id,
            installation_type=data.installation_type,
            description=data.description,
            progress_pct=data.progress_pct,
            status=data.status,
            scheduled_date=data.scheduled_date,
            started_date=data.started_date,
            completed_date=data.completed_date,
            assigned_team=data.assigned_team,
            lead_technician_id=data.lead_technician_id,
            issues=data.issues,
            notes=data.notes,
            metadata_=data.metadata,
        )
        installation = await self.installation_repo.create(installation)
        logger.info("LED installation created: %s", installation.installation_type)
        return installation

    async def update_installation(
        self,
        installation_id: uuid.UUID,
        data: LEDInstallationUpdate,
    ) -> LEDInstallation:
        """Update an LED installation record."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.installation_repo.update_fields(installation_id, **update_data)
        await self.session.commit()
        installation = await self.installation_repo.get_by_id(installation_id)
        if installation is None:
            raise ValueError(f"LED installation {installation_id} not found")
        return installation

    async def delete_installation(self, installation_id: uuid.UUID) -> None:
        """Delete an LED installation record."""
        await self.installation_repo.delete(installation_id)
        await self.session.commit()

    async def list_installations(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        installation_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDInstallation], int]:
        """List LED installation records for a project."""
        return await self.installation_repo.list_for_led_project(
            led_project_id,
            offset=offset,
            limit=limit,
            installation_type=installation_type,
            status=status,
        )

    # ── LED Milestones ───────────────────────────────────────────────────────

    async def create_milestone(
        self,
        data: LEDMilestoneCreate,
    ) -> LEDMilestone:
        """Create a new LED milestone."""
        milestone = LEDMilestone(
            led_project_id=data.led_project_id,
            name=data.name,
            milestone_type=data.milestone_type,
            description=data.description,
            planned_date=data.planned_date,
            actual_date=data.actual_date,
            status=data.status,
            linked_payment_pct=data.linked_payment_pct,
            criteria=data.criteria,
            metadata_=data.metadata,
        )
        milestone = await self.milestone_repo.create(milestone)
        logger.info("LED milestone created: %s", milestone.name)
        return milestone

    async def update_milestone(
        self,
        milestone_id: uuid.UUID,
        data: LEDMilestoneUpdate,
    ) -> LEDMilestone:
        """Update an LED milestone."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.milestone_repo.update_fields(milestone_id, **update_data)
        await self.session.commit()
        milestone = await self.milestone_repo.get_by_id(milestone_id)
        if milestone is None:
            raise ValueError(f"LED milestone {milestone_id} not found")
        return milestone

    async def delete_milestone(self, milestone_id: uuid.UUID) -> None:
        """Delete an LED milestone."""
        await self.milestone_repo.delete(milestone_id)
        await self.session.commit()

    async def list_milestones(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        milestone_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDMilestone], int]:
        """List LED milestones for a project."""
        return await self.milestone_repo.list_for_led_project(
            led_project_id,
            offset=offset,
            limit=limit,
            milestone_type=milestone_type,
            status=status,
        )

    # ── LED Maintenance Logs ─────────────────────────────────────────────────

    async def create_maintenance_log(
        self,
        data: LEDMaintenanceLogCreate,
    ) -> LEDMaintenanceLog:
        """Create a new LED maintenance log."""
        log = LEDMaintenanceLog(
            led_project_id=data.led_project_id,
            maintenance_type=data.maintenance_type,
            title=data.title,
            description=data.description,
            status=data.status,
            scheduled_date=data.scheduled_date,
            started_date=data.started_date,
            completed_date=data.completed_date,
            performed_by=data.performed_by,
            technician_id=data.technician_id,
            work_performed=data.work_performed,
            parts_replaced=data.parts_replaced,
            labor_cost=data.labor_cost,
            parts_cost=data.parts_cost,
            total_cost=data.total_cost,
            currency=data.currency,
            next_maintenance_date=data.next_maintenance_date,
            next_maintenance_type=data.next_maintenance_type,
            metadata_=data.metadata,
        )
        log = await self.maintenance_repo.create(log)
        logger.info("LED maintenance log created: %s", log.title)
        return log

    async def update_maintenance_log(
        self,
        log_id: uuid.UUID,
        data: LEDMaintenanceLogUpdate,
    ) -> LEDMaintenanceLog:
        """Update an LED maintenance log."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.maintenance_repo.update_fields(log_id, **update_data)
        await self.session.commit()
        log = await self.maintenance_repo.get_by_id(log_id)
        if log is None:
            raise ValueError(f"LED maintenance log {log_id} not found")
        return log

    async def delete_maintenance_log(self, log_id: uuid.UUID) -> None:
        """Delete an LED maintenance log."""
        await self.maintenance_repo.delete(log_id)
        await self.session.commit()

    async def list_maintenance_logs(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        maintenance_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDMaintenanceLog], int]:
        """List LED maintenance logs for a project."""
        return await self.maintenance_repo.list_for_led_project(
            led_project_id,
            offset=offset,
            limit=limit,
            maintenance_type=maintenance_type,
            status=status,
        )

    async def list_upcoming_maintenance(
        self,
        led_project_id: uuid.UUID | None = None,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[LEDMaintenanceLog], int]:
        """List upcoming maintenance."""
        return await self.maintenance_repo.list_upcoming(
            led_project_id,
            offset=offset,
            limit=limit,
        )

    # ── LED Documents ────────────────────────────────────────────────────────

    async def create_document(
        self,
        data: LEDDocumentCreate,
        user_id: str | None = None,
    ) -> LEDDocument:
        """Create a new LED document."""
        document = LEDDocument(
            led_project_id=data.led_project_id,
            name=data.name,
            document_type=data.document_type,
            description=data.description,
            file_path=data.file_path,
            file_name=data.file_name,
            file_size=data.file_size,
            mime_type=data.mime_type,
            version=data.version,
            status=data.status,
            document_date=data.document_date,
            uploaded_by=uuid.UUID(user_id) if user_id else None,
            external_url=data.external_url,
            metadata_=data.metadata,
        )
        document = await self.document_repo.create(document)
        logger.info("LED document created: %s", document.name)
        return document

    async def update_document(
        self,
        document_id: uuid.UUID,
        data: LEDDocumentUpdate,
    ) -> LEDDocument:
        """Update an LED document."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.document_repo.update_fields(document_id, **update_data)
        await self.session.commit()
        document = await self.document_repo.get_by_id(document_id)
        if document is None:
            raise ValueError(f"LED document {document_id} not found")
        return document

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """Delete an LED document."""
        await self.document_repo.delete(document_id)
        await self.session.commit()

    async def list_documents(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        document_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDDocument], int]:
        """List LED documents for a project."""
        return await self.document_repo.list_for_led_project(
            led_project_id,
            offset=offset,
            limit=limit,
            document_type=document_type,
            status=status,
        )

    # ── LED Budget ───────────────────────────────────────────────────────────

    async def create_budget(
        self,
        data: LEDBudgetCreate,
    ) -> LEDBudget:
        """Create a new LED budget entry."""
        budget = LEDBudget(
            led_project_id=data.led_project_id,
            category=data.category,
            description=data.description,
            planned_amount=data.planned_amount,
            actual_amount=data.actual_amount,
            committed_amount=data.committed_amount,
            currency=data.currency,
            status=data.status,
            breakdown=data.breakdown,
            notes=data.notes,
            metadata_=data.metadata,
        )
        budget = await self.budget_repo.create(budget)
        logger.info("LED budget created: %s - %s", budget.category, budget.planned_amount)
        return budget

    async def update_budget(
        self,
        budget_id: uuid.UUID,
        data: LEDBudgetUpdate,
    ) -> LEDBudget:
        """Update an LED budget entry."""
        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            await self.budget_repo.update_fields(budget_id, **update_data)
        await self.session.commit()
        budget = await self.budget_repo.get_by_id(budget_id)
        if budget is None:
            raise ValueError(f"LED budget {budget_id} not found")
        return budget

    async def delete_budget(self, budget_id: uuid.UUID) -> None:
        """Delete an LED budget entry."""
        await self.budget_repo.delete(budget_id)
        await self.session.commit()

    async def list_budgets(
        self,
        led_project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        status: str | None = None,
    ) -> tuple[list[LEDBudget], int]:
        """List LED budget entries for a project."""
        return await self.budget_repo.list_for_led_project(
            led_project_id,
            offset=offset,
            limit=limit,
            category=category,
            status=status,
        )