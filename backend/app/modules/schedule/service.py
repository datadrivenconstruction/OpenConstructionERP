"""Schedule service — business logic for 4D construction scheduling.

Stateless service layer. Handles:
- Schedule CRUD with project scoping
- Activity management with WBS hierarchy and BOQ linking
- Work order management
- Gantt chart data generation
- Event publishing for inter-module communication
"""

import logging
import uuid
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.schedule.models import Activity, Schedule, WorkOrder
from app.modules.schedule.repository import (
    ActivityRepository,
    ScheduleRepository,
    WorkOrderRepository,
)
from app.modules.schedule.schemas import (
    ActivityCreate,
    ActivityResponse,
    ActivityUpdate,
    GanttActivity,
    GanttData,
    GanttSummary,
    ScheduleCreate,
    ScheduleUpdate,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderUpdate,
)

logger = logging.getLogger(__name__)


def _str_to_float(value: str | None) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def compute_duration(start_date: str, end_date: str) -> int:
    """Calculate working days between two ISO date strings.

    Excludes weekends (Saturday and Sunday). If dates are invalid or
    end_date is before start_date, returns 0.

    Args:
        start_date: ISO date string (e.g. "2026-04-01").
        end_date: ISO date string (e.g. "2026-04-15").

    Returns:
        Number of working days (Mon-Fri) between start and end, inclusive.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        return 0

    if end < start:
        return 0

    working_days = 0
    current = start
    while current <= end:
        # weekday(): Monday=0, Sunday=6
        if current.weekday() < 5:
            working_days += 1
        current += timedelta(days=1)

    return working_days


class ScheduleService:
    """Business logic for Schedule, Activity, and WorkOrder operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.schedule_repo = ScheduleRepository(session)
        self.activity_repo = ActivityRepository(session)
        self.work_order_repo = WorkOrderRepository(session)

    # ── Schedule operations ────────────────────────────────────────────────

    async def create_schedule(self, data: ScheduleCreate) -> Schedule:
        """Create a new schedule.

        Args:
            data: Schedule creation payload with project_id, name, etc.

        Returns:
            The newly created schedule.
        """
        schedule = Schedule(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            status="draft",
            metadata_=data.metadata,
        )
        schedule = await self.schedule_repo.create(schedule)

        await event_bus.publish(
            "schedule.schedule.created",
            {"schedule_id": str(schedule.id), "project_id": str(data.project_id)},
            source_module="oe_schedule",
        )

        logger.info("Schedule created: %s (project=%s)", schedule.name, data.project_id)
        return schedule

    async def get_schedule(self, schedule_id: uuid.UUID) -> Schedule:
        """Get schedule by ID. Raises 404 if not found."""
        schedule = await self.schedule_repo.get_by_id(schedule_id)
        if schedule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule not found",
            )
        return schedule

    async def list_schedules_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Schedule], int]:
        """List schedules for a given project with pagination."""
        return await self.schedule_repo.list_for_project(
            project_id, offset=offset, limit=limit
        )

    async def update_schedule(
        self, schedule_id: uuid.UUID, data: ScheduleUpdate
    ) -> Schedule:
        """Update schedule metadata fields.

        Args:
            schedule_id: Target schedule identifier.
            data: Partial update payload.

        Returns:
            Updated schedule.

        Raises:
            HTTPException 404 if schedule not found.
        """
        await self.get_schedule(schedule_id)

        fields = data.model_dump(exclude_unset=True)
        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.schedule_repo.update_fields(schedule_id, **fields)

            await event_bus.publish(
                "schedule.schedule.updated",
                {"schedule_id": str(schedule_id), "fields": list(fields.keys())},
                source_module="oe_schedule",
            )

        # Re-fetch to return fresh data
        return await self.get_schedule(schedule_id)

    async def delete_schedule(self, schedule_id: uuid.UUID) -> None:
        """Delete a schedule and all its activities and work orders.

        Raises HTTPException 404 if not found.
        """
        schedule = await self.get_schedule(schedule_id)
        project_id = str(schedule.project_id)

        await self.schedule_repo.delete(schedule_id)

        await event_bus.publish(
            "schedule.schedule.deleted",
            {"schedule_id": str(schedule_id), "project_id": project_id},
            source_module="oe_schedule",
        )

        logger.info("Schedule deleted: %s", schedule_id)

    # ── Activity operations ────────────────────────────────────────────────

    async def create_activity(self, data: ActivityCreate) -> Activity:
        """Add a new activity to a schedule.

        Auto-calculates duration_days if start_date and end_date are provided.
        Assigns sort_order to place the activity at the end if not specified.

        Args:
            data: Activity creation payload.

        Returns:
            The newly created activity.

        Raises:
            HTTPException 404 if the target schedule doesn't exist.
        """
        # Verify schedule exists
        await self.get_schedule(data.schedule_id)

        # Auto-compute duration if not provided
        duration = data.duration_days
        if duration == 0 and data.start_date and data.end_date:
            duration = compute_duration(data.start_date, data.end_date)

        # Determine sort_order
        sort_order = data.sort_order
        if sort_order == 0:
            max_order = await self.activity_repo.get_max_sort_order(data.schedule_id)
            sort_order = max_order + 1

        # Serialize nested models to dicts for JSON storage
        dependencies_data = [dep.model_dump() for dep in data.dependencies]
        for dep in dependencies_data:
            dep["activity_id"] = str(dep["activity_id"])
        resources_data = [res.model_dump() for res in data.resources]
        boq_ids = [str(pid) for pid in data.boq_position_ids]

        activity = Activity(
            schedule_id=data.schedule_id,
            parent_id=data.parent_id,
            name=data.name,
            description=data.description,
            wbs_code=data.wbs_code,
            start_date=data.start_date,
            end_date=data.end_date,
            duration_days=duration,
            progress_pct=str(data.progress_pct),
            status=data.status,
            activity_type=data.activity_type,
            dependencies=dependencies_data,
            resources=resources_data,
            boq_position_ids=boq_ids,
            color=data.color,
            sort_order=sort_order,
            metadata_=data.metadata,
        )
        activity = await self.activity_repo.create(activity)

        await event_bus.publish(
            "schedule.activity.created",
            {
                "activity_id": str(activity.id),
                "schedule_id": str(data.schedule_id),
                "wbs_code": data.wbs_code,
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Activity added: %s to schedule %s", data.name, data.schedule_id
        )
        return activity

    async def get_activity(self, activity_id: uuid.UUID) -> Activity:
        """Get activity by ID. Raises 404 if not found."""
        activity = await self.activity_repo.get_by_id(activity_id)
        if activity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity not found",
            )
        return activity

    async def list_activities_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> tuple[list[Activity], int]:
        """List activities for a schedule ordered by sort_order."""
        return await self.activity_repo.list_for_schedule(
            schedule_id, offset=offset, limit=limit
        )

    async def update_activity(
        self, activity_id: uuid.UUID, data: ActivityUpdate
    ) -> Activity:
        """Update an activity and recalculate duration if dates changed.

        Args:
            activity_id: Target activity identifier.
            data: Partial update payload.

        Returns:
            Updated activity.

        Raises:
            HTTPException 404 if activity not found.
        """
        activity = await self.get_activity(activity_id)

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "progress_pct" in fields:
            fields["progress_pct"] = str(fields["progress_pct"])

        # Serialize nested models
        if "dependencies" in fields and fields["dependencies"] is not None:
            deps = fields["dependencies"]
            serialized = []
            for dep in deps:
                d = dep.model_dump() if hasattr(dep, "model_dump") else dep
                d["activity_id"] = str(d["activity_id"])
                serialized.append(d)
            fields["dependencies"] = serialized

        if "resources" in fields and fields["resources"] is not None:
            res_list = fields["resources"]
            fields["resources"] = [
                r.model_dump() if hasattr(r, "model_dump") else r for r in res_list
            ]

        if "boq_position_ids" in fields and fields["boq_position_ids"] is not None:
            fields["boq_position_ids"] = [str(pid) for pid in fields["boq_position_ids"]]

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recalculate duration if dates changed
        new_start = fields.get("start_date", activity.start_date)
        new_end = fields.get("end_date", activity.end_date)
        if "start_date" in fields or "end_date" in fields:
            fields["duration_days"] = compute_duration(new_start, new_end)

        if fields:
            await self.activity_repo.update_fields(activity_id, **fields)

            await event_bus.publish(
                "schedule.activity.updated",
                {
                    "activity_id": str(activity_id),
                    "schedule_id": str(activity.schedule_id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_schedule",
            )

        # Re-fetch to return fresh data
        return await self.get_activity(activity_id)

    async def delete_activity(self, activity_id: uuid.UUID) -> None:
        """Delete an activity.

        Raises HTTPException 404 if not found.
        """
        activity = await self.get_activity(activity_id)
        schedule_id = str(activity.schedule_id)

        await self.activity_repo.delete(activity_id)

        await event_bus.publish(
            "schedule.activity.deleted",
            {"activity_id": str(activity_id), "schedule_id": schedule_id},
            source_module="oe_schedule",
        )

        logger.info("Activity deleted: %s from schedule %s", activity_id, schedule_id)

    async def link_boq_position(
        self, activity_id: uuid.UUID, boq_position_id: uuid.UUID
    ) -> Activity:
        """Link a BOQ position to an activity.

        Args:
            activity_id: Target activity identifier.
            boq_position_id: BOQ position UUID to link.

        Returns:
            Updated activity with the new position linked.

        Raises:
            HTTPException 404 if activity not found.
            HTTPException 409 if position is already linked.
        """
        activity = await self.get_activity(activity_id)

        position_str = str(boq_position_id)
        current_ids: list[str] = list(activity.boq_position_ids or [])

        if position_str in current_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="BOQ position is already linked to this activity",
            )

        current_ids.append(position_str)
        await self.activity_repo.update_fields(activity_id, boq_position_ids=current_ids)

        await event_bus.publish(
            "schedule.activity.position_linked",
            {
                "activity_id": str(activity_id),
                "boq_position_id": position_str,
            },
            source_module="oe_schedule",
        )

        logger.info(
            "BOQ position %s linked to activity %s", boq_position_id, activity_id
        )
        return await self.get_activity(activity_id)

    async def unlink_boq_position(
        self, activity_id: uuid.UUID, boq_position_id: uuid.UUID
    ) -> Activity:
        """Unlink a BOQ position from an activity.

        Args:
            activity_id: Target activity identifier.
            boq_position_id: BOQ position UUID to unlink.

        Returns:
            Updated activity with the position removed.

        Raises:
            HTTPException 404 if activity not found or position not linked.
        """
        activity = await self.get_activity(activity_id)

        position_str = str(boq_position_id)
        current_ids: list[str] = list(activity.boq_position_ids or [])

        if position_str not in current_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ position is not linked to this activity",
            )

        current_ids.remove(position_str)
        await self.activity_repo.update_fields(activity_id, boq_position_ids=current_ids)

        await event_bus.publish(
            "schedule.activity.position_unlinked",
            {
                "activity_id": str(activity_id),
                "boq_position_id": position_str,
            },
            source_module="oe_schedule",
        )

        logger.info(
            "BOQ position %s unlinked from activity %s", boq_position_id, activity_id
        )
        return await self.get_activity(activity_id)

    async def update_progress(
        self, activity_id: uuid.UUID, progress_pct: float
    ) -> Activity:
        """Update activity progress and auto-adjust status.

        Args:
            activity_id: Target activity identifier.
            progress_pct: New progress percentage (0.0 - 100.0).

        Returns:
            Updated activity.

        Raises:
            HTTPException 404 if activity not found.
        """
        await self.get_activity(activity_id)

        # Determine status from progress
        if progress_pct >= 100.0:
            new_status = "completed"
        elif progress_pct > 0.0:
            new_status = "in_progress"
        else:
            new_status = "not_started"

        await self.activity_repo.update_fields(
            activity_id,
            progress_pct=str(progress_pct),
            status=new_status,
        )

        await event_bus.publish(
            "schedule.activity.progress_updated",
            {
                "activity_id": str(activity_id),
                "progress_pct": progress_pct,
                "status": new_status,
            },
            source_module="oe_schedule",
        )

        logger.info("Activity %s progress updated to %.1f%%", activity_id, progress_pct)
        return await self.get_activity(activity_id)

    # ── Work Order operations ──────────────────────────────────────────────

    async def create_work_order(self, data: WorkOrderCreate) -> WorkOrder:
        """Create a new work order for an activity.

        Args:
            data: Work order creation payload.

        Returns:
            The newly created work order.

        Raises:
            HTTPException 404 if the target activity doesn't exist.
        """
        # Verify activity exists
        await self.get_activity(data.activity_id)

        work_order = WorkOrder(
            activity_id=data.activity_id,
            assembly_id=data.assembly_id,
            boq_position_id=data.boq_position_id,
            code=data.code,
            description=data.description,
            assigned_to=data.assigned_to,
            planned_start=data.planned_start,
            planned_end=data.planned_end,
            actual_start=data.actual_start,
            actual_end=data.actual_end,
            planned_cost=str(data.planned_cost),
            actual_cost=str(data.actual_cost),
            status=data.status,
            metadata_=data.metadata,
        )
        work_order = await self.work_order_repo.create(work_order)

        await event_bus.publish(
            "schedule.work_order.created",
            {
                "work_order_id": str(work_order.id),
                "activity_id": str(data.activity_id),
                "code": data.code,
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Work order created: %s for activity %s", data.code, data.activity_id
        )
        return work_order

    async def get_work_order(self, work_order_id: uuid.UUID) -> WorkOrder:
        """Get work order by ID. Raises 404 if not found."""
        work_order = await self.work_order_repo.get_by_id(work_order_id)
        if work_order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work order not found",
            )
        return work_order

    async def list_work_orders_for_activity(
        self,
        activity_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[WorkOrder], int]:
        """List work orders for an activity."""
        return await self.work_order_repo.list_for_activity(
            activity_id, offset=offset, limit=limit
        )

    async def list_work_orders_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[WorkOrder], int]:
        """List all work orders across all activities in a schedule."""
        return await self.work_order_repo.list_for_schedule(
            schedule_id, offset=offset, limit=limit
        )

    async def update_work_order(
        self, work_order_id: uuid.UUID, data: WorkOrderUpdate
    ) -> WorkOrder:
        """Update a work order.

        Args:
            work_order_id: Target work order identifier.
            data: Partial update payload.

        Returns:
            Updated work order.

        Raises:
            HTTPException 404 if work order not found.
        """
        work_order = await self.get_work_order(work_order_id)

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "planned_cost" in fields:
            fields["planned_cost"] = str(fields["planned_cost"])
        if "actual_cost" in fields:
            fields["actual_cost"] = str(fields["actual_cost"])

        # Convert UUID fields to strings for GUID storage
        if "assembly_id" in fields and fields["assembly_id"] is not None:
            fields["assembly_id"] = fields["assembly_id"]
        if "boq_position_id" in fields and fields["boq_position_id"] is not None:
            fields["boq_position_id"] = fields["boq_position_id"]

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.work_order_repo.update_fields(work_order_id, **fields)

            await event_bus.publish(
                "schedule.work_order.updated",
                {
                    "work_order_id": str(work_order_id),
                    "activity_id": str(work_order.activity_id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_schedule",
            )

        # Re-fetch to return fresh data
        return await self.get_work_order(work_order_id)

    async def update_work_order_status(
        self, work_order_id: uuid.UUID, new_status: str
    ) -> WorkOrder:
        """Update work order status.

        Args:
            work_order_id: Target work order identifier.
            new_status: New status value.

        Returns:
            Updated work order.

        Raises:
            HTTPException 404 if work order not found.
        """
        work_order = await self.get_work_order(work_order_id)

        await self.work_order_repo.update_fields(work_order_id, status=new_status)

        await event_bus.publish(
            "schedule.work_order.status_changed",
            {
                "work_order_id": str(work_order_id),
                "activity_id": str(work_order.activity_id),
                "old_status": work_order.status,
                "new_status": new_status,
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Work order %s status changed: %s -> %s",
            work_order_id,
            work_order.status,
            new_status,
        )
        return await self.get_work_order(work_order_id)

    # ── Gantt chart data ───────────────────────────────────────────────────

    async def get_gantt_data(self, schedule_id: uuid.UUID) -> GanttData:
        """Build structured data for Gantt chart rendering.

        Returns all activities with their dependencies, progress, and summary
        statistics suitable for frontend Gantt visualization.

        Args:
            schedule_id: Target schedule identifier.

        Returns:
            GanttData with activities list and summary statistics.

        Raises:
            HTTPException 404 if schedule not found.
        """
        await self.get_schedule(schedule_id)

        activities, _ = await self.activity_repo.list_for_schedule(schedule_id)

        gantt_activities: list[GanttActivity] = []
        completed = 0
        in_progress = 0
        delayed = 0
        not_started = 0

        for act in activities:
            progress = _str_to_float(act.progress_pct)

            gantt_activities.append(
                GanttActivity(
                    id=act.id,
                    name=act.name,
                    start=act.start_date,
                    end=act.end_date,
                    progress=progress,
                    dependencies=act.dependencies or [],
                    parent_id=act.parent_id,
                    color=act.color,
                    boq_positions=act.boq_position_ids or [],
                    wbs_code=act.wbs_code,
                    activity_type=act.activity_type,
                    status=act.status,
                )
            )

            # Count by status
            if act.status == "completed":
                completed += 1
            elif act.status == "in_progress":
                in_progress += 1
            elif act.status == "delayed":
                delayed += 1
            else:
                not_started += 1

        summary = GanttSummary(
            total_activities=len(activities),
            completed=completed,
            in_progress=in_progress,
            delayed=delayed,
            not_started=not_started,
        )

        return GanttData(activities=gantt_activities, summary=summary)
