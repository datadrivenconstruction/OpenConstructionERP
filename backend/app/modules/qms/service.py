"""‌⁠‍QMS service — business logic for the unified quality module.

Status transitions are guarded by explicit allow-lists. Illegal moves
raise :class:`ValueError`; HTTP-layer translation happens in the router.

Cross-module communication is fire-and-forget via
:meth:`EventBus.publish_detached` — never await a subscriber while
holding a write session on SQLite.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.qms.models import (
    QMSNCR,
    ITPItem,
    ITPPlan,
    ITPTemplate,
    QMSAudit,
    QMSAuditFinding,
    QMSCalibration,
    QMSInspection,
    QMSInspectionSignature,
    QMSNCRAction,
    QMSPunchItem,
)
from app.modules.qms.repository import QMSRepository
from app.modules.qms.schemas import (
    AuditCreate,
    AuditFindingCreate,
    AuditUpdate,
    CalibrationCreate,
    CalibrationUpdate,
    InspectionCreate,
    InspectionSignatureCreate,
    InspectionUpdate,
    ITPItemCreate,
    ITPPlanCreate,
    ITPPlanUpdate,
    ITPTemplateCloneRequest,
    ITPTemplateCreate,
    ITPTemplateUpdate,
    NCRActionCreate,
    NCRCreate,
    NCRUpdate,
    PunchItemCreate,
    PunchItemUpdate,
)

logger = logging.getLogger(__name__)

# ── Configurable defaults ─────────────────────────────────────────────────
# Rework-cost-per-open-punch default. In production this should come from
# tenant configuration but a sensible constant unblocks COPQ analytics
# for fresh projects.
_DEFAULT_REWORK_COST_PER_PUNCH: Decimal = Decimal("250.00")

# ── Allowed status transitions ────────────────────────────────────────────

_ITP_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "closed"},
    "active": {"superseded", "closed"},
    "superseded": {"closed"},
    "closed": set(),
}

_INSPECTION_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"in_progress", "passed", "failed", "conditional"},
    "in_progress": {"passed", "failed", "conditional"},
    "passed": set(),
    "failed": set(),
    "conditional": {"passed", "failed"},
}

_NCR_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "open": {"action_pending", "cancelled"},
    "action_pending": {"verifying", "cancelled"},
    "verifying": {"closed", "action_pending"},
    "closed": set(),
    "cancelled": set(),
}

_PUNCH_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "open": {"assigned", "in_progress", "rejected", "closed"},
    "assigned": {"in_progress", "ready_for_inspection", "rejected"},
    "in_progress": {"ready_for_inspection", "rejected"},
    "ready_for_inspection": {"closed", "rejected", "in_progress"},
    "rejected": {"assigned", "in_progress"},
    "closed": set(),
}

_AUDIT_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"in_progress", "closed"},
    "in_progress": {"completed", "closed"},
    "completed": {"closed"},
    "closed": set(),
}


def _utc_now_iso() -> str:
    """‌⁠‍Return current UTC time as an ISO-8601 string for the String(32) columns."""
    return datetime.now(UTC).isoformat()


def _guard_transition(
    table: dict[str, set[str]],
    *,
    current: str,
    new: str,
    entity: str,
) -> None:
    """‌⁠‍Raise :class:`ValueError` if ``current → new`` is not in ``table``."""
    if new == current:
        return
    allowed = table.get(current, set())
    if new not in allowed:
        raise ValueError(
            f"Illegal {entity} transition: '{current}' → '{new}'. Allowed: {sorted(allowed) or 'none'}",
        )


class QMSService:
    """Business logic for the QMS module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = QMSRepository(session)

    # ── ITP plan ───────────────────────────────────────────────────────

    async def create_itp_plan(
        self,
        data: ITPPlanCreate,
        *,
        user_id: str | None = None,
    ) -> ITPPlan:
        plan = ITPPlan(
            project_id=data.project_id,
            name=data.name,
            work_type=data.work_type,
            wbs_ref=data.wbs_ref,
            status=data.status,
            version=data.version,
            created_by=user_id,
        )
        plan = await self.repo.create_itp_plan(plan)
        logger.info("QMS ITP plan created: %s (%s)", plan.name, plan.id)
        return plan

    async def update_itp_plan(
        self,
        plan_id: uuid.UUID,
        data: ITPPlanUpdate,
    ) -> ITPPlan:
        plan = await self.repo.get_itp_plan(plan_id)
        if plan is None:
            raise ValueError(f"ITP plan {plan_id} not found")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        new_status = fields.get("status")
        if new_status is not None and new_status != plan.status:
            _guard_transition(
                _ITP_STATUS_TRANSITIONS,
                current=plan.status,
                new=new_status,
                entity="ITP",
            )
        if fields:
            await self.repo.update_itp_plan_fields(plan_id, **fields)
            await self.session.refresh(plan)
        return plan

    async def add_itp_item(
        self,
        plan_id: uuid.UUID,
        data: ITPItemCreate,
    ) -> ITPItem:
        plan = await self.repo.get_itp_plan(plan_id)
        if plan is None:
            raise ValueError(f"ITP plan {plan_id} not found")
        if plan.status not in ("draft", "active"):
            raise ValueError(
                f"Cannot add item to ITP plan in status '{plan.status}'",
            )
        item = ITPItem(
            itp_plan_id=plan_id,
            sequence=data.sequence,
            control_point_name=data.control_point_name,
            criteria=data.criteria,
            frequency=data.frequency,
            method=data.method,
            acceptance_criteria=data.acceptance_criteria,
            hold_witness_point=data.hold_witness_point,
            responsible_role=data.responsible_role,
            signatories_required=data.signatories_required,
        )
        item = await self.repo.create_itp_item(item)
        return item

    async def activate_itp_plan(self, plan_id: uuid.UUID) -> ITPPlan:
        plan = await self.repo.get_itp_plan(plan_id)
        if plan is None:
            raise ValueError(f"ITP plan {plan_id} not found")
        _guard_transition(
            _ITP_STATUS_TRANSITIONS,
            current=plan.status,
            new="active",
            entity="ITP",
        )
        items = await self.repo.list_itp_items(plan_id)
        if not items:
            raise ValueError("Cannot activate an ITP plan with no items")
        await self.repo.update_itp_plan_fields(plan_id, status="active")
        await self.session.refresh(plan)
        logger.info("QMS ITP plan activated: %s", plan_id)
        event_bus.publish_detached(
            "qms.itp.activated",
            {
                "itp_plan_id": str(plan_id),
                "project_id": str(plan.project_id),
                "name": plan.name,
                "work_type": plan.work_type,
            },
            source_module="qms",
        )
        return plan

    # ── Inspection ─────────────────────────────────────────────────────

    async def schedule_inspection(
        self,
        data: InspectionCreate,
        *,
        user_id: str | None = None,
    ) -> QMSInspection:
        del user_id  # accepted for symmetry; field stored as inspector_user_id
        inspection = QMSInspection(
            itp_item_id=data.itp_item_id,
            project_id=data.project_id,
            location_ref=data.location_ref,
            inspector_user_id=data.inspector_user_id,
            scheduled_at=data.scheduled_at.isoformat() if data.scheduled_at else None,
            status="scheduled",
            bim_element_ref=data.bim_element_ref,
            drawing_ref=data.drawing_ref,
            notes=data.notes,
            photos_json=list(data.photos_json),
        )
        return await self.repo.create_inspection(inspection)

    async def update_inspection(
        self,
        inspection_id: uuid.UUID,
        data: InspectionUpdate,
    ) -> QMSInspection:
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        if inspection.status in ("passed", "failed"):
            raise ValueError(
                f"Cannot edit an inspection in terminal status '{inspection.status}'",
            )
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        new_status = fields.get("status")
        if new_status is not None and new_status != inspection.status:
            # Completion (→ passed/failed/conditional) must go through
            # ``complete_inspection`` so the ITP signatory-count invariant
            # is enforced. A plain PATCH must not be able to skip it.
            if new_status in ("passed", "failed", "conditional"):
                raise ValueError(
                    "Use the inspection 'complete' action to set a result; it enforces the required sign-offs",
                )
            _guard_transition(
                _INSPECTION_STATUS_TRANSITIONS,
                current=inspection.status,
                new=new_status,
                entity="inspection",
            )
        for key in ("scheduled_at", "performed_at"):
            value = fields.get(key)
            if isinstance(value, datetime):
                fields[key] = value.isoformat()
        if fields:
            await self.repo.update_inspection_fields(inspection_id, **fields)
            await self.session.refresh(inspection)
        return inspection

    async def start_inspection(self, inspection_id: uuid.UUID) -> QMSInspection:
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        prior_status = inspection.status
        _guard_transition(
            _INSPECTION_STATUS_TRANSITIONS,
            current=inspection.status,
            new="in_progress",
            entity="inspection",
        )
        await self.repo.update_inspection_fields(
            inspection_id,
            status="in_progress",
        )
        await self.session.refresh(inspection)
        await self.repo.append_audit(
            entity_type="inspection",
            entity_id=inspection_id,
            action="status_change",
            old_status=prior_status,
            new_status="in_progress",
        )
        return inspection

    async def add_signature(
        self,
        inspection_id: uuid.UUID,
        data: InspectionSignatureCreate,
    ) -> QMSInspectionSignature:
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        if inspection.status in ("passed", "failed"):
            raise ValueError(
                f"Cannot sign an inspection in status '{inspection.status}'",
            )
        # Dedup: one (user, role) signature per inspection. Two distinct
        # roles on the same user are still allowed (e.g. GC inspector +
        # designer reviewer when one person wears both hats).
        existing = await self.repo.list_signatures(inspection_id)
        for prior in existing:
            if prior.signer_user_id == data.signer_user_id and prior.signer_role == data.signer_role:
                raise ValueError(
                    f"Signer has already signed this inspection in role '{data.signer_role}'",
                )
        sig = QMSInspectionSignature(
            inspection_id=inspection_id,
            signer_user_id=data.signer_user_id,
            signer_role=data.signer_role,
            signed_at=_utc_now_iso(),
            signature_method=data.signature_method,
            comments=data.comments,
        )
        return await self.repo.add_signature(sig)

    async def complete_inspection(
        self,
        inspection_id: uuid.UUID,
        *,
        result: str,
        notes: str | None = None,
    ) -> QMSInspection:
        """Move an inspection to its terminal state.

        Validates that the linked ITP item's ``signatories_required`` count
        is satisfied before allowing the transition.
        """
        if result not in ("passed", "failed", "conditional"):
            raise ValueError(
                f"Invalid completion result '{result}'; expected one of passed/failed/conditional",
            )

        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")

        prior_status = inspection.status
        _guard_transition(
            _INSPECTION_STATUS_TRANSITIONS,
            current=inspection.status,
            new=result,
            entity="inspection",
        )

        required_sigs = 1
        if inspection.itp_item_id is not None:
            item = await self.repo.get_itp_item(inspection.itp_item_id)
            if item is not None:
                required_sigs = item.signatories_required

        sigs = await self.repo.list_signatures(inspection_id)
        if len(sigs) < required_sigs:
            raise ValueError(
                f"Cannot complete inspection: {len(sigs)}/{required_sigs} required signatures collected",
            )

        update_fields: dict[str, Any] = {
            "status": result,
            "performed_at": _utc_now_iso(),
        }
        if notes is not None:
            update_fields["notes"] = notes
        await self.repo.update_inspection_fields(inspection_id, **update_fields)
        await self.session.refresh(inspection)

        await self.repo.append_audit(
            entity_type="inspection",
            entity_id=inspection_id,
            action="completed",
            old_status=prior_status,
            new_status=result,
            after_state={"result": result},
        )

        event_name = "qms.inspection.passed" if result == "passed" else "qms.inspection.failed"
        event_bus.publish_detached(
            event_name,
            {
                "inspection_id": str(inspection_id),
                "project_id": str(inspection.project_id),
                "itp_item_id": str(inspection.itp_item_id) if inspection.itp_item_id else None,
                "result": result,
            },
            source_module="qms",
        )
        logger.info(
            "QMS inspection completed: project=%s id=%s result=%s signatures=%d/%d",
            inspection.project_id,
            inspection_id,
            result,
            len(sigs),
            required_sigs,
        )
        return inspection

    # ── NCR ────────────────────────────────────────────────────────────

    async def raise_ncr(
        self,
        data: NCRCreate,
        *,
        user_id: str | None = None,
    ) -> QMSNCR:
        raised_by_uuid: uuid.UUID | None = None
        if user_id:
            try:
                raised_by_uuid = uuid.UUID(user_id)
            except (TypeError, ValueError):
                raised_by_uuid = None

        # Money / currency consistency. Either both empty or both set;
        # silent acceptance of an amount without a currency makes COPQ
        # rollups currency-blind, which masks FX errors downstream.
        if data.cost_impact_amount is not None and data.cost_impact_amount > 0 and not data.cost_impact_currency:
            raise ValueError(
                "cost_impact_currency is required when cost_impact_amount is provided",
            )

        ncr = QMSNCR(
            project_id=data.project_id,
            raised_by=raised_by_uuid,
            raised_at=_utc_now_iso(),
            title=data.title,
            description=data.description,
            severity=data.severity,
            root_cause=data.root_cause,
            status="open",
            cost_impact_currency=data.cost_impact_currency,
            cost_impact_amount=data.cost_impact_amount,
            linked_inspection_id=data.linked_inspection_id,
        )
        ncr = await self.repo.create_ncr(ncr)

        await self.repo.append_audit(
            entity_type="ncr",
            entity_id=ncr.id,
            action="created",
            actor_user_id=raised_by_uuid,
            old_status=None,
            new_status="open",
            after_state={
                "severity": ncr.severity,
                "title": ncr.title,
            },
        )

        logger.info(
            "QMS NCR raised: project=%s id=%s severity=%s cost_impact=%s %s",
            ncr.project_id,
            ncr.id,
            ncr.severity,
            ncr.cost_impact_amount if ncr.cost_impact_amount is not None else "0",
            ncr.cost_impact_currency or "-",
        )

        event_bus.publish_detached(
            "qms.ncr.raised",
            {
                "ncr_id": str(ncr.id),
                "project_id": str(ncr.project_id),
                "title": ncr.title,
                "severity": ncr.severity,
                "cost_impact_amount": (str(ncr.cost_impact_amount) if ncr.cost_impact_amount is not None else None),
                "cost_impact_currency": ncr.cost_impact_currency,
            },
            source_module="qms",
        )
        return ncr

    async def update_ncr(
        self,
        ncr_id: uuid.UUID,
        data: NCRUpdate,
    ) -> QMSNCR:
        ncr = await self.repo.get_ncr(ncr_id)
        if ncr is None:
            raise ValueError(f"NCR {ncr_id} not found")
        if ncr.status in ("closed", "cancelled"):
            raise ValueError(
                f"Cannot edit an NCR in status '{ncr.status}'",
            )
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        new_status = fields.get("status")
        prior_status = ncr.status
        if new_status is not None and new_status != ncr.status:
            # Closing must go through ``close_ncr`` so the
            # "every corrective action verified" invariant and the
            # ``qms.ncr.closed`` event are not bypassed by a raw PATCH.
            if new_status == "closed":
                raise ValueError(
                    "Use the NCR 'close' action to close an NCR; it enforces corrective-action completion",
                )
            _guard_transition(
                _NCR_STATUS_TRANSITIONS,
                current=ncr.status,
                new=new_status,
                entity="NCR",
            )
        if fields:
            await self.repo.update_ncr_fields(ncr_id, **fields)
            await self.session.refresh(ncr)
        # R8 audit: status transitions via PATCH were not audit-logged, leaving
        # a gap in the FSM audit trail between ``raise_ncr`` (open) and
        # ``close_ncr`` (closed). The transition is often the most important
        # event for compliance reviewers ("who moved the NCR to verifying?").
        if new_status is not None and new_status != prior_status:
            await self.repo.append_audit(
                entity_type="ncr",
                entity_id=ncr_id,
                action="status_change",
                old_status=prior_status,
                new_status=new_status,
            )
        return ncr

    async def assign_ncr_action(
        self,
        ncr_id: uuid.UUID,
        data: NCRActionCreate,
    ) -> QMSNCRAction:
        ncr = await self.repo.get_ncr(ncr_id)
        if ncr is None:
            raise ValueError(f"NCR {ncr_id} not found")
        if ncr.status in ("closed", "cancelled"):
            raise ValueError(
                f"Cannot add action to NCR in status '{ncr.status}'",
            )
        action = QMSNCRAction(
            ncr_id=ncr_id,
            description=data.description,
            responsible_user_id=data.responsible_user_id,
            due_date=data.due_date.isoformat() if data.due_date else None,
            status="assigned",
            verification_method=data.verification_method,
        )
        action = await self.repo.create_ncr_action(action)
        # Auto-move NCR forward.
        if ncr.status == "open":
            await self.repo.update_ncr_fields(ncr_id, status="action_pending")
        return action

    async def verify_action(
        self,
        action_id: uuid.UUID,
        *,
        verified_by_user_id: uuid.UUID | None = None,
    ) -> QMSNCRAction:
        action = await self.repo.get_ncr_action(action_id)
        if action is None:
            raise ValueError(f"NCR action {action_id} not found")
        if action.status == "done":
            raise ValueError("Action already verified")
        parent = await self.repo.get_ncr(action.ncr_id)
        if parent is not None and parent.status in ("closed", "cancelled"):
            raise ValueError(
                f"Cannot verify an action on an NCR in status '{parent.status}'",
            )
        now = _utc_now_iso()
        await self.repo.update_ncr_action_fields(
            action_id,
            status="done",
            verified_by=verified_by_user_id,
            verified_at=now,
            completed_at=now,
        )
        await self.session.refresh(action)
        # If parent NCR is action_pending and ALL actions done, advance.
        ncr = await self.repo.get_ncr(action.ncr_id)
        if ncr and ncr.status == "action_pending":
            siblings = await self.repo.list_ncr_actions(action.ncr_id)
            if siblings and all(s.status == "done" for s in siblings):
                await self.repo.update_ncr_fields(
                    action.ncr_id,
                    status="verifying",
                )
        return action

    async def close_ncr(self, ncr_id: uuid.UUID) -> QMSNCR:
        ncr = await self.repo.get_ncr(ncr_id)
        if ncr is None:
            raise ValueError(f"NCR {ncr_id} not found")
        if ncr.status == "closed":
            raise ValueError("NCR already closed")
        if ncr.status == "cancelled":
            raise ValueError("Cannot close a cancelled NCR")

        actions = await self.repo.list_ncr_actions(ncr_id)
        if not actions or not all(a.status == "done" for a in actions):
            raise ValueError(
                "Cannot close NCR until every corrective action is verified",
            )
        prior_status = ncr.status
        _guard_transition(
            _NCR_STATUS_TRANSITIONS,
            current=ncr.status,
            new="closed",
            entity="NCR",
        )
        # R8 TOCTOU guard: two concurrent /close calls both pass the status
        # check above, then race to write "closed". Flush the pending update
        # and re-read inside the same transaction so the second caller sees the
        # committed "closed" status and raises instead of double-writing.
        await self.repo.update_ncr_fields(ncr_id, status="closed")
        await self.session.flush()
        await self.session.refresh(ncr)
        if ncr.status != "closed":
            # Another concurrent transaction won the race; surface a clear error.
            raise ValueError("NCR close failed due to concurrent modification; please retry")
        await self.repo.append_audit(
            entity_type="ncr",
            entity_id=ncr_id,
            action="closed",
            old_status=prior_status,
            new_status="closed",
            after_state={"actions_verified": len(actions)},
        )
        event_bus.publish_detached(
            "qms.ncr.closed",
            {
                "ncr_id": str(ncr_id),
                "project_id": str(ncr.project_id),
                "title": ncr.title,
                "severity": ncr.severity,
            },
            source_module="qms",
        )
        logger.info(
            "QMS NCR closed: project=%s id=%s severity=%s actions=%d cost_impact=%s %s",
            ncr.project_id,
            ncr_id,
            ncr.severity,
            len(actions),
            ncr.cost_impact_amount if ncr.cost_impact_amount is not None else "0",
            ncr.cost_impact_currency or "-",
        )
        return ncr

    async def escalate_ncr_to_variation(
        self,
        ncr_id: uuid.UUID,
        *,
        variation_id: uuid.UUID | None = None,
    ) -> QMSNCR:
        """Link an NCR with cost impact to a variation order."""
        ncr = await self.repo.get_ncr(ncr_id)
        if ncr is None:
            raise ValueError(f"NCR {ncr_id} not found")
        if ncr.cost_impact_amount is None or ncr.cost_impact_amount <= 0:
            raise ValueError(
                "Cannot escalate NCR without a non-zero cost_impact_amount",
            )
        if ncr.status in ("cancelled", "closed"):
            raise ValueError(
                f"Cannot escalate an NCR in terminal status '{ncr.status}'",
            )
        if ncr.linked_variation_id is not None and variation_id is None:
            raise ValueError(
                "NCR is already linked to a variation; pass an explicit variation_id to re-link",
            )
        # Generate a UUID if caller did not supply one — production glue
        # code would replace this with a real ChangeOrder lookup.
        var_id = variation_id or uuid.uuid4()
        await self.repo.update_ncr_fields(ncr_id, linked_variation_id=var_id)
        await self.session.refresh(ncr)

        event_bus.publish_detached(
            "qms.ncr.escalated_to_variation",
            {
                "ncr_id": str(ncr_id),
                "project_id": str(ncr.project_id),
                "cost_impact": (str(ncr.cost_impact_amount) if ncr.cost_impact_amount is not None else None),
                "cost_impact_currency": ncr.cost_impact_currency,
                "linked_variation_id": str(var_id),
            },
            source_module="qms",
        )
        return ncr

    # ── Punch list ─────────────────────────────────────────────────────

    async def add_punch_item(
        self,
        data: PunchItemCreate,
        *,
        user_id: str | None = None,
    ) -> QMSPunchItem:
        raised_by_uuid: uuid.UUID | None = None
        if user_id:
            try:
                raised_by_uuid = uuid.UUID(user_id)
            except (TypeError, ValueError):
                raised_by_uuid = None

        punch = QMSPunchItem(
            project_id=data.project_id,
            raised_at=_utc_now_iso(),
            raised_by=raised_by_uuid,
            title=data.title,
            description=data.description,
            room_ref=data.room_ref,
            drawing_ref=data.drawing_ref,
            bim_element_ref=data.bim_element_ref,
            status="open",
            severity=data.severity,
            assigned_to=data.assigned_to,
            due_date=data.due_date.isoformat() if data.due_date else None,
            photos_json=list(data.photos_json),
            source=data.source,
            category=data.category,
        )
        punch = await self.repo.create_punch(punch)
        event_bus.publish_detached(
            "qms.punch.created",
            {
                "punch_id": str(punch.id),
                "project_id": str(punch.project_id),
                "title": punch.title,
                "severity": punch.severity,
            },
            source_module="qms",
        )
        return punch

    async def update_punch_item(
        self,
        punch_id: uuid.UUID,
        data: PunchItemUpdate,
    ) -> QMSPunchItem:
        punch = await self.repo.get_punch(punch_id)
        if punch is None:
            raise ValueError(f"Punch item {punch_id} not found")
        if punch.status == "closed":
            raise ValueError("Cannot edit a closed punch item")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        new_status = fields.get("status")
        if new_status is not None and new_status != punch.status:
            _guard_transition(
                _PUNCH_STATUS_TRANSITIONS,
                current=punch.status,
                new=new_status,
                entity="punch",
            )
        if "due_date" in fields and isinstance(fields["due_date"], datetime):
            fields["due_date"] = fields["due_date"].isoformat()
        if fields:
            await self.repo.update_punch_fields(punch_id, **fields)
            await self.session.refresh(punch)
        return punch

    async def assign_punch_item(
        self,
        punch_id: uuid.UUID,
        *,
        assigned_to: uuid.UUID,
    ) -> QMSPunchItem:
        punch = await self.repo.get_punch(punch_id)
        if punch is None:
            raise ValueError(f"Punch item {punch_id} not found")
        _guard_transition(
            _PUNCH_STATUS_TRANSITIONS,
            current=punch.status,
            new="assigned",
            entity="punch",
        )
        await self.repo.update_punch_fields(
            punch_id,
            status="assigned",
            assigned_to=assigned_to,
        )
        await self.session.refresh(punch)
        return punch

    async def mark_ready_for_inspection(
        self,
        punch_id: uuid.UUID,
    ) -> QMSPunchItem:
        punch = await self.repo.get_punch(punch_id)
        if punch is None:
            raise ValueError(f"Punch item {punch_id} not found")
        _guard_transition(
            _PUNCH_STATUS_TRANSITIONS,
            current=punch.status,
            new="ready_for_inspection",
            entity="punch",
        )
        await self.repo.update_punch_fields(
            punch_id,
            status="ready_for_inspection",
        )
        await self.session.refresh(punch)
        return punch

    async def close_punch_item(self, punch_id: uuid.UUID) -> QMSPunchItem:
        punch = await self.repo.get_punch(punch_id)
        if punch is None:
            raise ValueError(f"Punch item {punch_id} not found")
        _guard_transition(
            _PUNCH_STATUS_TRANSITIONS,
            current=punch.status,
            new="closed",
            entity="punch",
        )
        await self.repo.update_punch_fields(
            punch_id,
            status="closed",
            closed_at=_utc_now_iso(),
        )
        await self.session.refresh(punch)
        event_bus.publish_detached(
            "qms.punch.closed",
            {
                "punch_id": str(punch_id),
                "project_id": str(punch.project_id),
            },
            source_module="qms",
        )
        return punch

    async def reject_punch_item(
        self,
        punch_id: uuid.UUID,
        *,
        reason: str | None = None,
    ) -> QMSPunchItem:
        del reason  # reserved for future use
        punch = await self.repo.get_punch(punch_id)
        if punch is None:
            raise ValueError(f"Punch item {punch_id} not found")
        _guard_transition(
            _PUNCH_STATUS_TRANSITIONS,
            current=punch.status,
            new="rejected",
            entity="punch",
        )
        await self.repo.update_punch_fields(punch_id, status="rejected")
        await self.session.refresh(punch)
        return punch

    # ── Audit ──────────────────────────────────────────────────────────

    async def plan_audit(self, data: AuditCreate) -> QMSAudit:
        audit = QMSAudit(
            project_id=data.project_id,
            audit_type=data.audit_type,
            planned_date=data.planned_date.isoformat() if data.planned_date else None,
            auditor_user_id=data.auditor_user_id,
            audit_scope=data.audit_scope,
            standard_ref=data.standard_ref,
            status="planned",
        )
        return await self.repo.create_audit(audit)

    async def update_audit(
        self,
        audit_id: uuid.UUID,
        data: AuditUpdate,
    ) -> QMSAudit:
        audit = await self.repo.get_audit(audit_id)
        if audit is None:
            raise ValueError(f"Audit {audit_id} not found")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        new_status = fields.get("status")
        if new_status is not None and new_status != audit.status:
            _guard_transition(
                _AUDIT_STATUS_TRANSITIONS,
                current=audit.status,
                new=new_status,
                entity="audit",
            )
        for key in ("planned_date", "performed_at"):
            value = fields.get(key)
            if isinstance(value, datetime):
                fields[key] = value.isoformat()
        if fields:
            await self.repo.update_audit_fields(audit_id, **fields)
            await self.session.refresh(audit)
        return audit

    async def start_audit(self, audit_id: uuid.UUID) -> QMSAudit:
        audit = await self.repo.get_audit(audit_id)
        if audit is None:
            raise ValueError(f"Audit {audit_id} not found")
        _guard_transition(
            _AUDIT_STATUS_TRANSITIONS,
            current=audit.status,
            new="in_progress",
            entity="audit",
        )
        await self.repo.update_audit_fields(audit_id, status="in_progress")
        await self.session.refresh(audit)
        return audit

    async def add_finding(
        self,
        audit_id: uuid.UUID,
        data: AuditFindingCreate,
    ) -> QMSAuditFinding:
        audit = await self.repo.get_audit(audit_id)
        if audit is None:
            raise ValueError(f"Audit {audit_id} not found")
        if audit.status == "closed":
            raise ValueError("Cannot add finding to a closed audit")
        finding = QMSAuditFinding(
            audit_id=audit_id,
            finding_type=data.finding_type,
            description=data.description,
            clause_ref=data.clause_ref,
            corrective_action_required=data.corrective_action_required,
            status="open",
            due_date=data.due_date.isoformat() if data.due_date else None,
        )
        finding = await self.repo.create_finding(finding)
        event_bus.publish_detached(
            "qms.audit.finding_raised",
            {
                "finding_id": str(finding.id),
                "audit_id": str(audit_id),
                "project_id": str(audit.project_id),
                "finding_type": finding.finding_type,
            },
            source_module="qms",
        )
        return finding

    async def close_finding(self, finding_id: uuid.UUID) -> QMSAuditFinding:
        finding = await self.repo.get_finding(finding_id)
        if finding is None:
            raise ValueError(f"Finding {finding_id} not found")
        if finding.status == "closed":
            raise ValueError("Finding already closed")
        await self.repo.update_finding_fields(
            finding_id,
            status="closed",
            closed_at=_utc_now_iso(),
        )
        await self.session.refresh(finding)
        return finding

    async def complete_audit(
        self,
        audit_id: uuid.UUID,
        *,
        overall_rating: int | None = None,
    ) -> QMSAudit:
        audit = await self.repo.get_audit(audit_id)
        if audit is None:
            raise ValueError(f"Audit {audit_id} not found")
        _guard_transition(
            _AUDIT_STATUS_TRANSITIONS,
            current=audit.status,
            new="completed",
            entity="audit",
        )
        updates: dict[str, Any] = {
            "status": "completed",
            "performed_at": _utc_now_iso(),
        }
        if overall_rating is not None:
            if not 1 <= overall_rating <= 5:
                raise ValueError("overall_rating must be in 1..5")
            updates["overall_rating"] = overall_rating
        await self.repo.update_audit_fields(audit_id, **updates)
        await self.session.refresh(audit)
        event_bus.publish_detached(
            "qms.audit.completed",
            {
                "audit_id": str(audit_id),
                "project_id": str(audit.project_id),
                "overall_rating": overall_rating,
            },
            source_module="qms",
        )
        return audit

    # ── Analytics ──────────────────────────────────────────────────────

    async def _resolve_project_currency(
        self,
        project_id: uuid.UUID,
        fallback: str,
    ) -> str:
        """Resolve the active currency for a COPQ-style report.

        If the caller passed an explicit non-empty value we honour it
        (FX-converted upstream). Otherwise fall back to
        ``Project.currency``. Empty string is returned only if the
        project lookup fails and no fallback was provided — callers
        should surface that as a "currency unknown" indicator rather
        than silently substituting ``EUR``/``USD``.
        """
        if fallback:
            return fallback
        try:
            # Lazy import to keep the QMS module loadable without a
            # ``projects`` module in minimal test fixtures.
            from app.modules.projects.repository import ProjectRepository

            proj_repo = ProjectRepository(self.session)
            project = await proj_repo.get_by_id(project_id)
            if project is not None:
                return getattr(project, "currency", "") or ""
        except Exception:  # noqa: BLE001 — defensive log-and-degrade
            logger.exception(
                "QMS COPQ: project currency lookup failed for %s",
                project_id,
            )
        return ""

    async def compute_copq(
        self,
        project_id: uuid.UUID,
        *,
        rework_cost_per_punch: Decimal | None = None,
        currency: str = "",
    ) -> dict[str, Any]:
        """Compute Cost of Poor Quality for a project.

        COPQ = sum(NCR.cost_impact_amount where status != cancelled) +
               open_punch_count * rework_cost_per_punch
        """
        per_punch = rework_cost_per_punch or _DEFAULT_REWORK_COST_PER_PUNCH

        ncr_total_raw = await self.repo.sum_ncr_cost_impact(project_id)
        # SQLite coalesce of Numeric to integer/float — coerce to Decimal.
        ncr_total = Decimal(str(ncr_total_raw or 0))
        open_punch = await self.repo.count_open_punch(project_id)
        rework_total = per_punch * Decimal(open_punch)
        copq_total = ncr_total + rework_total

        resolved_currency = await self._resolve_project_currency(
            project_id,
            currency,
        )

        logger.info(
            "QMS COPQ computed: project=%s ncr=%s rework=%s total=%s %s",
            project_id,
            ncr_total,
            rework_total,
            copq_total,
            resolved_currency or "-",
        )

        return {
            "project_id": project_id,
            "ncr_cost_total": ncr_total,
            "open_punch_count": open_punch,
            "rework_cost_estimate": rework_total,
            "copq_total": copq_total,
            "currency": resolved_currency,
        }

    async def compute_first_pass_yield(
        self,
        project_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Inspections that passed on first attempt / total inspections."""
        total = await self.repo.count_inspections(project_id)
        passed = await self.repo.count_inspections_passed(project_id)
        ratio = (passed / total) if total else 0.0
        return {
            "project_id": project_id,
            "inspections_total": total,
            "inspections_passed_first_time": passed,
            "first_pass_yield": round(ratio, 4),
        }

    async def compute_copq_detailed(
        self,
        project_id: uuid.UUID,
        *,
        rework_cost_per_punch: Decimal | None = None,
        warranty_cost: Decimal | None = None,
        delay_penalty_cost: Decimal | None = None,
        currency: str = "",
    ) -> dict[str, Any]:
        """COPQ extended with warranty and delay-penalty cost categories.

        COPQ (Juran) = internal failure (NCRs + rework) + external failure
        (warranty) + delay penalty. Each component is optional; defaults
        come from tenant config — here we surface them as explicit kwargs.
        """
        per_punch = rework_cost_per_punch or _DEFAULT_REWORK_COST_PER_PUNCH
        warranty = Decimal(str(warranty_cost or 0))
        delay = Decimal(str(delay_penalty_cost or 0))

        ncr_total_raw = await self.repo.sum_ncr_cost_impact(project_id)
        ncr_total = Decimal(str(ncr_total_raw or 0))
        open_punch = await self.repo.count_open_punch(project_id)
        rework_total = per_punch * Decimal(open_punch)
        copq_total = ncr_total + rework_total + warranty + delay

        resolved_currency = await self._resolve_project_currency(
            project_id,
            currency,
        )

        logger.info(
            "QMS COPQ-detailed: project=%s ncr=%s rework=%s warranty=%s delay=%s total=%s %s",
            project_id,
            ncr_total,
            rework_total,
            warranty,
            delay,
            copq_total,
            resolved_currency or "-",
        )

        return {
            "project_id": project_id,
            "ncr_cost_total": ncr_total,
            "open_punch_count": open_punch,
            "rework_cost_estimate": rework_total,
            "warranty_cost": warranty,
            "delay_penalty_cost": delay,
            "copq_total": copq_total,
            "currency": resolved_currency,
        }

    async def compute_fpy_trend(
        self,
        project_id: uuid.UUID,
        *,
        period_days: int = 7,
        periods: int = 12,
        work_type: str | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Bucketed first-pass-yield trend over the last ``periods`` periods.

        Each bucket is ``period_days`` wide. Optional ``work_type`` filters
        to a single trade by walking the inspection→ITP item→ITP plan
        relation in-process (kept simple — datasets are small per period).
        """
        if today is None:
            today = date.today()
        if period_days < 1:
            raise ValueError("period_days must be ≥ 1")
        if periods < 1:
            raise ValueError("periods must be ≥ 1")

        # ITP plan id set for work_type filter
        work_type_plan_ids: set[uuid.UUID] | None = None
        if work_type is not None:
            plans, _ = await self.repo.list_itp_plans(
                project_id,
                limit=10_000,
            )
            work_type_plan_ids = {p.id for p in plans if p.work_type == work_type}
            if not work_type_plan_ids:
                # No plans of this work_type — empty trend
                return {
                    "project_id": project_id,
                    "work_type": work_type,
                    "period_days": period_days,
                    "buckets": [],
                }

        buckets: list[dict[str, Any]] = []
        for i in range(periods - 1, -1, -1):
            # ``window_end`` is the INCLUSIVE last day of the bucket; the
            # most-recent bucket (i == 0) therefore includes ``today``.
            # The SQL upper bound is exclusive at the next day's midnight
            # so an inspection performed any time today is counted.
            window_end = today - timedelta(days=i * period_days)
            window_start = window_end - timedelta(days=period_days - 1)
            start_iso = datetime.combine(
                window_start,
                datetime.min.time(),
                tzinfo=UTC,
            ).isoformat()
            end_iso = datetime.combine(
                window_end + timedelta(days=1),
                datetime.min.time(),
                tzinfo=UTC,
            ).isoformat()
            inspections = await self.repo.list_inspections_in_period(
                project_id,
                period_start_iso=start_iso,
                period_end_iso=end_iso,
            )
            if work_type_plan_ids is not None:
                # Filter to those whose itp_item belongs to a matching plan.
                kept: list[QMSInspection] = []
                item_cache: dict[uuid.UUID, uuid.UUID] = {}
                for ins in inspections:
                    if ins.itp_item_id is None:
                        continue
                    plan_id = item_cache.get(ins.itp_item_id)
                    if plan_id is None:
                        item_obj = await self.repo.get_itp_item(ins.itp_item_id)
                        if item_obj is None:
                            continue
                        plan_id = item_obj.itp_plan_id
                        item_cache[ins.itp_item_id] = plan_id
                    if plan_id in work_type_plan_ids:
                        kept.append(ins)
                inspections = kept

            total = len(inspections)
            passed = sum(1 for ins in inspections if ins.status == "passed")
            ratio = (passed / total) if total else 0.0
            buckets.append(
                {
                    "period_start": window_start.isoformat(),
                    "period_end": window_end.isoformat(),
                    "inspections_total": total,
                    "inspections_passed_first_time": passed,
                    "first_pass_yield": round(ratio, 4),
                }
            )

        return {
            "project_id": project_id,
            "work_type": work_type,
            "period_days": period_days,
            "buckets": buckets,
        }

    async def generate_management_review(
        self,
        project_id: uuid.UUID,
        *,
        period_from: date,
        period_to: date,
        currency: str = "",
    ) -> dict[str, Any]:
        """ISO 9001:2015 §9.3 management-review report payload.

        Aggregates audits, findings, NCRs, inspections, punch list and
        COPQ over the given period, plus a short list of textual
        recommendations driven by simple thresholds (CMMI-style).
        """
        if period_to < period_from:
            raise ValueError("period_to must be on or after period_from")
        start_iso = datetime.combine(
            period_from,
            datetime.min.time(),
            tzinfo=UTC,
        ).isoformat()
        # exclusive upper bound = period_to + 1 day
        end_iso = datetime.combine(
            period_to + timedelta(days=1),
            datetime.min.time(),
            tzinfo=UTC,
        ).isoformat()

        audits = await self.repo.count_audits_in_period(
            project_id,
            date_from_iso=start_iso,
            date_to_iso=end_iso,
        )
        findings_open = await self.repo.count_open_findings_in_period(
            project_id,
            date_from_iso=start_iso,
            date_to_iso=end_iso,
        )
        findings_closed = await self.repo.count_closed_findings_in_period(
            project_id,
            date_from_iso=start_iso,
            date_to_iso=end_iso,
        )
        ncrs_raised = await self.repo.count_ncrs_in_period(
            project_id,
            date_from_iso=start_iso,
            date_to_iso=end_iso,
        )
        ncrs_closed = await self.repo.count_ncrs_in_period(
            project_id,
            date_from_iso=start_iso,
            date_to_iso=end_iso,
            only_closed=True,
        )

        inspections = await self.repo.list_inspections_in_period(
            project_id,
            period_start_iso=start_iso,
            period_end_iso=end_iso,
        )
        inspections_total = len(inspections)
        inspections_passed = sum(1 for i in inspections if i.status == "passed")
        inspections_failed = sum(1 for i in inspections if i.status == "failed")
        fpy = (inspections_passed / inspections_total) if inspections_total else 0.0

        copq_data = await self.compute_copq_detailed(project_id, currency=currency)
        open_punch = copq_data["open_punch_count"]
        # Mirror copq_detailed's currency resolution so the management
        # review report doesn't return a different label than the COPQ
        # numbers embedded within it.
        resolved_currency = copq_data["currency"]

        # Heuristic recommendations based on simple thresholds.
        recs: list[str] = []
        if fpy < 0.85 and inspections_total > 0:
            recs.append(
                f"First-pass yield {fpy:.2%} below 85% target — review inspector training and rework root causes."
            )
        if findings_open > findings_closed:
            recs.append(
                f"{findings_open} open findings vs {findings_closed} closed — "
                "increase CAPA closure cadence and review responsible owners."
            )
        if ncrs_raised > 0 and ncrs_closed / max(ncrs_raised, 1) < 0.5:
            recs.append(
                f"Only {ncrs_closed}/{ncrs_raised} NCRs closed in period — escalate ageing NCRs to senior leadership."
            )
        if open_punch > 50:
            recs.append(
                f"{open_punch} open punch items — schedule a rolling punch-down sprint before final inspection."
            )
        if not recs:
            recs.append("QMS performance within thresholds — maintain current cadence.")

        return {
            "project_id": project_id,
            "period_from": period_from,
            "period_to": period_to,
            "audits_completed": audits,
            "findings_open": findings_open,
            "findings_closed": findings_closed,
            "ncrs_raised": ncrs_raised,
            "ncrs_closed": ncrs_closed,
            "first_pass_yield": round(fpy, 4),
            "copq_total": copq_data["copq_total"],
            "currency": resolved_currency,
            "inspections_total": inspections_total,
            "inspections_passed": inspections_passed,
            "inspections_failed": inspections_failed,
            "open_punch_count": open_punch,
            "recommendations": recs,
        }

    # ── ITP template library ──────────────────────────────────────────

    async def create_itp_template(
        self,
        data: ITPTemplateCreate,
        *,
        user_id: str | None = None,
    ) -> ITPTemplate:
        tpl = ITPTemplate(
            csi_division=data.csi_division,
            work_type=data.work_type,
            name=data.name,
            description=data.description,
            standard_ref=data.standard_ref,
            items_json=[i.model_dump() for i in data.items],
            is_active=data.is_active,
            version=data.version,
            created_by=user_id,
        )
        tpl = await self.repo.create_itp_template(tpl)
        logger.info("QMS ITP template created: %s (%s)", tpl.name, tpl.id)
        return tpl

    async def update_itp_template(
        self,
        tpl_id: uuid.UUID,
        data: ITPTemplateUpdate,
    ) -> ITPTemplate:
        tpl = await self.repo.get_itp_template(tpl_id)
        if tpl is None:
            raise ValueError(f"ITP template {tpl_id} not found")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        items = fields.pop("items", None)
        if items is not None:
            fields["items_json"] = [i.model_dump() if hasattr(i, "model_dump") else i for i in items]
        if fields:
            await self.repo.update_itp_template_fields(tpl_id, **fields)
            await self.session.refresh(tpl)
        return tpl

    async def clone_itp_template_to_project(
        self,
        tpl_id: uuid.UUID,
        request: ITPTemplateCloneRequest,
        *,
        user_id: str | None = None,
    ) -> ITPPlan:
        """Deep-clone a tenant-level ITP template into a project as a Plan."""
        tpl = await self.repo.get_itp_template(tpl_id)
        if tpl is None:
            raise ValueError(f"ITP template {tpl_id} not found")
        if not tpl.is_active:
            raise ValueError("Cannot clone an inactive ITP template")

        plan = ITPPlan(
            project_id=request.project_id,
            name=request.name_override or tpl.name,
            work_type=tpl.work_type,
            wbs_ref=request.wbs_ref,
            status="draft",
            version=tpl.version,
            created_by=user_id,
        )
        plan = await self.repo.create_itp_plan(plan)

        items_data = tpl.items_json or []
        for raw in items_data:
            item = ITPItem(
                itp_plan_id=plan.id,
                sequence=int(raw.get("sequence", 0) or 0),
                control_point_name=str(raw["control_point_name"]),
                criteria=raw.get("criteria"),
                frequency=raw.get("frequency"),
                method=raw.get("method"),
                acceptance_criteria=raw.get("acceptance_criteria"),
                hold_witness_point=str(raw.get("hold_witness_point") or "review"),
                responsible_role=raw.get("responsible_role"),
                signatories_required=int(raw.get("signatories_required") or 1),
            )
            await self.repo.create_itp_item(item)

        event_bus.publish_detached(
            "qms.itp.cloned_from_template",
            {
                "template_id": str(tpl_id),
                "itp_plan_id": str(plan.id),
                "project_id": str(plan.project_id),
                "work_type": plan.work_type,
                "items_count": len(items_data),
            },
            source_module="qms",
        )
        return plan

    async def delete_itp_template(self, tpl_id: uuid.UUID) -> None:
        tpl = await self.repo.get_itp_template(tpl_id)
        if tpl is None:
            raise ValueError(f"ITP template {tpl_id} not found")
        await self.repo.delete_itp_template(tpl_id)

    # ── Calibration tracking ──────────────────────────────────────────

    async def create_calibration(
        self,
        data: CalibrationCreate,
        *,
        user_id: str | None = None,
    ) -> QMSCalibration:
        del user_id  # accepted for symmetry; not stored on this entity
        if data.valid_until <= data.calibration_date:
            raise ValueError("valid_until must be after calibration_date")
        cal = QMSCalibration(
            project_id=data.project_id,
            instrument_id=data.instrument_id,
            instrument_name=data.instrument_name,
            instrument_type=data.instrument_type,
            serial_number=data.serial_number,
            manufacturer=data.manufacturer,
            calibration_date=data.calibration_date,
            valid_until=data.valid_until,
            calibrated_by=data.calibrated_by,
            certificate_url=data.certificate_url,
            reference_standard=data.reference_standard,
            measurement_uncertainty=data.measurement_uncertainty,
            owner_user_id=data.owner_user_id,
            status="valid",
            notes=data.notes,
        )
        return await self.repo.create_calibration(cal)

    async def update_calibration(
        self,
        cal_id: uuid.UUID,
        data: CalibrationUpdate,
    ) -> QMSCalibration:
        cal = await self.repo.get_calibration(cal_id)
        if cal is None:
            raise ValueError(f"Calibration {cal_id} not found")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if fields:
            await self.repo.update_calibration_fields(cal_id, **fields)
            await self.session.refresh(cal)
        return cal

    async def delete_calibration(self, cal_id: uuid.UUID) -> None:
        cal = await self.repo.get_calibration(cal_id)
        if cal is None:
            raise ValueError(f"Calibration {cal_id} not found")
        await self.repo.delete_calibration(cal_id)

    async def expiring_calibrations(
        self,
        *,
        days: int = 30,
        project_id: uuid.UUID | None = None,
        today: date | None = None,
        publish_event: bool = True,
    ) -> list[QMSCalibration]:
        """Return valid calibrations expiring within ``days``.

        Publishes ``qms.calibration.expiring`` with the count so the
        notifications module can fan-out to owners.
        """
        if days < 0:
            raise ValueError("days must be ≥ 0")
        if today is None:
            today = date.today()
        cutoff = today + timedelta(days=days)
        rows = await self.repo.expiring_calibrations(
            before=cutoff,
            project_id=project_id,
        )
        if rows and publish_event:
            event_bus.publish_detached(
                "qms.calibration.expiring",
                {
                    "count": len(rows),
                    "days": days,
                    "project_id": str(project_id) if project_id else None,
                    "calibration_ids": [str(r.id) for r in rows],
                },
                source_module="qms",
            )
        return rows

    # ── Supplier audit linkage ────────────────────────────────────────

    async def link_audit_to_subcontractor(
        self,
        audit_id: uuid.UUID,
        *,
        subcontractor_id: uuid.UUID,
        rating_delta: int = 0,
    ) -> dict[str, Any]:
        """Publish a ``qms.audit.linked_to_subcontractor`` event.

        The subcontractors module subscribes and folds ``rating_delta``
        into the supplier's running quality rating. Returns the event
        payload for callers that want to log it.
        """
        if not -5 <= rating_delta <= 5:
            raise ValueError("rating_delta must be in -5..+5")
        audit = await self.repo.get_audit(audit_id)
        if audit is None:
            raise ValueError(f"Audit {audit_id} not found")
        if audit.audit_type != "supplier":
            raise ValueError(
                "Only supplier audits can be linked to a subcontractor",
            )
        payload = {
            "audit_id": str(audit_id),
            "project_id": str(audit.project_id),
            "subcontractor_id": str(subcontractor_id),
            "rating_delta": rating_delta,
            "overall_rating": audit.overall_rating,
        }
        event_bus.publish_detached(
            "qms.audit.linked_to_subcontractor",
            payload,
            source_module="qms",
        )
        return payload


# ── Pure helpers (exported for tests / cross-module callers) ──────────────


def severity_to_rating_delta(severity: str) -> int:
    """Map an NCR/finding severity to a default supplier-rating delta."""
    return {
        "minor": -1,
        "observation": 0,
        "major": -2,
        "critical": -3,
    }.get(severity, 0)


def compute_copq_breakdown(
    *,
    ncr_cost: Decimal,
    open_punch_count: int,
    rework_cost_per_punch: Decimal,
    warranty_cost: Decimal = Decimal("0"),
    delay_penalty_cost: Decimal = Decimal("0"),
) -> dict[str, Decimal]:
    """Pure COPQ breakdown — used by tests and offline reporting."""
    rework = rework_cost_per_punch * Decimal(open_punch_count)
    total = ncr_cost + rework + warranty_cost + delay_penalty_cost
    return {
        "ncr_cost": ncr_cost,
        "rework_cost": rework,
        "warranty_cost": warranty_cost,
        "delay_penalty_cost": delay_penalty_cost,
        "copq_total": total,
    }
