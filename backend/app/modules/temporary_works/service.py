# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Temporary-works service layer (safety-critical governance register).

Async data access on top of the module's own two tables plus the read-side
loaders that project persisted rows onto the pure
:class:`app.modules.temporary_works.register.RegisterItem` list fed to the
computation core. A permit is only ever created or mutated after its parent item
is confirmed to belong to the same project (:meth:`_require_item_in_project`), so
a permit can never be attached across projects even when the caller is authorised
on their own project - the defense-in-depth companion to the router's
:func:`verify_project_access` gate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select

from app.modules.temporary_works import register
from app.modules.temporary_works.models import TemporaryWorksItem, TemporaryWorksPermit

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.temporary_works.schemas import (
        TemporaryWorksItemCreate,
        TemporaryWorksItemUpdate,
        TemporaryWorksPermitCreate,
        TemporaryWorksPermitUpdate,
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


def _to_register_permit(row: TemporaryWorksPermit) -> register.RegisterPermit:
    """Project a persisted permit row onto the pure :class:`register.RegisterPermit`."""
    return register.RegisterPermit(
        permit_type=str(row.permit_type),
        status=str(row.status),
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        prereq_design_check_accepted=bool(row.prereq_design_check_accepted),
        prereq_inspection_passed=bool(row.prereq_inspection_passed),
    )


def _to_register_item(row: TemporaryWorksItem) -> register.RegisterItem:
    """Project a persisted item row (with its permits) onto :class:`register.RegisterItem`."""
    return register.RegisterItem(
        id=str(row.id) if row.id is not None else None,
        reference=str(row.reference or ""),
        title=str(row.title or ""),
        tw_type=str(row.tw_type),
        design_check_category=row.design_check_category,
        status=str(row.status),
        required_load_date=row.required_load_date,
        required_strike_date=row.required_strike_date,
        permits=[_to_register_permit(p) for p in row.permits],
    )


class TemporaryWorksService:
    """Stateless business logic for the temporary-works governance register."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- Items --------------------------------------------------------------

    async def create_item(
        self,
        project_id: uuid.UUID,
        payload: TemporaryWorksItemCreate,
        created_by: str | None,
    ) -> TemporaryWorksItem:
        """Create a temporary-works item (409 if the reference is already used)."""
        await self._require_unique_reference(project_id, payload.reference)
        item = TemporaryWorksItem(
            project_id=project_id,
            reference=payload.reference,
            title=payload.title,
            description=payload.description,
            tw_type=payload.tw_type,
            design_check_category=payload.design_check_category,
            designer_name=payload.designer_name,
            checker_name=payload.checker_name,
            twc_name=payload.twc_name,
            twc_user_id=payload.twc_user_id,
            status=payload.status,
            required_load_date=payload.required_load_date,
            required_strike_date=payload.required_strike_date,
            design_due_date=payload.design_due_date,
            location=payload.location,
            sort_order=payload.sort_order,
            notes=payload.notes,
            formwork_assignment_id=payload.formwork_assignment_id,
            design_document_id=payload.design_document_id,
            check_certificate_document_id=payload.check_certificate_document_id,
            schedule_activity_id=payload.schedule_activity_id,
            created_by=_as_optional_uuid(created_by),
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_items(
        self,
        project_id: uuid.UUID,
        *,
        tw_type: str | None = None,
        item_status: str | None = None,
        category: str | None = None,
    ) -> list[TemporaryWorksItem]:
        """List a project's items with optional type / status / category filters."""
        stmt = select(TemporaryWorksItem).where(TemporaryWorksItem.project_id == project_id)
        if tw_type is not None:
            stmt = stmt.where(TemporaryWorksItem.tw_type == tw_type)
        if item_status is not None:
            stmt = stmt.where(TemporaryWorksItem.status == item_status)
        if category is not None:
            stmt = stmt.where(TemporaryWorksItem.design_check_category == category)
        stmt = stmt.order_by(TemporaryWorksItem.sort_order.asc(), TemporaryWorksItem.created_at.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> TemporaryWorksItem | None:
        """Load one item, scoped to the project (``None`` if foreign/absent)."""
        stmt = select(TemporaryWorksItem).where(
            TemporaryWorksItem.id == item_id,
            TemporaryWorksItem.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> TemporaryWorksItem:
        """Load one in-project item or raise 404 (missing or foreign alike)."""
        item = await self.get_item(project_id, item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Temporary works item not found in this project",
            )
        return item

    async def update_item(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: TemporaryWorksItemUpdate,
    ) -> TemporaryWorksItem:
        """Patch a temporary-works item; only provided fields are changed."""
        item = await self.require_item(project_id, item_id)
        data = payload.model_dump(exclude_unset=True)
        new_reference = data.get("reference")
        if new_reference is not None and new_reference != item.reference:
            await self._require_unique_reference(project_id, new_reference, exclude_item_id=item_id)
        for key, value in data.items():
            setattr(item, key, value)
        await self.session.flush()
        return item

    async def delete_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> None:
        """Delete an in-project item and its permits (404 if missing or foreign)."""
        item = await self.require_item(project_id, item_id)
        await self.session.delete(item)
        await self.session.flush()

    # -- Permits ------------------------------------------------------------

    async def create_permit(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: TemporaryWorksPermitCreate,
        created_by: str | None,
    ) -> TemporaryWorksPermit:
        """Issue a permit against an item, re-verifying the item is in the project.

        The item is confirmed to belong to ``project_id`` first, so the permit's
        ``project_id`` (copied from the verified path project) and ``item_id``
        can never straddle two projects.
        """
        await self._require_item_in_project(project_id, item_id)
        permit = TemporaryWorksPermit(
            project_id=project_id,
            item_id=item_id,
            permit_number=payload.permit_number,
            permit_type=payload.permit_type,
            status=payload.status,
            issued_by=payload.issued_by,
            issued_at=payload.issued_at,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            closed_at=payload.closed_at,
            closed_by=payload.closed_by,
            inspection_id=payload.inspection_id,
            prereq_design_check_accepted=payload.prereq_design_check_accepted,
            prereq_inspection_passed=payload.prereq_inspection_passed,
            conditions=payload.conditions,
            created_by=_as_optional_uuid(created_by),
        )
        self.session.add(permit)
        await self.session.flush()
        return permit

    async def list_permits(
        self,
        project_id: uuid.UUID,
        *,
        item_id: uuid.UUID | None = None,
        permit_status: str | None = None,
    ) -> list[TemporaryWorksPermit]:
        """List a project's permits with optional item / status filters.

        When an ``item_id`` is given it is first confirmed to belong to the
        project, so listing another project's item's permits by id is a 404.
        """
        if item_id is not None:
            await self._require_item_in_project(project_id, item_id)
        stmt = select(TemporaryWorksPermit).where(TemporaryWorksPermit.project_id == project_id)
        if item_id is not None:
            stmt = stmt.where(TemporaryWorksPermit.item_id == item_id)
        if permit_status is not None:
            stmt = stmt.where(TemporaryWorksPermit.status == permit_status)
        stmt = stmt.order_by(TemporaryWorksPermit.created_at.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_permit(self, project_id: uuid.UUID, permit_id: uuid.UUID) -> TemporaryWorksPermit | None:
        """Load one permit, scoped to the project (``None`` if foreign/absent)."""
        stmt = select(TemporaryWorksPermit).where(
            TemporaryWorksPermit.id == permit_id,
            TemporaryWorksPermit.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_permit(self, project_id: uuid.UUID, permit_id: uuid.UUID) -> TemporaryWorksPermit:
        """Load one in-project permit or raise 404 (missing or foreign alike)."""
        permit = await self.get_permit(project_id, permit_id)
        if permit is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Temporary works permit not found in this project",
            )
        return permit

    async def update_permit(
        self,
        project_id: uuid.UUID,
        permit_id: uuid.UUID,
        payload: TemporaryWorksPermitUpdate,
    ) -> TemporaryWorksPermit:
        """Patch (or close) a permit; only provided fields are changed."""
        permit = await self.require_permit(project_id, permit_id)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(permit, key, value)
        await self.session.flush()
        return permit

    # -- Derived register (DB loaders + pure core) --------------------------

    async def build_register(
        self,
        project_id: uuid.UUID,
        as_of: date | None = None,
    ) -> dict:
        """Full temporary-works register rollup for a project."""
        as_of = as_of or datetime.now(UTC).date()
        items = [_to_register_item(r) for r in await self.list_items(project_id)]
        report = register.build_report(items, as_of=as_of)
        payload = report.to_dict()
        payload["project_id"] = str(project_id)
        return payload

    async def get_load_status(
        self,
        project_id: uuid.UUID,
        as_of: date | None = None,
    ) -> dict:
        """Per-item load / strike gate summary plus the compliance-breach list."""
        as_of = as_of or datetime.now(UTC).date()
        items = [_to_register_item(r) for r in await self.list_items(project_id)]
        gate_statuses = [register.item_gate_status(item, as_of) for item in items]
        breaches = register.compliance_breaches(items, as_of)
        return {
            "project_id": str(project_id),
            "as_of": as_of.isoformat(),
            "total": len(items),
            "is_compliant": not breaches,
            "gate_statuses": [g.to_dict() for g in gate_statuses],
            "compliance_breaches": breaches,
        }

    # -- Ownership / integrity guards ---------------------------------------

    async def _require_item_in_project(self, project_id: uuid.UUID, item_id: uuid.UUID) -> TemporaryWorksItem:
        """Confirm an item id references an item in this project, else 404.

        The linchpin of the module's IDOR defence: a permit can only ever be
        attached to (or listed under) an item that belongs to the same project,
        so a foreign item id smuggled onto a create / list is rejected even
        though the caller passed the project access gate.
        """
        stmt = select(TemporaryWorksItem).where(
            TemporaryWorksItem.id == item_id,
            TemporaryWorksItem.project_id == project_id,
        )
        item = (await self.session.execute(stmt)).scalar_one_or_none()
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Temporary works item not found in this project",
            )
        return item

    async def _require_unique_reference(
        self,
        project_id: uuid.UUID,
        reference: str,
        *,
        exclude_item_id: uuid.UUID | None = None,
    ) -> None:
        """Raise 409 when ``reference`` is already used by another item in the project.

        Enforces the ``uq_temp_works_item_project_reference`` constraint with a
        friendly conflict instead of letting a duplicate surface as a raw DB
        integrity error on flush.
        """
        stmt = select(TemporaryWorksItem.id).where(
            TemporaryWorksItem.project_id == project_id,
            TemporaryWorksItem.reference == reference,
        )
        if exclude_item_id is not None:
            stmt = stmt.where(TemporaryWorksItem.id != exclude_item_id)
        if (await self.session.execute(stmt)).first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A temporary works item with reference {reference!r} already exists in this project",
            )
