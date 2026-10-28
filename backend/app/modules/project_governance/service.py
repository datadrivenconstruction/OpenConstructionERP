# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project governance service: reads rows, asks the evaluator, writes the outcome.

The rules live in :mod:`evaluator` and are pure. This layer only loads what a
rule needs, locks what a decision changes, and writes the result together with
its audit trail (``log_activity`` in the same transaction), events (published
after commit, because every subscriber opens its own session) and
notifications.

Who may decide a gate is answered by the approval route of the gate
(``approval_routes``, target kind ``phase_gate``), never by a role alone:

* a pending instance at its final step: the deciders ``entitled_deciders``
  names for that step, or, for a role-based step, a caller whose role meets it;
* an instance someone already approved in the approval screen: exactly the
  user who approved its final step;
* no route configured: nobody, and the API says so.

Revisiting a decision (reopening or resuming its gate, waiving one of its
conditions, adding one) is for the decider of that decision or a user the
project's gate route entitles, never for the decide permission alone.

Concurrency: a decision locks the gate row (``SELECT ... FOR UPDATE``), the
gate carries a version column, and one decision per attempt is a unique
constraint. Whichever of two simultaneous deciders commits second finds the
gate no longer in review and gets a 409.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.project_governance import evaluator as ev
from app.modules.project_governance.catalogue import Catalogue
from app.modules.project_governance.catalogue_store import CatalogueStore, resolve_catalogue
from app.modules.project_governance.errors import GovernanceError, conflict, forbidden, not_found
from app.modules.project_governance.evidence import CollectedEvidence, GateAttempt, collect_evidence
from app.modules.project_governance.fsm import DOCUMENT_FSM, GATE_FSM
from app.modules.project_governance.models import (
    GovernanceArea,
    GovernanceChangeRequest,
    GovernanceCheck,
    GovernanceCondition,
    GovernanceDecision,
    GovernanceDocument,
    GovernanceGate,
    GovernanceModel,
)
from app.modules.project_governance.repository import GovernanceRepository

logger = logging.getLogger(__name__)

MODULE = "project_governance"
GATE_TARGET_KIND = "phase_gate"
CHANGE_TARGET_KIND = "frame_change"
_UNDECIDED = ("not_started", "in_preparation", "in_review", "on_hold")
_POSITIVE = ("go", "go_with_conditions")
_NEGATIVE = ("hold", "recycle", "stop")


def catalogue_key(source: str, catalogue_id: str, version: int) -> str:
    """The value gates store to say which pinned catalogue they belong to."""
    return f"{source}:{catalogue_id}@{version}"


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def approval_would_clear(step: Any, states: Any, entitled: Any, decider_id: Any) -> bool:
    """Whether one more approval, by ``decider_id``, clears the final step of a pending route.

    The rule is the approval engine's own (``simulate.step_cleared``), fed with
    the recorded decisions of that step plus the one the caller would add, so
    what the screen offers cannot drift from what ``decide`` then accepts.
    ``entitled`` is the engine's set of named deciders, ``None`` for a
    role-based step.
    """
    from app.modules.approval_routes.simulate import step_cleared

    mine = [s for s in states if s.step_id == step.id]
    approvers = {s.approver_user_id for s in mine if s.decision == "approved"}
    added = 0 if decider_id in approvers else 1
    approvers = approvers | {decider_id}
    return step_cleared(
        mode=step.mode,
        user_pinned=entitled is not None,
        pinned_user_approved=bool(set(entitled or ()) & approvers),
        approvals=sum(1 for s in mine if s.decision == "approved") + added,
        distinct_approvers=len(approvers),
        rejections=sum(1 for s in mine if s.decision == "rejected"),
        total_acted=sum(1 for s in mine if s.decision != "pending") + added,
        quorum=step.required_approver_count,
    )


def server_today() -> date:
    """The date every write is judged against. A client never supplies it."""
    return datetime.now(UTC).date()


def effective_condition_status(cond: GovernanceCondition, today: date) -> str:
    """What a condition is today: an open one past its due date reads overdue before any sweep ran."""
    return ev.condition_status(
        ev.ConditionState(
            id=str(cond.id),
            gate_code=cond.gate_code,
            area_code=cond.area_code,
            status=cond.status,
            due_date=_parse_day(cond.due_date),
        ),
        today,
    )


def _route_error(exc: HTTPException) -> GovernanceError:
    """An approval-route refusal in this module's error contract.

    The route engine answers with plain-text HTTP errors. Left alone they reach
    the client without a code, in a shape no governance screen can read.
    """
    info = exc.detail if isinstance(exc.detail, str) else None
    if exc.status_code == 403:
        return forbidden("decider_not_entitled", detail=info)
    return conflict("route_not_pending", detail=info)


@dataclass(frozen=True)
class _Authority:
    """What one caller may revisit on one project, read once per request."""

    actor_id: str
    route_entitled: bool
    four_eyes: bool
    areas: tuple[ev.AreaState, ...]
    deciders: dict[uuid.UUID, str]

    def over(self, decision_id: uuid.UUID | None) -> str | None:
        """Why this caller has no authority over that decision, or None."""
        decided_by = self.deciders.get(decision_id) if decision_id else None
        return ev.authority_violation(self.actor_id, decided_by=decided_by, route_entitled=self.route_entitled)


class GovernanceService:
    """Orchestrates models, gates, documents, checks, decisions and change requests."""

    # A caller that works inside a savepoint it may roll back sets a list here and
    # publishes it after the release: a deferred event survives a rolled-back
    # savepoint and would otherwise fire for rows that do not exist. Declared on
    # the class so that publishing never depends on ``__init__`` having run.
    outbox: list[tuple[str, dict[str, Any]]] | None = None

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = GovernanceRepository(session)
        self.last_evidence: list[CollectedEvidence] = []

    # ── helpers ────────────────────────────────────────────────────────────

    async def require_model(self, project_id: uuid.UUID, *, lock: bool = False) -> GovernanceModel:
        model = await self.repo.get_model(project_id, lock=lock)
        if model is None:
            raise not_found("model_missing")
        return model

    async def catalogue_for(self, model: GovernanceModel) -> Catalogue:
        return await resolve_catalogue(
            self.session, model.catalogue_source, model.catalogue_id, model.catalogue_version, from_pin=True
        )

    async def _fsm(self, fsm: Any, entity: Any, target: str, actor_id: Any, reason: str | None = None, **meta: Any):
        try:
            await fsm.apply(
                self.session,
                entity,
                target,
                actor_id=_s(actor_id),
                reason=reason,
                extra_metadata={"project_id": _s(getattr(entity, "project_id", None)), **meta},
                entity_type=fsm.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

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
        # ``name`` is the full event name: subscribers and the dead-subscription guard match the literal.
        if self.outbox is not None:
            self.outbox.append((name, data))
            return
        publish_after_commit(self.session, name, data, source_module=MODULE)

    async def _notify(self, user_id: Any, kind: str, entity_type: str, entity_id: Any, ctx: dict[str, Any]) -> None:
        """Best effort, inside a savepoint so a failure never poisons the decision."""
        if not user_id:
            return
        try:
            from app.modules.notifications.service import NotificationService

            async with self.session.begin_nested():
                await NotificationService(self.session).create(
                    user_id=user_id,
                    notification_type=f"governance_{kind}",
                    title_key=f"notifications.governance.{kind}.title",
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    body_key=f"notifications.governance.{kind}.body",
                    body_context=ctx,
                    action_url=f"/projects/{ctx.get('project_id')}/governance",
                    metadata=ctx,
                )
        except Exception:
            logger.debug("governance notification %s skipped", kind, exc_info=True)

    async def _mirror_project_phase(self, project_id: uuid.UUID, catalogue: Catalogue, phase_code: str | None) -> None:
        """``Project.phase`` is a mirror and this module is its only writer."""
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None or not phase_code:
            return
        spine = catalogue.phase(phase_code).spine_key
        if project.phase != spine:
            before = project.phase
            project.phase = spine
            await self._audit(
                None,
                "project",
                project_id,
                "phase_mirrored",
                from_status=before,
                to_status=spine,
                metadata={"governance_phase": phase_code},
            )

    async def user_can_access_project(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Owner, team member or admin: who may be named an area owner."""
        from app.core.permissions import Role
        from app.modules.approval_routes.service import _caller_role_satisfies
        from app.modules.projects.models import Project
        from app.modules.teams.access import is_project_member
        from app.modules.users.models import User

        project = await self.session.get(Project, project_id)
        if project is None:
            return False
        if project.owner_id == user_id:
            return True
        user = await self.session.get(User, user_id)
        if user is not None and _caller_role_satisfies(user.role, Role.ADMIN.value):
            return True
        return await is_project_member(self.session, project_id, user_id)

    async def _revision_facts(self, container_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str | None, str | None]]:
        """``container_id -> (current_revision_id, content_hash)`` read from CDE."""
        from app.modules.cde.models import DocumentContainer, DocumentRevision

        ids = [c for c in container_ids if c]
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(DocumentContainer.id, DocumentContainer.current_revision_id).where(DocumentContainer.id.in_(ids))
            )
        ).all()
        rev_ids = [r[1] for r in rows if r[1]]
        hashes: dict[str, str | None] = {}
        if rev_ids:
            for rid, h in (
                await self.session.execute(
                    select(DocumentRevision.id, DocumentRevision.content_hash).where(DocumentRevision.id.in_(rev_ids))
                )
            ).all():
                hashes[str(rid)] = h
        return {cid: (_s(rev), hashes.get(str(rev)) if rev else None) for cid, rev in rows}

    async def _revision_hash(self, revision_id: Any) -> str | None:
        from app.modules.cde.models import DocumentRevision

        if not revision_id:
            return None
        rev = await self.session.get(DocumentRevision, _uuid(revision_id))
        return rev.content_hash if rev is not None else None

    async def _container_in_project(self, project_id: uuid.UUID, container_id: uuid.UUID) -> bool:
        from app.modules.cde.models import DocumentContainer

        row = await self.session.get(DocumentContainer, container_id)
        return row is not None and row.project_id == project_id

    # ── context for the evaluator ──────────────────────────────────────────

    async def gate_context(
        self, model: GovernanceModel, gate: GovernanceGate, today: date
    ) -> tuple[ev.GateContext, dict[str, GovernanceArea], list[GovernanceDocument]]:
        areas = await self.repo.list_areas(model.project_id)
        by_id = {a.id: a for a in areas}
        docs = [d for d in await self.repo.list_documents(model.project_id) if d.area_id in by_id]
        facts = await self._revision_facts([d.container_id for d in docs if d.container_id])
        checks = await self.repo.list_checks(gate.id, gate.attempt_no)
        prior, _ = await self.repo.list_conditions(model.project_id)
        collected = await collect_evidence(
            self.session,
            model.project_id,
            GateAttempt(gate_id=gate.id, gate_code=gate.code, attempt_no=gate.attempt_no),
            list(areas),
        )
        ctx = ev.GateContext(
            gate_code=gate.code,
            gate_status=gate.status,
            areas=tuple(
                ev.AreaState(
                    code=a.code,
                    owner_user_id=_s(a.owner_user_id),
                    deputy_user_id=_s(a.deputy_user_id),
                    applicable=a.applicable,
                    na_rationale=a.na_rationale,
                )
                for a in areas
            ),
            documents=tuple(
                ev.DocumentState(
                    id=str(d.id),
                    area_code=by_id[d.area_id].code,
                    doc_type=d.doc_type,
                    required=gate.code in (d.required_at_gates or []),
                    status=d.status,
                    container_id=_s(d.container_id),
                    current_revision_id=facts.get(d.container_id, (None, None))[0] if d.container_id else None,
                    current_content_hash=facts.get(d.container_id, (None, None))[1] if d.container_id else None,
                    bound_revision_id=_s(d.bound_revision_id),
                    bound_content_hash=d.bound_content_hash,
                    read_only=d.read_only,
                )
                for d in docs
            ),
            checks=tuple(
                ev.CheckState(
                    area_code=by_id[c.area_id].code,
                    status=c.status,
                    confirmed_by=_s(c.confirmed_by),
                    confirmed_revisions=dict(c.confirmed_revisions or {}),
                    stale=c.stale,
                    na_rationale=c.na_rationale,
                    rag=c.rag,
                    note=c.note,
                    confirmed_at=c.confirmed_at.isoformat() if c.confirmed_at else None,
                    criteria=dict(c.criteria or {}),
                )
                for c in checks
                if c.area_id in by_id
            ),
            prior_conditions=tuple(
                ev.ConditionState(
                    id=str(c.id),
                    gate_code=c.gate_code,
                    area_code=c.area_code,
                    status="open" if c.status == "overdue" else c.status,
                    due_date=_parse_day(c.due_date),
                    severity=c.severity,
                    document_type=c.document_type,
                )
                for c in prior
                if c.gate_id != gate.id and c.status in ("open", "overdue")
            ),
            today=today,
            model_stopped=model.stopped,
            four_eyes=model.four_eyes,
            evidence=tuple(
                ev.EvidenceState(
                    area_code=e.area_code,
                    code=e.item.code,
                    state=e.item.state,
                    blocking=e.blocking,
                    provider=e.provider,
                )
                for e in collected
            ),
        )
        self.last_evidence = collected
        return ctx, {a.code: a for a in areas}, docs

    # ── model ──────────────────────────────────────────────────────────────

    async def set_model(
        self,
        project_id: uuid.UUID,
        *,
        source: str,
        catalogue_id: str,
        version: int | None,
        four_eyes: bool,
        actor_id: uuid.UUID,
        tenant_id: str | None,
    ) -> GovernanceModel:
        """Pin a catalogue on a project and build its areas, gates and documents."""
        if await self.repo.get_model(project_id) is not None:
            raise conflict("model_exists")
        pinned = await CatalogueStore(self.session).assert_pinnable(tenant_id, source, catalogue_id, version)
        catalogue = await resolve_catalogue(self.session, source, catalogue_id, pinned, tenant_id=tenant_id)
        model = await self.repo.add(
            GovernanceModel(
                project_id=project_id,
                catalogue_source=source,
                catalogue_id=catalogue_id,
                catalogue_version=pinned,
                current_phase=catalogue.first_phase.code,
                four_eyes=four_eyes,
                created_by=actor_id,
            )
        )
        await self._materialise(model, catalogue, existing_areas={}, existing_docs={})
        await self._mirror_project_phase(project_id, catalogue, model.current_phase)
        await self._audit(
            actor_id,
            "governance_model",
            model.id,
            "created",
            metadata={"catalogue": catalogue_key(source, catalogue_id, pinned)},
        )
        self._publish(
            "project_governance.model.set",
            {"project_id": str(project_id), "catalogue_id": catalogue_id, "version": pinned},
        )
        return model

    async def _materialise(
        self,
        model: GovernanceModel,
        catalogue: Catalogue,
        *,
        existing_areas: dict[str, GovernanceArea],
        existing_docs: dict[tuple[str, str], GovernanceDocument],
        historic_gates: dict[str, GovernanceGate] | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> None:
        """Build the rows of the pinned catalogue around what the project already has.

        ``historic_gates`` are the gates this very catalogue version left behind
        on an earlier visit, by code. They are revived instead of inserted
        again: they carry decisions, and ``(project, catalogue, code)`` is unique.
        """
        key = catalogue_key(model.catalogue_source, model.catalogue_id, model.catalogue_version)
        revivable = historic_gates or {}
        area_rows: dict[str, GovernanceArea] = {}
        codes = {a.code for a in catalogue.areas}
        for area in catalogue.areas:
            row = existing_areas.get(area.code)
            if row is None:
                row = await self.repo.add(
                    GovernanceArea(project_id=model.project_id, code=area.code, sort_order=area.order)
                )
            else:
                row.retired = False
                row.sort_order = area.order
            area_rows[area.code] = row
        for code, row in existing_areas.items():
            if code not in codes:
                row.retired = True
        order = {p.code: p.order for p in catalogue.phases}
        for gate in sorted(catalogue.gates, key=lambda g: order.get(g.from_phase, 0)):
            kept = revivable.get(gate.code)
            if kept is not None:
                kept.historic = False
                kept.from_phase = gate.from_phase
                kept.to_phase = gate.to_phase
                kept.sort_order = order.get(gate.from_phase, 0)
                continue
            await self.repo.add(
                GovernanceGate(
                    project_id=model.project_id,
                    catalogue_id=key,
                    code=gate.code,
                    from_phase=gate.from_phase,
                    to_phase=gate.to_phase,
                    sort_order=order.get(gate.from_phase, 0),
                )
            )
        seen: set[tuple[str, str]] = set()
        for dt in catalogue.document_types:
            area_row = area_rows.get(dt.area)
            if area_row is None:
                continue
            seen.add((dt.area, dt.code))
            doc = existing_docs.get((dt.area, dt.code))
            if doc is None:
                await self.repo.add(
                    GovernanceDocument(
                        project_id=model.project_id,
                        area_id=area_row.id,
                        doc_type=dt.code,
                        required_at_gates=list(dt.required_at_gates),
                    )
                )
            else:
                doc.required_at_gates = list(dt.required_at_gates)
                if doc.status == "superseded":
                    # The model has this document type again: its bound revision is in force again.
                    await self._fsm(DOCUMENT_FSM, doc, "binding", actor_id, reason="document type back in the model")
        for k, doc in existing_docs.items():
            if k not in seen:
                doc.required_at_gates = []
                if doc.status == "binding":
                    # Out of the frame of the pinned model; the bound revision stays on record.
                    await self._fsm(DOCUMENT_FSM, doc, "superseded", actor_id, reason="document type left the model")
        await self.session.flush()

    async def change_model(
        self,
        project_id: uuid.UUID,
        *,
        source: str,
        catalogue_id: str,
        version: int | None,
        mapping: dict[str, str],
        actor_id: uuid.UUID,
        tenant_id: str | None,
    ) -> GovernanceModel:
        """Move a project to another catalogue (or version) with an explicit phase mapping."""
        model = await self.require_model(project_id, lock=True)
        pinned = await CatalogueStore(self.session).assert_pinnable(tenant_id, source, catalogue_id, version)
        if (source, catalogue_id, pinned) == (model.catalogue_source, model.catalogue_id, model.catalogue_version):
            raise conflict("model_unchanged")
        new = await resolve_catalogue(self.session, source, catalogue_id, pinned, tenant_id=tenant_id)
        every_gate = await self.repo.list_gates(project_id, include_historic=True)
        gates = [g for g in every_gate if not g.historic]
        new_key = catalogue_key(source, catalogue_id, pinned)
        returning = {g.code: g for g in every_gate if g.historic and g.catalogue_id == new_key}
        counts = await self.repo.decision_counts(project_id)
        violations = ev.validate_phase_mapping(
            new_phase_codes=[p.code for p in new.phases],
            mapping=mapping,
            current_phase=model.current_phase,
            phases_with_decisions=[g.from_phase for g in gates if counts.get(g.id)],
        )
        if violations:
            raise GovernanceError("phase_mapping_missing", 422, violations=[v.as_dict() for v in violations])
        kept = ev.gates_kept_on_model_change({str(g.id): counts.get(g.id, 0) for g in gates})
        for gate in gates:
            # A review on a gate that leaves the model has nothing left to decide.
            await self._withdraw_review(gate, actor_id, reason="governance model changed")
            if str(gate.id) in kept:
                gate.historic = True
            else:
                await self.repo.delete(gate)
        await self.session.flush()
        before = catalogue_key(model.catalogue_source, model.catalogue_id, model.catalogue_version)
        old_phase = model.current_phase
        model.catalogue_source = source
        model.catalogue_id = catalogue_id
        model.catalogue_version = pinned
        model.current_phase = mapping.get(old_phase or "", new.first_phase.code)
        areas = {a.code: a for a in await self.repo.list_areas(project_id, include_retired=True)}
        by_id = {a.id: a for a in areas.values()}
        docs = {(by_id[d.area_id].code, d.doc_type): d for d in await self.repo.list_documents(project_id)}
        await self._materialise(
            model, new, existing_areas=areas, existing_docs=docs, historic_gates=returning, actor_id=actor_id
        )
        await self._mirror_project_phase(project_id, new, model.current_phase)
        await self._audit(
            actor_id,
            "governance_model",
            model.id,
            "catalogue_changed",
            from_status=before,
            to_status=catalogue_key(source, catalogue_id, pinned),
            metadata={"mapping": mapping, "kept_gates": sorted(kept)},
        )
        self._publish("project_governance.model.changed", {"project_id": str(project_id), "mapping": mapping})
        return model

    async def update_settings(
        self,
        project_id: uuid.UUID,
        *,
        four_eyes: bool | None,
        decision_route_id: uuid.UUID | None,
        change_route_id: uuid.UUID | None,
        fields_set: set[str],
        actor_id: uuid.UUID,
    ) -> GovernanceModel:
        model = await self.require_model(project_id, lock=True)

        def _state() -> dict[str, Any]:
            return {
                "four_eyes": model.four_eyes,
                "decision_route_id": _s(model.decision_route_id),
                "change_route_id": _s(model.change_route_id),
            }

        before = _state()
        if "four_eyes" in fields_set and four_eyes is None:
            raise GovernanceError("null_not_allowed", 422)
        if four_eyes is not None and four_eyes != model.four_eyes:
            await self._refuse_while_under_decision(project_id)
            model.four_eyes = four_eyes
        for field, kind, value in (
            ("decision_route_id", GATE_TARGET_KIND, decision_route_id),
            ("change_route_id", CHANGE_TARGET_KIND, change_route_id),
        ):
            if field not in fields_set:
                continue
            if value is not None and await self._pinnable_route(project_id, kind, value) is None:
                raise GovernanceError("route_not_pinnable", 422)
            setattr(model, field, value)
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_model",
            model.id,
            "settings_changed",
            before_state=before,
            after_state=_state(),
        )
        return model

    async def _refuse_while_under_decision(self, project_id: uuid.UUID) -> None:
        """409 while any gate of the project is in review or on hold."""
        code = ev.settings_freeze_violation(g.status for g in await self.repo.list_gates(project_id))
        if code:
            raise conflict(code)

    # ── areas ──────────────────────────────────────────────────────────────

    async def update_area(
        self,
        project_id: uuid.UUID,
        area_id: uuid.UUID,
        *,
        changes: dict[str, Any],
        actor_id: uuid.UUID,
    ) -> GovernanceArea:
        """Owner, deputy, applicability and name override; owner change resets readiness."""
        await self.require_model(project_id)
        area = await self.repo.get_area(project_id, area_id)
        if area is None:
            raise not_found("area_not_found")
        before = {
            "owner_user_id": _s(area.owner_user_id),
            "deputy_user_id": _s(area.deputy_user_id),
            "applicable": area.applicable,
        }
        for field in ("applicable", "na_rationale", "name_override"):
            if field in changes and changes[field] is None:
                # These columns hold no null; a name override is cleared with an empty string.
                raise GovernanceError("null_not_allowed", 422)
        if "applicable" in changes and changes["applicable"] != area.applicable:
            # Taking an area out of a gate that is being decided would remove its blockers unseen.
            await self._refuse_while_under_decision(project_id)
        for field in ("owner_user_id", "deputy_user_id"):
            if field in changes and changes[field] is not None:
                if not await self.user_can_access_project(project_id, changes[field]):
                    raise GovernanceError("owner_not_project_member", 422)
        if changes.get("applicable") is False:
            reason = changes.get("na_rationale", area.na_rationale)
            code = ev.not_applicable_violation(reason)
            if code:
                raise GovernanceError(code, 422)
        owner_changed = "owner_user_id" in changes and changes["owner_user_id"] != area.owner_user_id
        for field in ("owner_user_id", "deputy_user_id", "applicable", "na_rationale", "name_override"):
            if field in changes:
                setattr(area, field, changes[field] if changes[field] is not None or "user_id" in field else "")
        if owner_changed:
            for check in await self.repo.list_open_checks_for_area(project_id, area.id):
                await self._audit(
                    actor_id,
                    "governance_check",
                    check.id,
                    "reset_on_owner_change",
                    from_status=check.status,
                    to_status="not_assessed",
                    before_state={"confirmed_by": _s(check.confirmed_by), "status": check.status},
                )
                check.status = "not_assessed"
                check.confirmed_by = None
                check.confirmed_at = None
                check.confirmed_revisions = {}
                check.stale = False
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_area",
            area.id,
            "updated",
            before_state=before,
            after_state={k: _s(v) if "user_id" in k else v for k, v in changes.items()},
        )
        if owner_changed:
            await self._notify(
                area.owner_user_id,
                "area_owner",
                "governance_area",
                area.id,
                {"project_id": str(project_id), "area": area.code},
            )
        return area

    # ── gates ──────────────────────────────────────────────────────────────

    async def _pinnable_route(self, project_id: uuid.UUID, kind: str, route_id: uuid.UUID) -> Any:
        """The route, when it is an active route of this project for ``kind``; else ``None``.

        A route without a project is visible to every project and anyone who
        may configure routes can create one, so it must never decide a gate:
        only a route that belongs to the project qualifies.
        """
        from app.modules.approval_routes.models import Route

        route = await self.session.get(Route, route_id)
        if route is None or not route.is_active or route.target_kind != kind or route.project_id != project_id:
            return None
        return route

    async def _resolve_route(self, model: GovernanceModel, kind: str) -> Any:
        """The route pinned on the model for ``kind``, or ``None``.

        Nothing is looked up by project or kind: who decides a gate is a
        setting a governance manager made (``update_settings``), never the
        newest route somebody happened to create. The pin is checked again
        here because a route can be deactivated after it was pinned.
        """
        pinned = model.decision_route_id if kind == GATE_TARGET_KIND else model.change_route_id
        if pinned is None:
            return None
        return await self._pinnable_route(model.project_id, kind, pinned)

    async def _withdraw_review(self, gate: GovernanceGate, actor_id: uuid.UUID | None, *, reason: str) -> None:
        """Take a gate out of review: cancel its pending route instance, back to preparation."""
        from app.modules.approval_routes.service import ApprovalRouteService

        if gate.approval_instance_id is not None:
            routes = ApprovalRouteService(self.session)
            try:
                instance = await routes.get_instance(gate.approval_instance_id)
                if instance.status == "pending":
                    await routes.cancel_instance(instance.id, actor_id=actor_id, reason=reason)
            except HTTPException:
                logger.debug("governance: no pending route instance to cancel for gate %s", gate.id, exc_info=True)
            gate.approval_instance_id = None
        if gate.status == "in_review":
            await self._fsm(GATE_FSM, gate, "in_preparation", actor_id, reason=reason)

    async def _route_entitled(self, model: GovernanceModel, actor_id: uuid.UUID, role: str | None) -> bool:
        """Whether the final step of the project's gate route names this caller.

        Asked when no instance is running (the gate is decided or on hold), so
        the answer comes from the route as configured: the named approver or an
        active delegate of theirs, or for a role-based step a caller whose role
        meets it.
        """
        from app.modules.approval_routes.service import ApprovalRouteService, _caller_role_satisfies

        route = await self._resolve_route(model, GATE_TARGET_KIND)
        if route is None:
            return False
        svc = ApprovalRouteService(self.session)
        steps = sorted(await svc.list_steps(route.id), key=lambda s: s.ordinal)
        if not steps:
            return False
        final = steps[-1]
        # ``entitled_deciders`` reads two fields of an instance; there is none here.
        template = SimpleNamespace(current_assignee_user_id=None, route_id=route.id)
        entitled = await svc.entitled_deciders(template, final, now=datetime.now(UTC))  # type: ignore[arg-type]
        if entitled is None:
            return bool(final.approver_role) and _caller_role_satisfies(role, final.approver_role or "")
        return actor_id in entitled

    async def _authority(self, model: GovernanceModel, actor_id: uuid.UUID, role: str | None) -> _Authority:
        areas = await self.repo.list_areas(model.project_id)
        return _Authority(
            actor_id=str(actor_id),
            route_entitled=await self._route_entitled(model, actor_id, role),
            four_eyes=model.four_eyes,
            areas=tuple(
                ev.AreaState(
                    code=a.code,
                    owner_user_id=_s(a.owner_user_id),
                    deputy_user_id=_s(a.deputy_user_id),
                    applicable=a.applicable,
                )
                for a in areas
            ),
            deciders={d.id: str(d.decided_by) for d in await self.repo.list_decisions(model.project_id)},
        )

    async def _ensure_checks(self, gate: GovernanceGate, areas: list[GovernanceArea]) -> None:
        have = {c.area_id for c in await self.repo.list_checks(gate.id, gate.attempt_no)}
        for area in areas:
            if area.id not in have:
                self.session.add(
                    GovernanceCheck(
                        project_id=gate.project_id, gate_id=gate.id, attempt_no=gate.attempt_no, area_id=area.id
                    )
                )
        await self.session.flush()

    async def get_gate(self, project_id: uuid.UUID, gate_id: uuid.UUID, *, lock: bool = False) -> GovernanceGate:
        gate = await self.repo.get_gate(project_id, gate_id, lock=lock)
        if gate is None:
            raise not_found("gate_not_found")
        return gate

    async def submit_gate(self, project_id: uuid.UUID, gate_id: uuid.UUID, *, actor_id: uuid.UUID) -> GovernanceGate:
        """Start the gate's review: an approval route instance against the gate."""
        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        if model.stopped:
            raise conflict("project_stopped")
        if gate.historic or gate.status not in ("not_started", "in_preparation"):
            raise conflict("invalid_transition")
        if model.current_phase != gate.from_phase:
            raise conflict("gate_out_of_order")
        route = await self._resolve_route(model, GATE_TARGET_KIND)
        if route is None:
            raise GovernanceError("no_decision_route", 422)
        if gate.status == "not_started":
            await self._fsm(GATE_FSM, gate, "in_preparation", actor_id)
        await self._ensure_checks(gate, await self.repo.list_areas(project_id))
        try:
            instance = await ApprovalRouteService(self.session).start_instance(
                InstanceCreate(route_id=route.id, target_kind=GATE_TARGET_KIND, target_id=gate.id),
                started_by=actor_id,
            )
        except HTTPException as exc:
            raise _route_error(exc) from exc
        gate.approval_instance_id = instance.id
        await self._fsm(GATE_FSM, gate, "in_review", actor_id, attempt_no=gate.attempt_no)
        self._publish("project_governance.gate.submitted", {"project_id": str(project_id), "gate_id": str(gate.id)})
        return gate

    async def start_preparation(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> GovernanceGate:
        """Open the first attempt of a gate nobody has touched yet.

        Only from ``not_started``. The machine also allows ``in_preparation``
        from a review, a hold and a decision, but those moves belong to a route
        rejection, :meth:`resume` and :meth:`reopen`, each with its own guard.
        """
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        code = ev.preparation_violation(gate.status, historic=gate.historic, model_stopped=model.stopped)
        if code:
            raise conflict(code)
        await self._fsm(GATE_FSM, gate, "in_preparation", actor_id)
        await self._ensure_checks(gate, await self.repo.list_areas(project_id))
        return gate

    async def _entitlement(
        self, gate: GovernanceGate, outcome: str, decider_id: uuid.UUID, role: str | None
    ) -> tuple[Any, Any, str | None]:
        """Return ``(instance, final_step, violation_code)`` for this decider."""
        from app.modules.approval_routes.service import ApprovalRouteService, _caller_role_satisfies

        if gate.approval_instance_id is None:
            raise GovernanceError("no_decision_route", 422)
        svc = ApprovalRouteService(self.session)
        try:
            instance = await svc.get_instance(gate.approval_instance_id)
        except HTTPException as exc:
            raise _route_error(exc) from exc
        steps = sorted(await svc.list_steps(instance.route_id), key=lambda s: s.ordinal)
        if not steps:
            raise GovernanceError("no_decision_route", 422)
        final = steps[-1]
        if instance.status == "pending":
            if instance.current_step_ordinal != final.ordinal:
                raise conflict("route_not_at_final_step")
            entitled = await svc.entitled_deciders(instance, final, now=datetime.now(UTC))
            ids = frozenset(str(u) for u in entitled) if entitled is not None else None
            role_ok = bool(final.approver_role) and _caller_role_satisfies(role, final.approver_role or "")
        elif instance.status == "approved":
            if outcome not in ("go", "go_with_conditions"):
                raise conflict("route_not_pending")
            states = await svc.list_step_states(instance.id)
            ids = frozenset(
                str(s.approver_user_id) for s in states if s.step_id == final.id and s.decision == "approved"
            )
            role_ok = False
        else:
            raise conflict("route_not_pending")
        return instance, final, ev.entitlement_violation(str(decider_id), entitled_user_ids=ids, role_satisfies=role_ok)

    async def _admit_actor(
        self, model: GovernanceModel, gate: GovernanceGate, *, outcome: str, decider_id: uuid.UUID, role: str | None
    ) -> tuple[Any, Any]:
        """Whether this caller may record this outcome now: gate state, phase, route entitlement.

        Nothing here looks at what the decision says. Four-eyes and the content
        rules need the gate context and follow in :meth:`_admit_decision`.
        """
        if gate.historic:
            raise conflict("gate_historic")
        if gate.status != "in_review":
            existing = [
                d for d in await self.repo.list_decisions(model.project_id, gate.id) if d.attempt_no == gate.attempt_no
            ]
            raise conflict("concurrent_decision" if existing or gate.status == "decided" else "gate_not_in_review")
        if model.current_phase != gate.from_phase:
            # A reopened earlier gate took the phase back; this gate waits for it.
            raise conflict("gate_out_of_order")
        instance, final_step, entitlement = await self._entitlement(gate, outcome, decider_id, role)
        if entitlement:
            raise forbidden(entitlement)
        return instance, final_step

    async def _admit_decision(
        self,
        model: GovernanceModel,
        gate: GovernanceGate,
        *,
        request: ev.DecisionRequest,
        decider_id: uuid.UUID,
        role: str | None,
        today: date,
    ) -> tuple[Any, Any, ev.GateContext, dict[str, GovernanceArea], list[GovernanceDocument]]:
        """Every check that refuses a decision, in the order ``decide`` applies them.

        :meth:`decide_capability` runs the same two halves, so what the screen
        offers cannot drift from what the endpoint accepts.
        """
        instance, final_step = await self._admit_actor(
            model, gate, outcome=request.outcome, decider_id=decider_id, role=role
        )
        ctx, areas, docs = await self.gate_context(model, gate, today)
        violations = ev.validate_decision(ctx, request)
        if violations:
            code, status = ev.decision_refusal(violations)
            raise GovernanceError(code, status, violations=[v.as_dict() for v in violations])
        return instance, final_step, ctx, areas, docs

    async def _one_approval_clears(self, instance: Any, final_step: Any, decider_id: uuid.UUID) -> bool:
        """Whether this caller's approval would complete the pending route of a gate."""
        if instance.status != "pending":
            return True
        from app.modules.approval_routes.service import ApprovalRouteService

        svc = ApprovalRouteService(self.session)
        entitled = await svc.entitled_deciders(instance, final_step, now=datetime.now(UTC))
        return approval_would_clear(final_step, await svc.list_step_states(instance.id), entitled, decider_id)

    async def decide_capability(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, *, decider_id: uuid.UUID, role: str | None, today: date
    ) -> dict[str, Any]:
        """What this caller could decide on the gate now. Nothing is written.

        ``outcomes`` answers per outcome whether the caller may record it:
        gate state, phase, route entitlement and four-eyes, the checks
        :meth:`decide` applies before it reads the decision's content. The two
        outcome classes differ once somebody approved the route in the approval
        screen: the instance is then approved, a go is still the final
        approver's to record, and hold, recycle and stop are no longer open.

        ``decide`` is true when at least one outcome is open; ``go`` also needs
        every readiness blocker gone, as a plain go would.
        """
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id)
        ctx: ev.GateContext | None = None
        outcomes: dict[str, dict[str, Any]] = {}
        for members in (_POSITIVE, _NEGATIVE):
            reason: str | None = None
            try:
                instance, final_step = await self._admit_actor(
                    model, gate, outcome=members[-1], decider_id=decider_id, role=role
                )
                if ctx is None:
                    ctx, _, _ = await self.gate_context(model, gate, today)
                if ev.four_eyes_violation(ctx, str(decider_id)):
                    reason = "decider_is_area_owner"
                elif members is _POSITIVE and not await self._one_approval_clears(instance, final_step, decider_id):
                    # A role step in mode all or majority: decide would answer 409 after this approval.
                    reason = "route_needs_more_approvals"
            except GovernanceError as exc:
                reason = exc.code
            for outcome in members:
                outcomes[outcome] = {"allowed": reason is None, "reason": reason}
        out: dict[str, Any] = {"outcomes": outcomes, "decide": any(o["allowed"] for o in outcomes.values())}
        if not out["decide"]:
            out["decide_reason"] = outcomes["stop"]["reason"]
        go_reason = outcomes["go"]["reason"]
        # What a go has to name. It is content of the request, as a rationale is, and not a
        # reason the go is closed, so the probe below names all of it.
        pending = ev.evidence_to_acknowledge(ctx) if ctx is not None else []
        out["acknowledge"] = [
            {"area_code": e.area_code, "code": e.code, "provider": e.provider, "state": e.state} for e in pending
        ]
        if go_reason is None and ctx is not None:
            probe = ev.DecisionRequest(
                outcome="go",
                rationale="",
                decider_id=str(decider_id),
                acknowledged_evidence=tuple((e.area_code, e.code) for e in pending),
            )
            violations = ev.validate_decision(ctx, probe)
            go_reason = ev.decision_refusal(violations)[0] if violations else None
        out["go"] = go_reason is None
        if go_reason is not None:
            out["go_reason"] = go_reason
        return out

    async def unknown_evidence(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, *, today: date
    ) -> tuple[tuple[str, str], ...]:
        """``(area_code, code)`` of the unknown evidence a go on this gate has to name now.

        For a caller that decides without a screen, such as the demo seed: it
        reads the list the dialog shows and hands it to :meth:`decide`.
        """
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id)
        ctx, _, _ = await self.gate_context(model, gate, today)
        return tuple((e.area_code, e.code) for e in ev.evidence_to_acknowledge(ctx))

    async def gate_capability(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, *, actor_id: uuid.UUID, role: str | None
    ) -> dict[str, Any]:
        """Whether this caller could resume, reopen or add a condition to the gate now."""
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id)
        authority = await self._authority(model, actor_id, role)
        out: dict[str, Any] = {}
        for key, refusal in (
            ("resume", await self._resume_refusal(model, gate, authority)),
            ("reopen", await self._reopen_refusal(model, gate, "probe", authority)),
            ("add_condition", (await self._add_condition_target(gate, authority))[1]),
        ):
            out[key] = refusal is None
            if refusal is not None:
                out[f"{key}_reason"] = refusal.code
        return out

    async def matrix(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """Areas x gates of the current attempts, plus the next gate and its blocker count.

        A fixed set of queries whatever the number of areas, gates or documents.
        """
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        gates = await self.repo.list_gates(project_id)
        area_rows = await self.repo.list_areas(project_id)
        docs = await self.repo.list_documents(project_id)
        checks = {(c.gate_id, c.area_id): c for c in await self.repo.list_current_checks(project_id)}
        next_gate = next((g for g in gates if g.status != "decided"), None)
        blocker_count = 0
        if next_gate is not None:
            ctx, _, _ = await self.gate_context(model, next_gate, today)
            blocker_count = len(ev.gate_blockers(ctx))
        return {
            "catalogue": catalogue,
            "gates": gates,
            "next_gate": next_gate,
            "blocker_count": blocker_count,
            "areas": [
                {
                    "area": a,
                    "cells": {
                        g.code: {
                            "check_status": checks[(g.id, a.id)].status if (g.id, a.id) in checks else None,
                            "rag": checks[(g.id, a.id)].rag if (g.id, a.id) in checks else "",
                            "stale": checks[(g.id, a.id)].stale if (g.id, a.id) in checks else False,
                            "documents": [
                                {"document_id": str(d.id), "doc_type": d.doc_type, "status": d.status, "required": True}
                                for d in docs
                                if d.area_id == a.id and g.code in (d.required_at_gates or [])
                            ],
                        }
                        for g in gates
                    },
                }
                for a in area_rows
            ],
        }

    async def decide(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        *,
        request: ev.DecisionRequest,
        decider_id: uuid.UUID,
        role: str | None,
        today: date,
    ) -> GovernanceDecision:
        """Record an immutable decision on the gate's current attempt."""
        from app.modules.approval_routes.schemas import DecisionSubmit
        from app.modules.approval_routes.service import ApprovalRouteService

        model = await self.require_model(project_id, lock=True)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        instance, final_step, ctx, areas, docs = await self._admit_decision(
            model, gate, request=request, decider_id=decider_id, role=role, today=today
        )
        # Before anything is written: a refusal must leave no decision behind.
        for cond in request.conditions:
            await self._require_condition_owner(project_id, cond.owner_user_id)

        effects = ev.decision_effects(request.outcome)
        now = datetime.now(UTC)
        decision = GovernanceDecision(
            project_id=project_id,
            gate_id=gate.id,
            gate_code=gate.code,
            attempt_no=gate.attempt_no,
            outcome=request.outcome,
            rationale=request.rationale or "",
            decided_by=decider_id,
            decided_at=now,
            snapshot=ev.build_snapshot(ctx, request),
            proceed_at_risk_areas=list(request.proceed_at_risk_areas),
            accepted_not_applicable=list(request.accepted_not_applicable),
            hold_resume_date=request.hold_resume_date.isoformat() if request.hold_resume_date else "",
            approval_instance_id=instance.id,
        )
        self.session.add(decision)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise conflict("concurrent_decision") from exc

        for cond in request.conditions:
            self.session.add(
                GovernanceCondition(
                    project_id=project_id,
                    decision_id=decision.id,
                    gate_id=gate.id,
                    gate_code=gate.code,
                    area_code=cond.area_code,
                    document_type=cond.document_type,
                    text=cond.text.strip(),
                    owner_user_id=_uuid(cond.owner_user_id),
                    due_date=cond.due_date.isoformat() if cond.due_date else "",
                    severity=cond.severity,
                )
            )

        # Route: close the instance in the same transaction, as the decider.
        routes = ApprovalRouteService(self.session)
        if instance.status == "pending":
            try:
                if effects.route_action in ("approved", "rejected"):
                    after = await routes.submit_decision(
                        instance.id,
                        DecisionSubmit(
                            step_id=final_step.id,
                            decision=effects.route_action,
                            comment=request.rationale[:2000] or None,
                        ),
                        approver_id=decider_id,
                        caller_role=role,
                    )
                    if effects.route_action == "approved" and after.status == "pending":
                        # A role-based final step in mode all or majority is not cleared by one
                        # approval. Recording the gate as decided here would leave the instance
                        # pending for good; the caller rolls the request back instead.
                        raise conflict("route_needs_more_approvals")
                elif effects.route_action == "cancel":
                    await routes.cancel_instance(instance.id, actor_id=decider_id, reason=request.rationale)
            except HTTPException as exc:
                raise _route_error(exc) from exc

        catalogue = await self.catalogue_for(model)
        if effects.approve_documents:
            for doc in docs:
                if gate.code in (doc.required_at_gates or []) and doc.status == "in_review" and doc.container_id:
                    facts = (await self._revision_facts([doc.container_id])).get(doc.container_id, (None, None))
                    doc.bound_revision_id = _uuid(facts[0])
                    doc.bound_content_hash = facts[1]
                    doc.approved_gate_id = gate.id
                    await self._fsm(DOCUMENT_FSM, doc, "approved_at_gate", decider_id, gate_id=str(gate.id))
                    await self._fsm(DOCUMENT_FSM, doc, "binding", decider_id, gate_id=str(gate.id))
                    self._publish(
                        "project_governance.frame_document.state_changed",
                        {"project_id": str(project_id), "document_id": str(doc.id), "status": "binding"},
                    )
        if effects.advance_phase:
            before = model.current_phase
            model.current_phase = gate.to_phase
            await self._mirror_project_phase(project_id, catalogue, gate.to_phase)
            self._publish(
                "project_governance.phase.changed",
                {"project_id": str(project_id), "from_phase": before, "to_phase": gate.to_phase},
            )
        if effects.stop_project:
            model.stopped = True
            model.stopped_at = now
            frozen = set(ev.documents_to_freeze(ctx.documents))
            for doc in docs:
                if str(doc.id) in frozen:
                    doc.read_only = True

        gate.last_outcome = request.outcome
        gate.hold_resume_date = decision.hold_resume_date
        if effects.new_attempt:
            await self._fsm(
                GATE_FSM, gate, effects.next_gate_status, decider_id, reason=request.rationale, outcome=request.outcome
            )
            await self._next_attempt(gate, carry_stale=effects.mark_checks_stale)
        else:
            await self._fsm(
                GATE_FSM, gate, effects.next_gate_status, decider_id, reason=request.rationale, outcome=request.outcome
            )
        await self.session.flush()
        await self._audit(
            decider_id,
            "governance_decision",
            decision.id,
            "decided",
            to_status=request.outcome,
            reason=request.rationale,
            parent_entity_type="governance_gate",
            parent_entity_id=gate.id,
            metadata={"attempt_no": decision.attempt_no, "proceed_at_risk_areas": list(request.proceed_at_risk_areas)},
        )
        self._publish(
            "project_governance.gate.decided",
            {
                "project_id": str(project_id),
                "gate_id": str(gate.id),
                "decision_id": str(decision.id),
                "outcome": request.outcome,
                "attempt_no": decision.attempt_no,
            },
        )
        for cond in request.conditions:
            await self._notify(
                cond.owner_user_id,
                "condition_assigned",
                "governance_gate",
                gate.id,
                {"project_id": str(project_id), "gate": gate.code},
            )
        return decision

    async def _next_attempt(self, gate: GovernanceGate, *, carry_stale: bool) -> None:
        old = await self.repo.list_checks(gate.id, gate.attempt_no)
        gate.attempt_no = ev.next_attempt_number(gate.attempt_no)
        gate.approval_instance_id = None
        for c in old:
            self.session.add(
                GovernanceCheck(
                    project_id=c.project_id,
                    gate_id=c.gate_id,
                    attempt_no=gate.attempt_no,
                    area_id=c.area_id,
                    status=c.status,
                    rag=c.rag,
                    note=c.note,
                    confirmed_by=c.confirmed_by,
                    confirmed_at=c.confirmed_at,
                    confirmed_revisions=dict(c.confirmed_revisions or {}),
                    stale=True if carry_stale else c.stale,
                    na_rationale=c.na_rationale,
                    criteria=dict(c.criteria or {}),
                )
            )
        await self.session.flush()

    async def _latest_decision_id(self, gate: GovernanceGate) -> uuid.UUID | None:
        decisions = await self.repo.list_decisions(gate.project_id, gate.id)
        return decisions[-1].id if decisions else None

    async def _reopen_refusal(
        self, model: GovernanceModel, gate: GovernanceGate, rationale: str, authority: _Authority
    ) -> GovernanceError | None:
        later = [
            g.status
            for g in await self.repo.list_gates(model.project_id)
            if g.id != gate.id and g.sort_order > gate.sort_order
        ]
        code = ev.reopen_violation(gate.status, rationale, historic=gate.historic, later_gate_statuses=later)
        if code:
            return GovernanceError(code, 422 if code == "rationale_required" else 409)
        code = authority.over(await self._latest_decision_id(gate))
        return forbidden(code) if code else None

    async def _resume_refusal(
        self, model: GovernanceModel, gate: GovernanceGate, authority: _Authority
    ) -> GovernanceError | None:
        code = ev.resume_violation(gate.status, historic=gate.historic, model_stopped=model.stopped)
        if code:
            return conflict(code)
        code = authority.over(await self._latest_decision_id(gate))
        return forbidden(code) if code else None

    async def reopen(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        *,
        rationale: str,
        actor_id: uuid.UUID,
        role: str | None = None,
    ) -> GovernanceGate:
        """Start attempt n+1 of a decided gate; the earlier decision stays as recorded.

        A gate whose decision advanced the phase takes the phase back with it,
        otherwise the reopened gate could never be submitted again. That is
        also why no later gate may have been started: it would sit ahead of
        the phase and could be decided past the reopened one.
        """
        model = await self.require_model(project_id, lock=True)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        refusal = await self._reopen_refusal(model, gate, rationale, await self._authority(model, actor_id, role))
        if refusal is not None:
            raise refusal
        if gate.last_outcome == "stop":
            model.stopped = False
            model.stopped_at = None
            for doc in await self.repo.list_documents(project_id):
                doc.read_only = False
        if ev.reopen_rewinds_phase(gate.last_outcome):
            before = model.current_phase
            model.current_phase = gate.from_phase
            await self._mirror_project_phase(project_id, await self.catalogue_for(model), gate.from_phase)
            self._publish(
                "project_governance.phase.changed",
                {"project_id": str(project_id), "from_phase": before, "to_phase": gate.from_phase},
            )
        await self._fsm(GATE_FSM, gate, "in_preparation", actor_id, reason=rationale, reopened=True)
        await self._next_attempt(gate, carry_stale=True)
        self._publish(
            "project_governance.gate.reopened",
            {"project_id": str(project_id), "gate_id": str(gate.id), "attempt_no": gate.attempt_no},
        )
        return gate

    async def resume(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, *, actor_id: uuid.UUID, role: str | None = None
    ) -> GovernanceGate:
        """A held gate continues as a new attempt in preparation."""
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        refusal = await self._resume_refusal(model, gate, await self._authority(model, actor_id, role))
        if refusal is not None:
            raise refusal
        await self._fsm(GATE_FSM, gate, "in_preparation", actor_id, resumed=True)
        await self._next_attempt(gate, carry_stale=False)
        return gate

    async def apply_gate_route_rejection(self, gate_id: uuid.UUID, instance_id: uuid.UUID) -> bool:
        """Route rejected outside a decision: the review goes back to preparation.

        Locks the gate and acts only when it is still in review on exactly this
        instance, so a stop or recycle decided through :meth:`decide` (which
        also rejects the instance) is never overwritten.
        """
        gate = await self.repo.get_gate_by_id(gate_id, lock=True)
        if gate is None or gate.status != "in_review" or gate.approval_instance_id != instance_id:
            return False
        await self._fsm(GATE_FSM, gate, "in_preparation", None, reason="approval route rejected")
        gate.approval_instance_id = None
        await self.session.flush()
        return True

    # ── planning ───────────────────────────────────────────────────────────

    async def gate_target_dates(self, gates: list[GovernanceGate]) -> dict[uuid.UUID, str]:
        """The planned date of each gate: the linked schedule activity's, else the gate's own.

        The schedule owns the date. A linked gate reads it on every request, so
        a move in the schedule shows here without anything being copied.
        """
        linked = {g.schedule_activity_id for g in gates if g.schedule_activity_id}
        dates: dict[uuid.UUID, str] = {}
        if linked:
            from app.modules.schedule.models import Activity

            rows = await self.session.execute(
                select(Activity.id, Activity.end_date, Activity.start_date).where(Activity.id.in_(linked))
            )
            dates = {aid: str(end or start or "")[:10] for aid, end, start in rows.all()}
        return {
            g.id: dates.get(g.schedule_activity_id, "") if g.schedule_activity_id else (g.target_date or "")
            for g in gates
        }

    async def _activity_in_project(self, project_id: uuid.UUID, activity_id: uuid.UUID) -> bool:
        from app.modules.schedule.models import Activity, Schedule

        stmt = (
            select(Activity.id)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Activity.id == activity_id, Schedule.project_id == project_id)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def plan_gate(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, *, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> GovernanceGate:
        """Set when a gate is planned: a link to a schedule activity, or its own date without one.

        ``changes`` holds only the fields the caller sent: ``schedule_activity_id``
        (None unlinks) and ``target_date`` (None clears). A linked gate has no
        date of its own, so sending both is refused.
        """
        await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        if gate.historic:
            raise conflict("gate_historic")
        before = {"schedule_activity_id": _s(gate.schedule_activity_id), "target_date": gate.target_date}
        if "schedule_activity_id" in changes:
            activity_id = changes["schedule_activity_id"]
            if activity_id is not None:
                if not await self._activity_in_project(project_id, activity_id):
                    raise GovernanceError("activity_not_in_project", 422)
                gate.target_date = ""
            gate.schedule_activity_id = activity_id
        if "target_date" in changes:
            day = changes["target_date"]
            if day is not None and gate.schedule_activity_id is not None:
                raise GovernanceError("target_date_owned_by_schedule", 422)
            gate.target_date = day.isoformat() if day is not None else ""
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_gate",
            gate.id,
            "planned",
            before_state=before,
            after_state={"schedule_activity_id": _s(gate.schedule_activity_id), "target_date": gate.target_date},
        )
        return gate

    # ── checks ─────────────────────────────────────────────────────────────

    async def _current_check(self, gate: GovernanceGate, area: GovernanceArea) -> GovernanceCheck:
        for c in await self.repo.list_checks(gate.id, gate.attempt_no):
            if c.area_id == area.id:
                return c
        check = GovernanceCheck(
            project_id=gate.project_id, gate_id=gate.id, attempt_no=gate.attempt_no, area_id=area.id
        )
        return await self.repo.add(check)

    async def _area_for_owner(self, project_id: uuid.UUID, area_id: uuid.UUID, user_id: uuid.UUID) -> GovernanceArea:
        area = await self.repo.get_area(project_id, area_id)
        if area is None:
            raise not_found("area_not_found")
        if not area.owner_user_id:
            raise conflict("area_without_owner")
        if user_id not in (area.owner_user_id, area.deputy_user_id):
            raise forbidden("not_area_owner")
        return area

    async def confirm_check(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        area_id: uuid.UUID,
        *,
        status: str,
        rag: str,
        note: str,
        actor_id: uuid.UUID,
    ) -> GovernanceCheck:
        """The area owner (or deputy) attests readiness; the revisions it saw are recorded."""
        if status not in ("ready", "ready_with_risks", "not_ready", "not_assessed"):
            raise GovernanceError("invalid_status", 422)
        await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        if gate.status not in _UNDECIDED or gate.historic:
            raise conflict("invalid_transition")
        area = await self._area_for_owner(project_id, area_id, actor_id)
        docs = [d for d in await self.repo.list_documents(project_id) if d.area_id == area.id]
        facts = await self._revision_facts([d.container_id for d in docs if d.container_id])
        confirmed: dict[str, str] = {}
        for d in docs:
            in_force = (
                _s(d.bound_revision_id)
                if d.status in ("approved_at_gate", "binding", "superseded") and d.bound_revision_id
                else facts.get(d.container_id, (None, None))[0]
                if d.container_id
                else None
            )
            if in_force:
                confirmed[str(d.id)] = in_force
        check = await self._current_check(gate, area)
        before = check.status
        check.status = status
        check.rag = rag
        check.note = note
        check.confirmed_by = actor_id
        check.confirmed_at = datetime.now(UTC)
        check.confirmed_revisions = confirmed
        check.stale = False
        check.na_rationale = ""
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_check",
            check.id,
            "confirmed",
            from_status=before,
            to_status=status,
            metadata={"gate": gate.code, "area": area.code, "revisions": confirmed},
        )
        return check

    async def tick_criterion(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        area_id: uuid.UUID,
        code: str,
        *,
        met: bool,
        note: str,
        actor_id: uuid.UUID,
    ) -> GovernanceCheck:
        """The area owner (or deputy) ticks one readiness criterion of the catalogue.

        The checklist is what the owner works through before attesting; it does
        not attest and does not block. Readiness is still the check's status.
        """
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        if gate.status not in _UNDECIDED or gate.historic:
            raise conflict("invalid_transition")
        area = await self._area_for_owner(project_id, area_id, actor_id)
        catalogue = await self.catalogue_for(model)
        if code not in {c.code for c in catalogue.criteria_for(gate.code, area.code)}:
            raise GovernanceError("unknown_criterion", 422)
        check = await self._current_check(gate, area)
        check.criteria = ev.criterion_tick(
            check.criteria or {}, code, met=met, note=note, actor_id=str(actor_id), at=datetime.now(UTC).isoformat()
        )
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_check",
            check.id,
            "criterion_ticked" if met else "criterion_unticked",
            metadata={"gate": gate.code, "area": area.code, "criterion": code},
        )
        return check

    async def mark_check_not_applicable(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, area_id: uuid.UUID, *, rationale: str, actor_id: uuid.UUID
    ) -> GovernanceCheck:
        code = ev.not_applicable_violation(rationale)
        if code:
            raise GovernanceError(code, 422)
        gate = await self.get_gate(project_id, gate_id, lock=True)
        if gate.status not in _UNDECIDED or gate.historic:
            raise conflict("invalid_transition")
        area = await self._area_for_owner(project_id, area_id, actor_id)
        check = await self._current_check(gate, area)
        before = check.status
        check.status = "not_applicable"
        check.na_rationale = rationale.strip()
        check.confirmed_by = actor_id
        check.confirmed_at = datetime.now(UTC)
        check.stale = False
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_check",
            check.id,
            "not_applicable",
            from_status=before,
            to_status="not_applicable",
            reason=rationale,
        )
        return check

    # ── documents ──────────────────────────────────────────────────────────

    async def _document_for_edit(
        self, project_id: uuid.UUID, document_id: uuid.UUID, user_id: uuid.UUID, is_manager: bool, action: str
    ) -> tuple[GovernanceDocument, GovernanceArea]:
        doc = await self.repo.get_document(project_id, document_id, lock=True)
        if doc is None:
            raise not_found("document_not_found")
        area = await self.repo.get_area(project_id, doc.area_id)
        assert area is not None
        refusal = self._document_refusal(doc, area, user_id, is_manager, action)
        if refusal is not None:
            raise refusal
        return doc, area

    @staticmethod
    def _document_refusal(
        doc: GovernanceDocument, area: GovernanceArea, user_id: uuid.UUID, is_manager: bool, action: str
    ) -> GovernanceError | None:
        """Why this caller may not ``attach``, ``submit`` or ``return`` the document, or ``None``.

        The write routes raise this and :meth:`document_capabilities` reports
        it, so a button and its request can never disagree.
        """
        if not is_manager and user_id not in (area.owner_user_id, area.deputy_user_id):
            return forbidden("not_area_owner")
        state = ev.DocumentState(
            id=str(doc.id),
            area_code=area.code,
            doc_type=doc.doc_type,
            required=False,
            status=doc.status,
            container_id=_s(doc.container_id),
            current_revision_id=None,
            bound_revision_id=_s(doc.bound_revision_id),
            read_only=doc.read_only,
        )
        code = ev.document_edit_violation(state, action)
        if code:
            return conflict(code)
        target = {"submit": "in_review", "return": "draft"}.get(action)
        if target is not None and not DOCUMENT_FSM.has_transition(doc.status, target):
            return conflict("invalid_transition")
        return None

    async def document_capabilities(
        self,
        project_id: uuid.UUID,
        documents: list[GovernanceDocument],
        *,
        actor_id: uuid.UUID,
        can_edit: bool,
        is_manager: bool,
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Per document what this caller may do, each with a reason code.

        ``{attach, submit, return, change_request}``. ``submit`` is also
        refused with ``no_pending_revision`` while the document has no
        container. Whether an attached container holds a newer revision is
        only known to the write, so ``change_request`` can still answer
        ``no_pending_revision`` there.
        """
        areas = {a.id: a for a in await self.repo.list_areas(project_id, include_retired=True)}
        model = await self.repo.get_model(project_id)
        open_requests = {
            cr.document_id for cr in await self.repo.list_change_requests(project_id) if cr.status == "submitted"
        }
        has_route = model is not None and await self._resolve_route(model, CHANGE_TARGET_KIND) is not None
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for doc in documents:
            flags: dict[str, Any] = {}
            area = areas.get(doc.area_id)
            if not can_edit:
                change: str | None = "missing_permission"
            elif model is None:
                change = "model_missing"
            else:
                refused = self._change_request_refusal(
                    model,
                    doc,
                    area,
                    actor_id,
                    is_manager,
                    has_open=doc.id in open_requests,
                    has_route=has_route,
                )
                change = refused.code if refused is not None else None
            flags["change_request"] = change is None
            flags["change_request_reason"] = change
            for action in ("attach", "submit", "return"):
                if not can_edit:
                    code: str | None = "missing_permission"
                elif area is None:
                    code = "area_not_found"
                else:
                    refusal = self._document_refusal(doc, area, actor_id, is_manager, action)
                    code = refusal.code if refusal is not None else None
                    if code is None and action == "submit" and not doc.container_id:
                        code = "no_pending_revision"
                flags[action] = code is None
                flags[f"{action}_reason"] = code
            out[doc.id] = flags
        return out

    @staticmethod
    def _add_document_refusal(area: GovernanceArea, user_id: uuid.UUID, is_manager: bool) -> GovernanceError | None:
        """Why this caller may not add a frame document to the area, or ``None``.

        A new document can be required at a gate, so it changes what the gate
        reads: like every other document write it belongs to the area's owner
        or deputy, or to a governance manager.
        """
        if area.retired:
            return conflict("area_retired")
        if not is_manager and user_id not in (area.owner_user_id, area.deputy_user_id):
            return forbidden("not_area_owner")
        return None

    def area_capabilities(
        self, areas: list[GovernanceArea], *, actor_id: uuid.UUID, can_edit: bool, is_manager: bool
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Per area what this caller may do: ``{add_document, add_document_reason}``."""
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for area in areas:
            if not can_edit:
                code: str | None = "missing_permission"
            else:
                refusal = self._add_document_refusal(area, actor_id, is_manager)
                code = refusal.code if refusal is not None else None
            out[area.id] = {"add_document": code is None, "add_document_reason": code}
        return out

    @staticmethod
    def _change_request_refusal(
        model: GovernanceModel,
        doc: GovernanceDocument,
        area: GovernanceArea | None,
        user_id: uuid.UUID,
        is_manager: bool,
        *,
        has_open: bool,
        has_route: bool,
    ) -> GovernanceError | None:
        """Why this caller may not raise a change request on the document, or ``None``.

        Everything that can be known before the request body is read; the
        write raises it and :meth:`document_capabilities` reports it.
        """
        if not is_manager and area is not None and user_id not in (area.owner_user_id, area.deputy_user_id):
            return forbidden("not_area_owner")
        if model.stopped:
            # A stopped project keeps the baseline it was stopped with.
            return conflict("project_stopped")
        if doc.read_only:
            return conflict("document_read_only")
        if doc.status != "binding":
            return conflict("document_not_binding")
        if has_open:
            return conflict("change_request_not_open")
        if not has_route:
            return GovernanceError("no_change_route", 422)
        return None

    async def create_document(
        self,
        project_id: uuid.UUID,
        *,
        area_id: uuid.UUID,
        doc_type: str,
        actor_id: uuid.UUID,
        is_manager: bool = False,
    ) -> GovernanceDocument:
        """Add an optional frame document of a catalogue type the project does not track yet."""
        model = await self.require_model(project_id)
        area = await self.repo.get_area(project_id, area_id)
        if area is None:
            raise not_found("area_not_found")
        refusal = self._add_document_refusal(area, actor_id, is_manager)
        if refusal is not None:
            raise refusal
        catalogue = await self.catalogue_for(model)
        known = {d.code: d for d in catalogue.document_types if d.area == area.code}
        if doc_type not in known:
            raise GovernanceError("unknown_document_type", 422)
        for d in await self.repo.list_documents(project_id):
            if d.area_id == area.id and d.doc_type == doc_type:
                raise conflict("document_exists")
        doc = await self.repo.add(
            GovernanceDocument(
                project_id=project_id,
                area_id=area.id,
                doc_type=doc_type,
                required_at_gates=list(known[doc_type].required_at_gates),
            )
        )
        await self._audit(actor_id, "governance_document", doc.id, "created")
        return doc

    async def attach_container(
        self,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        container_id: uuid.UUID,
        actor_id: uuid.UUID,
        is_manager: bool = False,
    ) -> GovernanceDocument:
        doc, _ = await self._document_for_edit(project_id, document_id, actor_id, is_manager, "attach")
        if not await self._container_in_project(project_id, container_id):
            raise GovernanceError("container_not_in_project", 422)
        before = _s(doc.container_id)
        doc.container_id = container_id
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_document",
            doc.id,
            "container_attached",
            before_state={"container_id": before},
            after_state={"container_id": str(container_id)},
        )
        return doc

    async def submit_document(
        self, project_id: uuid.UUID, document_id: uuid.UUID, *, actor_id: uuid.UUID, is_manager: bool = False
    ) -> GovernanceDocument:
        doc, _ = await self._document_for_edit(project_id, document_id, actor_id, is_manager, "submit")
        if (
            not doc.container_id
            or not (await self._revision_facts([doc.container_id])).get(doc.container_id, (None,))[0]
        ):
            raise GovernanceError("no_pending_revision", 422)
        await self._fsm(DOCUMENT_FSM, doc, "in_review", actor_id)
        self._publish(
            "project_governance.frame_document.state_changed",
            {"project_id": str(project_id), "document_id": str(doc.id), "status": doc.status},
        )
        return doc

    async def return_document(
        self, project_id: uuid.UUID, document_id: uuid.UUID, *, actor_id: uuid.UUID, is_manager: bool = False
    ) -> GovernanceDocument:
        doc, _ = await self._document_for_edit(project_id, document_id, actor_id, is_manager, "return")
        await self._fsm(DOCUMENT_FSM, doc, "draft", actor_id)
        return doc

    async def document_history(self, project_id: uuid.UUID, document_id: uuid.UUID) -> dict[str, Any]:
        """CDE revisions of the container, which revision is in force, and change requests."""
        from app.modules.cde.models import DocumentRevision

        doc = await self.repo.get_document(project_id, document_id)
        if doc is None:
            raise not_found("document_not_found")
        revisions: list[dict[str, Any]] = []
        if doc.container_id:
            rows = (
                await self.session.execute(
                    select(DocumentRevision)
                    .where(DocumentRevision.container_id == doc.container_id)
                    .order_by(DocumentRevision.revision_number)
                )
            ).scalars()
            revisions = [
                {
                    "id": str(r.id),
                    "revision_code": r.revision_code,
                    "revision_number": r.revision_number,
                    "content_hash": r.content_hash,
                    "file_name": r.file_name,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "in_force": doc.bound_revision_id is not None and r.id == doc.bound_revision_id,
                }
                for r in rows
            ]
        crs = await self.repo.list_change_requests(project_id, doc.id)
        return {"document_id": str(doc.id), "revisions": revisions, "change_requests": crs}

    # ── conditions ─────────────────────────────────────────────────────────

    async def _require_condition_owner(self, project_id: uuid.UUID, owner_user_id: Any) -> None:
        """A condition owner clears the condition, so they must be able to open the project."""
        owner = _uuid(owner_user_id)
        if owner is not None and not await self.user_can_access_project(project_id, owner):
            raise GovernanceError("owner_not_project_member", 422)

    async def _add_condition_target(
        self, gate: GovernanceGate, authority: _Authority
    ) -> tuple[GovernanceDecision | None, GovernanceError | None]:
        """The decision a further condition would attach to, or why there is none for this caller."""
        if gate.historic:
            return None, conflict("gate_historic")
        decisions = [
            d for d in await self.repo.list_decisions(gate.project_id, gate.id) if d.outcome == "go_with_conditions"
        ]
        if not decisions:
            return None, conflict("conditions_not_allowed")
        code = authority.over(decisions[-1].id)
        return decisions[-1], forbidden(code) if code else None

    async def add_condition(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        *,
        cond: ev.ProposedCondition,
        actor_id: uuid.UUID,
        role: str | None = None,
    ) -> GovernanceCondition:
        """Attach a further condition to the gate's latest go-with-conditions decision."""
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id)
        target, refusal = await self._add_condition_target(gate, await self._authority(model, actor_id, role))
        if refusal is not None or target is None:
            raise refusal or conflict("conditions_not_allowed")
        if not cond.text.strip():
            raise GovernanceError("condition_text_required", 422)
        areas = {a.code for a in await self.repo.list_areas(project_id)}
        if cond.area_code is not None and cond.area_code not in areas:
            raise GovernanceError("condition_unknown_area", 422)
        await self._require_condition_owner(project_id, cond.owner_user_id)
        row = await self.repo.add(
            GovernanceCondition(
                project_id=project_id,
                decision_id=target.id,
                gate_id=gate.id,
                gate_code=gate.code,
                area_code=cond.area_code,
                document_type=cond.document_type,
                text=cond.text.strip(),
                owner_user_id=_uuid(cond.owner_user_id),
                due_date=cond.due_date.isoformat() if cond.due_date else "",
                severity=cond.severity,
            )
        )
        await self._audit(actor_id, "governance_condition", row.id, "created", to_status="open")
        return row

    def _waive_code(self, cond: GovernanceCondition, authority: _Authority) -> str | None:
        return ev.condition_waive_violation(
            cond.status,
            actor_id=authority.actor_id,
            decided_by=authority.deciders.get(cond.decision_id),
            route_entitled=authority.route_entitled,
            four_eyes=authority.four_eyes,
            areas=authority.areas,
            area_code=cond.area_code,
        )

    async def condition_capabilities(
        self,
        project_id: uuid.UUID,
        conditions: list[GovernanceCondition],
        *,
        actor_id: uuid.UUID,
        role: str | None,
        can_edit: bool,
        can_decide: bool,
        is_manager: bool,
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Per condition what this caller may do, from the rules :meth:`clear_condition` and :meth:`waive_condition` apply.

        ``can_edit``, ``can_decide`` and ``is_manager`` are the caller's
        permission answers; a missing one reads ``missing_permission``.
        """
        model = await self.repo.get_model(project_id)
        authority = (
            await self._authority(model, actor_id, role) if model is not None and can_decide and conditions else None
        )
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for cond in conditions:
            clear = (
                ev.condition_clear_violation(
                    cond.status, _s(cond.owner_user_id), actor_id=str(actor_id), is_manager=is_manager
                )
                if can_edit
                else "missing_permission"
            )
            waive = self._waive_code(cond, authority) if authority is not None else "missing_permission"
            out[cond.id] = {
                "clear": clear is None,
                "clear_reason": clear,
                "waive": waive is None,
                "waive_reason": waive,
            }
        return out

    async def clear_condition(
        self,
        project_id: uuid.UUID,
        condition_id: uuid.UUID,
        *,
        evidence: str,
        actor_id: uuid.UUID,
        is_manager: bool = False,
    ) -> GovernanceCondition:
        cond = await self.repo.get_condition(project_id, condition_id, lock=True)
        if cond is None:
            raise not_found("condition_not_found")
        code = ev.condition_clear_violation(
            cond.status, _s(cond.owner_user_id), actor_id=str(actor_id), is_manager=is_manager
        )
        if code:
            raise conflict(code) if code == "condition_not_open" else forbidden(code)
        before = cond.status
        cond.status = "cleared"
        cond.evidence = evidence or ""
        cond.cleared_by = actor_id
        cond.cleared_at = datetime.now(UTC)
        await self.session.flush()
        await self._audit(actor_id, "governance_condition", cond.id, "cleared", from_status=before, to_status="cleared")
        return cond

    async def waive_condition(
        self,
        project_id: uuid.UUID,
        condition_id: uuid.UUID,
        *,
        rationale: str,
        actor_id: uuid.UUID,
        role: str | None = None,
    ) -> GovernanceCondition:
        """Waive an open condition: a written reason, and authority over the decision that set it."""
        code = ev.waiver_violation(rationale)
        if code:
            raise GovernanceError(code, 422)
        model = await self.require_model(project_id)
        cond = await self.repo.get_condition(project_id, condition_id, lock=True)
        if cond is None:
            raise not_found("condition_not_found")
        code = self._waive_code(cond, await self._authority(model, actor_id, role))
        if code:
            raise conflict(code) if code == "condition_not_open" else forbidden(code)
        before = cond.status
        cond.status = "waived"
        cond.waiver_rationale = rationale.strip()
        cond.waived_by = actor_id
        cond.waived_at = datetime.now(UTC)
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_condition",
            cond.id,
            "waived",
            from_status=before,
            to_status="waived",
            reason=rationale,
        )
        return cond

    async def escalate_overdue(self, project_id: uuid.UUID, *, today: date) -> list[GovernanceCondition]:
        """Mark overdue conditions and tell the decider of the gate that set them."""
        rows, _ = await self.repo.list_conditions(project_id, status="open")
        states = [
            ev.ConditionState(
                id=str(c.id),
                gate_code=c.gate_code,
                area_code=c.area_code,
                status=c.status,
                due_date=_parse_day(c.due_date),
            )
            for c in rows
        ]
        late_ids = {s.id for s in ev.conditions_to_escalate(states, today)}
        out: list[GovernanceCondition] = []
        decisions = {d.id: d for d in await self.repo.list_decisions(project_id)}
        for c in rows:
            if str(c.id) not in late_ids:
                continue
            c.status = "overdue"
            c.escalated_at = datetime.now(UTC)
            out.append(c)
            await self._audit(None, "governance_condition", c.id, "escalated", from_status="open", to_status="overdue")
            decider = decisions.get(c.decision_id)
            await self._notify(
                decider.decided_by if decider else None,
                "condition_overdue",
                "governance_condition",
                c.id,
                {"project_id": str(project_id), "gate": c.gate_code},
            )
            self._publish(
                "project_governance.condition.overdue", {"project_id": str(project_id), "condition_id": str(c.id)}
            )
        await self.session.flush()
        return out

    # ── change requests ────────────────────────────────────────────────────

    async def create_change_request(
        self,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        reason: str,
        impact: str,
        proposed_revision_id: uuid.UUID | None,
        actor_id: uuid.UUID,
        is_manager: bool = False,
    ) -> GovernanceChangeRequest:
        """Ask to make a newer revision binding; starts the ``frame_change`` route."""
        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        model = await self.require_model(project_id)
        doc = await self.repo.get_document(project_id, document_id, lock=True)
        if doc is None:
            raise not_found("document_not_found")
        area = await self.repo.get_area(project_id, doc.area_id)
        route = await self._resolve_route(model, CHANGE_TARGET_KIND)
        refusal = self._change_request_refusal(
            model,
            doc,
            area,
            actor_id,
            is_manager,
            has_open=any(cr.status == "submitted" for cr in await self.repo.list_change_requests(project_id, doc.id)),
            has_route=route is not None,
        )
        if refusal is not None:
            raise refusal
        if not (reason or "").strip():
            raise GovernanceError("rationale_required", 422)
        current = (
            (await self._revision_facts([doc.container_id])).get(doc.container_id, (None, None))[0]
            if (doc.container_id)
            else None
        )
        proposed = proposed_revision_id or _uuid(current)
        if proposed is None or proposed == doc.bound_revision_id:
            raise GovernanceError("no_pending_revision", 422)
        from app.modules.cde.models import DocumentRevision

        rev = await self.session.get(DocumentRevision, proposed)
        if rev is None or rev.container_id != doc.container_id:
            raise GovernanceError("no_pending_revision", 422)
        cr = await self.repo.add(
            GovernanceChangeRequest(
                project_id=project_id,
                document_id=doc.id,
                previous_revision_id=doc.bound_revision_id,
                proposed_revision_id=proposed,
                proposed_content_hash=rev.content_hash,
                reason=reason.strip(),
                impact=impact or "",
                requested_by=actor_id,
            )
        )
        try:
            instance = await ApprovalRouteService(self.session).start_instance(
                InstanceCreate(route_id=route.id, target_kind=CHANGE_TARGET_KIND, target_id=cr.id), started_by=actor_id
            )
        except HTTPException as exc:
            raise _route_error(exc) from exc
        cr.approval_instance_id = instance.id
        await self.session.flush()
        await self._audit(
            actor_id,
            "governance_change_request",
            cr.id,
            "submitted",
            to_status="submitted",
            reason=reason,
            parent_entity_type="governance_document",
            parent_entity_id=doc.id,
        )
        return cr

    async def apply_change_decision(
        self, cr_id: uuid.UUID, *, decision: str, decided_by: Any = None
    ) -> GovernanceChangeRequest | None:
        """Idempotent: the route's verdict on a change request, applied once."""
        cr = await self.repo.get_change_request_by_id(cr_id, lock=True)
        if cr is None or cr.status != "submitted":
            return None
        doc = await self.repo.get_document(cr.project_id, cr.document_id, lock=True)
        now = datetime.now(UTC)
        cr.decided_by = _uuid(decided_by) if decided_by else None
        cr.decided_at = now
        if decision == "approved" and doc is not None and doc.status == "binding" and not doc.read_only:
            before = _s(doc.bound_revision_id)
            doc.bound_revision_id = cr.proposed_revision_id
            doc.bound_content_hash = cr.proposed_content_hash
            cr.status = "approved"
            await self._audit(
                decided_by,
                "governance_document",
                doc.id,
                "binding_revision_changed",
                before_state={"bound_revision_id": before},
                after_state={"bound_revision_id": str(cr.proposed_revision_id)},
            )
            self._publish(
                "project_governance.frame_document.state_changed",
                {
                    "project_id": str(cr.project_id),
                    "document_id": str(doc.id),
                    "status": "binding",
                    "bound_revision_id": str(cr.proposed_revision_id),
                },
            )
        else:
            cr.status = "rejected"
        await self.session.flush()
        await self._audit(
            decided_by, "governance_change_request", cr.id, cr.status, from_status="submitted", to_status=cr.status
        )
        return cr

    # ── reads ──────────────────────────────────────────────────────────────

    async def gate_detail(self, project_id: uuid.UUID, gate_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """The readiness matrix of one gate: blockers, per-area check and documents, attempts."""
        model = await self.require_model(project_id)
        gate = await self.get_gate(project_id, gate_id)
        ctx, areas, docs = await self.gate_context(model, gate, today)
        decisions = await self.repo.list_decisions(project_id, gate.id)
        checks = {c.area_code: c for c in ctx.checks}
        doc_states = {d.id: d for d in ctx.documents}
        unseen = {(e.area_code, e.code) for e in ev.evidence_to_acknowledge(ctx)}
        try:
            catalogue: Catalogue | None = await self.catalogue_for(model)
        except GovernanceError:
            # A pin that no longer resolves: the gate still reads, without a checklist.
            catalogue = None

        def _criteria(area_code: str) -> list[dict[str, Any]]:
            if catalogue is None:
                return []
            ticks = checks[area_code].criteria if area_code in checks else {}
            return ev.criteria_rows([c.code for c in catalogue.criteria_for(gate.code, area_code)], ticks)

        return {
            "gate": gate,
            "blockers": [b.as_dict() for b in ev.gate_blockers(ctx)],
            "areas": [
                {
                    "area_id": str(a.id),
                    "code": a.code,
                    "owner_user_id": _s(a.owner_user_id),
                    "deputy_user_id": _s(a.deputy_user_id),
                    "applicable": a.applicable,
                    "evidence": [
                        e.as_dict(project_id) | {"needs_acknowledgement": (e.area_code, e.item.code) in unseen}
                        for e in self.last_evidence
                        if e.area_code == a.code
                    ],
                    "check": (
                        {
                            "status": checks[a.code].status,
                            "rag": checks[a.code].rag,
                            "note": checks[a.code].note,
                            "confirmed_by": checks[a.code].confirmed_by,
                            "confirmed_at": checks[a.code].confirmed_at,
                            "stale": ev.check_is_stale(checks[a.code], ctx.documents),
                            "na_rationale": checks[a.code].na_rationale,
                        }
                        if a.code in checks
                        else None
                    ),
                    "criteria": _criteria(a.code),
                    "documents": [
                        {
                            "document_id": str(d.id),
                            "doc_type": d.doc_type,
                            "status": d.status,
                            "required": gate.code in (d.required_at_gates or []),
                            "container_id": _s(d.container_id),
                            "revision_in_force": ev.revision_in_force(doc_states[str(d.id)]),
                            "pending_revision": ev.pending_revision(doc_states[str(d.id)]),
                            "read_only": d.read_only,
                        }
                        for d in docs
                        if d.area_id == a.id
                    ],
                }
                for a in areas.values()
            ],
            "decisions": decisions,
        }

    async def validation_payload(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """The payload the ``project_governance`` rule set reads (see ``validators.py``)."""
        await self.require_model(project_id)
        areas = await self.repo.list_areas(project_id)
        by_id = {a.id: a for a in areas}
        docs = [d for d in await self.repo.list_documents(project_id) if d.area_id in by_id]
        facts = await self._revision_facts([d.container_id for d in docs if d.container_id])
        conditions, _ = await self.repo.list_conditions(project_id)
        decisions = await self.repo.list_decisions(project_id)
        gates = await self.repo.list_gates(project_id)
        planned = await self.gate_target_dates(gates)
        return {
            "today": today.isoformat(),
            "areas": [
                {
                    "code": a.code,
                    "owner_user_id": _s(a.owner_user_id),
                    "applicable": a.applicable,
                    "na_rationale": a.na_rationale,
                }
                for a in areas
            ],
            "gates": [
                {
                    "code": g.code,
                    "status": g.status,
                    "target_date": planned[g.id],
                    "sort_order": g.sort_order,
                    "historic": g.historic,
                }
                for g in gates
            ],
            "documents": [
                {
                    "id": str(d.id),
                    "doc_type": d.doc_type,
                    "area_code": by_id[d.area_id].code,
                    "status": d.status,
                    "required_at_gates": list(d.required_at_gates or []),
                    "bound_revision_id": _s(d.bound_revision_id),
                    "current_revision_id": facts.get(d.container_id, (None, None))[0] if d.container_id else None,
                }
                for d in docs
            ],
            "conditions": [{"id": str(c.id), "status": c.status, "due_date": c.due_date} for c in conditions],
            "decisions": [
                {
                    "gate_code": d.gate_code,
                    "decided_by": str(d.decided_by),
                    "four_eyes": bool((d.snapshot or {}).get("four_eyes")),
                    "owner_ids": sorted(
                        {
                            str(x)
                            for a in (d.snapshot or {}).get("areas", [])
                            if a.get("applicable", True)
                            for x in (a.get("owner_user_id"), a.get("deputy_user_id"))
                            if x
                        }
                    ),
                }
                for d in decisions
            ],
        }

    async def trail(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every decision with its conditions, oldest first: the exportable record."""
        decisions = await self.repo.list_decisions(project_id)
        conditions, _ = await self.repo.list_conditions(project_id)
        by_decision: dict[uuid.UUID, list[GovernanceCondition]] = {}
        for c in conditions:
            by_decision.setdefault(c.decision_id, []).append(c)
        return [
            {
                "gate_code": d.gate_code,
                "attempt_no": d.attempt_no,
                "outcome": d.outcome,
                "decided_by": str(d.decided_by),
                "decided_at": d.decided_at.isoformat(),
                "rationale": d.rationale,
                "proceed_at_risk_areas": d.proceed_at_risk_areas or [],
                "conditions": [{"text": c.text, "status": c.status} for c in by_decision.get(d.id, [])],
            }
            for d in decisions
        ]
