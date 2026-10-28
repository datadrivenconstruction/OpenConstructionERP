# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Enterprise Workflows data access layer.

All database queries for workflow entities live here.
No business logic - pure data access.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.orm_write import apply_update
from app.modules.enterprise_workflows.models import ApprovalRequest, ApprovalWorkflow


class WorkflowRepository:
    """Data access for ApprovalWorkflow model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, workflow_id: uuid.UUID) -> ApprovalWorkflow | None:
        """Get workflow by ID."""
        return await self.session.get(ApprovalWorkflow, workflow_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        is_active: bool | None = None,
        accessible_project_ids: set[uuid.UUID] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ApprovalWorkflow], int]:
        """List workflows with filters and pagination.

        ``accessible_project_ids`` scopes the result to a non-admin caller's
        reachable projects when no explicit ``project_id`` filter is given.
        ``None`` means "do not scope" (admin / full view). A provided set
        restricts results to workflows whose ``project_id`` is in the set;
        workspace-level templates (``project_id IS NULL``) stay visible to
        everyone. An empty set therefore yields only those templates.
        """
        base = select(ApprovalWorkflow)

        if project_id is not None:
            base = base.where(ApprovalWorkflow.project_id == project_id)
        elif accessible_project_ids is not None:
            # Optional-scope IDOR guard: a non-admin caller who omits the
            # project_id filter sees only their accessible projects' workflows
            # plus workspace-level (NULL project) templates.
            base = base.where(
                (ApprovalWorkflow.project_id.in_(accessible_project_ids)) | (ApprovalWorkflow.project_id.is_(None))
            )
        if entity_type is not None:
            base = base.where(ApprovalWorkflow.entity_type == entity_type)
        if is_active is not None:
            base = base.where(ApprovalWorkflow.is_active == is_active)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ApprovalWorkflow.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, workflow: ApprovalWorkflow) -> ApprovalWorkflow:
        """Insert a new workflow."""
        self.session.add(workflow)
        await self.session.flush()
        return workflow

    async def update(self, workflow_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a workflow."""
        await apply_update(self.session, ApprovalWorkflow, workflow_id, **fields)

    async def delete(self, workflow_id: uuid.UUID) -> None:
        """Delete a workflow and its requests (cascade)."""
        workflow = await self.get(workflow_id)
        if workflow:
            await self.session.delete(workflow)
            await self.session.flush()


class ApprovalRequestRepository:
    """Data access for ApprovalRequest model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, request_id: uuid.UUID) -> ApprovalRequest | None:
        """Get approval request by ID."""
        return await self.session.get(ApprovalRequest, request_id)

    async def list(
        self,
        *,
        workflow_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        status: str | None = None,
        accessible_project_ids: set[uuid.UUID] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ApprovalRequest], int]:
        """List approval requests with filters and pagination.

        ``accessible_project_ids`` scopes the result to a non-admin caller's
        reachable projects when no explicit ``workflow_id`` filter is given.
        ``None`` means "do not scope" (admin / full view). A provided set
        restricts results to requests whose parent workflow's ``project_id``
        is in the set; requests under workspace-level templates (workflow
        ``project_id IS NULL``) stay visible to everyone. An empty set
        therefore yields only those template-workflow requests.
        """
        base = select(ApprovalRequest)

        if workflow_id is not None:
            base = base.where(ApprovalRequest.workflow_id == workflow_id)
        elif accessible_project_ids is not None:
            # Optional-scope IDOR guard: a non-admin caller who omits the
            # workflow_id filter sees only requests whose parent workflow
            # belongs to an accessible project (or is a workspace-level
            # template with no project). Scope via a subquery over the
            # accessible workflow ids.
            accessible_workflow_ids = select(ApprovalWorkflow.id).where(
                (ApprovalWorkflow.project_id.in_(accessible_project_ids)) | (ApprovalWorkflow.project_id.is_(None))
            )
            base = base.where(ApprovalRequest.workflow_id.in_(accessible_workflow_ids))
        if entity_type is not None:
            base = base.where(ApprovalRequest.entity_type == entity_type)
        if status is not None:
            base = base.where(ApprovalRequest.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ApprovalRequest.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, request: ApprovalRequest) -> ApprovalRequest:
        """Insert a new approval request."""
        self.session.add(request)
        await self.session.flush()
        return request

    async def update(self, request_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an approval request."""
        await apply_update(self.session, ApprovalRequest, request_id, **fields)
