"""Enterprise Workflows service — business logic for approval workflows.

Stateless service layer.
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


class WorkflowService:
    """Business logic for enterprise approval workflows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workflows = WorkflowRepository(session)
        self.requests = ApprovalRequestRepository(session)

    # ── Workflows ───────────────────────────────────────────────────────────

    async def create_workflow(self, data: WorkflowCreate) -> ApprovalWorkflow:
        """Create a new approval workflow definition."""
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
            if user_role is None or needed is None or ROLE_HIERARCHY.get(user_role, -1) < ROLE_HIERARCHY.get(needed, 999):
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

        # Enforce per-step role / assignee before accepting the decision.
        await self._require_step_role(workflow.steps, current_step, user_id)

        if current_step < total_steps:
            # Advance to next step — not fully approved yet
            await self.requests.update(
                request_id,
                current_step=current_step + 1,
                decision_notes=decision_notes,
            )
        else:
            # Final step — fully approved
            await self.requests.update(
                request_id,
                status="approved",
                decided_by=uuid.UUID(user_id),
                decided_at=datetime.now(UTC).isoformat(),
                decision_notes=decision_notes,
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

        await self.requests.update(
            request_id,
            status="rejected",
            decided_by=uuid.UUID(user_id),
            decided_at=datetime.now(UTC).isoformat(),
            decision_notes=decision_notes,
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

        await self.requests.update(
            request_id,
            status="cancelled",
            decided_by=uuid.UUID(user_id),
            decided_at=datetime.now(UTC).isoformat(),
        )

        updated = await self.requests.get(request_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        logger.info("Approval request cancelled: %s by %s", request_id, user_id)
        return updated
