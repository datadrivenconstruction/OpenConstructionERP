# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement concept service: every write and every computed view.

Ownership of data (SPEC section 6, INTEGRATION section 6):

* package identity and execution link: module 3 ``ContractPackage`` via :mod:`plan_source`;
* bids, bidders and awards: ``bid_management`` / ``rfq_bidding`` (created here once, read back by events);
* company prequalification status, certificates, ratings: ``subcontractors`` (read as evidence);
* award milestones: ``schedule`` activities (proposed here, created only on confirm);
* thresholds and procedures: the pinned catalogue (kind ``procurement_procedures``).

Approval is the governance gate (Decision 10): this module has no approve
action. A submitted concept (``in_review``) whose frame document governance
made binding is approved; :meth:`mirror_binding` records who decided it. The
state ``binding`` is derived on every read from that document and is never
reported for a concept that was not submitted.

Locks: the concept is "plan locked" while in review, approved or binding;
plan fields (jurisdiction, procedures, values, split, advance, frameworks,
holds and cancellations, prequalification profiles) then refuse with 409. A
submitted change request on the binding frame document lifts the lock until
governance decides it (rule 14). The operational parts (candidates, scores,
soundings, schedule confirmation, execution) stay writable, because they are
how the binding concept is carried out.

Who may steer is decided by the router from permissions and passed in as
``can_manage``; the owner and deputy of the governance area that hosts
procurement may steer too. Governance areas, documents and gates are resolved
from catalogue tags (:mod:`hosting`), never by a literal code.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.modules.procurement_concept import commitments
from app.modules.procurement_concept import evaluator as ev
from app.modules.procurement_concept import plan_source as plan
from app.modules.procurement_concept.catalogue import (
    CONTRACT_PACKAGE_KIND_MAP,
    DEFAULT_CATALOGUE_ID,
    PROCUREMENT_KIND,
    ProcurementCatalogue,
    parse_amount,
    register_kind,
)
from app.modules.procurement_concept.errors import ProcurementError, conflict, forbidden, not_found
from app.modules.procurement_concept.fsm import (
    CONCEPT_FSM,
    CONCEPT_HAND_TARGETS,
    FRAMEWORK_FSM,
    can_set_package_state_by_hand,
    can_transition,
    read_back_target,
)
from app.modules.procurement_concept.hosting import ProcurementHosting, project_hosting
from app.modules.procurement_concept.models import (
    AwardPackage,
    BidderCandidate,
    CandidateScore,
    FrameworkAgreement,
    MarketSounding,
    PrequalProfile,
    ProcurementConcept,
    ProjectReference,
)
from app.modules.project_governance.public import (
    project_areas,
    project_change_requests,
    project_conditions,
    project_controls,
    project_documents,
    project_gate_decisions,
    project_gates,
)

logger = logging.getLogger(__name__)

MODULE = "procurement_concept"
SUPPLY_KINDS = ("supply", "supply_and_install")
_PLAN_LOCKED = ("approved", "binding", "in_review")
_SUBMITTED = ("in_review", "approved")
_GO = ("go", "go_with_conditions")
_EXECUTION_OPEN = ("in_tender", "awarded")
# Refusals that say the package is past or not yet at the point of getting a vehicle, whoever asks.
_EXECUTION_NOT_APPLICABLE = ("execution_exists", "package_not_ready_for_execution")


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def _day(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _iso(v: date | str | None) -> str | None:
    # Several date columns are ISO strings; a value read back before refresh may be either form.
    if not v:
        return None
    return v if isinstance(v, str) else v.isoformat()


def _dec(v: Decimal | str | None) -> str | None:
    # An attribute assigned as a string keeps that type until the row is refreshed.
    return None if v is None else format(Decimal(v), "f")


def _number(v: Decimal | str | int | None) -> Decimal | None:
    """An amount or a rate as a number, whatever form the caller handed in.

    Parsed where the value enters the service, so nothing later compares or
    stores a string. The request schemas already hand in ``Decimal``; a seeder
    or another module calling the service directly may not.
    """
    return None if v is None else Decimal(str(v))


def _answer(reason: str | None, *, applies: bool = True) -> dict[str, Any]:
    """One ``can`` flag: allowed, or the error code that would refuse it.

    ``applies`` is false when the move makes no sense for the object in its
    present state (resuming a package that is not on hold), whoever asks. A
    screen hides such an action and shows the others, enabled or refused.
    """
    return {"allowed": reason is None, "reason": reason, "applies": applies}


def _flag(not_applicable: str | None, refused: str | None) -> dict[str, Any]:
    """Applicability first: a move that does not apply is reported as such even to a caller who may not make it."""
    if not_applicable is not None:
        return _answer(not_applicable, applies=False)
    return _answer(refused)


class ProcurementConceptService:
    """All operations of the module; the router is a thin mapping onto these."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._hosting_cache: dict[uuid.UUID, ProcurementHosting] = {}

    # ── plumbing ─────────────────────────────────────────────────────────

    async def _audit(self, actor_id: Any, entity_type: str, entity_id: Any, action: str, **kw: Any) -> None:
        await log_activity(
            self.session,
            actor_id=_s(actor_id),
            entity_type=entity_type,
            entity_id=_s(entity_id),
            action=action,
            module=MODULE,
            **kw,
        )

    def _publish(self, name: str, data: dict[str, Any]) -> None:
        # ``name`` is the full event name: a subscriber and the dead-subscription scan match the literal.
        publish_after_commit(self.session, name, data, source_module=MODULE)

    async def catalogue_of(self, concept: ProcurementConcept) -> ProcurementCatalogue:
        from app.modules.project_governance.catalogue_store import resolve_catalogue
        from app.modules.project_governance.errors import GovernanceError

        register_kind()
        try:
            return await resolve_catalogue(
                self.session,
                concept.catalogue_source,
                concept.catalogue_id,
                concept.catalogue_version,
                kind=PROCUREMENT_KIND,
                # A pin the server stored and checked when it was set (``_pin``).
                from_pin=True,
            )
        except GovernanceError as exc:
            raise not_found("unknown_catalogue") from exc

    # ── governance reads ─────────────────────────────────────────────────

    async def hosting(self, project_id: uuid.UUID) -> ProcurementHosting:
        """Where procurement lives in the project's governance model (catalogue tags, read once per request)."""
        if project_id not in self._hosting_cache:
            self._hosting_cache[project_id] = await project_hosting(self.session, project_id)
        return self._hosting_cache[project_id]

    async def _procurement_area(self, project_id: uuid.UUID) -> Any:
        """The live area that hosts procurement (governance's read model), or ``None``."""
        code = (await self.hosting(project_id)).area_code
        if code is None:
            return None
        return next((a for a in await project_areas(self.session, project_id) if a.code == code), None)

    async def can_steer(self, project_id: uuid.UUID, actor_id: uuid.UUID, can_manage: bool) -> bool:
        """The manage permission, or owner / deputy of the governance area that hosts procurement."""
        if can_manage:
            return True
        area = await self._procurement_area(project_id)
        return area is not None and actor_id in (area.owner_user_id, area.deputy_user_id)

    async def _require_steer(self, project_id: uuid.UUID, actor_id: uuid.UUID, can_manage: bool) -> None:
        if not await self.can_steer(project_id, actor_id, can_manage):
            raise forbidden("not_procurement_owner")

    async def _frame_document(self, project_id: uuid.UUID, concept: ProcurementConcept) -> Any:
        """The frame document that carries the concept: the one named on it, else the one the catalogue tags.

        Governance's read model of it (``id``, ``code``, ``status``). ``None`` when the model hosts procurement
        nowhere, when the project has no document row for the host, or when the project pinned no model.
        """
        documents = await project_documents(self.session, project_id)
        if concept.governance_document_id is not None:
            return next((d for d in documents if d.id == concept.governance_document_id), None)
        types = (await self.hosting(project_id)).document_types
        return next((d for d in documents if d.code in types), None)

    async def _open_change_requests(self, project_id: uuid.UUID, document_id: uuid.UUID) -> int:
        return len(await project_change_requests(self.session, project_id, document_id, open_only=True))

    async def effective_state(self, concept: ProcurementConcept) -> str:
        """The stored state, or what governance made of a submitted concept.

        While the frame document is binding: a submitted concept (``in_review``
        or ``approved``) reads ``binding``; a submitted change request on the
        document lifts that, an approved concept then reads ``reopened`` and a
        resubmitted one ``in_review`` until governance decides (rule 14). A
        concept that was never submitted keeps its own state whatever the
        document says, so a draft is never reported binding.
        """
        doc = await self._frame_document(concept.project_id, concept)
        if doc is None or doc.status != "binding" or concept.state not in _SUBMITTED:
            return concept.state
        if await self._open_change_requests(concept.project_id, doc.id):
            return "reopened" if concept.state == "approved" else concept.state
        return "binding"

    async def _project_gates(self, project_id: uuid.UUID) -> list[Any]:
        """The gates of the project's current phase model, in order (governance's read model)."""
        return list(await project_gates(self.session, project_id))

    async def release_gate(self, project_id: uuid.UUID, concept: ProcurementConcept) -> Any:
        """The gate whose go releases procurement: the one named on the concept, else the tagged one.

        ``None`` when the project has no such gate. Callers treat that as
        "release not known" (a finding, an ``unknown`` evidence item), never as
        "nothing to wait for", unless :meth:`released_from_start` says the
        model holds procurement behind no gate at all.
        """
        gates = await self._project_gates(project_id)
        if concept.release_gate_code:
            return next((g for g in gates if g.code == concept.release_gate_code), None)
        tagged = (await self.hosting(project_id)).release_gate_codes
        return next((g for g in gates if g.code in tagged), None)

    async def released_from_start(self, project_id: uuid.UUID, concept: ProcurementConcept) -> bool:
        """Whether procurement is open from project start, so there is no release gate to resolve.

        True when the model's first phase enables procurement and the concept
        names no gate. A gate named on the concept is a decision to wait for
        it, and one that is not a gate of the project stays "not known".
        """
        return not concept.release_gate_code and (await self.hosting(project_id)).released_from_start

    async def gates_in_use(self, project_id: uuid.UUID) -> bool:
        """Whether the project has gates at all. A project that never adopted a phase model has none.

        Asked of the gates and not of the model: a pinned model that cannot be
        read leaves its gates on the project, and there the release is "not
        known", which is a different answer from "no gates here".
        """
        return bool(await self._project_gates(project_id))

    async def advance_applies(self, project_id: uuid.UUID, concept: ProcurementConcept) -> bool:
        """Whether a package of this project can be an advance package at all.

        "Advance" means ahead of the release gate. Where procurement is open
        from project start there is no such gate, so the action does not exist.
        """
        return not await self.released_from_start(project_id, concept)

    async def _release_date(self, project_id: uuid.UUID, gate: Any) -> date | None:
        """Date procurement is released: the go decision of the release gate, else its target date."""
        if gate is None:
            return None
        go = await self._go_decisions(project_id, gate.id)
        if go:
            return go[-1].decided_at.date()
        return gate.target_date

    async def _go_decisions(self, project_id: uuid.UUID, gate_id: uuid.UUID) -> list[Any]:
        """The go decisions of one gate (governance's read model), oldest first."""
        decisions = await project_gate_decisions(self.session, project_id, gate_id)
        return sorted((d for d in decisions if d.outcome in _GO), key=lambda d: d.decided_at)

    async def advance_release_status(self, project_id: uuid.UUID, row: AwardPackage, gate: Any) -> str:
        """``released`` | ``none`` | ``missing`` | ``other_gate`` | ``not_cleared`` | ``unavailable`` (rule 12).

        Two things release an advance package. An act of the release gate
        itself: a condition of that gate that is cleared (open, overdue and
        waived do not count), or its go decision. Or, before that gate was ever
        decided, a commitment of this project the owner released, which the
        commitment matrix answers for through a registered checker;
        ``unavailable`` when none is registered, which is never "released".
        """
        if row.advance_release_id is None:
            return "none"
        if row.advance_release_kind == commitments.KIND:
            check = commitments.commitment_checker()
            if check is None:
                return "unavailable"
            answer = await check(self.session, project_id, row.advance_release_id)
            if not answer.found:
                return "missing"
            return "released" if answer.released else "not_cleared"
        if row.advance_release_kind not in ("gate_decision", "condition"):
            return "none"
        # The listings are scoped to the project, so an act of another project is not found.
        if row.advance_release_kind == "gate_decision":
            acts = await project_gate_decisions(self.session, project_id)
        else:
            acts = await project_conditions(self.session, project_id)
        act = next((a for a in acts if a.id == row.advance_release_id), None)
        if act is None:
            return "missing"
        if gate is None or act.gate_id != gate.id:
            return "other_gate"
        if row.advance_release_kind == "gate_decision":
            return "released" if act.outcome in _GO else "not_cleared"
        return "released" if act.status == "cleared" else "not_cleared"

    # ── concept ──────────────────────────────────────────────────────────

    async def find_concept(self, project_id: uuid.UUID, *, lock: bool = False) -> ProcurementConcept | None:
        q = select(ProcurementConcept).where(ProcurementConcept.project_id == project_id)
        if lock:
            q = q.with_for_update()
        return (await self.session.execute(q)).scalars().first()

    async def get_concept(self, project_id: uuid.UUID, *, lock: bool = False) -> ProcurementConcept:
        row = await self.find_concept(project_id, lock=lock)
        if row is None:
            raise not_found("concept_missing")
        return row

    async def _plan_refusal(self, concept: ProcurementConcept) -> ProcurementError | None:
        """Why the plan cannot be changed now, or ``None``."""
        state = await self.effective_state(concept)
        if state == "binding":
            return conflict("binding_requires_change_request")
        if state in _PLAN_LOCKED:
            return conflict("concept_locked", detail=state)
        return None

    async def _require_plan_editable(self, concept: ProcurementConcept) -> None:
        refusal = await self._plan_refusal(concept)
        if refusal is not None:
            raise refusal

    async def _pin(self, tenant_id: str | None, source: str, catalogue_id: str, version: int | None) -> int:
        """The version this caller may pin; another company's or a retired catalogue is refused."""
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        register_kind()
        try:
            return await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, str(catalogue_id), version, kind=PROCUREMENT_KIND
            )
        except GovernanceError as exc:
            raise ProcurementError(exc.code, exc.status_code, detail=exc.detail) from exc

    async def set_concept(
        self,
        project_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
        tenant_id: str | None,
    ) -> ProcurementConcept:
        await self._require_steer(project_id, actor_id, can_manage)
        concept = await self.find_concept(project_id, lock=True)
        created = concept is None
        if concept is None:
            _form, mod3_public = await plan.delivery_form(self.session, project_id)
            concept = ProcurementConcept(
                project_id=project_id,
                catalogue_source="shipped",
                catalogue_id=DEFAULT_CATALOGUE_ID,
                catalogue_version=1,
                jurisdiction="none",
                client_type="private",
                public_client=bool(mod3_public),
                vat_rate_pct=Decimal("0"),
                release_gate_code="",
                state="draft",
                created_by=actor_id,
            )
        else:
            await self._require_plan_editable(concept)
        if "release_gate_code" in data or "governance_document_id" in data:
            # These decide what the governance gate reads, so they need the manage permission and are
            # frozen once the concept left its first state.
            if not can_manage:
                raise forbidden("manage_required")
            if concept.state != "draft":
                raise conflict("gate_fields_frozen", detail=concept.state)
        pinned = any(k in data for k in ("catalogue_source", "catalogue_id", "catalogue_version"))
        if created or pinned:
            source = data.get("catalogue_source", concept.catalogue_source)
            catalogue_id = data.get("catalogue_id", concept.catalogue_id)
            concept.catalogue_version = await self._pin(tenant_id, source, catalogue_id, data.get("catalogue_version"))
            concept.catalogue_source, concept.catalogue_id = source, catalogue_id
        for key in ("jurisdiction", "client_type", "vat_rate_pct", "public_client"):
            if key in data:
                setattr(concept, key, _number(data[key]) if key == "vat_rate_pct" else data[key])
        if "release_gate_code" in data:
            code = data["release_gate_code"]
            if code and code not in {g.code for g in await self._project_gates(project_id)}:
                raise ProcurementError("release_gate_unknown", 422, detail=code)
            concept.release_gate_code = code
        if "governance_document_id" in data:
            if data["governance_document_id"] is not None:
                await self._require_document_in_project(project_id, data["governance_document_id"])
            concept.governance_document_id = data["governance_document_id"]
        if "default_profile_id" in data:
            if data["default_profile_id"] is not None:
                await self._profile(project_id, data["default_profile_id"])
            concept.default_profile_id = data["default_profile_id"]
        cat = await self.catalogue_of(concept)
        juris = cat.jurisdiction(concept.jurisdiction)
        if juris is None:
            raise ProcurementError("jurisdiction_not_in_catalogue", 422, detail=concept.jurisdiction)
        if not concept.public_client:
            # A private client keeps the jurisdiction for reference; no threshold applies (Decision 9).
            concept.client_type = juris.private_client_type
        elif concept.client_type == juris.private_client_type:
            # A public client on the private client type would switch every threshold off without a word.
            raise ProcurementError("public_client_needs_client_type", 422, detail=concept.jurisdiction)
        elif concept.client_type not in juris.client_types:
            raise ProcurementError("client_type_not_in_jurisdiction", 422, detail=concept.client_type)
        if created:
            try:
                async with self.session.begin_nested():
                    self.session.add(concept)
                    await self.session.flush()
            except IntegrityError as exc:
                # Two first writes of the same project raced; the other one created the concept.
                raise conflict("concurrent_update") from exc
        else:
            await self.session.flush()
        await self._audit(actor_id, "procurement_concept", concept.id, "created" if created else "updated")
        self._publish(
            "procurement_concept.concept.updated", {"project_id": str(project_id), "concept_id": str(concept.id)}
        )
        return concept

    async def _require_document_in_project(self, project_id: uuid.UUID, document_id: uuid.UUID) -> None:
        if all(d.id != document_id for d in await project_documents(self.session, project_id)):
            raise not_found("document_not_found")

    async def transition(
        self, project_id: uuid.UUID, target: str, *, actor_id: uuid.UUID, can_manage: bool
    ) -> ProcurementConcept:
        """submit (-> in_review) or return (-> draft).

        Approval is the governance gate where the project has gates, and
        :meth:`approve_by_hand` where it has none; it is never a call here.
        """
        await self._require_steer(project_id, actor_id, can_manage)
        concept = await self.get_concept(project_id, lock=True)
        current = await self.effective_state(concept)
        if current == "binding":
            raise conflict("binding_requires_change_request")
        if target not in CONCEPT_HAND_TARGETS or not can_transition(CONCEPT_FSM, current, target):
            raise conflict("invalid_transition", detail=f"{current}->{target}")
        if target == "in_review":
            doc = await self._frame_document(project_id, concept)
            if (
                doc is not None
                and doc.status == "binding"
                and not await self._open_change_requests(concept.project_id, doc.id)
            ):
                # The frame document is already binding: a new concept version needs a change request on it.
                raise conflict("binding_requires_change_request")
            plan_findings = await self._plan_findings(project_id)
            if plan_findings:
                raise ProcurementError("package_without_procedure_plan", 422, violations=plan_findings)
            concept.submitted_by = actor_id
        concept.state = target
        await self.session.flush()
        await self._audit(actor_id, "procurement_concept", concept.id, target, from_status=current, to_status=target)
        self._publish(
            "procurement_concept.concept.state_changed", {"project_id": str(project_id), "from": current, "to": target}
        )
        return concept

    async def hand_approval_refusal(
        self, project_id: uuid.UUID, concept: ProcurementConcept, actor_id: uuid.UUID, can_manage: bool
    ) -> tuple[ProcurementError | None, bool]:
        """Why this caller cannot approve the concept by hand now, and whether the action exists here.

        It exists only on a project without gates: with gates the gate decision
        approves. Four-eyes is the project control governance states, which is
        on for a project without a phase model: whoever submitted does not approve.
        """
        if await self.gates_in_use(project_id):
            return conflict("approved_by_gate_decision"), False
        if not can_manage:
            return forbidden("approval_needs_manager"), True
        if concept.state != "in_review":
            return conflict("concept_not_submitted", detail=concept.state), True
        if (await project_controls(self.session, project_id)).four_eyes and concept.submitted_by == actor_id:
            return forbidden("approver_is_submitter"), True
        blocking = [f for f in await self.findings(project_id) if f["blocks_approval"]]
        if blocking:
            return ProcurementError("concept_has_blocking_findings", 422, violations=blocking), True
        return None, True

    async def approve_by_hand(
        self, project_id: uuid.UUID, *, actor_id: uuid.UUID, can_manage: bool
    ) -> ProcurementConcept:
        """Approve the submitted concept on a project that has no gates to approve it."""
        concept = await self.get_concept(project_id, lock=True)
        refusal, _ = await self.hand_approval_refusal(project_id, concept, actor_id, can_manage)
        if refusal is not None:
            raise refusal
        concept.state = "approved"
        concept.approved_by = actor_id
        concept.approved_at = datetime.now(UTC)
        await self.session.flush()
        await self._audit(
            actor_id,
            "procurement_concept",
            concept.id,
            "approved",
            from_status="in_review",
            to_status="approved",
            metadata={"source": "hand", "four_eyes_violated": actor_id == concept.submitted_by},
        )
        self._publish(
            "procurement_concept.concept.state_changed",
            {"project_id": str(project_id), "from": "in_review", "to": "approved"},
        )
        return concept

    async def hand_reopen_refusal(
        self, project_id: uuid.UUID, concept: ProcurementConcept, can_manage: bool
    ) -> tuple[ProcurementError | None, bool]:
        """Why this caller cannot reopen the approved concept by hand now, and whether the action exists here.

        With gates a change request on the frame document reopens the concept.
        Without gates nothing else could, and an approved plan would be frozen for good.
        """
        if await self.gates_in_use(project_id):
            return conflict("reopened_by_change_request"), False
        if concept.state != "approved":
            return conflict("invalid_transition", detail=f"{concept.state}->reopened"), False
        if not can_manage:
            return forbidden("approval_needs_manager"), True
        return None, True

    async def reopen_by_hand(
        self, project_id: uuid.UUID, reason: str, *, actor_id: uuid.UUID, can_manage: bool
    ) -> ProcurementConcept:
        """Open the approved concept for changes on a project without gates; it is submitted and approved again.

        The reason is required and goes into the audit trail with the reopening.
        """
        concept = await self.get_concept(project_id, lock=True)
        refusal, _ = await self.hand_reopen_refusal(project_id, concept, can_manage)
        if refusal is not None:
            raise refusal
        reason = (reason or "").strip()
        if not reason:
            raise ProcurementError("reopen_reason_required", 422)
        concept.state = "reopened"
        await self.session.flush()
        await self._audit(
            actor_id,
            "procurement_concept",
            concept.id,
            "reopened",
            from_status="approved",
            to_status="reopened",
            reason=reason,
            metadata={"source": "hand"},
        )
        self._publish(
            "procurement_concept.concept.state_changed",
            {"project_id": str(project_id), "from": "approved", "to": "reopened"},
        )
        return concept

    async def mirror_binding(self, project_id: uuid.UUID, document_id: uuid.UUID) -> bool:
        """Governance made the frame document binding: the submitted concept is approved (idempotent).

        The approver is whoever decided in governance: the go decision of the
        gate that bound the document, else the approved change request.
        """
        concept = await self.find_concept(project_id, lock=True)
        if concept is None or concept.state != "in_review":
            return False
        doc = await self._frame_document(project_id, concept)
        if doc is None or doc.id != document_id or doc.status != "binding":
            return False
        approver, at = None, None
        if doc.approved_gate_id is not None:
            go = await self._go_decisions(project_id, doc.approved_gate_id)
            if go:
                approver, at = go[-1].decided_by, go[-1].decided_at
        approved = [
            c
            for c in await project_change_requests(self.session, project_id, doc.id)
            if c.status == "approved" and c.decided_at is not None
        ]
        change = max(approved, key=lambda c: c.decided_at, default=None)
        if change is not None and (at is None or change.decided_at > at):
            approver, at = change.decided_by, change.decided_at
        concept.state = "approved"
        concept.approved_by = approver
        concept.approved_at = at or datetime.now(UTC)
        await self.session.flush()
        await self._audit(
            approver,
            "procurement_concept",
            concept.id,
            "approved",
            from_status="in_review",
            to_status="approved",
            metadata={"document_id": str(document_id), "four_eyes_violated": approver == concept.submitted_by},
        )
        self._publish(
            "procurement_concept.concept.state_changed",
            {"project_id": str(project_id), "from": "in_review", "to": "approved"},
        )
        return True

    # ── facts ────────────────────────────────────────────────────────────

    async def _award_rows(self, project_id: uuid.UUID) -> list[AwardPackage]:
        return list(
            (await self.session.execute(select(AwardPackage).where(AwardPackage.project_id == project_id)))
            .scalars()
            .all()
        )

    async def _concept_facts(self, concept: ProcurementConcept) -> ev.ConceptFacts:
        form, _ = await plan.delivery_form(self.session, concept.project_id)
        return ev.ConceptFacts(
            jurisdiction=concept.jurisdiction,
            client_type=concept.client_type,
            public_client=concept.public_client,
            vat_rate_pct=Decimal(concept.vat_rate_pct or 0),
            delivery_form=form,
        )

    async def _package_facts(
        self, project_id: uuid.UUID
    ) -> tuple[list[plan.PlanPackage], dict[str, AwardPackage], list[ev.PackageFacts]]:
        cps = await plan.list_packages(self.session, project_id)
        rows = {str(r.id): r for r in await self._award_rows(project_id)}
        concept = await self.find_concept(project_id)
        gate = await self.release_gate(project_id, concept) if concept is not None else None
        applies = concept is None or await self.advance_applies(project_id, concept)
        facts = []
        for cp in cps:
            r = rows.get(str(cp.id))
            if r is None:
                continue
            facts.append(await self._facts_of(project_id, cp, r, gate, advance_applies=applies))
        return cps, rows, facts

    async def _bind_need_date(self, project_id: uuid.UUID, activity_id: uuid.UUID) -> str:
        """The start date of a schedule activity of this project; any other activity is refused as unknown."""
        from app.modules.schedule.models import Activity, Schedule

        row = (
            await self.session.execute(
                select(Activity.start_date)
                .join(Schedule, Schedule.id == Activity.schedule_id)
                .where(Activity.id == activity_id, Schedule.project_id == project_id)
            )
        ).first()
        if row is None or not row[0]:
            raise ProcurementError("need_activity_unknown", 422)
        return str(row[0])[:10]

    async def _facts_of(
        self, project_id: uuid.UUID, cp: plan.PlanPackage, r: AwardPackage, gate: Any, *, advance_applies: bool
    ) -> ev.PackageFacts:
        released = (
            advance_applies and r.is_advance and await self.advance_release_status(project_id, r, gate) == "released"
        )
        need_day = _day(r.need_date) or _day(cp.need_date)
        if r.need_activity_id is not None:
            # The schedule owns the date once the package is bound: moving the milestone moves the award schedule.
            from app.modules.schedule.models import Activity

            bound = await self.session.get(Activity, r.need_activity_id)
            need_day = _day(bound.start_date) if bound is not None and bound.start_date else need_day
        return ev.PackageFacts(
            id=str(r.id),
            code=cp.code,
            cp_kind=cp.kind,
            parent_id=str(cp.parent_id) if cp.parent_id else None,
            estimated_value=r.estimated_value,
            currency=r.currency,
            lot_group=r.lot_group,
            small_lot_exemption=r.small_lot_exemption,
            procedure_code=r.procedure_code,
            tender_basis=r.tender_basis,
            is_advance=r.is_advance,
            advance_reason=r.advance_reason,
            advance_released=released,
            advance_applies=advance_applies,
            framework_agreement_id=str(r.framework_agreement_id) if r.framework_agreement_id else None,
            need_date=need_day,
            lead_time_days=r.lead_time_days,
            procedure_days=r.procedure_days,
            planned_start=_day(r.planned_start),
            state=r.state,
        )

    @staticmethod
    def _check_day(p: ev.PackageFacts, cat: ProcurementCatalogue, today: date) -> date:
        """The planned procedure start the threshold must be valid on (rule 4)."""
        if p.planned_start:
            return p.planned_start
        bp = ev.backward_pass(cat, p)
        return bp.start_date if bp else today

    async def _plan_findings(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        cps = await plan.list_packages(self.session, project_id)
        ids = {str(r.id) for r in await self._award_rows(project_id)}
        return ev.plan_findings([{"id": str(c.id), "code": c.code, "kind": c.kind} for c in cps], ids)

    async def findings(self, project_id: uuid.UUID, *, today: date | None = None) -> list[dict[str, Any]]:
        """Every finding of every rule for the project (the one source for validation, approval, readiness)."""
        today = today or datetime.now(UTC).date()
        concept = await self.get_concept(project_id)
        cat = await self.catalogue_of(concept)
        facts = await self._concept_facts(concept)
        cps, rows, pkgs = await self._package_facts(project_id)
        out = ev.plan_findings([{"id": str(c.id), "code": c.code, "kind": c.kind} for c in cps], set(rows))
        gate = await self.release_gate(project_id, concept)
        from_start = gate is None and await self.released_from_start(project_id, concept)
        if from_start:
            doc = await self._frame_document(project_id, concept)
            if doc is not None and not doc.required_at_gates:
                # No release gate and no gate that asks for the document: no decision would ever look at the
                # concept. That is a property of the phase model, so it is said here and not as gate evidence.
                out.append(ev.finding("concept_required_at_no_gate", ev.WARNING, "project"))
        if gate is None and not from_start and await self.gates_in_use(project_id):
            # Without a release gate rule 11 cannot test "before the releasing gate"; say so, never skip it silently.
            # A model that opens procurement in its first phase has no such gate and rule 11 nothing to test.
            # Neither has a project without gates: it waits for none, and that is how it is run, not a gap.
            out.append(ev.finding("release_gate_unresolved", ev.WARNING, "project"))
        release = await self._release_date(project_id, gate)
        for p in pkgs:
            if p.state == "cancelled" or p.package_kind is None:
                continue
            out += ev.package_findings(cat, p)
            out += ev.procedure_findings(cat, facts, p, pkgs, self._check_day(p, cat, today))
            bp = ev.backward_pass(cat, p)
            if p.state not in _EXECUTION_OPEN:
                # A package already in tender or awarded is past its planning dates and its call-off: time
                # passing must not turn them into errors that block a later re-approval.
                out += ev.schedule_findings(cat, p, today=today, release_date=release)
                fw = await self._framework_facts(p.framework_agreement_id)
                out += ev.framework_findings(
                    cat,
                    p,
                    fw,
                    award_date=bp.award_date if bp else None,
                    remaining=fw["remaining_excluding"](p.id) if fw else None,
                )
            out += await self._prequal_findings(project_id, cat, p, rows[p.id], bp.award_date if bp else None)
        out += ev.consistency_findings(cat, facts.delivery_form, pkgs)
        soundings = (
            (await self.session.execute(select(MarketSounding).where(MarketSounding.project_id == project_id)))
            .scalars()
            .all()
        )
        out += ev.capacity_findings(
            [
                {"id": s.id, "capacity_signal": s.capacity_signal, "mitigation": s.mitigation, "resplit": s.resplit}
                for s in soundings
            ]
        )
        for f in out:
            f.setdefault("message_key", f"procurement_concept.findings.{f['code']}")
        return out

    # ── packages ─────────────────────────────────────────────────────────

    async def _award(self, project_id: uuid.UUID, package_id: uuid.UUID, *, lock: bool = False) -> AwardPackage:
        q = select(AwardPackage).where(AwardPackage.id == package_id, AwardPackage.project_id == project_id)
        if lock:
            q = q.with_for_update()
        row = (await self.session.execute(q)).scalars().first()
        if row is None:
            raise not_found("package_not_found")
        return row

    async def package_views(
        self, project_id: uuid.UUID, *, today: date | None = None, access: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """The package board (screen 1): every ContractPackage joined with its award package.

        With ``access`` (from :meth:`access`) every row carries ``can``: what
        this caller may do with the package now, each with the refusing code.
        """
        today = today or datetime.now(UTC).date()
        concept = await self.get_concept(project_id)
        all_findings = await self.findings(project_id, today=today) if access is not None else []
        cat = await self.catalogue_of(concept)
        facts = await self._concept_facts(concept)
        cps, rows, pkgs = await self._package_facts(project_id)
        by_id = {p.id: p for p in pkgs}
        aggregated = ev.aggregated_values(cat, pkgs)
        out = []
        for cp in cps:
            row = rows.get(str(cp.id))
            p = by_id.get(str(cp.id))
            view: dict[str, Any] = {
                "contract_package": cp.as_dict(),
                "package_kind": CONTRACT_PACKAGE_KIND_MAP.get(cp.kind),
                "award": None,
                "threshold": None,
                "schedule": None,
            }
            if row is not None and p is not None:
                tv = ev.threshold_view(cat, facts, p, pkgs, self._check_day(p, cat, today))
                bp = ev.backward_pass(cat, p)
                view["award"] = self._award_out(row)
                view["award"]["aggregated_value"] = _dec(aggregated.get(p.id))
                view["threshold"] = {
                    "status": tv.status,
                    "allowed": tv.allowed,
                    "thresholds": tv.thresholds,
                    "small_lot_exempt": tv.small_lot_exempt,
                    "aggregated_value": _dec(tv.aggregated_value),
                }
                view["schedule"] = (
                    {
                        "award_date": _iso(bp.award_date),
                        "start_date": _iso(bp.start_date),
                        "procedure_days": bp.procedure_days,
                    }
                    if bp
                    else None
                )
            if access is not None:
                view["can"] = await self._package_can(project_id, concept, cp, row, access, all_findings)
            out.append(view)
        return out

    async def _package_can(
        self,
        project_id: uuid.UUID,
        concept: ProcurementConcept,
        cp: plan.PlanPackage,
        row: AwardPackage | None,
        access: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """The answers of the checks ``put_package``, ``set_package_state`` and ``create_execution`` enforce."""
        plan_reason = access["edit_plan"]["reason"]
        steer_reason = access["steer"]["reason"]
        edit_na = None
        if CONTRACT_PACKAGE_KIND_MAP.get(cp.kind) is None:
            edit_na = "package_kind_not_procured"
        elif row is not None and row.state in ("in_tender", "awarded", "cancelled"):
            edit_na = "package_closed"

        def move(target: str | None, missing: str) -> dict[str, Any]:
            if row is None:
                return _flag("package_not_found", None)
            if target is None:
                return _flag(missing, None)
            if not can_set_package_state_by_hand(row.state, target):
                return _flag("invalid_transition", None)
            return _flag(None, plan_reason)

        resume_to = row.state_before if row is not None and row.state == "on_hold" else None
        if row is None:
            shortlist = _flag("package_not_found", None)
            execution = _flag("package_not_found", None)
        else:
            shortlist = _flag(None if row.state == "procedure_set" else "invalid_transition", steer_reason)
            refusal = await self._execution_refusal(project_id, concept, row, cp, findings=findings)
            code = refusal.code if refusal is not None else None
            execution = _flag(code if code in _EXECUTION_NOT_APPLICABLE else None, steer_reason or code)
        advance_na = None if await self.advance_applies(project_id, concept) else "advance_not_applicable"
        return {
            "edit": _flag(edit_na, plan_reason),
            # Marking a package as advance is an edit that exists only where a gate releases procurement.
            "set_advance": _flag(advance_na or edit_na, plan_reason),
            "hold": move("on_hold", ""),
            "resume": move(resume_to, "package_not_on_hold"),
            "cancel": move("cancelled", ""),
            "confirm_shortlist": shortlist,
            "create_execution": execution,
        }

    @staticmethod
    def _award_out(r: AwardPackage) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "split_basis": r.split_basis,
            "is_advance": r.is_advance,
            "advance_reason": r.advance_reason,
            "advance_release_kind": r.advance_release_kind,
            "advance_release_id": _s(r.advance_release_id),
            "estimated_value": _dec(r.estimated_value),
            "currency": r.currency,
            "cost_ref_kind": r.cost_ref_kind,
            "cost_ref_id": _s(r.cost_ref_id),
            "lot_group": r.lot_group,
            "small_lot_exemption": r.small_lot_exemption,
            "procedure_code": r.procedure_code,
            "tender_basis": r.tender_basis,
            "framework_agreement_id": _s(r.framework_agreement_id),
            "evaluation_method": r.evaluation_method,
            "evaluation_weights": r.evaluation_weights or {},
            "need_activity_id": _s(r.need_activity_id),
            "need_date": r.need_date,
            "lead_time_days": r.lead_time_days,
            "procedure_days": r.procedure_days,
            "planned_start": r.planned_start,
            "prequal_profile_id": _s(r.prequal_profile_id),
            "start_activity_id": _s(r.start_activity_id),
            "award_activity_id": _s(r.award_activity_id),
            "state": r.state,
            "notes": r.notes,
        }

    async def put_package(
        self,
        project_id: uuid.UUID,
        package_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
        tenant_id: str | None,
    ) -> AwardPackage:
        """Create (first call) or change the procurement attributes of one ContractPackage."""
        await self._require_steer(project_id, actor_id, can_manage)
        concept = await self.get_concept(project_id)
        await self._require_plan_editable(concept)
        cp = await plan.get_package(self.session, project_id, package_id)
        if cp is None:
            raise not_found("package_not_found")
        if CONTRACT_PACKAGE_KIND_MAP.get(cp.kind) is None:
            raise ProcurementError("package_kind_not_procured", 422, detail=cp.kind)
        q = select(AwardPackage).where(AwardPackage.id == package_id).with_for_update()
        row = (await self.session.execute(q)).scalars().first()
        created = row is None
        if row is None:
            row = AwardPackage(id=package_id, project_id=project_id, created_by=actor_id, state="planned")
        elif row.project_id != project_id:
            raise not_found("package_not_found")
        if row.state in ("in_tender", "awarded", "cancelled"):
            raise conflict("package_closed", detail=row.state)
        cat = await self.catalogue_of(concept)
        procedure_before = row.procedure_code
        advance_before = bool(row.is_advance)
        for key, value in data.items():
            if key in ("need_date", "planned_start"):
                setattr(row, key, _iso(value))
            elif key == "estimated_value":
                row.estimated_value = _number(value)
            else:
                setattr(row, key, value)
        if row.estimated_value is not None and not row.currency:
            # An amount without a currency cannot be aggregated or compared; none is ever assumed.
            raise ProcurementError("currency_required", 422)
        if "procedure_code" in data and row.procedure_code and cat.procedure(row.procedure_code) is None:
            raise ProcurementError("procedure_unknown", 422, detail=row.procedure_code)
        advance_applies = await self.advance_applies(project_id, concept)
        if not advance_applies and (
            (row.is_advance and not advance_before) or data.get("advance_release_id") is not None
        ):
            # No gate holds procurement back here, so nothing can be run ahead of one. A row that carries the
            # flag from an earlier phase model may still be edited, and cleared.
            raise conflict("advance_not_applicable")
        if advance_applies and row.is_advance and not (row.advance_reason or "").strip():
            # Rule 12: an advance package without a reason is rejected outright.
            raise ProcurementError("advance_without_reason", 422)
        if advance_applies and row.advance_release_id is not None:
            if not row.advance_release_kind:
                raise ProcurementError("advance_release_kind_required", 422)
            # A condition that is still open, or a commitment not released yet, may be named: the package then
            # stays unreleased (a blocking finding) until it is. An act of another gate or project is refused.
            gate = await self.release_gate(project_id, concept)
            status = await self.advance_release_status(project_id, row, gate)
            if status == "unavailable":
                raise conflict(commitments.UNAVAILABLE)
            if status == "missing":
                raise not_found("advance_release_not_found")
            if status == "other_gate":
                raise ProcurementError("advance_release_other_gate", 422)
        if row.prequal_profile_id is not None:
            await self._profile(project_id, row.prequal_profile_id)
        if "need_activity_id" in data and row.need_activity_id is not None:
            row.need_date = await self._bind_need_date(project_id, row.need_activity_id)
        if "cost_ref_id" in data and row.cost_ref_id is not None:
            await self._require_boq_section(project_id, row.cost_ref_id)
        if row.framework_agreement_id is not None and any(
            k in data for k in ("framework_agreement_id", "estimated_value", "currency")
        ):
            await self._link_framework(project_id, row, tenant_id)
        if row.state == "shortlisted" and row.procedure_code != procedure_before:
            # The short list was confirmed for the old procedure (its minimum bidders); it has to be confirmed again.
            row.state = "procedure_set"
        if row.state in ("planned", "procedure_set"):
            row.state = "procedure_set" if row.procedure_code else "planned"
        if created:
            try:
                async with self.session.begin_nested():
                    self.session.add(row)
                    await self.session.flush()
            except IntegrityError as exc:
                raise conflict("concurrent_update") from exc
        else:
            await self.session.flush()
        await self._audit(actor_id, "procurement_award_package", row.id, "created" if created else "updated")
        return row

    async def set_package_state(
        self, project_id: uuid.UUID, package_id: uuid.UUID, action: str, *, actor_id: uuid.UUID, can_manage: bool
    ) -> AwardPackage:
        await self._require_steer(project_id, actor_id, can_manage)
        # Holding or cancelling a lot changes the plan (it leaves the aggregation), so the plan lock applies.
        await self._require_plan_editable(await self.get_concept(project_id))
        row = await self._award(project_id, package_id, lock=True)
        if action == "hold":
            target = "on_hold"
        elif action == "cancel":
            target = "cancelled"
        else:
            if row.state != "on_hold" or not row.state_before:
                raise conflict("package_not_on_hold")
            target = row.state_before
        if not can_set_package_state_by_hand(row.state, target):
            raise conflict("invalid_transition", detail=f"{row.state}->{target}")
        if target == "on_hold":
            row.state_before = row.state
        elif row.state == "on_hold":
            row.state_before = None
        before = row.state
        row.state = target
        await self.session.flush()
        await self._audit(actor_id, "procurement_award_package", row.id, action, from_status=before, to_status=target)
        return row

    async def threshold_check(
        self, project_id: uuid.UUID, package_id: uuid.UUID, *, today: date | None = None
    ) -> dict[str, Any]:
        """Screen 2: threshold explanation with sources and the procedure picker with reasons."""
        today = today or datetime.now(UTC).date()
        concept = await self.get_concept(project_id)
        cat = await self.catalogue_of(concept)
        facts = await self._concept_facts(concept)
        _cps, _rows, pkgs = await self._package_facts(project_id)
        p = next((x for x in pkgs if x.id == str(package_id)), None)
        if p is None:
            raise not_found("package_not_found")
        day = self._check_day(p, cat, today)
        tv = ev.threshold_view(cat, facts, p, pkgs, day)
        return {
            "package_id": str(package_id),
            "checked_on": day.isoformat(),
            "status": tv.status,
            "single_value": _dec(tv.single_value),
            "aggregated_value": _dec(tv.aggregated_value),
            "small_lot_exempt": tv.small_lot_exempt,
            "thresholds": tv.thresholds,
            "procedures": ev.allowed_procedures(cat, facts, p, pkgs, day),
            "findings": ev.procedure_findings(cat, facts, p, pkgs, day),
        }

    async def consistency_report(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        concept = await self.get_concept(project_id)
        cat = await self.catalogue_of(concept)
        facts = await self._concept_facts(concept)
        _cps, _rows, pkgs = await self._package_facts(project_id)
        return ev.consistency_findings(cat, facts.delivery_form, pkgs)

    # ── prequalification ─────────────────────────────────────────────────

    async def _profile(self, project_id: uuid.UUID, profile_id: uuid.UUID) -> PrequalProfile:
        row = await self.session.get(PrequalProfile, profile_id)
        if row is None or row.project_id != project_id:
            raise not_found("profile_not_found")
        return row

    async def list_profiles(self, project_id: uuid.UUID) -> list[PrequalProfile]:
        return list(
            (await self.session.execute(select(PrequalProfile).where(PrequalProfile.project_id == project_id)))
            .scalars()
            .all()
        )

    async def save_profile(
        self,
        project_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
        profile_id: uuid.UUID | None = None,
    ) -> PrequalProfile:
        await self._require_steer(project_id, actor_id, can_manage)
        concept = await self.get_concept(project_id)
        await self._require_plan_editable(concept)
        cat = await self.catalogue_of(concept)
        criteria = []
        for c in data.get("criteria") or []:
            known = cat.criterion(c["code"])
            if known is None:
                raise ProcurementError("criterion_unknown", 422, detail=c["code"])
            weight = Decimal(c.get("weight") or 0) if known.kind == "scored" else Decimal("0")
            criteria.append({"code": known.code, "kind": known.kind, "weight": format(weight, "f")})
        bad = ev.weights_findings(criteria, "profile")
        if bad:
            raise ProcurementError("prequal_weights_not_100", 422, violations=bad)
        if data.get("package_id") is not None:
            await self._award(project_id, data["package_id"])
        row = await self._profile(project_id, profile_id) if profile_id else PrequalProfile(project_id=project_id)
        row.package_id = data.get("package_id")
        row.name = data.get("name") or ""
        row.criteria = criteria
        row.pass_mark = Decimal(data.get("pass_mark") or 0)
        row.validity_months = int(data.get("validity_months") or 12)
        if profile_id is None:
            self.session.add(row)
        await self.session.flush()
        return row

    async def delete_profile(
        self, project_id: uuid.UUID, profile_id: uuid.UUID, *, actor_id: uuid.UUID, can_manage: bool
    ) -> None:
        await self._require_steer(project_id, actor_id, can_manage)
        concept = await self.get_concept(project_id)
        await self._require_plan_editable(concept)
        row = await self._profile(project_id, profile_id)
        if profile_id in await self._profiles_in_use(project_id, concept):
            # Deleting it would leave packages with no criteria at all, and a short list would then pass unchecked.
            raise conflict("profile_in_use")
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "procurement_prequal_profile", profile_id, "deleted")

    async def _profiles_in_use(self, project_id: uuid.UUID, concept: ProcurementConcept) -> set[uuid.UUID]:
        """Profiles the concept or a package points at."""
        used = set(
            (
                await self.session.execute(
                    select(AwardPackage.prequal_profile_id).where(
                        AwardPackage.project_id == project_id, AwardPackage.prequal_profile_id.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        if concept.default_profile_id is not None:
            used.add(concept.default_profile_id)
        return used

    async def profile_for(self, project_id: uuid.UUID, award: AwardPackage) -> PrequalProfile | None:
        if award.prequal_profile_id:
            return await self.session.get(PrequalProfile, award.prequal_profile_id)
        own = (
            (
                await self.session.execute(
                    select(PrequalProfile).where(
                        PrequalProfile.project_id == project_id, PrequalProfile.package_id == award.id
                    )
                )
            )
            .scalars()
            .first()
        )
        if own is not None:
            return own
        concept = await self.find_concept(project_id)
        if concept and concept.default_profile_id:
            return await self.session.get(PrequalProfile, concept.default_profile_id)
        return None

    async def _candidate(self, project_id: uuid.UUID, candidate_id: uuid.UUID) -> BidderCandidate:
        row = await self.session.get(BidderCandidate, candidate_id)
        if row is None or row.project_id != project_id:
            raise not_found("candidate_not_found")
        return row

    async def _require_company(self, data: dict[str, Any]) -> None:
        from app.modules.subcontractors.models import Subcontractor
        from app.modules.supplier_catalogs.models import Vendor

        if data.get("subcontractor_id") and await self.session.get(Subcontractor, data["subcontractor_id"]) is None:
            raise not_found("company_not_found")
        if data.get("vendor_id") and await self.session.get(Vendor, data["vendor_id"]) is None:
            raise not_found("company_not_found")

    @staticmethod
    def _registered(c: BidderCandidate) -> bool:
        return c.subcontractor_id is not None or c.vendor_id is not None

    def _check_list_change(self, row: BidderCandidate) -> None:
        if row.list_kind == "excluded" and not (row.decision_rationale or "").strip():
            raise ProcurementError("excluded_candidate_without_rationale", 422)
        if row.list_kind == "short" and not self._registered(row):
            raise ProcurementError("candidate_not_registered", 422)
        if not self._registered(row) and not (row.free_name or "").strip():
            raise ProcurementError("candidate_needs_company", 422)

    async def add_candidate(
        self,
        project_id: uuid.UUID,
        package_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> BidderCandidate:
        await self._award(project_id, package_id)
        if (data.get("list") or "long") != "long":
            # Short-listing and excluding decide who may bid: that is steering, not data entry.
            await self._require_steer(project_id, actor_id, can_manage)
        await self._require_company(data)
        row = BidderCandidate(
            project_id=project_id,
            package_id=package_id,
            subcontractor_id=data.get("subcontractor_id"),
            vendor_id=data.get("vendor_id"),
            free_name=data.get("free_name") or "",
            source=data.get("source") or "own_list",
            list_kind=data.get("list") or "long",
            decision_rationale=data.get("decision_rationale") or "",
            conflict_of_interest_declared=bool(data.get("conflict_of_interest_declared")),
            conflict_note=data.get("conflict_note") or "",
        )
        self._check_list_change(row)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict("candidate_exists") from exc
        await self._audit(actor_id, "procurement_candidate", row.id, "created")
        return row

    async def patch_candidate(
        self,
        project_id: uuid.UUID,
        candidate_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> BidderCandidate:
        row = await self._candidate(project_id, candidate_id)
        if "list" in data and data["list"] != row.list_kind:
            await self._require_steer(project_id, actor_id, can_manage)
        await self._require_company(data)
        for key, value in data.items():
            setattr(row, "list_kind" if key == "list" else key, value)
        self._check_list_change(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            # The company is already a candidate of this package under another row.
            raise conflict("candidate_exists") from exc
        await self._audit(actor_id, "procurement_candidate", row.id, "updated")
        return row

    async def delete_candidate(
        self, project_id: uuid.UUID, candidate_id: uuid.UUID, *, actor_id: uuid.UUID, can_manage: bool
    ) -> None:
        await self._require_steer(project_id, actor_id, can_manage)
        row = await self._candidate(project_id, candidate_id)
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "procurement_candidate", candidate_id, "deleted")

    async def put_scores(
        self, project_id: uuid.UUID, candidate_id: uuid.UUID, scores: list[dict[str, Any]], *, actor_id: uuid.UUID
    ) -> list[CandidateScore]:
        cand = await self._candidate(project_id, candidate_id)
        award = await self._award(project_id, cand.package_id)
        profile = await self.profile_for(project_id, award)
        allowed = {c["code"]: c["kind"] for c in (profile.criteria if profile else [])}
        sent = [s["criterion_code"] for s in scores]
        twice = sorted({c for c in sent if sent.count(c) > 1})
        if twice:
            raise ProcurementError("criterion_scored_twice", 422, detail=", ".join(twice))
        existing = {
            s.criterion_code: s
            for s in (await self.session.execute(select(CandidateScore).where(CandidateScore.candidate_id == cand.id)))
            .scalars()
            .all()
        }
        out = []
        for s in scores:
            kind = allowed.get(s["criterion_code"])
            if kind is None:
                raise ProcurementError("criterion_not_in_profile", 422, detail=s["criterion_code"])
            if kind == "pass_fail" and s.get("score") is not None:
                raise ProcurementError("pass_fail_takes_no_score", 422, detail=s["criterion_code"])
            row = existing.get(s["criterion_code"])
            if row is None:
                row = CandidateScore(candidate_id=cand.id, criterion_code=s["criterion_code"])
                self.session.add(row)
            row.passed = s.get("passed")
            row.score = s.get("score")
            row.evidence = [dict(e) for e in s.get("evidence") or []]
            row.note = s.get("note") or ""
            row.scored_by = actor_id
            out.append(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            # A concurrent scoring of the same criterion won.
            raise conflict("concurrent_update") from exc
        return out

    async def add_reference(
        self, project_id: uuid.UUID, candidate_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> ProjectReference:
        cand = await self._candidate(project_id, candidate_id)
        verified = data.pop("verified", False)
        row = ProjectReference(candidate_id=cand.id, **data)
        if verified:
            row.verified_by = actor_id
            row.verified_at = datetime.now(UTC)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete_reference(self, project_id: uuid.UUID, candidate_id: uuid.UUID, reference_id: uuid.UUID) -> None:
        cand = await self._candidate(project_id, candidate_id)
        row = await self.session.get(ProjectReference, reference_id)
        if row is None or row.candidate_id != cand.id:
            raise not_found("reference_not_found")
        await self.session.delete(row)
        await self.session.flush()

    async def _evidence_of(self, cand: BidderCandidate) -> list[dict[str, Any]]:
        """Evidence chips read from subcontractors (Decision 5): certificates with expiry, prequal status, rating."""
        if cand.subcontractor_id is None:
            return []
        from app.modules.subcontractors.models import (
            Certificate,
            PrequalificationApplication,
            Subcontractor,
            SubcontractorRating,
        )

        out: list[dict[str, Any]] = []
        sub = await self.session.get(Subcontractor, cand.subcontractor_id)
        if sub is not None:
            out.append(
                {
                    "kind": "prequal_status",
                    "ref": f"subcontractor:{sub.id}",
                    "status": sub.prequalification_status,
                    "expires": getattr(sub, "insurance_expiry_date", None),
                    "rating": _dec(getattr(sub, "rating_score", None)),
                }
            )
        certs = (
            (
                await self.session.execute(
                    select(Certificate).where(Certificate.subcontractor_id == cand.subcontractor_id)
                )
            )
            .scalars()
            .all()
        )
        for c in certs:
            if c.revoked:
                continue
            out.append(
                {"kind": "certificate", "ref": f"certificate:{c.id}", "type": c.cert_type, "expires": c.valid_until}
            )
        application = (
            (
                await self.session.execute(
                    select(PrequalificationApplication)
                    .where(PrequalificationApplication.subcontractor_id == cand.subcontractor_id)
                    .order_by(PrequalificationApplication.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if application is not None:
            out.append(
                {
                    "kind": "prequal_application",
                    "ref": f"prequal_application:{application.id}",
                    "status": application.status,
                    "decided_on": application.decision_at.date() if application.decision_at else None,
                }
            )
        rating = (
            (
                await self.session.execute(
                    select(SubcontractorRating)
                    .where(SubcontractorRating.subcontractor_id == cand.subcontractor_id)
                    .order_by(SubcontractorRating.period.desc())
                )
            )
            .scalars()
            .first()
        )
        if rating is not None:
            out.append(
                {
                    "kind": "rating",
                    "ref": f"rating:{rating.id}",
                    "period": rating.period,
                    "quality": _dec(rating.quality_score),
                    "hse": _dec(rating.hse_score),
                    "schedule": _dec(rating.schedule_score),
                }
            )
        return out

    async def candidate_views(self, project_id: uuid.UUID, package_id: uuid.UUID) -> dict[str, Any]:
        """Screen 3: the candidate matrix of one package with totals, evidence and the shortlist findings."""
        award = await self._award(project_id, package_id)
        concept = await self.get_concept(project_id)
        cat = await self.catalogue_of(concept)
        profile = await self.profile_for(project_id, award)
        criteria = list(profile.criteria) if profile else []
        pass_mark = Decimal(profile.pass_mark) if profile else Decimal("0")
        cands = list(
            (
                await self.session.execute(
                    select(BidderCandidate)
                    .where(BidderCandidate.project_id == project_id, BidderCandidate.package_id == package_id)
                    .order_by(BidderCandidate.created_at)
                )
            )
            .scalars()
            .all()
        )
        ids = [c.id for c in cands]
        scores: dict[uuid.UUID, list[CandidateScore]] = {}
        refs: dict[uuid.UUID, list[ProjectReference]] = {}
        if ids:
            for s in (
                await self.session.execute(select(CandidateScore).where(CandidateScore.candidate_id.in_(ids)))
            ).scalars():
                scores.setdefault(s.candidate_id, []).append(s)
            for r in (
                await self.session.execute(select(ProjectReference).where(ProjectReference.candidate_id.in_(ids)))
            ).scalars():
                refs.setdefault(r.candidate_id, []).append(r)
        cp = await plan.get_package(self.session, project_id, package_id)
        gate = await self.release_gate(project_id, concept)
        applies = await self.advance_applies(project_id, concept)
        pf = await self._facts_of(project_id, cp, award, gate, advance_applies=applies) if cp else None
        bp = ev.backward_pass(cat, pf) if pf else None
        items = []
        rule_rows = []
        findings: list[dict[str, Any]] = []
        for c in cands:
            sc = {
                s.criterion_code: {"passed": s.passed, "score": None if s.score is None else str(s.score)}
                for s in scores.get(c.id, [])
            }
            total = ev.candidate_score(criteria, sc)
            evidence = await self._evidence_of(c)
            if c.list_kind == "short":
                findings += ev.evidence_findings(str(c.id), evidence, bp.award_date if bp else None)
            name = await self._company_name(c)
            items.append(
                {
                    "id": str(c.id),
                    "package_id": str(c.package_id),
                    "subcontractor_id": _s(c.subcontractor_id),
                    "vendor_id": _s(c.vendor_id),
                    "name": name,
                    "registered": self._registered(c),
                    "source": c.source,
                    "list": c.list_kind,
                    "decision_rationale": c.decision_rationale,
                    "conflict_of_interest_declared": c.conflict_of_interest_declared,
                    "conflict_note": c.conflict_note,
                    "scores": [
                        {
                            "criterion_code": s.criterion_code,
                            "passed": s.passed,
                            "score": None if s.score is None else str(s.score),
                            "evidence": s.evidence,
                            "note": s.note,
                        }
                        for s in scores.get(c.id, [])
                    ],
                    "total_score": str(total["total"]),
                    "passed_all": total["passed_all"],
                    "missing_criteria": total["missing"],
                    "evidence": [
                        {**e, **{k: _iso(e[k]) for k in ("expires", "decided_on") if k in e}} for e in evidence
                    ],
                    "references": [
                        {
                            "id": str(r.id),
                            "project_name": r.project_name,
                            "client": r.client,
                            "value": _dec(r.value),
                            "currency": r.currency,
                            "year": r.year,
                            "role": r.role,
                            "contact": r.contact,
                            "verified": r.verified_at is not None,
                        }
                        for r in refs.get(c.id, [])
                    ],
                }
            )
            rule_rows.append(
                {
                    "id": c.id,
                    "list": c.list_kind,
                    "registered": self._registered(c),
                    "rationale": c.decision_rationale,
                    "scores": sc,
                }
            )
        if pf is not None:
            findings = ev.shortlist_findings(cat, pf, criteria, pass_mark, rule_rows) + findings
        return {
            "package_id": str(package_id),
            "profile": None
            if profile is None
            else {"id": str(profile.id), "criteria": criteria, "pass_mark": str(profile.pass_mark)},
            "min_bidders": ev.min_bidders_of(cat, award.procedure_code),
            "items": items,
            "total": len(items),
            "findings": findings,
            "package_state": award.state,
        }

    async def _company_name(self, c: BidderCandidate) -> str:
        if c.subcontractor_id:
            from app.modules.subcontractors.models import Subcontractor

            sub = await self.session.get(Subcontractor, c.subcontractor_id)
            if sub is not None:
                return sub.trade_name or sub.legal_name
        if c.vendor_id:
            from app.modules.supplier_catalogs.models import Vendor

            v = await self.session.get(Vendor, c.vendor_id)
            if v is not None:
                return v.name
        return c.free_name

    async def confirm_shortlist(
        self, project_id: uuid.UUID, package_id: uuid.UUID, *, actor_id: uuid.UUID, can_manage: bool
    ) -> AwardPackage:
        """Rule 8: the package becomes ``shortlisted`` only with a valid short list."""
        await self._require_steer(project_id, actor_id, can_manage)
        award = await self._award(project_id, package_id, lock=True)
        if award.state != "procedure_set":
            raise conflict("invalid_transition", detail=f"{award.state}->shortlisted")
        view = await self.candidate_views(project_id, package_id)
        errors = [f for f in view["findings"] if f["severity"] == "error"]
        if errors:
            raise ProcurementError("shortlist_invalid", 422, violations=errors)
        award.state = "shortlisted"
        await self.session.flush()
        await self._audit(actor_id, "procurement_award_package", award.id, "shortlisted", to_status="shortlisted")
        self._publish(
            "procurement_concept.package.shortlisted", {"project_id": str(project_id), "package_id": str(package_id)}
        )
        return award

    # ── market sounding ──────────────────────────────────────────────────

    async def _sounding(self, project_id: uuid.UUID, sounding_id: uuid.UUID) -> MarketSounding:
        row = await self.session.get(MarketSounding, sounding_id)
        if row is None or row.project_id != project_id:
            raise not_found("sounding_not_found")
        return row

    async def _check_sounding_refs(self, project_id: uuid.UUID, data: dict[str, Any]) -> None:
        for pid in data.get("package_ids") or []:
            await self._award(project_id, pid)
        for cid in data.get("participant_candidate_ids") or []:
            await self._candidate(project_id, cid)

    async def list_soundings(self, project_id: uuid.UUID) -> list[MarketSounding]:
        return list(
            (
                await self.session.execute(
                    select(MarketSounding)
                    .where(MarketSounding.project_id == project_id)
                    .order_by(MarketSounding.held_on.desc())
                )
            )
            .scalars()
            .all()
        )

    async def save_sounding(
        self,
        project_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        sounding_id: uuid.UUID | None = None,
    ) -> MarketSounding:
        await self.get_concept(project_id)
        await self._check_sounding_refs(project_id, data)
        row = (
            await self._sounding(project_id, sounding_id)
            if sounding_id
            else MarketSounding(project_id=project_id, created_by=actor_id)
        )
        for key, value in data.items():
            if key in ("package_ids", "participant_candidate_ids"):
                value = [str(v) for v in value]
            elif key == "held_on":
                value = _iso(value)
            setattr(row, key, value)
        if sounding_id is None:
            self.session.add(row)
        await self.session.flush()
        await self._audit(actor_id, "procurement_sounding", row.id, "updated" if sounding_id else "created")
        return row

    async def delete_sounding(self, project_id: uuid.UUID, sounding_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        row = await self._sounding(project_id, sounding_id)
        await self.session.delete(row)
        await self.session.flush()

    # ── award schedule (rule 11, Decision 7) ─────────────────────────────

    async def schedule_view(self, project_id: uuid.UUID, *, today: date | None = None) -> dict[str, Any]:
        today = today or datetime.now(UTC).date()
        concept = await self.get_concept(project_id)
        cat = await self.catalogue_of(concept)
        cps, _rows, pkgs = await self._package_facts(project_id)
        codes = {str(c.id): c for c in cps}
        gate = await self.release_gate(project_id, concept)
        release = await self._release_date(project_id, gate)
        rows = []
        for p in pkgs:
            if p.state == "cancelled":
                continue
            bp = ev.backward_pass(cat, p)
            award_row = await self.session.get(AwardPackage, uuid.UUID(p.id))
            rows.append(
                {
                    "package_id": p.id,
                    "code": p.code,
                    "title": codes[p.id].title if p.id in codes else "",
                    "need_date": _iso(p.need_date),
                    "lead_time_days": p.lead_time_days,
                    "procedure_code": p.procedure_code,
                    "procedure_days": bp.procedure_days if bp else ev.procedure_days(cat, p),
                    "proposed_award_date": _iso(bp.award_date) if bp else None,
                    "proposed_start_date": _iso(bp.start_date) if bp else None,
                    "is_advance": p.is_advance,
                    "start_activity_id": _s(award_row.start_activity_id) if award_row else None,
                    "award_activity_id": _s(award_row.award_activity_id) if award_row else None,
                    "findings": ev.schedule_findings(cat, p, today=today, release_date=release),
                }
            )
        return {"release_date": _iso(release), "release_gate_code": gate.code if gate else None, "items": rows}

    async def confirm_schedule(
        self, project_id: uuid.UUID, package_ids: list[uuid.UUID], *, actor_id: uuid.UUID, can_manage: bool
    ) -> list[dict[str, Any]]:
        """Write the confirmed proposals as schedule activities (idempotent: re-confirm updates the dates)."""
        from app.modules.schedule.models import Activity, Schedule

        await self._require_steer(project_id, actor_id, can_manage)
        concept = await self.get_concept(project_id)
        cat = await self.catalogue_of(concept)
        gate = await self.release_gate(project_id, concept)
        schedule = (
            (
                await self.session.execute(
                    select(Schedule).where(Schedule.project_id == project_id).order_by(Schedule.created_at)
                )
            )
            .scalars()
            .first()
        )
        if schedule is None:
            raise conflict("no_schedule")
        cps = {str(c.id): c for c in await plan.list_packages(self.session, project_id)}
        out = []
        for pid in package_ids:
            row = await self._award(project_id, pid, lock=True)
            cp = cps.get(str(pid))
            if cp is None:
                raise not_found("package_not_found")
            applies = await self.advance_applies(project_id, concept)
            facts = await self._facts_of(project_id, cp, row, gate, advance_applies=applies)
            bp = ev.backward_pass(cat, facts)
            if bp is None:
                raise ProcurementError("schedule_needs_need_date_and_procedure", 422, detail=cp.code)
            for slot, day, label in (
                ("start_activity_id", bp.start_date, "start"),
                ("award_activity_id", bp.award_date, "award"),
            ):
                act_id = getattr(row, slot)
                act = await self.session.get(Activity, act_id) if act_id else None
                if act is None or act.schedule_id != schedule.id:
                    act = Activity(
                        schedule_id=schedule.id,
                        name=f"{cp.code} {label}",
                        start_date=day.isoformat(),
                        end_date=day.isoformat(),
                        duration_days=0,
                        activity_type="milestone",
                        metadata_={"award_package_id": str(pid), "procurement_milestone": label},
                    )
                    self.session.add(act)
                    await self.session.flush()
                    setattr(row, slot, act.id)
                else:
                    act.start_date = day.isoformat()
                    act.end_date = day.isoformat()
            out.append(
                {
                    "package_id": str(pid),
                    "start_activity_id": str(row.start_activity_id),
                    "award_activity_id": str(row.award_activity_id),
                    "start_date": bp.start_date.isoformat(),
                    "award_date": bp.award_date.isoformat(),
                }
            )
        await self.session.flush()
        await self._audit(actor_id, "procurement_concept", concept.id, "schedule_confirmed")
        return out

    # ── execution (rules 15, 16) ─────────────────────────────────────────

    async def cost_reference_options(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """What a package may name as its cost reference: the section headers of the project's bills.

        The positions under the chosen section become the scope lines of the
        execution vehicle, so ``positions`` says how many it would carry.
        """
        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.service import SECTION_UNITS

        rows = (
            await self.session.execute(
                select(Position, BOQ.name)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id, func.lower(func.trim(Position.unit)).in_(SECTION_UNITS))
                .order_by(BOQ.name, Position.sort_order, Position.ordinal)
            )
        ).all()
        ids = [pos.id for pos, _name in rows]
        children: dict[uuid.UUID, int] = {}
        if ids:
            counted = await self.session.execute(
                select(Position.parent_id, func.count()).where(Position.parent_id.in_(ids)).group_by(Position.parent_id)
            )
            children = {parent: n for parent, n in counted.all()}
        return [
            {
                "kind": "boq_section",
                "id": str(pos.id),
                "code": pos.ordinal,
                "title": pos.description,
                "boq_id": str(pos.boq_id),
                "boq_name": name,
                "positions": children.get(pos.id, 0),
            }
            for pos, name in rows
        ]

    async def _require_boq_section(self, project_id: uuid.UUID, position_id: uuid.UUID) -> None:
        """The reference is a section header of a bill of this project (what the picker lists)."""
        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.service import SECTION_UNITS

        head = await self.session.get(Position, position_id)
        boq = await self.session.get(BOQ, head.boq_id) if head is not None else None
        if boq is None or boq.project_id != project_id:
            raise not_found("cost_reference_not_found")
        if (head.unit or "").strip().lower() not in SECTION_UNITS:
            raise not_found("cost_reference_not_found")

    async def _scope_lines(self, project_id: uuid.UUID, row: AwardPackage) -> list[dict[str, Any]]:
        """Scope lines from the BOQ section the package points at (positions under that section)."""
        if row.cost_ref_kind != "boq_section" or row.cost_ref_id is None:
            return []
        from app.modules.boq.models import BOQ, Position

        head = await self.session.get(Position, row.cost_ref_id)
        if head is None:
            return []
        boq = await self.session.get(BOQ, head.boq_id)
        if boq is None or boq.project_id != project_id:
            return []
        children = (
            (
                await self.session.execute(
                    select(Position).where(Position.parent_id == head.id).order_by(Position.sort_order)
                )
            )
            .scalars()
            .all()
        )
        out = []
        for pos in children:
            if not (pos.description or "").strip():
                continue
            # BOQ quantities are stored as text; one that is not a number is named, never read as zero.
            try:
                quantity = parse_amount(pos.quantity if pos.quantity not in (None, "") else "0")
            except ValueError as exc:
                raise ProcurementError("scope_line_quantity_invalid", 422, detail=str(pos.ordinal)) from exc
            out.append(
                {"code": pos.ordinal, "description": pos.description, "unit": pos.unit or "lsum", "quantity": quantity}
            )
        return out

    async def _require_executable(
        self, project_id: uuid.UUID, award: AwardPackage, cp: plan.PlanPackage
    ) -> ProcurementConcept:
        """What must hold before a package gets an execution vehicle (rules 11, 12, 15).

        The concept is approved (or binding), or the package is an advance
        package governance has released; the package is in a state that has a
        procedure; and no rule reports an error on it.
        """
        concept = await self.get_concept(project_id)
        refusal = await self._execution_refusal(project_id, concept, award, cp)
        if refusal is not None:
            raise refusal
        return concept

    async def _execution_refusal(
        self,
        project_id: uuid.UUID,
        concept: ProcurementConcept,
        award: AwardPackage,
        cp: plan.PlanPackage,
        *,
        findings: list[dict[str, Any]] | None = None,
    ) -> ProcurementError | None:
        """Why this package cannot get an execution vehicle now, or ``None`` (the one check, also for ``can``)."""
        if cp.link_id is not None:
            return conflict("execution_exists", detail=f"{cp.link_kind}:{cp.link_id}")
        if award.state not in ("procedure_set", "shortlisted"):
            return conflict("package_not_ready_for_execution", detail=award.state)
        state = await self.effective_state(concept)
        if state not in ("approved", "binding"):
            gate = await self.release_gate(project_id, concept)
            # Where no gate releases procurement nothing is an advance package, whatever a leftover row names.
            released = (
                award.is_advance
                and await self.advance_applies(project_id, concept)
                and await self.advance_release_status(project_id, award, gate) == "released"
            )
            if not released:
                return conflict("concept_not_approved", detail=state)
        if findings is None:
            findings = await self.findings(project_id)
        errors = [f for f in findings if f["ref"] == cp.code and f["severity"] == ev.ERROR]
        if errors:
            return ProcurementError("package_has_blocking_findings", 422, violations=errors)
        if not award.currency:
            return ProcurementError("currency_required", 422)
        return None

    async def create_execution(
        self,
        project_id: uuid.UUID,
        package_id: uuid.UUID,
        *,
        vehicle: str | None,
        submission_deadline: date | None,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> dict[str, Any]:
        """Create ONE BidPackage (works, design, services) or ONE RFQ (supply) and link it (rule 15)."""
        await self._require_steer(project_id, actor_id, can_manage)
        award = await self._award(project_id, package_id, lock=True)
        cp = await plan.get_package(self.session, project_id, package_id)
        if cp is None:
            raise not_found("package_not_found")
        await self._require_executable(project_id, award, cp)
        kind = CONTRACT_PACKAGE_KIND_MAP.get(cp.kind)
        chosen = vehicle or ("rfq" if kind in SUPPLY_KINDS else "bid_package")
        if chosen == "rfq" and kind not in SUPPLY_KINDS:
            raise ProcurementError("vehicle_not_allowed_for_kind", 422, detail=kind)
        lines = await self._scope_lines(project_id, award)
        meta = {"award_package_id": str(package_id), "contract_package_id": str(package_id), "source": MODULE}
        if chosen == "rfq":
            from app.modules.rfq_bidding.schemas import RFQCreate, RFQLineCreate
            from app.modules.rfq_bidding.service import RFQService

            rfq = await RFQService(self.session).create_rfq(
                RFQCreate(
                    project_id=project_id,
                    title=cp.title or cp.code,
                    scope_of_work=cp.scope or None,
                    submission_deadline=_iso(submission_deadline),
                    currency_code=award.currency,
                    evaluation_method="lowest_price" if award.evaluation_method == "lowest_price" else "best_value",
                    lines=[
                        RFQLineCreate(
                            code=ln["code"], description=ln["description"], unit=ln["unit"], quantity=ln["quantity"]
                        )
                        for ln in lines
                    ],
                    metadata=meta,
                ),
                user_id=str(actor_id),
            )
            link_kind, link_id = plan.LINK_RFQ, rfq.id
        else:
            from app.modules.bid_management.models import BidPackageLineItem
            from app.modules.bid_management.schemas import BidPackageCreate
            from app.modules.bid_management.service import BidManagementService

            code = f"{cp.code}-{uuid.uuid4().hex[:6].upper()}"[:64]
            bp = await BidManagementService(self.session).create_package(
                BidPackageCreate(
                    project_id=project_id,
                    code=code,
                    title=cp.title or cp.code,
                    scope_description=cp.scope,
                    submission_deadline=_iso(submission_deadline),
                    currency=award.currency,
                    total_budget_estimate=award.estimated_value or Decimal("0"),
                    metadata=meta,
                ),
                user_id=str(actor_id),
            )
            for i, ln in enumerate(lines):
                self.session.add(
                    BidPackageLineItem(
                        package_id=bp.id,
                        code=ln["code"],
                        description=ln["description"],
                        unit=ln["unit"],
                        quantity=format(ln["quantity"], "f"),
                        order_index=i,
                    )
                )
            link_kind, link_id = plan.LINK_BID_PACKAGE, bp.id
        return await self._link_execution(project_id, package_id, link_kind, link_id, actor_id, lines=len(lines))

    async def link_tender_package(
        self,
        project_id: uuid.UUID,
        package_id: uuid.UUID,
        tender_package_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> dict[str, Any]:
        """Link an EXISTING tender package of this project as the execution vehicle (rule 15: link only).

        Nothing is created in tendering and its data is not changed; the package
        simply cannot get a second vehicle afterwards.
        """
        from app.modules.tendering.models import TenderPackage

        await self._require_steer(project_id, actor_id, can_manage)
        award = await self._award(project_id, package_id, lock=True)
        cp = await plan.get_package(self.session, project_id, package_id)
        if cp is None:
            raise not_found("package_not_found")
        tender = await self.session.get(TenderPackage, tender_package_id)
        if tender is None or tender.project_id != project_id:
            raise not_found("tender_package_not_found")
        if await plan.find_by_link(self.session, plan.LINK_TENDER_PACKAGE, tender_package_id) is not None:
            raise conflict("execution_exists", detail=f"{plan.LINK_TENDER_PACKAGE}:{tender_package_id}")
        await self._require_executable(project_id, award, cp)
        return await self._link_execution(
            project_id, package_id, plan.LINK_TENDER_PACKAGE, tender_package_id, actor_id, lines=0
        )

    async def _link_execution(
        self,
        project_id: uuid.UUID,
        package_id: uuid.UUID,
        link_kind: str,
        link_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        lines: int,
    ) -> dict[str, Any]:
        try:
            linked = await plan.set_link_once(self.session, project_id, package_id, link_kind, link_id)
        except plan.PlanUnavailableError as exc:
            raise conflict("package_plan_unavailable") from exc
        if not linked:
            # A concurrent creation won the link; the caller's transaction (and this vehicle) rolls back.
            raise conflict("execution_exists")
        await self.session.flush()
        await self._audit(
            actor_id,
            "procurement_award_package",
            package_id,
            "execution_created",
            metadata={"kind": link_kind, "id": str(link_id)},
        )
        self._publish(
            "procurement_concept.execution.created",
            {"project_id": str(project_id), "package_id": str(package_id), "kind": link_kind, "id": str(link_id)},
        )
        return {"package_id": str(package_id), "kind": link_kind, "id": str(link_id), "lines": lines}

    async def read_back(self, link_kind: str, link_id: uuid.UUID, target: str) -> AwardPackage | None:
        """Rule 16: move the award package of a linked vehicle to ``in_tender`` / ``awarded``, idempotently."""
        cp = await plan.find_by_link(self.session, link_kind, link_id)
        if cp is None:
            return None
        q = select(AwardPackage).where(AwardPackage.id == cp.id).with_for_update()
        row = (await self.session.execute(q)).scalars().first()
        if row is None:
            return None
        nxt = read_back_target(row.state, target)
        if nxt is None:
            return row
        before = row.state
        row.state = nxt
        row.state_before = None
        await self.session.flush()
        await self._audit(
            None, "procurement_award_package", row.id, f"read_back_{nxt}", from_status=before, to_status=nxt
        )
        return row

    # ── frameworks (rule 13, Decision 6) ─────────────────────────────────

    async def _framework(
        self, tenant_id: str | None, framework_id: uuid.UUID, *, lock: bool = False
    ) -> FrameworkAgreement:
        q = select(FrameworkAgreement).where(FrameworkAgreement.id == framework_id)
        if lock:
            q = q.with_for_update()
        row = (await self.session.execute(q)).scalars().first()
        if row is None or not tenant_id or row.tenant_id != tenant_id:
            raise not_found("framework_not_found")
        return row

    async def project_tenant(self, project_id: uuid.UUID) -> str | None:
        """The company a project belongs to: its owner's tenant (the platform has no other company key)."""
        from app.modules.projects.models import Project

        owner = (
            await self.session.execute(select(Project.owner_id).where(Project.id == project_id))
        ).scalar_one_or_none()
        return str(owner) if owner else None

    async def list_frameworks(self, tenant_id: str | None) -> list[FrameworkAgreement]:
        if not tenant_id:
            return []
        return list(
            (
                await self.session.execute(
                    select(FrameworkAgreement)
                    .where(FrameworkAgreement.tenant_id == tenant_id)
                    .order_by(FrameworkAgreement.code)
                )
            )
            .scalars()
            .all()
        )

    async def project_frameworks(self, project_id: uuid.UUID, tenant_id: str | None) -> list[FrameworkAgreement]:
        """Frameworks a package of this project may call off: the project's company's and the caller's own."""
        tenants = [t for t in dict.fromkeys((await self.project_tenant(project_id), tenant_id)) if t]
        out: list[FrameworkAgreement] = []
        for t in tenants:
            out += await self.list_frameworks(t)
        return out

    async def create_framework(
        self, tenant_id: str | None, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> FrameworkAgreement:
        if not tenant_id:
            raise forbidden("no_tenant")
        if data["end_date"] < data["start_date"]:
            raise ProcurementError("framework_dates_inverted", 422)
        data = {**data, "max_value": _number(data["max_value"])}
        await self._require_company(data)
        row = FrameworkAgreement(
            tenant_id=tenant_id,
            created_by=actor_id,
            state="draft",
            **{**data, "start_date": _iso(data["start_date"]), "end_date": _iso(data["end_date"])},
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict("framework_code_exists") from exc
        await self._audit(actor_id, "procurement_framework", row.id, "created")
        return row

    async def patch_framework(
        self, tenant_id: str | None, framework_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> FrameworkAgreement:
        row = await self._framework(tenant_id, framework_id, lock=True)
        if row.state in ("expired", "terminated"):
            raise conflict("framework_closed")
        await self._require_company(data)
        if "end_date" in data and data["end_date"] < _day(row.start_date):
            raise ProcurementError("framework_dates_inverted", 422)
        if "max_value" in data:
            data = {**data, "max_value": _number(data["max_value"])}
            ledger = await self._ledger_of(row)
            if data["max_value"] < Decimal(ledger["call_off_value"]):
                # The ceiling may not drop below what has already been called off.
                raise ProcurementError("framework_max_below_call_off", 422, detail=ledger["call_off_value"])
        for key, value in data.items():
            setattr(row, key, _iso(value) if key == "end_date" else value)
        await self.session.flush()
        await self._audit(actor_id, "procurement_framework", row.id, "updated", metadata={"fields": sorted(data)})
        return row

    async def transition_framework(
        self, tenant_id: str | None, framework_id: uuid.UUID, target: str, *, actor_id: uuid.UUID
    ) -> FrameworkAgreement:
        row = await self._framework(tenant_id, framework_id, lock=True)
        if not can_transition(FRAMEWORK_FSM, row.state, target):
            raise conflict("invalid_transition", detail=f"{row.state}->{target}")
        before = row.state
        row.state = target
        await self.session.flush()
        await self._audit(actor_id, "procurement_framework", row.id, target, from_status=before, to_status=target)
        return row

    async def ledger(self, tenant_id: str | None, framework_id: uuid.UUID) -> dict[str, Any]:
        """Call-off ledger: linked award packages (estimates, all projects of the tenant) and tagged POs."""
        row = await self._framework(tenant_id, framework_id)
        return await self._ledger_of(row)

    async def _tenant_project_ids(self, tenant_id: str) -> set[uuid.UUID]:
        """Projects of the framework's company (those its tenant owns)."""
        from app.modules.projects.models import Project

        try:
            owner = uuid.UUID(tenant_id)
        except ValueError:
            return set()
        return set((await self.session.execute(select(Project.id).where(Project.owner_id == owner))).scalars().all())

    async def _ledger_of(self, row: FrameworkAgreement) -> dict[str, Any]:
        """Everything that consumes the framework, and what is left of it.

        Award packages that call it off and whose ContractPackage still exists,
        and purchase orders that name it in projects of the framework's company
        (or of a project that calls it off); a purchase order elsewhere that
        merely carries the id does not consume it. An entry in another currency, or a purchase order
        lookup that failed, makes the remainder unknown (``None``), because a
        partial sum would overstate what is left.
        """
        from app.modules.procurement.models import PurchaseOrder

        linked = (
            (
                await self.session.execute(
                    select(AwardPackage).where(
                        AwardPackage.framework_agreement_id == row.id, AwardPackage.state != "cancelled"
                    )
                )
            )
            .scalars()
            .all()
        )
        live = await plan.existing_package_ids(self.session, [p.id for p in linked])
        # A linked package was checked against the framework's company when it was linked.
        pkgs = [p for p in linked if live is None or p.id in live]
        projects = await self._tenant_project_ids(row.tenant_id) | {p.project_id for p in pkgs}
        entries = [
            {
                "kind": "award_package",
                "id": str(p.id),
                "project_id": str(p.project_id),
                "amount": _dec(p.estimated_value or Decimal("0")),
                "currency": p.currency,
                "state": p.state,
            }
            for p in pkgs
        ]
        complete = True
        pos: list[Any] = []
        if projects:
            try:
                async with self.session.begin_nested():
                    res = await self.session.execute(
                        select(PurchaseOrder).where(
                            PurchaseOrder.project_id.in_(projects),
                            PurchaseOrder.metadata_["framework_agreement_id"].as_string() == str(row.id),
                        )
                    )
                    pos = list(res.scalars().all())
            except DBAPIError:
                logger.warning("framework ledger: purchase order lookup failed for %s", row.id, exc_info=True)
                complete = False
        pkg_ids = {str(p.id) for p in pkgs}
        for po in pos:
            meta = po.metadata_ or {}
            if str(meta.get("award_package_id") or "") in pkg_ids:
                continue  # counted through its package already
            try:
                amount = parse_amount(po.amount_subtotal if po.amount_subtotal not in (None, "") else "0")
            except ValueError:
                complete = False
                continue
            entries.append(
                {
                    "kind": "purchase_order",
                    "id": str(po.id),
                    "project_id": str(po.project_id),
                    "amount": format(amount, "f"),
                    "currency": po.currency_code,
                    "state": po.status,
                }
            )
        currency = row.currency.upper()
        same = [e for e in entries if (e["currency"] or "").upper() == currency]
        other = [e for e in entries if (e["currency"] or "").upper() != currency and Decimal(e["amount"]) != 0]
        call_off = sum((Decimal(e["amount"]) for e in same), Decimal("0"))
        known = complete and not other
        return {
            "framework_id": str(row.id),
            "max_value": _dec(row.max_value),
            "currency": row.currency,
            "call_off_value": _dec(call_off),
            "remaining_value": _dec(row.max_value - call_off) if known else None,
            "remaining_known": known,
            "complete": complete,
            "unconverted_entries": len(other),
            "items": entries,
            "total": len(entries),
        }

    async def _framework_facts(self, framework_id: str | None) -> dict[str, Any] | None:
        if not framework_id:
            return None
        row = await self.session.get(FrameworkAgreement, uuid.UUID(framework_id))
        if row is None:
            return None
        ledger = await self._ledger_of(row)
        items = ledger["items"]
        currency = row.currency.upper()

        def remaining_excluding(pkg_id: str) -> Decimal | None:
            """What is left for this package, or ``None`` when another entry cannot be expressed in the currency."""
            others = [e for e in items if e["id"] != pkg_id]
            if not ledger["complete"] or any(
                (e["currency"] or "").upper() != currency and Decimal(e["amount"]) != 0 for e in others
            ):
                return None
            used = sum(
                (Decimal(e["amount"]) for e in others if (e["currency"] or "").upper() == currency), Decimal("0")
            )
            return row.max_value - used

        return {
            "state": row.state,
            "package_kinds": row.package_kinds,
            "currency": row.currency,
            "end_date": _day(row.end_date),
            "remaining_excluding": remaining_excluding,
        }

    async def _link_framework(self, project_id: uuid.UUID, award: AwardPackage, tenant_id: str | None) -> None:
        """Calling off: a framework of the project's company, active, same currency, with value left (rule 13).

        The framework is locked while the remainder is read, so two call-offs
        cannot both take the last of it.
        """
        company = await self.project_tenant(project_id)
        fw = (
            (
                await self.session.execute(
                    select(FrameworkAgreement)
                    .where(FrameworkAgreement.id == award.framework_agreement_id)
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if fw is None or fw.tenant_id not in {t for t in (tenant_id, company) if t}:
            raise not_found("framework_not_found")
        if fw.state != "active":
            raise conflict("framework_not_active", detail=fw.state)
        if award.estimated_value is None:
            return
        if (award.currency or "").upper() != fw.currency.upper():
            # Amounts in two currencies are never compared as plain numbers.
            raise ProcurementError("framework_currency_mismatch", 422, detail=fw.currency)
        facts = await self._framework_facts(str(fw.id))
        remaining = facts["remaining_excluding"](str(award.id)) if facts else None
        if remaining is None:
            raise ProcurementError("framework_remaining_unknown", 422)
        if remaining < award.estimated_value:
            raise ProcurementError("framework_exhausted", 422, detail=format(remaining, "f"))

    async def _prequal_findings(
        self,
        project_id: uuid.UUID,
        cat: ProcurementCatalogue,
        p: ev.PackageFacts,
        row: AwardPackage,
        award_date: date | None,
    ) -> list[dict[str, Any]]:
        if row.state not in ("shortlisted",):
            return []
        view = await self.candidate_views(project_id, row.id)
        return view["findings"]

    # ── what the caller may do, and the pickers ──────────────────────────

    async def access(
        self, project_id: uuid.UUID, actor_id: uuid.UUID, *, can_edit: bool, can_manage: bool
    ) -> dict[str, Any]:
        """The three answers every write of a project starts with, each with its refusing code.

        ``edit`` is the edit permission, ``steer`` adds the steering right, and
        ``edit_plan`` adds the plan lock. Computed by the functions the writes call.
        """
        edit = None if can_edit else "permission_denied"
        steer = edit or (None if await self.can_steer(project_id, actor_id, can_manage) else "not_procurement_owner")
        plan_reason = steer
        if plan_reason is None:
            concept = await self.find_concept(project_id)
            if concept is None:
                plan_reason = "concept_missing"
            else:
                refusal = await self._plan_refusal(concept)
                plan_reason = refusal.code if refusal is not None else None
        return {"edit": _answer(edit), "steer": _answer(steer), "edit_plan": _answer(plan_reason)}

    async def profile_views(self, project_id: uuid.UUID, access: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        """Profiles with ``in_use``, and what the caller may do with the list."""
        concept = await self.find_concept(project_id)
        used = await self._profiles_in_use(project_id, concept) if concept is not None else set()
        rows = await self.list_profiles(project_id)
        plan_reason = access["edit_plan"]["reason"]
        items = [
            (
                p,
                {
                    "edit": _answer(plan_reason),
                    "delete": _answer(plan_reason or ("profile_in_use" if p.id in used else None)),
                },
            )
            for p in rows
        ]
        return items, {"create": _answer(plan_reason)}

    async def shortlist_can(self, view: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
        """What the caller may do on one package's candidate list (``view`` from :meth:`candidate_views`)."""
        steer = access["steer"]["reason"]
        invalid = any(f["severity"] == "error" for f in view["findings"])
        confirm = _flag(
            None if view["package_state"] == "procedure_set" else "invalid_transition",
            steer or ("shortlist_invalid" if invalid else None),
        )
        return {
            "add": access["edit"],
            "score": access["edit"],
            "reference": access["edit"],
            "set_list": _answer(steer),
            "delete": _answer(steer),
            "confirm_shortlist": confirm,
        }

    async def gate_options(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The project's gates (governance's read model) for the release gate picker; empty without a model."""
        concept = await self.get_concept(project_id)
        resolved = await self.release_gate(project_id, concept)
        tagged = set((await self.hosting(project_id)).release_gate_codes)
        items = [
            {
                "code": g.code,
                "label": g.label,
                "from_phase": g.from_phase,
                "to_phase": g.to_phase,
                "status": g.status,
                "target_date": _iso(g.target_date),
                "sort_order": g.order,
                "tagged_release_gate": g.code in tagged,
                "selected": resolved is not None and g.id == resolved.id,
            }
            for g in await self._project_gates(project_id)
        ]
        return {
            "items": items,
            "release_gate_code": concept.release_gate_code,
            "resolved_release_gate_code": resolved.code if resolved is not None else None,
            "released_from_start": await self.released_from_start(project_id, concept),
            "gates_in_use": bool(items),
        }

    async def advance_release_options(self, project_id: uuid.UUID) -> dict[str, Any]:
        """What an advance package may name as its release.

        ``items``: the go decisions and conditions of the release gate, then the
        commitments of the project. ``commitments``: whether the commitment
        matrix answers at all, with the reason when it does not, so an empty
        list of commitments is never mistaken for "this project has none".
        """
        concept = await self.get_concept(project_id)
        gate = await self.release_gate(project_id, concept)
        out: list[dict[str, Any]] = []
        if gate is not None:
            out.extend(
                {
                    "kind": "gate_decision",
                    "id": str(d.id),
                    "gate_code": gate.code,
                    "label": d.outcome,
                    "status": d.outcome,
                    "date": d.decided_at.date().isoformat(),
                    "releases": True,
                }
                for d in await self._go_decisions(project_id, gate.id)
            )
            out.extend(
                {
                    "kind": "condition",
                    "id": str(c.id),
                    "gate_code": gate.code,
                    "label": c.text,
                    "status": c.status,
                    "date": c.cleared_at.date().isoformat() if c.cleared_at else None,
                    "releases": c.status == "cleared",
                }
                for c in await project_conditions(self.session, project_id, gate.id)
            )
        lister = commitments.commitment_lister()
        if lister is None or commitments.commitment_checker() is None:
            # Listing what the service would then refuse to accept helps nobody: both hooks or neither.
            return {"items": out, "commitments": {"available": False, "reason": commitments.UNAVAILABLE}}
        out.extend(
            {
                "kind": commitments.KIND,
                "id": str(o.id),
                "gate_code": None,
                "label": f"{o.code} {o.title}".strip(),
                "status": o.status,
                "date": o.released_on.isoformat() if o.released_on else None,
                "releases": o.released,
            }
            for o in await lister(self.session, project_id)
        )
        return {"items": out, "commitments": {"available": True, "reason": None}}

    async def tender_package_options(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Tender packages of the project for the link picker; one already linked says to which package."""
        from app.modules.tendering.models import TenderPackage

        rows = (
            (
                await self.session.execute(
                    select(TenderPackage).where(TenderPackage.project_id == project_id).order_by(TenderPackage.name)
                )
            )
            .scalars()
            .all()
        )
        linked = {
            str(c.link_id): c
            for c in await plan.list_packages(self.session, project_id)
            if c.link_kind == plan.LINK_TENDER_PACKAGE and c.link_id is not None
        }
        return [
            {
                "id": str(t.id),
                "name": t.name,
                "status": t.status,
                "deadline": t.deadline,
                "linked_package_id": str(linked[str(t.id)].id) if str(t.id) in linked else None,
                "linked_package_code": linked[str(t.id)].code if str(t.id) in linked else None,
                "can": {"link": _flag("execution_exists" if str(t.id) in linked else None, None)},
            }
            for t in rows
        ]

    def framework_can(
        self, row: FrameworkAgreement, tenant_id: str | None, can_manage_frameworks: bool
    ) -> dict[str, Any]:
        """What the caller may do with one framework; the allowed state moves come from the state machine."""
        reason = None if can_manage_frameworks else "permission_denied"
        if reason is None and (not tenant_id or row.tenant_id != tenant_id):
            reason = "not_framework_owner"
        return {
            "edit": _answer(reason),
            "transitions": list(FRAMEWORK_FSM.get(row.state, ())) if reason is None else [],
        }

    # ── readiness ────────────────────────────────────────────────────────

    async def readiness(self, project_id: uuid.UUID) -> dict[str, Any]:
        """What the governance gate reads.

        ``ready_for_gate`` is a submitted concept with no blocking finding. It
        does not require an approved concept: the gate decision IS the approval.
        """
        concept = await self.find_concept(project_id)
        if concept is None:
            return {"state": None, "approved": False, "submitted": False, "blocking": 0, "ready_for_gate": False}
        state = await self.effective_state(concept)
        blocking = [f for f in await self.findings(project_id) if f["blocks_approval"]]
        submitted = concept.state in _SUBMITTED
        return {
            "state": state,
            "approved": state in ("approved", "binding"),
            "submitted": submitted,
            "blocking": len(blocking),
            "ready_for_gate": submitted and not blocking,
        }

    async def capabilities(self, project_id: uuid.UUID, actor_id: uuid.UUID, can_manage: bool) -> dict[str, Any]:
        """What this caller may do now, from the same checks the writes enforce, with the refusing code."""
        concept = await self.get_concept(project_id)
        state = await self.effective_state(concept)
        steer = await self.can_steer(project_id, actor_id, can_manage)
        no_steer = None if steer else "not_procurement_owner"
        locked = (
            "binding_requires_change_request"
            if state == "binding"
            else ("concept_locked" if state in _PLAN_LOCKED else None)
        )

        answer = _answer

        def move(target: str) -> str | None:
            return None if can_transition(CONCEPT_FSM, state, target) else (locked or "invalid_transition")

        gate_fields = no_steer or (None if can_manage else "manage_required")
        if gate_fields is None and concept.state != "draft":
            gate_fields = "gate_fields_frozen"
        approve, approve_applies = await self.hand_approval_refusal(project_id, concept, actor_id, can_manage)
        reopen, reopen_applies = await self.hand_reopen_refusal(project_id, concept, can_manage)
        return {
            "steer": answer(no_steer),
            "edit_plan": answer(no_steer or locked),
            "submit": answer(no_steer or move("in_review")),
            "return": answer(no_steer or move("draft")),
            "set_gate_fields": answer(gate_fields),
            # By hand only where the project has no gates; with gates the gate decision approves and a
            # change request reopens, so neither action exists and the screen hides both.
            "approve": answer(approve.code if approve else None, applies=approve_applies),
            "reopen": answer(reopen.code if reopen else None, applies=reopen_applies),
        }
