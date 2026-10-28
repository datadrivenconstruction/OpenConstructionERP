# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Engineering brief service: requirements brief, technical concept, programme and framework schedule.

Every write runs in the caller's transaction with its audit entry (``log_activity``) and its events
(``publish_after_commit``).

Approval: the brief is the content of the governance frame document that the project's governance
catalogue tags as hosting it (``hosting``). This module submits; the gate decision (or an approved frame
change request) binds the document, and ``mirror_binding`` copies that onto the brief together with a
frozen snapshot. Only a decision taken after the submission counts. While the brief is in review everything
the reviewer reads stands still. A project that runs without gates approves by hand, never weaker than the
gate (four eyes holds, the same findings refuse it).

The requirements are rows of the ``requirements`` module in one requirement set per brief, written through
that module's service. The framework schedule is planned backwards from the operating proof; published, its
milestones become activities of a ``schedule`` programme, and the gate milestones are linked to their
governance gates, so the schedule then owns the gate dates.

The caller arrives as an :class:`Actor`: a user id and the booleans the router's permission checks
produced. No role and no token reach this file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.engineering_brief import hosting, rules
from app.modules.engineering_brief.catalogue import (
    DEFAULT_CATALOGUE_ID,
    ENGINEERING_BRIEF_KIND,
    EngineeringBriefCatalogue,
    label_of,
    register_kinds,
)
from app.modules.engineering_brief.errors import EngineeringBriefError, conflict, forbidden, not_found
from app.modules.engineering_brief.fsm import BRIEF_EDITABLE, BRIEF_FSM, CONCEPT_FSM
from app.modules.engineering_brief.models import (
    ConceptItem,
    EngineeringBrief,
    FrameMilestone,
    ProgrammeLine,
    SpecificationIssue,
    Study,
)
from app.modules.engineering_brief.repository import EngineeringBriefRepository
from app.modules.project_governance import public as governance

logger = logging.getLogger(__name__)

MODULE = "engineering_brief"
_GO = ("go", "go_with_conditions")
# Marks the schedule this module created, so a user's own programme is never taken over.
SCHEDULE_MARK = "engineering_brief"
_REQUIREMENT_FIELDS = (
    "entity",
    "attribute",
    "constraint_type",
    "constraint_value",
    "unit",
    "category",
    "priority",
    "verification_method",
    "originator",
    "originator_role",
    "source_ref",
    "rationale",
    "phase",
)
# Fields a milestone may be explicitly cleared of.
_MILESTONE_NULLABLE = ("planned_date", "successor_id", "gate_code", "permit_requirement_id")


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Actor:
    """Who is calling, and what the router's permission checks allow them."""

    user_id: uuid.UUID | None
    manage: bool = False
    edit: bool = False


def _as_actor(actor: Any) -> Actor:
    """A bare user id is a caller with no capability beyond the route's own permission."""
    return actor if isinstance(actor, Actor) else Actor(actor)


def _uid(actor: Any) -> Any:
    return actor.user_id if isinstance(actor, Actor) else actor


_SAME = "same-as-reason"


def _can(allowed: bool, reason: str | None, state_reason: str | None = _SAME) -> dict[str, Any]:
    refused = None if allowed else reason
    return rules.capability(refused, refused if state_reason is _SAME else state_reason)


def _refuse_nulls(changes: dict[str, Any], nullable: tuple[str, ...] = ()) -> None:
    """An explicit null on a field the row cannot leave empty is a 422, never a database error."""
    empty = sorted(k for k, v in changes.items() if v is None and k not in nullable)
    if empty:
        raise EngineeringBriefError(
            "field_required", 422, violations=[{"code": "field_required", "ref": k} for k in empty]
        )


def _dec(value: Any) -> Decimal:
    out = rules.dec(value)
    if out is None or out <= 0 or out >= Decimal("100000000000000"):
        raise EngineeringBriefError("programme_quantity_invalid", 422)
    return out


def _next_code(prefix: str, existing: list[str]) -> str:
    numbers = [
        int(c[len(prefix) + 1 :]) for c in existing if c.startswith(prefix + "-") and c[len(prefix) + 1 :].isdigit()
    ]
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def _requirement_dict(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "entity": r.entity,
        "attribute": r.attribute,
        "constraint_type": r.constraint_type,
        "constraint_value": r.constraint_value,
        "unit": r.unit,
        "category": r.category,
        "priority": r.priority,
        "verification_method": r.verification_method,
        "originator": r.originator,
        "originator_role": r.originator_role,
        "source_ref": r.source_ref,
        "rationale": r.rationale,
        "phase": r.phase,
        "status": r.status,
    }


def concept_dict(c: ConceptItem) -> dict[str, Any]:
    return {
        "id": c.id,
        "code": c.code,
        "topic_code": c.topic_code,
        "title": c.title,
        "description": c.description,
        "decision": c.decision,
        "status": c.status,
        "requirement_ids": list(c.requirement_ids or []),
    }


def programme_dict(p: ProgrammeLine) -> dict[str, Any]:
    return {
        "id": p.id,
        "code": p.code,
        "kind_code": p.kind_code,
        "label": p.label,
        "unit": p.unit,
        "quantity": Decimal(p.quantity),
        "basis": p.basis,
    }


def milestone_dict(m: FrameMilestone) -> dict[str, Any]:
    return {
        "id": m.id,
        "code": m.code,
        "kind_code": m.kind_code,
        "name": m.name,
        "planned_date": m.planned_date,
        "lead_days": m.lead_days,
        "successor_id": m.successor_id,
        "gate_code": m.gate_code,
        "permit_requirement_id": m.permit_requirement_id,
        "activity_id": m.activity_id,
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def requirements_hash(requirements: list[dict[str, Any]]) -> str:
    """SHA-256 of the requirements, order independent: what binding fixes and drift is measured against."""
    rows = sorted((json_safe(r) for r in requirements), key=lambda r: r["id"])
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EngineeringBriefService:
    """Orchestrates the brief, concept, programme and framework schedule of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EngineeringBriefRepository(session)
        self._governance: dict[uuid.UUID, Any] = {}
        register_kinds()

    # ── infrastructure ─────────────────────────────────────────────────────

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
        publish_after_commit(self.session, f"{MODULE}.{name}", data, source_module=MODULE)

    async def _fsm(self, fsm: Any, row: Any, target: str, actor_id: Any, **meta: Any) -> None:
        """Move ``row`` to ``target``. Repeating a transition is a conflict, so nothing is written twice."""
        if row.status == target:
            raise conflict("already_in_state")
        try:
            await fsm.apply(
                self.session,
                row,
                target,
                actor_id=_s(actor_id),
                extra_metadata={"project_id": _s(row.project_id), **meta},
                entity_type=fsm.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _insert(self, row: Any, taken: str) -> None:
        """Add a row whose unique key another request may take first: the loser answers 409, not a 500."""
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict(taken) from exc

    async def _governance_catalogue(self, project_id: uuid.UUID) -> Any:
        if project_id not in self._governance:
            self._governance[project_id] = await hosting.project_catalogue(self.session, project_id)
        return self._governance[project_id]

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    async def catalogue_for(self, brief: EngineeringBrief) -> EngineeringBriefCatalogue:
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        # The triple is the brief's own stored pin, checked when it was written.
        return await resolve_catalogue(
            self.session,
            brief.catalogue_source,
            brief.catalogue_id,
            brief.catalogue_version,
            kind=ENGINEERING_BRIEF_KIND,
            from_pin=True,
        )

    async def _pin(self, tenant_id: str | None, source: str, cid: str, version: int | None) -> int:
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        try:
            return await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, cid, version, kind=ENGINEERING_BRIEF_KIND
            )
        except GovernanceError as exc:
            raise EngineeringBriefError(exc.code, exc.status_code) from exc

    async def get_brief(self, project_id: uuid.UUID, *, lock: bool = False) -> EngineeringBrief | None:
        return await self.repo.brief(project_id, lock=lock)

    async def require_brief(self, project_id: uuid.UUID, *, lock: bool = False) -> EngineeringBrief:
        brief = await self.repo.brief(project_id, lock=lock)
        if brief is None:
            raise not_found("brief_missing")
        return brief

    async def _child(self, model: type, project_id: uuid.UUID, row_id: uuid.UUID, code: str, *, lock=False) -> Any:
        row = await self.repo.child(model, project_id, row_id, lock=lock)
        if row is None:
            raise not_found(code)
        return row

    # ── brief ──────────────────────────────────────────────────────────────

    async def set_brief(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        catalogue_source: str = "shipped",
        catalogue_id: str | None = None,
        catalogue_version: int | None = None,
        title: str = "",
        summary: str = "",
        operation_proof_date: date | None = None,
    ) -> EngineeringBrief:
        """Create the project's brief with its requirement set and pin a catalogue (the country's, else neutral)."""
        from app.modules.requirements.schemas import RequirementSetCreate
        from app.modules.requirements.service import RequirementsService

        project = await self._project(project_id)
        if await self.repo.brief(project_id) is not None:
            raise conflict("brief_exists")
        cid = catalogue_id
        if cid is None:
            # Governance answers for the country: the active pack's default, else the one shipped catalogue
            # that claims it. Without an answer the module pins its neutral file; it has no country rule.
            pin = governance.default_catalogue_pin(
                ENGINEERING_BRIEF_KIND,
                getattr(project, "country_code", None),
                getattr(project, "subdivision_code", None),
            )
            if pin is not None:
                catalogue_source, cid, catalogue_version = pin.source, pin.catalogue_id, pin.version
            else:
                cid = DEFAULT_CATALOGUE_ID
        version = await self._pin(tenant_id, catalogue_source, cid, catalogue_version)
        from app.modules.engineering_brief.messages import translate

        req_set = await RequirementsService(self.session).create_set(
            RequirementSetCreate(
                project_id=project_id,
                name=title or translate("engineering_brief.requirement_set_name"),
                description=translate("engineering_brief.requirement_set_description"),
            ),
            user_id=_s(actor_id) or "",
        )
        brief = EngineeringBrief(
            project_id=project_id,
            catalogue_source=catalogue_source,
            catalogue_id=cid,
            catalogue_version=version,
            status="draft",
            title=title,
            summary=summary,
            requirement_set_id=req_set.id,
            operation_proof_date=operation_proof_date,
            bound_snapshot={},
            created_by=actor_id,
        )
        await self._insert(brief, "brief_exists")
        await self._audit(actor_id, "engineering_brief", brief.id, "brief_created", metadata={"catalogue": cid})
        return brief

    async def patch_brief(self, project_id: uuid.UUID, changes: dict[str, Any], actor_id: Any) -> EngineeringBrief:
        _refuse_nulls(changes, ("operation_proof_date",))
        brief = await self.require_brief(project_id, lock=True)
        new = {
            k: changes[k]
            for k in ("title", "summary", "operation_proof_date")
            if k in changes and changes[k] != getattr(brief, k)
        }
        if not new:
            return brief
        brief = await self._open_for_edit(project_id, _uid(actor_id))
        for key, value in new.items():
            setattr(brief, key, value)
        if "operation_proof_date" in new:
            catalogue = await self.catalogue_for(brief)
            for m in await self.repo.milestones(project_id):
                if m.kind_code == catalogue.anchor_kind:
                    m.planned_date = new["operation_proof_date"]
        await self.session.flush()
        await self._audit(
            _uid(actor_id),
            "engineering_brief",
            brief.id,
            "brief_updated",
            metadata={k: _iso(v) if isinstance(v, date) else v for k, v in new.items() if k != "summary"},
        )
        return brief

    async def catalogue_view(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The pinned catalogue plus the vocabularies the screens would otherwise hold as literals."""
        from app.modules.requirements.lifecycle import ORIGINATOR_ROLES, PHASE_SPINE, VERIFICATION_METHODS

        catalogue = await self.catalogue_for(await self.require_brief(project_id))
        body = catalogue.model_dump(mode="json")
        body["verification_methods"] = list(VERIFICATION_METHODS)
        body["originator_roles"] = list(ORIGINATOR_ROLES)
        body["phases"] = list(PHASE_SPINE)
        body["priorities"] = ["must", "should", "could", "wont"]
        return body

    async def _gates(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        return [
            {
                "id": g.id,
                "code": g.code,
                "label": g.label,
                "order": g.order,
                "status": g.status,
                "target_date": g.target_date,
                "schedule_activity_id": g.schedule_activity_id,
            }
            for g in await governance.project_gates(self.session, project_id)
        ]

    async def _resolve_frame_document(self, project_id: uuid.UUID) -> Any:
        """The governance document that carries the brief: the one whose type the catalogue tags for it."""
        host = hosting.host(await self._governance_catalogue(project_id))
        if host is None:
            return None
        # A project pinned before its model gained the document type has no row for it: also nothing.
        documents = await governance.project_documents(self.session, project_id)
        return next((d for d in documents if d.code == host.doc_type), None)

    async def brief_view(self, project_id: uuid.UUID, actor: Any = None) -> dict[str, Any]:
        """The brief header. Reading it catches up with a governance approval whose event never arrived."""
        brief = await self.require_brief(project_id)
        if brief.status == "in_review" and brief.governance_document_id is not None:
            await self.mirror_binding(project_id, brief.governance_document_id)
        who = _as_actor(actor)
        has_frame = await self._resolve_frame_document(project_id) is not None
        gates = await hosting.gates_in_use(self.session, project_id)
        four_eyes = await hosting.four_eyes(self.session, project_id)

        def brief_can(action: str) -> dict[str, Any]:
            state = {"has_frame_document": has_frame, "gates_in_use": gates}
            refused = rules.brief_action_refusal(action, brief.status, can_edit=who.edit, **state)
            by_state = rules.brief_action_refusal(action, brief.status, can_edit=True, **state)
            return _can(refused is None, refused, by_state)

        def approve_can() -> dict[str, Any]:
            asked = {"gates_in_use": gates, "four_eyes": four_eyes}
            mine = who.user_id is not None and brief.submitted_by == who.user_id
            refused = rules.brief_approval_refusal(brief.status, can_manage=who.manage, is_submitter=mine, **asked)
            by_state = rules.brief_approval_refusal(brief.status, can_manage=True, is_submitter=False, **asked)
            return _can(refused is None, refused, by_state)

        requirements = [_requirement_dict(r) for r in await self._requirement_rows(brief)]
        return {
            "id": str(brief.id),
            "project_id": str(project_id),
            "catalogue_source": brief.catalogue_source,
            "catalogue_id": brief.catalogue_id,
            "catalogue_version": brief.catalogue_version,
            "status": brief.status,
            "title": brief.title,
            "summary": brief.summary,
            "requirement_set_id": _s(brief.requirement_set_id),
            "schedule_id": _s(brief.schedule_id),
            "operation_proof_date": _iso(brief.operation_proof_date),
            "governance_document_id": _s(brief.governance_document_id),
            "submitted_by": _s(brief.submitted_by),
            "submitted_at": _iso(brief.submitted_at),
            "approved_by": _s(brief.approved_by),
            "approved_at": _iso(brief.approved_at),
            "approval_source": brief.approval_source,
            "has_bound_snapshot": bool(brief.bound_snapshot),
            "bound_snapshot": brief.bound_snapshot or None,
            # True when requirements were changed in the requirements register after the brief was bound.
            "requirements_changed": brief.bound_requirements_hash is not None
            and brief.bound_requirements_hash != requirements_hash(requirements),
            "requirement_count": len(requirements),
            # False on a project without gates: the brief is then approved by hand, and no gate is named.
            "gates_in_use": gates,
            "can": {
                "manage": _can(who.manage, rules.NO_MANAGE),
                "submit": brief_can("submit"),
                "return": brief_can("return"),
                "approve": approve_can(),
                "edit": brief_can("edit"),
                "publish": _can(who.manage, rules.NO_MANAGE),
            },
        }

    async def _open_for_edit(self, project_id: uuid.UUID, actor_id: Any) -> EngineeringBrief:
        """Draft and revising edit freely; approved or binding opens a revision; in review is locked."""
        brief = await self.require_brief(project_id, lock=True)
        refused = rules.brief_action_refusal("edit", brief.status, can_edit=True)
        if refused:
            raise conflict(refused)
        if brief.status not in BRIEF_EDITABLE:
            await self._fsm(BRIEF_FSM, brief, "revising", actor_id)
            await self._audit(actor_id, "engineering_brief", brief.id, "revision_opened")
        return brief

    # ── approval ───────────────────────────────────────────────────────────

    async def submission_findings(self, project_id: uuid.UUID) -> list[rules.Finding]:
        brief = await self.require_brief(project_id)
        return rules.submission_findings(**await self._rule_inputs(brief))

    async def _refuse_open_findings(self, project_id: uuid.UUID) -> None:
        """An incomplete brief answers 422 with what is missing, at submission and at hand approval alike."""
        findings = [f for f in await self.submission_findings(project_id) if f.severity == rules.ERROR]
        if findings:
            raise EngineeringBriefError(findings[0].code, 422, violations=[f.as_dict() for f in findings])

    async def submit(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> EngineeringBrief:
        """Draft or revising -> in_review, only when the brief is complete and something can approve it."""
        brief = await self.require_brief(project_id, lock=True)
        doc = await self._resolve_frame_document(project_id)
        refused = rules.brief_action_refusal(
            "submit",
            brief.status,
            can_edit=True,
            has_frame_document=doc is not None,
            gates_in_use=await hosting.gates_in_use(self.session, project_id),
        )
        if refused:
            raise conflict(refused)
        await self._refuse_open_findings(project_id)
        await self._fsm(BRIEF_FSM, brief, "in_review", actor_id)
        # Without gates no document carries the brief: it is approved by hand.
        brief.governance_document_id = doc.id if doc is not None else None
        brief.submitted_by, brief.submitted_at = actor_id, _now()
        await self.session.flush()
        await self._audit(actor_id, "engineering_brief", brief.id, "brief_submitted")
        self._publish("brief.submitted", {"project_id": str(project_id), "brief_id": str(brief.id)})
        return brief

    async def approve_by_hand(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> EngineeringBrief:
        """In review -> binding on a project that has no gates to approve the brief.

        Never weaker than the gate: four-eyes holds, and the brief is refused on the findings a submission
        is refused on. The manage right is the route's.
        """
        brief = await self.require_brief(project_id, lock=True)
        refused = rules.brief_approval_refusal(
            brief.status,
            can_manage=True,
            gates_in_use=await hosting.gates_in_use(self.session, project_id),
            four_eyes=await hosting.four_eyes(self.session, project_id),
            is_submitter=brief.submitted_by == actor_id,
        )
        if refused == rules.APPROVER_IS_SUBMITTER:
            raise forbidden(refused)
        if refused:
            raise conflict(refused)
        await self._refuse_open_findings(project_id)
        await self._fsm(BRIEF_FSM, brief, "approved", actor_id)
        await self._fsm(BRIEF_FSM, brief, "binding", actor_id)
        await self._freeze(brief)
        brief.approved_by, brief.approved_at, brief.approval_source = actor_id, _now(), "hand"
        brief.bound_revision_id = None
        await self.session.flush()
        await self._audit(actor_id, "engineering_brief", brief.id, "brief_bound", metadata={"source": "hand"})
        self._publish("brief.bound", {"project_id": str(project_id), "brief_id": str(brief.id), "source": "hand"})
        return brief

    async def return_brief(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> EngineeringBrief:
        brief = await self.require_brief(project_id, lock=True)
        refused = rules.brief_action_refusal("return", brief.status, can_edit=True)
        if refused:
            raise conflict(refused)
        await self._fsm(BRIEF_FSM, brief, "draft", actor_id)
        await self._audit(actor_id, "engineering_brief", brief.id, "brief_returned")
        return brief

    async def _freeze(self, brief: EngineeringBrief) -> None:
        brief.bound_snapshot = await self.snapshot(brief.project_id)
        brief.bound_requirements_hash = requirements_hash(
            [_requirement_dict(r) for r in await self._requirement_rows(brief)]
        )

    async def _approval_of(self, brief: EngineeringBrief, doc: Any) -> tuple[Any, datetime, str] | None:
        """Who approved THIS submission, when and how; ``None`` while nobody has.

        The document stays binding between revisions, so its state proves nothing about the brief in
        review. Only a decision taken after the submission counts.
        """
        since = brief.submitted_at
        if since is None:
            return None
        requests = [
            cr
            for cr in await governance.project_change_requests(self.session, brief.project_id, doc.id)
            if cr.status == "approved" and cr.decided_at is not None and cr.decided_at >= since
        ]
        if requests:
            cr = max(requests, key=lambda r: r.decided_at)
            return cr.decided_by, cr.decided_at, "change_request"
        if doc.approved_gate_id is None:
            return None
        decisions = [
            d
            for d in await governance.project_gate_decisions(self.session, brief.project_id, doc.approved_gate_id)
            if d.outcome in _GO and d.decided_at >= since
        ]
        if decisions:
            decision = max(decisions, key=lambda d: d.decided_at)
            return decision.decided_by, decision.decided_at, "gate"
        return None

    async def mirror_binding(self, project_id: uuid.UUID | None, document_id: uuid.UUID) -> bool:
        """The frame document that carries the brief is binding: approve and freeze the submitted brief.

        Idempotent. Called by the governance event and again whenever the brief is read while in review.
        """
        changed = False
        for brief in await self.repo.briefs_for_document(document_id):
            if project_id is not None and brief.project_id != project_id:
                continue
            if brief.status != "in_review":
                continue
            documents = await governance.project_documents(self.session, brief.project_id)
            doc = next((d for d in documents if d.id == document_id), None)
            if doc is None or doc.status != "binding":
                continue
            approval = await self._approval_of(brief, doc)
            if approval is None:
                continue
            approver, at, source = approval
            await self._fsm(BRIEF_FSM, brief, "approved", approver)
            await self._fsm(BRIEF_FSM, brief, "binding", approver)
            await self._freeze(brief)
            brief.approved_by, brief.approved_at, brief.approval_source = approver, at, source
            brief.bound_revision_id = doc.bound_revision_id
            await self.session.flush()
            await self._audit(approver, "engineering_brief", brief.id, "brief_bound", metadata={"source": source})
            self._publish(
                "brief.bound", {"project_id": str(brief.project_id), "brief_id": str(brief.id), "source": source}
            )
            changed = True
        return changed

    async def snapshot(self, project_id: uuid.UUID) -> dict[str, Any]:
        """JSON-safe frozen requirements, concept, programme and milestones."""
        brief = await self.require_brief(project_id)
        return json_safe(
            {
                "taken_at": _now(),
                "operation_proof_date": brief.operation_proof_date,
                "requirements": [_requirement_dict(r) for r in await self._requirement_rows(brief)],
                "concepts": [concept_dict(c) for c in await self.repo.concepts(project_id)],
                "programme": [programme_dict(p) for p in await self.repo.programme(project_id)],
                "milestones": [milestone_dict(m) for m in await self.repo.milestones(project_id)],
            }
        )

    # ── requirements (rows of the requirements module) ─────────────────────

    async def _requirement_rows(self, brief: EngineeringBrief) -> list[Any]:
        if brief.requirement_set_id is None:
            return []
        from app.modules.requirements.repository import RequirementRepository

        return await RequirementRepository(self.session).all_for_set(brief.requirement_set_id)

    async def requirement_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        brief = await self.require_brief(project_id)
        answered: dict[str, list[str]] = {}
        for c in await self.repo.concepts(project_id):
            for rid in c.requirement_ids or []:
                answered.setdefault(str(rid), []).append(c.code)
        return [
            {**json_safe(_requirement_dict(r)), "answered_by": answered.get(str(r.id), [])}
            for r in await self._requirement_rows(brief)
        ]

    async def _set_for_edit(self, project_id: uuid.UUID, actor_id: Any) -> EngineeringBrief:
        brief = await self._open_for_edit(project_id, actor_id)
        if brief.requirement_set_id is None:
            raise conflict("requirement_set_missing")
        return brief

    async def _requirement(self, brief: EngineeringBrief, requirement_id: uuid.UUID) -> Any:
        from app.modules.requirements.repository import RequirementRepository

        row = await RequirementRepository(self.session).get_by_id(requirement_id)
        if row is None or row.requirement_set_id != brief.requirement_set_id:
            raise not_found("requirement_not_found")
        return row

    async def _check_category(self, brief: EngineeringBrief, category: str) -> None:
        if (await self.catalogue_for(brief)).category(category) is None:
            raise EngineeringBriefError("requirement_category_unknown", 422, detail=category)

    async def create_requirement(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> Any:
        from app.modules.requirements.schemas import RequirementCreate
        from app.modules.requirements.service import RequirementsService

        brief = await self._set_for_edit(project_id, actor_id)
        await self._check_category(brief, data["category"])
        row = await RequirementsService(self.session).add_requirement(
            brief.requirement_set_id, RequirementCreate(**data), user_id=_s(actor_id) or ""
        )
        await self._audit(actor_id, "engineering_brief_requirement", row.id, "requirement_added")
        return row

    async def update_requirement(
        self, project_id: uuid.UUID, requirement_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ) -> Any:
        from app.modules.requirements.schemas import RequirementUpdate
        from app.modules.requirements.service import RequirementsService

        _refuse_nulls(changes)
        brief = await self._set_for_edit(project_id, actor_id)
        await self._requirement(brief, requirement_id)
        if "category" in changes:
            await self._check_category(brief, changes["category"])
        row = await RequirementsService(self.session).update_requirement(requirement_id, RequirementUpdate(**changes))
        await self._audit(actor_id, "engineering_brief_requirement", row.id, "requirement_updated")
        return row

    async def delete_requirement(self, project_id: uuid.UUID, requirement_id: uuid.UUID, actor_id: Any) -> None:
        from app.modules.requirements.service import RequirementsService

        brief = await self._set_for_edit(project_id, actor_id)
        await self._requirement(brief, requirement_id)
        # A concept item must not keep answering a requirement that is gone.
        for c in await self.repo.concepts(project_id):
            if str(requirement_id) in (c.requirement_ids or []):
                c.requirement_ids = [r for r in c.requirement_ids if r != str(requirement_id)]
        await RequirementsService(self.session).delete_requirement(brief.requirement_set_id, requirement_id)
        await self._audit(actor_id, "engineering_brief_requirement", requirement_id, "requirement_deleted")

    # ── technical concept ──────────────────────────────────────────────────

    def _check_topic(self, catalogue: EngineeringBriefCatalogue, topic_code: str) -> None:
        if catalogue.topic(topic_code) is None:
            raise EngineeringBriefError("concept_topic_unknown", 422, detail=topic_code)

    async def _check_requirement_ids(self, brief: EngineeringBrief, ids: list[uuid.UUID]) -> list[str]:
        known = {str(r.id) for r in await self._requirement_rows(brief)}
        wanted = [str(i) for i in dict.fromkeys(ids)]
        bad = [i for i in wanted if i not in known]
        if bad:
            raise EngineeringBriefError(
                "requirement_not_in_brief",
                422,
                violations=[{"code": "requirement_not_in_brief", "ref": b} for b in bad],
            )
        return wanted

    async def concept_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        return [json_safe(concept_dict(c)) for c in await self.repo.concepts(project_id)]

    async def create_concept(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> ConceptItem:
        brief = await self._open_for_edit(project_id, actor_id)
        self._check_topic(await self.catalogue_for(brief), data["topic_code"])
        existing = await self.repo.concepts(project_id)
        row = ConceptItem(
            project_id=project_id,
            brief_id=brief.id,
            code=_next_code("CON", [c.code for c in existing]),
            topic_code=data["topic_code"],
            title=data["title"],
            description=data.get("description", ""),
            decision=data.get("decision", ""),
            status="agreed" if str(data.get("decision", "")).strip() else "open",
            requirement_ids=await self._check_requirement_ids(brief, data.get("requirement_ids") or []),
            sort_order=len(existing),
        )
        await self._insert(row, "concept_code_taken")
        await self._audit(actor_id, "engineering_brief_concept", row.id, "concept_added", metadata={"code": row.code})
        return row

    async def concepts_from_catalogue(self, project_id: uuid.UUID, actor_id: Any) -> list[ConceptItem]:
        """One open item for every required topic that has none yet. The user writes the decision."""
        from app.modules.engineering_brief.messages import translate

        brief = await self._open_for_edit(project_id, actor_id)
        catalogue = await self.catalogue_for(brief)
        existing = await self.repo.concepts(project_id)
        have = {c.topic_code for c in existing}
        made: list[ConceptItem] = []
        for topic in catalogue.concept_topics:
            if not topic.required or topic.code in have:
                continue
            row = ConceptItem(
                project_id=project_id,
                brief_id=brief.id,
                code=_next_code("CON", [c.code for c in existing] + [m.code for m in made]),
                topic_code=topic.code,
                title=label_of(topic, "en") or translate(topic.name_key),
                requirement_ids=[],
                sort_order=len(existing) + len(made),
            )
            await self._insert(row, "concept_code_taken")
            made.append(row)
        if made:
            await self._audit(
                actor_id, "engineering_brief", brief.id, "concepts_from_catalogue", metadata={"count": len(made)}
            )
        return made

    async def update_concept(
        self, project_id: uuid.UUID, concept_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ) -> ConceptItem:
        _refuse_nulls(changes)
        brief = await self._open_for_edit(project_id, actor_id)
        row = await self._child(ConceptItem, project_id, concept_id, "concept_not_found", lock=True)
        if "topic_code" in changes:
            self._check_topic(await self.catalogue_for(brief), changes["topic_code"])
        if "requirement_ids" in changes:
            changes["requirement_ids"] = await self._check_requirement_ids(brief, changes["requirement_ids"])
        for key, value in changes.items():
            setattr(row, key, value)
        if "decision" in changes and not str(row.decision).strip() and row.status == "agreed":
            row.status = "open"
        await self.session.flush()
        await self._audit(actor_id, "engineering_brief_concept", row.id, "concept_updated")
        return row

    async def set_concept_status(
        self, project_id: uuid.UUID, concept_id: uuid.UUID, status: str, actor_id: Any
    ) -> ConceptItem:
        await self._open_for_edit(project_id, actor_id)
        row = await self._child(ConceptItem, project_id, concept_id, "concept_not_found", lock=True)
        if status == "agreed" and not str(row.decision).strip():
            raise EngineeringBriefError("decision_required", 422)
        await self._fsm(CONCEPT_FSM, row, status, actor_id)
        return row

    async def delete_concept(self, project_id: uuid.UUID, concept_id: uuid.UUID, actor_id: Any) -> None:
        await self._open_for_edit(project_id, actor_id)
        row = await self._child(ConceptItem, project_id, concept_id, "concept_not_found", lock=True)
        await self.repo.delete(row)
        await self._audit(actor_id, "engineering_brief_concept", concept_id, "concept_deleted")

    # ── programme ──────────────────────────────────────────────────────────

    def _check_programme_kind(self, catalogue: EngineeringBriefCatalogue, kind_code: str) -> None:
        if catalogue.programme_kind(kind_code) is None:
            raise EngineeringBriefError("programme_kind_unknown", 422, detail=kind_code)

    async def programme_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        return [json_safe(programme_dict(p)) for p in await self.repo.programme(project_id)]

    async def create_programme(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> ProgrammeLine:
        brief = await self._open_for_edit(project_id, actor_id)
        self._check_programme_kind(await self.catalogue_for(brief), data["kind_code"])
        existing = await self.repo.programme(project_id)
        row = ProgrammeLine(
            project_id=project_id,
            brief_id=brief.id,
            code=_next_code("PRG", [p.code for p in existing]),
            kind_code=data["kind_code"],
            label=data["label"],
            unit=data["unit"],
            quantity=_dec(data["quantity"]),
            basis=data.get("basis", ""),
            sort_order=len(existing),
        )
        await self._insert(row, "programme_code_taken")
        await self._audit(
            actor_id, "engineering_brief_programme", row.id, "programme_added", metadata={"code": row.code}
        )
        return row

    async def update_programme(
        self, project_id: uuid.UUID, line_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ) -> ProgrammeLine:
        _refuse_nulls(changes)
        brief = await self._open_for_edit(project_id, actor_id)
        row = await self._child(ProgrammeLine, project_id, line_id, "programme_not_found", lock=True)
        if "kind_code" in changes:
            self._check_programme_kind(await self.catalogue_for(brief), changes["kind_code"])
        if "quantity" in changes:
            changes["quantity"] = _dec(changes["quantity"])
        for key, value in changes.items():
            setattr(row, key, value)
        await self.session.flush()
        await self._audit(actor_id, "engineering_brief_programme", row.id, "programme_updated")
        return row

    async def delete_programme(self, project_id: uuid.UUID, line_id: uuid.UUID, actor_id: Any) -> None:
        await self._open_for_edit(project_id, actor_id)
        row = await self._child(ProgrammeLine, project_id, line_id, "programme_not_found", lock=True)
        await self.repo.delete(row)
        await self._audit(actor_id, "engineering_brief_programme", line_id, "programme_deleted")

    # ── framework schedule ─────────────────────────────────────────────────

    async def _permit_states(self, project_id: uuid.UUID, ids: set[str]) -> dict[str, str | None]:
        """Derived state of each linked permit requirement, read through the permits port.

        Without the permits module nothing can be proven or refuted: every link reads ``unavailable``.
        """
        if not ids:
            return {}
        try:
            from app.modules.permits import public as permits
        except ImportError:
            return dict.fromkeys(ids, "unavailable")
        return {i: await permits.requirement_state(self.session, project_id, uuid.UUID(i)) for i in ids}

    async def _activities(self, brief: EngineeringBrief, ids: set[str]) -> dict[str, dict[str, Any] | None]:
        if not ids:
            return {}
        out: dict[str, dict[str, Any] | None] = dict.fromkeys(ids)
        if brief.schedule_id is None:
            return out
        from app.modules.schedule.models import Activity

        stmt = select(Activity.id, Activity.start_date, Activity.end_date).where(
            Activity.schedule_id == brief.schedule_id, Activity.id.in_([uuid.UUID(i) for i in ids])
        )
        for aid, start, end in (await self.session.execute(stmt)).all():
            out[str(aid)] = {"start_date": str(start)[:10], "end_date": str(end)[:10]}
        return out

    async def _rule_inputs(self, brief: EngineeringBrief) -> dict[str, Any]:
        pid = brief.project_id
        milestones = [milestone_dict(m) for m in await self.repo.milestones(pid)]
        return {
            "catalogue": await self.catalogue_for(brief),
            "requirements": [_requirement_dict(r) for r in await self._requirement_rows(brief)],
            "concepts": [concept_dict(c) for c in await self.repo.concepts(pid)],
            "programme": [programme_dict(p) for p in await self.repo.programme(pid)],
            "milestones": milestones,
            "gates": await self._gates(pid),
            "operation_proof_date": brief.operation_proof_date,
            "permit_states": await self._permit_states(
                pid, {str(m["permit_requirement_id"]) for m in milestones if m["permit_requirement_id"]}
            ),
            "activities": await self._activities(
                brief, {str(m["activity_id"]) for m in milestones if m["activity_id"]}
            ),
        }

    async def milestone_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Milestones with the gate and permit they are bound to, and whether the published activity agrees."""
        brief = await self.require_brief(project_id)
        gates = {g["code"]: g for g in await self._gates(project_id)}
        rows = [milestone_dict(m) for m in await self.repo.milestones(project_id)]
        permit = await self._permit_states(
            project_id, {str(m["permit_requirement_id"]) for m in rows if m["permit_requirement_id"]}
        )
        acts = await self._activities(brief, {str(m["activity_id"]) for m in rows if m["activity_id"]})
        findings = rules.schedule_findings(
            await self.catalogue_for(brief),
            rows,
            list(gates.values()),
            operation_proof_date=brief.operation_proof_date,
            permit_states=permit,
            activities=acts,
        )
        by_ref: dict[str, list[dict[str, str]]] = {}
        for f in findings:
            by_ref.setdefault(f.ref, []).append(f.as_dict())
        out = []
        for m in rows:
            gate = gates.get(str(m["gate_code"])) if m["gate_code"] else None
            out.append(
                {
                    **json_safe(m),
                    "gate": None
                    if gate is None
                    else {
                        "code": gate["code"],
                        "label": gate["label"],
                        "status": gate["status"],
                        "target_date": _iso(gate["target_date"]),
                        "bound_to_schedule": bool(m["activity_id"])
                        and str(gate["schedule_activity_id"] or "") == str(m["activity_id"]),
                    },
                    "permit_state": permit.get(str(m["permit_requirement_id"])) if m["permit_requirement_id"] else None,
                    "published": m["activity_id"] is not None and acts.get(str(m["activity_id"])) is not None,
                    "findings": by_ref.get(str(m["id"]), []),
                }
            )
        return out

    async def _check_milestone(
        self,
        brief: EngineeringBrief,
        catalogue: EngineeringBriefCatalogue,
        values: dict[str, Any],
        own_id: uuid.UUID | None,
    ) -> None:
        kind = catalogue.milestone_kind(values["kind_code"])
        if kind is None:
            raise EngineeringBriefError("milestone_kind_unknown", 422, detail=values["kind_code"])
        gate_code = values.get("gate_code")
        if gate_code:
            if not kind.gate:
                raise EngineeringBriefError("gate_code_on_wrong_kind", 422)
            if gate_code not in {g["code"] for g in await self._gates(brief.project_id)}:
                raise EngineeringBriefError("gate_unknown", 422, detail=gate_code)
        succ = values.get("successor_id")
        if succ is not None:
            if own_id is not None and succ == own_id:
                raise EngineeringBriefError("successor_cycle", 422)
            if await self.repo.child(FrameMilestone, brief.project_id, succ) is None:
                raise EngineeringBriefError("successor_not_found", 422)
        permit = values.get("permit_requirement_id")
        if permit is not None:
            state = (await self._permit_states(brief.project_id, {str(permit)}))[str(permit)]
            if state is None:
                raise EngineeringBriefError("permit_requirement_unknown", 422)

    async def _refuse_cycle(self, project_id: uuid.UUID) -> None:
        cyc = rules.chain_cycles([milestone_dict(m) for m in await self.repo.milestones(project_id)])
        if cyc:
            raise EngineeringBriefError("successor_cycle", 422)

    async def create_milestone(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> FrameMilestone:
        brief = await self._open_for_edit(project_id, actor_id)
        catalogue = await self.catalogue_for(brief)
        await self._check_milestone(brief, catalogue, data, None)
        existing = await self.repo.milestones(project_id)
        day = data.get("planned_date")
        if data["kind_code"] == catalogue.anchor_kind:
            if any(m.kind_code == catalogue.anchor_kind for m in existing):
                raise conflict("anchor_exists")
            day = day or brief.operation_proof_date
            brief.operation_proof_date = day
        row = FrameMilestone(
            project_id=project_id,
            brief_id=brief.id,
            code=_next_code("MS", [m.code for m in existing]),
            kind_code=data["kind_code"],
            name=data["name"],
            planned_date=day,
            lead_days=data.get("lead_days", 0),
            successor_id=data.get("successor_id"),
            gate_code=data.get("gate_code"),
            permit_requirement_id=data.get("permit_requirement_id"),
            notes=data.get("notes", ""),
            sort_order=len(existing),
        )
        await self._insert(row, "milestone_code_taken")
        await self._audit(
            actor_id, "engineering_brief_milestone", row.id, "milestone_added", metadata={"code": row.code}
        )
        return row

    async def update_milestone(
        self, project_id: uuid.UUID, milestone_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ) -> FrameMilestone:
        _refuse_nulls(changes, _MILESTONE_NULLABLE)
        brief = await self._open_for_edit(project_id, actor_id)
        row = await self._child(FrameMilestone, project_id, milestone_id, "milestone_not_found", lock=True)
        catalogue = await self.catalogue_for(brief)
        merged = {**milestone_dict(row), **changes}
        await self._check_milestone(brief, catalogue, merged, row.id)
        if changes.get("kind_code") not in (None, row.kind_code) and row.kind_code == catalogue.anchor_kind:
            raise conflict("anchor_kind_fixed")
        for key, value in changes.items():
            setattr(row, key, value)
        if row.kind_code == catalogue.anchor_kind and "planned_date" in changes:
            brief.operation_proof_date = row.planned_date
        await self.session.flush()
        await self._refuse_cycle(project_id)
        await self._audit(actor_id, "engineering_brief_milestone", row.id, "milestone_updated")
        return row

    async def delete_milestone(self, project_id: uuid.UUID, milestone_id: uuid.UUID, actor_id: Any) -> None:
        await self._open_for_edit(project_id, actor_id)
        row = await self._child(FrameMilestone, project_id, milestone_id, "milestone_not_found", lock=True)
        await self.repo.delete(row)
        await self._audit(actor_id, "engineering_brief_milestone", milestone_id, "milestone_deleted")

    async def milestones_from_catalogue(
        self, project_id: uuid.UUID, codes: list[str] | None, actor_id: Any
    ) -> list[FrameMilestone]:
        """Create the template chain of the catalogue, dated backwards from the operating proof.

        The anchor takes the brief's operating proof date, so it must be set. Dates are proposals the user
        edits: the shipped lead times are starting points, not facts about the project.
        """
        from app.modules.engineering_brief.messages import translate

        brief = await self._open_for_edit(project_id, actor_id)
        if brief.operation_proof_date is None:
            raise EngineeringBriefError("operation_proof_missing", 422)
        catalogue = await self.catalogue_for(brief)
        templates = [t for t in catalogue.milestone_templates if codes is None or t.code in codes]
        if codes:
            unknown = sorted(set(codes) - {t.code for t in catalogue.milestone_templates})
            if unknown:
                raise EngineeringBriefError("template_unknown", 422, detail=", ".join(unknown))
        existing = await self.repo.milestones(project_id)
        taken = {m.code for m in existing}
        # Template code -> row; a template already created stays and is the successor of the next ones.
        by_template: dict[str, FrameMilestone] = {m.code: m for m in existing}
        made: list[FrameMilestone] = []
        have_kind = {m.kind_code for m in existing}
        pending = list(templates)
        # Successors first, so a template's successor exists before it is created.
        order: list[Any] = []
        placed: set[str] = set()
        guard = len(pending) + 1
        while pending and guard:
            guard -= 1
            for t in list(pending):
                if t.successor is None or t.successor in placed or t.successor not in {p.code for p in pending}:
                    order.append(t)
                    placed.add(t.code)
                    pending.remove(t)
        for t in order:
            row_code = f"T-{t.code}"
            if row_code in taken or (t.kind == catalogue.anchor_kind and t.kind in have_kind):
                continue
            succ_row = by_template.get(f"T-{t.successor}") if t.successor else None
            if succ_row is None and t.successor is not None:
                # The successor is not part of this request and not created before: leave the chain open.
                succ_row = None
            row = FrameMilestone(
                project_id=project_id,
                brief_id=brief.id,
                code=row_code,
                kind_code=t.kind,
                name=label_of(t, "en") or translate(t.name_key),
                planned_date=None,
                lead_days=t.lead_days,
                successor_id=succ_row.id if succ_row is not None else None,
                sort_order=len(existing) + len(made),
            )
            if t.kind == catalogue.anchor_kind:
                row.planned_date = brief.operation_proof_date
            elif succ_row is not None and succ_row.planned_date is not None:
                row.planned_date = succ_row.planned_date - timedelta(days=t.lead_days)
            await self._insert(row, "milestone_code_taken")
            by_template[row_code] = row
            made.append(row)
        await self._audit(
            actor_id, "engineering_brief", brief.id, "milestones_from_catalogue", metadata={"count": len(made)}
        )
        return made

    async def milestones_from_gates(
        self, project_id: uuid.UUID, actor_id: Any, locale: str = "en"
    ) -> list[FrameMilestone]:
        """One gate milestone for every gate of the project that has none, dated like the gate."""
        brief = await self._open_for_edit(project_id, actor_id)
        catalogue = await self.catalogue_for(brief)
        if catalogue.gate_kind is None:
            raise EngineeringBriefError("gate_kind_missing", 422)
        existing = await self.repo.milestones(project_id)
        bound = {m.gate_code for m in existing if m.gate_code}
        made: list[FrameMilestone] = []
        for g in await self._gates(project_id):
            if g["code"] in bound:
                continue
            from app.modules.engineering_brief.messages import translate

            prefix = translate("engineering_brief.gate_milestone_prefix", locale=locale)
            # A tenant catalogue carries its own text; a shipped one an i18n key the client translates, so
            # the stored name falls back to the code and the screen shows the gate's label beside it.
            text = (g["label"] or {}).get("text") or {}
            name = (
                text.get(locale)
                or text.get("en")
                or next(iter(text.values()), None)
                or str(g["code"]).replace("_", " ")
            )
            row = FrameMilestone(
                project_id=project_id,
                brief_id=brief.id,
                code=_next_code("MS", [m.code for m in existing] + [m.code for m in made]),
                kind_code=catalogue.gate_kind,
                name=name if name.startswith(prefix) else f"{prefix} {name}".strip(),
                planned_date=g["target_date"],
                gate_code=g["code"],
                sort_order=len(existing) + len(made),
            )
            await self._insert(row, "milestone_code_taken")
            made.append(row)
        await self._audit(
            actor_id, "engineering_brief", brief.id, "milestones_from_gates", metadata={"count": len(made)}
        )
        return made

    async def backplan(self, project_id: uuid.UUID, apply: bool, actor_id: Any) -> dict[str, Any]:
        """The dates a backward plan from the operating proof gives; written only when ``apply`` is set.

        The proposal is computed by the function the application uses, so what the user confirms is what is
        written. Gate milestones keep their dates: those belong to the governance model.
        """
        brief = await self.require_brief(project_id)
        catalogue = await self.catalogue_for(brief)
        rows = await self.repo.milestones(project_id)
        changes, unreached = rules.backplan(
            [milestone_dict(m) for m in rows], anchor_kind=catalogue.anchor_kind, gate_kind=catalogue.gate_kind
        )
        if apply:
            await self._open_for_edit(project_id, actor_id)
            by_id = {str(m.id): m for m in rows}
            for ch in changes:
                if ch["changed"]:
                    by_id[ch["id"]].planned_date = date.fromisoformat(ch["to"])
            await self.session.flush()
            await self._audit(
                actor_id,
                "engineering_brief",
                brief.id,
                "schedule_backplanned",
                metadata={"moved": sum(c["changed"] for c in changes)},
            )
        return {"applied": apply, "changes": changes, "unreached": unreached}

    # ── publication into the schedule module ───────────────────────────────

    async def publish_schedule(self, project_id: uuid.UUID, actor_id: Any) -> dict[str, Any]:
        """Write the milestones as activities of a schedule and link the gate milestones to their gates.

        Idempotent: a milestone already published moves its activity, a new one creates it. The schedule is
        created on the first publication and marked as this module's own. A gate that has not been decided
        takes the milestone's activity as the owner of its date; a decided gate is left as it was.
        """
        from app.modules.engineering_brief.messages import translate
        from app.modules.project_governance.errors import GovernanceError
        from app.modules.project_governance.service import GovernanceService
        from app.modules.schedule.models import Activity, Schedule
        from app.modules.schedule.schemas import ActivityCreate, ActivityUpdate, ScheduleCreate
        from app.modules.schedule.service import ScheduleService

        brief = await self.require_brief(project_id, lock=True)
        milestones = await self.repo.milestones(project_id)
        undated = sorted(m.code for m in milestones if m.planned_date is None)
        if not milestones:
            raise EngineeringBriefError("no_milestones", 422)
        if undated:
            raise EngineeringBriefError(
                "milestone_date_missing",
                422,
                violations=[{"code": "milestone_date_missing", "ref": c} for c in undated],
            )
        svc = ScheduleService(self.session)
        schedule = await self.session.get(Schedule, brief.schedule_id) if brief.schedule_id else None
        if schedule is None or schedule.project_id != project_id:
            schedule = await svc.create_schedule(
                ScheduleCreate(
                    project_id=project_id,
                    name=translate("engineering_brief.schedule_name"),
                    description=translate("engineering_brief.schedule_description"),
                    start_date=min(m.planned_date for m in milestones).isoformat(),
                    end_date=max(m.planned_date for m in milestones).isoformat(),
                    created_by=_uid(actor_id),
                    metadata={SCHEDULE_MARK: True},
                )
            )
            brief.schedule_id = schedule.id
        created = moved = 0
        existing = {
            a.id: a
            for a in (await self.session.execute(select(Activity).where(Activity.schedule_id == schedule.id))).scalars()
        }
        for m in milestones:
            day = m.planned_date.isoformat()
            act = existing.get(m.activity_id) if m.activity_id else None
            if act is None:
                act = await svc.create_activity(
                    ActivityCreate(
                        schedule_id=schedule.id,
                        name=m.name,
                        wbs_code=m.code,
                        start_date=day,
                        end_date=day,
                        duration_days=0,
                        activity_type="milestone",
                    ),
                    actor_id=_s(_uid(actor_id)),
                )
                m.activity_id = act.id
                created += 1
            elif str(act.start_date)[:10] != day or str(act.end_date)[:10] != day or act.name != m.name:
                await svc.update_activity(
                    act.id, ActivityUpdate(name=m.name, start_date=day, end_date=day), actor_id=_s(_uid(actor_id))
                )
                moved += 1
        await self.session.flush()
        # The schedule now owns the date of every undecided gate that has a milestone.
        bound: list[str] = []
        skipped: list[str] = []
        decided: list[str] = []
        gates = {g["code"]: g for g in await self._gates(project_id)}
        for m in milestones:
            gate = gates.get(m.gate_code) if m.gate_code else None
            if gate is None or m.activity_id is None:
                continue
            if gate["schedule_activity_id"] == m.activity_id:
                continue
            if gate["status"] == "decided":
                decided.append(gate["code"])
                continue
            try:
                await GovernanceService(self.session).plan_gate(
                    project_id,
                    gate["id"],
                    changes={"schedule_activity_id": m.activity_id},
                    actor_id=_uid(actor_id),
                )
                bound.append(gate["code"])
            except GovernanceError:
                skipped.append(gate["code"])
        await self._audit(
            _uid(actor_id),
            "engineering_brief",
            brief.id,
            "schedule_published",
            metadata={"created": created, "moved": moved, "gates_bound": bound},
        )
        self._publish("schedule.published", {"project_id": str(project_id), "schedule_id": str(schedule.id)})
        return {
            "schedule_id": str(schedule.id),
            "created": created,
            "moved": moved,
            "gates_bound": bound,
            "gates_skipped": skipped,
            "gates_decided": decided,
        }

    # ── studies: site analysis and suitability, with the report in the documents module ──

    def study_dict(self, s: Study) -> dict[str, Any]:
        return json_safe(
            {
                "id": s.id,
                "code": s.code,
                "kind": s.kind,
                "title": s.title,
                "scope": s.scope,
                "author": s.author,
                "study_date": s.study_date,
                "result": s.result,
                "conclusion": s.conclusion,
                "document_id": s.document_id,
            }
        )

    async def _document(self, project_id: uuid.UUID, document_id: uuid.UUID) -> Any:
        """The document of this project; one of another project is reported as absent."""
        from app.modules.documents.models import Document

        doc = await self.session.get(Document, document_id)
        if doc is None or doc.project_id != project_id:
            raise EngineeringBriefError("document_not_found", 422)
        return doc

    async def study_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        from app.modules.documents.models import Document

        rows = await self.repo.studies(project_id)
        ids = {s.document_id for s in rows if s.document_id}
        names: dict[uuid.UUID, str] = {}
        if ids:
            found = await self.session.execute(select(Document.id, Document.name).where(Document.id.in_(ids)))
            names = dict(found.all())
        return [
            {**self.study_dict(s), "document_name": names.get(s.document_id, "") if s.document_id else ""} for s in rows
        ]

    async def create_study(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> Study:
        brief = await self.require_brief(project_id, lock=True)
        if data.get("document_id"):
            await self._document(project_id, data["document_id"])
        existing = await self.repo.studies(project_id)
        row = Study(
            project_id=project_id,
            brief_id=brief.id,
            code=_next_code("STU", [s.code for s in existing]),
            kind=data["kind"],
            title=data["title"],
            scope=data.get("scope", ""),
            author=data.get("author", ""),
            study_date=data.get("study_date"),
            result=data.get("result", ""),
            conclusion=data.get("conclusion", "open"),
            document_id=data.get("document_id"),
            sort_order=len(existing),
        )
        await self._insert(row, "study_code_taken")
        await self._audit(actor_id, "engineering_brief_study", row.id, "study_added", metadata={"code": row.code})
        return row

    async def update_study(
        self, project_id: uuid.UUID, study_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ) -> Study:
        _refuse_nulls(changes, nullable=("study_date", "document_id"))
        row = await self._child(Study, project_id, study_id, "study_not_found", lock=True)
        if changes.get("document_id"):
            await self._document(project_id, changes["document_id"])
        for key, value in changes.items():
            setattr(row, key, value)
        await self.session.flush()
        await self._audit(actor_id, "engineering_brief_study", row.id, "study_updated")
        return row

    async def delete_study(self, project_id: uuid.UUID, study_id: uuid.UUID, actor_id: Any) -> None:
        row = await self._child(Study, project_id, study_id, "study_not_found", lock=True)
        await self.repo.delete(row)
        await self._audit(actor_id, "engineering_brief_study", study_id, "study_deleted")

    # ── the issued requirements specification (Lastenheft) ──────────────────

    def issue_dict(self, i: SpecificationIssue) -> dict[str, Any]:
        return json_safe(
            {
                "id": i.id,
                "version_no": i.version_no,
                "title": i.title,
                "issued_at": i.issued_at,
                "issued_by": i.issued_by,
                "document_id": i.document_id,
                "requirements_hash": i.requirements_hash,
                "requirement_count": i.requirement_count,
                "note": i.note,
            }
        )

    async def _current_requirements_hash(self, brief: EngineeringBrief) -> tuple[str, int]:
        rows = [_requirement_dict(r) for r in await self._requirement_rows(brief)]
        return requirements_hash(rows), len(rows)

    async def issue_views(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The issues, newest first, and whether the latest one still matches the requirements."""
        brief = await self.require_brief(project_id)
        current, count = await self._current_requirements_hash(brief)
        issues = [self.issue_dict(i) for i in await self.repo.issues(project_id)]
        state, detail = rules.specification_state(issues, current)
        return {
            "items": issues,
            "current": state == "met",
            "stale": bool(issues) and state != "met",
            "requirement_count": count,
            "detail": detail,
        }

    async def issue_specification(
        self, project_id: uuid.UUID, actor_id: Any, note: str = "", locale: str = "en"
    ) -> SpecificationIssue:
        """Render the requirements brief as a PDF into the documents module and record the issue.

        Only a submitted brief can be issued, and only when the requirements changed since the last issue:
        two issues of the same content would be two versions that differ in nothing. The second and later
        issues are revisions of the first document, so the documents module keeps one chain.
        """
        from io import BytesIO

        from starlette.datastructures import UploadFile

        from app.modules.documents.service import DocumentService
        from app.modules.engineering_brief import export as ex
        from app.modules.engineering_brief.messages import translate

        brief = await self.require_brief(project_id, lock=True)
        if brief.status not in ("in_review", "approved", "binding"):
            raise conflict("brief_not_submitted")
        views = await self.requirement_views(project_id)
        if not views:
            raise EngineeringBriefError("no_requirements", 422)
        current, count = await self._current_requirements_hash(brief)
        previous = await self.repo.issues(project_id)
        if previous and previous[0].requirements_hash == current:
            raise conflict("specification_unchanged")
        version_no = (previous[0].version_no + 1) if previous else 1
        project = await self._project(project_id)
        doc = ex.requirements_document(
            views,
            catalogue=await self.catalogue_for(brief),
            project_name=getattr(project, "name", "") or "",
            locale=locale,
        )
        doc.details.append((translate("engineering_brief.export.version", locale=locale), f"{version_no}"))
        pdf = ex.render(doc, "pdf")
        base = translate("engineering_brief.specification_filename", locale=locale)
        upload = UploadFile(file=BytesIO(pdf), filename=f"{base}.pdf")
        svc = DocumentService(self.session)
        who = _s(_uid(actor_id)) or ""
        first = next((i for i in reversed(previous) if i.document_id), None)
        if first is not None:
            document = await svc.upload_document_revision(first.document_id, upload, who, notes=note or None)
        else:
            document = await svc.upload_document(project_id, upload, "specification", who)
        row = SpecificationIssue(
            project_id=project_id,
            brief_id=brief.id,
            version_no=version_no,
            title=f"{base} v{version_no}",
            issued_at=_now(),
            issued_by=_uid(actor_id),
            document_id=document.id,
            requirements_hash=current,
            requirement_count=count,
            note=note,
        )
        await self._insert(row, "specification_version_taken")
        await self._audit(
            actor_id, "engineering_brief", brief.id, "specification_issued", metadata={"version": version_no}
        )
        self._publish("specification.issued", {"project_id": str(project_id), "version": version_no})
        return row

    # ── gate readiness and validation ──────────────────────────────────────

    async def readiness(self, project_id: uuid.UUID, gate_code: str) -> dict[str, Any]:
        """What the governance gate ``gate_code`` reads of the brief."""
        brief = await self.get_brief(project_id)
        if brief is None:
            return {"in_use": False}
        gate = next((g for g in await self._gates(project_id) if g["code"] == gate_code), None)
        if gate is None:
            raise not_found("gate_not_found")
        inputs = await self._rule_inputs(brief)
        errors = [f for f in rules.submission_findings(**inputs) if f.severity == rules.ERROR]
        frame = await self._resolve_frame_document(project_id)
        studies = [self.study_dict(s) for s in await self.repo.studies(project_id)]
        issues = [self.issue_dict(i) for i in await self.repo.issues(project_id)]
        current_hash, _count = await self._current_requirements_hash(brief)
        mine = [m for m in inputs["milestones"] if m["gate_code"] == gate_code]
        return {
            "in_use": True,
            "status": brief.status,
            # Submitted or later. Approval itself is the gate decision, so it cannot be a precondition of the gate.
            "submitted": brief.status in ("in_review", "approved", "binding")
            or (brief.status == "revising" and bool(brief.bound_snapshot)),
            # The model hosts the brief but the project has no document row for it: nothing can be read.
            "frame_document_missing": frame is None,
            "frame_required": frame is not None and gate_code in frame.required_at_gates,
            "gate_milestone": bool(mine),
            "gate_dated": bool(mine) and mine[0]["planned_date"] is not None,
            "site_analysis": rules.study_state("site_analysis", studies),
            "suitability": rules.study_state("suitability", studies),
            "specification": rules.specification_state(issues, current_hash),
            "errors": [f.as_dict() for f in errors],
        }

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        """What the engineering brief rules read."""
        brief = await self.require_brief(project_id)
        inputs = await self._rule_inputs(brief)
        current = requirements_hash(inputs["requirements"])
        return {
            **inputs,
            "brief": {"status": brief.status, "operation_proof_date": brief.operation_proof_date},
            "requirements_changed": brief.bound_requirements_hash is not None
            and brief.bound_requirements_hash != current,
        }
