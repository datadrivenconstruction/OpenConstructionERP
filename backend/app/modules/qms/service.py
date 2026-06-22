"""‌⁠‍QMS service - business logic for the unified quality module.

Status transitions are guarded by explicit allow-lists. Illegal moves
raise :class:`ValueError`; HTTP-layer translation happens in the router.

Cross-module communication is fire-and-forget via
:meth:`EventBus.publish_detached` - never await a subscriber while
holding a write session on SQLite.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
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
    QMSHoldPointRelease,
    QMSInspection,
    QMSInspectionAttachment,
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
    HoldPointReleaseCreate,
    InspectionAttachmentCreate,
    InspectionCreate,
    InspectionSignatureCreate,
    InspectionUpdate,
    ITPItemCreate,
    ITPItemLinkSpec,
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


class QMSConflictError(ValueError):
    """A write lost a uniqueness/idempotency race.

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers
    still treat it as a client error, while the router can catch it
    specifically to return ``409 Conflict`` instead of ``400``.
    """


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

# ── Signer-role authority ladder (item 12) ────────────────────────────────
# Ranks the inspection sign-off roles so a signer can satisfy a control
# point that names a *lower or equal* authority. A control point that
# requires a "subcontractor" sign-off can therefore also be signed by a GC,
# inspector, designer or client, but a control point that requires a "client"
# sign-off cannot be satisfied by a subcontractor alone. ``responsible_role``
# on the ITP item is free-form; only values that map here are gated, anything
# else (or an empty role) is treated as "any role may sign" so legacy plans
# never lock out their inspectors.
_SIGNER_ROLE_RANK: dict[str, int] = {
    "subcontractor": 1,
    "inspector": 2,
    "designer": 2,
    "GC": 3,
    "client": 4,
}


def _utc_now_iso() -> str:
    """‌⁠‍Return current UTC time as an ISO-8601 string for the String(32) columns."""
    return datetime.now(UTC).isoformat()


def _to_utc_iso(value: datetime | None) -> str | None:
    """Normalise a datetime to a UTC ISO-8601 string for the String(32) columns.

    The QMS temporal columns are stored as ISO strings and queried by lexical
    ``>=`` / ``<`` range comparisons that only preserve chronology when every
    value carries the **same** UTC offset. A naive client datetime produces an
    offset-less string (``"...T10:00:00"``) that sorts *before* an offset-bearing
    one (``"...T10:00:00+00:00"``), silently corrupting the ordering - on both
    SQLite and PostgreSQL, but it bites harder on PG where this is the only
    ordering the planner has. Coercing every write to UTC-with-offset here keeps
    lexical order == chronological order regardless of what the client sent.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


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
        # A predecessor must be an existing item in the SAME plan. This keeps
        # the hold-point dependency graph inside one plan and prevents a
        # cross-plan FK that the release/guard logic can't reason about.
        if data.predecessor_itp_item_id is not None:
            pred = await self.repo.get_itp_item(data.predecessor_itp_item_id)
            if pred is None or pred.itp_plan_id != plan_id:
                raise ValueError(
                    "predecessor_itp_item_id must reference an item in the same ITP plan",
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
            boq_position_id=data.boq_position_id,
            csi_section_ref=data.csi_section_ref,
            spec_drawing_ref=data.spec_drawing_ref,
            bim_element_id=data.bim_element_id,
            predecessor_itp_item_id=data.predecessor_itp_item_id,
        )
        item = await self.repo.create_itp_item(item)
        return item

    async def link_itp_item_to_spec(
        self,
        itp_item_id: uuid.UUID,
        data: ITPItemLinkSpec,
    ) -> ITPItem:
        """Link an ITP control point to its spec sources / predecessor.

        Only the fields supplied in the request are written (PATCH
        semantics). A ``predecessor_itp_item_id`` must reference an item in
        the same plan and may not point at the item itself (self-cycle) nor
        create a direct 2-cycle with a predecessor that already points back.
        """
        item = await self.repo.get_itp_item(itp_item_id)
        if item is None:
            raise ValueError(f"ITP item {itp_item_id} not found")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        pred_id = fields.get("predecessor_itp_item_id")
        if pred_id is not None:
            if pred_id == itp_item_id:
                raise ValueError("An ITP item cannot be its own predecessor")
            pred = await self.repo.get_itp_item(pred_id)
            if pred is None or pred.itp_plan_id != item.itp_plan_id:
                raise ValueError(
                    "predecessor_itp_item_id must reference an item in the same ITP plan",
                )
            if pred.predecessor_itp_item_id == itp_item_id:
                raise ValueError(
                    "Circular hold-point dependency: that item already depends on this one",
                )
        if fields:
            await self.repo.update_itp_item_fields(itp_item_id, **fields)
            await self.session.refresh(item)
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
            scheduled_at=_to_utc_iso(data.scheduled_at),
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
                fields[key] = _to_utc_iso(value)
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

    @staticmethod
    def validate_signer_role(required_role: str | None, signer_role: str) -> None:
        """Gate a sign-off by the control point's ``responsible_role`` (item 12).

        The signer's role must rank *at or above* the role the ITP control
        point names. Unknown / empty required roles are treated as "any role
        may sign" so free-form legacy plans never lock out inspectors. Raises
        :class:`ValueError` when the signer has insufficient authority.
        """
        if not required_role:
            return
        required_rank = _SIGNER_ROLE_RANK.get(required_role)
        if required_rank is None:
            # Required role is not on the authority ladder - cannot gate it.
            return
        signer_rank = _SIGNER_ROLE_RANK.get(signer_role, 0)
        if signer_rank < required_rank:
            raise ValueError(
                f"Signer role '{signer_role}' is below the control point's required authority '{required_role}'",
            )

    async def add_signature(
        self,
        inspection_id: uuid.UUID,
        data: InspectionSignatureCreate,
        *,
        default_signer_user_id: uuid.UUID | None = None,
        signer_ip: str | None = None,
        signer_user_agent: str | None = None,
    ) -> QMSInspectionSignature:
        """Record a sign-off against an inspection.

        The signer is resolved as ``data.signer_user_id`` when supplied
        (sign on behalf of another member), otherwise ``default_signer_user_id``
        - the authenticated caller. This lets the UI "sign as me" without
        hand-typing a UUID.

        ``signer_ip`` / ``signer_user_agent`` capture non-repudiation context
        from the HTTP request (item 12); both are optional so service-level
        callers and tests can omit them.
        """
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        if inspection.status in ("passed", "failed"):
            raise ValueError(
                f"Cannot sign an inspection in status '{inspection.status}'",
            )
        signer_user_id = data.signer_user_id or default_signer_user_id
        if signer_user_id is None:
            raise ValueError("signer_user_id is required")
        # Role gating: a control point that names a responsible_role can only
        # be signed by a signer with at-or-above authority.
        if inspection.itp_item_id is not None:
            item = await self.repo.get_itp_item(inspection.itp_item_id)
            if item is not None:
                self.validate_signer_role(item.responsible_role, data.signer_role)
        # Dedup: one (user, role) signature per inspection. Two distinct
        # roles on the same user are still allowed (e.g. GC inspector +
        # designer reviewer when one person wears both hats).
        #
        # The pre-flight list-then-check below gives a clean 409 in the common
        # case, but it is NOT atomic: two concurrent sign requests for the same
        # (inspection, user, role) can both pass it and both INSERT, inflating
        # the signatory count and defeating the multi-signatory completion gate.
        # The ``uq_oe_qms_inspection_signature_inspection_user_role`` unique
        # constraint (models.py) is the backstop; we catch the resulting
        # IntegrityError on the loser so it gets a 409 instead of an opaque 500.
        existing = await self.repo.list_signatures(inspection_id)
        for prior in existing:
            if prior.signer_user_id == signer_user_id and prior.signer_role == data.signer_role:
                raise QMSConflictError(
                    f"Signer has already signed this inspection in role '{data.signer_role}'",
                )
        now_iso = _utc_now_iso()
        sig = QMSInspectionSignature(
            inspection_id=inspection_id,
            signer_user_id=signer_user_id,
            signer_role=data.signer_role,
            signed_at=now_iso,
            signature_method=data.signature_method,
            comments=data.comments,
            timestamp_utc=now_iso,
            signer_ip=signer_ip,
            signer_user_agent=(signer_user_agent[:512] if signer_user_agent else None),
        )
        try:
            return await self.repo.add_signature(sig)
        except IntegrityError as exc:
            # Lost the unique-constraint race: another concurrent request
            # inserted the same (inspection, user, role) signature first.
            # Roll back so the session is usable, then surface a clean 409.
            await self.session.rollback()
            logger.info(
                "Race on QMS signature inspection=%s user=%s role=%s (treated as duplicate)",
                inspection_id,
                signer_user_id,
                data.signer_role,
            )
            raise QMSConflictError(
                f"Signer has already signed this inspection in role '{data.signer_role}'",
            ) from exc

    async def required_signatures(self, inspection: QMSInspection) -> int:
        """Resolve how many signatures this inspection needs to complete.

        Mirrors :meth:`complete_inspection`: an inspection linked to an ITP
        item inherits that item's ``signatories_required`` (default 1), so
        the UI can show ``collected/required`` and gate the Complete button.
        """
        required = 1
        if inspection.itp_item_id is not None:
            item = await self.repo.get_itp_item(inspection.itp_item_id)
            if item is not None:
                required = item.signatories_required
        return required

    async def list_signatures(
        self,
        inspection_id: uuid.UUID,
    ) -> list[QMSInspectionSignature]:
        return await self.repo.list_signatures(inspection_id)

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
        item: ITPItem | None = None
        if inspection.itp_item_id is not None:
            item = await self.repo.get_itp_item(inspection.itp_item_id)
            if item is not None:
                required_sigs = item.signatories_required

        # Hold-point sequencing guard: a control point with a predecessor
        # cannot be PASSED until its predecessor's inspection has passed.
        # Failing or conditional an inspection is always allowed (you must be
        # able to record a failure regardless of upstream state).
        if result == "passed" and item is not None and item.predecessor_itp_item_id is not None:
            pred_ok = await self.check_hold_point_predecessor_status(item.id)
            if not pred_ok["predecessor_passed"]:
                raise ValueError(
                    "Blocked: predecessor hold point has not passed yet "
                    f"(item '{pred_ok.get('predecessor_name') or pred_ok['predecessor_itp_item_id']}')",
                )

        # Count DISTINCT signers, not raw rows: ``signatories_required`` is a
        # head-count of separate people, so one person signing in two roles
        # must not satisfy a 2-signatory gate. (The DB unique constraint stops
        # the same (user, role) row twice; this stops the same user counting
        # twice across different roles.)
        sigs = await self.repo.list_signatures(inspection_id)
        distinct_signers = {s.signer_user_id for s in sigs}
        if len(distinct_signers) < required_sigs:
            raise ValueError(
                f"Cannot complete inspection: {len(distinct_signers)}/{required_sigs} required signatures collected",
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

        # Hold-point lifecycle events (item 12). When the inspection is a
        # hold or witness point, fan out a dedicated event so downstream
        # subscribers (punchlist, notifications) can react to the gate
        # passing or failing without parsing the generic passed/failed event.
        is_hold_point = item is not None and item.hold_witness_point in ("hold", "witness")
        if is_hold_point and result in ("passed", "failed"):
            hold_event = (
                "qms.inspection.hold_point_passed" if result == "passed" else "qms.inspection.hold_point_failed"
            )
            event_bus.publish_detached(
                hold_event,
                {
                    "inspection_id": str(inspection_id),
                    "project_id": str(inspection.project_id),
                    "itp_item_id": str(item.id),
                    "control_point_name": item.control_point_name,
                    "hold_witness_point": item.hold_witness_point,
                    "result": result,
                    "location_ref": inspection.location_ref,
                },
                source_module="qms",
            )

        # Approval integration (item 12 gap #4). A failed or conditional
        # result on a hold / witness point does not release the gate by
        # itself - it needs a formal disposition. We fan out
        # ``qms.inspection.approval_requested`` so the approval_routes engine
        # (which subscribes in its own module) can open an approval instance
        # against the inspection. Emitting an event rather than calling the
        # approval service inline keeps QMS loadable without approval_routes
        # in minimal fixtures and avoids holding a write session across a
        # second module's transaction.
        if is_hold_point and result in ("failed", "conditional"):
            event_bus.publish_detached(
                "qms.inspection.approval_requested",
                {
                    "inspection_id": str(inspection_id),
                    "project_id": str(inspection.project_id),
                    "itp_item_id": str(item.id),
                    "control_point_name": item.control_point_name,
                    "hold_witness_point": item.hold_witness_point,
                    "result": result,
                    "reason": (
                        "Hold point did not pass cleanly; a disposition approval is required "
                        "before dependent work may proceed."
                    ),
                },
                source_module="qms",
            )

        logger.info(
            "QMS inspection completed: project=%s id=%s result=%s signatures=%d/%d hold_point=%s",
            inspection.project_id,
            inspection_id,
            result,
            len(distinct_signers),
            required_sigs,
            is_hold_point,
        )
        return inspection

    # ── Hold-point sequencing + evidence + release (item 12) ────────────

    async def check_hold_point_predecessor_status(
        self,
        itp_item_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Resolve whether an ITP item's predecessor hold point has passed.

        Returns a dict describing the gate. ``predecessor_passed`` is True
        when there is no predecessor, or when at least one inspection
        scheduled against the predecessor item has reached ``passed``.
        """
        item = await self.repo.get_itp_item(itp_item_id)
        if item is None:
            raise ValueError(f"ITP item {itp_item_id} not found")
        if item.predecessor_itp_item_id is None:
            return {
                "itp_item_id": itp_item_id,
                "predecessor_itp_item_id": None,
                "predecessor_name": None,
                "predecessor_passed": True,
            }
        pred = await self.repo.get_itp_item(item.predecessor_itp_item_id)
        pred_inspections = await self.repo.list_inspections_for_itp_item(
            item.predecessor_itp_item_id,
        )
        passed = any(ins.status == "passed" for ins in pred_inspections)
        return {
            "itp_item_id": itp_item_id,
            "predecessor_itp_item_id": item.predecessor_itp_item_id,
            "predecessor_name": pred.control_point_name if pred is not None else None,
            "predecessor_passed": passed,
        }

    async def hold_point_status(
        self,
        inspection_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Aggregate the hold-point gate state for an inspection.

        Combines predecessor status, whether the linked item is a hold/witness
        point, and whether a manual release record already exists. Drives the
        traffic-light in the UI.
        """
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        is_hold_point = False
        predecessor_itp_item_id: uuid.UUID | None = None
        predecessor_passed = True
        blocking_reason: str | None = None
        if inspection.itp_item_id is not None:
            item = await self.repo.get_itp_item(inspection.itp_item_id)
            if item is not None:
                is_hold_point = item.hold_witness_point in ("hold", "witness")
                if item.predecessor_itp_item_id is not None:
                    pred = await self.check_hold_point_predecessor_status(item.id)
                    predecessor_itp_item_id = pred["predecessor_itp_item_id"]
                    predecessor_passed = pred["predecessor_passed"]
                    if not predecessor_passed:
                        blocking_reason = (
                            "Predecessor hold point "
                            f"'{pred.get('predecessor_name') or predecessor_itp_item_id}' "
                            "has not passed yet"
                        )
        release = await self.repo.get_hold_point_release(inspection_id)
        blocked = not predecessor_passed and inspection.status not in ("passed", "failed")
        return {
            "inspection_id": inspection_id,
            "itp_item_id": inspection.itp_item_id,
            "is_hold_point": is_hold_point,
            "predecessor_itp_item_id": predecessor_itp_item_id,
            "predecessor_passed": predecessor_passed,
            "blocked": blocked,
            "blocking_reason": blocking_reason,
            "released": release is not None,
        }

    async def add_inspection_attachment(
        self,
        inspection_id: uuid.UUID,
        data: InspectionAttachmentCreate,
        *,
        uploaded_by_user_id: uuid.UUID | None = None,
    ) -> QMSInspectionAttachment:
        """Link a stored document to an inspection as auditable evidence.

        Keeps the denormalised ``attachment_document_ids`` array on the
        inspection in sync so a single inspection read returns the id set.
        """
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        # Idempotency: a document can be linked to an inspection only once.
        existing = await self.repo.list_inspection_attachments(inspection_id)
        if any(a.document_id == data.document_id for a in existing):
            raise ValueError("This document is already attached to the inspection")
        attachment = QMSInspectionAttachment(
            inspection_id=inspection_id,
            document_id=data.document_id,
            caption=data.caption,
            file_hash_sha256=(data.file_hash_sha256.lower() if data.file_hash_sha256 else None),
            uploaded_by=uploaded_by_user_id,
            attached_at=_utc_now_iso(),
        )
        attachment = await self.repo.create_inspection_attachment(attachment)
        # Sync the denormalised id list (deduplicated, order-stable).
        doc_ids = list(inspection.attachment_document_ids or [])
        doc_str = str(data.document_id)
        if doc_str not in doc_ids:
            doc_ids.append(doc_str)
            await self.repo.update_inspection_fields(
                inspection_id,
                attachment_document_ids=doc_ids,
            )
        await self.repo.append_audit(
            entity_type="inspection",
            entity_id=inspection_id,
            action="evidence_attached",
            after_state={"document_id": doc_str},
        )
        return attachment

    async def list_inspection_attachments(
        self,
        inspection_id: uuid.UUID,
    ) -> list[QMSInspectionAttachment]:
        return await self.repo.list_inspection_attachments(inspection_id)

    async def release_hold_point(
        self,
        inspection_id: uuid.UUID,
        data: HoldPointReleaseCreate,
        *,
        released_by_user_id: uuid.UUID | None = None,
    ) -> QMSHoldPointRelease:
        """Release a passed hold point so dependent work can proceed.

        Pre-conditions:
          * the inspection must exist and be linked to a hold / witness point,
          * it must have PASSED (you cannot release a gate that has not been
            satisfied),
          * it must not already have a release record (the FK is unique).

        Emits ``qms.inspection.hold_point_released`` on success.
        """
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        if inspection.itp_item_id is None:
            raise ValueError("Inspection is not linked to an ITP control point")
        item = await self.repo.get_itp_item(inspection.itp_item_id)
        if item is None or item.hold_witness_point not in ("hold", "witness"):
            raise ValueError("Only hold or witness control points can be released")
        if inspection.status != "passed":
            raise ValueError(
                f"Cannot release a hold point from status '{inspection.status}'; the inspection must have passed first",
            )
        if await self.repo.get_hold_point_release(inspection_id) is not None:
            raise ValueError("This hold point has already been released")

        release = QMSHoldPointRelease(
            inspection_id=inspection_id,
            released_by=released_by_user_id,
            released_at=_utc_now_iso(),
            justification=data.justification,
            approval_route_id=data.approval_route_id,
        )
        release = await self.repo.create_hold_point_release(release)
        await self.repo.append_audit(
            entity_type="inspection",
            entity_id=inspection_id,
            action="hold_point_released",
            actor_user_id=released_by_user_id,
            after_state={"justification": data.justification},
        )
        event_bus.publish_detached(
            "qms.inspection.hold_point_released",
            {
                "inspection_id": str(inspection_id),
                "project_id": str(inspection.project_id),
                "itp_item_id": str(item.id),
                "control_point_name": item.control_point_name,
                "released_by": (str(released_by_user_id) if released_by_user_id else None),
                "justification": data.justification,
            },
            source_module="qms",
        )
        logger.info(
            "QMS hold point released: project=%s inspection=%s by=%s",
            inspection.project_id,
            inspection_id,
            released_by_user_id,
        )
        return release

    # ── Quality-gate enforcement for downstream modules (item 12 gap #3) ─

    async def is_hold_point_satisfied(
        self,
        itp_item_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Resolve whether the hold point on an ITP item is satisfied.

        A hold / witness point is *satisfied* (downstream work may proceed)
        when its most-recent inspection has PASSED, OR a manual hold-point
        release record exists for a passed inspection. A ``review`` point is
        not a gate and is always satisfied. Returns a dict the caller can use
        both for a boolean decision and for surfacing the blocking reason in
        a UI / error message.

        This is the read-only seam other modules (task progression, change
        orders) call before allowing a gated action - see
        :meth:`assert_downstream_action_allowed`.
        """
        item = await self.repo.get_itp_item(itp_item_id)
        if item is None:
            raise ValueError(f"ITP item {itp_item_id} not found")
        if item.hold_witness_point not in ("hold", "witness"):
            return {
                "itp_item_id": itp_item_id,
                "is_hold_point": False,
                "satisfied": True,
                "reason": None,
            }
        inspections = await self.repo.list_inspections_for_itp_item(itp_item_id)
        if not inspections:
            return {
                "itp_item_id": itp_item_id,
                "is_hold_point": True,
                "satisfied": False,
                "reason": (f"Hold point '{item.control_point_name}' has no inspection scheduled yet"),
            }
        passed = [ins for ins in inspections if ins.status == "passed"]
        if not passed:
            # Any failed inspection is the strongest blocking signal.
            failed = any(ins.status == "failed" for ins in inspections)
            reason = (
                f"Hold point '{item.control_point_name}' last inspection failed"
                if failed
                else f"Hold point '{item.control_point_name}' inspection has not passed yet"
            )
            return {
                "itp_item_id": itp_item_id,
                "is_hold_point": True,
                "satisfied": False,
                "reason": reason,
            }
        # At least one passed inspection. Witness points are satisfied on a
        # pass; hold points additionally require a manual release record so a
        # human explicitly unblocked downstream work.
        if item.hold_witness_point == "witness":
            return {
                "itp_item_id": itp_item_id,
                "is_hold_point": True,
                "satisfied": True,
                "reason": None,
            }
        released = False
        for ins in passed:
            if await self.repo.get_hold_point_release(ins.id) is not None:
                released = True
                break
        return {
            "itp_item_id": itp_item_id,
            "is_hold_point": True,
            "satisfied": released,
            "reason": (
                None if released else (f"Hold point '{item.control_point_name}' has passed but has not been released")
            ),
        }

    async def assert_downstream_action_allowed(
        self,
        itp_item_id: uuid.UUID,
    ) -> None:
        """Raise :class:`ValueError` if a hold point blocks downstream work.

        Thin guard wrapper over :meth:`is_hold_point_satisfied` for callers
        (task progression, change-order approval) that want fail-closed
        semantics: the action is allowed only when the gate is satisfied.
        """
        status = await self.is_hold_point_satisfied(itp_item_id)
        if not status["satisfied"]:
            raise ValueError(
                f"Blocked by quality gate: {status['reason'] or 'hold point not satisfied'}",
            )

    # ── Compliance-ready export (item 12 gap #7) ────────────────────────

    async def build_inspection_compliance_record(
        self,
        inspection_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Assemble the audit-ready record for a single inspection.

        Bundles the inspection, its linked control point, every signature
        (with non-repudiation context), evidence attachments (with their
        SHA-256 integrity hashes) and the hold-point release, if any. The
        shape is reused by both the JSON and CSV/PDF export endpoints so a
        compliance reviewer always sees the same fields.
        """
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise ValueError(f"Inspection {inspection_id} not found")
        item: ITPItem | None = None
        if inspection.itp_item_id is not None:
            item = await self.repo.get_itp_item(inspection.itp_item_id)
        signatures = await self.repo.list_signatures(inspection_id)
        attachments = await self.repo.list_inspection_attachments(inspection_id)
        release = await self.repo.get_hold_point_release(inspection_id)
        return self._assemble_inspection_compliance_record(
            inspection,
            item,
            signatures,
            attachments,
            release,
        )

    @staticmethod
    def _assemble_inspection_compliance_record(
        inspection: QMSInspection,
        item: ITPItem | None,
        signatures: list[QMSInspectionSignature],
        attachments: list[QMSInspectionAttachment],
        release: QMSHoldPointRelease | None,
    ) -> dict[str, Any]:
        """Build the compliance record dict from already-loaded rows.

        Pure / synchronous so it can be driven both by the single-inspection
        path (which loads each piece on demand) and by the batched whole-plan
        export (which pre-loads everything and groups in memory). The output
        shape is identical for both callers.
        """
        return {
            "inspection_id": str(inspection.id),
            "project_id": str(inspection.project_id),
            "status": inspection.status,
            "scheduled_at": inspection.scheduled_at,
            "performed_at": inspection.performed_at,
            "location_ref": inspection.location_ref,
            "control_point_name": (item.control_point_name if item else None),
            "hold_witness_point": (item.hold_witness_point if item else None),
            "responsible_role": (item.responsible_role if item else None),
            "acceptance_criteria": (item.acceptance_criteria if item else None),
            "csi_section_ref": (item.csi_section_ref if item else None),
            "spec_drawing_ref": (item.spec_drawing_ref if item else None),
            "boq_position_id": (str(item.boq_position_id) if item and item.boq_position_id else None),
            "bim_element_id": (item.bim_element_id if item else None),
            "signatures": [
                {
                    "signer_user_id": str(s.signer_user_id),
                    "signer_role": s.signer_role,
                    "signed_at": s.signed_at,
                    "signature_method": s.signature_method,
                    "timestamp_utc": s.timestamp_utc,
                    "signer_ip": s.signer_ip,
                    "comments": s.comments,
                }
                for s in signatures
            ],
            "evidence": [
                {
                    "document_id": str(a.document_id),
                    "caption": a.caption,
                    "file_hash_sha256": a.file_hash_sha256,
                    "uploaded_by": (str(a.uploaded_by) if a.uploaded_by else None),
                    "attached_at": a.attached_at,
                }
                for a in attachments
            ],
            "released": release is not None,
            "released_by": (str(release.released_by) if release and release.released_by else None),
            "released_at": (release.released_at if release else None),
            "release_justification": (release.justification if release else None),
        }

    async def build_plan_compliance_export(
        self,
        plan_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Assemble the compliance export for a whole ITP plan.

        One compliance record per inspection across every control point in
        the plan, plus the plan header. Used by the CSV / PDF endpoints so an
        auditor can pull the full quality dossier for a work package.
        """
        plan = await self.repo.get_itp_plan(plan_id)
        if plan is None:
            raise ValueError(f"ITP plan {plan_id} not found")
        items = await self.repo.list_itp_items(plan_id)

        # Batch-load the whole dossier instead of fanning out one query per
        # control point and ~5 more per inspection (BUG-perf-qms N+1). The
        # item ids drive the inspection fetch; the inspection ids drive the
        # signature / attachment / release fetches. Everything is then grouped
        # in memory so the assembled records are byte-identical to the
        # per-inspection path.
        item_ids = [item.id for item in items]
        inspections = await self.repo.list_inspections_for_itp_items(item_ids)
        inspection_ids = [ins.id for ins in inspections]

        # Group inspections under their control point. The batch query orders
        # by ``(itp_item_id, created_at)`` so each per-item bucket stays in the
        # oldest-first order ``list_inspections_for_itp_item`` produced.
        inspections_by_item: dict[uuid.UUID, list[QMSInspection]] = {}
        for ins in inspections:
            if ins.itp_item_id is not None:
                inspections_by_item.setdefault(ins.itp_item_id, []).append(ins)

        sigs_by_inspection: dict[uuid.UUID, list[QMSInspectionSignature]] = {}
        for sig in await self.repo.list_signatures_for_inspections(inspection_ids):
            sigs_by_inspection.setdefault(sig.inspection_id, []).append(sig)
        atts_by_inspection: dict[uuid.UUID, list[QMSInspectionAttachment]] = {}
        for att in await self.repo.list_inspection_attachments_for_inspections(inspection_ids):
            atts_by_inspection.setdefault(att.inspection_id, []).append(att)
        release_by_inspection: dict[uuid.UUID, QMSHoldPointRelease] = {
            rel.inspection_id: rel for rel in await self.repo.list_hold_point_releases_for_inspections(inspection_ids)
        }

        # Walk items in their loaded order (``sequence`` ASC) and, within each,
        # the oldest-first inspections - byte-for-byte the same traversal the
        # previous nested loop produced, just without the per-row queries.
        records: list[dict[str, Any]] = []
        for item in items:
            for ins in inspections_by_item.get(item.id, []):
                records.append(
                    self._assemble_inspection_compliance_record(
                        ins,
                        item,
                        sigs_by_inspection.get(ins.id, []),
                        atts_by_inspection.get(ins.id, []),
                        release_by_inspection.get(ins.id),
                    )
                )
        return {
            "plan_id": str(plan.id),
            "project_id": str(plan.project_id),
            "name": plan.name,
            "work_type": plan.work_type,
            "status": plan.status,
            "generated_at": _utc_now_iso(),
            "records": records,
        }

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
            due_date=_to_utc_iso(data.due_date),
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
        if variation_id is None:
            raise ValueError(
                "Escalation requires an existing variation order id "
                "(variation_id); the QMS module does not fabricate one",
            )
        if ncr.linked_variation_id is not None and ncr.linked_variation_id != variation_id:
            raise ValueError(
                "NCR is already linked to a different variation; unlink it first",
            )
        # Validate the variation exists and belongs to the same project so
        # the link always points at a real VariationOrder row. Read-only
        # lazy import keeps QMS loadable without the variations module in
        # minimal test fixtures.
        try:
            from app.modules.variations.repository import VariationOrderRepository

            vo_repo = VariationOrderRepository(self.session)
            variation = await vo_repo.get_by_id(variation_id)
        except ImportError:
            variation = None
        if variation is None:
            raise ValueError(f"Variation {variation_id} not found")
        if getattr(variation, "project_id", None) != ncr.project_id:
            raise ValueError(
                "Variation belongs to a different project than the NCR",
            )
        var_id = variation_id
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
            due_date=_to_utc_iso(data.due_date),
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
            fields["due_date"] = _to_utc_iso(fields["due_date"])
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
            planned_date=_to_utc_iso(data.planned_date),
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
                fields[key] = _to_utc_iso(value)
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
            due_date=_to_utc_iso(data.due_date),
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
        project lookup fails and no fallback was provided - callers
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
        except Exception:  # noqa: BLE001 - defensive log-and-degrade
            logger.exception(
                "QMS COPQ: project currency lookup failed for %s",
                project_id,
            )
        return ""

    async def _project_currency_and_fx(
        self,
        project_id: uuid.UUID,
    ) -> tuple[str, dict[str, str]]:
        """Load the project base currency and its FX map ``{code: rate}``.

        ``rate`` is units of base currency per 1 unit of the foreign
        currency (the same convention BOQ uses). Returns ``("", {})`` if
        the project can't be loaded so the COPQ computation degrades
        gracefully rather than raising.
        """
        try:
            from app.modules.projects.repository import ProjectRepository

            proj_repo = ProjectRepository(self.session)
            project = await proj_repo.get_by_id(project_id)
        except Exception:  # noqa: BLE001 - defensive log-and-degrade
            logger.exception(
                "QMS COPQ: project lookup failed for %s",
                project_id,
            )
            return "", {}
        if project is None:
            return "", {}
        base = (getattr(project, "currency", "") or "").strip().upper()
        fx_map: dict[str, str] = {}
        raw = getattr(project, "fx_rates", None)
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                code = str(entry.get("code") or "").strip().upper()
                rate = str(entry.get("rate") or "").strip()
                if code and rate:
                    fx_map[code] = rate
        return base, fx_map

    async def _ncr_cost_total_in_base(
        self,
        project_id: uuid.UUID,
        *,
        requested_currency: str = "",
    ) -> tuple[Decimal, str, dict[str, Decimal]]:
        """Sum NCR cost impacts converted into the project base currency.

        Mirrors ``boq.service._position_total_in_base``: each per-currency
        bucket priced in a non-base currency contributes
        ``amount * fx_rates[code]``. A bucket whose currency has no FX rate
        is summed in its own units anyway (never dropped) so a missing rate
        degrades visibly. Returns ``(total_in_base, base_currency,
        per_currency_breakdown)`` - the breakdown lets the UI surface a
        mixed-currency warning when conversion was incomplete.
        """
        by_currency = await self.repo.sum_ncr_cost_impact_by_currency(project_id)
        base, fx_map = await self._project_currency_and_fx(project_id)
        if requested_currency:
            base = requested_currency.strip().upper()
        total = Decimal("0")
        for code, amount in by_currency.items():
            if code and base and code != base:
                rate = fx_map.get(code)
                if rate:
                    try:
                        factor = Decimal(str(rate))
                    except (ArithmeticError, ValueError):
                        factor = Decimal("1")
                    if factor > 0:
                        total += amount * factor
                        continue
            # Same currency, no base known, or missing rate - add raw.
            total += amount
        return total, base, by_currency

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

        # FX-convert each NCR currency bucket into the project base currency
        # rather than coalesce-summing mixed currencies (project money rule).
        ncr_total, base_currency, _breakdown = await self._ncr_cost_total_in_base(
            project_id,
            requested_currency=currency,
        )
        open_punch = await self.repo.count_open_punch(project_id)
        rework_total = per_punch * Decimal(open_punch)
        copq_total = ncr_total + rework_total

        resolved_currency = await self._resolve_project_currency(
            project_id,
            currency or base_currency,
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
        come from tenant config - here we surface them as explicit kwargs.
        """
        per_punch = rework_cost_per_punch or _DEFAULT_REWORK_COST_PER_PUNCH
        warranty = Decimal(str(warranty_cost or 0))
        delay = Decimal(str(delay_penalty_cost or 0))

        # FX-convert each NCR currency bucket into the project base currency
        # rather than coalesce-summing mixed currencies (project money rule).
        ncr_total, base_currency, _breakdown = await self._ncr_cost_total_in_base(
            project_id,
            requested_currency=currency,
        )
        open_punch = await self.repo.count_open_punch(project_id)
        rework_total = per_punch * Decimal(open_punch)
        copq_total = ncr_total + rework_total + warranty + delay

        resolved_currency = await self._resolve_project_currency(
            project_id,
            currency or base_currency,
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
        relation in-process (kept simple - datasets are small per period).
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
                # No plans of this work_type - empty trend
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
                f"First-pass yield {fpy:.2%} below 85% target - review inspector training and rework root causes."
            )
        if findings_open > findings_closed:
            recs.append(
                f"{findings_open} open findings vs {findings_closed} closed - "
                "increase CAPA closure cadence and review responsible owners."
            )
        if ncrs_raised > 0 and ncrs_closed / max(ncrs_raised, 1) < 0.5:
            recs.append(
                f"Only {ncrs_closed}/{ncrs_raised} NCRs closed in period - escalate ageing NCRs to senior leadership."
            )
        if open_punch > 50:
            recs.append(
                f"{open_punch} open punch items - schedule a rolling punch-down sprint before final inspection."
            )
        if not recs:
            recs.append("QMS performance within thresholds - maintain current cadence.")

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
    """Pure COPQ breakdown - used by tests and offline reporting."""
    rework = rework_cost_per_punch * Decimal(open_punch_count)
    total = ncr_cost + rework + warranty_cost + delay_penalty_cost
    return {
        "ncr_cost": ncr_cost,
        "rework_cost": rework,
        "warranty_cost": warranty_cost,
        "delay_penalty_cost": delay_penalty_cost,
        "copq_total": total,
    }
