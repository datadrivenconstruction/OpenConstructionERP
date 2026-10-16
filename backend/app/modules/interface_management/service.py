# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface-register service layer (multi-package coordination register).

Async data access on top of the module's own two tables plus the read-side
loaders that project persisted rows onto the pure
:class:`app.modules.interface_management.register.InterfaceRow` list fed to the
computation core. An action is only ever created, listed or mutated after its
parent interface is confirmed to belong to the same project
(:meth:`_require_interface_in_project`), so an action can never be attached
across projects even when the caller is authorised on their own project - the
defense-in-depth companion to the router's :func:`verify_project_access` gate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select

from app.modules.interface_management import register
from app.modules.interface_management.models import InterfaceAction, InterfaceRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.interface_management.schemas import (
        InterfaceActionCreate,
        InterfaceActionUpdate,
        InterfaceCreate,
        InterfaceUpdate,
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


def _to_action_row(row: InterfaceAction) -> register.ActionRow:
    """Project a persisted action row onto the pure :class:`register.ActionRow`."""
    return register.ActionRow(status=str(row.status), due_date=row.due_date)


def _to_interface_row(row: InterfaceRecord) -> register.InterfaceRow:
    """Project a persisted interface row (with its actions) onto :class:`register.InterfaceRow`."""
    return register.InterfaceRow(
        id=str(row.id) if row.id is not None else None,
        reference=str(row.reference or ""),
        title=str(row.title or ""),
        status=str(row.status),
        priority=row.priority,
        interface_type=row.interface_type,
        owner_party=row.owner_party,
        accepter_party=row.accepter_party,
        work_package_from=row.work_package_from,
        need_by_date=row.need_by_date,
        agreed_date=row.agreed_date,
        actions=[_to_action_row(a) for a in row.actions],
    )


class InterfaceManagementService:
    """Stateless business logic for the interface coordination register."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- Interfaces ---------------------------------------------------------

    async def create_interface(
        self,
        project_id: uuid.UUID,
        payload: InterfaceCreate,
        created_by: str | None,
    ) -> InterfaceRecord:
        """Create an interface (409 if the reference is already used)."""
        await self._require_unique_reference(project_id, payload.reference)
        interface = InterfaceRecord(
            project_id=project_id,
            reference=payload.reference,
            title=payload.title,
            description=payload.description,
            owner_party=payload.owner_party,
            owner_subcontractor_id=payload.owner_subcontractor_id,
            accepter_party=payload.accepter_party,
            accepter_subcontractor_id=payload.accepter_subcontractor_id,
            discipline_from=payload.discipline_from,
            discipline_to=payload.discipline_to,
            work_package_from=payload.work_package_from,
            work_package_to=payload.work_package_to,
            interface_type=payload.interface_type,
            status=payload.status,
            priority=payload.priority,
            need_by_date=payload.need_by_date,
            agreed_date=payload.agreed_date,
            closed_date=payload.closed_date,
            rfi_id=payload.rfi_id,
            schedule_activity_id=payload.schedule_activity_id,
            location=payload.location,
            sort_order=payload.sort_order,
            notes=payload.notes,
            created_by=_as_optional_uuid(created_by),
        )
        self.session.add(interface)
        await self.session.flush()
        return interface

    async def list_interfaces(
        self,
        project_id: uuid.UUID,
        *,
        interface_status: str | None = None,
        owner_subcontractor_id: uuid.UUID | None = None,
        work_package: str | None = None,
        interface_type: str | None = None,
        priority: str | None = None,
        party_clause: Any | None = None,
    ) -> list[InterfaceRecord]:
        """List a project's interfaces with optional filters.

        ``work_package`` matches an interface touching that package on either
        side (``work_package_from`` or ``work_package_to``), so a coordinator can
        pull every interface a package is involved in with one query.

        ``party_clause`` is the caller's party visibility filter
        (:func:`app.modules.teams.party_access.party_read_clause`); it can only
        remove rows.
        """
        stmt = select(InterfaceRecord).where(InterfaceRecord.project_id == project_id)
        if party_clause is not None:
            stmt = stmt.where(party_clause)
        if interface_status is not None:
            stmt = stmt.where(InterfaceRecord.status == interface_status)
        if owner_subcontractor_id is not None:
            stmt = stmt.where(InterfaceRecord.owner_subcontractor_id == owner_subcontractor_id)
        if work_package is not None:
            stmt = stmt.where(
                or_(
                    InterfaceRecord.work_package_from == work_package,
                    InterfaceRecord.work_package_to == work_package,
                ),
            )
        if interface_type is not None:
            stmt = stmt.where(InterfaceRecord.interface_type == interface_type)
        if priority is not None:
            stmt = stmt.where(InterfaceRecord.priority == priority)
        stmt = stmt.order_by(InterfaceRecord.sort_order.asc(), InterfaceRecord.created_at.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_interface(self, project_id: uuid.UUID, interface_id: uuid.UUID) -> InterfaceRecord | None:
        """Load one interface, scoped to the project (``None`` if foreign/absent)."""
        stmt = select(InterfaceRecord).where(
            InterfaceRecord.id == interface_id,
            InterfaceRecord.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_interface(self, project_id: uuid.UUID, interface_id: uuid.UUID) -> InterfaceRecord:
        """Load one in-project interface or raise 404 (missing or foreign alike)."""
        interface = await self.get_interface(project_id, interface_id)
        if interface is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interface not found in this project",
            )
        return interface

    async def update_interface(
        self,
        project_id: uuid.UUID,
        interface_id: uuid.UUID,
        payload: InterfaceUpdate,
    ) -> InterfaceRecord:
        """Patch an interface; only provided fields are changed."""
        interface = await self.require_interface(project_id, interface_id)
        data = payload.model_dump(exclude_unset=True)
        new_reference = data.get("reference")
        if new_reference is not None and new_reference != interface.reference:
            await self._require_unique_reference(project_id, new_reference, exclude_interface_id=interface_id)
        for key, value in data.items():
            setattr(interface, key, value)
        await self.session.flush()
        return interface

    async def delete_interface(self, project_id: uuid.UUID, interface_id: uuid.UUID) -> None:
        """Delete an in-project interface and its actions (404 if missing or foreign)."""
        interface = await self.require_interface(project_id, interface_id)
        await self.session.delete(interface)
        await self.session.flush()

    # -- Actions ------------------------------------------------------------

    async def create_action(
        self,
        project_id: uuid.UUID,
        interface_id: uuid.UUID,
        payload: InterfaceActionCreate,
        created_by: str | None,
    ) -> InterfaceAction:
        """Add an action to an interface, re-verifying the interface is in the project.

        The interface is confirmed to belong to ``project_id`` first, so the
        action's ``project_id`` (copied from the verified path project) and
        ``interface_id`` can never straddle two projects.
        """
        await self._require_interface_in_project(project_id, interface_id)
        action = InterfaceAction(
            project_id=project_id,
            interface_id=interface_id,
            description=payload.description,
            action_party=payload.action_party,
            due_date=payload.due_date,
            status=payload.status,
            completed_date=payload.completed_date,
            created_by=_as_optional_uuid(created_by),
        )
        self.session.add(action)
        await self.session.flush()
        return action

    async def list_actions(
        self,
        project_id: uuid.UUID,
        *,
        interface_id: uuid.UUID | None = None,
        action_status: str | None = None,
        party_clause: Any | None = None,
    ) -> list[InterfaceAction]:
        """List a project's actions with optional interface / status filters.

        When an ``interface_id`` is given it is first confirmed to belong to the
        project, so listing another project's interface's actions by id is a 404.
        """
        if interface_id is not None:
            await self._require_interface_in_project(project_id, interface_id)
        stmt = select(InterfaceAction).where(InterfaceAction.project_id == project_id)
        if party_clause is not None:
            # An action is visible exactly when its interface is.
            stmt = stmt.where(InterfaceAction.interface_id.in_(select(InterfaceRecord.id).where(party_clause)))
        if interface_id is not None:
            stmt = stmt.where(InterfaceAction.interface_id == interface_id)
        if action_status is not None:
            stmt = stmt.where(InterfaceAction.status == action_status)
        stmt = stmt.order_by(InterfaceAction.created_at.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_action(self, project_id: uuid.UUID, action_id: uuid.UUID) -> InterfaceAction | None:
        """Load one action, scoped to the project (``None`` if foreign/absent)."""
        stmt = select(InterfaceAction).where(
            InterfaceAction.id == action_id,
            InterfaceAction.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_action(self, project_id: uuid.UUID, action_id: uuid.UUID) -> InterfaceAction:
        """Load one in-project action or raise 404 (missing or foreign alike)."""
        action = await self.get_action(project_id, action_id)
        if action is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interface action not found in this project",
            )
        return action

    async def update_action(
        self,
        project_id: uuid.UUID,
        action_id: uuid.UUID,
        payload: InterfaceActionUpdate,
    ) -> InterfaceAction:
        """Patch (or close) an action; only provided fields are changed."""
        action = await self.require_action(project_id, action_id)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(action, key, value)
        await self.session.flush()
        return action

    # -- Derived register (DB loaders + pure core) --------------------------

    async def build_register(
        self,
        project_id: uuid.UUID,
        as_of: date | None = None,
        party_clause: Any | None = None,
    ) -> dict:
        """Full interface register rollup for a project."""
        as_of = as_of or datetime.now(UTC).date()
        interfaces = [_to_interface_row(r) for r in await self.list_interfaces(project_id, party_clause=party_clause)]
        report = register.build_report(interfaces, as_of=as_of)
        payload = report.to_dict()
        payload["project_id"] = str(project_id)
        return payload

    async def get_work_package_health(
        self,
        project_id: uuid.UUID,
        as_of: date | None = None,
        party_clause: Any | None = None,
    ) -> dict:
        """Per-work-package health plus the overdue and disputed interface lists."""
        as_of = as_of or datetime.now(UTC).date()
        interfaces = [_to_interface_row(r) for r in await self.list_interfaces(project_id, party_clause=party_clause)]
        packages = register.work_package_health(interfaces, as_of)
        overdue = register.overdue_interfaces(interfaces, as_of)
        disputed = register.disputed_interfaces(interfaces)
        return {
            "project_id": str(project_id),
            "as_of": as_of.isoformat(),
            "total": len(interfaces),
            "is_healthy": register.is_healthy(interfaces, as_of),
            "work_packages": [p.to_dict() for p in packages],
            "overdue": [i.to_ref() for i in overdue],
            "disputed": [i.to_ref() for i in disputed],
        }

    # -- Ownership / integrity guards ---------------------------------------

    async def _require_interface_in_project(
        self,
        project_id: uuid.UUID,
        interface_id: uuid.UUID,
    ) -> InterfaceRecord:
        """Confirm an interface id references an interface in this project, else 404.

        The linchpin of the module's IDOR defence: an action can only ever be
        attached to (or listed under) an interface that belongs to the same
        project, so a foreign interface id smuggled onto a create / list is
        rejected even though the caller passed the project access gate.
        """
        stmt = select(InterfaceRecord).where(
            InterfaceRecord.id == interface_id,
            InterfaceRecord.project_id == project_id,
        )
        interface = (await self.session.execute(stmt)).scalar_one_or_none()
        if interface is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interface not found in this project",
            )
        return interface

    async def _require_unique_reference(
        self,
        project_id: uuid.UUID,
        reference: str,
        *,
        exclude_interface_id: uuid.UUID | None = None,
    ) -> None:
        """Raise 409 when ``reference`` is already used by another interface in the project.

        Enforces the ``uq_interface_mgmt_project_reference`` constraint with a
        friendly conflict instead of letting a duplicate surface as a raw DB
        integrity error on flush.
        """
        stmt = select(InterfaceRecord.id).where(
            InterfaceRecord.project_id == project_id,
            InterfaceRecord.reference == reference,
        )
        if exclude_interface_id is not None:
            stmt = stmt.where(InterfaceRecord.id != exclude_interface_id)
        if (await self.session.execute(stmt)).first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An interface with reference {reference!r} already exists in this project",
            )
