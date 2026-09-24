# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hold/witness/surveillance/review gating service (Pillar 5).

The gating engine built on the inspection ``intervention_point`` seed. A gate is
attached to an activity, a handover package or an inspection; ``blocks_progress`` is the
single source of truth for whether it stops work. A hold gate is a hard block and can
never be waived; witness / surveillance / review gates default to soft and may be waived.

Release is defence in depth: RBAC (manager) gates the endpoint, and the service requires
the caller's asserted ``party_role`` to satisfy the gate's ``required_party_role`` (a qc
cannot release an ahj gate). A release captures an e-signature - a SHA-256 over a
canonical snapshot, with the signer and IP - and publishes ``cc.gate.released`` so
schedule / handover consumers can unblock.
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.construction_control.deletion import refuse_if_locked
from app.modules.construction_control.models import AcceptanceCriterion, HoldGate, Inspection
from app.modules.construction_control.repository import HoldGateRepository
from app.modules.construction_control.schemas import (
    HoldGateCreate,
    HoldGateReleaseIn,
    HoldGateUpdate,
    HoldGateWaiveIn,
)
from app.modules.construction_control.signing import snapshot_sha256

logger = logging.getLogger(__name__)

# A blocking gate (hold by default) stops progress; the rest are advisory unless the
# caller flips ``blocks_progress`` on at create time.
_BLOCKING_BY_DEFAULT = {"hold"}
# Only these point types may be waived; a hold can only be released, never waived.
_WAIVABLE_POINT_TYPES = {"witness", "surveillance", "review"}

# Only a pending gate may be deleted; every other state carries a signature.
_GATE_DELETE_LOCKED_STATUSES = frozenset({"released", "waived", "void"})
# The party-role hierarchy used to decide whether a caller satisfies a required role.
# A higher-authority party may stand in for a lower one (an authority having
# jurisdiction or a third-party inspector may release a qc/qa gate), never the reverse.
_PARTY_ROLE_RANK = {"qc": 0, "qa": 1, "tpi": 2, "ahj": 3}


def party_role_satisfies(asserted: str, required: str) -> bool:
    """True when an ``asserted`` party role is authorised to act for a ``required`` one.

    Equal roles satisfy; a higher-rank role satisfies a lower one (ahj >= tpi >= qa >= qc).
    A lower-rank role never satisfies a higher requirement, so a qc cannot release an ahj
    gate. Unknown roles only satisfy themselves (defensive default).
    """
    if asserted == required:
        return True
    a = _PARTY_ROLE_RANK.get(asserted)
    r = _PARTY_ROLE_RANK.get(required)
    if a is None or r is None:
        return False
    return a >= r


class GatingService:
    """Business logic for hold/witness/surveillance/review gates (Pillar 5)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.gates = HoldGateRepository(session)

    # ── Cross-project guards ─────────────────────────────────────────────────

    async def _assert_criterion_in_project(self, criterion_id: uuid.UUID, project_id: uuid.UUID) -> None:
        criterion = await self.session.get(AcceptanceCriterion, criterion_id)
        if criterion is None or criterion.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Acceptance criterion not found in this project",
            )

    async def _assert_inspection_in_project(self, inspection_id: uuid.UUID, project_id: uuid.UUID) -> None:
        inspection = await self.session.get(Inspection, inspection_id)
        if inspection is None or inspection.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inspection not found in this project",
            )

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create_gate(self, data: HoldGateCreate, user_id: str | None) -> HoldGate:
        if data.criterion_id is not None:
            await self._assert_criterion_in_project(data.criterion_id, data.project_id)
        if data.inspection_id is not None:
            await self._assert_inspection_in_project(data.inspection_id, data.project_id)

        # blocks_progress defaults from the point type when the caller did not set it.
        blocks = data.blocks_progress
        if blocks is None:
            blocks = data.point_type in _BLOCKING_BY_DEFAULT

        gate = HoldGate(
            project_id=data.project_id,
            point_type=data.point_type,
            title=data.title,
            description=data.description,
            required_party_role=data.required_party_role,
            inspection_id=str(data.inspection_id) if data.inspection_id else None,
            criterion_id=str(data.criterion_id) if data.criterion_id else None,
            attached_kind=data.attached_kind,
            attached_id=data.attached_id,
            blocks_progress=blocks,
            status="pending",
            created_by=user_id,
            metadata_=data.metadata,
        )
        gate = await self.gates.create(gate)
        logger.info(
            "Hold gate created: %s (%s, blocks=%s) project %s",
            gate.gate_number,
            data.point_type,
            blocks,
            data.project_id,
        )
        return gate

    async def get_gate(self, gate_id: uuid.UUID) -> HoldGate:
        gate = await self.gates.get_by_id(gate_id)
        if gate is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hold gate not found")
        return gate

    async def list_gates(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        point_type: str | None = None,
        attached_kind: str | None = None,
        attached_id: str | None = None,
    ) -> tuple[list[HoldGate], int]:
        return await self.gates.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            point_type=point_type,
            attached_kind=attached_kind,
            attached_id=attached_id,
        )

    async def update_gate(self, gate_id: uuid.UUID, data: HoldGateUpdate) -> HoldGate:
        gate = await self.get_gate(gate_id)
        if gate.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This gate is {gate.status} and can no longer be edited; only a pending gate is editable. "
                    "Create a new gate if a further check is needed."
                ),
            )
        fields = data.model_dump(exclude_unset=True)
        if fields.get("criterion_id") is not None:
            await self._assert_criterion_in_project(fields["criterion_id"], gate.project_id)
            fields["criterion_id"] = str(fields["criterion_id"])
        if fields.get("inspection_id") is not None:
            await self._assert_inspection_in_project(fields["inspection_id"], gate.project_id)
            fields["inspection_id"] = str(fields["inspection_id"])
        fields = self._merge_metadata_patch(fields, gate)
        if not fields:
            return gate
        await self.gates.update_fields(gate_id, **fields)
        await self.session.refresh(gate)
        return gate

    async def delete_gate(self, gate_id: uuid.UUID) -> None:
        """Delete a gate that is still pending.

        A released or waived gate is the authority under which work was allowed
        to carry on, captured with the releasing party's e-signature. Deleting
        it would leave the work it unblocked with no record of who let it
        through, so only a gate nobody has decided on can go.
        """
        gate = await self.get_gate(gate_id)
        refuse_if_locked(
            f"gate {gate.gate_number}",
            gate.status,
            _GATE_DELETE_LOCKED_STATUSES,
            reason=(
                "It carries the signed decision that let the work past this point, "
                "which is the record of who authorised it."
            ),
        )
        await self.gates.delete(gate_id)

    # ── Release / waive / void (the FSM) ──────────────────────────────────────

    async def release_gate(
        self,
        gate_id: uuid.UUID,
        data: HoldGateReleaseIn,
        user_id: str | None,
        *,
        signature_ip: str | None,
    ) -> HoldGate:
        """Release a pending gate. The caller's ``party_role`` must satisfy the gate's
        ``required_party_role`` (a qc cannot release an ahj gate). If the gate names a
        linked inspection, that inspection must have passed. Captures an e-signature and
        publishes ``cc.gate.released`` so downstream consumers can unblock.
        """
        gate = await self.get_gate(gate_id)
        if gate.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot release a gate with status '{gate.status}'; only a pending gate can be released",
            )
        if not party_role_satisfies(data.party_role, gate.required_party_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Party role '{data.party_role}' cannot release a gate that requires '{gate.required_party_role}'"
                ),
            )
        # If a satisfying inspection is named, it must have passed before the gate releases.
        if gate.inspection_id:
            try:
                inspection = await self.session.get(Inspection, uuid.UUID(gate.inspection_id))
            except (ValueError, TypeError):
                inspection = None
            if inspection is not None and inspection.status != "passed":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Linked inspection {inspection.inspection_number} has not passed "
                        f"(status '{inspection.status}'); the gate cannot be released yet"
                    ),
                )

        released_at = data.released_at or _utc_now_iso()
        snapshot = {
            "gate_number": gate.gate_number,
            "point_type": gate.point_type,
            "inspection_id": gate.inspection_id,
            "attached_kind": gate.attached_kind,
            "attached_id": gate.attached_id,
            "released_party_role": data.party_role,
        }
        await self.gates.update_fields(
            gate_id,
            status="released",
            released_by=user_id,
            released_party_role=data.party_role,
            released_at=released_at,
            release_justification=data.justification,
            release_signature_ip=signature_ip,
            release_signature_sha256=snapshot_sha256(snapshot),
        )
        await self.session.refresh(gate)

        await self._log(gate, action="gate_released", from_status="pending", to_status="released", user_id=user_id)
        event_bus.publish_detached(
            "cc.gate.released",
            {
                "gate_id": str(gate.id),
                "gate_number": gate.gate_number,
                "project_id": str(gate.project_id),
                "point_type": gate.point_type,
                "attached_kind": gate.attached_kind,
                "attached_id": gate.attached_id,
                "released_by": user_id,
                "released_party_role": data.party_role,
            },
            source_module="construction_control",
        )
        logger.info("Hold gate %s released by %s as %s", gate.gate_number, user_id, data.party_role)
        return gate

    async def waive_gate(self, gate_id: uuid.UUID, data: HoldGateWaiveIn, user_id: str | None) -> HoldGate:
        """Waive a gate. Only witness / surveillance / review gates may be waived; a hold
        gate can only be released."""
        gate = await self.get_gate(gate_id)
        if gate.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot waive a gate with status '{gate.status}'; only a pending gate can be waived",
            )
        if gate.point_type not in _WAIVABLE_POINT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A '{gate.point_type}' gate cannot be waived; it must be released by an authorised party",
            )

        await self.gates.update_fields(
            gate_id,
            status="waived",
            waived_by=user_id,
            waived_reason=data.reason,
        )
        await self.session.refresh(gate)
        await self._log(gate, action="gate_waived", from_status="pending", to_status="waived", user_id=user_id)
        logger.info("Hold gate %s waived by %s", gate.gate_number, user_id)
        return gate

    async def void_gate(self, gate_id: uuid.UUID, user_id: str | None) -> HoldGate:
        """Void a pending gate (it no longer applies)."""
        gate = await self.get_gate(gate_id)
        if gate.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot void a gate with status '{gate.status}'; only a pending gate can be voided",
            )
        await self.gates.update_fields(gate_id, status="void")
        await self.session.refresh(gate)
        await self._log(gate, action="gate_voided", from_status="pending", to_status="void", user_id=user_id)
        return gate

    # ── Enforcement seam ─────────────────────────────────────────────────────
    # Only handover enforces a gate today: handover_service reads
    # blocking_gates_for before it issues a package, and GET /gates/can-proceed
    # reports the same list. assert_can_proceed has no caller, so a hold point
    # on a schedule activity or an inspection is advisory until a writer in
    # those modules calls it.

    async def blocking_gates_for(self, project_id: uuid.UUID, attached_kind: str, attached_id: str) -> list[HoldGate]:
        """Pending, blocking gates attached to one entity."""
        return await self.gates.list_blocking(project_id, attached_kind, attached_id)

    async def assert_can_proceed(self, project_id: uuid.UUID, attached_kind: str, attached_id: str) -> None:
        """Raise 409 listing blocking gate numbers when the entity is gated."""
        blocking = await self.blocking_gates_for(project_id, attached_kind, attached_id)
        if blocking:
            numbers = ", ".join(g.gate_number for g in blocking)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Blocked by unreleased gate(s): {numbers}",
            )

    async def count_unreleased_holds(self, project_id: uuid.UUID) -> int:
        """Count pending, blocking gates across the project (Pillar-4 gate input)."""
        return await self.gates.count_unreleased_holds(project_id)

    # ── Internals ──────────────────────────────────────────────────────────--

    async def _log(self, gate: HoldGate, *, action: str, from_status: str, to_status: str, user_id: str | None) -> None:
        """Best-effort activity-log write for a gate transition (never fails the action)."""
        from app.core.audit_log import log_activity

        try:
            await log_activity(
                self.session,
                actor_id=user_id,
                entity_type="cc_hold_gate",
                entity_id=str(gate.id),
                action=action,
                from_status=from_status,
                to_status=to_status,
                module="construction_control",
                parent_entity_type="project",
                parent_entity_id=str(gate.project_id),
                metadata={"gate_number": gate.gate_number, "point_type": gate.point_type},
            )
        except Exception:  # pragma: no cover - audit must never break the business write
            logger.warning("Activity log failed for gate %s action %s", gate.gate_number, action, exc_info=True)

    @staticmethod
    def _merge_metadata_patch(fields: dict[str, Any], instance: object) -> dict[str, Any]:
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            if isinstance(incoming, dict):
                fields["metadata_"] = merge_metadata(getattr(instance, "metadata_", None), incoming)
            elif incoming is not None:
                fields["metadata_"] = incoming
        return fields


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (matches the QMS signing convention)."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
