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

Submitting never approves. With no approval configured the requisition simply
waits in ``submitted``; the ``procurement_requisition`` rule set runs first and
its errors block the submission with a 422 that lists every failing rule.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.core.i18n import get_locale
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.procurement.cost_spine import resolve_cost_line_ids
from app.modules.procurement.models import (
    MaterialRequisition,
    MaterialRequisitionItem,
    MaterialRequisitionItemSource,
)
from app.modules.procurement.schemas import (
    RequisitionCreate,
    RequisitionItemIn,
    RequisitionItemResponse,
    RequisitionItemSourceResponse,
    RequisitionResponse,
    RequisitionUpdate,
)
from app.modules.procurement.service import (
    _MR_STATUS_TRANSITIONS,
    MaterialRequisitionService,
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


class RequisitionWorkflowService(MaterialRequisitionService):
    """List, edit, submit, withdraw and cancel material requisitions."""

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
                    detail={
                        "message": (
                            "This requisition has problems that must be fixed before it can be submitted. "
                            "Correct each error listed below, then submit again."
                        ),
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
                    },
                )
        return await self._transition(requisition_id, "submitted", user_id=user_id, action="submitted")

    async def withdraw(self, requisition_id: uuid.UUID, *, user_id: str | None) -> MaterialRequisition:
        """Take a submitted requisition back to draft so it can be edited."""
        req = await self.get_requisition(requisition_id)
        if req.status not in ("submitted", "draft"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Only a submitted requisition can be withdrawn; this one is '{req.status}'.",
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

    # ── Validation ──────────────────────────────────────────────────────────

    @staticmethod
    def validation_payload(req: MaterialRequisition, *, today: date | None = None) -> dict[str, Any]:
        """The payload the ``procurement_requisition`` rules read."""
        return {
            "req_number": req.req_number,
            "required_date": req.required_date,
            "today": (today or date.today()).isoformat(),
            "items": [
                {
                    "description": item.description,
                    "unit": item.unit,
                    "quantity_requested": item.quantity_requested,
                    "sources": [
                        {"unit": s.unit, "quantity": s.quantity, "resource_key": s.resource_key} for s in item.sources
                    ],
                }
                for item in sorted(req.items, key=lambda i: i.sort_order)
            ],
        }

    async def validate(self, req: MaterialRequisition) -> ValidationReport:
        """Run the ``procurement_requisition`` rule set against a requisition."""
        return await validation_engine.validate(
            data=self.validation_payload(req),
            rule_sets=[REQUISITION_RULE_SET],
            target_type="material_requisition",
            target_id=str(req.id),
            project_id=str(req.project_id),
            metadata={"locale": get_locale(), "operation": "submit"},
        )


def requisition_to_response(req: MaterialRequisition) -> RequisitionResponse:
    """Serialise a requisition with per-line progress and the header reconciliation."""
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
            )
        )
    reconciliation = {key: format(value, "f") for key, value in _mr_reconcile(list(req.items)).items()}
    requested = _dec(reconciliation.get("requested"))
    received = _dec(reconciliation.get("received"))
    reconciliation["outstanding"] = format(requested - received, "f")
    history = (req.metadata_ or {}).get("history") if isinstance(req.metadata_, dict) else None
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
        po_id=req.po_id,
        notes=req.notes,
        items=items,
        reconciliation=reconciliation,
        history=list(history) if isinstance(history, list) else [],
        created_at=req.created_at,
        updated_at=req.updated_at,
    )
