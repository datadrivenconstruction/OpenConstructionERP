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

Status history. Every status an interface takes is written to
``oe_interface_mgmt_history`` by :meth:`InterfaceManagementService._record`, in
the same transaction as the change, so an interface can never move without a
trace; the same entry is mirrored into the platform activity log and announced
on the event bus as ``interface_management.interface.status_changed`` once the
transaction commits. Approval verdicts arrive the other way round: approval_routes
publishes ``approval_routes.instance.*`` and :mod:`.events` turns the ones aimed
at an interface into history entries (and, for an approval, the move to agreed)
through :meth:`InterfaceManagementService.apply_approval_event`.

Validated links. ``schedule_activity_id`` must name an activity in one of the
project's schedules and ``rfi_id`` an RFI of the project; anything else is a 422
at write time, and the ``interface_management`` rule set re-checks stored links.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.modules.interface_management import register
from app.modules.interface_management.models import (
    InterfaceAction,
    InterfaceHistoryEntry,
    InterfaceRecord,
)

logger = logging.getLogger(__name__)

# The approval-routes target kind an interface agreement is routed under.
APPROVAL_TARGET_KIND = "interface"
STATUS_CHANGED_EVENT = "interface_management.interface.status_changed"

# History event names (the ``event`` column).
EVENT_CREATED = "created"
EVENT_STATUS_CHANGED = "status_changed"
EVENT_APPROVAL_REQUESTED = "approval_requested"
EVENT_APPROVAL_APPROVED = "approval_approved"
EVENT_APPROVAL_REJECTED = "approval_rejected"
EVENT_APPROVAL_CANCELLED = "approval_cancelled"
HISTORY_EVENTS: tuple[str, ...] = (
    EVENT_CREATED,
    EVENT_STATUS_CHANGED,
    EVENT_APPROVAL_REQUESTED,
    EVENT_APPROVAL_APPROVED,
    EVENT_APPROVAL_REJECTED,
    EVENT_APPROVAL_CANCELLED,
)

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
        opened_on=row.created_at.date() if row.created_at is not None else None,
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
        """Create an interface (409 if the reference is already used, 422 on a foreign link).

        The first history entry (``created``, no from-status) is written with it.
        An interface created straight into ``agreed`` or ``closed`` gets today as
        its agreed date when none is given, so the register never holds an
        agreement without a date.
        """
        await self._require_unique_reference(project_id, payload.reference)
        await self._require_links(project_id, rfi_id=payload.rfi_id, activity_id=payload.schedule_activity_id)
        today = datetime.now(UTC).date()
        agreed_date = payload.agreed_date
        if agreed_date is None and payload.status in ("agreed", "closed"):
            agreed_date = today
        closed_date = payload.closed_date
        if closed_date is None and payload.status == "closed":
            closed_date = today
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
            agreed_date=agreed_date,
            closed_date=closed_date,
            rfi_id=str(payload.rfi_id) if payload.rfi_id is not None else None,
            schedule_activity_id=payload.schedule_activity_id,
            location=payload.location,
            sort_order=payload.sort_order,
            notes=payload.notes,
            created_by=_as_optional_uuid(created_by),
        )
        self.session.add(interface)
        await self.session.flush()
        await self._record(
            interface,
            event=EVENT_CREATED,
            from_status=None,
            to_status=interface.status,
            actor_id=_as_optional_uuid(created_by),
        )
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
    ) -> list[InterfaceRecord]:
        """List a project's interfaces with optional filters.

        ``work_package`` matches an interface touching that package on either
        side (``work_package_from`` or ``work_package_to``), so a coordinator can
        pull every interface a package is involved in with one query.
        """
        stmt = select(InterfaceRecord).where(InterfaceRecord.project_id == project_id)
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
        actor_id: str | uuid.UUID | None = None,
    ) -> InterfaceRecord:
        """Patch an interface; only provided fields are changed.

        A status move is checked before anything is written: ``closed`` only
        from ``agreed`` (422), and ``agreed`` by hand is refused while the
        interface's latest approval route is pending or was rejected (409) - the
        route decides then, not the editor. Moving to ``agreed`` / ``closed``
        stamps today's agreed / closed date when the patch does not carry one.
        Each move writes one history entry with ``status_comment`` as its note.
        Changed links are re-checked against the project (422 on a foreign or
        missing RFI or schedule activity).
        """
        interface = await self.require_interface(project_id, interface_id)
        data = payload.model_dump(exclude_unset=True)
        comment = data.pop("status_comment", None)
        new_reference = data.get("reference")
        if new_reference is not None and new_reference != interface.reference:
            await self._require_unique_reference(project_id, new_reference, exclude_interface_id=interface_id)
        if data.get("rfi_id") is not None:
            data["rfi_id"] = str(data["rfi_id"])
        # Only a link the patch actually changes is checked: a form that sends
        # every field back must not be refused over a link that went stale
        # after it was made (the rule set reports those instead).
        new_rfi = data.get("rfi_id") if data.get("rfi_id") != interface.rfi_id else None
        new_activity = (
            data.get("schedule_activity_id")
            if data.get("schedule_activity_id") != interface.schedule_activity_id
            else None
        )
        await self._require_links(
            project_id,
            rfi_id=uuid.UUID(new_rfi) if new_rfi else None,
            activity_id=new_activity,
        )

        previous_status = str(interface.status)
        new_status = data.get("status")
        if new_status is None:
            data.pop("status", None)
        moving = new_status is not None and new_status != previous_status
        if moving:
            problem = register.transition_problem(previous_status, new_status)
            if problem is not None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=problem)
            if new_status == "agreed":
                await self._require_route_allows_agreement(interface.id)
            today = datetime.now(UTC).date()
            if new_status in ("agreed", "closed") and data.get("agreed_date", interface.agreed_date) is None:
                data["agreed_date"] = today
            if new_status == "closed" and data.get("closed_date", interface.closed_date) is None:
                data["closed_date"] = today

        for key, value in data.items():
            setattr(interface, key, value)
        await self.session.flush()
        if moving:
            await self._record(
                interface,
                event=EVENT_STATUS_CHANGED,
                from_status=previous_status,
                to_status=str(new_status),
                actor_id=_as_optional_uuid(actor_id),
                comment=comment,
            )
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
    ) -> list[InterfaceAction]:
        """List a project's actions with optional interface / status filters.

        When an ``interface_id`` is given it is first confirmed to belong to the
        project, so listing another project's interface's actions by id is a 404.
        """
        if interface_id is not None:
            await self._require_interface_in_project(project_id, interface_id)
        stmt = select(InterfaceAction).where(InterfaceAction.project_id == project_id)
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
    ) -> dict:
        """Full interface register rollup for a project."""
        as_of = as_of or datetime.now(UTC).date()
        interfaces = [_to_interface_row(r) for r in await self.list_interfaces(project_id)]
        report = register.build_report(interfaces, as_of=as_of)
        payload = report.to_dict()
        payload["project_id"] = str(project_id)
        return payload

    async def get_work_package_health(
        self,
        project_id: uuid.UUID,
        as_of: date | None = None,
    ) -> dict:
        """Per-work-package health plus the overdue and disputed interface lists."""
        as_of = as_of or datetime.now(UTC).date()
        interfaces = [_to_interface_row(r) for r in await self.list_interfaces(project_id)]
        packages = register.work_package_health(interfaces, as_of)
        overdue = register.overdue_interfaces(interfaces, as_of)
        disputed = register.disputed_interfaces(interfaces)
        return {
            "project_id": str(project_id),
            "as_of": as_of.isoformat(),
            "total": len(interfaces),
            "is_healthy": register.is_healthy(interfaces, as_of),
            "work_packages": [p.to_dict() for p in packages],
            "overdue": [i.to_ref(as_of) for i in overdue],
            "disputed": [i.to_ref(as_of) for i in disputed],
        }

    # -- Status history -----------------------------------------------------

    async def list_history(self, project_id: uuid.UUID, interface_id: uuid.UUID) -> list[dict[str, Any]]:
        """An interface's status history, oldest first, with the actor's display name.

        404 when the interface is not in the project, so a foreign interface id
        never reveals whether it exists.
        """
        await self._require_interface_in_project(project_id, interface_id)
        stmt = (
            select(InterfaceHistoryEntry)
            .where(
                InterfaceHistoryEntry.project_id == project_id,
                InterfaceHistoryEntry.interface_id == interface_id,
            )
            .order_by(InterfaceHistoryEntry.changed_at.asc(), InterfaceHistoryEntry.created_at.asc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        names = await self._user_names({r.actor_id for r in rows if r.actor_id is not None})
        return [
            {
                "id": r.id,
                "interface_id": r.interface_id,
                "event": r.event,
                "from_status": r.from_status,
                "to_status": r.to_status,
                "actor_id": r.actor_id,
                "actor_name": names.get(r.actor_id) if r.actor_id is not None else None,
                "comment": r.comment,
                "approval_instance_id": r.approval_instance_id,
                "changed_at": r.changed_at,
            }
            for r in rows
        ]

    async def _record(
        self,
        interface: InterfaceRecord,
        *,
        event: str,
        from_status: str | None,
        to_status: str | None,
        actor_id: uuid.UUID | None,
        comment: str | None = None,
        approval_instance_id: uuid.UUID | None = None,
    ) -> InterfaceHistoryEntry:
        """Write one history entry, mirror it to the activity log and announce it after commit.

        The history row is the record of truth and shares the caller's
        transaction. The activity-log mirror keeps the platform-wide audit trail
        complete; it runs in its own savepoint and cannot break the write. The
        bus event fires only once the transaction commits, so no subscriber is
        told about a change that was rolled back.
        """
        now = datetime.now(UTC)
        entry = InterfaceHistoryEntry(
            project_id=interface.project_id,
            interface_id=interface.id,
            event=event,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor_id,
            comment=comment,
            approval_instance_id=approval_instance_id,
            changed_at=now,
        )
        self.session.add(entry)
        await self.session.flush()
        await log_activity(
            self.session,
            actor_id=actor_id,
            entity_type="interface",
            entity_id=str(interface.id),
            action=event,
            from_status=from_status,
            to_status=to_status,
            reason=comment,
            module="interface_management",
            parent_entity_type="project",
            parent_entity_id=str(interface.project_id),
            metadata={"reference": interface.reference}
            | ({"approval_instance_id": str(approval_instance_id)} if approval_instance_id else {}),
        )
        publish_after_commit(
            self.session,
            STATUS_CHANGED_EVENT,
            {
                "project_id": str(interface.project_id),
                "interface_id": str(interface.id),
                "reference": interface.reference,
                "event": event,
                "from_status": from_status,
                "to_status": to_status,
                "actor_id": str(actor_id) if actor_id else None,
                "comment": comment,
                "approval_instance_id": str(approval_instance_id) if approval_instance_id else None,
                "changed_at": now.isoformat(),
            },
            source_module="interface_management",
        )
        return entry

    # -- Approval routing ---------------------------------------------------

    async def latest_approval(self, interface_id: uuid.UUID) -> Any | None:
        """The most recent approval-routes instance started against this interface, if any."""
        from app.modules.approval_routes.models import Instance

        stmt = (
            select(Instance)
            .where(Instance.target_kind == APPROVAL_TARGET_KIND, Instance.target_id == interface_id)
            .order_by(Instance.started_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _require_route_allows_agreement(self, interface_id: uuid.UUID) -> None:
        """Refuse a manual move to ``agreed`` while the interface's approval route has not granted it (409).

        No route ever started, or the last one cancelled, leaves the move to the
        editor. A pending route has to finish first; a rejected one means the
        agreement was refused and has to be routed again.
        """
        latest = await self.latest_approval(interface_id)
        if latest is None or latest.status in ("approved", "cancelled"):
            return
        detail = (
            "The interface agreement is waiting on its approval route"
            if latest.status == "pending"
            else "The interface agreement was rejected on its approval route; route it again"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    async def apply_approval_event(
        self,
        interface_id: uuid.UUID,
        *,
        verdict: str,
        instance_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        comment: str | None = None,
    ) -> bool:
        """Record an approval-routes lifecycle event on the interface it was aimed at.

        ``verdict`` is ``started``, ``approved``, ``rejected`` or ``cancelled``.
        An approval moves the interface to ``agreed`` (stamping the agreed date)
        unless it already is agreed or closed; every other verdict leaves the
        status where it is and only records the entry. Returns ``False`` when
        the interface no longer exists.
        """
        interface = await self.session.get(InterfaceRecord, interface_id)
        if interface is None:
            return False
        current = str(interface.status)
        if verdict == "started":
            event, to_status = EVENT_APPROVAL_REQUESTED, current
        elif verdict == "approved":
            event = EVENT_APPROVAL_APPROVED
            to_status = current if current in ("agreed", "closed") else "agreed"
            if to_status != current:
                interface.status = to_status
                if interface.agreed_date is None:
                    interface.agreed_date = datetime.now(UTC).date()
                await self.session.flush()
        elif verdict == "rejected":
            event, to_status = EVENT_APPROVAL_REJECTED, current
        elif verdict == "cancelled":
            event, to_status = EVENT_APPROVAL_CANCELLED, current
        else:
            return False
        await self._record(
            interface,
            event=event,
            from_status=current,
            to_status=to_status,
            actor_id=actor_id,
            comment=comment,
            approval_instance_id=instance_id,
        )
        return True

    # -- Validation ---------------------------------------------------------

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The dict the ``interface_management`` rule set reads, links already resolved.

        Each interface row carries whether its schedule activity and RFI exist in
        this project (and the activity's finish date), plus the status of its
        latest approval instance, so the rules stay pure.
        """
        from app.modules.approval_routes.models import Instance

        rows = await self.list_interfaces(project_id)
        activity_ids = {r.schedule_activity_id for r in rows if r.schedule_activity_id is not None}
        rfi_ids = {u for u in (_as_optional_uuid(r.rfi_id) for r in rows if r.rfi_id) if u is not None}
        activities = await self._activities_in_project(project_id, activity_ids)
        rfis = await self._rfis_in_project(project_id, rfi_ids)

        approvals: dict[uuid.UUID, str] = {}
        if rows:
            stmt = (
                select(Instance.target_id, Instance.status, Instance.started_at)
                .where(
                    Instance.target_kind == APPROVAL_TARGET_KIND,
                    Instance.target_id.in_([r.id for r in rows]),
                )
                .order_by(Instance.started_at.asc())
            )
            for target_id, inst_status, _started in (await self.session.execute(stmt)).all():
                approvals[_as_optional_uuid(target_id) or target_id] = str(inst_status)

        def _iso(value: date | None) -> str | None:
            return value.isoformat() if value is not None else None

        payload_rows = []
        for r in rows:
            rfi_uuid = _as_optional_uuid(r.rfi_id) if r.rfi_id else None
            end_date = activities.get(r.schedule_activity_id) if r.schedule_activity_id is not None else None
            payload_rows.append(
                {
                    "id": str(r.id),
                    "reference": r.reference,
                    "status": str(r.status),
                    "need_by_date": _iso(r.need_by_date),
                    "agreed_date": _iso(r.agreed_date),
                    "closed_date": _iso(r.closed_date),
                    "schedule_activity_id": str(r.schedule_activity_id) if r.schedule_activity_id else None,
                    "activity_found": r.schedule_activity_id in activities,
                    "activity_end_date": end_date,
                    "rfi_id": r.rfi_id,
                    "rfi_found": rfi_uuid is not None and rfi_uuid in rfis,
                    "approval_status": approvals.get(r.id),
                }
            )
        return {"interfaces": payload_rows}

    async def run_validation(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Run the ``interface_management`` rule set over the project's register."""
        from app.core.validation.engine import rule_registry, validation_engine
        from app.modules.interface_management.validators import (
            RULE_SET,
            register_interface_management_validation_rules,
        )

        if not rule_registry.list_rule_sets().get(RULE_SET):
            register_interface_management_validation_rules()
        report = await validation_engine.validate(
            data=await self.validation_payload(project_id),
            rule_sets=[RULE_SET],
            target_type="interface_register",
            target_id=str(project_id),
            project_id=str(project_id),
        )
        results = [
            {
                "rule_id": r.rule_id,
                "severity": r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
            }
            for r in report.results
            if not getattr(r, "is_engine_error", False)
        ]
        return {
            "project_id": str(project_id),
            "status": report.status.value if hasattr(report.status, "value") else str(report.status),
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "passed": len(report.passed_rules),
            "results": results,
        }

    # -- Link checks --------------------------------------------------------

    async def _activities_in_project(
        self,
        project_id: uuid.UUID,
        activity_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, str | None]:
        """Map each given activity id that belongs to a schedule of this project to its finish date."""
        if not activity_ids:
            return {}
        from app.modules.schedule.models import Activity, Schedule

        stmt = (
            select(Activity.id, Activity.end_date)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Activity.id.in_(list(activity_ids)), Schedule.project_id == project_id)
        )
        return {
            (_as_optional_uuid(aid) or aid): (str(end)[:10] if end else None)
            for aid, end in (await self.session.execute(stmt)).all()
        }

    async def _rfis_in_project(self, project_id: uuid.UUID, rfi_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        """The subset of the given RFI ids that are RFIs of this project."""
        if not rfi_ids:
            return set()
        from app.modules.rfi.models import RFI

        stmt = select(RFI.id).where(RFI.id.in_(list(rfi_ids)), RFI.project_id == project_id)
        return {_as_optional_uuid(rid) or rid for (rid,) in (await self.session.execute(stmt)).all()}

    async def _require_links(
        self,
        project_id: uuid.UUID,
        *,
        rfi_id: uuid.UUID | None,
        activity_id: uuid.UUID | None,
    ) -> None:
        """422 when a given RFI or schedule activity is not one of this project's.

        A missing row and another project's row read the same, so the answer
        never tells a caller whether an id exists elsewhere.
        """
        if activity_id is not None and activity_id not in await self._activities_in_project(project_id, {activity_id}):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="schedule_activity_id does not name an activity of this project's schedules",
            )
        if rfi_id is not None and rfi_id not in await self._rfis_in_project(project_id, {rfi_id}):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="rfi_id does not name an RFI of this project",
            )

    async def _user_names(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Display names for the given users (full name, else email); missing users are left out."""
        if not user_ids:
            return {}
        from app.modules.users.models import User

        stmt = select(User.id, User.full_name, User.email).where(User.id.in_(list(user_ids)))
        names: dict[uuid.UUID, str] = {}
        for uid, full_name, email in (await self.session.execute(stmt)).all():
            key = _as_optional_uuid(uid) or uid
            names[key] = (full_name or "").strip() or str(email or "")
        return names

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
