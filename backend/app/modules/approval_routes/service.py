# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval Routes business logic.

Stateless service layer that owns the workflow rules:

* :meth:`ApprovalRouteService.create_route` - insert a route template + steps.
* :meth:`ApprovalRouteService.start_instance` - begin a workflow for a target.
* :meth:`ApprovalRouteService.submit_decision` - record a decision on the
  current step; auto-advance / auto-complete the instance.
* :meth:`ApprovalRouteService.cancel_instance` - terminate a pending workflow.

Every transition writes an :func:`app.core.audit_log.log_activity` row
under ``entity_type='approval_instance'``. Race protection is layered:

* The DB enforces ``UniqueConstraint(instance_id, step_id,
  approver_user_id)`` so two concurrent decision rows from the same user
  on the same step collide at flush time.
* The service additionally re-fetches the instance after acquiring an
  exclusive lock (``with_for_update``) before mutating ``status`` /
  ``current_step_ordinal``, so two approvers at the same step do not
  race the advance computation.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import event_bus
from app.core.permissions import ROLE_HIERARCHY, _resolve_role
from app.modules.approval_routes.models import (
    INSTANCE_STATUSES,
    STEP_MODES,
    TARGET_KINDS,
    Instance,
    Route,
    Step,
    StepState,
)
from app.modules.approval_routes.repository import ApprovalRouteRepository
from app.modules.approval_routes.schemas import (
    DecisionSubmit,
    InstanceCreate,
    RouteCreate,
    RouteUpdate,
)

logger = logging.getLogger(__name__)


def _validate_target_kind(kind: str) -> None:
    if kind not in TARGET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown target_kind: {kind!r}",
        )


def _validate_step_mode(mode: str) -> None:
    if mode not in STEP_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown step mode: {mode!r}",
        )


def _safe_publish(name: str, data: dict[str, object]) -> None:
    """Fire-and-forget a lifecycle event without coupling to consumers.

    Detached so a subscriber that opens its own session (variations,
    changeorders, contracts reacting to a terminal decision) can't
    deadlock the request transaction under SQLite's single-writer lock.
    Any failure to schedule is swallowed at debug - emitting an event
    must never break the workflow transition that produced it.
    """
    try:
        event_bus.publish_detached(name, data, source_module="approval_routes")
    except Exception:  # pragma: no cover - defensive, e.g. no running loop
        logger.debug("approval_routes event publish skipped: %s", name)


def _caller_role_satisfies(caller_role: str | None, required_role: str) -> bool:
    """Whether the caller's effective role meets a role-based step's gate.

    The route author configures ``approver_role`` as an app role name
    (admin / manager / editor / viewer) or an industry alias. A caller
    clears the gate when their role is an exact match OR ranks at or above
    the required role in the permission hierarchy. Aliases (estimator,
    owner, ...) are resolved to their canonical Role first - mirroring
    :data:`app.core.permissions.ROLE_ALIASES`, the same translation
    ``documents._iso_role_for`` performs - so a "quantity_surveyor"
    satisfies an "editor" step. Unknown roles cannot satisfy a gate, so an
    unrecognised caller or required role fails closed.
    """
    caller = (caller_role or "").strip().lower()
    required = (required_role or "").strip().lower()
    if caller and caller == required:
        return True
    caller_resolved = _resolve_role(caller)
    required_resolved = _resolve_role(required)
    if caller_resolved is None or required_resolved is None:
        return False
    return ROLE_HIERARCHY.get(caller_resolved, -99) >= ROLE_HIERARCHY.get(required_resolved, 99)


class ApprovalRouteService:
    """Business logic for the approval-routes feature."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ApprovalRouteRepository(session)

    # ── Routes ────────────────────────────────────────────────────────

    async def get_route(self, route_id: uuid.UUID) -> Route:
        row = await self.repo.get_route(route_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Route not found",
            )
        return row

    async def list_routes(
        self,
        *,
        project_id: uuid.UUID | None,
        target_kind: str | None = None,
        include_inactive: bool = True,
    ) -> list[Route]:
        if target_kind is not None:
            _validate_target_kind(target_kind)
        return await self.repo.list_routes(
            project_id=project_id,
            target_kind=target_kind,
            include_inactive=include_inactive,
        )

    async def list_steps(self, route_id: uuid.UUID) -> list[Step]:
        return await self.repo.list_steps(route_id)

    async def list_steps_for_routes(
        self,
        route_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[Step]]:
        """Batched accessor - kills the per-route N+1 in :get:`/routes`."""
        return await self.repo.list_steps_for_routes(route_ids)

    async def create_route(
        self,
        payload: RouteCreate,
        *,
        created_by: uuid.UUID | None,
    ) -> Route:
        """Insert a route + all its steps atomically.

        The schema validator already enforced dense ordinals 1..N; we
        re-check the mode whitelist here because the literal type
        constrains it at the API boundary but a service caller (e.g. a
        seed script) can bypass that.
        """
        _validate_target_kind(payload.target_kind)
        for step in payload.steps:
            _validate_step_mode(step.mode)

        route = Route(
            project_id=payload.project_id,
            name=payload.name,
            target_kind=payload.target_kind,
            is_active=payload.is_active,
            created_by=created_by,
        )
        await self.repo.add_route(route)

        step_rows = [
            Step(
                route_id=route.id,
                ordinal=s.ordinal,
                approver_role=s.approver_role,
                approver_user_id=s.approver_user_id,
                mode=s.mode,
                required_approver_count=s.required_approver_count,
                sla_hours=s.sla_hours,
            )
            for s in payload.steps
        ]
        await self.repo.add_steps_bulk(step_rows)

        await log_activity(
            self.session,
            actor_id=created_by,
            entity_type="approval_route",
            entity_id=str(route.id),
            action="created",
            to_status="active" if route.is_active else "inactive",
            module="approval_routes",
            metadata={
                "name": route.name,
                "target_kind": route.target_kind,
                "step_count": len(step_rows),
                "project_id": str(route.project_id) if route.project_id else None,
            },
        )
        return route

    async def update_route(
        self,
        route_id: uuid.UUID,
        payload: RouteUpdate,
        *,
        actor_id: uuid.UUID | None,
    ) -> Route:
        route = await self.get_route(route_id)
        changed: dict[str, object] = {}
        if payload.name is not None and payload.name != route.name:
            changed["name"] = (route.name, payload.name)
            route.name = payload.name
        if payload.is_active is not None and payload.is_active != route.is_active:
            changed["is_active"] = (route.is_active, payload.is_active)
            route.is_active = payload.is_active

        # Replace the step list when supplied. Deleting steps cascades to
        # any StepState rows, so we refuse to touch the steps of a route
        # that already has instances - the decision history would be lost.
        if payload.steps is not None:
            for step in payload.steps:
                _validate_step_mode(step.mode)
            existing = await self.repo.list_instances(route_id=route_id, limit=1)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=("Route has instances; its steps can no longer be edited. Create a new route instead."),
                )
            old_steps = await self.repo.list_steps(route_id)
            await self.repo.delete_steps_for_route(route_id)
            new_steps = [
                Step(
                    route_id=route.id,
                    ordinal=s.ordinal,
                    approver_role=s.approver_role,
                    approver_user_id=s.approver_user_id,
                    mode=s.mode,
                    required_approver_count=s.required_approver_count,
                    sla_hours=s.sla_hours,
                )
                for s in payload.steps
            ]
            await self.repo.add_steps_bulk(new_steps)
            changed["step_count"] = (len(old_steps), len(new_steps))

        if not changed:
            return route
        await self.session.flush()
        # The UPDATE fires ``updated_at``'s server-side ``onupdate=func.now()``,
        # which expires the attribute. Reload the scalar columns inside the
        # async greenlet so the synchronous ``RouteResponse.model_validate``
        # downstream doesn't trigger lazy IO (MissingGreenlet). Mirrors the
        # refresh in ``submit_decision`` / ``cancel_instance``.
        await self.session.refresh(route)
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="approval_route",
            entity_id=str(route.id),
            action="updated",
            module="approval_routes",
            metadata={k: {"from": v[0], "to": v[1]} for k, v in changed.items()},
        )
        return route

    async def delete_route(
        self,
        route_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
    ) -> None:
        route = await self.get_route(route_id)
        # Reject delete when any instance still references this route -
        # the FK uses RESTRICT, so we surface a friendly 409 instead of
        # letting the DB raise a raw IntegrityError.
        existing = await self.repo.list_instances(route_id=route_id, limit=1)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Route has active instances; deactivate it instead",
            )
        await self.repo.delete_route(route)
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="approval_route",
            entity_id=str(route_id),
            action="deleted",
            module="approval_routes",
        )

    # ── Instances ─────────────────────────────────────────────────────

    async def get_instance(self, instance_id: uuid.UUID) -> Instance:
        row = await self.repo.get_instance(instance_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval instance not found",
            )
        return row

    async def list_step_states(self, instance_id: uuid.UUID) -> list[StepState]:
        return await self.repo.list_step_states(instance_id)

    async def list_step_states_for_instances(
        self,
        instance_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[StepState]]:
        """Batched accessor - kills the per-instance N+1 in :get:`/instances`."""
        return await self.repo.list_step_states_for_instances(instance_ids)

    async def list_instances(
        self,
        *,
        target_kind: str | None = None,
        target_id: uuid.UUID | None = None,
        route_id: uuid.UUID | None = None,
        instance_status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Instance]:
        if target_kind is not None:
            _validate_target_kind(target_kind)
        if instance_status is not None and instance_status not in INSTANCE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown status: {instance_status!r}",
            )
        return await self.repo.list_instances(
            target_kind=target_kind,
            target_id=target_id,
            route_id=route_id,
            status=instance_status,
            limit=limit,
            offset=offset,
        )

    async def start_instance(
        self,
        payload: InstanceCreate,
        *,
        started_by: uuid.UUID | None,
    ) -> Instance:
        """Start a new workflow against a concrete target row.

        Re-using an active workflow on the same target is rejected (409)
        so consumer modules cannot accidentally fork the chain. The
        caller can cancel the existing instance first if they really
        need to restart the workflow.
        """
        _validate_target_kind(payload.target_kind)

        route = await self.get_route(payload.route_id)
        if not route.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Route is not active",
            )
        if route.target_kind != payload.target_kind:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"Route target_kind {route.target_kind!r} does not match requested {payload.target_kind!r}"),
            )

        steps = await self.repo.list_steps(route.id)
        if not steps:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Route has no steps",
            )

        # Reject duplicate workflow on the same target row.
        active = await self.repo.list_instances(
            target_kind=payload.target_kind,
            target_id=payload.target_id,
            status="pending",
            limit=1,
        )
        if active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An approval workflow is already pending on this target",
            )

        now = datetime.now(UTC)
        instance = Instance(
            route_id=route.id,
            target_kind=payload.target_kind,
            target_id=payload.target_id,
            current_step_ordinal=1,
            status="pending",
            started_at=now,
            completed_at=None,
            started_by=started_by,
        )
        await self.repo.add_instance(instance)

        await log_activity(
            self.session,
            actor_id=started_by,
            entity_type="approval_instance",
            entity_id=str(instance.id),
            action="started",
            to_status="pending",
            module="approval_routes",
            metadata={
                "route_id": str(route.id),
                "target_kind": payload.target_kind,
                "target_id": str(payload.target_id),
                "step_count": len(steps),
            },
        )
        _safe_publish(
            "approval_routes.instance.started",
            {
                "instance_id": str(instance.id),
                "route_id": str(route.id),
                "target_kind": payload.target_kind,
                "target_id": str(payload.target_id),
                "step_count": len(steps),
                "status": "pending",
            },
        )
        return instance

    async def submit_decision(
        self,
        instance_id: uuid.UUID,
        payload: DecisionSubmit,
        *,
        approver_id: uuid.UUID | None,
        caller_role: str | None = None,
    ) -> Instance:
        """Record a decision on the current step + auto-advance.

        Workflow:
            1. Re-fetch the instance under ``with_for_update`` to serialise
               two concurrent decisions at the DB level.
            2. Reject when the instance is not pending OR the step does
               not belong to the instance's route OR the step's ordinal
               is not the current one.
            3. Insert one :class:`StepState` row. The unique constraint
               ``(instance_id, step_id, approver_user_id)`` blocks a
               duplicate decision from the same approver on the same step.
            4. If decision is ``rejected`` → finalise the instance as
               ``rejected`` immediately.
            5. If decision is ``approved`` → consult the step's mode:

                ``all``       - needs every distinct approver_user_id on
                                 the step to approve.
                ``any``       - first approval advances.
                ``majority``  - strict majority of approvers (>50%).

               The step's "expected approver count" is derived from
               distinct ``approver_user_id`` rows submitted so far when
               the step is role-based (we cannot expand a role to its
               members from the engine - that is a consumer concern;
               the safe fallback is ``any``-style advance for roles).
               When the step is user-pinned, the count is 1.

            6. On advance, if there is no next step, complete the
               instance as ``approved``. Otherwise bump
               ``current_step_ordinal`` and stay pending.
        """
        # Lock the instance row so two approvers can't race the
        # advance/complete computation. ``nowait=False`` is the default -
        # we wait for the lock, which is the right semantic for a UI
        # click (the second clicker just sees the post-advance state).
        # SQLite ignores SELECT...FOR UPDATE silently; for production
        # Postgres this is the actual race guard.
        instance = await self._lock_instance(instance_id)

        if instance.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Instance is {instance.status}, not pending",
            )

        step = await self.repo.get_step(payload.step_id)
        if step is None or step.route_id != instance.route_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Step does not belong to this instance's route",
            )
        if step.ordinal != instance.current_step_ordinal:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Step ordinal {step.ordinal} is not the current step ({instance.current_step_ordinal})"),
            )

        # User-pinned step: only the named user may decide.
        if step.approver_user_id is not None and approver_id != step.approver_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not the named approver for this step",
            )

        # Role-based step: the caller must actually hold the required role.
        # Without this, anyone with the ``approval_routes.decide`` permission
        # could clear a step pinned to a higher role (e.g. an editor signing
        # off a "manager" gate). The caller role is translated through the
        # permission hierarchy / aliases the same way other role-gated
        # services resolve it.
        if (
            step.approver_user_id is None
            and step.approver_role
            and not _caller_role_satisfies(caller_role, step.approver_role)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caller role does not satisfy the approver role for this step",
            )

        now = datetime.now(UTC)
        state = StepState(
            instance_id=instance.id,
            step_id=step.id,
            approver_user_id=approver_id,
            decision=payload.decision,
            comment=payload.comment,
            decided_at=now,
        )
        try:
            await self.repo.add_step_state(state)
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Decision already recorded for this approver on this step",
            ) from exc

        previous_status = instance.status
        previous_ordinal = instance.current_step_ordinal

        # Lifecycle events to fan out once the transition is durable. The
        # payload snapshots enough context (target_kind + target_id) for a
        # consumer subscriber to locate the row without re-querying us.
        events_to_fire: list[tuple[str, dict[str, object]]] = []
        base_event = {
            "instance_id": str(instance.id),
            "route_id": str(instance.route_id),
            "target_kind": instance.target_kind,
            "target_id": str(instance.target_id),
            "decision": payload.decision,
            "step_id": str(step.id),
            "step_ordinal": step.ordinal,
            # The deciding approver, so a consumer subscriber that drives a
            # domain FSM off a terminal decision (submittals / rfi feature 06)
            # can attribute the resulting status change to the right actor in
            # its own audit trail instead of recording it as anonymous.
            "decided_by": str(approver_id) if approver_id else None,
            "comment": payload.comment,
        }

        if payload.decision == "rejected":
            instance.status = "rejected"
            instance.completed_at = now
            events_to_fire.append(("approval_routes.instance.rejected", {**base_event, "status": "rejected"}))
        else:
            advanced = await self._maybe_advance(instance, step)
            if advanced is None:
                # Step still pending - need more approvals. No lifecycle event.
                pass
            elif advanced is True:
                # All steps cleared - the clearing step both advanced the
                # cursor and finished the chain, so both events fire.
                instance.status = "approved"
                instance.completed_at = now
                events_to_fire.append(("approval_routes.instance.advanced", {**base_event, "status": "pending"}))
                events_to_fire.append(("approval_routes.instance.completed", {**base_event, "status": "approved"}))
            else:
                # Move to next step.
                instance.current_step_ordinal = step.ordinal + 1
                events_to_fire.append(("approval_routes.instance.advanced", {**base_event, "status": "pending"}))

        await self.session.flush()
        await self.session.refresh(instance)

        await log_activity(
            self.session,
            actor_id=approver_id,
            entity_type="approval_instance",
            entity_id=str(instance.id),
            action="decision",
            from_status=previous_status,
            to_status=instance.status,
            reason=payload.comment,
            module="approval_routes",
            metadata={
                "step_id": str(step.id),
                "step_ordinal_before": previous_ordinal,
                "step_ordinal_after": instance.current_step_ordinal,
                "decision": payload.decision,
                "target_kind": instance.target_kind,
                "target_id": str(instance.target_id),
            },
        )
        for event_name, event_data in events_to_fire:
            _safe_publish(event_name, event_data)
        return instance

    async def cancel_instance(
        self,
        instance_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> Instance:
        instance = await self._lock_instance(instance_id)
        if instance.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Instance is {instance.status}, cannot cancel",
            )
        previous_status = instance.status
        instance.status = "cancelled"
        instance.completed_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(instance)

        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="approval_instance",
            entity_id=str(instance.id),
            action="cancelled",
            from_status=previous_status,
            to_status="cancelled",
            reason=reason,
            module="approval_routes",
            metadata={
                "target_kind": instance.target_kind,
                "target_id": str(instance.target_id),
            },
        )
        _safe_publish(
            "approval_routes.instance.cancelled",
            {
                "instance_id": str(instance.id),
                "route_id": str(instance.route_id),
                "target_kind": instance.target_kind,
                "target_id": str(instance.target_id),
                "reason": reason,
                "status": "cancelled",
            },
        )
        return instance

    # ── Internal helpers ──────────────────────────────────────────────

    async def _lock_instance(self, instance_id: uuid.UUID) -> Instance:
        """Re-fetch the instance with a row lock.

        SQLite silently drops ``FOR UPDATE`` so this is a true lock only
        on Postgres; the application-level guard (status + ordinal check)
        is the SQLite-safe fallback.
        """
        stmt = select(Instance).where(Instance.id == instance_id).with_for_update()
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval instance not found",
            )
        return row

    async def _maybe_advance(self, instance: Instance, step: Step) -> bool | None:
        """Decide whether the current step is cleared.

        Returns:
            ``True``  - every step has been cleared; complete the instance.
            ``False`` - current step cleared; bump to the next step.
            ``None``  - current step not yet cleared; stay put.
        """
        states = await self.repo.list_step_states_for_step(
            instance_id=instance.id,
            step_id=step.id,
        )
        # Only count decisive (approved) rows for advance purposes.
        approvals = [s for s in states if s.decision == "approved"]
        approver_ids: set[uuid.UUID | None] = {s.approver_user_id for s in approvals}

        if step.approver_user_id is not None:
            # User-pinned: one approval from that user advances.
            cleared = step.approver_user_id in approver_ids
        else:
            # Role-based: the engine does not expand roles to members
            # (that's the consumer module's job), so we use sensible
            # defaults driven by ``mode``:
            #
            #   any       - first approval advances
            #   all       - every eligible approver has to approve, with no
            #               rejection rows (rejections short-circuit upstream)
            #   majority  - > 50% of the eligible approvers approved
            #               (rejections short-circuit)
            #
            # The consumer can override this by passing an explicit
            # ``approver_user_id`` list when defining the route - at that
            # point the step becomes user-pinned per row.
            #
            # ``all`` / ``majority`` must NOT clear on a single approval:
            # that evaluated only the rows submitted so far, not the
            # eligible population, so the very first approver closed a gate
            # that was meant to require several. When the route author has
            # declared the eligible population on the step
            # (``required_approver_count``) we evaluate against it; without
            # it we cannot know the true population, so we require more than
            # one distinct approver to have approved (with no rejection) as
            # the safe non-deadlocking fallback.
            quorum = step.required_approver_count
            approver_count = len({s.approver_user_id for s in approvals})
            rejections = [s for s in states if s.decision == "rejected"]
            if step.mode == "any":
                cleared = len(approvals) >= 1
            elif step.mode == "majority":
                if quorum is not None and quorum >= 1:
                    cleared = approver_count * 2 > quorum and len(rejections) == 0
                else:
                    total_acted = len([s for s in states if s.decision != "pending"])
                    cleared = total_acted >= 2 and len(approvals) * 2 > total_acted
            else:  # "all"
                if quorum is not None and quorum >= 1:
                    cleared = approver_count >= quorum and len(rejections) == 0
                else:
                    cleared = approver_count >= 2 and len(rejections) == 0

        if not cleared:
            return None

        # Check whether there is a next step.
        steps = await self.repo.list_steps(instance.route_id)
        next_ordinal = step.ordinal + 1
        has_next = any(s.ordinal == next_ordinal for s in steps)
        return not has_next  # True == finished, False == has next step


def _group_step_states_by_step(
    states: list[StepState],
) -> dict[uuid.UUID, list[StepState]]:
    """Helper for tests / debugging - group state rows by their step."""
    grouped: dict[uuid.UUID, list[StepState]] = defaultdict(list)
    for s in states:
        grouped[s.step_id].append(s)
    return dict(grouped)
