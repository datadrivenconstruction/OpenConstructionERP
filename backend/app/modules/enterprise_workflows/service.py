"""‌⁠‍Enterprise Workflows service — business logic for approval workflows.

Stateless service layer.

Hardening notes (2026-05-21 sweep):

* ``MAX_STEPS`` caps every workflow definition at 32 steps. This is the
  infinite-loop guard: a malicious / buggy workflow that smuggled
  millions of steps into ``steps`` JSON would lock the approval engine
  in a tight ``current_step + 1`` cycle. Enforced at create + update.
* ``ALLOWED_ACTION_TYPES`` whitelists the per-step ``action_type`` keys
  the engine knows how to dispatch. Unknown values are rejected at
  create / update so we never silently dispatch — and never grow into
  a sandbox-escape vector where a step JSON node executes templated
  SQL / Python / JS.
* ``role`` on each step must resolve to a canonical Role via
  ``_resolve_role``. Garbage roles (e.g. ``"<script>"``) are rejected
  at the schema boundary rather than silently locking / unlocking
  approvals downstream.
* Every approve / reject / cancel transition appends an ``audit_log``
  entry to ``request.metadata_`` — who, when, what step, outcome,
  notes. This is the forensic trail; the single ``decided_by`` field
  only records the final decider, which is insufficient for
  multi-step workflows.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.enterprise_workflows.models import ApprovalRequest, ApprovalWorkflow
from app.modules.enterprise_workflows.repository import (
    ApprovalRequestRepository,
    WorkflowRepository,
)
from app.modules.enterprise_workflows.schemas import (
    ApprovalRequestCreate,
    WorkflowCreate,
    WorkflowUpdate,
)

logger = logging.getLogger(__name__)

# Hard cap on workflow step count. 32 is generous for real-world approval
# chains (typical real workflows are 2-5 steps; the longest documented
# DACH construction sign-off is ~12). Anything beyond this is a config
# mistake or a malicious payload trying to DoS the engine.
MAX_STEPS: int = 32

# Whitelist of valid per-step action_type values. The approval engine
# only knows how to dispatch these; anything else is rejected at the
# schema boundary so we never silently no-op and never grow this into
# a templated-code-execution vector.
ALLOWED_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "approve",  # Standard approve / reject decision step (default)
        "review",  # Soft review — captured but doesn't gate progression
        "sign_off",  # Final binding sign-off (e.g. director / client)
        "notify",  # Send-and-forward — no decision required
    }
)


def _validate_steps(steps: list[dict] | None) -> None:
    """Validate workflow steps at create / update.

    Enforces:
        * step count ≤ MAX_STEPS (infinite-loop guard)
        * each step is a dict
        * ``action_type`` if present is in ALLOWED_ACTION_TYPES
        * ``role`` if present resolves to a canonical Role

    Raises HTTPException 400 on any violation.
    """
    if steps is None:
        return
    if not isinstance(steps, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow 'steps' must be a list",
        )
    if len(steps) > MAX_STEPS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow exceeds maximum of {MAX_STEPS} steps (got {len(steps)})",
        )

    # Defer permissions import — keeps the module light at import time.
    from app.core.permissions import _resolve_role

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Step {idx + 1} must be a JSON object",
            )
        action_type = step.get("action_type")
        if action_type is not None and action_type not in ALLOWED_ACTION_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Step {idx + 1}: action_type '{action_type}' is not allowed. "
                    f"Allowed values: {sorted(ALLOWED_ACTION_TYPES)}"
                ),
            )
        required_role = step.get("role")
        if required_role:
            if not isinstance(required_role, str) or _resolve_role(required_role) is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Step {idx + 1}: role '{required_role}' is not a known role",
                )


class WorkflowService:
    """‌⁠‍Business logic for enterprise approval workflows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workflows = WorkflowRepository(session)
        self.requests = ApprovalRequestRepository(session)

    # ── Workflows ───────────────────────────────────────────────────────────

    async def create_workflow(self, data: WorkflowCreate) -> ApprovalWorkflow:
        """‌⁠‍Create a new approval workflow definition."""
        _validate_steps(data.steps)
        workflow = ApprovalWorkflow(
            project_id=data.project_id,
            entity_type=data.entity_type,
            name=data.name,
            description=data.description,
            steps=data.steps,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        workflow = await self.workflows.create(workflow)
        logger.info("Workflow created: %s (%s)", workflow.name, workflow.entity_type)
        return workflow

    async def get_workflow(self, workflow_id: uuid.UUID) -> ApprovalWorkflow:
        """Get workflow by ID. Raises 404 if not found."""
        workflow = await self.workflows.get(workflow_id)
        if workflow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found",
            )
        return workflow

    async def list_workflows(
        self,
        *,
        project_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ApprovalWorkflow], int]:
        """List workflows with filters."""
        return await self.workflows.list(
            project_id=project_id,
            entity_type=entity_type,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    async def update_workflow(
        self,
        workflow_id: uuid.UUID,
        data: WorkflowUpdate,
    ) -> ApprovalWorkflow:
        """Update workflow fields."""
        await self.get_workflow(workflow_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if "steps" in fields:
            _validate_steps(fields["steps"])
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.workflows.update(workflow_id, **fields)

        updated = await self.workflows.get(workflow_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found",
            )
        logger.info("Workflow updated: %s", workflow_id)
        return updated

    async def delete_workflow(self, workflow_id: uuid.UUID) -> None:
        """Delete a workflow and its requests."""
        await self.get_workflow(workflow_id)  # 404 check
        await self.workflows.delete(workflow_id)
        logger.info("Workflow deleted: %s", workflow_id)

    # ── Approval Requests ───────────────────────────────────────────────────

    async def submit_request(
        self,
        data: ApprovalRequestCreate,
        user_id: str,
    ) -> ApprovalRequest:
        """Submit an entity for approval against a workflow."""
        await self.get_workflow(data.workflow_id)  # 404 check

        request = ApprovalRequest(
            workflow_id=data.workflow_id,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            current_step=1,
            status="pending",
            requested_by=uuid.UUID(user_id),
            metadata_=data.metadata,
        )
        request = await self.requests.create(request)
        logger.info(
            "Approval request submitted: %s/%s via workflow %s",
            data.entity_type,
            data.entity_id,
            data.workflow_id,
        )
        return request

    async def get_request(self, request_id: uuid.UUID) -> ApprovalRequest:
        """Get approval request by ID. Raises 404 if not found."""
        request = await self.requests.get(request_id)
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        return request

    async def list_requests(
        self,
        *,
        workflow_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        request_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ApprovalRequest], int]:
        """List approval requests with filters."""
        return await self.requests.list(
            workflow_id=workflow_id,
            entity_type=entity_type,
            status=request_status,
            limit=limit,
            offset=offset,
        )

    def _append_audit(
        self,
        request: ApprovalRequest,
        *,
        user_id: str,
        action: str,
        step: int,
        notes: str | None = None,
    ) -> dict:
        """Append an audit-log entry to a request's metadata.

        Returns the updated metadata dict — caller is responsible for
        persisting it via ``self.requests.update(metadata_=...)``.
        Each entry records who did what at which step, when, and the
        optional decision notes. Loses no information across step
        transitions (the single ``decided_by`` column only captures the
        terminal decider, which is insufficient for multi-step
        workflows).
        """
        metadata = dict(request.metadata_ or {})
        audit_log = list(metadata.get("audit_log") or [])
        audit_log.append(
            {
                "actor": user_id,
                "action": action,
                "step": step,
                "at": datetime.now(UTC).isoformat(),
                "notes": notes,
            }
        )
        metadata["audit_log"] = audit_log
        return metadata

    async def _require_step_role(
        self,
        workflow_steps: list[dict] | None,
        current_step: int,
        user_id: str,
    ) -> None:
        """Enforce that *user_id*'s role matches the current step's ``role``
        (or ``assignee_id`` if explicitly assigned). Raises 403 otherwise.

        Steps without a role restriction stay open to anyone (legacy
        behaviour). This guards against BUG-156 — any authenticated user
        could previously approve a step intended for a specific role.
        """
        if not workflow_steps:
            return
        idx = max(0, min(len(workflow_steps) - 1, current_step - 1))
        step = workflow_steps[idx] or {}
        required_role = (step.get("role") or "").strip()
        required_assignee = step.get("assignee_id")
        if not required_role and not required_assignee:
            return

        from uuid import UUID as _UUID

        from app.core.permissions import ROLE_HIERARCHY, _resolve_role
        from app.modules.users.models import User as _UserModel

        try:
            user = await self.session.get(_UserModel, _UUID(user_id))
        except Exception:
            user = None
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not authorised for this approval step",
            )

        if required_assignee and str(required_assignee) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Step is assigned to a different reviewer",
            )

        if required_role:
            user_role = _resolve_role(user.role)
            needed = _resolve_role(required_role)
            if (
                user_role is None
                or needed is None
                or ROLE_HIERARCHY.get(user_role, -1) < ROLE_HIERARCHY.get(needed, 999)
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Step requires role '{required_role}'",
                )

    async def approve_request(
        self,
        request_id: uuid.UUID,
        user_id: str,
        decision_notes: str | None = None,
    ) -> ApprovalRequest:
        """Approve an approval request at the current step.

        If the workflow has more steps, advances to the next step.
        If this is the final step, marks the request as approved.
        """
        request = await self.get_request(request_id)
        if request.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve request in status '{request.status}'",
            )

        # Load workflow to check total steps
        workflow = await self.get_workflow(request.workflow_id)
        total_steps = len(workflow.steps) if workflow.steps else 1
        current_step = request.current_step

        # Runtime infinite-loop guard. ``current_step`` should never
        # exceed ``MAX_STEPS`` because the workflow can't be created
        # past that cap, but a corrupted row or a stale workflow whose
        # steps were trimmed after a request was already past the new
        # tail must not silently spin. Reject loudly.
        if current_step > MAX_STEPS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request exceeds maximum step count ({MAX_STEPS})",
            )

        # Enforce per-step role / assignee before accepting the decision.
        await self._require_step_role(workflow.steps, current_step, user_id)

        new_metadata = self._append_audit(
            request,
            user_id=user_id,
            action="approve",
            step=current_step,
            notes=decision_notes,
        )

        if current_step < total_steps:
            # Advance to next step — not fully approved yet
            await self.requests.update(
                request_id,
                current_step=current_step + 1,
                decision_notes=decision_notes,
                metadata_=new_metadata,
            )
        else:
            # Final step — fully approved
            await self.requests.update(
                request_id,
                status="approved",
                decided_by=uuid.UUID(user_id),
                decided_at=datetime.now(UTC).isoformat(),
                decision_notes=decision_notes,
                metadata_=new_metadata,
            )

        updated = await self.requests.get(request_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        logger.info("Approval request approved at step %d/%d: %s", current_step, total_steps, request_id)
        return updated

    async def reject_request(
        self,
        request_id: uuid.UUID,
        user_id: str,
        decision_notes: str | None = None,
    ) -> ApprovalRequest:
        """Reject an approval request."""
        request = await self.get_request(request_id)
        if request.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject request in status '{request.status}'",
            )

        workflow = await self.get_workflow(request.workflow_id)
        await self._require_step_role(workflow.steps, request.current_step, user_id)

        new_metadata = self._append_audit(
            request,
            user_id=user_id,
            action="reject",
            step=request.current_step,
            notes=decision_notes,
        )

        await self.requests.update(
            request_id,
            status="rejected",
            decided_by=uuid.UUID(user_id),
            decided_at=datetime.now(UTC).isoformat(),
            decision_notes=decision_notes,
            metadata_=new_metadata,
        )

        updated = await self.requests.get(request_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        logger.info("Approval request rejected: %s", request_id)
        return updated

    async def cancel_request(
        self,
        request_id: uuid.UUID,
        user_id: str,
    ) -> ApprovalRequest:
        """Withdraw a still-pending request.

        Only the original requester (or an admin) may cancel — closes the
        "once submitted, stuck forever" gap in the workflow engine.
        """
        from app.core.permissions import Role, _resolve_role
        from app.modules.users.models import User as _UserModel

        request = await self.get_request(request_id)
        if request.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel request in status '{request.status}'",
            )

        is_owner = str(request.requested_by) == str(user_id)
        if not is_owner:
            try:
                user = await self.session.get(_UserModel, uuid.UUID(user_id))
            except Exception:
                user = None
            if user is None or _resolve_role(user.role) != Role.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the requester or an admin can cancel this request",
                )

        new_metadata = self._append_audit(
            request,
            user_id=user_id,
            action="cancel",
            step=request.current_step,
            notes=None,
        )

        await self.requests.update(
            request_id,
            status="cancelled",
            decided_by=uuid.UUID(user_id),
            decided_at=datetime.now(UTC).isoformat(),
            metadata_=new_metadata,
        )

        updated = await self.requests.get(request_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        logger.info("Approval request cancelled: %s by %s", request_id, user_id)
        return updated
