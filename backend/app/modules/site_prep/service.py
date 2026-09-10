# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-prep service layer (pre-construction mobilisation readiness).

Business logic delegating data access to :mod:`app.modules.site_prep.repository`
and projecting persisted rows onto the pure
:class:`app.modules.site_prep.readiness.ReadinessItem` list fed to the
computation core. Every referenced ``plan_id`` is confirmed to belong to the same
project before it is written to an item, so an item can never be attached to
another project's plan even when the caller is authorised on their own project -
the defense-in-depth companion to the router's :func:`verify_project_access` gate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from app.modules.site_prep import readiness
from app.modules.site_prep.models import SitePrepItem, SitePrepPlan
from app.modules.site_prep.repository import SitePrepItemRepository, SitePrepPlanRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.site_prep.schemas import (
        SitePrepItemCreate,
        SitePrepItemUpdate,
        SitePrepPlanCreate,
        SitePrepPlanUpdate,
    )


def _as_optional_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Coerce an actor id to ``uuid.UUID`` or ``None`` (never raise).

    The current user id arrives as the JWT subject string; a well-formed value
    is stored as a proper GUID, and anything unparseable is stored as ``None``
    rather than corrupting the ``created_by`` column.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _to_readiness_item(row: SitePrepItem) -> readiness.ReadinessItem:
    """Project a persisted item row onto the pure :class:`readiness.ReadinessItem`."""
    return readiness.ReadinessItem(
        category=str(row.category),
        status=str(row.status),
        is_gate=bool(row.is_gate),
        due_date=row.due_date,
        title=str(row.title or ""),
        item_id=str(row.id) if row.id is not None else None,
        completed_date=row.completed_date,
    )


class SitePrepService:
    """Stateless business logic for pre-construction mobilisation readiness."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._plan_repo = SitePrepPlanRepository(session)
        self._item_repo = SitePrepItemRepository(session)

    # -- Plan ---------------------------------------------------------------

    async def get_plan(self, project_id: uuid.UUID) -> SitePrepPlan | None:
        """Load the project's mobilisation plan (``None`` if none exists yet)."""
        return await self._plan_repo.get_by_project(project_id)

    async def require_plan(self, project_id: uuid.UUID) -> SitePrepPlan:
        """Load the project's plan or raise 404 when it has not been created."""
        plan = await self.get_plan(project_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mobilisation plan not found for this project",
            )
        return plan

    async def create_plan(
        self,
        project_id: uuid.UUID,
        payload: SitePrepPlanCreate,
        created_by: str | None,
    ) -> SitePrepPlan:
        """Create the project's single mobilisation plan (409 if one exists)."""
        if await self.get_plan(project_id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A mobilisation plan already exists for this project",
            )
        plan = SitePrepPlan(
            project_id=project_id,
            target_start_date=payload.target_start_date,
            status=payload.status,
            notes=payload.notes,
            created_by=_as_optional_uuid(created_by),
        )
        return await self._plan_repo.create(plan)

    async def update_plan(
        self,
        project_id: uuid.UUID,
        payload: SitePrepPlanUpdate,
    ) -> SitePrepPlan:
        """Patch the project's plan; only provided fields are changed."""
        plan = await self.require_plan(project_id)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(plan, key, value)
        await self.session.flush()
        return plan

    # -- Items --------------------------------------------------------------

    async def create_item(
        self,
        project_id: uuid.UUID,
        payload: SitePrepItemCreate,
        created_by: str | None,
    ) -> SitePrepItem:
        """Create a readiness item, re-verifying any referenced plan in-project."""
        if payload.plan_id is not None:
            await self._require_plan_in_project(project_id, payload.plan_id)
        item = SitePrepItem(
            project_id=project_id,
            plan_id=payload.plan_id,
            category=payload.category,
            title=payload.title,
            description=payload.description,
            status=payload.status,
            responsible_party=payload.responsible_party,
            due_date=payload.due_date,
            completed_date=payload.completed_date,
            is_gate=payload.is_gate,
            sort_order=payload.sort_order,
            notes=payload.notes,
            created_by=_as_optional_uuid(created_by),
        )
        return await self._item_repo.create(item)

    async def list_items(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        item_status: str | None = None,
    ) -> list[SitePrepItem]:
        """List a project's readiness items with optional category / status filter."""
        return await self._item_repo.list_by_project(project_id, category=category, status=item_status)

    async def get_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> SitePrepItem | None:
        """Load one item, scoped to the project (``None`` if foreign/absent)."""
        return await self._item_repo.get_by_id_and_project(item_id, project_id)

    async def require_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> SitePrepItem:
        """Load one in-project item or raise 404 (missing or foreign alike)."""
        item = await self.get_item(project_id, item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Readiness item not found in this project",
            )
        return item

    async def update_item(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: SitePrepItemUpdate,
    ) -> SitePrepItem:
        """Patch a readiness item; re-verify a new plan_id belongs to the project."""
        item = await self.require_item(project_id, item_id)
        data = payload.model_dump(exclude_unset=True)
        if "plan_id" in data and data["plan_id"] is not None:
            await self._require_plan_in_project(project_id, data["plan_id"])
        for key, value in data.items():
            setattr(item, key, value)
        await self.session.flush()
        return item

    async def delete_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> None:
        """Delete an in-project readiness item (404 if missing or foreign)."""
        item = await self.require_item(project_id, item_id)
        await self._item_repo.delete(item)

    # -- Derived readiness (DB loaders + pure core) -------------------------

    async def get_readiness(
        self,
        project_id: uuid.UUID,
        as_of: date | None = None,
    ) -> dict:
        """Full mobilisation readiness rollup for a project."""
        as_of = as_of or datetime.now(UTC).date()
        target = await self._target_start_date(project_id)
        items = [_to_readiness_item(r) for r in await self.list_items(project_id)]
        report = readiness.build_report(items, target_start_date=target, as_of=as_of)
        payload = report.to_dict()
        payload["project_id"] = str(project_id)
        return payload

    async def get_gate_status(
        self,
        project_id: uuid.UUID,
        as_of: date | None = None,
    ) -> dict:
        """Commencement-gate status: are all hard prerequisites satisfied."""
        as_of = as_of or datetime.now(UTC).date()
        target = await self._target_start_date(project_id)
        items = [_to_readiness_item(r) for r in await self.list_items(project_id)]

        gates = readiness.gate_items(items)
        blocking = readiness.blocking_gate_items(items)
        return {
            "project_id": str(project_id),
            "as_of": as_of.isoformat(),
            "target_start_date": target.isoformat() if target is not None else None,
            "days_to_target": readiness.days_to_target(target, as_of),
            "gate_ready": readiness.gate_ready(items),
            "on_track": readiness.on_track(items, target, as_of),
            "gate_total": len(gates),
            "gate_ready_count": len(gates) - len(blocking),
            "gate_blocking": [i.to_dict() for i in blocking],
        }

    # -- Ownership guards ---------------------------------------------------

    async def _target_start_date(self, project_id: uuid.UUID) -> date | None:
        """The project plan's target start date, or ``None`` when no plan exists."""
        plan = await self.get_plan(project_id)
        return plan.target_start_date if plan is not None else None

    async def _require_plan_in_project(self, project_id: uuid.UUID, plan_id: uuid.UUID) -> None:
        """Confirm a plan id references a plan in this project, else 404.

        The linchpin of the module's IDOR defence: an item can only ever point at
        its own project's mobilisation plan, so a foreign plan id smuggled onto a
        create / update is rejected even though the caller passed the project
        access gate.
        """
        if not await self._plan_repo.plan_exists_for_project(project_id, plan_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mobilisation plan not found in this project",
            )
