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
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
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
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.modules.procurement.schemas import (
    POCreate,
    POItemCreate,
    PositionTraceResponse,
    PositionTraceRow,
    POTraceLine,
    POTraceRequisition,
    POTraceResponse,
    RequisitionConvert,
    RequisitionConvertResponse,
    RequisitionCreate,
    RequisitionItemIn,
    RequisitionItemResponse,
    RequisitionItemSourceResponse,
    RequisitionPOItemRef,
    RequisitionResponse,
    RequisitionUpdate,
    TracePOLine,
    TraceSource,
)
from app.modules.procurement.service import (
    _MR_STATUS_TRANSITIONS,
    MaterialRequisitionService,
    ProcurementService,
    _compute_delivery_date,
    _mr_assert_transition,
    _mr_reconcile,
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
        """Append one entry to the requisition's history.

        The metadata dict is replaced rather than mutated so the change is
        seen by the ORM.
        """
        meta = dict(req.metadata_ or {})
        history = list(meta.get("history") or [])
        entry: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "action": action, "actor": actor}
        entry.update({k: v for k, v in extra.items() if v is not None})
        history.append(entry)
        meta["history"] = history
        req.metadata_ = meta

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
                sources.append(
                    MaterialRequisitionItemSource(
                        boq_position_id=source.boq_position_id,
                        resource_key=source.resource_key,
                        quantity=_safe_decimal_str(source.quantity),
                        unit=source.unit,
                        cost_line_id=source_cost_lines[cursor],
                        sort_order=order,
                    )
                )
                cursor += 1
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
                    sort_order=index,
                    sources=sources,
                )
            )
        await self.session.flush()

    async def create(self, data: RequisitionCreate, *, user_id: str | None) -> MaterialRequisition:
        """Create a draft requisition, its lines and their BOQ sources."""
        required = data.required_date.isoformat() if data.required_date else None
        req = await self._create_req_with_retry(
            project_id=data.project_id,
            requester_id=user_id,
            title=data.title,
            required_date=required,
            lead_time_days=data.lead_time_days,
            estimated_delivery_date=_compute_delivery_date(required, data.lead_time_days),
            notes=data.notes,
        )
        if data.vendor_id is not None:
            await self._require_vendor(data.vendor_id)
            req.vendor_id = data.vendor_id
        self._record(req, "created", user_id)
        await self._write_items(req, data.items)
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
        if "required_date" in fields or "lead_time_days" in fields:
            req.estimated_delivery_date = _compute_delivery_date(req.required_date, req.lead_time_days)
        if "vendor_id" in fields and data.vendor_id != req.vendor_id:
            if data.vendor_id is not None:
                await self._require_vendor(data.vendor_id)
            req.vendor_id = data.vendor_id
            changed.append("vendor_id")
        if data.items is not None:
            for item in list(req.items):
                await self.session.delete(item)
            await self.session.flush()
            await self._write_items(req, data.items)
            changed.append("items")
        if changed:
            self._record(req, "updated", user_id, fields=changed)
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
        self._record(req, action, user_id, previous=previous, status=target, reason=reason)
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
            # A fresh submission is a fresh decision: the previous approver's
            # verdict and comment belong to the history, not to this round.
            req.submitted_by = user_id
            req.approver_id = None
            req.decided_at = None
            req.decision_comment = None
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

    async def approve(
        self,
        requisition_id: uuid.UUID,
        *,
        user_id: str | None,
        comment: str | None = None,
    ) -> MaterialRequisition:
        """Approve a submitted requisition.

        The submitter may not approve it. The rules run again first, with the
        vendor as it stands now: a supplier blacklisted after submission blocks
        the approval. Approving an approved requisition is a no-op.
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
        req.approver_id = user_id
        req.decided_at = datetime.now(UTC).isoformat()
        req.decision_comment = comment or None
        await self._audit(req, actor_id=user_id, previous="submitted", target="approved", reason=comment)
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

    async def convert_to_purchase_order(
        self,
        data: RequisitionConvert,
        *,
        user_id: str | None,
    ) -> RequisitionConvertResponse:
        """Turn approved requisitions of one project into one draft purchase order.

        Every requisition must belong to ``data.project_id`` (404 otherwise, so a
        foreign id is not confirmed to exist) and be ``approved`` (409 naming the
        ones that are not). The supplier is ``data.vendor_id`` or the one the
        requisitions agree on; requisitions naming different suppliers, or a
        stated supplier another requisition contradicts, are a 409. The rules
        then run on each requisition with that supplier and operation
        ``convert``, which requires a supplier, an active one, and lines in one
        currency.

        The requisitions are claimed with one conditional UPDATE from
        ``approved`` to ``ordered`` once the order is written. A concurrent
        conversion that got there first leaves fewer rows matched, and the whole
        request is refused and rolled back, order included, so a requisition is
        never ordered twice. The claim follows the order rather than preceding
        it because the order number retry rolls the session back on a
        collision, which would silently undo a claim made before it.

        One order line is written per requisition line, in requisition then
        line order: the requested quantity and unit unchanged, the line's unit
        cost as the rate, its frozen cost line, and its id as
        ``requisition_item_id``. Lines are never merged across requisitions,
        so each order line leads back to exactly one requisition line.
        """
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

        already = [r for r in ordered_reqs if r.status in ("ordered", "received", "consumed") or r.po_id is not None]
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

        currencies = {
            (item.currency_code or "").strip().upper()
            for req in ordered_reqs
            for item in req.items
            if (item.currency_code or "").strip()
        }
        items: list[POItemCreate] = []
        for req in ordered_reqs:
            for item in sorted(req.items, key=lambda i: i.sort_order):
                items.append(
                    POItemCreate(
                        description=item.description,
                        quantity=_safe_decimal_str(item.quantity_requested),
                        unit=item.unit,
                        unit_rate=format(_dec(item.unit_cost), "f"),
                        cost_line_id=str(item.cost_line_id) if item.cost_line_id else None,
                        requisition_item_id=item.id,
                        sort_order=len(items),
                    )
                )
        metadata: dict[str, Any] = {
            "source": "material_requisitions",
            "source_requisition_ids": [str(r.id) for r in ordered_reqs],
            "source_requisition_numbers": [r.req_number for r in ordered_reqs],
        }
        if vendor is not None:
            metadata["vendor_id"] = str(vendor.id)
            metadata["supplier_name"] = vendor.name
        # Plain values from here on: the order number retry inside create_po may
        # roll the session back, which expires every instance read above.
        req_keys = [(r.id, r.req_number, r.project_id) for r in ordered_reqs]
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

        claimed = await self.session.execute(
            update(MaterialRequisition)
            .where(MaterialRequisition.id.in_(wanted), MaterialRequisition.status == "approved")
            .values(status="ordered", po_id=po_id)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != len(wanted):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "requisition_already_ordered",
                    "message": "Another conversion claimed some of these requisitions first. Reload and try again.",
                    "requisitions": [{"id": str(rid), "req_number": number} for rid, number, _pid in req_keys],
                },
            )

        for rid, _number, _pid in req_keys:
            fresh = await self._reload(rid)
            for item in fresh.items:
                item.quantity_ordered = _safe_decimal_str(item.quantity_requested)
            self._record(fresh, "ordered", user_id, previous="approved", status="ordered", po_number=po_number)
            await self._audit(
                fresh,
                actor_id=user_id,
                previous="approved",
                target="ordered",
                reason=None,
                extra={"po_id": str(po_id), "po_number": po_number},
            )
        await self.session.flush()
        for rid, number, pid in req_keys:
            await _safe_publish(
                "procurement.requisition.ordered",
                {
                    "requisition_id": str(rid),
                    "req_number": number,
                    "project_id": str(pid),
                    "status": "ordered",
                    "previous_status": "approved",
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
        )

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
    ) -> dict[str, Any]:
        """The payload the ``procurement_requisition`` rules read.

        ``vendor_id`` is the supplier the step uses (the requisition's own unless
        a conversion names one); ``vendor`` is its directory entry, or None when
        it cannot be read, which the vendor rule reports rather than trusts.
        """
        return {
            "req_number": req.req_number,
            "required_date": req.required_date,
            "today": (today or date.today()).isoformat(),
            "operation": operation,
            "vendor_id": str(vendor_id) if vendor_id else None,
            "vendor": vendor.as_payload() if vendor is not None else None,
            "items": [
                {
                    "description": item.description,
                    "unit": item.unit,
                    "quantity_requested": item.quantity_requested,
                    "currency_code": item.currency_code,
                    "cost_line_id": str(item.cost_line_id) if item.cost_line_id else None,
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
        return await validation_engine.validate(
            data=self.validation_payload(req, operation=operation, vendor=vendor, vendor_id=vendor_id),
            rule_sets=[REQUISITION_RULE_SET],
            target_type="material_requisition",
            target_id=str(req.id),
            project_id=str(req.project_id),
            metadata={"locale": get_locale(), "operation": operation},
        )


async def release_requisitions_for_po(
    session: AsyncSession,
    po_id: uuid.UUID,
    *,
    actor_id: str | None,
    action: str,
) -> list[uuid.UUID]:
    """Return the requisitions converted into an order to ``approved``.

    Called when the order is cancelled or deleted. The need behind each
    requisition is still approved, so it can be ordered again; the order lines
    of a cancelled order keep their ``requisition_item_id``, so the history of
    the first attempt stays traceable. Only requisitions still ``ordered`` are
    released: one that has started receiving is left for a person to resolve.
    """
    reqs = (
        (
            await session.execute(
                select(MaterialRequisition).where(
                    MaterialRequisition.po_id == po_id,
                    MaterialRequisition.status == "ordered",
                )
            )
        )
        .scalars()
        .all()
    )
    released: list[uuid.UUID] = []
    for req in reqs:
        req.status = "approved"
        req.po_id = None
        for item in req.items:
            item.quantity_ordered = "0"
        RequisitionWorkflowService._record(
            req, "released", actor_id, previous="ordered", status="approved", reason=action, po_id=str(po_id)
        )
        released.append(req.id)
    if released:
        await session.flush()
        for req in reqs:
            await _safe_publish(
                "procurement.requisition.released",
                {
                    "requisition_id": str(req.id),
                    "req_number": req.req_number,
                    "project_id": str(req.project_id),
                    "status": "approved",
                    "previous_status": "ordered",
                    "actor_id": actor_id,
                    "po_id": str(po_id),
                    "reason": action,
                },
            )
    return released


class ResponseContext:
    """The lookups a page of requisition responses needs, read once for the page."""

    def __init__(
        self,
        vendors: dict[uuid.UUID, VendorInfo] | None = None,
        po_numbers: dict[uuid.UUID, str] | None = None,
        po_lines: dict[uuid.UUID, list[TracePOLine]] | None = None,
        user_names: dict[str, str] | None = None,
    ) -> None:
        self.vendors = vendors or {}
        self.po_numbers = po_numbers or {}
        self.po_lines = po_lines or {}
        self.user_names = user_names or {}


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
    """Vendor names, order numbers, converted order lines and approver names, in four queries."""
    vendors = await load_vendors(session, {r.vendor_id for r in reqs if r.vendor_id is not None})
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
    item_ids = {item.id for r in reqs for item in r.items}
    po_lines = await RequisitionWorkflowService(session)._po_lines_for_items(item_ids)
    user_names = await load_user_names(session, {r.approver_id for r in reqs if r.approver_id})
    return ResponseContext(vendors, po_numbers, po_lines, user_names)


def requisition_to_response(req: MaterialRequisition, context: ResponseContext | None = None) -> RequisitionResponse:
    """Serialise a requisition with per-line progress and the header reconciliation."""
    ctx = context or ResponseContext()
    items: list[RequisitionItemResponse] = []
    for item in sorted(req.items, key=lambda i: i.sort_order):
        outstanding = _dec(item.quantity_requested) - _dec(item.quantity_received)
        items.append(
            RequisitionItemResponse(
                id=item.id,
                description=item.description,
                unit=item.unit,
                quantity_requested=item.quantity_requested,
                quantity_ordered=item.quantity_ordered,
                quantity_received=item.quantity_received,
                quantity_consumed=item.quantity_consumed,
                quantity_outstanding=format(outstanding, "f"),
                unit_cost=item.unit_cost,
                extended_cost=item.extended_cost,
                currency_code=item.currency_code,
                catalog_item_id=item.catalog_item_id,
                cost_line_id=item.cost_line_id,
                sort_order=item.sort_order,
                sources=[RequisitionItemSourceResponse.model_validate(s) for s in item.sources],
                po_items=[
                    RequisitionPOItemRef(
                        po_item_id=line.po_item_id,
                        po_id=line.po_id,
                        po_number=line.po_number,
                        quantity=line.quantity,
                        unit=line.unit,
                    )
                    for line in ctx.po_lines.get(item.id, [])
                ],
            )
        )
    reconciliation = {key: format(value, "f") for key, value in _mr_reconcile(list(req.items)).items()}
    requested = _dec(reconciliation.get("requested"))
    received = _dec(reconciliation.get("received"))
    reconciliation["outstanding"] = format(requested - received, "f")
    history = (req.metadata_ or {}).get("history") if isinstance(req.metadata_, dict) else None
    vendor = ctx.vendors.get(req.vendor_id) if req.vendor_id else None
    return RequisitionResponse(
        id=req.id,
        project_id=req.project_id,
        req_number=req.req_number,
        status=req.status,
        title=req.title,
        required_date=req.required_date,
        lead_time_days=req.lead_time_days,
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
        po_id=req.po_id,
        po_number=ctx.po_numbers.get(req.po_id) if req.po_id else None,
        notes=req.notes,
        items=items,
        reconciliation=reconciliation,
        history=list(history) if isinstance(history, list) else [],
        created_at=req.created_at,
        updated_at=req.updated_at,
    )
