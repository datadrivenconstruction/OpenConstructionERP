# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Material requisition workflow behind the ``/requisitions`` endpoints.

``procurement.MaterialRequisition`` is the canonical requisition. This service
adds what a person needs to work with one: list, read, edit while in draft,
submit, withdraw and cancel, with the BOQ provenance of every line kept in
``oe_procurement_req_item_source``.

Lines are merged automatically only when they name the same supplier catalogue
item in the same unit. A shared description and unit are not proof of the same
material, so lines without a catalogue item stay separate until a person merges
them in the draft.

Submitting never approves. The requisition waits in ``submitted`` until an
approver (``procurement.approve_requisition``) approves or rejects it, and the
person who submitted it may not decide it (four-eyes). The
``procurement_requisition`` rule set runs before submit, approve and conversion;
its errors block the step with a 422 that lists every failing rule.

Approved requisitions of one project are converted into one draft purchase
order (issue #516). Each order line keeps the requisition line it came from in
``oe_procurement_po_item.requisition_item_id``, and the requisition line keeps
its BOQ sources, so a BOQ position leads to its requisitions and orders and an
order leads back to its requisitions and positions. The conversion claims the
requisitions with a compare-and-swap on their status, so two conversions racing
for the same requisition cannot both succeed. Cancelling or deleting the order
returns its requisitions to ``approved``.

The supplier is chosen from the Vendor directory of the supplier catalogue
module, read lazily: procurement does not depend on that module, and without it
a requisition simply cannot name a vendor.

Each line may carry a suggested supplier, inherited from its BOQ sources when
they agree and otherwise left empty with every source's suggestion still shown.
A suggestion never becomes the requisition's supplier by itself. Each line may
also carry its own needed-by date, proposed from a schedule activity minus a
buffer; the activity start the proposal read is kept, so a later schedule change
is shown on the line instead of rewriting a date someone already agreed to.

A requisition may name designated approvers in order. Each of them approves in
turn, the requisition stays ``submitted`` through the intermediate steps and is
``approved`` only by the last one; without designated approvers one holder of
the permission approves. Conversion orders line by line: part of a line, a line
over several orders, and lines of several requisitions on one order, with what
is ordered and received read live from the orders and receipts
(:mod:`requisition_progress`). A requisition whose orders are placed in an
external purchasing system is never converted; that system's order lines are
reconciled against it instead, without a local order or commitment. Every
change lands in the replayable change feed (:mod:`requisition_feed`).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.procurement.cost_spine import resolve_cost_line_ids
from app.modules.procurement.models import (
    MaterialRequisition,
    MaterialRequisitionItem,
    MaterialRequisitionItemSource,
    ProcurementProjectSettings,
    PurchaseOrder,
    PurchaseOrderItem,
    RequisitionExternalOrderLine,
)
from app.modules.procurement.order_owner import (
    EXTERNAL,
    OCERP,
    effective_owner,
    load_settings,
)
from app.modules.procurement.requisition_feed import append_history, line_summary, note_change
from app.modules.procurement.requisition_progress import (
    LineProgress,
    fmt,
    in_line_unit,
    load_progress,
    order_progress,
    refresh_requisitions,
)
from app.modules.procurement.schemas import (
    ExternalOrderReport,
    POCreate,
    POItemCreate,
    PositionTraceResponse,
    PositionTraceRow,
    POTraceLine,
    POTraceRequisition,
    POTraceResponse,
    ProcurementSettingsResponse,
    ProcurementSettingsUpdate,
    RequisitionApprovalStep,
    RequisitionConvert,
    RequisitionConvertResponse,
    RequisitionCreate,
    RequisitionExternalLineResponse,
    RequisitionItemIn,
    RequisitionItemResponse,
    RequisitionItemSourceResponse,
    RequisitionOrderRef,
    RequisitionPOItemRef,
    RequisitionResponse,
    RequisitionUpdate,
    RequisitionVendorRef,
    ScheduleActivityOption,
    ScheduleActivityOptionPage,
    TracePOLine,
    TraceSource,
)
from app.modules.procurement.service import (
    _MR_STATUS_TRANSITIONS,
    MaterialRequisitionService,
    ProcurementService,
    _latest_order_date,
    _mr_assert_transition,
    _safe_decimal_str,
    _safe_publish,
)

logger = logging.getLogger(__name__)

#: Rule set the submission gate and the validate endpoint run.
REQUISITION_RULE_SET = "procurement_requisition"

#: Statuses the list filter accepts, taken from the FSM so the two cannot drift.
REQUISITION_STATUSES: frozenset[str] = frozenset(_MR_STATUS_TRANSITIONS)


def _dec(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return value if value.is_finite() else Decimal("0")


def _unit_key(raw: str | None) -> str:
    return (raw or "").strip().lower()


def merge_lines_by_catalog_item(items: list[RequisitionItemIn]) -> list[RequisitionItemIn]:
    """Merge lines that name the same catalogue item in the same unit.

    Only ``catalog_item_id`` is an identity strong enough to merge on without
    asking. Lines without one, or with the same item in a different unit, are
    returned as they came. The first line keeps its description, cost and
    position in the list; quantities are summed and sources concatenated.
    """
    merged: list[RequisitionItemIn] = []
    by_key: dict[tuple[uuid.UUID, str], int] = {}
    for item in items:
        if item.catalog_item_id is None:
            merged.append(item.model_copy(deep=True))
            continue
        key = (item.catalog_item_id, _unit_key(item.unit))
        index = by_key.get(key)
        if index is None:
            by_key[key] = len(merged)
            merged.append(item.model_copy(deep=True))
            continue
        target = merged[index]
        total = _dec(target.quantity_requested) + _dec(item.quantity_requested)
        merged[index] = target.model_copy(
            update={
                "quantity_requested": format(total, "f"),
                "sources": [*target.sources, *item.sources],
            }
        )
    return merged


class VendorInfo:
    """What a requisition needs to know about a Vendor directory entry."""

    __slots__ = ("contact_id", "currency", "id", "name", "status")

    def __init__(self, vendor_id: uuid.UUID, name: str, status: str, contact_id: str | None, currency: str) -> None:
        self.id = vendor_id
        self.name = name
        self.status = status
        self.contact_id = contact_id
        self.currency = currency

    def as_payload(self) -> dict[str, Any]:
        return {"id": str(self.id), "name": self.name, "status": self.status}


async def load_vendors(session: AsyncSession, vendor_ids: set[uuid.UUID]) -> dict[uuid.UUID, VendorInfo]:
    """Read Vendor directory entries by id, in one query.

    The directory belongs to the supplier catalogue module. Procurement does not
    depend on it, so the import is lazy and an install without the module
    answers with an empty map: a vendor that cannot be read is reported as
    unknown, never invented.
    """
    if not vendor_ids:
        return {}
    try:
        from app.modules.supplier_catalogs.models import Vendor
    except ImportError:  # pragma: no cover - module not installed
        return {}
    rows = (await session.execute(select(Vendor).where(Vendor.id.in_(vendor_ids)))).scalars().all()
    return {v.id: VendorInfo(v.id, v.name, v.status, v.contact_id, (v.currency or "").strip().upper()) for v in rows}


def _rule_errors_detail(report: ValidationReport, message: str) -> dict[str, Any]:
    """The 422 body every gated step answers with, in the shape submit already used."""
    return {
        "message": message,
        "report": report.summary(),
        "errors": [
            {
                "rule_id": r.rule_id,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }
            for r in report.errors
        ],
    }


class RequisitionWorkflowService(MaterialRequisitionService):
    """List, edit, submit, approve, reject, withdraw, cancel and convert material requisitions."""

    # ── Reads ───────────────────────────────────────────────────────────────

    async def list_requisitions(
        self,
        project_id: uuid.UUID,
        *,
        req_status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[MaterialRequisition], int]:
        """One page of a project's requisitions, newest first, with the total."""
        if req_status is not None and req_status not in REQUISITION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown requisition status '{req_status}'. Allowed: {sorted(REQUISITION_STATUSES)}.",
            )
        conditions = [MaterialRequisition.project_id == project_id]
        if req_status is not None:
            conditions.append(MaterialRequisition.status == req_status)
        total = (
            await self.session.execute(select(func.count()).select_from(MaterialRequisition).where(*conditions))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    select(MaterialRequisition)
                    .where(*conditions)
                    .order_by(MaterialRequisition.created_at.desc(), MaterialRequisition.id)
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    async def _reload(self, requisition_id: uuid.UUID) -> MaterialRequisition:
        """Re-read a requisition with its lines and sources after a write.

        A flush does not load collections onto the rows it just wrote, and an
        unloaded collection touched from async code raises. ``populate_existing``
        refreshes the instance already in the identity map, lines included.
        """
        stmt = (
            select(MaterialRequisition)
            .where(MaterialRequisition.id == requisition_id)
            .execution_options(populate_existing=True)
        )
        req = (await self.session.execute(stmt)).scalar_one_or_none()
        if req is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MaterialRequisition {requisition_id} not found.",
            )
        return req

    # ── Writes ──────────────────────────────────────────────────────────────

    @staticmethod
    def _record(req: MaterialRequisition, action: str, actor: str | None, **extra: Any) -> None:
        """Append one entry to the requisition's history only, without a feed entry.

        Kept for callers outside the workflow; the workflow itself records
        through :meth:`_note` so the change also reaches the feed.
        """
        append_history(req, action, actor, **extra)

    def _note(self, req: MaterialRequisition, action: str, actor: str | None, **extra: Any) -> None:
        """Record a change in the history and the replayable feed, in this transaction."""
        note_change(self.session, req, action, actor, **extra)

    # ── Designated approvers ────────────────────────────────────────────────

    async def _validated_chain(self, project_id: uuid.UUID, raw: list[uuid.UUID] | list[str] | None) -> list[str]:
        """Designated approvers as stored, refusing a chain that could never be completed.

        Each approver must be an active user who can open the project and whose
        role holds ``procurement.approve_requisition``; nobody may appear twice.
        """
        chain = [str(uuid.UUID(str(v))) for v in (raw or [])]
        if len(set(chain)) != len(chain):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Each designated approver may appear only once in the approval chain.",
            )
        if not chain:
            return []
        from app.core.permissions import permission_registry
        from app.dependencies import verify_project_access
        from app.modules.users.models import User

        users = {
            str(u.id): u
            for u in (await self.session.execute(select(User).where(User.id.in_([uuid.UUID(c) for c in chain]))))
            .scalars()
            .all()
        }
        refused: list[str] = []
        for approver in chain:
            user = users.get(approver)
            if user is None or not getattr(user, "is_active", True):
                refused.append(approver)
                continue
            role = str(getattr(user, "role", "") or "")
            if role != "admin" and not permission_registry.role_has_permission(role, "procurement.approve_requisition"):
                refused.append(approver)
                continue
            try:
                await verify_project_access(project_id, approver, self.session)
            except HTTPException:
                refused.append(approver)
        if refused:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "These designated approvers cannot approve requisitions in this project "
                    f"(unknown, inactive, without project access or without the approval permission): "
                    f"{', '.join(refused)}."
                ),
            )
        return chain

    async def _write_items(
        self,
        req: MaterialRequisition,
        items: list[RequisitionItemIn],
    ) -> None:
        """Insert the lines of a requisition with their BOQ sources.

        Cost lines are resolved for the lines and for every source through the
        same cost spine resolver a purchase order uses, which also refuses a
        position from another project with a 404. A line that names no cost
        line itself takes the one its sources agree on, when they agree.
        """
        lines = merge_lines_by_catalog_item(items)
        if not lines:
            return
        boq_suggestions = await self._boq_suggestions(lines)
        activities = await self._activities_for_lines(req.project_id, lines)
        explicit_vendors = {
            line.suggested_vendor_id
            for line in lines
            if "suggested_vendor_id" in line.model_fields_set and line.suggested_vendor_id is not None
        }
        if explicit_vendors:
            known = await load_vendors(self.session, explicit_vendors)
            unknown = sorted(str(v) for v in explicit_vendors if v not in known)
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Suggested suppliers not in the Vendor directory: {', '.join(unknown)}.",
                )
        line_cost_lines = await resolve_cost_line_ids(
            self.session,
            req.project_id,
            [(line.cost_line_id, line.boq_position_id) for line in lines],
        )
        flat_sources = [source for line in lines for source in line.sources]
        source_cost_lines = (
            await resolve_cost_line_ids(
                self.session,
                req.project_id,
                [(source.cost_line_id, source.boq_position_id) for source in flat_sources],
            )
            if flat_sources
            else []
        )
        cursor = 0
        for index, line in enumerate(lines):
            qty = _safe_decimal_str(line.quantity_requested)
            unit_cost = _dec(line.unit_cost)
            sources: list[MaterialRequisitionItemSource] = []
            for order, source in enumerate(line.sources):
                if "suggested_vendor_id" in source.model_fields_set:
                    source_vendor = source.suggested_vendor_id
                elif source.boq_position_id is not None:
                    source_vendor = boq_suggestions.get((source.boq_position_id, source.resource_key))
                else:
                    source_vendor = None
                sources.append(
                    MaterialRequisitionItemSource(
                        boq_position_id=source.boq_position_id,
                        resource_key=source.resource_key,
                        quantity=_safe_decimal_str(source.quantity),
                        unit=source.unit,
                        cost_line_id=source_cost_lines[cursor],
                        suggested_vendor_id=source_vendor,
                        sort_order=order,
                    )
                )
                cursor += 1
            if "suggested_vendor_id" in line.model_fields_set:
                line_vendor = line.suggested_vendor_id
            else:
                offered = {s.suggested_vendor_id for s in sources if s.suggested_vendor_id is not None}
                line_vendor = next(iter(offered)) if len(offered) == 1 else None
            required_date, anchor = self._line_dates(line, activities)
            cost_line_id = line_cost_lines[index]
            if cost_line_id is None:
                agreed = {s.cost_line_id for s in sources}
                if len(agreed) == 1:
                    cost_line_id = next(iter(agreed))
            self.session.add(
                MaterialRequisitionItem(
                    requisition_id=req.id,
                    description=line.description,
                    unit=line.unit,
                    quantity_requested=qty,
                    unit_cost=unit_cost,
                    extended_cost=Decimal(qty) * unit_cost,
                    currency_code=line.currency_code,
                    catalog_item_id=line.catalog_item_id,
                    cost_line_id=cost_line_id,
                    suggested_vendor_id=line_vendor,
                    required_date=required_date,
                    schedule_activity_id=line.schedule_activity_id,
                    schedule_buffer_days=line.schedule_buffer_days if line.schedule_activity_id else None,
                    schedule_anchor_date=anchor,
                    sort_order=index,
                    sources=sources,
                )
            )
        await self.session.flush()

    async def _boq_suggestions(
        self, lines: list[RequisitionItemIn]
    ) -> dict[tuple[uuid.UUID, str | None], uuid.UUID | None]:
        """The BOQ's suggested supplier for every source that did not bring its own."""
        wanted = [
            (source.boq_position_id, source.resource_key)
            for line in lines
            for source in line.sources
            if source.boq_position_id is not None and "suggested_vendor_id" not in source.model_fields_set
        ]
        if not wanted:
            return {}
        try:
            from app.modules.boq.supplier_suggestion import resolve_suggested_vendors  # noqa: PLC0415
        except ImportError:  # pragma: no cover - BOQ module not installed
            return {}
        return await resolve_suggested_vendors(self.session, wanted)

    async def load_activities(
        self, project_id: uuid.UUID, activity_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, ScheduleActivityOption]:
        """Schedule activities of one project by id; ids from another project are left out."""
        if not activity_ids:
            return {}
        return {
            option.id: option for option in await self.list_schedule_activities(project_id, activity_ids=activity_ids)
        }

    async def list_schedule_activities(
        self,
        project_id: uuid.UUID,
        *,
        activity_ids: set[uuid.UUID] | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> list[ScheduleActivityOption]:
        """The project's schedule activities a line can take its needed-by date from, by start date.

        With ``activity_ids`` every named activity of the project is returned;
        without, one page of ``limit`` rows from ``offset``.
        """
        try:
            from app.modules.schedule.models import Activity, Schedule  # noqa: PLC0415
        except ImportError:  # pragma: no cover - schedule module not installed
            return []
        stmt = (
            select(Activity, Schedule.name)
            .join(Schedule, Activity.schedule_id == Schedule.id)
            .where(Schedule.project_id == project_id)
            .order_by(Activity.start_date, Activity.name, Activity.id)
        )
        if activity_ids is not None:
            stmt = stmt.where(Activity.id.in_(activity_ids))
        else:
            stmt = stmt.offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).all()
        return [
            ScheduleActivityOption(
                id=activity.id,
                name=activity.name,
                schedule_name=schedule_name,
                start_date=str(activity.start_date)[:10],
                end_date=str(activity.end_date)[:10] if activity.end_date else None,
                activity_type=activity.activity_type,
            )
            for activity, schedule_name in rows
        ]

    async def page_schedule_activities(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 500
    ) -> ScheduleActivityOptionPage:
        """One page of the project's schedule activities, with the count of all of them."""
        try:
            from app.modules.schedule.models import Activity, Schedule  # noqa: PLC0415
        except ImportError:  # pragma: no cover - schedule module not installed
            return ScheduleActivityOptionPage(items=[], total=0, offset=offset, limit=limit)
        items = await self.list_schedule_activities(project_id, offset=offset, limit=limit)
        total = (
            await self.session.execute(
                select(func.count(Activity.id))
                .join(Schedule, Activity.schedule_id == Schedule.id)
                .where(Schedule.project_id == project_id)
            )
        ).scalar_one()
        return ScheduleActivityOptionPage(items=items, total=int(total or 0), offset=offset, limit=limit)

    async def _activities_for_lines(
        self, project_id: uuid.UUID, lines: list[RequisitionItemIn]
    ) -> dict[uuid.UUID, ScheduleActivityOption]:
        """The activities the lines name, refusing one that is not in this project with a 422."""
        wanted = {line.schedule_activity_id for line in lines if line.schedule_activity_id is not None}
        found = await self.load_activities(project_id, wanted)
        missing = sorted(str(a) for a in wanted if a not in found)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Schedule activities not found in this project: {', '.join(missing)}.",
            )
        return found

    @staticmethod
    def _line_dates(
        line: RequisitionItemIn,
        activities: dict[uuid.UUID, ScheduleActivityOption],
    ) -> tuple[str | None, str | None]:
        """The line's needed-by date and the activity start it was proposed from.

        Without an activity the line keeps the date it was given (or none, so
        the header applies). With one, the anchor is the start the client says
        it proposed from, else the activity's start now; a line sent without a
        date gets the anchor minus the buffer. A date sent with the activity is
        the requester's and is kept as sent.
        """
        given = line.required_date.isoformat() if line.required_date else None
        if line.schedule_activity_id is None:
            return given, None
        activity = activities[line.schedule_activity_id]
        anchor = line.schedule_anchor_date.isoformat() if line.schedule_anchor_date else activity.start_date
        if given is not None:
            return given, anchor
        try:
            proposed = date.fromisoformat(anchor[:10]) - timedelta(days=line.schedule_buffer_days or 0)
        except ValueError:
            return None, anchor
        return proposed.isoformat(), anchor

    async def find_by_client_request_id(self, project_id: uuid.UUID, key: str) -> MaterialRequisition | None:
        """The requisition an earlier create with this idempotency key made in the project."""
        return (
            await self.session.execute(
                select(MaterialRequisition).where(
                    MaterialRequisition.project_id == project_id,
                    MaterialRequisition.client_request_id == key,
                )
            )
        ).scalar_one_or_none()

    async def create(self, data: RequisitionCreate, *, user_id: str | None) -> MaterialRequisition:
        """Create a draft requisition, its lines and their BOQ sources.

        With ``client_request_id`` a repeated create answers with the
        requisition the first one made, so an integration may retry safely.
        """
        if data.client_request_id:
            existing = await self.find_by_client_request_id(data.project_id, data.client_request_id)
            if existing is not None:
                return await self._reload(existing.id)
        settings = await load_settings(self.session, data.project_id)
        owner = data.order_owner or effective_owner(settings.order_owner if settings is not None else None)
        if data.approval_chain is not None:
            chain = await self._validated_chain(data.project_id, data.approval_chain)
        else:
            # The project default is re-checked: an approver may have left the project since.
            chain = await self._validated_chain(
                data.project_id, list(settings.default_approval_chain or []) if settings is not None else []
            )
        required = data.required_date.isoformat() if data.required_date else None
        req = await self._create_req_with_retry(
            project_id=data.project_id,
            requester_id=user_id,
            title=data.title,
            required_date=required,
            lead_time_days=data.lead_time_days,
            # A delivery forecast exists only once an order does (set at conversion).
            estimated_delivery_date=None,
            notes=data.notes,
        )
        if data.vendor_id is not None:
            await self._require_vendor(data.vendor_id)
            req.vendor_id = data.vendor_id
        req.order_owner = owner
        req.approval_chain = chain
        req.approval_step = 0
        req.client_request_id = data.client_request_id
        await self._write_items(req, data.items)
        await self.session.flush()
        req = await self._reload(req.id)
        self._note(
            req,
            "created",
            user_id,
            order_owner=owner,
            approval_chain=chain or None,
            lines=line_summary(list(req.items)) or None,
            client_request_id=data.client_request_id,
        )
        await self.session.flush()
        return await self._reload(req.id)

    async def update(
        self,
        requisition_id: uuid.UUID,
        data: RequisitionUpdate,
        *,
        user_id: str | None,
    ) -> MaterialRequisition:
        """Edit a draft. Anything past draft is refused with a 409."""
        req = await self.get_requisition(requisition_id)
        if req.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Requisition {req.req_number or req.id} is '{req.status}' and can only be edited "
                    "while it is a draft. Withdraw it first."
                ),
            )
        fields = data.model_dump(exclude_unset=True)
        changed: list[str] = []
        if "title" in fields:
            req.title = data.title
            changed.append("title")
        if "notes" in fields:
            req.notes = data.notes
            changed.append("notes")
        if "required_date" in fields:
            req.required_date = data.required_date.isoformat() if data.required_date else None
            changed.append("required_date")
        if "lead_time_days" in fields and data.lead_time_days is not None:
            req.lead_time_days = data.lead_time_days
            changed.append("lead_time_days")
        if "vendor_id" in fields and data.vendor_id != req.vendor_id:
            if data.vendor_id is not None:
                await self._require_vendor(data.vendor_id)
            req.vendor_id = data.vendor_id
            changed.append("vendor_id")
        if (
            "order_owner" in fields
            and data.order_owner is not None
            and data.order_owner != effective_owner(req.order_owner)
        ):
            req.order_owner = data.order_owner
            changed.append("order_owner")
        if "approval_chain" in fields and data.approval_chain is not None:
            chain = await self._validated_chain(req.project_id, data.approval_chain)
            if chain != list(req.approval_chain or []):
                req.approval_chain = chain
                req.approval_step = 0
                changed.append("approval_chain")
        lines_before: list[dict[str, Any]] | None = None
        if data.items is not None:
            lines_before = line_summary(list(req.items))
            for item in list(req.items):
                await self.session.delete(item)
            await self.session.flush()
            await self._write_items(req, data.items)
            changed.append("items")
        req = await self._reload(req.id)
        if changed:
            lines_after = line_summary(list(req.items)) if lines_before is not None else None
            self._note(
                req,
                "updated",
                user_id,
                fields=changed,
                lines_before=lines_before if lines_before != lines_after else None,
                lines_after=lines_after if lines_before != lines_after else None,
            )
        await self.session.flush()
        return await self._reload(req.id)

    async def _transition(
        self,
        requisition_id: uuid.UUID,
        target: str,
        *,
        user_id: str | None,
        action: str,
        reason: str | None = None,
    ) -> MaterialRequisition:
        """Move a requisition along the FSM, record it and announce it.

        Repeating a transition the requisition already made is a no-op: no
        second history entry and no second event, so a retried request is safe.
        """
        req = await self.get_requisition(requisition_id)
        if req.status == target:
            return await self._reload(req.id)
        _mr_assert_transition(req.status, target)
        previous = req.status
        req.status = target
        self._note(req, action, user_id, previous=previous, status=target, reason=reason)
        await self.session.flush()
        await _safe_publish(
            f"procurement.requisition.{action}",
            {
                "requisition_id": str(req.id),
                "req_number": req.req_number,
                "project_id": str(req.project_id),
                "status": target,
                "previous_status": previous,
                "actor_id": user_id,
            },
        )
        return await self._reload(req.id)

    async def submit(self, requisition_id: uuid.UUID, *, user_id: str | None) -> MaterialRequisition:
        """Submit a draft for purchasing. It stays ``submitted``; nothing approves it here."""
        req = await self.get_requisition(requisition_id)
        if req.status == "draft":
            if not req.items:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="A requisition needs at least one line before it can be submitted.",
                )
            report = await self.validate(req)
            if report.has_errors:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=_rule_errors_detail(
                        report,
                        "This requisition has problems that must be fixed before it can be submitted. "
                        "Correct each error listed below, then submit again.",
                    ),
                )
            chain = [str(a) for a in (req.approval_chain or [])]
            if user_id and str(user_id) in chain:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        "You are one of the designated approvers of this requisition, so you cannot submit it "
                        "yourself (four-eyes principle). Remove yourself from the approval chain or ask a "
                        "colleague to submit it."
                    ),
                )
            # A fresh submission is a fresh decision: the previous approver's
            # verdict and comment belong to the history, not to this round.
            req.submitted_by = user_id
            req.approver_id = None
            req.decided_at = None
            req.decision_comment = None
            req.approval_step = 0
            meta = dict(req.metadata_ or {})
            meta["approval_round"] = []
            req.metadata_ = meta
        return await self._transition(requisition_id, "submitted", user_id=user_id, action="submitted")

    async def withdraw(self, requisition_id: uuid.UUID, *, user_id: str | None) -> MaterialRequisition:
        """Take a submitted or rejected requisition back to draft so it can be edited."""
        req = await self.get_requisition(requisition_id)
        if req.status not in ("submitted", "rejected", "draft"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Only a submitted or rejected requisition can be withdrawn; this one is '{req.status}'.",
            )
        return await self._transition(requisition_id, "draft", user_id=user_id, action="withdrawn")

    async def cancel(
        self,
        requisition_id: uuid.UUID,
        *,
        user_id: str | None,
        reason: str | None = None,
    ) -> MaterialRequisition:
        """Cancel a requisition for good. The row and its history stay."""
        return await self._transition(requisition_id, "cancelled", user_id=user_id, action="cancelled", reason=reason)

    # ── Vendor ──────────────────────────────────────────────────────────────

    async def _require_vendor(self, vendor_id: uuid.UUID) -> VendorInfo:
        """The Vendor directory entry behind an id, or 422 when there is none.

        Any status is accepted on a draft: whether a suspended or blacklisted
        supplier may be ordered from is the ``requisition_vendor_active`` rule's
        question, asked at submit, approval and conversion.
        """
        vendor = (await load_vendors(self.session, {vendor_id})).get(vendor_id)
        if vendor is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Vendor {vendor_id} is not in the Vendor directory.",
            )
        return vendor

    # ── Approval ────────────────────────────────────────────────────────────

    @staticmethod
    def _assert_not_own_submission(req: MaterialRequisition, user_id: str | None, action: str) -> None:
        """The person who submitted a requisition may not decide it (four-eyes).

        ``submitted_by`` is set on every submission; a requisition submitted
        before it existed falls back to its requester.
        """
        submitter = req.submitted_by or req.requester_id
        if submitter and user_id and str(submitter) == str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You cannot {action} a requisition you submitted yourself (four-eyes principle).",
            )

    async def _audit(
        self,
        req: MaterialRequisition,
        *,
        actor_id: str | None,
        previous: str,
        target: str,
        reason: str | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write the activity-log row for a decision, in the caller's transaction.

        Best effort in the same way the purchase order doors are: a failed audit
        row is logged loudly and does not undo the decision.
        """
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="material_requisition",
                entity_id=str(req.id),
                action="status_changed",
                from_status=previous,
                to_status=target,
                reason=reason,
                metadata={"req_number": req.req_number, **(extra or {})},
            )
        except Exception:
            logger.warning("Activity log FAILED for requisition %s (%s -> %s)", req.id, previous, target, exc_info=True)

    @staticmethod
    def _next_designated(req: MaterialRequisition) -> str | None:
        """The designated approver who decides now, or None without a chain (or past its end)."""
        chain = [str(a) for a in (req.approval_chain or [])]
        step = int(req.approval_step or 0)
        return chain[step] if step < len(chain) else None

    def _assert_designated(self, req: MaterialRequisition, user_id: str | None, action: str) -> None:
        """With designated approvers, only the next one in the chain may decide."""
        expected = self._next_designated(req)
        if expected is not None and str(user_id) != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This requisition has designated approvers. Only the next one in the chain may {action} it now."
                ),
            )

    async def approve(
        self,
        requisition_id: uuid.UUID,
        *,
        user_id: str | None,
        comment: str | None = None,
    ) -> MaterialRequisition:
        """Approve a submitted requisition, one step of its approval chain at a time.

        The submitter may not approve it. With designated approvers only the
        next one in the chain may approve; every approval but the last is an
        intermediate step that leaves the requisition ``submitted``, and the
        last one approves it. Without designated approvers one approval by a
        permission holder is final. The rules run again at every step, with the
        vendor as it stands now: a supplier blacklisted after submission blocks
        the approval. Approving an approved requisition, or approving again a
        step one already approved, is a no-op.
        """
        req = await self.get_requisition(requisition_id)
        if req.status == "approved":
            return await self._reload(req.id)
        if req.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Only a submitted requisition can be approved; this one is '{req.status}'.",
            )
        self._assert_not_own_submission(req, user_id, "approve")
        chain = [str(a) for a in (req.approval_chain or [])]
        step = int(req.approval_step or 0)
        if chain and user_id and str(user_id) in chain[:step]:
            return await self._reload(req.id)
        self._assert_designated(req, user_id, "approve")
        report = await self.validate(req, operation="approve")
        if report.has_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_rule_errors_detail(
                    report,
                    "This requisition cannot be approved until the errors listed below are corrected. "
                    "Reject it with a comment so the requester can fix them.",
                ),
            )
        now = datetime.now(UTC).isoformat()
        meta = dict(req.metadata_ or {})
        meta["approval_round"] = [
            *list(meta.get("approval_round") or []),
            {"user_id": str(user_id) if user_id else None, "at": now, "comment": comment or None, "step": step + 1},
        ]
        req.metadata_ = meta
        if chain and step + 1 < len(chain):
            # An intermediate approval: the requisition waits for the next approver.
            req.approval_step = step + 1
            self._note(
                req,
                "approval_step",
                user_id,
                step=step + 1,
                of=len(chain),
                next_approver_id=chain[step + 1],
                reason=comment,
            )
            await self._audit(
                req,
                actor_id=user_id,
                previous="submitted",
                target="submitted",
                reason=comment,
                extra={"approval_step": step + 1, "approval_steps": len(chain), "final": False},
            )
            await self.session.flush()
            await _safe_publish(
                "procurement.requisition.approval_step",
                {
                    "requisition_id": str(req.id),
                    "req_number": req.req_number,
                    "project_id": str(req.project_id),
                    "status": "submitted",
                    "actor_id": user_id,
                    "step": step + 1,
                    "of": len(chain),
                    "final": False,
                    "next_approver_id": chain[step + 1],
                },
            )
            return await self._reload(req.id)
        req.approval_step = len(chain)
        req.approver_id = user_id
        req.decided_at = now
        req.decision_comment = comment or None
        await self._audit(
            req,
            actor_id=user_id,
            previous="submitted",
            target="approved",
            reason=comment,
            extra={"approval_steps": len(chain), "final": True} if chain else None,
        )
        return await self._transition(requisition_id, "approved", user_id=user_id, action="approved", reason=comment)

    async def reject(self, requisition_id: uuid.UUID, *, user_id: str | None, comment: str) -> MaterialRequisition:
        """Reject a submitted requisition with the reason the requester needs.

        The submitter may not reject it either. The requester takes it back to
        draft with withdraw, corrects it and submits again.
        """
        req = await self.get_requisition(requisition_id)
        if req.status == "rejected":
            return await self._reload(req.id)
        if req.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Only a submitted requisition can be rejected; this one is '{req.status}'.",
            )
        reason = (comment or "").strip()
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A rejection needs a comment that tells the requester what to change.",
            )
        self._assert_not_own_submission(req, user_id, "reject")
        self._assert_designated(req, user_id, "reject")
        req.approver_id = user_id
        req.decided_at = datetime.now(UTC).isoformat()
        req.decision_comment = reason
        await self._audit(req, actor_id=user_id, previous="submitted", target="rejected", reason=reason)
        return await self._transition(requisition_id, "rejected", user_id=user_id, action="rejected", reason=reason)

    # ── Conversion into a purchase order ────────────────────────────────────

    @staticmethod
    def _conflict(code: str, message: str, reqs: list[MaterialRequisition]) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": code,
                "message": message,
                "requisitions": [
                    {
                        "id": str(r.id),
                        "req_number": r.req_number,
                        "status": r.status,
                        "po_id": str(r.po_id) if r.po_id else None,
                    }
                    for r in reqs
                ],
            },
        )

    async def _conversion_by_key(self, project_id: uuid.UUID, key: str) -> RequisitionConvertResponse | None:
        """The answer of an earlier conversion with this idempotency key in the project, if there was one."""
        orders = (
            (await self.session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id)))
            .scalars()
            .all()
        )
        for po in orders:
            md = po.metadata_ if isinstance(po.metadata_, dict) else {}
            if md.get("requisition_conversion_key") != key:
                continue
            req_ids = [uuid.UUID(str(r)) for r in md.get("source_requisition_ids") or []]
            reqs = (
                (await self.session.execute(select(MaterialRequisition).where(MaterialRequisition.id.in_(req_ids))))
                .scalars()
                .all()
                if req_ids
                else []
            )
            return RequisitionConvertResponse(
                po_id=po.id,
                po_number=po.po_number,
                project_id=project_id,
                requisition_ids=req_ids,
                line_count=len(po.items),
                replayed=True,
                fully_ordered_requisition_ids=[r.id for r in reqs if r.status == "ordered"],
            )
        return None

    def _plan_lines(
        self,
        data: RequisitionConvert,
        ordered_reqs: list[MaterialRequisition],
        progress: dict[uuid.UUID, LineProgress],
    ) -> list[tuple[MaterialRequisition, MaterialRequisitionItem, Decimal]]:
        """Which requisition lines go on the order, and how much of each, in requisition and line order.

        Without ``data.lines`` every line goes with what is still to order. With
        them, only the named lines, each with its quantity, which must be
        positive and no more than what is still to order on that line.
        """
        if data.lines is None:
            return [
                (req, item, progress[item.id].to_order)
                for req in ordered_reqs
                for item in sorted(req.items, key=lambda i: i.sort_order)
                if progress[item.id].to_order > 0
            ]
        owners = {item.id: (req, item) for req in ordered_reqs for item in req.items}
        wanted: dict[uuid.UUID, Decimal] = {}
        for line in data.lines:
            if line.requisition_item_id not in owners:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"Line {line.requisition_item_id} is not a line of the requisitions being converted. "
                        "Add its requisition to requisition_ids or leave the line out."
                    ),
                )
            if line.requisition_item_id in wanted:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Line {line.requisition_item_id} is named twice. Name each line once with its quantity.",
                )
            quantity = _dec(line.quantity)
            if quantity <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Line {line.requisition_item_id} needs a quantity above zero to go on the order.",
                )
            wanted[line.requisition_item_id] = quantity
        too_much = [
            {
                "requisition_item_id": str(item_id),
                "description": owners[item_id][1].description,
                "unit": owners[item_id][1].unit,
                "quantity": format(quantity, "f"),
                "quantity_to_order": fmt(progress[item_id].to_order),
            }
            for item_id, quantity in wanted.items()
            if quantity > progress[item_id].to_order
        ]
        if too_much:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "quantity_exceeds_remaining",
                    "message": "Some lines ask for more than is still to order on them.",
                    "lines": too_much,
                },
            )
        unused = [r for r in ordered_reqs if not any(item.id in wanted for item in r.items)]
        if unused:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "These requisitions have no line in this conversion: "
                    f"{', '.join(r.req_number or str(r.id) for r in unused)}. Leave them out of requisition_ids."
                ),
            )
        return [
            (req, item, wanted[item.id])
            for req in ordered_reqs
            for item in sorted(req.items, key=lambda i: i.sort_order)
            if item.id in wanted
        ]

    async def convert_to_purchase_order(
        self,
        data: RequisitionConvert,
        *,
        user_id: str | None,
    ) -> RequisitionConvertResponse:
        """Turn approved requisition lines of one project into one draft purchase order.

        Every requisition must belong to ``data.project_id`` (404 otherwise, so a
        foreign id is not confirmed to exist), be ``approved`` (409 naming the
        ones that are not) and have its orders placed in OCERP (409 for one an
        external purchasing system orders). The supplier is ``data.vendor_id``
        or the one the requisitions agree on; requisitions naming different
        suppliers, or a stated supplier another requisition contradicts, are a
        409. The rules then run on each requisition with that supplier and
        operation ``convert``, which requires a supplier, an active one, and
        lines in one currency.

        One order line is written per requisition line in the plan
        (:meth:`_plan_lines`), with the planned quantity, the line's unit, its
        unit cost as the rate, its frozen cost line and its id as
        ``requisition_item_id``. Lines are never merged across requisitions, so
        each order line leads back to exactly one requisition line, and the
        quantity a requisition line put on each order is that order line's
        quantity. A line may be split over several orders; one order may hold
        lines of several requisitions.

        Once the order is written the requisitions are locked with a
        conditional UPDATE that bumps ``row_version`` while they are still
        ``approved``, and what is ordered is counted again under that lock. A
        concurrent conversion that ordered the same quantity first makes the
        count exceed the request, and the whole request is refused and rolled
        back, order included, so a line is never ordered twice. The lock follows
        the order rather than preceding it because the order number retry rolls
        the session back on a collision, which would release a lock taken
        before it. A requisition whose lines are now all on orders moves to
        ``ordered``; one with quantity left stays ``approved``.

        With ``data.idempotency_key`` a repeated conversion answers with the
        order the first one wrote and writes nothing.
        """
        if data.idempotency_key:
            replay = await self._conversion_by_key(data.project_id, data.idempotency_key)
            if replay is not None:
                return replay
        wanted = list(dict.fromkeys(data.requisition_ids))
        reqs = list(
            (
                await self.session.execute(
                    select(MaterialRequisition)
                    .where(MaterialRequisition.id.in_(wanted))
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        found = {r.id: r for r in reqs if r.project_id == data.project_id}
        missing = [str(i) for i in wanted if i not in found]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Requisitions not found in this project: {', '.join(missing)}.",
            )
        ordered_reqs = [found[i] for i in wanted]
        ordered_reqs.sort(key=lambda r: (r.req_number or "", str(r.id)))

        external = [r for r in ordered_reqs if effective_owner(r.order_owner) == EXTERNAL]
        if external:
            raise self._conflict(
                "requisition_orders_external",
                "The orders for these requisitions are placed in an external purchasing system. Record the "
                "external order against them instead of raising a purchase order here.",
                external,
            )
        progress = await load_progress(self.session, [item for r in ordered_reqs for item in r.items])

        def _nothing_left(r: MaterialRequisition) -> bool:
            return bool(r.items) and all(progress[i.id].to_order <= 0 for i in r.items)

        already = [
            r
            for r in ordered_reqs
            if r.status in ("ordered", "received", "consumed") or (r.status == "approved" and _nothing_left(r))
        ]
        if already:
            raise self._conflict(
                "requisition_already_ordered",
                "Some requisitions have already been converted into a purchase order.",
                already,
            )
        not_approved = [r for r in ordered_reqs if r.status != "approved"]
        if not_approved:
            raise self._conflict(
                "requisition_not_approved",
                "Only approved requisitions can be converted into a purchase order.",
                not_approved,
            )

        named = {r.vendor_id for r in ordered_reqs if r.vendor_id is not None}
        if len(named) > 1 or (data.vendor_id is not None and named and data.vendor_id not in named):
            raise self._conflict(
                "vendor_conflict",
                "These requisitions name different suppliers. Convert each supplier's requisitions separately.",
                [r for r in ordered_reqs if r.vendor_id is not None],
            )
        vendor_id = data.vendor_id or (next(iter(named)) if named else None)
        vendor = (await load_vendors(self.session, {vendor_id})).get(vendor_id) if vendor_id else None
        if vendor_id is not None and vendor is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Vendor {vendor_id} is not in the Vendor directory.",
            )

        failing: list[Any] = []
        report: ValidationReport | None = None
        for req in ordered_reqs:
            report = await self.validate(req, operation="convert", vendor=vendor, vendor_id=vendor_id)
            for result in report.errors:
                # Line labels repeat across requisitions; say whose line it is.
                result.element_ref = f"{req.req_number or req.id}: {result.element_ref or ''}".rstrip(": ")
                failing.append(result)
        if failing and report is not None:
            report.results = list(failing)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_rule_errors_detail(
                    report,
                    "These requisitions cannot be converted into a purchase order until the errors listed below "
                    "are corrected.",
                ),
            )

        plan = self._plan_lines(data, ordered_reqs, progress)
        if not plan:
            raise self._conflict(
                "requisition_already_ordered",
                "Nothing is left to order on these requisitions.",
                ordered_reqs,
            )
        planned_reqs = list(dict.fromkeys(req.id for req, _item, _qty in plan))
        currencies = {
            (item.currency_code or "").strip().upper()
            for _req, item, _qty in plan
            if (item.currency_code or "").strip()
        }
        items: list[POItemCreate] = []
        for _req, item, quantity in plan:
            items.append(
                POItemCreate(
                    description=item.description,
                    quantity=format(quantity, "f"),
                    unit=item.unit,
                    unit_rate=format(_dec(item.unit_cost), "f"),
                    cost_line_id=str(item.cost_line_id) if item.cost_line_id else None,
                    requisition_item_id=item.id,
                    sort_order=len(items),
                )
            )
        by_id = {r.id: r for r in ordered_reqs}
        metadata: dict[str, Any] = {
            "source": "material_requisitions",
            "source_requisition_ids": [str(rid) for rid in planned_reqs],
            "source_requisition_numbers": [by_id[rid].req_number for rid in planned_reqs],
        }
        if data.idempotency_key:
            metadata["requisition_conversion_key"] = data.idempotency_key
        if vendor is not None:
            metadata["vendor_id"] = str(vendor.id)
            metadata["supplier_name"] = vendor.name
        # Plain values from here on: the order number retry inside create_po may
        # roll the session back, which expires every instance read above.
        req_keys = [(rid, by_id[rid].req_number, by_id[rid].project_id) for rid in planned_reqs]
        planned_qty = {item.id: quantity for _req, item, quantity in plan}
        po = await ProcurementService(self.session).create_po(
            POCreate(
                project_id=data.project_id,
                vendor_contact_id=vendor.contact_id if vendor is not None else None,
                delivery_date=data.delivery_date.isoformat() if data.delivery_date else None,
                currency_code=next(iter(currencies)) if len(currencies) == 1 else "",
                notes=data.notes,
                items=items,
                metadata=metadata,
            ),
            user_id,
            from_requisition_conversion=True,
        )
        vendor_warnings = list(getattr(po, "vendor_warnings", []) or [])
        po_id, po_number = po.id, po.po_number

        locked = await self.session.execute(
            update(MaterialRequisition)
            .where(MaterialRequisition.id.in_(planned_reqs), MaterialRequisition.status == "approved")
            .values(row_version=func.coalesce(MaterialRequisition.row_version, 0) + 1)
            .execution_options(synchronize_session=False)
        )
        conflict_detail = {
            "code": "requisition_already_ordered",
            "message": "Another conversion ordered some of these lines first. Reload and try again.",
            "requisitions": [{"id": str(rid), "req_number": number} for rid, number, _pid in req_keys],
        }
        if locked.rowcount != len(planned_reqs):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict_detail)

        fresh_reqs = [await self._reload(rid) for rid, _number, _pid in req_keys]
        recount = await load_progress(self.session, [item for r in fresh_reqs for item in r.items])
        if any(recount[item_id].ordered > recount[item_id].requested for item_id in planned_qty):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict_detail)

        changed = await refresh_requisitions(self.session, fresh_reqs)
        fully_ordered: list[uuid.UUID] = []
        for fresh in fresh_reqs:
            if data.delivery_date:
                fresh.estimated_delivery_date = data.delivery_date.isoformat()
            previous, target = changed.get(fresh.id, (fresh.status, fresh.status))
            if fresh.status == "ordered":
                fully_ordered.append(fresh.id)
            self._note(
                fresh,
                "ordered" if target == "ordered" else "partially_ordered",
                user_id,
                previous=previous,
                status=target,
                po_id=str(po_id),
                po_number=po_number,
                lines=[
                    {"requisition_item_id": str(item.id), "quantity": format(planned_qty[item.id], "f")}
                    for item in sorted(fresh.items, key=lambda i: i.sort_order)
                    if item.id in planned_qty
                ],
            )
            await self._audit(
                fresh,
                actor_id=user_id,
                previous=previous,
                target=target,
                reason=None,
                extra={"po_id": str(po_id), "po_number": po_number},
            )
        await self.session.flush()
        for fresh in fresh_reqs:
            previous, target = changed.get(fresh.id, (fresh.status, fresh.status))
            await _safe_publish(
                "procurement.requisition.ordered"
                if target == "ordered"
                else "procurement.requisition.partially_ordered",
                {
                    "requisition_id": str(fresh.id),
                    "req_number": fresh.req_number,
                    "project_id": str(fresh.project_id),
                    "status": target,
                    "previous_status": previous,
                    "actor_id": user_id,
                    "po_id": str(po_id),
                    "po_number": po_number,
                },
            )
        return RequisitionConvertResponse(
            po_id=po_id,
            po_number=po_number,
            project_id=data.project_id,
            requisition_ids=[rid for rid, _number, _pid in req_keys],
            line_count=len(items),
            vendor_warnings=vendor_warnings,
            fully_ordered_requisition_ids=fully_ordered,
        )

    # ── External orders ─────────────────────────────────────────────────────

    async def report_external_order(
        self,
        requisition_id: uuid.UUID,
        data: ExternalOrderReport,
        *,
        user_id: str | None,
    ) -> MaterialRequisition:
        """Reconcile an order an external purchasing system placed against a requisition.

        Only a requisition whose orders are placed externally, and that has been
        approved, takes a report. Each reported line is upserted on (requisition
        line, system, order number, line reference): a report repeated with the
        same figures changes nothing and records nothing, so an integration may
        retry it. No purchase order and no commitment is created. Quantities
        are taken in the reported unit and must be restatable in the
        requisition line's unit; a cancelled external line stops counting.
        """
        req = await self.get_requisition(requisition_id)
        if effective_owner(req.order_owner) != EXTERNAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "requisition_orders_in_ocerp",
                    "message": (
                        f"Requisition {req.req_number or req.id} is ordered in OpenConstructionERP. Convert it into "
                        "a purchase order here instead of recording an external order."
                    ),
                },
            )
        if req.status not in ("approved", "ordered", "received"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Requisition {req.req_number or req.id} is '{req.status}'. An external order can only be "
                    "recorded against an approved requisition."
                ),
            )
        items = {item.id: item for item in req.items}
        unknown = sorted({str(line.requisition_item_id) for line in data.lines} - {str(i) for i in items})
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"These lines are not lines of requisition {req.req_number or req.id}: {', '.join(unknown)}.",
            )
        keys = [(line.requisition_item_id, line.external_line_ref) for line in data.lines]
        if len(set(keys)) != len(keys):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Each external line may appear only once in a report.",
            )
        mismatched = [
            f"{items[line.requisition_item_id].description} ({line.unit} -> {items[line.requisition_item_id].unit})"
            for line in data.lines
            if line.unit and in_line_unit(Decimal("1"), line.unit, items[line.requisition_item_id].unit) is None
        ]
        if mismatched:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "These external lines are in a unit that cannot be restated in the requisition line's unit: "
                    f"{'; '.join(mismatched)}. Report them in the requisition line's unit."
                ),
            )
        existing = {
            (row.requisition_item_id, row.external_line_ref): row
            for row in (
                await self.session.execute(
                    select(RequisitionExternalOrderLine).where(
                        RequisitionExternalOrderLine.requisition_id == req.id,
                        RequisitionExternalOrderLine.external_system == data.external_system,
                        RequisitionExternalOrderLine.external_order_number == data.external_order_number,
                    )
                )
            )
            .scalars()
            .all()
        }
        changes: list[dict[str, Any]] = []
        for line in data.lines:
            values = {
                "status": line.status,
                "quantity_ordered": fmt(_dec(line.quantity_ordered)),
                "quantity_received": fmt(_dec(line.quantity_received)),
                "unit": line.unit or items[line.requisition_item_id].unit,
                "expected_delivery_date": line.expected_delivery_date.isoformat()
                if line.expected_delivery_date
                else None,
                "confirmed_delivery_date": line.confirmed_delivery_date.isoformat()
                if line.confirmed_delivery_date
                else None,
            }
            row = existing.get((line.requisition_item_id, line.external_line_ref))
            if row is None:
                self.session.add(
                    RequisitionExternalOrderLine(
                        requisition_id=req.id,
                        requisition_item_id=line.requisition_item_id,
                        project_id=req.project_id,
                        external_system=data.external_system,
                        external_order_number=data.external_order_number,
                        external_line_ref=line.external_line_ref,
                        updated_by=user_id,
                        **values,
                    )
                )
                changes.append({"requisition_item_id": str(line.requisition_item_id), "change": "added", **values})
                continue
            diff = {k: v for k, v in values.items() if getattr(row, k) != v}
            if not diff:
                continue
            before = {k: getattr(row, k) for k in diff}
            for key, value in diff.items():
                setattr(row, key, value)
            row.updated_by = user_id
            changes.append(
                {
                    "requisition_item_id": str(line.requisition_item_id),
                    "external_line_ref": line.external_line_ref,
                    "change": "updated",
                    "before": before,
                    "after": diff,
                }
            )
        if not changes:
            return await self._reload(req.id)
        await self.session.flush()
        req = await self._reload(req.id)
        changed = await refresh_requisitions(self.session, [req])
        previous, target = changed.get(req.id, (req.status, req.status))
        self._note(
            req,
            "external_order_reported",
            user_id,
            previous=previous if previous != target else None,
            status=target,
            external_system=data.external_system,
            external_order_number=data.external_order_number,
            lines=changes,
        )
        await self.session.flush()
        await _safe_publish(
            "procurement.requisition.external_order_reported",
            {
                "requisition_id": str(req.id),
                "req_number": req.req_number,
                "project_id": str(req.project_id),
                "status": target,
                "previous_status": previous,
                "actor_id": user_id,
                "external_system": data.external_system,
                "external_order_number": data.external_order_number,
            },
        )
        return await self._reload(req.id)

    # ── Project settings ────────────────────────────────────────────────────

    async def settings_response(self, project_id: uuid.UUID) -> ProcurementSettingsResponse:
        """The project's order owner and default approvers, with their names."""
        row = await load_settings(self.session, project_id)
        chain = [str(a) for a in ((row.default_approval_chain if row is not None else None) or [])]
        names = await load_user_names(self.session, set(chain))
        return ProcurementSettingsResponse(
            project_id=project_id,
            order_owner=effective_owner(row.order_owner if row is not None else None),
            default_approvers=[RequisitionApprovalStep(user_id=a, name=names.get(a), state="waiting") for a in chain],
        )

    async def update_settings(
        self, project_id: uuid.UUID, data: ProcurementSettingsUpdate, *, user_id: str | None
    ) -> ProcurementSettingsResponse:
        """Change the project's order owner or default approvers.

        Requisitions already raised keep the owner and approvers they were
        created with; the setting applies to new ones and to award drafts.
        """
        row = await load_settings(self.session, project_id)
        if row is None:
            row = ProcurementProjectSettings(project_id=project_id, order_owner=OCERP, default_approval_chain=[])
            self.session.add(row)
        before = {"order_owner": row.order_owner, "default_approval_chain": list(row.default_approval_chain or [])}
        if data.order_owner is not None:
            row.order_owner = data.order_owner
        if data.default_approval_chain is not None:
            row.default_approval_chain = await self._validated_chain(project_id, data.default_approval_chain)
        row.updated_by = user_id
        await self.session.flush()
        after = {"order_owner": row.order_owner, "default_approval_chain": list(row.default_approval_chain or [])}
        if before != after:
            await self._audit_settings(project_id, user_id, before, after)
        return await self.settings_response(project_id)

    async def _audit_settings(
        self, project_id: uuid.UUID, actor_id: str | None, before: dict[str, Any], after: dict[str, Any]
    ) -> None:
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="procurement_project_settings",
                entity_id=str(project_id),
                action="updated",
                metadata={"before": before, "after": after},
            )
        except Exception:
            logger.warning("Activity log FAILED for procurement settings of %s", project_id, exc_info=True)

    # ── Traceability ────────────────────────────────────────────────────────

    async def trace_position(self, project_id: uuid.UUID, boq_position_id: uuid.UUID) -> PositionTraceResponse:
        """Every requisition line a BOQ position fed, with the order lines each became.

        One row per source record, so a position that fed the same line through
        two resources shows both. Only requisitions of ``project_id`` are read.
        """
        rows = (
            await self.session.execute(
                select(MaterialRequisitionItemSource, MaterialRequisitionItem, MaterialRequisition)
                .join(MaterialRequisitionItem, MaterialRequisitionItemSource.item_id == MaterialRequisitionItem.id)
                .join(MaterialRequisition, MaterialRequisitionItem.requisition_id == MaterialRequisition.id)
                .where(
                    MaterialRequisitionItemSource.boq_position_id == boq_position_id,
                    MaterialRequisition.project_id == project_id,
                )
                .order_by(
                    MaterialRequisition.created_at,
                    MaterialRequisition.id,
                    MaterialRequisitionItem.sort_order,
                    MaterialRequisitionItemSource.sort_order,
                )
            )
        ).all()
        po_lines = await self._po_lines_for_items({item.id for _source, item, _req in rows})
        return PositionTraceResponse(
            boq_position_id=boq_position_id,
            items=[
                PositionTraceRow(
                    requisition_id=req.id,
                    req_number=req.req_number,
                    requisition_status=req.status,
                    requisition_item_id=item.id,
                    description=item.description,
                    line_unit=item.unit,
                    quantity_requested=item.quantity_requested,
                    quantity_ordered=item.quantity_ordered,
                    resource_key=source.resource_key,
                    source_quantity=source.quantity,
                    source_unit=source.unit,
                    purchase_orders=po_lines.get(item.id, []),
                )
                for source, item, req in rows
            ],
        )

    async def _po_lines_for_items(self, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[TracePOLine]]:
        """Order lines converted from these requisition lines, keyed by requisition line."""
        if not item_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    PurchaseOrderItem.id,
                    PurchaseOrderItem.po_id,
                    PurchaseOrderItem.quantity,
                    PurchaseOrderItem.unit,
                    PurchaseOrderItem.requisition_item_id,
                    PurchaseOrder.po_number,
                    PurchaseOrder.status,
                    PurchaseOrder.delivery_date,
                    PurchaseOrder.supplier_confirmed_delivery_date,
                )
                .join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id)
                .where(PurchaseOrderItem.requisition_item_id.in_(item_ids))
                .order_by(PurchaseOrder.created_at, PurchaseOrderItem.sort_order)
            )
        ).all()
        out: dict[uuid.UUID, list[TracePOLine]] = {}
        for row in rows:
            out.setdefault(row.requisition_item_id, []).append(
                TracePOLine(
                    po_id=row.po_id,
                    po_number=row.po_number,
                    po_status=row.status,
                    po_item_id=row.id,
                    quantity=row.quantity,
                    unit=row.unit,
                    po_delivery_date=row.delivery_date,
                    supplier_confirmed_delivery_date=row.supplier_confirmed_delivery_date,
                )
            )
        return out

    async def _position_labels(self, position_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[str | None, str | None]]:
        """Ordinal and description of BOQ positions, in one query; a deleted position is simply absent."""
        if not position_ids:
            return {}
        from app.modules.boq.models import Position

        rows = (
            await self.session.execute(
                select(Position.id, Position.ordinal, Position.description).where(Position.id.in_(position_ids))
            )
        ).all()
        return {row.id: (row.ordinal, row.description) for row in rows}

    async def trace_purchase_order(self, po: PurchaseOrder) -> POTraceResponse:
        """The requisitions an order came from, and each line's requisition line and BOQ sources."""
        link_ids = {item.requisition_item_id for item in po.items if item.requisition_item_id}
        req_items: dict[uuid.UUID, MaterialRequisitionItem] = {}
        if link_ids:
            req_items = {
                i.id: i
                for i in (
                    await self.session.execute(
                        select(MaterialRequisitionItem).where(MaterialRequisitionItem.id.in_(link_ids))
                    )
                )
                .scalars()
                .all()
            }
        req_ids = {i.requisition_id for i in req_items.values()}
        reqs = (
            (
                await self.session.execute(
                    select(MaterialRequisition)
                    .where((MaterialRequisition.po_id == po.id) | MaterialRequisition.id.in_(req_ids))
                    .order_by(MaterialRequisition.req_number, MaterialRequisition.id)
                )
            )
            .scalars()
            .all()
        )
        numbers = {r.id: r.req_number for r in reqs}
        labels = await self._position_labels(
            {s.boq_position_id for i in req_items.values() for s in i.sources if s.boq_position_id is not None}
        )
        lines: list[POTraceLine] = []
        for item in sorted(po.items, key=lambda i: i.sort_order):
            req_item = req_items.get(item.requisition_item_id) if item.requisition_item_id else None
            lines.append(
                POTraceLine(
                    po_item_id=item.id,
                    description=item.description,
                    quantity=item.quantity,
                    unit=item.unit,
                    requisition_item_id=item.requisition_item_id,
                    requisition_id=req_item.requisition_id if req_item else None,
                    req_number=numbers.get(req_item.requisition_id) if req_item else None,
                    sources=[
                        TraceSource(
                            boq_position_id=s.boq_position_id,
                            position_ordinal=labels.get(s.boq_position_id, (None, None))[0],
                            position_description=labels.get(s.boq_position_id, (None, None))[1],
                            resource_key=s.resource_key,
                            quantity=s.quantity,
                            unit=s.unit,
                        )
                        for s in (req_item.sources if req_item else [])
                    ],
                )
            )
        return POTraceResponse(
            po_id=po.id,
            po_number=po.po_number,
            po_status=po.status,
            requisitions=[
                POTraceRequisition(id=r.id, req_number=r.req_number, status=r.status, title=r.title) for r in reqs
            ],
            lines=lines,
        )

    # ── Validation ──────────────────────────────────────────────────────────

    @staticmethod
    def validation_payload(
        req: MaterialRequisition,
        *,
        today: date | None = None,
        operation: str = "submit",
        vendor: VendorInfo | None = None,
        vendor_id: uuid.UUID | None = None,
        suggested_vendors: dict[uuid.UUID, VendorInfo] | None = None,
        activity_starts: dict[uuid.UUID, str] | None = None,
        progress: dict[uuid.UUID, LineProgress] | None = None,
    ) -> dict[str, Any]:
        """The payload the ``procurement_requisition`` rules read.

        ``vendor_id`` is the supplier the step uses (the requisition's own unless
        a conversion names one); ``vendor`` is its directory entry, or None when
        it cannot be read, which the vendor rule reports rather than trusts.
        ``suggested_vendors`` holds the directory entries of the lines'
        suggestions and ``activity_starts`` the current start of each linked
        schedule activity. ``progress`` carries each line's live ordered
        quantity and the order lines whose unit cannot be restated.
        """
        known = suggested_vendors or {}
        starts = activity_starts or {}
        lines = progress or {}

        def _ordered(item: MaterialRequisitionItem) -> str:
            line = lines.get(item.id)
            return fmt(line.ordered) if line is not None else str(item.quantity_ordered or "0")

        def _mismatches(item: MaterialRequisitionItem) -> list[dict[str, Any]]:
            line = lines.get(item.id)
            if line is None:
                return []
            found = [
                {"ref": po_line.po_number or str(po_line.po_id), "unit": po_line.unit}
                for po_line in line.po_lines
                if po_line.unit_mismatch and po_line.po_status != "cancelled"
            ]
            found.extend(
                {"ref": f"{ext.external_system} {ext.external_order_number}", "unit": ext.unit}
                for ext in line.external_lines
                if ext.id in line.external_mismatch and ext.status != "cancelled"
            )
            return found

        def _vendor(vid: uuid.UUID | None) -> dict[str, Any] | None:
            info = known.get(vid) if vid is not None else None
            return info.as_payload() if info is not None else None

        return {
            "req_number": req.req_number,
            "required_date": req.required_date,
            "today": (today or date.today()).isoformat(),
            "operation": operation,
            "vendor_id": str(vendor_id) if vendor_id else None,
            "vendor": vendor.as_payload() if vendor is not None else None,
            "requester_id": req.requester_id,
            "approval_chain": [str(a) for a in (req.approval_chain or [])],
            "items": [
                {
                    "description": item.description,
                    "unit": item.unit,
                    "quantity_requested": item.quantity_requested,
                    "quantity_ordered": _ordered(item),
                    "order_unit_mismatches": _mismatches(item),
                    "currency_code": item.currency_code,
                    "cost_line_id": str(item.cost_line_id) if item.cost_line_id else None,
                    "required_date": item.required_date,
                    "schedule_activity_id": str(item.schedule_activity_id) if item.schedule_activity_id else None,
                    "schedule_anchor_date": item.schedule_anchor_date,
                    "schedule_activity_start": starts.get(item.schedule_activity_id)
                    if item.schedule_activity_id
                    else None,
                    "suggested_vendor_id": str(item.suggested_vendor_id) if item.suggested_vendor_id else None,
                    "suggested_vendor": _vendor(item.suggested_vendor_id),
                    "source_suggested_vendor_ids": sorted(
                        {str(s.suggested_vendor_id) for s in item.sources if s.suggested_vendor_id is not None}
                    ),
                    "sources": [
                        {"unit": s.unit, "quantity": s.quantity, "resource_key": s.resource_key} for s in item.sources
                    ],
                }
                for item in sorted(req.items, key=lambda i: i.sort_order)
            ],
        }

    async def validate(
        self,
        req: MaterialRequisition,
        *,
        operation: str = "submit",
        vendor: VendorInfo | None = None,
        vendor_id: uuid.UUID | None = None,
    ) -> ValidationReport:
        """Run the ``procurement_requisition`` rule set against a requisition.

        ``operation`` is ``submit``, ``approve`` or ``convert``; some rules only
        speak at a later step. Without an explicit vendor the requisition's own
        is read from the directory.
        """
        if vendor_id is None and vendor is None:
            vendor_id = req.vendor_id
            if vendor_id is not None:
                vendor = (await load_vendors(self.session, {vendor_id})).get(vendor_id)
        suggested = await load_vendors(
            self.session, {i.suggested_vendor_id for i in req.items if i.suggested_vendor_id is not None}
        )
        activities = await self.load_activities(
            req.project_id, {i.schedule_activity_id for i in req.items if i.schedule_activity_id is not None}
        )
        progress = await load_progress(self.session, list(req.items))
        return await validation_engine.validate(
            data=self.validation_payload(
                req,
                operation=operation,
                vendor=vendor,
                vendor_id=vendor_id,
                suggested_vendors=suggested,
                activity_starts={aid: a.start_date for aid, a in activities.items()},
                progress=progress,
            ),
            rule_sets=[REQUISITION_RULE_SET],
            target_type="material_requisition",
            target_id=str(req.id),
            project_id=str(req.project_id),
            metadata={"locale": get_locale(), "operation": operation},
        )


async def _requisitions_linked_to_po(session: AsyncSession, po_id: uuid.UUID) -> list[MaterialRequisition]:
    """Approved or ordered requisitions with a line on this order, or that name it as their order."""
    item_req_ids = select(MaterialRequisitionItem.requisition_id).where(
        MaterialRequisitionItem.id.in_(
            select(PurchaseOrderItem.requisition_item_id).where(
                PurchaseOrderItem.po_id == po_id,
                PurchaseOrderItem.requisition_item_id.is_not(None),
            )
        )
    )
    return list(
        (
            await session.execute(
                select(MaterialRequisition)
                .where(
                    (MaterialRequisition.po_id == po_id) | MaterialRequisition.id.in_(item_req_ids),
                    MaterialRequisition.status.in_(("approved", "ordered")),
                )
                .order_by(MaterialRequisition.req_number, MaterialRequisition.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def release_requisitions_for_po(
    session: AsyncSession,
    po_id: uuid.UUID,
    *,
    actor_id: str | None,
    action: str,
) -> list[uuid.UUID]:
    """Take an order that is about to be cancelled or deleted out of its requisitions' figures.

    Called under the order's lock, before it is cancelled or deleted. What the
    order held is counted as not ordered any more, so each requisition goes
    back to ``approved`` when it has quantity to order again (the need is
    still approved and may be ordered again) and names its newest remaining
    order, or none. The order lines of a cancelled order keep their
    ``requisition_item_id``, so the history of the first attempt stays
    traceable. Only ``approved`` and ``ordered`` requisitions move: one that
    has started receiving is left for a person to resolve.
    """
    reqs = await _requisitions_linked_to_po(session, po_id)
    if not reqs:
        return []
    changed = await refresh_requisitions(session, reqs, exclude_po_ids={po_id})
    for req in reqs:
        previous, target = changed.get(req.id, (req.status, req.status))
        note_change(
            session, req, "released", actor_id, previous=previous, status=target, reason=action, po_id=str(po_id)
        )
    await session.flush()
    for req in reqs:
        previous, target = changed.get(req.id, (req.status, req.status))
        await _safe_publish(
            "procurement.requisition.released",
            {
                "requisition_id": str(req.id),
                "req_number": req.req_number,
                "project_id": str(req.project_id),
                "status": target,
                "previous_status": previous,
                "actor_id": actor_id,
                "po_id": str(po_id),
                "reason": action,
            },
        )
    return [req.id for req in reqs]


async def sync_requisitions_for_po(session: AsyncSession, po_id: uuid.UUID, *, actor_id: str | None) -> None:
    """Bring requisitions in step after the lines of one of their orders were replaced.

    A buyer who lowers a line on a draft order leaves quantity to order again,
    so a fully ordered requisition goes back to ``approved``; raising it does
    the opposite. Nothing is recorded when nothing moved.
    """
    reqs = await _requisitions_linked_to_po(session, po_id)
    if not reqs:
        return
    changed = await refresh_requisitions(session, reqs)
    for req in reqs:
        if req.id not in changed:
            continue
        previous, target = changed[req.id]
        note_change(session, req, "order_changed", actor_id, previous=previous, status=target, po_id=str(po_id))
    await session.flush()


class ResponseContext:
    """The lookups a page of requisition responses needs, read once for the page."""

    def __init__(
        self,
        vendors: dict[uuid.UUID, VendorInfo] | None = None,
        po_numbers: dict[uuid.UUID, str] | None = None,
        po_lines: dict[uuid.UUID, list[TracePOLine]] | None = None,
        user_names: dict[str, str] | None = None,
        activities: dict[uuid.UUID, ScheduleActivityOption] | None = None,
        progress: dict[uuid.UUID, LineProgress] | None = None,
    ) -> None:
        self.vendors = vendors or {}
        self.po_numbers = po_numbers or {}
        self.po_lines = po_lines or {}
        self.user_names = user_names or {}
        self.activities = activities or {}
        self.progress = progress or {}


async def load_user_names(session: AsyncSession, raw_ids: set[str]) -> dict[str, str]:
    """Display names keyed by the user id string the requisition stores; unknown ids are left out."""
    from app.modules.users.models import User  # noqa: PLC0415

    parsed: dict[uuid.UUID, str] = {}
    for raw in raw_ids:
        try:
            parsed[uuid.UUID(str(raw))] = raw
        except (ValueError, TypeError):
            continue
    if not parsed:
        return {}
    rows = (await session.execute(select(User.id, User.full_name).where(User.id.in_(parsed)))).all()
    return {parsed[row.id]: row.full_name for row in rows if row.full_name}


async def build_response_context(session: AsyncSession, reqs: list[MaterialRequisition]) -> ResponseContext:
    """Vendor names, order numbers, live order progress, approver names and schedule activities."""
    vendor_ids = {r.vendor_id for r in reqs if r.vendor_id is not None}
    for r in reqs:
        for item in r.items:
            if item.suggested_vendor_id is not None:
                vendor_ids.add(item.suggested_vendor_id)
            vendor_ids.update(s.suggested_vendor_id for s in item.sources if s.suggested_vendor_id is not None)
    vendors = await load_vendors(session, vendor_ids)
    po_ids = {r.po_id for r in reqs if r.po_id is not None}
    po_numbers: dict[uuid.UUID, str] = {}
    if po_ids:
        po_numbers = {
            row.id: row.po_number
            for row in (
                await session.execute(
                    select(PurchaseOrder.id, PurchaseOrder.po_number).where(PurchaseOrder.id.in_(po_ids))
                )
            ).all()
        }
    progress = await load_progress(session, [item for r in reqs for item in r.items])
    people: set[str] = {r.approver_id for r in reqs if r.approver_id}
    for r in reqs:
        people.update(str(a) for a in (r.approval_chain or []))
    user_names = await load_user_names(session, people)
    activities: dict[uuid.UUID, ScheduleActivityOption] = {}
    workflow = RequisitionWorkflowService(session)
    for project_id in {r.project_id for r in reqs}:
        wanted = {
            item.schedule_activity_id
            for r in reqs
            if r.project_id == project_id
            for item in r.items
            if item.schedule_activity_id is not None
        }
        activities.update(await workflow.load_activities(project_id, wanted))
    return ResponseContext(vendors, po_numbers, {}, user_names, activities, progress)


def _vendor_ref(vendor_id: uuid.UUID, ctx: ResponseContext) -> RequisitionVendorRef:
    info = ctx.vendors.get(vendor_id)
    return RequisitionVendorRef(
        id=vendor_id,
        name=info.name if info is not None else None,
        status=info.status if info is not None else None,
    )


def _line_dates_view(req: MaterialRequisition, item: MaterialRequisitionItem, ctx: ResponseContext) -> dict[str, Any]:
    """The needed-by fields of one line as the response shows them."""
    if item.required_date:
        effective: str | None = item.required_date
        origin: str | None = "schedule" if item.schedule_activity_id else "line"
    elif req.required_date:
        effective, origin = req.required_date, "requisition"
    else:
        effective, origin = None, None
    activity = ctx.activities.get(item.schedule_activity_id) if item.schedule_activity_id else None
    current = activity.start_date if activity is not None else None
    return {
        "required_date": item.required_date,
        "effective_required_date": effective,
        "required_date_source": origin,
        "latest_order_date": _latest_order_date(effective, req.lead_time_days),
        "schedule_activity_id": item.schedule_activity_id,
        "schedule_activity_name": activity.name if activity is not None else None,
        "schedule_buffer_days": item.schedule_buffer_days,
        "schedule_anchor_date": item.schedule_anchor_date,
        "schedule_activity_start": current,
        "schedule_moved": bool(
            current and item.schedule_anchor_date and current[:10] != str(item.schedule_anchor_date)[:10]
        ),
    }


def _approval_view(req: MaterialRequisition, ctx: ResponseContext) -> list[RequisitionApprovalStep]:
    """Each designated approver and where they stand in the current round."""
    chain = [str(a) for a in (req.approval_chain or [])]
    if not chain:
        return []
    step = int(req.approval_step or 0)
    meta = req.metadata_ if isinstance(req.metadata_, dict) else {}
    done = {str(a.get("user_id")): a for a in meta.get("approval_round") or [] if isinstance(a, dict)}
    steps: list[RequisitionApprovalStep] = []
    for index, approver in enumerate(chain):
        decided = done.get(approver) if index < step else None
        if index < step:
            state = "approved"
        elif index == step and req.status == "submitted":
            state = "next"
        else:
            state = "waiting"
        steps.append(
            RequisitionApprovalStep(
                user_id=approver,
                name=ctx.user_names.get(approver),
                state=state,
                decided_at=decided.get("at") if decided else None,
                comment=decided.get("comment") if decided else None,
            )
        )
    return steps


def _line_progress(item: MaterialRequisitionItem, ctx: ResponseContext) -> LineProgress:
    """The live figures of a line, or its stored ones when the context carries none."""
    live = ctx.progress.get(item.id)
    if live is not None:
        return live
    return LineProgress(
        requested=_dec(item.quantity_requested),
        ordered=_dec(item.quantity_ordered),
        received=_dec(item.quantity_received),
    )


def requisition_to_response(req: MaterialRequisition, context: ResponseContext | None = None) -> RequisitionResponse:
    """Serialise a requisition with per-line progress and the header reconciliation."""
    ctx = context or ResponseContext()
    items: list[RequisitionItemResponse] = []
    line_suggestions: list[uuid.UUID] = []
    progress: dict[uuid.UUID, LineProgress] = {}
    orders: dict[uuid.UUID, RequisitionOrderRef] = {}
    for item in sorted(req.items, key=lambda i: i.sort_order):
        line = _line_progress(item, ctx)
        progress[item.id] = line
        offered = list(dict.fromkeys(s.suggested_vendor_id for s in item.sources if s.suggested_vendor_id is not None))
        suggested = ctx.vendors.get(item.suggested_vendor_id) if item.suggested_vendor_id else None
        if item.suggested_vendor_id is not None:
            line_suggestions.append(item.suggested_vendor_id)
        for po_line in line.po_lines:
            orders.setdefault(
                po_line.po_id,
                RequisitionOrderRef(po_id=po_line.po_id, po_number=po_line.po_number, status=po_line.po_status),
            )
        items.append(
            RequisitionItemResponse(
                id=item.id,
                description=item.description,
                unit=item.unit,
                quantity_requested=item.quantity_requested,
                quantity_ordered=fmt(line.ordered),
                quantity_received=fmt(line.received),
                quantity_consumed=item.quantity_consumed,
                quantity_outstanding=fmt(line.outstanding),
                quantity_to_order=fmt(line.to_order),
                over_ordered=line.over_ordered,
                unit_cost=item.unit_cost,
                extended_cost=item.extended_cost,
                currency_code=item.currency_code,
                catalog_item_id=item.catalog_item_id,
                cost_line_id=item.cost_line_id,
                sort_order=item.sort_order,
                suggested_vendor_id=item.suggested_vendor_id,
                suggested_vendor_name=suggested.name if suggested is not None else None,
                suggested_vendor_status=suggested.status if suggested is not None else None,
                source_suggested_vendors=[_vendor_ref(vid, ctx) for vid in offered],
                suggestion_conflict=len(offered) > 1,
                **_line_dates_view(req, item, ctx),
                sources=[
                    RequisitionItemSourceResponse(
                        id=s.id,
                        boq_position_id=s.boq_position_id,
                        resource_key=s.resource_key,
                        quantity=s.quantity,
                        unit=s.unit,
                        cost_line_id=s.cost_line_id,
                        suggested_vendor_id=s.suggested_vendor_id,
                        suggested_vendor_name=(
                            ctx.vendors[s.suggested_vendor_id].name if s.suggested_vendor_id in ctx.vendors else None
                        ),
                    )
                    for s in item.sources
                ],
                po_items=[
                    RequisitionPOItemRef(
                        po_item_id=po_line.po_item_id,
                        po_id=po_line.po_id,
                        po_number=po_line.po_number,
                        po_status=po_line.po_status,
                        quantity=fmt(po_line.quantity),
                        unit=po_line.unit,
                        po_delivery_date=po_line.po_delivery_date,
                        supplier_confirmed_delivery_date=po_line.supplier_confirmed_delivery_date,
                        quantity_received=fmt(po_line.received),
                        unit_mismatch=po_line.unit_mismatch,
                    )
                    for po_line in line.po_lines
                ],
                external_orders=[
                    RequisitionExternalLineResponse(
                        id=ext.id,
                        external_system=ext.external_system,
                        external_order_number=ext.external_order_number,
                        external_line_ref=ext.external_line_ref or "",
                        status=ext.status,
                        quantity_ordered=ext.quantity_ordered,
                        quantity_received=ext.quantity_received,
                        unit=ext.unit,
                        expected_delivery_date=ext.expected_delivery_date,
                        confirmed_delivery_date=ext.confirmed_delivery_date,
                        unit_mismatch=ext.id in line.external_mismatch,
                        updated_at=ext.updated_at,
                    )
                    for ext in line.external_lines
                ],
            )
        )
    requested = sum((p.requested for p in progress.values()), Decimal("0"))
    ordered = sum((p.ordered for p in progress.values()), Decimal("0"))
    received = sum((p.received for p in progress.values()), Decimal("0"))
    consumed = sum((_dec(i.quantity_consumed) for i in req.items), Decimal("0"))
    reconciliation = {
        "requested": fmt(requested),
        "ordered": fmt(ordered),
        "received": fmt(received),
        "consumed": fmt(consumed),
        "to_order": fmt(sum((p.to_order for p in progress.values()), Decimal("0"))),
        "undelivered": fmt(max(ordered - received, Decimal("0"))),
        "unconsumed": fmt(max(received - consumed, Decimal("0"))),
        "outstanding": fmt(requested - received),
    }
    history = (req.metadata_ or {}).get("history") if isinstance(req.metadata_, dict) else None
    vendor = ctx.vendors.get(req.vendor_id) if req.vendor_id else None
    next_approver = RequisitionWorkflowService._next_designated(req) if req.status == "submitted" else None
    return RequisitionResponse(
        id=req.id,
        project_id=req.project_id,
        req_number=req.req_number,
        status=req.status,
        title=req.title,
        required_date=req.required_date,
        lead_time_days=req.lead_time_days,
        latest_order_date=_latest_order_date(req.required_date, req.lead_time_days),
        estimated_delivery_date=req.estimated_delivery_date,
        requester_id=req.requester_id,
        approver_id=req.approver_id,
        approver_name=ctx.user_names.get(req.approver_id) if req.approver_id else None,
        submitted_by=req.submitted_by,
        decided_at=req.decided_at,
        decision_comment=req.decision_comment,
        vendor_id=req.vendor_id,
        vendor_name=vendor.name if vendor is not None else None,
        vendor_status=vendor.status if vendor is not None else None,
        suggested_vendors=[_vendor_ref(vid, ctx) for vid in dict.fromkeys(line_suggestions)],
        po_id=req.po_id,
        po_number=ctx.po_numbers.get(req.po_id) if req.po_id else None,
        notes=req.notes,
        order_owner=effective_owner(req.order_owner),
        order_progress=order_progress(progress),
        purchase_orders=list(orders.values()),
        approval_chain=_approval_view(req, ctx),
        approval_step=int(req.approval_step or 0),
        next_approver_id=next_approver,
        row_version=int(req.row_version or 0),
        client_request_id=req.client_request_id,
        items=items,
        reconciliation=reconciliation,
        history=list(history) if isinstance(history, list) else [],
        created_at=req.created_at,
        updated_at=req.updated_at,
    )
