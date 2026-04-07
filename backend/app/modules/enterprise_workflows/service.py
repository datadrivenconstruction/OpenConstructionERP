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

    async def approve_request(
        self,
        request_id: uuid.UUID,
        user_id: str,
        decision_notes: str | None = None,
    ) -> ApprovalRequest:
        """Approve an approval request."""
        request = await self.get_request(request_id)
        if request.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve request in status '{request.status}'",
            )

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
        logger.info("Approval request approved: %s", request_id)
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
