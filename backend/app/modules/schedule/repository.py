# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule data access layer.

All database queries for schedules, activities, and work orders live here.
No business logic - pure data access.
"""

import uuid
from typing import Literal

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, raiseload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.schedule.models import Activity, Schedule, ScheduleBaseline, ScheduleRelationship, WorkOrder
from app.modules.schedule.ordering import activity_order_terms


class ScheduleRepository:
    """Data access for Schedule model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, schedule_id: uuid.UUID) -> Schedule | None:
        """Get schedule by ID."""
        return await self.session.get(Schedule, schedule_id)

    async def get_for_update(self, schedule_id: uuid.UUID) -> Schedule | None:
        """Serialize lifecycle transitions without loading or changing activities."""
        stmt = (
            select(Schedule)
            .where(Schedule.id == schedule_id)
            .with_for_update()
            .options(raiseload(Schedule.activities, sql_only=True))
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        archive_state: Literal["current", "archived", "all"] = "all",
    ) -> tuple[list[Schedule], int]:
        """List schedules for a project with pagination. Returns (schedules, total_count).

        Activities are NOT loaded in list queries to avoid N+1.
        """
        base = select(Schedule).where(Schedule.project_id == project_id)
        # Internal financial readers retain their existing all-status default.
        # The public list explicitly requests current schedules by default.
        if archive_state == "current":
            base = base.where(Schedule.status != "archived")
        elif archive_state == "archived":
            base = base.where(Schedule.status == "archived")

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch - skip eager loading of activities for list queries
        stmt = (
            base.options(noload(Schedule.activities)).order_by(Schedule.created_at.desc()).offset(offset).limit(limit)
        )
        result = await self.session.execute(stmt)
        schedules = list(result.scalars().all())

        return schedules, total

    async def create(self, schedule: Schedule) -> Schedule:
        """Insert a new schedule."""
        self.session.add(schedule)
        await self.session.flush()
        return schedule

    async def update_fields(self, schedule_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a schedule."""
        stmt = update(Schedule).where(Schedule.id == schedule_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        instance = self.session.identity_map.get(identity_key(Schedule, schedule_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, schedule_id: uuid.UUID) -> None:
        """Delete a schedule and all its activities (via CASCADE)."""
        stmt = delete(Schedule).where(Schedule.id == schedule_id)
        await self.session.execute(stmt)

    async def count_baselines(self, schedule_id: uuid.UUID) -> int:
        """How many baselines a schedule has."""
        stmt = select(func.count()).select_from(ScheduleBaseline).where(ScheduleBaseline.schedule_id == schedule_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def delete_baselines(self, schedule_id: uuid.UUID) -> int:
        """Delete the baselines of a schedule; returns how many went.

        The baseline table keeps the schedule id without a foreign key, so
        deleting the schedule cascades nothing to it.
        """
        stmt = delete(ScheduleBaseline).where(ScheduleBaseline.schedule_id == schedule_id)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)


class ActivityRepository:
    """Data access for Activity model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, activity_id: uuid.UUID) -> Activity | None:
        """Get activity by ID."""
        return await self.session.get(Activity, activity_id)

    async def list_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> tuple[list[Activity], int]:
        """List activities for a schedule in display order. Returns (activities, total).

        Children and work_orders are NOT loaded to avoid N+1 on list queries.

        The order is decided here rather than by the caller because this read
        is paginated: a client that re-sorts the rows it was handed only
        rearranges one page. See :func:`~app.modules.schedule.ordering.activity_order_terms`.
        """
        base = select(Activity).where(Activity.schedule_id == schedule_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch in canonical display order - skip heavy relationships
        stmt = (
            base.options(
                noload(Activity.children),
                noload(Activity.work_orders),
            )
            .order_by(*activity_order_terms())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        activities = list(result.scalars().all())

        return activities, total

    async def create(self, activity: Activity) -> Activity:
        """Insert a new activity."""
        self.session.add(activity)
        await self.session.flush()
        return activity

    async def update_fields(self, activity_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an activity."""
        stmt = update(Activity).where(Activity.id == activity_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        instance = self.session.identity_map.get(identity_key(Activity, activity_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def update_fields_if_revision(self, activity_id: uuid.UUID, expected_revision: int, **fields: object) -> bool:
        """Compare-and-swap update for the optimistic-concurrency guard.

        Sets ``fields`` only if the row's ``revision`` still equals
        ``expected_revision``, in a single atomic ``UPDATE ... WHERE id AND
        revision`` so two concurrent writers on the same base cannot both
        succeed. Returns ``True`` when a row was updated, ``False`` when it was
        changed concurrently (rowcount 0) so the caller can surface a 409
        instead of silently overwriting the other write (lost update).
        """
        stmt = (
            update(Activity).where(Activity.id == activity_id, Activity.revision == expected_revision).values(**fields)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()
        return bool(result.rowcount and result.rowcount > 0)

    async def bulk_update_fields(self, updates: list[dict[str, object]]) -> None:
        """Update many activities in a single round trip.

        Each entry in ``updates`` must carry the primary key under ``"id"``
        plus the columns to set, e.g.
        ``{"id": <uuid>, "color": "#ef4444", "metadata_": {...}}``. Uses
        SQLAlchemy's ORM-enabled bulk UPDATE by primary key (executemany under
        the hood), which collapses what would otherwise be N separate UPDATE
        statements into one. Unlike :meth:`update_fields`, which syncs only the
        row it wrote, this expires the whole identity map once, so callers must
        read what they need before calling it rather than after. No-op when
        ``updates`` is empty.
        """
        if not updates:
            return
        await self.session.execute(update(Activity), updates)
        await self.session.flush()
        # Expire cached ORM instances once so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, activity_id: uuid.UUID) -> None:
        """Delete an activity."""
        stmt = delete(Activity).where(Activity.id == activity_id)
        await self.session.execute(stmt)

    @staticmethod
    def subtree(schedule_id: uuid.UUID, root_id: uuid.UUID) -> Select:
        """Ids of ``root_id`` and everything under it, at any depth, as a subquery.

        A recursive query over ``parent_id``, kept inside the schedule. UNION
        rather than UNION ALL, so a parent loop in bad data still ends.
        """
        tree = (
            select(Activity.id)
            .where(Activity.id == root_id, Activity.schedule_id == schedule_id)
            .cte("activity_subtree", recursive=True)
        )
        tree = tree.union(
            select(Activity.id).where(Activity.parent_id == tree.c.id, Activity.schedule_id == schedule_id)
        )
        return select(tree.c.id)

    async def delete_subtree(self, schedule_id: uuid.UUID, root_id: uuid.UUID) -> list[uuid.UUID]:
        """Delete ``root_id`` and everything under it; return the ids removed.

        Deleted through the subquery, not a list of ids, so a section of any
        size goes in one statement without running into a bound-parameter cap.
        """
        ids = list((await self.session.execute(self.subtree(schedule_id, root_id))).scalars().all())
        await self.session.execute(delete(Activity).where(Activity.id.in_(self.subtree(schedule_id, root_id))))
        return ids

    async def dependency_mirrors(self, schedule_id: uuid.UUID) -> list[tuple[uuid.UUID, list]]:
        """``(id, dependencies)`` of every activity of a schedule that lists any.

        A two-column read, so pruning the mirror after a delete never loads
        whole rows, and finds entries no canonical edge backs (older data).
        """
        rows = await self.session.execute(
            select(Activity.id, Activity.dependencies).where(Activity.schedule_id == schedule_id)
        )
        return [(row[0], row[1]) for row in rows.all() if row[1]]

    async def delete_many(self, activity_ids: list[uuid.UUID]) -> None:
        """Delete several activities in one statement (work orders cascade)."""
        if not activity_ids:
            return
        await self.session.execute(delete(Activity).where(Activity.id.in_(activity_ids)))

    async def delete_for_schedule(self, schedule_id: uuid.UUID) -> int:
        """Delete all activities of a schedule in a single statement.

        Returns the number of activities removed. Dependent work orders are
        removed via the ON DELETE CASCADE FK on WorkOrder.activity_id.
        """
        count_stmt = select(func.count()).select_from(
            select(Activity).where(Activity.schedule_id == schedule_id).subquery()
        )
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = delete(Activity).where(Activity.schedule_id == schedule_id)
        await self.session.execute(stmt)
        return int(total)

    async def create_many(self, activities: list[Activity]) -> None:
        """Insert many activities with one flush.

        Callers assign ``id`` up front when rows refer to each other.
        """
        if not activities:
            return
        self.session.add_all(activities)
        await self.session.flush()

    async def count_started(self, schedule_id: uuid.UUID) -> int:
        """Count the activities of a schedule that have started (any status past not started)."""
        stmt = select(func.count()).where(
            Activity.schedule_id == schedule_id,
            Activity.status != "not_started",
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def ids_in_schedule(self, schedule_id: uuid.UUID, activity_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        """Return those of ``activity_ids`` that are activities of ``schedule_id``."""
        if not activity_ids:
            return set()
        stmt = select(Activity.id).where(Activity.schedule_id == schedule_id, Activity.id.in_(activity_ids))
        return set((await self.session.execute(stmt)).scalars().all())

    async def reparent_children(self, parent_id: uuid.UUID, new_parent_id: uuid.UUID | None) -> None:
        """Move every child of ``parent_id`` under ``new_parent_id``."""
        stmt = update(Activity).where(Activity.parent_id == parent_id).values(parent_id=new_parent_id)
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_max_sort_order(self, schedule_id: uuid.UUID) -> int:
        """Get the highest sort_order for activities in a schedule."""
        stmt = select(func.coalesce(func.max(Activity.sort_order), -1)).where(Activity.schedule_id == schedule_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)

    async def list_outline(self, schedule_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID | None, int, str]]:
        """Return ``(id, parent_id, sort_order, wbs_code)`` for every activity in a schedule.

        A column-only read, so placing a new activity or numbering it never
        loads the full rows (JSON dependencies, resources, BIM ids).
        """
        stmt = select(Activity.id, Activity.parent_id, Activity.sort_order, Activity.wbs_code).where(
            Activity.schedule_id == schedule_id
        )
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], int(r[2] or 0), r[3] or "") for r in rows]

    async def get_max_activity_code_seq(self, schedule_id: uuid.UUID) -> int:
        """Get the highest numeric suffix from ACT-NNN activity codes in a schedule.

        Returns 0 if no activity codes exist yet.
        """
        stmt = (
            select(Activity.activity_code)
            .where(Activity.schedule_id == schedule_id)
            .where(Activity.activity_code.isnot(None))
        )
        result = await self.session.execute(stmt)
        codes = [row[0] for row in result.all() if row[0]]

        max_seq = 0
        for code in codes:
            # Parse ACT-NNN pattern
            if code and code.startswith("ACT-"):
                try:
                    seq = int(code[4:])
                    max_seq = max(max_seq, seq)
                except (ValueError, IndexError):
                    pass
        return max_seq


class WorkOrderRepository:
    """Data access for WorkOrder model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, work_order_id: uuid.UUID) -> WorkOrder | None:
        """Get work order by ID."""
        return await self.session.get(WorkOrder, work_order_id)

    async def list_for_activity(
        self,
        activity_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[WorkOrder], int]:
        """List work orders for an activity. Returns (work_orders, total_count)."""
        base = select(WorkOrder).where(WorkOrder.activity_id == activity_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(WorkOrder.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        work_orders = list(result.scalars().all())

        return work_orders, total

    async def list_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[WorkOrder], int]:
        """List work orders for all activities in a schedule.

        Joins through Activity to filter by schedule_id.
        Returns (work_orders, total_count).
        """
        base = (
            select(WorkOrder)
            .join(Activity, WorkOrder.activity_id == Activity.id)
            .where(Activity.schedule_id == schedule_id)
        )

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(WorkOrder.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        work_orders = list(result.scalars().all())

        return work_orders, total

    async def create(self, work_order: WorkOrder) -> WorkOrder:
        """Insert a new work order."""
        self.session.add(work_order)
        await self.session.flush()
        return work_order

    async def update_fields(self, work_order_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a work order."""
        stmt = update(WorkOrder).where(WorkOrder.id == work_order_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        instance = self.session.identity_map.get(identity_key(WorkOrder, work_order_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, work_order_id: uuid.UUID) -> None:
        """Delete a work order."""
        stmt = delete(WorkOrder).where(WorkOrder.id == work_order_id)
        await self.session.execute(stmt)


class RelationshipRepository:
    """Data access for :class:`ScheduleRelationship` - the canonical edge store.

    :class:`ScheduleRelationship` is the single source of truth for schedule
    dependency edges. Activity-embedded ``dependencies`` JSON is a derived
    mirror that the service rebuilds from these rows. All reads and writes of
    the canonical edge set go through this layer so the projection / CPM /
    completion-guard paths share one query surface.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_schedule(self, schedule_id: uuid.UUID) -> list[ScheduleRelationship]:
        """Return every relationship row of a schedule (unbounded - CPM needs all)."""
        stmt = select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_predecessors(self, successor_id: uuid.UUID) -> list[ScheduleRelationship]:
        """Return all relationship rows whose successor is ``successor_id``.

        These are the inbound predecessor edges of a single activity - used by
        the completion guard and the derived-JSON mirror rebuild.
        """
        stmt = select(ScheduleRelationship).where(ScheduleRelationship.successor_id == successor_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, relationship: ScheduleRelationship) -> ScheduleRelationship:
        """Insert a new relationship row."""
        self.session.add(relationship)
        await self.session.flush()
        return relationship

    async def create_many(self, relationships: list[ScheduleRelationship]) -> None:
        """Insert many relationship rows with one flush."""
        if not relationships:
            return
        self.session.add_all(relationships)
        await self.session.flush()

    async def delete_for_schedule(self, schedule_id: uuid.UUID) -> None:
        """Delete every relationship row of a schedule."""
        stmt = delete(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)
        await self.session.execute(stmt)

    async def delete_by_id(self, relationship_id: uuid.UUID) -> None:
        """Delete a single relationship by primary key."""
        stmt = delete(ScheduleRelationship).where(ScheduleRelationship.id == relationship_id)
        await self.session.execute(stmt)

    async def delete_edges(
        self,
        successor_id: uuid.UUID,
        predecessor_ids: list[uuid.UUID],
    ) -> None:
        """Delete the inbound edges of ``successor_id`` for the given predecessors.

        No-op when ``predecessor_ids`` is empty.
        """
        if not predecessor_ids:
            return
        stmt = delete(ScheduleRelationship).where(
            ScheduleRelationship.successor_id == successor_id,
            ScheduleRelationship.predecessor_id.in_(predecessor_ids),
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_edge(
        self,
        relationship_id: uuid.UUID,
        *,
        relationship_type: str,
        lag_days: int,
    ) -> None:
        """Update the type / lag of an existing relationship row."""
        stmt = (
            update(ScheduleRelationship)
            .where(ScheduleRelationship.id == relationship_id)
            .values(relationship_type=relationship_type, lag_days=lag_days)
        )
        await self.session.execute(stmt)
        await self.session.flush()
