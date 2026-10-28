# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Approval Routes data access layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval_routes.models import (
    Delegation,
    Instance,
    Route,
    Step,
    StepState,
)


class ApprovalRouteRepository:
    """Data access for :class:`Route` / :class:`Step` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_route(self, route_id: uuid.UUID) -> Route | None:
        return await self.session.get(Route, route_id)

    async def list_routes(
        self,
        *,
        project_id: uuid.UUID | None,
        target_kind: str | None = None,
        include_tenant_wide: bool = True,
        include_inactive: bool = True,
    ) -> list[Route]:
        """List routes visible to the caller.

        When ``project_id`` is supplied we return rows that match that
        project AND (when ``include_tenant_wide``) tenant-wide
        ``project_id IS NULL`` templates as well - so a module surface
        can show shared templates plus per-project ones in a single
        dropdown without two round trips.

        ``include_inactive`` defaults to ``True`` (the admin surface shows
        archived routes). Pass ``False`` to restrict the result to
        ``is_active = True`` rows - what a consumer picker wants so users
        can't start a workflow on an archived template.
        """
        stmt = select(Route)
        if project_id is None:
            stmt = stmt.where(Route.project_id.is_(None))
        elif include_tenant_wide:
            stmt = stmt.where(
                or_(Route.project_id == project_id, Route.project_id.is_(None)),
            )
        else:
            stmt = stmt.where(Route.project_id == project_id)
        if target_kind is not None:
            stmt = stmt.where(Route.target_kind == target_kind)
        if not include_inactive:
            stmt = stmt.where(Route.is_active.is_(True))
        stmt = stmt.order_by(Route.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_steps(self, route_id: uuid.UUID) -> list[Step]:
        stmt = select(Step).where(Step.route_id == route_id).order_by(Step.ordinal.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_steps_for_routes(
        self,
        route_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[Step]]:
        """Batched fetch of steps for many routes - kills the N+1 in /routes.

        Returns a dict keyed by ``route_id``; missing keys mean no steps.
        Steps within each bucket are ordered by ``ordinal``, matching the
        per-route accessor's contract.
        """
        if not route_ids:
            return {}
        stmt = select(Step).where(Step.route_id.in_(route_ids)).order_by(Step.route_id, Step.ordinal.asc())
        rows = list((await self.session.execute(stmt)).scalars().all())
        out: dict[uuid.UUID, list[Step]] = {rid: [] for rid in route_ids}
        for step in rows:
            out.setdefault(step.route_id, []).append(step)
        return out

    async def get_step(self, step_id: uuid.UUID) -> Step | None:
        return await self.session.get(Step, step_id)

    async def add_route(self, route: Route) -> Route:
        self.session.add(route)
        await self.session.flush()
        return route

    async def add_step(self, step: Step) -> Step:
        self.session.add(step)
        await self.session.flush()
        return step

    async def add_steps_bulk(self, steps: list[Step]) -> list[Step]:
        for s in steps:
            self.session.add(s)
        await self.session.flush()
        return steps

    async def delete_steps_for_route(self, route_id: uuid.UUID) -> None:
        """Remove every step of a route - used when replacing the step list."""
        await self.session.execute(
            delete(Step).where(Step.route_id == route_id),
        )
        await self.session.flush()

    async def delete_route(self, route: Route) -> None:
        await self.session.delete(route)
        await self.session.flush()

    # ── Instances ─────────────────────────────────────────────────────

    async def get_instance(self, instance_id: uuid.UUID) -> Instance | None:
        return await self.session.get(Instance, instance_id)

    async def list_instances(
        self,
        *,
        target_kind: str | None = None,
        target_id: uuid.UUID | None = None,
        route_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Instance]:
        stmt = select(Instance)
        if target_kind is not None:
            stmt = stmt.where(Instance.target_kind == target_kind)
        if target_id is not None:
            stmt = stmt.where(Instance.target_id == target_id)
        if route_id is not None:
            stmt = stmt.where(Instance.route_id == route_id)
        if status is not None:
            stmt = stmt.where(Instance.status == status)
        stmt = stmt.order_by(Instance.started_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_instances_for_routes(
        self,
        route_ids: list[uuid.UUID],
        *,
        status: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        limit: int = 5000,
    ) -> list[Instance]:
        """Instances whose route is in ``route_ids``, newest first, capped.

        Backs the project-scoped analytics aggregate: :meth:`list_instances`
        filters by a single ``route_id``, so this batches the scan across a
        project's whole route set in one query. The ``limit`` bounds the
        Python-side held-time computation; the caller pairs it with the exact
        GROUP BY counter below so the headline status counts stay accurate even
        when the compute set is capped.
        """
        if not route_ids:
            return []
        stmt = select(Instance).where(Instance.route_id.in_(route_ids))
        if status is not None:
            stmt = stmt.where(Instance.status == status)
        if started_after is not None:
            stmt = stmt.where(Instance.started_at >= started_after)
        if started_before is not None:
            stmt = stmt.where(Instance.started_at <= started_before)
        stmt = stmt.order_by(Instance.started_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_instances_by_status_for_routes(
        self,
        route_ids: list[uuid.UUID],
        *,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
    ) -> dict[str, int]:
        """GROUP BY status count over a project's routes - cheap and exact.

        Stays accurate even when :meth:`list_instances_for_routes` is capped,
        so the analytics KPI headline never undercounts a busy project.
        """
        if not route_ids:
            return {}
        stmt = select(Instance.status, func.count()).where(Instance.route_id.in_(route_ids)).group_by(Instance.status)
        if started_after is not None:
            stmt = stmt.where(Instance.started_at >= started_after)
        if started_before is not None:
            stmt = stmt.where(Instance.started_at <= started_before)
        rows = (await self.session.execute(stmt)).all()
        return {status: int(count) for status, count in rows}

    async def add_instance(self, instance: Instance) -> Instance:
        self.session.add(instance)
        await self.session.flush()
        return instance

    # ── Step states ───────────────────────────────────────────────────

    async def list_step_states(self, instance_id: uuid.UUID) -> list[StepState]:
        stmt = select(StepState).where(StepState.instance_id == instance_id).order_by(StepState.created_at.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_step_states_for_instances(
        self,
        instance_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[StepState]]:
        """Batched fetch of step states for many instances - kills the N+1 in /instances.

        Returns a dict keyed by ``instance_id``; missing keys mean no
        states. States within each bucket are ordered by ``created_at``,
        matching the per-instance accessor's contract.
        """
        if not instance_ids:
            return {}
        stmt = (
            select(StepState)
            .where(StepState.instance_id.in_(instance_ids))
            .order_by(StepState.instance_id, StepState.created_at.asc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        out: dict[uuid.UUID, list[StepState]] = {iid: [] for iid in instance_ids}
        for state in rows:
            out.setdefault(state.instance_id, []).append(state)
        return out

    async def list_step_states_for_step(
        self,
        *,
        instance_id: uuid.UUID,
        step_id: uuid.UUID,
    ) -> list[StepState]:
        stmt = (
            select(StepState)
            .where(
                and_(
                    StepState.instance_id == instance_id,
                    StepState.step_id == step_id,
                ),
            )
            .order_by(StepState.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_step_state(self, state: StepState) -> StepState:
        self.session.add(state)
        await self.session.flush()
        return state

    # ── Delegations ───────────────────────────────────────────────────

    async def get_delegation(self, delegation_id: uuid.UUID) -> Delegation | None:
        return await self.session.get(Delegation, delegation_id)

    async def list_active_delegations(self) -> list[Delegation]:
        """Every delegation with the active flag set.

        The active *window* (starts_at / ends_at) and project scoping are
        applied by the pure engine, not here - this only filters the cheap
        boolean flag so a revoked hand-off is never considered.
        """
        stmt = select(Delegation).where(Delegation.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_delegations(
        self,
        *,
        delegator_user_id: uuid.UUID | None = None,
        delegate_user_id: uuid.UUID | None = None,
        include_inactive: bool = False,
    ) -> list[Delegation]:
        stmt = select(Delegation)
        if delegator_user_id is not None:
            stmt = stmt.where(Delegation.delegator_user_id == delegator_user_id)
        if delegate_user_id is not None:
            stmt = stmt.where(Delegation.delegate_user_id == delegate_user_id)
        if not include_inactive:
            stmt = stmt.where(Delegation.is_active.is_(True))
        stmt = stmt.order_by(Delegation.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_delegation(self, delegation: Delegation) -> Delegation:
        self.session.add(delegation)
        await self.session.flush()
        return delegation
