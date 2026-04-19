"""Schedule service — business logic for 4D construction scheduling.

Stateless service layer. Handles:
- Schedule CRUD with project scoping
- Activity management with WBS hierarchy and BOQ linking
- Work order management
- Gantt chart data generation
- CPM (Critical Path Method) calculation
- PERT risk analysis
- Generate-from-BOQ automation
- Event publishing for inter-module communication
"""

import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


def _normalize_deps(deps: list | None) -> list[dict]:
    """Normalize dependencies to list[dict].

    Seeded/legacy data may store dependencies as plain UUID strings.
    This ensures a consistent dict format for Pydantic schemas.
    """
    if not deps:
        return []
    result: list[dict] = []
    for dep in deps:
        if isinstance(dep, str):
            result.append({"activity_id": dep, "type": "FS", "lag_days": 0})
        elif isinstance(dep, dict):
            result.append(dep)
        else:
            result.append({"activity_id": str(dep), "type": "FS", "lag_days": 0})
    return result


from app.modules.schedule.models import Activity, Schedule, WorkOrder
from app.modules.schedule.repository import (
    ActivityRepository,
    ScheduleRepository,
    WorkOrderRepository,
)
from app.modules.schedule.schemas import (
    ActivityCreate,
    ActivityUpdate,
    CPMActivityResult,
    CriticalPathResponse,
    GanttActivity,
    GanttData,
    GanttSummary,
    RiskAnalysisResponse,
    ScheduleCreate,
    ScheduleUpdate,
    WorkOrderCreate,
    WorkOrderUpdate,
)

# PERT distribution factors (from DDC_Toolkit reference)
_PERT_OPTIMISTIC = 0.75
_PERT_PESSIMISTIC = 1.60

logger = logging.getLogger(__name__)


def _str_to_float(value: str | None) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ── Regional work calendar configuration ─────────────────────────────────
# Defines hours_per_day, working_days (weekday indices), and typical holidays.
# weekday(): Monday=0, Tuesday=1, ... Saturday=5, Sunday=6

WORK_CALENDARS: dict[str, dict] = {
    "DEFAULT": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Standard (Mon-Fri, 8h)",
    },
    # 1. USA — USA_USD
    "US": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "USA (Mon-Fri, 8h)",
    },
    # 2. UK — UK_GBP
    "UK": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "UK (Mon-Fri, 8h)",
    },
    # 3. Germany/DACH — DE_BERLIN
    "DACH": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Germany/DACH (Mon-Fri, 8h)",
    },
    # 4. Canada — ENG_TORONTO
    "CANADA": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Canada (Mon-Fri, 8h)",
    },
    # 5. France — FR_PARIS
    "FRANCE": {
        "hours_per_day": 7,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri (35h/week legal)
        "label": "France (Mon-Fri, 7h)",
    },
    # 6. Spain — SP_BARCELONA
    "SPAIN": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Spain (Mon-Fri, 8h)",
    },
    # 7. Brazil — PT_SAOPAULO
    "BRAZIL": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4, 5},  # Mon-Sat (44h/week legal)
        "label": "Brazil (Mon-Sat, 8h)",
    },
    # 8. Russia — RU_STPETERSBURG
    "RU": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Russia (Mon-Fri, 8h)",
    },
    # 9. UAE/Gulf — AR_DUBAI
    "GULF": {
        "hours_per_day": 10,
        "work_days": {0, 1, 2, 3, 4, 5},  # Mon-Sat
        "label": "UAE/Gulf (Mon-Sat, 10h)",
    },
    # 10. China — ZH_SHANGHAI
    "CHINA": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4, 5},  # Mon-Sat (common in construction)
        "label": "China (Mon-Sat, 8h)",
    },
    # 11. India — HI_MUMBAI
    "INDIA": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4, 5},  # Mon-Sat
        "label": "India (Mon-Sat, 8h)",
    },
}


def get_work_calendar(region: str | None = None) -> dict:
    """Get work calendar for a region. Falls back to DEFAULT."""
    if region:
        # Try exact match, then prefix match
        cal = WORK_CALENDARS.get(region.upper())
        if cal:
            return cal
        # Try matching region prefix (e.g., "DE_BERLIN" → "DACH")
        region_map = {
            # CWICR db_id prefixes → calendar keys
            "USA": "US",
            "US": "US",
            "UK": "UK",
            "GB": "UK",
            "DE": "DACH",
            "AT": "DACH",
            "CH": "DACH",
            "ENG": "CANADA",  # ENG_TORONTO
            "FR": "FRANCE",
            "SP": "SPAIN",
            "ES": "SPAIN",
            "PT": "BRAZIL",
            "BR": "BRAZIL",
            "RU": "RU",
            "AR": "GULF",
            "AE": "GULF",
            "SA": "GULF",
            "QA": "GULF",
            "ZH": "CHINA",
            "CN": "CHINA",
            "HI": "INDIA",
            "IN": "INDIA",
            # Project region values
            "DACH": "DACH",
            "GULF": "GULF",
            "NORDIC": "DACH",
            "CANADA": "CANADA",
            "FRANCE": "FRANCE",
            "SPAIN": "SPAIN",
            "BRAZIL": "BRAZIL",
            "CHINA": "CHINA",
            "INDIA": "INDIA",
        }
        prefix = region.split("_")[0].upper()
        mapped = region_map.get(prefix)
        if mapped:
            return WORK_CALENDARS.get(mapped, WORK_CALENDARS["DEFAULT"])
    return WORK_CALENDARS["DEFAULT"]


def compute_duration(start_date: str, end_date: str, region: str | None = None) -> int:
    """Calculate working days between two ISO date strings.

    Uses regional work calendar (respects different work weeks).

    Args:
        start_date: ISO date string (e.g. "2026-04-01").
        end_date: ISO date string (e.g. "2026-04-15").
        region: Optional region for work calendar (e.g. "DACH", "GULF").

    Returns:
        Number of working days between start and end, inclusive.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        return 0

    if end < start:
        return 0

    cal = get_work_calendar(region)
    work_days_set = cal["work_days"]

    working_days = 0
    current = start
    while current <= end:
        if current.weekday() in work_days_set:
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
            schedule_type=data.schedule_type,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            status="draft",
            data_date=data.data_date,
            created_by=data.created_by,
            metadata_=data.metadata,
        )
        schedule = await self.schedule_repo.create(schedule)

        await _safe_publish(
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
        return await self.schedule_repo.list_for_project(project_id, offset=offset, limit=limit)

    async def update_schedule(self, schedule_id: uuid.UUID, data: ScheduleUpdate) -> Schedule:
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

            await _safe_publish(
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

        await _safe_publish(
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

        # Auto-compute duration only when the client omitted it (sent explicit
        # null / not provided). An explicit ``duration_days=0`` is respected
        # so callers can create milestones / zero-duration events.
        duration = data.duration_days
        if duration is None and data.start_date and data.end_date:
            duration = compute_duration(data.start_date, data.end_date)
        if duration is None:
            duration = 0

        # Determine sort_order
        sort_order = data.sort_order
        if sort_order == 0:
            max_order = await self.activity_repo.get_max_sort_order(data.schedule_id)
            sort_order = max_order + 1

        # Auto-generate activity_code if not provided
        activity_code = data.activity_code
        if not activity_code:
            max_seq = await self.activity_repo.get_max_activity_code_seq(data.schedule_id)
            activity_code = f"ACT-{max_seq + 1:03d}"

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
            constraint_type=data.constraint_type,
            constraint_date=data.constraint_date,
            activity_code=activity_code,
            bim_element_ids=data.bim_element_ids,
            metadata_=data.metadata,
        )
        activity = await self.activity_repo.create(activity)

        await _safe_publish(
            "schedule.activity.created",
            {
                "activity_id": str(activity.id),
                "schedule_id": str(data.schedule_id),
                "wbs_code": data.wbs_code,
            },
            source_module="oe_schedule",
        )

        logger.info("Activity added: %s to schedule %s", data.name, data.schedule_id)
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
        return await self.activity_repo.list_for_schedule(schedule_id, offset=offset, limit=limit)

    async def update_activity(self, activity_id: uuid.UUID, data: ActivityUpdate) -> Activity:
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

        # Capture schedule_id before update_fields() calls expire_all(),
        # which would invalidate the ORM object and trigger a sync lazy-load
        # (MissingGreenlet) when accessing activity.schedule_id afterwards.
        schedule_id_str = str(activity.schedule_id)

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
            fields["resources"] = [r.model_dump() if hasattr(r, "model_dump") else r for r in res_list]

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

            await _safe_publish(
                "schedule.activity.updated",
                {
                    "activity_id": str(activity_id),
                    "schedule_id": schedule_id_str,
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

        await _safe_publish(
            "schedule.activity.deleted",
            {"activity_id": str(activity_id), "schedule_id": schedule_id},
            source_module="oe_schedule",
        )

        logger.info("Activity deleted: %s from schedule %s", activity_id, schedule_id)

    async def link_boq_position(self, activity_id: uuid.UUID, boq_position_id: uuid.UUID) -> Activity:
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

        await _safe_publish(
            "schedule.activity.position_linked",
            {
                "activity_id": str(activity_id),
                "boq_position_id": position_str,
            },
            source_module="oe_schedule",
        )

        logger.info("BOQ position %s linked to activity %s", boq_position_id, activity_id)
        return await self.get_activity(activity_id)

    async def unlink_boq_position(self, activity_id: uuid.UUID, boq_position_id: uuid.UUID) -> Activity:
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

        await _safe_publish(
            "schedule.activity.position_unlinked",
            {
                "activity_id": str(activity_id),
                "boq_position_id": position_str,
            },
            source_module="oe_schedule",
        )

        logger.info("BOQ position %s unlinked from activity %s", boq_position_id, activity_id)
        return await self.get_activity(activity_id)

    async def update_progress(self, activity_id: uuid.UUID, progress_pct: float) -> Activity:
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

        await _safe_publish(
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

    # ── BIM ↔ Activity linking ─────────────────────────────────────────────

    async def update_bim_links(
        self,
        activity_id: uuid.UUID,
        bim_element_ids: list[str],
    ) -> Activity:
        """Replace the BIM element link set on an activity.

        Args:
            activity_id: Target activity identifier.
            bim_element_ids: Full list of BIM element UUIDs (as strings) to
                store on the activity. The existing list is replaced, not
                merged.

        Returns:
            The updated activity (re-fetched from the database).

        Raises:
            HTTPException 404 if the activity does not exist.
        """
        activity = await self.get_activity(activity_id)
        schedule_id_str = str(activity.schedule_id)

        # Normalise to a list of plain strings so we never write a dict to
        # the JSON column (legacy values may have been dict-shaped).
        normalised = [str(eid) for eid in bim_element_ids]

        await self.activity_repo.update_fields(
            activity_id,
            bim_element_ids=normalised,
        )

        await _safe_publish(
            "schedule.activity.bim_links_updated",
            {
                "activity_id": str(activity_id),
                "schedule_id": schedule_id_str,
                "bim_element_ids": normalised,
                "count": len(normalised),
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Activity %s BIM links replaced (%d element(s))",
            activity_id,
            len(normalised),
        )
        return await self.get_activity(activity_id)

    async def get_activities_for_bim_element(
        self,
        bim_element_id: str,
        project_id: uuid.UUID,
    ) -> list[Activity]:
        """Return all activities in ``project_id`` that reference ``bim_element_id``.

        The ``bim_element_ids`` JSON column is stored as a plain list so we
        filter on the Python side (works across SQLite and PostgreSQL without
        a dialect-specific JSON contains operator). Scoping by project keeps
        the scan bounded.
        """
        target = str(bim_element_id)

        stmt = (
            select(Activity)
            .join(Schedule, Activity.schedule_id == Schedule.id)
            .where(Schedule.project_id == project_id)
            .where(Activity.bim_element_ids.isnot(None))
            .options(
                noload(Activity.children),
                noload(Activity.work_orders),
            )
            .order_by(Activity.sort_order, Activity.wbs_code)
        )
        result = await self.session.execute(stmt)
        candidates = list(result.scalars().all())

        matched: list[Activity] = []
        for act in candidates:
            raw = act.bim_element_ids
            # Legacy dict-shaped values are treated as empty.
            if isinstance(raw, list):
                if target in (str(eid) for eid in raw):
                    matched.append(act)
        return matched

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

        await _safe_publish(
            "schedule.work_order.created",
            {
                "work_order_id": str(work_order.id),
                "activity_id": str(data.activity_id),
                "code": data.code,
            },
            source_module="oe_schedule",
        )

        logger.info("Work order created: %s for activity %s", data.code, data.activity_id)
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
        return await self.work_order_repo.list_for_activity(activity_id, offset=offset, limit=limit)

    async def list_work_orders_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[WorkOrder], int]:
        """List all work orders across all activities in a schedule."""
        return await self.work_order_repo.list_for_schedule(schedule_id, offset=offset, limit=limit)

    async def update_work_order(self, work_order_id: uuid.UUID, data: WorkOrderUpdate) -> WorkOrder:
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

            await _safe_publish(
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

    async def update_work_order_status(self, work_order_id: uuid.UUID, new_status: str) -> WorkOrder:
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

        await _safe_publish(
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

            duration = 0
            try:
                from datetime import datetime as _dt

                d1 = _dt.fromisoformat(str(act.start_date))
                d2 = _dt.fromisoformat(str(act.end_date))
                duration = (d2 - d1).days
            except Exception:
                duration = int(_str_to_float(act.duration_days)) if act.duration_days else 0

            gantt_activities.append(
                GanttActivity(
                    id=act.id,
                    name=act.name,
                    start_date=str(act.start_date),
                    end_date=str(act.end_date),
                    duration_days=duration,
                    progress_pct=progress,
                    dependencies=_normalize_deps(act.dependencies),
                    parent_id=act.parent_id,
                    color=act.color,
                    boq_position_ids=act.boq_position_ids or [],
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

    # ── Generate from BOQ ─────────────────────────────────────────────────

    async def generate_from_boq(
        self,
        schedule_id: uuid.UUID,
        boq_id: uuid.UUID,
        total_project_days: int | None = None,
    ) -> list[Activity]:
        """Generate hierarchical schedule activities from BOQ sections.

        Reads all positions from the specified BOQ, creates SUMMARY activities
        for top-level sections and TASK activities for child positions. Uses
        quantity-based production rates for duration calculation, working-day
        calendar (excludes weekends), smart dependencies (sequential within
        section, overlapping between sections), and milestone markers.

        Args:
            schedule_id: Target schedule to populate.
            boq_id: Source BOQ to read sections from.
            total_project_days: Override total project duration in calendar days.
                If None, defaults to 365 (residential) or 540 (office).

        Returns:
            List of created Activity ORM objects.

        Raises:
            HTTPException 404 if schedule or BOQ not found.
            HTTPException 409 if schedule already has activities.
        """
        schedule = await self.get_schedule(schedule_id)
        schedule_project_id = schedule.project_id  # Save before expire
        schedule_start_date = schedule.start_date

        # Check schedule doesn't already have activities
        existing, count = await self.activity_repo.list_for_schedule(schedule_id, limit=1)
        if count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Schedule already has activities. Delete them first to regenerate.",
            )

        # Fetch BOQ with positions
        from app.modules.boq.repository import BOQRepository, PositionRepository

        boq_repo = BOQRepository(self.session)
        pos_repo = PositionRepository(self.session)

        boq = await boq_repo.get_by_id(boq_id)
        if boq is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ not found",
            )

        raw_positions, _ = await pos_repo.list_for_boq(boq_id, limit=5000)
        # Force-load all attributes in session context to prevent MissingGreenlet
        for p in raw_positions:
            _ = p.id, p.parent_id, p.ordinal, p.description, p.unit
            _ = p.quantity, p.unit_rate, p.total, p.metadata_
        if not raw_positions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ has no positions",
            )

        # Eagerly snapshot all needed fields to avoid lazy-loading / greenlet issues.
        # Access every attribute while still inside the async session context.
        positions = []
        for p in raw_positions:
            # metadata_ uses SQL alias "metadata" — access carefully
            try:
                meta = dict(p.metadata_) if p.metadata_ else {}
            except Exception:
                meta = {}
            positions.append(
                {
                    "id": p.id,
                    "parent_id": p.parent_id,
                    "ordinal": p.ordinal or "",
                    "description": p.description or "",
                    "unit": p.unit or "",
                    "quantity": p.quantity or "0",
                    "unit_rate": p.unit_rate or "0",
                    "total": p.total or "0",
                    "metadata_": meta,
                }
            )

        # Determine project duration
        if total_project_days is None:
            boq_meta = boq.metadata_ or {}
            building_type = boq_meta.get("building_type", "residential")
            total_project_days = 540 if building_type == "office" else 365

        # ── Get regional work calendar from project ──────────────────────
        # Fetch project to get region for work calendar
        from app.modules.projects.repository import ProjectRepository

        proj_repo = ProjectRepository(self.session)
        project = await proj_repo.get_by_id(schedule_project_id)
        project_region = project.region if project else None
        cal = get_work_calendar(project_region)
        hours_per_day = cal["hours_per_day"]
        work_days_set = cal["work_days"]
        work_days_per_week = len(work_days_set)
        logger.info(
            "Using work calendar: %s (%.1fh/day, %d days/week)", cal["label"], hours_per_day, work_days_per_week
        )

        # ── Duration calculation from real labor data ──────────────────
        # Priority:
        #   1. labor_hours & workers_per_unit from position metadata
        #   2. Sum labor-type resources from position metadata
        #   3. Cost-proportional fallback

        def _calc_duration_from_resources(
            pos_meta: dict,
            quantity: float,
            total_cost: float,
            grand_total: float,
            total_days: int,
        ) -> int:
            """Calculate calendar days from labor_hours and workers.

            Uses regional work calendar for hours_per_day and work_days_per_week.
            """
            # ── Try 1: explicit labor_hours + workers_per_unit in metadata ──
            labor_hours = pos_meta.get("labor_hours", 0)
            workers = pos_meta.get("workers_per_unit", 0)

            if labor_hours > 0 and quantity > 0:
                total_hours = quantity * labor_hours
                crew_hours_per_day = max(workers, 1) * hours_per_day
                working_days = total_hours / crew_hours_per_day
                # Add 10% for mobilization / demobilization
                cal_days = working_days * 1.1
                # Convert working days → calendar days
                cal_days = cal_days * 7 / work_days_per_week
                return max(1, min(int(round(cal_days)), total_days))

            # ── Try 2: sum labor-type resources stored in metadata ──────────
            resources = pos_meta.get("resources", [])
            if resources and quantity > 0:
                labor_hrs_per_unit = 0.0
                for res in resources:
                    res_type = (res.get("type") or "").lower()
                    res_unit = (res.get("unit") or "").lower()
                    if res_type in ("labor", "operator") or "hrs" in res_unit or "hours" in res_unit:
                        labor_hrs_per_unit += res.get("quantity", 0)
                if labor_hrs_per_unit > 0:
                    total_hours = quantity * labor_hrs_per_unit
                    crew_size = max(
                        sum(1 for r in resources if (r.get("type") or "").lower() in ("labor", "operator")),
                        1,
                    )
                    crew_hours_per_day = crew_size * hours_per_day
                    working_days = total_hours / crew_hours_per_day
                    cal_days = working_days * 1.1 * 7 / work_days_per_week
                    return max(1, min(int(round(cal_days)), total_days))

            # ── Try 3: cost-proportional fallback ───────────────────────────
            if total_cost > 0 and grand_total > 0:
                proportion = total_cost / grand_total
                return max(1, round(proportion * total_days))

            return 3  # minimum default

        def _add_working_days(start: date, working_days: int) -> date:
            """Advance a date by N working days, using regional calendar."""
            current = start
            added = 0
            while added < working_days:
                current += timedelta(days=1)
                if current.weekday() in work_days_set:
                    added += 1
            return current

        def _working_days_between(start: date, end: date) -> int:
            """Count working days between two dates, using regional calendar."""
            count = 0
            current = start
            while current < end:
                current += timedelta(days=1)
                if current.weekday() in work_days_set:
                    count += 1
            return count

        # ── Identify section headers and children ────────────────────────
        top_level = [p for p in positions if p["parent_id"] is None]

        # Build child map: parent_id_str -> list of child position dicts
        child_map: dict[str, list[dict]] = {}
        for p in positions:
            if p["parent_id"] is not None:
                parent_str = str(p["parent_id"])
                if parent_str not in child_map:
                    child_map[parent_str] = []
                child_map[parent_str].append(p)

        # Build sections with their children
        sections: list[dict] = []
        for pos in top_level:
            pos_id_str = str(pos["id"])
            children = child_map.get(pos_id_str, [])
            if children:
                section_total = sum(_str_to_float(c["total"]) for c in children)
            else:
                section_total = _str_to_float(pos["total"])

            sections.append(
                {
                    "name": pos["description"][:255] if pos["description"] else f"Section {pos['ordinal']}",
                    "ordinal": pos["ordinal"],
                    "total": section_total,
                    "parent_position": pos,
                    "children": children if children else [pos],
                }
            )

        if not sections:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No sections found in BOQ",
            )

        # Compute grand total for cost-proportional fallback
        grand_total = sum(s["total"] for s in sections)
        if grand_total <= 0:
            grand_total = 1.0  # avoid division by zero

        # ── Determine schedule start date ────────────────────────────────
        schedule_start_str = schedule.start_date
        if schedule_start_str:
            try:
                schedule_start = date.fromisoformat(schedule_start_str)
            except (ValueError, TypeError):
                schedule_start = date.today()
        else:
            schedule_start = date.today()

        # ── Create hierarchical activities ───────────────────────────────
        created_activities: list[Activity] = []
        sort_counter = 0

        # Track previous section for inter-section SS dependencies
        prev_section_summary_id: uuid.UUID | None = None
        prev_section_duration_work_days: int = 0

        # Track per-section data for summary rollup
        summary_activity_map: dict[uuid.UUID, list[Activity]] = {}

        # Current date cursor for section starts
        section_start = schedule_start

        for section_idx, section in enumerate(sections):
            # ── Create SUMMARY activity (placeholder dates, updated later) ──
            sort_counter += 1
            summary = Activity(
                schedule_id=schedule_id,
                parent_id=None,
                name=section["name"],
                description=f"Summary: BOQ section {section['ordinal']}",
                wbs_code=section["ordinal"],
                start_date=section_start.isoformat(),
                end_date=section_start.isoformat(),  # placeholder
                duration_days=0,  # placeholder — computed from children
                progress_pct="0",
                status="not_started",
                activity_type="summary",
                dependencies=[],
                resources=[],
                boq_position_ids=[],
                color="#1e40af",
                sort_order=sort_counter,
                metadata_={"source": "boq_generation", "boq_id": str(boq_id)},
            )
            summary = await self.activity_repo.create(summary)
            summary_id = summary.id  # Save ID before any expire_all
            created_activities.append(
                {
                    "activity_type": "summary",
                    "end_date": summary.end_date,
                    "id": summary_id,
                }
            )
            summary_activity_map[summary_id] = []

            # Inter-section dependency: SS with lag = 50% of previous section
            if prev_section_summary_id is not None:
                lag = max(3, prev_section_duration_work_days // 2)
                summary_deps = [
                    {
                        "activity_id": str(prev_section_summary_id),
                        "type": "SS",
                        "lag_days": lag,
                    }
                ]
                await self.activity_repo.update_fields(
                    summary_id,
                    dependencies=summary_deps,
                )

            # ── Create TASK activities for each child position ───────────
            child_start = section_start
            prev_child_id: uuid.UUID | None = None
            section_work_days_total = 0

            for child_idx, child_pos in enumerate(section["children"]):
                child_quantity = _str_to_float(child_pos["quantity"])
                child_unit = child_pos["unit"] or ""
                child_total = _str_to_float(child_pos["total"])
                child_meta = child_pos.get("metadata_", {}) or {}

                duration_cal = _calc_duration_from_resources(
                    child_meta,
                    child_quantity,
                    child_total,
                    grand_total,
                    total_project_days,
                )
                # Convert calendar days to working days for date arithmetic
                work_days = max(1, math.ceil(duration_cal * 5 / 7))
                section_work_days_total += work_days

                child_end = _add_working_days(child_start, work_days)

                # Within-section dependency: sequential FS
                child_deps: list[dict] = []
                if prev_child_id is not None:
                    child_deps = [
                        {
                            "activity_id": str(prev_child_id),
                            "type": "FS",
                            "lag_days": 0,
                        }
                    ]

                sort_counter += 1
                child_name = (
                    child_pos["description"][:255] if child_pos["description"] else f"Position {child_pos['ordinal']}"
                )
                child_activity = Activity(
                    schedule_id=schedule_id,
                    parent_id=summary_id,
                    name=child_name,
                    description=(
                        f"Auto-generated from BOQ position {child_pos['ordinal']} ({child_quantity} {child_unit})"
                    ),
                    wbs_code=child_pos["ordinal"] or f"{section['ordinal']}.{child_idx + 1:03d}",
                    start_date=child_start.isoformat(),
                    end_date=child_end.isoformat(),
                    duration_days=duration_cal,
                    progress_pct="0",
                    status="not_started",
                    activity_type="task",
                    dependencies=child_deps,
                    resources=[],
                    boq_position_ids=[str(child_pos["id"])],
                    color="#0071e3",
                    sort_order=sort_counter,
                    metadata_={
                        "source": "boq_generation",
                        "boq_id": str(boq_id),
                        "quantity": child_quantity,
                        "unit": child_unit,
                        "labor_hours": child_meta.get("labor_hours", 0),
                        "workers_per_unit": child_meta.get("workers_per_unit", 0),
                        "duration_method": (
                            "labor_hours"
                            if child_meta.get("labor_hours", 0) > 0
                            else ("resource_sum" if child_meta.get("resources") else "cost_proportional")
                        ),
                    },
                )
                child_activity = await self.activity_repo.create(child_activity)
                child_activity_id = child_activity.id  # Save before expire
                child_activity_start = child_activity.start_date
                child_activity_end = child_activity.end_date
                created_activities.append(
                    {
                        "activity_type": "task",
                        "end_date": child_activity_end,
                        "id": child_activity_id,
                    }
                )
                # Store as dict to avoid ORM lazy-loading issues
                summary_activity_map[summary_id].append(
                    {
                        "id": child_activity_id,
                        "start_date": child_activity_start,
                        "end_date": child_activity_end,
                    }
                )

                prev_child_id = child_activity_id
                child_start = child_end  # next child starts after this one ends

            # ── Update SUMMARY dates from children (rollup) ─────────────
            children_data = summary_activity_map[summary_id]
            if children_data:
                earliest_start = min(date.fromisoformat(a["start_date"]) for a in children_data)
                latest_end = max(date.fromisoformat(a["end_date"]) for a in children_data)
                summary_duration = (latest_end - earliest_start).days
                await self.activity_repo.update_fields(
                    summary_id,
                    start_date=earliest_start.isoformat(),
                    end_date=latest_end.isoformat(),
                    duration_days=max(1, summary_duration),
                    boq_position_ids=[str(c["id"]) for c in section["children"]],
                )

            prev_section_summary_id = summary_id
            prev_section_duration_work_days = section_work_days_total

            # Next section start: overlap via SS — section_start advances by
            # half the previous section's working days for partial overlap
            if children_data:
                latest_end = max(date.fromisoformat(a["end_date"]) for a in children_data)
                half_work_days = max(3, section_work_days_total // 2)
                section_start = _add_working_days(section_start, half_work_days)
            else:
                section_start = child_start

        # ── Add project milestones ───────────────────────────────────────
        # Milestone: Project Start
        sort_counter += 1
        ms_start = Activity(
            schedule_id=schedule_id,
            parent_id=None,
            name="Project Start",
            description="Project kick-off milestone",
            wbs_code="MS-001",
            start_date=schedule_start.isoformat(),
            end_date=schedule_start.isoformat(),
            duration_days=0,
            progress_pct="0",
            status="not_started",
            activity_type="milestone",
            dependencies=[],
            resources=[],
            boq_position_ids=[],
            color="#f59e0b",
            sort_order=0,  # first item
            metadata_={"source": "boq_generation", "boq_id": str(boq_id)},
        )
        ms_start = await self.activity_repo.create(ms_start)
        ms_start_end = ms_start.end_date
        created_activities.append(
            {
                "activity_type": "milestone",
                "end_date": ms_start_end,
            }
        )

        # Milestone: Project Completion (depends on last section finishing)
        if prev_section_summary_id is not None:
            # Find the latest end date across all activities
            all_end_dates = []
            for act_info in created_activities:
                atype = act_info.get("activity_type", "task") if isinstance(act_info, dict) else "task"
                aend = act_info.get("end_date", "") if isinstance(act_info, dict) else ""
                if atype != "milestone" and aend:
                    try:
                        all_end_dates.append(date.fromisoformat(aend))
                    except (ValueError, TypeError):
                        pass
            project_end = max(all_end_dates) if all_end_dates else schedule_start

            sort_counter += 1
            ms_end = Activity(
                schedule_id=schedule_id,
                parent_id=None,
                name="Project Completion",
                description="Project completion milestone",
                wbs_code="MS-999",
                start_date=project_end.isoformat(),
                end_date=project_end.isoformat(),
                duration_days=0,
                progress_pct="0",
                status="not_started",
                activity_type="milestone",
                dependencies=[
                    {
                        "activity_id": str(prev_section_summary_id),
                        "type": "FS",
                        "lag_days": 0,
                    }
                ],
                resources=[],
                boq_position_ids=[],
                color="#f59e0b",
                sort_order=sort_counter,
                metadata_={"source": "boq_generation", "boq_id": str(boq_id)},
            )
            ms_end = await self.activity_repo.create(ms_end)
            ms_end_date = ms_end.end_date
            created_activities.append({"activity_type": "milestone", "end_date": ms_end_date})

        # ── Update schedule dates ────────────────────────────────────────
        if created_activities:
            all_end_dates = []
            for act_info in created_activities:
                aend = act_info.get("end_date", "") if isinstance(act_info, dict) else ""
                if aend:
                    try:
                        all_end_dates.append(date.fromisoformat(aend))
                    except (ValueError, TypeError):
                        pass
            if all_end_dates:
                final_end = max(all_end_dates).isoformat()
                await self.schedule_repo.update_fields(schedule_id, end_date=final_end)
            # Always set start_date (schedule object may be expired by now)
            await self.schedule_repo.update_fields(schedule_id, start_date=schedule_start.isoformat())

        await _safe_publish(
            "schedule.generated_from_boq",
            {
                "schedule_id": str(schedule_id),
                "boq_id": str(boq_id),
                "activities_created": len(created_activities),
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Generated %d activities from BOQ %s for schedule %s",
            len(created_activities),
            boq_id,
            schedule_id,
        )
        return created_activities

    # ── Critical Path Method ──────────────────────────────────────────────

    async def calculate_critical_path(self, schedule_id: uuid.UUID) -> CriticalPathResponse:
        """Calculate the critical path using forward/backward pass CPM.

        Algorithm adapted from DDC_Toolkit _compute_cpm:
        - Forward pass: compute Early Start (ES) and Early Finish (EF) for each activity
        - Backward pass: compute Late Start (LS) and Late Finish (LF)
        - Total Float = LS - ES
        - Critical path = activities where Total Float = 0

        Supports FS (Finish-to-Start) and SS (Start-to-Start) dependency types.
        Results are stored in each activity's metadata for later retrieval.

        Args:
            schedule_id: Target schedule to analyze.

        Returns:
            CriticalPathResponse with all CPM data and the critical path.

        Raises:
            HTTPException 404 if schedule not found or has no activities.
        """
        await self.get_schedule(schedule_id)

        activities, count = await self.activity_repo.list_for_schedule(schedule_id)
        if count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule has no activities",
            )

        # Snapshot all activity data to avoid MissingGreenlet after expire_all
        act_data: list[dict] = []
        for a in activities:
            act_data.append(
                {
                    "id": str(a.id),
                    "name": a.name or "",
                    "duration_days": a.duration_days or 0,
                    "activity_type": a.activity_type or "task",
                    "dependencies": _normalize_deps(a.dependencies),
                    "color": a.color or "#0071e3",
                }
            )

        # Build activity index and dependency map
        idx: dict[str, dict] = {d["id"]: d for d in act_data}
        active_ids = set(idx.keys())

        # Parse dependencies: map activity_id -> list of (predecessor_id, type, lag)
        deps: dict[str, list[tuple[str, str, int]]] = {d["id"]: [] for d in act_data}

        # 1. Load explicit ScheduleRelationship records from the database
        from sqlalchemy import select

        from app.modules.schedule.models import ScheduleRelationship

        rel_stmt = select(ScheduleRelationship).where(
            ScheduleRelationship.schedule_id == schedule_id
        )
        rel_result = await self.session.execute(rel_stmt)
        seen_pairs: set[tuple[str, str]] = set()
        for r in rel_result.scalars().all():
            pred_id = str(r.predecessor_id)
            succ_id = str(r.successor_id)
            if pred_id in active_ids and succ_id in active_ids:
                deps[succ_id].append((pred_id, r.relationship_type or "FS", r.lag_days or 0))
                seen_pairs.add((pred_id, succ_id))

        # 2. Inline JSON dependencies from each activity (deduplicate against DB)
        for ad in act_data:
            act_id = ad["id"]
            for dep in ad["dependencies"]:
                pred_id = str(dep.get("activity_id", ""))
                dep_type = dep.get("type", "FS")
                lag = dep.get("lag_days", 0)
                if pred_id in active_ids and (pred_id, act_id) not in seen_pairs:
                    deps[act_id].append((pred_id, dep_type, lag))
                    seen_pairs.add((pred_id, act_id))

        # --- Topological sort (Kahn's algorithm) ---
        # The forward/backward passes must visit each activity AFTER all of its
        # predecessors. Iterating in raw DB order is unsafe: if a successor is
        # listed before its predecessor, the forward pass would read ef.get(pred)
        # as the fallback (0 + pred_dur) and produce wrong CPM dates. We also
        # detect cycles here so we never silently return nonsense.
        from collections import defaultdict, deque

        adj: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {d["id"]: 0 for d in act_data}
        for succ_id, preds in deps.items():
            for pred_id, _dep_type, _lag in preds:
                adj[pred_id].append(succ_id)
                in_degree[succ_id] += 1

        queue: deque[str] = deque(
            [d["id"] for d in act_data if in_degree[d["id"]] == 0]
        )
        sorted_ids: list[str] = []
        while queue:
            nid = queue.popleft()
            sorted_ids.append(nid)
            for succ in adj[nid]:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(sorted_ids) < len(act_data):
            unsorted_ids = [d["id"] for d in act_data if d["id"] not in set(sorted_ids)]
            unsorted_names = [idx[aid]["name"] or aid for aid in unsorted_ids[:5]]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Schedule has a dependency cycle. Affected activities: "
                    + ", ".join(unsorted_names)
                ),
            )

        sorted_act_data: list[dict] = [idx[aid] for aid in sorted_ids]

        # --- Forward pass: compute ES, EF ---
        # Supports all 4 dependency types per PMBOK:
        #   FS (Finish-to-Start): successor starts after predecessor finishes (+lag)
        #   SS (Start-to-Start):  successor starts after predecessor starts (+lag)
        #   FF (Finish-to-Finish): successor finishes after predecessor finishes (+lag)
        #   SF (Start-to-Finish): successor finishes after predecessor starts (+lag)
        es: dict[str, int] = {}
        ef: dict[str, int] = {}
        for ad in sorted_act_data:
            act_id = ad["id"]
            dur = ad["duration_days"]
            act_es = 0
            for pred_id, dep_type, lag in deps[act_id]:
                dep_type = (dep_type or "FS").upper()
                pred_dur = idx[pred_id]["duration_days"]
                pred_ef = ef.get(pred_id, pred_dur)
                pred_es = es.get(pred_id, 0)
                if dep_type == "FS":
                    candidate = pred_ef + lag
                elif dep_type == "SS":
                    candidate = pred_es + lag
                elif dep_type == "FF":
                    # Successor finish ≥ predecessor finish + lag → ES = EF_succ - dur
                    candidate = pred_ef + lag - dur
                elif dep_type == "SF":
                    # Successor finish ≥ predecessor start + lag → ES = SF - dur
                    candidate = pred_es + lag - dur
                else:
                    logger.warning(
                        "Unknown dependency type '%s' on activity %s; treating as FS",
                        dep_type, act_id,
                    )
                    candidate = pred_ef + lag
                act_es = max(act_es, candidate)
            es[act_id] = act_es
            ef[act_id] = act_es + dur

        # Project duration
        project_duration = max(ef.values()) if ef else 0

        # --- Backward pass: compute LS, LF ---
        successors: dict[str, list[tuple[str, str, int]]] = {d["id"]: [] for d in act_data}
        for ad in act_data:
            act_id = ad["id"]
            for pred_id, dep_type, lag in deps[act_id]:
                successors[pred_id].append((act_id, dep_type, lag))

        lf: dict[str, int] = {d["id"]: project_duration for d in act_data}
        ls: dict[str, int] = {}

        for ad in reversed(sorted_act_data):
            act_id = ad["id"]
            dur = ad["duration_days"]
            for succ_id, dep_type, lag in successors.get(act_id, []):
                dep_type = (dep_type or "FS").upper()
                succ_ls = ls.get(succ_id, project_duration)
                succ_lf = lf.get(succ_id, project_duration)
                if dep_type == "FS":
                    # pred LF ≤ succ LS - lag
                    lf[act_id] = min(lf[act_id], succ_ls - lag)
                elif dep_type == "SS":
                    # pred LS ≤ succ LS - lag → LF = LS_succ - lag + dur
                    lf[act_id] = min(lf[act_id], succ_ls - lag + dur)
                elif dep_type == "FF":
                    # pred LF ≤ succ LF - lag
                    lf[act_id] = min(lf[act_id], succ_lf - lag)
                elif dep_type == "SF":
                    # pred LS ≤ succ LF - lag → LF = LF_succ - lag + dur
                    lf[act_id] = min(lf[act_id], succ_lf - lag + dur)
                else:
                    logger.warning(
                        "Unknown dependency type '%s' on backward pass %s → %s; treating as FS",
                        dep_type, act_id, succ_id,
                    )
                    lf[act_id] = min(lf[act_id], succ_ls - lag)
            ls[act_id] = lf[act_id] - dur

        # --- Compute float and identify critical path ---
        all_results: list[CPMActivityResult] = []
        critical_results: list[CPMActivityResult] = []

        for ad in act_data:
            act_id = ad["id"]
            total_float = ls[act_id] - es[act_id]
            is_critical = total_float <= 0

            result = CPMActivityResult(
                activity_id=uuid.UUID(act_id),
                name=ad["name"],
                duration_days=ad["duration_days"],
                early_start=es[act_id],
                early_finish=ef[act_id],
                late_start=ls[act_id],
                late_finish=lf[act_id],
                total_float=total_float,
                is_critical=is_critical,
            )
            all_results.append(result)
            if is_critical:
                critical_results.append(result)

            # Update activity color + CPM metadata — persist so the frontend
            # can display ES/EF/LS/LF/float on next load without re-running CPM.
            cpm_meta = {
                "es": es[act_id],
                "ef": ef[act_id],
                "ls": ls[act_id],
                "lf": lf[act_id],
                "total_float": total_float,
                "is_critical": is_critical,
                "calculated_at": datetime.now(UTC).isoformat(),
            }
            new_color = "#ef4444" if is_critical else "#0071e3"
            # Merge cpm into existing metadata_ so we don't clobber user-set keys
            activity = idx.get(act_id)
            existing_meta = {}
            if activity:
                raw_meta = activity.get("metadata_") or activity.get("metadata") or {}
                if isinstance(raw_meta, dict):
                    existing_meta = dict(raw_meta)
            existing_meta["cpm"] = cpm_meta
            await self.activity_repo.update_fields(
                uuid.UUID(act_id),
                color=new_color,
                metadata_=existing_meta,
            )

        await _safe_publish(
            "schedule.cpm.calculated",
            {
                "schedule_id": str(schedule_id),
                "project_duration": project_duration,
                "critical_count": len(critical_results),
            },
            source_module="oe_schedule",
        )

        logger.info(
            "CPM calculated for schedule %s: duration=%d, critical=%d/%d",
            schedule_id,
            project_duration,
            len(critical_results),
            len(all_results),
        )

        return CriticalPathResponse(
            schedule_id=schedule_id,
            project_duration_days=project_duration,
            critical_path=critical_results,
            all_activities=all_results,
        )

    # ── Risk Analysis (PERT) ──────────────────────────────────────────────

    async def get_risk_analysis(self, schedule_id: uuid.UUID) -> RiskAnalysisResponse:
        """Compute PERT-based risk analysis for the schedule.

        Uses the three-point estimation:
        - Optimistic (O) = duration * 0.75
        - Most Likely (M) = duration (as planned)
        - Pessimistic (P) = duration * 1.60

        Expected = (O + 4*M + P) / 6
        Variance per task = ((P - O) / 6)^2

        For the critical path: sums variances, computes standard deviation,
        and derives P50, P80, P95 percentiles using normal distribution
        approximation (Central Limit Theorem).

        Args:
            schedule_id: Target schedule to analyze.

        Returns:
            RiskAnalysisResponse with PERT estimates.

        Raises:
            HTTPException 404 if schedule not found or has no activities.
        """
        # First ensure CPM has been calculated (need critical path)
        cpm_result = await self.calculate_critical_path(schedule_id)

        det_days = cpm_result.project_duration_days

        # Compute per-activity PERT estimates
        activity_risks: list[dict] = []
        critical_variance_sum = 0.0

        for act_cpm in cpm_result.all_activities:
            duration = act_cpm.duration_days
            optimistic = max(3, int(duration * _PERT_OPTIMISTIC))
            pessimistic = max(duration + 2, int(duration * _PERT_PESSIMISTIC))
            expected = (optimistic + 4 * duration + pessimistic) / 6.0
            std_dev = (pessimistic - optimistic) / 6.0
            variance = std_dev**2

            activity_risks.append(
                {
                    "activity_id": str(act_cpm.activity_id),
                    "name": act_cpm.name,
                    "duration_days": duration,
                    "optimistic": optimistic,
                    "most_likely": duration,
                    "pessimistic": pessimistic,
                    "expected": round(expected, 1),
                    "std_dev": round(std_dev, 2),
                    "is_critical": act_cpm.is_critical,
                }
            )

            if act_cpm.is_critical:
                critical_variance_sum += variance

        # Project-level PERT estimates (sum of critical path variances)
        project_std = math.sqrt(critical_variance_sum)

        # Normal distribution percentiles: z_50=0, z_80=0.84, z_95=1.645
        p50_days = det_days  # median = deterministic for symmetric approx
        p80_days = int(det_days + 0.84 * project_std)
        p95_days = int(det_days + 1.645 * project_std)
        mean_days = round(
            sum(r["expected"] for r in activity_risks if r["is_critical"]),
            1,
        )
        risk_buffer = p80_days - det_days

        logger.info(
            "PERT risk analysis for schedule %s: P50=%d, P80=%d, P95=%d (buffer=%d)",
            schedule_id,
            p50_days,
            p80_days,
            p95_days,
            risk_buffer,
        )

        return RiskAnalysisResponse(
            schedule_id=schedule_id,
            deterministic_days=det_days,
            p50_days=p50_days,
            p80_days=p80_days,
            p95_days=p95_days,
            mean_days=mean_days,
            std_dev_days=round(project_std, 1),
            risk_buffer_days=risk_buffer,
            activity_risks=activity_risks,
        )

    # ── Project Intelligence (RFC 25) ──────────────────────────────────────

    async def get_labor_cost_by_phase(self, project_id: uuid.UUID):
        """Roll up labour cost per schedule phase (RFC 25)."""
        from sqlalchemy import select as _select

        from app.modules.boq.models import Position
        from app.modules.schedule.models import Activity, Schedule
        from app.modules.schedule.schemas import (
            LaborCostByPhaseResponse,
            LaborCostByPhaseRow,
        )

        stmt = (
            _select(Activity)
            .join(Schedule, Activity.schedule_id == Schedule.id)
            .where(Schedule.project_id == project_id)
        )
        result = await self.session.execute(stmt)
        activities: list[Activity] = list(result.scalars().all())

        if not activities:
            return LaborCostByPhaseResponse()

        # Gather linked BOQ position ids for aggregate lookup
        all_boq_ids: list[uuid.UUID] = []
        for act in activities:
            for pid in act.boq_position_ids or []:
                try:
                    all_boq_ids.append(uuid.UUID(str(pid)))
                except (TypeError, ValueError):
                    continue

        position_totals: dict[uuid.UUID, float] = {}
        if all_boq_ids:
            pos_stmt = _select(Position.id, Position.total).where(
                Position.id.in_(all_boq_ids)
            )
            pos_result = await self.session.execute(pos_stmt)
            for pid, total in pos_result.all():
                position_totals[pid] = _str_to_float(total)

        phases: dict[str, dict[str, object]] = {}
        for act in activities:
            wbs = (act.wbs_code or "").strip()
            if wbs:
                phase = wbs.split(".")[0]
            else:
                phase = (act.activity_type or "task").strip() or "task"

            labour = 0.0
            for resource in act.resources or []:
                if not isinstance(resource, dict):
                    continue
                if resource.get("type") != "labor":
                    continue
                tc = resource.get("total_cost")
                if tc not in (None, "", 0):
                    labour += _str_to_float(tc)
                else:
                    units = _str_to_float(resource.get("units"))
                    rate = _str_to_float(resource.get("rate"))
                    labour += units * rate

            linked_total = 0.0
            for pid in act.boq_position_ids or []:
                try:
                    linked_total += position_totals.get(uuid.UUID(str(pid)), 0.0)
                except (TypeError, ValueError):
                    continue

            entry = phases.setdefault(
                phase,
                {
                    "phase": phase,
                    "activity_count": 0,
                    "labor_cost": 0.0,
                    "total_cost": 0.0,
                    "start_date": act.start_date,
                    "end_date": act.end_date,
                },
            )
            entry["activity_count"] = int(entry["activity_count"]) + 1
            entry["labor_cost"] = float(entry["labor_cost"]) + labour
            entry["total_cost"] = (
                float(entry["total_cost"]) + labour + linked_total
            )
            start = str(entry["start_date"] or "")
            end = str(entry["end_date"] or "")
            if act.start_date and (not start or act.start_date < start):
                entry["start_date"] = act.start_date
            if act.end_date and (not end or act.end_date > end):
                entry["end_date"] = act.end_date

        rows = [
            LaborCostByPhaseRow(
                phase=str(p["phase"]),
                activity_count=int(p["activity_count"]),
                labor_cost=round(float(p["labor_cost"]), 2),
                total_cost=round(float(p["total_cost"]), 2),
                start_date=(str(p["start_date"]) if p["start_date"] else None),
                end_date=(str(p["end_date"]) if p["end_date"] else None),
            )
            for p in sorted(
                phases.values(),
                key=lambda e: (str(e["start_date"] or ""), str(e["phase"])),
            )
        ]

        return LaborCostByPhaseResponse(phases=rows)
