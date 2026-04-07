"""Enterprise Workflows data access layer.

All database queries for workflow entities live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ApprovalWorkflow], int]:
        """List workflows with filters and pagination."""
        base = select(ApprovalWorkflow)

        if project_id is not None:
            base = base.where(ApprovalWorkflow.project_id == project_id)
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
        stmt = (
            update(ApprovalWorkflow)
            .where(ApprovalWorkflow.id == workflow_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

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
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ApprovalRequest], int]:
        """List approval requests with filters and pagination."""
        base = select(ApprovalRequest)

        if workflow_id is not None:
            base = base.where(ApprovalRequest.workflow_id == workflow_id)
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
        stmt = (
            update(ApprovalRequest)
            .where(ApprovalRequest.id == request_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()
