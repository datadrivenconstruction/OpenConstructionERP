# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quality concept service: the plan, its coverage, and the mirrors of other modules' acts.

Owned here: the concept (pinned catalogue, package scope, state), standards,
certification and credit targets, proof requirements, evidence links, the
project's stage model, stage progress, acceptance units with confirmed legal
effects, preservation surveys and expert report plans.

Read only (linked): every evidence row (construction_control, qms,
commissioning, closeout, submittals, inspections, cde, daily_diary,
requirements). Written through the owning module's service and only on an
explicit human act: hold gates (stage release request), CX issues (failed
stage test), requirement sets and requirements (quality requirements), DLP
warranties (confirmed limitation effect).

States owned elsewhere arrive as mirrors: a released hold gate releases a
stage (rule 10), an issued handover certificate accepts a unit (rule 15), a
binding governance frame document makes the concept binding (rule 22).
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.events import publish_after_commit
from app.core.i18n import get_locale
from app.modules.quality_concept import capabilities as caps
from app.modules.quality_concept import evaluator as ev
from app.modules.quality_concept import fsm, hosting, links, references
from app.modules.quality_concept.catalogue import (
    DEFAULT_CATALOGUE_ID,
    QUALITY_CONCEPT_KIND,
    QualityConceptCatalogue,
)
from app.modules.quality_concept.errors import QualityConceptError, conflict, not_found
from app.modules.quality_concept.messages import translate
from app.modules.quality_concept.models import (
    AcceptanceEffect,
    AcceptanceUnit,
    AppliedStandard,
    CertificationTarget,
    CommissioningStageDef,
    CreditTarget,
    EvidenceLink,
    ExpertReportPlan,
    PreservationSurvey,
    ProofRequirement,
    QualityConcept,
    QualityConceptRevision,
    StageProgress,
)
from app.modules.quality_concept.repository import QualityConceptRepository
from app.modules.quality_concept.vocab import WARRANTY_EFFECTS

logger = logging.getLogger(__name__)

EVENT_PREFIX = "quality_concept."
PLAN_EDITABLE = caps.PLAN_OPEN_STATES
DATES_OPEN = caps.DATES_OPEN
# NCR severities a regime may accept as a reservation; the rest are material defects (rule 13).
MINOR_NCR = ("minor", "observation")
OWNER_MODELS: dict[str, Any] = {
    "proof": ProofRequirement,
    "credit": CreditTarget,
    "stage_progress": StageProgress,
    "preservation": PreservationSurvey,
    "expert_report": ExpertReportPlan,
}
_DONE_PROOF = ("delivered", "accepted", "waived")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _transition(machine: str, state: str, action: str, *, mirror: bool = False, rationale: str = "") -> str:
    try:
        return fsm.next_state(machine, state, action, mirror=mirror, rationale=rationale)
    except fsm.TransitionError as exc:
        status = 422 if exc.code == "rationale_required" else 409
        raise QualityConceptError(exc.code, status, detail=f"{machine}:{state}->{action}") from exc


def _refuse(code: str | None, **kw: Any) -> None:
    """Raise the refusal a ``capabilities`` check returned; the same code is the ``can`` reason."""
    if code is not None:
        raise QualityConceptError(code, caps.status_of(code), **kw)


class ProjectFacts:
    """Project-wide reads behind ``unmet_preconditions``, each made once however many units ask.

    One instance lives for one request. A caller that asks about a single unit passes none
    and gets the same reads, made for that unit alone.
    """

    def __init__(self) -> None:
        self._loaded: dict[str, Any] = {}

    async def get(self, key: str, load: Any) -> Any:
        if key not in self._loaded:
            self._loaded[key] = await load()
        return self._loaded[key]


# A unit reaches these two states only through its handover act.
_ACCEPTED_BY_ACT = ("accepted", "accepted_with_reservations")


def _state_after_issue(state: str, reserved: bool) -> str:
    """Where an issued act takes a unit; refused when the unit cannot follow it."""
    if state in ("planned", "refused"):
        # The certificate is the request and its answer; a refusal was overtaken by it.
        state = _transition("acceptance", state, "request")
    return _transition("acceptance", state, "accept_with_reservations" if reserved else "accept", mirror=True)


def _follows_issue(state: str) -> bool:
    if state in ev.ACCEPTED_STATES:
        return False
    try:
        _state_after_issue(state, False)
    except QualityConceptError:
        return False
    return True


def _text(key: str, **params: Any) -> str:
    """A sentence this module stores or hands to another module, in the request locale."""
    return translate(f"quality_concept.text.{key}", locale=get_locale() or "en", **params)


def _assign(row: Any, fields: dict[str, Any]) -> None:
    """Set ``fields`` on ``row``; an explicit null on a NOT NULL column is a 422, not a 500."""
    columns = row.__mapper__.columns
    for key, value in fields.items():
        column = columns.get(key)
        if value is None and column is not None and not column.nullable:
            raise QualityConceptError("null_not_allowed", detail=key)
    for key, value in fields.items():
        setattr(row, key, value)


def _findings(findings: list[ev.Finding]) -> list[dict[str, Any]]:
    return [f.as_dict() for f in findings]


class QualityConceptService:
    """Business logic of the quality concept; one instance per request session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = QualityConceptRepository(session)
        # The user a request acts for; ``None`` for the demo seed and the event mirrors.
        self.caller_id: str | None = None
        # Set by the API: the caller's permissions and what the ``can`` flags of this request read.
        self.ctx: Any = None

    def _publish(self, name: str, data: dict[str, Any]) -> None:
        publish_after_commit(self.session, EVENT_PREFIX + name, data, source_module="quality_concept")

    async def _audit(
        self, project_id: uuid.UUID, actor: uuid.UUID | None, entity: str, eid: Any, action: str, **kw: Any
    ) -> None:
        from app.core.audit_log import log_activity

        try:
            async with self.session.begin_nested():
                await log_activity(
                    self.session,
                    actor_id=actor,
                    entity_type=f"quality_concept.{entity}",
                    entity_id=eid,
                    action=action,
                    metadata={"project_id": str(project_id), **kw},
                )
        except Exception:  # audit is best effort, never blocks the act
            logger.debug("quality_concept: audit %s %s failed", entity, action, exc_info=True)

    # ── concept ─────────────────────────────────────────────────────────────

    async def concept(self, project_id: uuid.UUID) -> QualityConcept | None:
        return await self.repo.concept(project_id)

    async def concept_state(self, project_id: uuid.UUID) -> str | None:
        """The state alone. Loads no row, so a later locked read still sees what the lock returns."""
        stmt = select(QualityConcept.state).where(QualityConcept.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_concept(self, project_id: uuid.UUID, *, lock: bool = False) -> QualityConcept:
        row = await self.repo.concept(project_id, lock=lock)
        if row is None:
            raise not_found("concept_missing")
        return row

    async def ensure_concept(self, project_id: uuid.UUID, actor: uuid.UUID | None) -> QualityConcept:
        """The project's concept; created with the neutral catalogue pinned.

        Called only from an explicit write (``POST /concept``, the demo seed); no read creates it.
        """
        row = await self.repo.concept(project_id)
        if row is not None:
            return row
        source, catalogue_id, version = self.default_pin()
        row = QualityConcept(
            project_id=project_id,
            catalogue_source=source,
            catalogue_id=catalogue_id,
            catalogue_version=version,
            state="draft",
            packages=[],
            holidays=[],
            created_by=actor,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(row)
        except IntegrityError:
            existing = await self.repo.concept(project_id)
            if existing is None:
                raise
            return existing
        row.requirement_set_id = await self._ensure_requirement_set(project_id, actor)
        await self.session.flush()
        await self._audit(project_id, actor, "concept", row.id, "created")
        return row

    @staticmethod
    def default_pin() -> tuple[str, str, int]:
        """What a new concept pins: the active pack's default, else the shipped neutral catalogue."""
        from app.modules.project_governance.public import default_catalogue_pin
        from app.modules.quality_concept.catalogue import register_kinds, shipped_catalogue

        register_kinds()
        pin = default_catalogue_pin(QUALITY_CONCEPT_KIND)
        if pin is not None:
            return pin.source, str(pin.catalogue_id), pin.version
        return "shipped", DEFAULT_CATALOGUE_ID, shipped_catalogue().version

    async def available_catalogues(self, tenant_id: str | None) -> list[dict[str, Any]]:
        """Catalogues this caller may pin; ``default`` marks the one a new concept gets."""
        from app.modules.project_governance.catalogue_store import CatalogueStore

        source, catalogue_id, _version = self.default_pin()
        items = await CatalogueStore(self.session).list_available(tenant_id, kind=QUALITY_CONCEPT_KIND)
        for item in items:
            item.pop("phases", None)
            item["id"] = str(item["id"])
            item["default"] = (item["source"], item["id"]) == (source, catalogue_id)
        return items

    async def _frame_documents(self, project_id: uuid.UUID) -> dict[uuid.UUID, str]:
        """``{document id: status}`` of the governance frame documents tagged for quality.

        Resolved from the pinned governance catalogue each time; empty when the project has no
        governance model or its catalogue tags no document type for quality.
        """
        from app.modules.project_governance import public

        host = await hosting.project_host(self.session, project_id)
        if host is None:
            return {}
        documents = await public.project_documents(self.session, project_id)
        return {d.id: d.status for d in documents if d.code == host.doc_type}

    async def _bound_revision(self, project_id: uuid.UUID, document_id: uuid.UUID | None) -> str | None:
        """The revision of a frame document that is in force, as governance names it."""
        from app.modules.project_governance import public

        if document_id is None:
            return None
        for doc in await public.project_documents(self.session, project_id):
            if doc.id == document_id:
                return str(doc.bound_revision_id) if doc.bound_revision_id else None
        return None

    async def reconcile_governance(self, project_id: uuid.UUID, *, reopen: bool = False) -> bool:
        """Follow a frame document whose event never arrived (rule 22). Called from write routes only.

        A concept in review under a document that is binding is approved and bound.

        ``reopen``: also follow an approved change request. A bound concept is reopened only
        when the document names a revision in force other than the one the concept was
        approved under; a concept approved before that was recorded is left alone. Asked
        only where the plan is about to be written, since it reads the last approved revision.
        """
        state = await self.concept_state(project_id)
        if state != "in_review" and not (reopen and state == "binding"):
            return False
        bound = [doc for doc, status in (await self._frame_documents(project_id)).items() if status == "binding"]
        if not bound:
            return False
        if state == "in_review":
            return await self.apply_governance_state(project_id, bound[0], "binding")
        in_force = await self._bound_revision(project_id, bound[0])
        stmt = (
            select(QualityConceptRevision.snapshot)
            .where(QualityConceptRevision.project_id == project_id)
            .where(QualityConceptRevision.reason == "approved")
            .order_by(QualityConceptRevision.revision_no.desc())
            .limit(1)
        )
        under = ((await self.session.execute(stmt)).scalar_one_or_none() or {}).get("document_revision_id")
        if not in_force or not under or under == in_force:
            return False
        return await self.apply_governance_state(project_id, bound[0], "binding", change_request=in_force)

    async def _ensure_requirement_set(self, project_id: uuid.UUID, actor: uuid.UUID | None) -> uuid.UUID:
        from app.modules.requirements.models import RequirementSet
        from app.modules.requirements.schemas import RequirementSetCreate
        from app.modules.requirements.service import RequirementsService

        for s in (
            await self.session.execute(select(RequirementSet).where(RequirementSet.project_id == project_id))
        ).scalars():
            if (s.metadata_ or {}).get("purpose") == "quality_concept":
                return s.id
        created = await RequirementsService(self.session).create_set(
            RequirementSetCreate(
                project_id=project_id,
                name=_text("requirement_set_name"),
                description=_text("requirement_set_description"),
                metadata={"purpose": "quality_concept"},
            ),
            str(actor or ""),
        )
        return created.id

    async def catalogue_for(self, concept: QualityConcept) -> QualityConceptCatalogue:
        from app.modules.project_governance.catalogue_store import resolve_catalogue
        from app.modules.project_governance.errors import GovernanceError
        from app.modules.quality_concept.catalogue import register_kinds

        register_kinds()
        try:
            return await resolve_catalogue(
                self.session,
                concept.catalogue_source,
                concept.catalogue_id,
                concept.catalogue_version,
                kind=QUALITY_CONCEPT_KIND,
                # The triple is the pin stored on the concept; it was checked when it was written.
                from_pin=True,
            )
        except GovernanceError as exc:
            raise not_found("unknown_catalogue") from exc

    async def refuse_duplicate_concept(self) -> None:
        raise conflict("concept_exists")

    @staticmethod
    def submit_refusal(concept: QualityConcept, errors: list[ev.Finding]) -> str | None:
        """Why ``submit`` would be refused, by the tests ``submit`` itself applies; ``None`` if it would not."""
        if "submit" not in fsm.allowed_actions("concept", concept.state):
            return "invalid_transition"
        return "concept_incomplete" if errors else None

    async def is_area_owner(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Owner or deputy of the governance area tagged for quality in the pinned model."""
        from app.modules.project_governance import public

        host = await hosting.project_host(self.session, project_id)
        if host is None:
            return False
        return any(
            area.code == host.area_code and user_id in (area.owner_user_id, area.deputy_user_id)
            for area in await public.project_areas(self.session, project_id)
        )

    async def _assert_plan_editable(self, concept: QualityConcept) -> None:
        # Whether gates exist only matters for the wording of a plan in force.
        gates = await self.gates_in_use(concept.project_id) if concept.state == "binding" else True
        _refuse(caps.plan_refusal(concept.state, gates), detail=concept.state)

    async def _plan_concept(self, project_id: uuid.UUID) -> QualityConcept:
        await self.reconcile_governance(project_id, reopen=True)
        concept = await self.require_concept(project_id)
        await self._assert_plan_editable(concept)
        return concept

    async def pin_catalogue(
        self, project_id: uuid.UUID, tenant_id: str | None, source: str, catalogue_id: str, version: int | None
    ) -> QualityConcept:
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError
        from app.modules.quality_concept.catalogue import register_kinds

        register_kinds()
        concept = await self._plan_concept(project_id)
        try:
            pinned = await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, catalogue_id, version, kind=QUALITY_CONCEPT_KIND
            )
        except GovernanceError as exc:
            raise QualityConceptError(exc.code, exc.status_code) from exc
        concept.catalogue_source, concept.catalogue_id, concept.catalogue_version = source, catalogue_id, pinned
        await self.session.flush()
        return concept

    async def patch_concept(self, project_id: uuid.UUID, data: Any) -> QualityConcept:
        concept = await self._plan_concept(project_id)
        fields = data.model_dump(exclude_unset=True)
        for key in ("packages", "holidays"):
            if key in fields and fields[key] is None:
                raise QualityConceptError("null_not_allowed", detail=key)
        if "packages" in fields:
            refs = [p["ref"] for p in fields["packages"]]
            if len(refs) != len(set(refs)):
                raise QualityConceptError("package_duplicate")
            concept.packages = fields["packages"]
        if "holidays" in fields:
            concept.holidays = sorted({d.isoformat() for d in fields["holidays"]})
        if "documentation_set_code" in fields:
            code = fields["documentation_set_code"]
            if code is not None and (await self.catalogue_for(concept)).documentation_set(code) is None:
                raise QualityConceptError("documentation_set_unknown")
            concept.documentation_set_code = code
        await self.session.flush()
        return concept

    async def apply_documentation_set(self, project_id: uuid.UUID, actor: uuid.UUID) -> dict[str, list[str]]:
        """Seed what the chosen documentation set asks for: closeout slots and FM data deliverables.

        Idempotent: a slot key or a deliverable type that is already there is left alone. Both
        are written through the owning module's service, which commits as it goes, so every
        refusal is raised before the first write.
        """
        from app.modules.closeout.checklist_templates import CHECKLIST_TEMPLATES, EXTRA_SLOT_DEFS
        from app.modules.closeout.service import CloseoutService
        from app.modules.quality_concept.schemas import QualityRequirementIn
        from app.modules.requirements.models import Requirement, RequirementDeliverable
        from app.modules.requirements.schemas import DeliverableCreate
        from app.modules.requirements.service import RequirementsService

        concept = await self._plan_concept(project_id)
        doc_set = (await self.catalogue_for(concept)).documentation_set(concept.documentation_set_code)
        if doc_set is None:
            raise QualityConceptError("documentation_set_missing")
        if concept.requirement_set_id is None:
            concept.requirement_set_id = await self._ensure_requirement_set(project_id, actor)
        set_id = concept.requirement_set_id
        definitions = {d["slot_key"]: d for defs in CHECKLIST_TEMPLATES.values() for d in defs}
        definitions.update({d["slot_key"]: d for d in EXTRA_SLOT_DEFS})
        unknown = sorted(key for key in doc_set.slot_keys if key not in definitions)
        if unknown:
            raise QualityConceptError("documentation_slot_unknown", detail=", ".join(unknown))
        for fm in doc_set.fm_data:
            # Built here so a deliverable the requirements module would refuse stops the request now.
            DeliverableCreate(deliverable_type=fm.deliverable_type, loi=fm.loi or None)
        closeout = CloseoutService(self.session)
        package = await closeout.create_package(project_id, doc_set.closeout_template or "")
        have = {slot.slot_key for slot in await closeout.repo.list_slots(package.id)}
        slots = [key for key in doc_set.slot_keys if key not in have]
        for key in slots:
            await closeout.add_slot(package, dict(definitions[key]))
        stmt = (
            select(RequirementDeliverable.deliverable_type)
            .join(Requirement, Requirement.id == RequirementDeliverable.requirement_id)
            .where(Requirement.requirement_set_id == set_id)
        )
        present = set((await self.session.execute(stmt)).scalars())
        requirements = RequirementsService(self.session)
        added = []
        for fm in doc_set.fm_data:
            if fm.deliverable_type in present:
                continue
            requirement = await self.add_requirement(
                project_id,
                QualityRequirementIn(category="quality.fm_data", entity=_text("fm_data_entity"), attribute=fm.code),
                actor,
            )
            await requirements.add_deliverable(
                requirement.id, DeliverableCreate(deliverable_type=fm.deliverable_type, loi=fm.loi or None)
            )
            present.add(fm.deliverable_type)
            added.append(fm.code)
        return {"slots_added": slots, "fm_data_added": added}

    async def applicable_packages(self, concept: QualityConcept) -> list[dict[str, Any]]:
        """Packages in scope: the directory when a package module registered one, else the declared scope."""
        from app.core.project_scope_directory import list_contract_packages

        declared = {p["ref"]: p for p in concept.packages or []}
        listed = await list_contract_packages(self.session, concept.project_id)
        if listed is None:
            return list(declared.values())
        out = []
        for p in listed:
            ref = str(p.get("id") or p.get("ref"))
            merged = {"ref": ref, "code": p.get("code", ""), "title": p.get("title", ""), "no_proofs_rationale": ""}
            merged.update({k: v for k, v in declared.get(ref, {}).items() if k == "no_proofs_rationale"})
            out.append(merged)
        return out

    async def completeness(self, concept: QualityConcept) -> list[ev.Finding]:
        """Rules 1 and 2 over the current plan."""
        pid = concept.project_id
        packages = await self.applicable_packages(concept)
        proofs = await self.repo.list(ProofRequirement, pid)
        stages = await self.repo.list(CommissioningStageDef, pid, CommissioningStageDef.order)
        units = await self.repo.list(AcceptanceUnit, pid)
        standards = await self.repo.list(AppliedStandard, pid)
        per_pkg: dict[str, int] = defaultdict(int)
        for p in proofs:
            if p.package_ref:
                per_pkg[p.package_ref] += 1
        findings = ev.concept_completeness(
            standards_count=len(standards),
            packages=[
                ev.PackageScope(p["ref"], per_pkg.get(p["ref"], 0), p.get("no_proofs_rationale", "")) for p in packages
            ],
            stages=[
                ev.StageModelEntry(
                    s.code, s.order, str(s.owner_user_id) if s.owner_user_id else None, s.release_party_role
                )
                for s in stages
            ],
            units=[ev.UnitSummary(u.kind, u.regime_code, tuple(u.package_refs or [])) for u in units],
        )
        stage_codes = [s.code for s in stages]
        unit_ids = [str(u.id) for u in units]
        for p in proofs:
            findings += ev.proof_findings(
                ref=str(p.id),
                deliverer_role=p.deliverer_role,
                required_by_kind=p.required_by_kind,
                required_by_ref=p.required_by_ref,
                stage_codes=stage_codes,
                unit_ids=unit_ids,
            )
        return findings

    async def snapshot(self, concept: QualityConcept) -> dict[str, Any]:
        pid = concept.project_id
        proofs = await self.repo.list(ProofRequirement, pid)
        stages = await self.repo.list(CommissioningStageDef, pid, CommissioningStageDef.order)
        units = await self.repo.list(AcceptanceUnit, pid)
        return {
            "catalogue": f"{concept.catalogue_source}:{concept.catalogue_id}@{concept.catalogue_version}",
            "packages": list(concept.packages or []),
            "proofs": [
                {
                    "id": str(p.id),
                    "package_ref": p.package_ref,
                    "evidence_type": p.evidence_type,
                    "deliverer_role": p.deliverer_role,
                    "required_by": f"{p.required_by_kind}:{p.required_by_ref}",
                    "quantity_rule": p.quantity_rule,
                }
                for p in proofs
            ],
            "stages": [
                {
                    "code": s.code,
                    "order": s.order,
                    "owner_user_id": str(s.owner_user_id) if s.owner_user_id else None,
                    "release_party_role": s.release_party_role,
                    "preconditions": s.preconditions,
                }
                for s in stages
            ],
            "acceptance_units": [
                {"id": str(u.id), "kind": u.kind, "package_refs": u.package_refs, "regime_code": u.regime_code}
                for u in units
            ],
        }

    async def _freeze(self, concept: QualityConcept, reason: str, actor: uuid.UUID | None) -> QualityConceptRevision:
        concept.revision_no += 1
        rev = QualityConceptRevision(
            project_id=concept.project_id,
            concept_id=concept.id,
            revision_no=concept.revision_no,
            reason=reason,
            snapshot=await self.snapshot(concept),
            created_by=actor,
        )
        return await self.repo.add(rev)

    async def submit(self, project_id: uuid.UUID, actor: uuid.UUID) -> QualityConcept:
        concept = await self.require_concept(project_id, lock=True)
        target = _transition("concept", concept.state, "submit")
        findings = [f for f in await self.completeness(concept) if f.severity == ev.ERROR]
        if self.submit_refusal(concept, findings) is not None:
            raise QualityConceptError("concept_incomplete", violations=_findings(findings))
        before = concept.state
        concept.state = target
        concept.submitted_by, concept.submitted_at = actor, _now()
        await self._freeze(concept, "submitted", actor)
        await self.session.flush()
        await self._audit(project_id, actor, "concept", concept.id, "submitted", from_status=before)
        self._publish("concept.submitted", {"project_id": str(project_id), "concept_id": str(concept.id)})
        # A frame document that is already binding sends no further event, so a concept submitted
        # after it is bound here; governance approved the document, this follows it.
        bound = [doc for doc, status in (await self._frame_documents(project_id)).items() if status == "binding"]
        if bound:
            concept.governance_doc_id = bound[0]
            await self._approve_and_bind(concept)
        return concept

    async def gates_in_use(self, project_id: uuid.UUID) -> bool:
        """Whether the project has governance gates at all.

        Asked of the gates, not of the model: a pinned model that cannot be read leaves its
        gates on the project, and there the answer to approval is still the gate.
        """
        from app.modules.project_governance import public

        return bool(await public.project_gates(self.session, project_id))

    async def approve_by_hand(self, project_id: uuid.UUID, actor: uuid.UUID) -> QualityConcept:
        """A project without gates: a manager approves the concept in review and it is in force.

        The frozen revision records who approved and when. Under four eyes whoever submitted
        does not approve.
        """
        concept = await self.require_concept(project_id, lock=True)
        _refuse(
            caps.hand_approval_refusal(
                gates_in_use=await self.gates_in_use(project_id),
                state=concept.state,
                submitted_by=concept.submitted_by,
                actor=actor,
                four_eyes=await self._four_eyes(project_id),
            )
        )
        before = concept.state
        concept.state = _transition("concept", concept.state, "approve", mirror=True)
        await self._freeze(concept, "approved", actor)
        concept.state = _transition("concept", concept.state, "bind", mirror=True)
        await self.session.flush()
        await self._audit(project_id, actor, "concept", concept.id, "approved", from_status=before)
        self._publish("concept.binding", {"project_id": str(project_id), "concept_id": str(concept.id)})
        return concept

    async def reopen_by_hand(self, project_id: uuid.UUID, rationale: str, actor: uuid.UUID) -> QualityConcept:
        """A project without gates: a manager reopens the plan in force, with a reason.

        The plan as it stood is frozen as a revision that carries the reason and who gave it;
        the next submit and approval put the changed plan in force.
        """
        concept = await self.require_concept(project_id, lock=True)
        _refuse(caps.hand_reopen_refusal(gates_in_use=await self.gates_in_use(project_id), state=concept.state))
        before = concept.state
        revision = await self._freeze(concept, "reopened", actor)
        revision.snapshot = {**revision.snapshot, "reopen_reason": rationale}
        concept.state = _transition("concept", concept.state, "reopen", mirror=True)
        await self.session.flush()
        await self._audit(project_id, actor, "concept", concept.id, "reopened", from_status=before)
        self._publish("concept.reopened", {"project_id": str(project_id), "concept_id": str(concept.id)})
        return concept

    async def act_on_concept(self, project_id: uuid.UUID, action: str, actor: uuid.UUID) -> QualityConcept:
        """User action ``return`` (in_review -> draft)."""
        await self.reconcile_governance(project_id)
        concept = await self.require_concept(project_id, lock=True)
        concept.state = _transition("concept", concept.state, action)
        await self.session.flush()
        await self._audit(project_id, actor, "concept", concept.id, action)
        return concept

    async def apply_governance_state(
        self, project_id: uuid.UUID, document_id: uuid.UUID, status: str, *, change_request: str | None = None
    ) -> bool:
        """Mirror of the governance frame document becoming binding (rule 22).

        First binding (a gate decision): a concept in review is approved and bound. A draft or
        revising concept is left alone, since nobody reviewed it; ``submit`` binds it later.

        ``change_request``: the id of the document revision an approved change request made
        binding. The bound plan is frozen as a revision and reopened, so the plan can follow the
        document; the next ``submit`` binds it again. The frozen revision remembers that id, so
        the same event delivered again does not reopen a plan that was bound again since.
        """
        concept = await self.repo.concept(project_id, lock=True)
        if concept is None or status != "binding":
            return False
        if document_id not in await self._frame_documents(project_id):
            return False
        concept.governance_doc_id = document_id
        if concept.state == "binding":
            if not change_request:
                return False
            applied = {
                (r.snapshot or {}).get("bound_revision_id")
                for r in await self.revisions(project_id)
                if r.reason == "change_request"
            }
            if change_request in applied:
                return False
            revision = await self._freeze(concept, "change_request", None)
            revision.snapshot = {**revision.snapshot, "bound_revision_id": change_request}
            concept.state = _transition("concept", concept.state, "reopen", mirror=True)
            await self.session.flush()
            self._publish("concept.reopened", {"project_id": str(project_id), "concept_id": str(concept.id)})
            return True
        return await self._approve_and_bind(concept)

    async def _approve_and_bind(self, concept: QualityConcept) -> bool:
        project_id = concept.project_id
        if concept.state == "in_review":
            concept.state = _transition("concept", concept.state, "approve", mirror=True)
            revision = await self._freeze(concept, "approved", None)
            # What the concept was approved under; a later change of the document is told from it.
            in_force = await self._bound_revision(project_id, concept.governance_doc_id)
            if in_force:
                revision.snapshot = {**revision.snapshot, "document_revision_id": in_force}
        if concept.state == "approved":
            concept.state = _transition("concept", concept.state, "bind", mirror=True)
            await self.session.flush()
            self._publish("concept.binding", {"project_id": str(project_id), "concept_id": str(concept.id)})
            return True
        return False

    async def revisions(self, project_id: uuid.UUID) -> list[QualityConceptRevision]:
        return await self.repo.list(QualityConceptRevision, project_id, QualityConceptRevision.revision_no)

    # ── standards and quality requirements ──────────────────────────────────

    async def create_standard(self, project_id: uuid.UUID, data: Any) -> AppliedStandard:
        concept = await self._plan_concept(project_id)
        for ref in getattr(data, "package_refs", None) or []:
            await self._check_package(concept, ref)
        return await self.repo.add(AppliedStandard(project_id=project_id, **data.model_dump()))

    async def patch_row(self, model: Any, project_id: uuid.UUID, row_id: uuid.UUID, fields: dict[str, Any]) -> Any:
        row = await self.repo.get(model, project_id, row_id)
        if row is None:
            raise not_found("not_found")
        _assign(row, fields)
        await self.session.flush()
        return row

    async def delete_row(
        self, model: Any, project_id: uuid.UUID, row_id: uuid.UUID, owner_kind: str | None = None
    ) -> None:
        row = await self.repo.get(model, project_id, row_id)
        if row is None:
            raise not_found("not_found")
        if owner_kind:
            await self.repo.drop_links(owner_kind, row_id)
        await self.repo.remove(row)

    async def get_row(self, model: Any, project_id: uuid.UUID, row_id: uuid.UUID) -> Any:
        row = await self.repo.get(model, project_id, row_id)
        if row is None:
            raise not_found("not_found")
        return row

    async def list_requirements(self, project_id: uuid.UUID) -> list[Any]:
        from app.modules.requirements.models import Requirement

        concept = await self.require_concept(project_id)
        if concept.requirement_set_id is None:
            return []
        stmt = (
            select(Requirement)
            .where(Requirement.requirement_set_id == concept.requirement_set_id)
            .order_by(Requirement.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_requirement(self, project_id: uuid.UUID, data: Any, actor: uuid.UUID) -> Any:
        from app.modules.requirements.schemas import RequirementCreate
        from app.modules.requirements.service import RequirementsService

        concept = await self._plan_concept(project_id)
        if concept.requirement_set_id is None:
            concept.requirement_set_id = await self._ensure_requirement_set(project_id, actor)
        cat = await self.catalogue_for(concept)
        default_vm = next((c.verification_method for c in cat.requirement_categories if c.code == data.category), "")
        return await RequirementsService(self.session).add_requirement(
            concept.requirement_set_id,
            RequirementCreate(
                entity=data.entity,
                attribute=data.attribute,
                constraint_value=data.constraint_value,
                unit=data.unit,
                category=data.category,
                source_ref=data.source_ref,
                verification_method=data.verification_method or default_vm,
                rationale=data.rationale,
            ),
            str(actor),
        )

    # ── certification ───────────────────────────────────────────────────────

    async def create_certification(self, project_id: uuid.UUID, data: Any) -> CertificationTarget:
        concept = await self.require_concept(project_id)
        scheme = (await self.catalogue_for(concept)).scheme(data.scheme_code)
        if scheme is None:
            raise QualityConceptError("scheme_unknown")
        if scheme.levels and ev.level_index(scheme.levels, data.target_level) is None:
            raise QualityConceptError("level_unknown")
        await self._check_contact(data.assessor_contact_id)
        return await self.repo.add(CertificationTarget(project_id=project_id, state="planned", **data.model_dump()))

    async def patch_certification(
        self, project_id: uuid.UUID, target_id: uuid.UUID, fields: dict[str, Any]
    ) -> CertificationTarget:
        target = await self.get_row(CertificationTarget, project_id, target_id)
        if fields.get("target_level") is not None:
            concept = await self.require_concept(project_id)
            scheme = (await self.catalogue_for(concept)).scheme(target.scheme_code)
            if scheme and scheme.levels and ev.level_index(scheme.levels, fields["target_level"]) is None:
                raise QualityConceptError("level_unknown")
        for key in ("assessor_contact_id",):
            await self._check_contact(fields.get(key))
        await self._check_cde(project_id, fields.get("certificate_cde_id"))
        _assign(target, fields)
        await self.session.flush()
        return target

    async def delete_certification(self, project_id: uuid.UUID, target_id: uuid.UUID) -> None:
        """Remove a target with its credits and their evidence links (no orphaned links)."""
        target = await self.get_row(CertificationTarget, project_id, target_id)
        for credit in await self.repo.list(CreditTarget, project_id):
            if credit.target_id == target.id:
                await self.repo.drop_links("credit", credit.id)
                await self.repo.remove(credit)
        await self.repo.remove(target)

    async def transition_certification(
        self, project_id: uuid.UUID, target_id: uuid.UUID, data: Any
    ) -> CertificationTarget:
        target = await self.get_row(CertificationTarget, project_id, target_id)
        new_state = _transition("certification", target.state, data.action, rationale=data.rationale)
        if data.on is not None and data.on > _now().date():
            raise QualityConceptError("date_in_future", detail="on")
        concept = await self.require_concept(project_id)
        scheme = (await self.catalogue_for(concept)).scheme(target.scheme_code)
        levels = scheme.levels if scheme else []
        if data.action == "certify":
            if not data.achieved_level or not ev.certify_allowed(levels, target.target_level, data.achieved_level):
                raise QualityConceptError("achieved_level_below_target")
            target.achieved_level = data.achieved_level
            target.certified_on = _iso(data.on or _now().date())
        if data.action == "miss_level":
            if not data.achieved_level:
                raise QualityConceptError("achieved_level_required")
            target.achieved_level = data.achieved_level
        if data.action == "register":
            target.registered_on = _iso(data.on or _now().date())
        if data.rationale:
            target.rationale = data.rationale
        target.state = new_state
        await self.session.flush()
        return target

    async def certification_findings(self, project_id: uuid.UUID) -> list[ev.Finding]:
        concept = await self.require_concept(project_id)
        cat = await self.catalogue_for(concept)
        out: list[ev.Finding] = []
        credits = await self.repo.list(CreditTarget, project_id)
        for t in await self.repo.list(CertificationTarget, project_id):
            if t.state in ("abandoned", "certified", "level_missed"):
                continue
            scheme = cat.scheme(t.scheme_code)
            pts = [c.points_targeted for c in credits if c.target_id == t.id and c.state != "dropped"]
            out += ev.certification_target_at_risk(
                scheme.levels if scheme else [],
                t.target_level,
                pts,
                str(t.id),
                points_available=t.points_available,
            )
        return out

    async def add_credits(self, project_id: uuid.UUID, target_id: uuid.UUID, items: list[Any]) -> list[CreditTarget]:
        await self.get_row(CertificationTarget, project_id, target_id)
        await self._check_users(project_id, [getattr(item, "owner_user_id", None) for item in items])
        out = []
        for item in items:
            try:
                async with self.session.begin_nested():
                    out.append(
                        await self.repo.add(
                            CreditTarget(
                                project_id=project_id, target_id=target_id, state="targeted", **item.model_dump()
                            )
                        )
                    )
            except IntegrityError as exc:
                raise conflict("credit_code_exists", detail=item.credit_code) from exc
        return out

    async def patch_credit(self, project_id: uuid.UUID, credit_id: uuid.UUID, data: Any) -> CreditTarget:
        credit = await self.get_row(CreditTarget, project_id, credit_id)
        fields = data.model_dump(exclude_unset=True)
        action = fields.pop("action", None)
        await self._check_users(project_id, [fields.get("owner_user_id")])
        _assign(credit, fields)
        if action:
            credit.state = _transition("credit", credit.state, action)
        await self.session.flush()
        return credit

    # ── proofs ──────────────────────────────────────────────────────────────

    async def _check_proof(self, concept: QualityConcept, data: dict[str, Any]) -> None:
        cat = await self.catalogue_for(concept)
        if "evidence_type" in data and cat.evidence_type(data["evidence_type"]) is None:
            raise QualityConceptError("evidence_type_unknown")
        kind, ref = data.get("required_by_kind"), data.get("required_by_ref")
        if kind == "stage" and ref:
            codes = {s.code for s in await self.repo.list(CommissioningStageDef, concept.project_id)}
            if ref not in codes:
                raise QualityConceptError("proof_due_stage_unknown")
        if kind == "acceptance_unit" and ref:
            try:
                uid = uuid.UUID(ref)
            except ValueError as exc:
                raise QualityConceptError("proof_due_unit_unknown") from exc
            if await self.repo.get(AcceptanceUnit, concept.project_id, uid) is None:
                raise QualityConceptError("proof_due_unit_unknown")
        if kind == "date" and ref and ev.to_date(ref) is None:
            raise QualityConceptError("proof_due_date_invalid")
        if data.get("cx_system_id"):
            await self._require_system(concept.project_id, data["cx_system_id"])
        await self._check_package(concept, data.get("package_ref"))
        await self._check_plant(concept.project_id, data.get("plant_item_id"))
        await self._check_contact(data.get("deliverer_contact_id"))

    # Soft links are stored only after they were found inside the project (or the tenant's
    # contact book); an id from elsewhere is refused and nothing about it is returned.

    async def _check_package(self, concept: QualityConcept, ref: str | None) -> None:
        if ref is None:
            return
        known = {p["ref"] for p in await self.applicable_packages(concept)}
        if ref not in known:
            raise QualityConceptError("package_unknown", detail=ref)

    async def _check_plant(self, project_id: uuid.UUID, plant_item_id: str | None) -> None:
        from app.core.project_scope_directory import plant_item_facts, plant_reader_registered

        if plant_item_id is None:
            return
        if not plant_reader_registered():
            raise QualityConceptError("plant_register_unavailable")
        if await plant_item_facts(self.session, project_id, plant_item_id) is None:
            raise not_found("plant_item_not_found")

    async def _check_contact(self, contact_id: uuid.UUID | None) -> None:
        if contact_id is None:
            return
        # The same rule as the option listing: a contact the caller cannot see is not found.
        if not await references.contact_visible(self.session, self.caller_id, contact_id):
            raise not_found("contact_not_found")

    async def _check_users(self, project_id: uuid.UUID, user_ids: list[Any]) -> None:
        """A person named on a record is someone who can open the project; anyone else is not found."""
        from app.modules.project_governance import public

        for raw in user_ids:
            if raw is None:
                continue
            uid = references.as_uuid(raw)
            if uid is None or not await public.user_can_access_project(self.session, project_id, uid):
                raise not_found("user_not_found")

    async def _check_cde(self, project_id: uuid.UUID, container_id: uuid.UUID | None) -> None:
        if container_id is None:
            return
        if await links.resolve(self.session, project_id, "cde_document", str(container_id)) is None:
            raise not_found("cde_document_not_found")

    async def _check_activity(self, project_id: uuid.UUID, activity_id: str | None) -> None:
        from app.modules.schedule.models import Activity, Schedule

        if activity_id is None:
            return
        try:
            aid = uuid.UUID(str(activity_id))
        except ValueError as exc:
            raise not_found("schedule_activity_not_found") from exc
        stmt = (
            select(Activity.id)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Activity.id == aid)
            .where(Schedule.project_id == project_id)
        )
        if (await self.session.execute(stmt)).scalar_one_or_none() is None:
            raise not_found("schedule_activity_not_found")

    @staticmethod
    def _rule_json(rule: Any) -> dict[str, Any]:
        if not rule:
            return {}
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in rule.items() if v is not None}

    async def create_proof(self, project_id: uuid.UUID, data: Any, actor: uuid.UUID) -> ProofRequirement:
        concept = await self._plan_concept(project_id)
        fields = data.model_dump()
        await self._check_proof(concept, fields)
        fields["quantity_rule"] = self._rule_json(fields.get("quantity_rule"))
        return await self.repo.add(
            ProofRequirement(project_id=project_id, source="edited", decision="none", requested_by=None, **fields)
        )

    async def patch_proof(self, project_id: uuid.UUID, proof_id: uuid.UUID, data: Any) -> ProofRequirement:
        concept = await self._plan_concept(project_id)
        proof = await self.get_row(ProofRequirement, project_id, proof_id)
        fields = data.model_dump(exclude_unset=True)
        merged = {"required_by_kind": proof.required_by_kind, "required_by_ref": proof.required_by_ref, **fields}
        await self._check_proof(concept, merged)
        if "quantity_rule" in fields:
            fields["quantity_rule"] = self._rule_json(fields["quantity_rule"])
        _assign(proof, fields)
        proof.source = "edited"
        await self.session.flush()
        return proof

    async def generate_proofs(self, project_id: uuid.UUID, data: Any) -> dict[str, Any]:
        """Preview (``confirm`` omitted) or create the catalogue default proofs of one package."""
        if data.confirm is not None:
            await self.reconcile_governance(project_id, reopen=True)
        concept = await self.require_concept(project_id)
        if data.confirm is not None:
            await self._assert_plan_editable(concept)
        cat = await self.catalogue_for(concept)
        stages = await self.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)
        if not stages:
            raise QualityConceptError("stage_model_missing")
        wanted: list[str] = list(data.evidence_types or [])
        if not wanted:
            for s in stages:
                wanted += [e for e in s.evidence_types if e not in wanted]
            for p in cat.material_test_plans:
                if p.evidence_type not in wanted:
                    wanted.append(p.evidence_type)
            for extra in ("as_built_drawings", "om_manual", "warranty_certificate"):
                if extra not in wanted:
                    wanted.append(extra)
        existing = {
            p.evidence_type for p in await self.repo.list(ProofRequirement, project_id, package_ref=data.package_ref)
        }
        units = [
            u for u in await self.repo.list(AcceptanceUnit, project_id) if data.package_ref in (u.package_refs or [])
        ]
        rows = []
        for code in wanted:
            et = cat.evidence_type(code)
            if et is None:
                raise QualityConceptError("evidence_type_unknown", detail=code)
            stage = next((s for s in stages if code in (s.evidence_types or [])), None)
            if stage is not None:
                kind, ref = "stage", stage.code
            elif units:
                kind, ref = "acceptance_unit", str(units[0].id)
            else:
                kind, ref = "stage", stages[-1].code
            plan = cat.test_plan_for(code)
            rule = (
                {"per_quantity": plan.frequency.per_quantity, "unit": plan.frequency.unit, "min_count": 1}
                if plan and plan.frequency
                else {}
            )
            rows.append(
                {
                    "evidence_type": code,
                    "deliverer_role": et.default_deliverer,
                    "required_by_kind": kind,
                    "required_by_ref": ref,
                    "quantity_rule": rule,
                    "quantity_rule_review_status": plan.review_status.value if plan else None,
                    "exists": code in existing,
                }
            )
        created: list[ProofRequirement] = []
        if data.confirm is not None:
            chosen = set(data.confirm)
            for r in rows:
                if r["evidence_type"] in chosen and not r["exists"]:
                    created.append(
                        await self.repo.add(
                            ProofRequirement(
                                project_id=project_id,
                                package_ref=data.package_ref,
                                evidence_type=r["evidence_type"],
                                deliverer_role=r["deliverer_role"],
                                required_by_kind=r["required_by_kind"],
                                required_by_ref=r["required_by_ref"],
                                quantity_rule=r["quantity_rule"],
                                source="catalogue_default",
                                decision="none",
                            )
                        )
                    )
        return {"preview": rows, "created": created}

    async def proof_delivery(
        self, project_id: uuid.UUID, proofs: list[ProofRequirement]
    ) -> dict[uuid.UUID, ev.Delivery]:
        """Rules 4-6 for many proofs; one resolver call per linked row."""
        all_links = await self.repo.links_for("proof", [p.id for p in proofs])
        by_owner: dict[uuid.UUID, list[EvidenceLink]] = defaultdict(list)
        for link in all_links:
            by_owner[link.owner_id].append(link)
        out: dict[uuid.UUID, ev.Delivery] = {}
        for p in proofs:
            facts: list[ev.EvidenceFact] = []
            for link in by_owner.get(p.id, []):
                fact = await links.resolve(self.session, project_id, link.link_kind, link.link_id)
                if fact is None:
                    continue
                if link.retest_of and not fact.retest_of:
                    fact = dataclasses.replace(fact, retest_of=link.retest_of)
                facts.append(fact)
            qr = p.quantity_rule or {}
            rule = None
            if qr.get("per_quantity"):
                per = ev.to_decimal(qr["per_quantity"])
                if per is not None and per > 0:
                    rule = ev.QuantityRule(per, str(qr.get("unit", "")), int(qr.get("min_count") or 1))
            placed = links.placed_quantity(facts, qr.get("placed_quantity")) if rule else None
            out[p.id] = ev.derive_delivery(facts, rule=rule, placed_quantity=placed, ref=str(p.id))
        return out

    async def coverage(self, project_id: uuid.UUID) -> dict[str, Any]:
        proofs = await self.repo.list(ProofRequirement, project_id)
        delivery = await self.proof_delivery(project_id, proofs)
        packages: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        findings: list[ev.Finding] = []
        for p in proofs:
            state = ev.proof_state(delivery[p.id].state, p.decision)
            bucket = packages[p.package_ref or ""]
            bucket["total"] += 1
            bucket[state] += 1
            # The proof title (or its evidence type and package) reads better than its id in the
            # message a finding turns into; the rule names the evidence type in the reader's locale.
            named = (
                {"label": p.title} if p.title else {"evidence_type": p.evidence_type, "package": p.package_ref or ""}
            )
            findings += [dataclasses.replace(f, params={**f.params, **named}) for f in delivery[p.id].findings]
        return {
            "packages": [
                {"package_ref": ref or None, **dict(counts), "done": sum(counts[s] for s in _DONE_PROOF)}
                for ref, counts in sorted(packages.items())
            ],
            "findings": _findings(findings),
            "delivery": delivery,
        }

    async def request_waiver(
        self, project_id: uuid.UUID, proof_id: uuid.UUID, rationale: str, actor: uuid.UUID
    ) -> ProofRequirement:
        proof = await self.get_row(ProofRequirement, project_id, proof_id)
        _refuse(caps.waiver_request_refusal(proof.decision))
        proof.decision_rationale, proof.requested_by = rationale, actor
        await self.session.flush()
        return proof

    async def decide_waiver(
        self, project_id: uuid.UUID, proof_id: uuid.UUID, approve: bool, actor: uuid.UUID
    ) -> ProofRequirement:
        """Rule 7: an approver other than the requester (four-eyes from the governance setting)."""
        proof = await self.repo.get(ProofRequirement, project_id, proof_id, lock=True)
        if proof is None:
            raise not_found("not_found")
        # A decided proof has no request pending; rejecting here would wipe the rationale of the waiver.
        _refuse(
            caps.waiver_decision_refusal(
                proof.decision,
                proof.requested_by,
                proof.decision_rationale,
                actor,
                await self._four_eyes(project_id),
            ),
            detail=f"proof:{proof.decision}->waiver_decision",
        )
        if approve:
            proof.decision = _transition("proof", proof.decision, "waive", rationale=proof.decision_rationale)
            proof.decided_by, proof.decided_at = actor, _now()
        else:
            proof.requested_by, proof.decision_rationale = None, ""
        await self.session.flush()
        await self._audit(project_id, actor, "proof", proof.id, "waived" if approve else "waiver_rejected")
        return proof

    async def accept_proof(self, project_id: uuid.UUID, proof_id: uuid.UUID, actor: uuid.UUID) -> ProofRequirement:
        proof = await self.get_row(ProofRequirement, project_id, proof_id)
        delivery = (await self.proof_delivery(project_id, [proof]))[proof.id]
        # Four-eyes: whoever attached the evidence does not also accept it.
        authors = [link.created_by for link in await self.repo.links_for("proof", [proof.id])]
        code = caps.accept_refusal(proof.decision, delivery.state, authors, actor, await self._four_eyes(project_id))
        if code == "proof_not_delivered":
            raise conflict(code, violations=_findings(list(delivery.findings)))
        _refuse(code, detail=f"proof:{proof.decision}->accept")
        proof.decision = _transition("proof", proof.decision, "accept")
        proof.decided_by, proof.decided_at = actor, _now()
        await self.session.flush()
        return proof

    async def reopen_proof(self, project_id: uuid.UUID, proof_id: uuid.UUID) -> ProofRequirement:
        proof = await self.get_row(ProofRequirement, project_id, proof_id)
        proof.decision = _transition("proof", proof.decision, "reopen")
        proof.requested_by = proof.decided_by = None
        proof.decision_rationale = ""
        await self.session.flush()
        return proof

    async def _four_eyes(self, project_id: uuid.UUID) -> bool:
        """The project's four-eyes control as governance states it; on when the project has no model."""
        from app.modules.project_governance import public

        return (await public.project_controls(self.session, project_id)).four_eyes

    # ── evidence links ──────────────────────────────────────────────────────

    async def add_link(self, project_id: uuid.UUID, data: Any, actor: uuid.UUID) -> EvidenceLink:
        """Rule 3: the kind must fulfil the proof's evidence type; a row of another project is 404."""
        owner = await self.repo.get(OWNER_MODELS[data.owner_kind], project_id, data.owner_id)
        if owner is None:
            raise not_found("owner_not_found")
        if data.owner_kind == "proof":
            concept = await self.require_concept(project_id)
            et = (await self.catalogue_for(concept)).evidence_type(owner.evidence_type)
            if et is None or data.link_kind not in et.fulfilled_by:
                raise QualityConceptError("evidence_kind_not_allowed", detail=data.link_kind)
        fact = await links.resolve(self.session, project_id, data.link_kind, data.link_id)
        if fact is None:
            raise not_found("linked_record_not_found")
        if data.retest_of is not None and not await references.retest_target_ok(
            self.session, project_id, data.owner_kind, data.owner_id, data.retest_of
        ):
            raise not_found("retest_link_not_found")
        row = EvidenceLink(
            project_id=project_id,
            owner_kind=data.owner_kind,
            owner_id=data.owner_id,
            link_kind=data.link_kind,
            link_id=str(fact.link_id),
            retest_of=data.retest_of,
            note=data.note,
            created_by=actor,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(row)
        except IntegrityError as exc:
            raise conflict("link_exists") from exc
        self._publish(
            "evidence.linked",
            {"project_id": str(project_id), "owner_kind": data.owner_kind, "owner_id": str(data.owner_id)},
        )
        return row

    async def remove_link(self, project_id: uuid.UUID, link_id: uuid.UUID) -> None:
        await self.delete_row(EvidenceLink, project_id, link_id)

    async def links_of(self, project_id: uuid.UUID, owner_kind: str, owner_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.get_row(OWNER_MODELS[owner_kind], project_id, owner_id)
        out = []
        for link in await self.repo.links_for(owner_kind, [owner_id]):
            fact = await links.resolve(self.session, project_id, link.link_kind, link.link_id)
            out.append({"link": link, "fact": fact})
        return out

    async def candidates(
        self, project_id: uuid.UUID, link_kind: str, q: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        return await links.candidates(self.session, project_id, link_kind, q, limit)

    # ── stage model and progress ────────────────────────────────────────────

    async def apply_catalogue_stages(self, project_id: uuid.UUID) -> list[CommissioningStageDef]:
        """Copy the catalogue levels the project does not have yet (copy on write, idempotent)."""
        concept = await self._plan_concept(project_id)
        cat = await self.catalogue_for(concept)
        have = {s.code for s in await self.repo.list(CommissioningStageDef, project_id)}
        for s in cat.commissioning_stages:
            if s.code in have:
                continue
            await self.repo.add(
                CommissioningStageDef(
                    project_id=project_id,
                    code=s.code,
                    order=s.order,
                    release_party_role=s.default_release_party,
                    release_user_ids=[],
                    preconditions=[p.model_dump() for p in s.default_preconditions],
                    evidence_types=list(s.evidence_types),
                    applies_to={"mode": "all"},
                    catalogue_code=s.code,
                )
            )
        return await self.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)

    async def add_stage(self, project_id: uuid.UUID, data: Any) -> CommissioningStageDef:
        await self._plan_concept(project_id)
        fields = data.model_dump()
        fields["preconditions"] = [dict(p) for p in fields["preconditions"]]
        fields["owner_user_id"] = data.owner_user_id
        await self._check_users(project_id, [data.owner_user_id])
        try:
            async with self.session.begin_nested():
                return await self.repo.add(CommissioningStageDef(project_id=project_id, release_user_ids=[], **fields))
        except IntegrityError as exc:
            raise conflict("stage_code_exists") from exc

    async def patch_stage(self, project_id: uuid.UUID, stage_id: uuid.UUID, data: Any) -> CommissioningStageDef:
        await self._plan_concept(project_id)
        fields = data.model_dump(exclude_unset=True)
        for key in ("preconditions", "release_user_ids"):
            if key in fields and fields[key] is None:
                raise QualityConceptError("null_not_allowed", detail=key)
        if "preconditions" in fields:
            fields["preconditions"] = [dict(p) for p in fields["preconditions"]]
        if "release_user_ids" in fields:
            fields["release_user_ids"] = [str(u) for u in fields["release_user_ids"]]
        await self._check_users(project_id, [fields.get("owner_user_id"), *fields.get("release_user_ids", [])])
        return await self.patch_row(CommissioningStageDef, project_id, stage_id, fields)

    async def delete_stage(self, project_id: uuid.UUID, stage_id: uuid.UUID) -> None:
        await self._plan_concept(project_id)
        stage = await self.get_row(CommissioningStageDef, project_id, stage_id)
        used = await self.repo.list(StageProgress, project_id, stage_code=stage.code)
        if any(p.state not in ("blocked", "ready") for p in used):
            raise conflict("stage_in_use")
        for p in used:
            await self.repo.remove(p)
        await self.repo.remove(stage)

    async def _require_system(self, project_id: uuid.UUID, system_id: Any) -> Any:
        from app.modules.commissioning.models import CxSystem

        sid = system_id if isinstance(system_id, uuid.UUID) else uuid.UUID(str(system_id))
        row = await self.session.get(CxSystem, sid)
        if row is None or row.project_id != project_id:
            raise not_found("system_not_found")
        return row

    @staticmethod
    def _applies(stage: CommissioningStageDef, system: Any) -> bool:
        mode = (stage.applies_to or {}).get("mode", "all")
        values = set((stage.applies_to or {}).get("values") or [])
        if mode == "system_types":
            return system.system_type in values
        if mode == "systems":
            return str(system.id) in values
        return True

    async def sync_progress(self, project_id: uuid.UUID) -> list[StageProgress]:
        """Create the missing (system x stage) rows for every applicable stage; never deletes."""
        from app.modules.commissioning.models import CxSystem

        stages = await self.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)
        systems = list(
            (await self.session.execute(select(CxSystem).where(CxSystem.project_id == project_id))).scalars()
        )
        have = {(p.system_id, p.stage_code) for p in await self.repo.list(StageProgress, project_id)}
        for system in systems:
            for s in stages:
                if self._applies(s, system) and (system.id, s.code) not in have:
                    await self.repo.add(StageProgress(project_id=project_id, system_id=system.id, stage_code=s.code))
        await self.refresh_ready(project_id)
        return await self.repo.list(StageProgress, project_id)

    async def _verified_slot_keys(self, project_id: uuid.UUID) -> set[str]:
        from app.modules.closeout.models import CloseoutBinding, CloseoutPackage, CloseoutSlot

        stmt = (
            select(CloseoutSlot.slot_key)
            .join(CloseoutPackage, CloseoutPackage.id == CloseoutSlot.package_id)
            .join(CloseoutBinding, CloseoutBinding.slot_id == CloseoutSlot.id)
            .where(CloseoutPackage.project_id == project_id)
            .where(CloseoutBinding.is_verified.is_(True))
        )
        return set((await self.session.execute(stmt)).scalars())

    async def evaluate_progress(self, project_id: uuid.UUID) -> list[tuple[StageProgress, list[ev.PreconditionResult]]]:
        """Preconditions of every (system, stage) row. Reads only; each shared fact is loaded once."""
        from app.core.project_scope_directory import plant_item_facts, plant_reader_registered
        from app.modules.commissioning.models import CxIssue, CxSystem
        from app.modules.construction_control.models import HoldGate

        stages = await self.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)
        by_code = {s.code: s for s in stages}
        rows = [r for r in await self.repo.list(StageProgress, project_id) if r.stage_code in by_code]
        if not rows:
            return []
        systems = {
            s.id: s
            for s in (await self.session.execute(select(CxSystem).where(CxSystem.project_id == project_id))).scalars()
        }
        proofs = await self.repo.list(ProofRequirement, project_id)
        delivery = await self.proof_delivery(project_id, proofs)
        done = {p.id: ev.proof_state(delivery[p.id].state, p.decision) in _DONE_PROOF for p in proofs}
        issues: dict[uuid.UUID, list[str]] = defaultdict(list)
        issue_stmt = (
            select(CxIssue.system_id, CxIssue.severity)
            .join(CxSystem, CxSystem.id == CxIssue.system_id)
            .where(CxSystem.project_id == project_id)
            .where(CxIssue.status == "open")
        )
        for system_id, severity in (await self.session.execute(issue_stmt)).all():
            issues[system_id].append(severity)
        gate_stmt = (
            select(HoldGate.attached_id)
            .where(HoldGate.project_id == project_id)
            .where(HoldGate.status == "pending")
            .where(HoldGate.blocks_progress.is_(True))
            .where(HoldGate.attached_kind == "cx_stage")
        )
        pending_gates = set((await self.session.execute(gate_stmt)).scalars())
        slots = frozenset(await self._verified_slot_keys(project_id))
        released: dict[str, set[str]] = defaultdict(set)
        per_system: dict[uuid.UUID, list[StageProgress]] = defaultdict(list)
        for r in rows:
            per_system[r.system_id].append(r)
            if r.state == "released":
                released[r.stage_code].add(str(r.system_id))
        released_frozen = {k: frozenset(v) for k, v in released.items()}
        reader = plant_reader_registered()
        out = []
        for system_id, mine in per_system.items():
            mine.sort(key=lambda r: by_code[r.stage_code].order)
            system = systems.get(system_id)
            plant_id = getattr(system, "plant_item_id", None)
            plant = await plant_item_facts(self.session, project_id, plant_id) if plant_id and reader else None
            reason = "no_plant_item_linked" if not plant_id else ("" if reader else "no_plant_register")
            # In scope for this system: its own proofs and the ones no system is named on.
            types = ev.delivered_evidence_types(
                (p.evidence_type, done[p.id]) for p in proofs if p.cx_system_id in (None, system_id)
            )
            states = [r.state for r in mine]
            for index, r in enumerate(mine):
                earlier = {str(e.id) for e in mine[:index]}
                ctx = ev.StageContext(
                    previous_state=ev.effective_previous_state(states, index),
                    delivered_evidence_types=types,
                    open_cx_issue_severities=tuple(issues.get(system_id, ())),
                    unreleased_gate_count=len(earlier & pending_gates),
                    plant_item_delivered=plant.get("delivered") if plant is not None else None,
                    delivery_limit_agreed=plant.get("delivery_limit_agreed") if plant is not None else None,
                    plant_unavailable_reason=reason,
                    authority_acceptance_present="authority_acceptance" in types,
                    released_systems_by_stage=released_frozen,
                    scope_system_ids=frozenset(r.depends_on_system_ids or []),
                    delivered_slot_keys=slots,
                )
                out.append((r, ev.evaluate_preconditions(by_code[r.stage_code].preconditions or [], ctx)))
        return out

    async def refresh_ready(self, project_id: uuid.UUID) -> None:
        """Recompute ``blocked`` / ``ready`` (rules 8, 9) and catch up with gates already released.

        Only rows whose state changes are written. Called from write routes only.
        """
        await self.reconcile_governance(project_id)
        await self.reconcile_released_gates(project_id)
        for row, results in await self.evaluate_progress(project_id):
            target = ev.computed_stage_state(row.state, results)
            if target != row.state:
                row.state = target
        await self._flush_versioned()

    async def _flush_versioned(self) -> None:
        try:
            await self.session.flush()
        except StaleDataError as exc:
            raise conflict("concurrent_update") from exc

    async def reconcile_released_gates(self, project_id: uuid.UUID) -> int:
        """Release the rows whose hold gate is released although its event never arrived (rule 10)."""
        from app.modules.construction_control.models import HoldGate

        stmt = (
            select(HoldGate.id)
            .join(StageProgress, StageProgress.hold_gate_id == HoldGate.id)
            .where(StageProgress.project_id == project_id)
            .where(StageProgress.state.in_(("passed", "stale")))
            .where(HoldGate.status == "released")
        )
        moved = 0
        for gate_id in list((await self.session.execute(stmt)).scalars()):
            moved += await self.apply_gate_released(gate_id)
        return moved

    async def _progress(self, project_id: uuid.UUID, progress_id: uuid.UUID) -> StageProgress:
        row = await self.repo.get(StageProgress, project_id, progress_id, lock=True)
        if row is None:
            raise not_found("not_found")
        return row

    async def open_test(self, project_id: uuid.UUID, progress_id: uuid.UUID, actor: uuid.UUID) -> StageProgress:
        await self.refresh_ready(project_id)
        row = await self._progress(project_id, progress_id)
        was_released = row.state in ("released", "stale")
        row.state = _transition("stage", row.state, "open_test")
        if was_released:
            # The old gate signed the previous test; the re-test needs a release of its own.
            row.hold_gate_id = row.released_at = row.released_by = None
        await self._flush_versioned()
        if was_released:
            await self._stale_dependants(project_id, row.system_id)
        await self._audit(project_id, actor, "stage_progress", row.id, "open_test")
        return row

    async def _stale_dependants(self, project_id: uuid.UUID, system_id: uuid.UUID) -> None:
        """Rule 12: released rows that depend on a system now back in testing go stale."""
        rows = await self.repo.list(StageProgress, project_id)
        deps = {str(r.id): frozenset(r.depends_on_system_ids or []) for r in rows}
        stale = set(ev.stale_dependants(str(system_id), deps, [str(r.id) for r in rows if r.state == "released"]))
        for r in rows:
            if str(r.id) in stale:
                r.state = _transition("stage", r.state, "go_stale", mirror=True)
                # The gate signed a state that no longer holds; reconciling must not release on it again.
                r.hold_gate_id = None
        await self.session.flush()

    async def pass_refusal(self, project_id: uuid.UUID, row: StageProgress) -> str | None:
        """Why this row cannot be recorded as passed now; also the reason behind its ``record_pass`` flag.

        A stage that names evidence types needs one linked record of a fulfilling kind that
        passed with a valid calibration.
        """
        code = caps.transition_refusal("stage", row.state, "pass")
        if code is not None:
            return code
        stage = next(
            (s for s in await self.repo.list(CommissioningStageDef, project_id) if s.code == row.stage_code), None
        )
        required = set(stage.evidence_types or []) if stage else set()
        if not required:
            return None
        concept = await self.require_concept(project_id)
        cat = await self.catalogue_for(concept)
        kinds_ok = {lk for code in required if (et := cat.evidence_type(code)) for lk in et.fulfilled_by}
        for link in await self.repo.links_for("stage_progress", [row.id]):
            fact = await links.resolve(self.session, project_id, link.link_kind, link.link_id)
            if fact and fact.outcome == "pass" and not fact.calibration_expired and link.link_kind in kinds_ok:
                return None
        return "stage_evidence_missing"

    async def record_result(
        self, project_id: uuid.UUID, progress_id: uuid.UUID, data: Any, actor: uuid.UUID
    ) -> StageProgress:
        from app.modules.commissioning.models import CxIssue

        row = await self._progress(project_id, progress_id)
        if data.result == "pass":
            _refuse(await self.pass_refusal(project_id, row))
            row.state = _transition("stage", row.state, "pass")
        else:
            row.state = _transition("stage", row.state, "fail")
            # A gate asked for the passed result signs nothing once that result failed.
            row.hold_gate_id = None
            issue = CxIssue(
                system_id=row.system_id,
                description=data.note or _text("stage_test_failed", stage=row.stage_code),
                severity=data.severity,
                status="open",
                raised_by=str(actor),
                metadata_={"quality_concept_stage": row.stage_code, "stage_progress_id": str(row.id)},
            )
            self.session.add(issue)
            await self.session.flush()
            row.last_issue_id = issue.id
            row.state = _transition("stage", row.state, "open_test")
        await self.session.flush()
        await self._audit(project_id, actor, "stage_progress", row.id, f"result_{data.result}")
        return row

    async def request_release(self, project_id: uuid.UUID, progress_id: uuid.UUID, actor: uuid.UUID) -> Any:
        """Rule 10: create the construction_control hold gate that alone can release this stage."""
        from app.modules.construction_control.gating_service import GatingService
        from app.modules.construction_control.models import HoldGate
        from app.modules.construction_control.schemas import HoldGateCreate

        row = await self._progress(project_id, progress_id)
        held = await self.session.get(HoldGate, row.hold_gate_id) if row.hold_gate_id is not None else None
        _refuse(caps.release_request_refusal(row.state, held.status if held is not None else None))
        stage = next(s for s in await self.repo.list(CommissioningStageDef, project_id) if s.code == row.stage_code)
        system = await self._require_system(project_id, row.system_id)
        gate = await GatingService(self.session).create_gate(
            HoldGateCreate(
                project_id=project_id,
                point_type="hold",
                title=f"{system.name}: {stage.name_override or stage.code}",
                required_party_role=stage.release_party_role,
                attached_kind="cx_stage",
                attached_id=str(row.id),
                metadata={"quality_concept": {"stage_code": row.stage_code, "system_id": str(row.system_id)}},
            ),
            str(actor),
        )
        row.hold_gate_id = gate.id
        await self.session.flush()
        return gate

    async def apply_gate_released(self, gate_id: uuid.UUID) -> bool:
        """Mirror of ``cc.gate.released`` for ``attached_kind=cx_stage`` (rule 10). Idempotent."""
        from app.modules.construction_control.gating_service import party_role_satisfies
        from app.modules.construction_control.models import HoldGate

        gate = await self.session.get(HoldGate, gate_id)
        if gate is None or gate.attached_kind != "cx_stage" or gate.status != "released":
            return False
        row = await self.repo.progress_for_gate(gate.id)
        if row is None or row.project_id != gate.project_id or str(row.id) != gate.attached_id:
            return False
        if row.state == "released":
            return False
        stage = next(
            (s for s in await self.repo.list(CommissioningStageDef, row.project_id) if s.code == row.stage_code), None
        )
        if stage is None or not party_role_satisfies(gate.released_party_role or "", stage.release_party_role):
            return False
        if stage.release_user_ids and gate.released_by not in stage.release_user_ids:
            return False
        row.state = _transition("stage", row.state, "release", mirror=True)
        row.released_at = _now()
        row.released_by = uuid.UUID(gate.released_by) if gate.released_by else None
        try:
            await self.session.flush()
        except StaleDataError as exc:
            raise conflict("concurrent_release") from exc
        await self._audit(row.project_id, row.released_by, "stage_progress", row.id, "released", gate=str(gate.id))
        self._publish(
            "stage.released",
            {"project_id": str(row.project_id), "progress_id": str(row.id), "stage_code": row.stage_code},
        )
        return True

    async def mark_not_applicable(self, project_id: uuid.UUID, progress_id: uuid.UUID, rationale: str) -> StageProgress:
        row = await self._progress(project_id, progress_id)
        row.state = _transition("stage", row.state, "not_applicable", rationale=rationale)
        row.rationale = rationale
        await self.session.flush()
        return row

    async def reinstate(self, project_id: uuid.UUID, progress_id: uuid.UUID) -> StageProgress:
        """Undo ``not_applicable``: the row is blocked again and follows its preconditions."""
        row = await self._progress(project_id, progress_id)
        row.state = _transition("stage", row.state, "reinstate")
        row.rationale = ""
        await self._flush_versioned()
        return row

    async def set_dependencies(
        self, project_id: uuid.UUID, progress_id: uuid.UUID, system_ids: list[uuid.UUID]
    ) -> StageProgress:
        row = await self._progress(project_id, progress_id)
        for sid in system_ids:
            await self._require_system(project_id, sid)
        row.depends_on_system_ids = [str(s) for s in system_ids]
        await self.session.flush()
        return row

    async def final_stage_blockers(self, project_id: uuid.UUID, system_id: uuid.UUID) -> list[str]:
        """Rule 11: the final applicable stage of the system must be released."""
        concept = await self.repo.concept(project_id)
        if concept is None:
            return []
        stages = await self.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)
        if not stages:
            return []
        system = await self._require_system(project_id, system_id)
        applicable = [s for s in stages if self._applies(s, system)]
        if not applicable:
            return []
        rows = {r.stage_code: r for r in await self.repo.list(StageProgress, project_id, system_id=system_id)}
        final = [
            s for s in reversed(applicable) if (rows.get(s.code) is None or rows[s.code].state != "not_applicable")
        ]
        if not final:
            return []
        last = final[0]
        row = rows.get(last.code)
        if row is None or row.state != "released":
            return [_text("final_stage_not_released", stage=last.code)]
        return []

    # ── acceptance ──────────────────────────────────────────────────────────

    async def _check_unit(self, concept: QualityConcept, fields: dict[str, Any]) -> None:
        cat = await self.catalogue_for(concept)
        if fields.get("regime_code") and cat.regime(fields["regime_code"]) is None:
            raise QualityConceptError("regime_unknown")
        regime = cat.regime(fields.get("regime_code"))
        if fields.get("kind") in ("partial_package", "partial_section") and regime and not regime.partial_allowed:
            raise QualityConceptError("partial_not_allowed_by_regime")
        if fields.get("kind") == "partial_package" and not fields.get("package_refs"):
            raise QualityConceptError("partial_needs_package")
        for ref in fields.get("package_refs") or []:
            await self._check_package(concept, ref)
        await self._check_activity(concept.project_id, fields.get("schedule_activity_id"))
        for unit_id in (fields.get("preconditions") or {}).get("include_units", []):
            if await self.repo.get(AcceptanceUnit, concept.project_id, uuid.UUID(str(unit_id))) is None:
                raise not_found("included_unit_not_found")

    async def create_unit(self, project_id: uuid.UUID, data: Any) -> AcceptanceUnit:
        concept = await self._plan_concept(project_id)
        fields = data.model_dump()
        await self._check_unit(concept, fields)
        pre = fields.pop("preconditions")
        pre["include_units"] = [str(u) for u in pre.get("include_units", [])]
        fields["planned_date"] = _iso(fields["planned_date"])
        return await self.repo.add(
            AcceptanceUnit(
                project_id=project_id, state="planned", preconditions=pre, reservations=[], refusal_defects=[], **fields
            )
        )

    async def patch_unit(self, project_id: uuid.UUID, unit_id: uuid.UUID, data: Any) -> AcceptanceUnit:
        await self.reconcile_handover(project_id)
        # Every write that asks whether the plan is open follows an approved change request first.
        await self.reconcile_governance(project_id, reopen=True)
        concept = await self.require_concept(project_id)
        unit = await self.get_row(AcceptanceUnit, project_id, unit_id)
        fields = data.model_dump(exclude_unset=True)
        if "preconditions" in fields and fields["preconditions"] is None:
            raise QualityConceptError("null_not_allowed", detail="preconditions")
        plan_fields = set(fields) - {"handover_package_id"}
        if plan_fields:
            await self._assert_plan_editable(concept)
        await self._check_unit(concept, {"kind": unit.kind, "package_refs": unit.package_refs, **fields})
        if "preconditions" in fields:
            fields["preconditions"]["include_units"] = [
                str(u) for u in fields["preconditions"].get("include_units", [])
            ]
        if "planned_date" in fields:
            fields["planned_date"] = _iso(fields["planned_date"])
        if "handover_package_id" in fields and fields["handover_package_id"] is not None:
            await self._link_handover(unit, fields["handover_package_id"], {**fields})
        _assign(unit, fields)
        await self._flush_versioned()
        return unit

    async def _link_handover(self, unit: AcceptanceUnit, package_id: uuid.UUID, fields: dict[str, Any]) -> None:
        """The act lives in construction_control; it learns this unit's regime and package scope."""
        from app.modules.construction_control.models import HandoverPackage

        package = await self.session.get(HandoverPackage, package_id)
        if package is None or package.project_id != unit.project_id:
            raise not_found("handover_package_not_found")
        if package.status in ("issued", "revoked"):
            raise conflict("handover_package_locked")
        package.regime_code = fields.get("regime_code", unit.regime_code)
        if unit.kind in ("partial_package", "partial_section"):
            mine = list(fields.get("package_refs", unit.package_refs) or [])
            package.package_refs = sorted({*(package.package_refs or []), *mine})

    async def unmet_preconditions(
        self, project_id: uuid.UUID, unit: AcceptanceUnit, facts: ProjectFacts | None = None
    ) -> list[ev.UnmetPrecondition]:
        """Rules 13, 16, 17: what stands between this unit and its acceptance.

        Scope is the unit's packages; a unit that names none (the total acceptance) covers the
        whole project. Open NCRs count by severity: minor ones are ``defects`` (a regime may take
        them as reservations), the rest are ``material_defects``. Pending hold gates always count.

        ``facts``: the project-wide reads, shared by a caller that asks about many units.
        """
        from app.modules.commissioning.models import CxSystem
        from app.modules.construction_control.models import HoldGate
        from app.modules.ncr.models import NCR

        pre = unit.preconditions or {}
        out: list[ev.UnmetPrecondition] = []
        refs = list(unit.package_refs or [])
        facts = facts or ProjectFacts()
        proofs = await facts.get("proofs", lambda: self.repo.list(ProofRequirement, project_id))
        scoped = [p for p in proofs if (p.package_ref in refs if refs else True)]
        # Systems in scope: the ones the unit's package proofs name; none named means every system.
        scope_systems = {str(p.cx_system_id) for p in scoped if p.cx_system_id} if refs else set()
        rows = await facts.get("progress", lambda: self.repo.list(StageProgress, project_id))
        progress = [(str(r.system_id), r.stage_code, r.state) for r in rows]
        out += ev.stages_unmet(pre.get("stages", []), progress, scope_systems)
        wanted = set(pre.get("evidence_types", []))
        due_here = [
            p
            for p in scoped
            if (p.required_by_kind == "acceptance_unit" and p.required_by_ref == str(unit.id))
            or (wanted and p.evidence_type in wanted)
        ]
        # Delivery is derived proof by proof, so one pass over all proofs serves every unit.
        delivery = await facts.get("delivery", lambda: self.proof_delivery(project_id, proofs)) if due_here else {}
        for p in due_here:
            if ev.proof_state(delivery[p.id].state, p.decision) not in _DONE_PROOF:
                out.append(ev.UnmetPrecondition("proofs", str(p.id)))
        slot_keys = pre.get("slot_keys", [])
        verified = await facts.get("verified", lambda: self._verified_slot_keys(project_id)) if slot_keys else set()
        for key in slot_keys:
            if key not in verified:
                out.append(ev.UnmetPrecondition("documentation", key))
        ncr_stmt = (
            select(NCR.id, NCR.severity, NCR.package_ref)
            .where(NCR.project_id == project_id)
            .where(NCR.status.notin_(("closed", "void")))
        )
        gate_stmt = (
            select(HoldGate.id, HoldGate.package_ref)
            .where(HoldGate.project_id == project_id)
            .where(HoldGate.status == "pending")
            .where(HoldGate.blocks_progress.is_(True))
        )

        async def _all(stmt: Any) -> list[Any]:
            return list((await self.session.execute(stmt)).all())

        # Every open defect and pending gate of the project is read once; the unit's packages pick from it.
        for ncr_id, severity, package in await facts.get("ncrs", lambda: _all(ncr_stmt)):
            if refs and package not in refs:
                continue
            kind = "defects" if severity in MINOR_NCR else "material_defects"
            out.append(ev.UnmetPrecondition(kind, str(ncr_id)))
        for gate_id, package in await facts.get("gates", lambda: _all(gate_stmt)):
            if refs and package not in refs:
                continue
            out.append(ev.UnmetPrecondition("hold_gates", str(gate_id)))
        if unit.kind == "total":
            included = set(pre.get("include_units", []))
            partials = [
                (str(u.id), u.state, str(u.id) in included)
                for u in await facts.get("units", lambda: self.repo.list(AcceptanceUnit, project_id))
                if u.kind in ("partial_package", "partial_section")
            ]
            out += ev.total_acceptance_unmet(partials)
        if unit.kind == "handover_to_operation":
            for system in (
                await self.session.execute(select(CxSystem).where(CxSystem.project_id == project_id))
            ).scalars():
                if await self.final_stage_blockers(project_id, system.id):
                    out.append(ev.UnmetPrecondition("final_stage", str(system.id)))
            out += [ev.UnmetPrecondition("fm_data", d) for d in await self._fm_data_open(project_id)]
        return out

    async def _fm_data_open(self, project_id: uuid.UUID) -> list[str]:
        from app.modules.requirements.models import Requirement, RequirementDeliverable

        concept = await self.require_concept(project_id)
        if concept.requirement_set_id is None:
            return []
        stmt = (
            select(RequirementDeliverable.id)
            .join(Requirement, Requirement.id == RequirementDeliverable.requirement_id)
            .where(Requirement.requirement_set_id == concept.requirement_set_id)
            .where(RequirementDeliverable.accepted_at.is_(None))
        )
        return [str(i) for i in (await self.session.execute(stmt)).scalars()]

    async def request_acceptance(
        self, project_id: uuid.UUID, unit_id: uuid.UUID, data: Any, actor: uuid.UUID
    ) -> AcceptanceUnit:
        await self.reconcile_handover(project_id)
        unit = await self.repo.get(AcceptanceUnit, project_id, unit_id, lock=True)
        if unit is None:
            raise not_found("not_found")
        target = _transition("acceptance", unit.state, "request")
        concept = await self.require_concept(project_id)
        regime = (await self.catalogue_for(concept)).regime(unit.regime_code)
        if regime is None:
            raise QualityConceptError("acceptance_regime_missing")
        unmet = await self.unmet_preconditions(project_id, unit)
        blocking, reservations = ev.acceptance_request_check(
            unmet, reservable=regime.reservable, with_reservations=data.with_reservations
        )
        if blocking:
            raise QualityConceptError("acceptance_preconditions_unmet", violations=_findings(blocking))
        unit.reservations = [{"kind": r.kind, "ref": r.ref, "note": data.notes.get(r.ref, "")} for r in reservations]
        unit.state = target
        await self.session.flush()
        await self._audit(project_id, actor, "acceptance_unit", unit.id, "requested", reservations=len(reservations))
        self._publish("acceptance.requested", {"project_id": str(project_id), "unit_id": str(unit.id)})
        return unit

    async def act_on_unit(
        self, project_id: uuid.UUID, unit_id: uuid.UUID, action: str, actor: uuid.UUID
    ) -> AcceptanceUnit:
        """``schedule_inspection``, ``withdraw`` and ``confirm_deemed`` (rule 14: human confirms).

        The deemed date is compared with the server's date; no caller supplies the clock.
        """
        await self.reconcile_handover(project_id)
        unit = await self.repo.get(AcceptanceUnit, project_id, unit_id, lock=True)
        if unit is None:
            raise not_found("not_found")
        target = _transition("acceptance", unit.state, action)
        if action == "confirm_deemed":
            due = [d for d in await self.deemed_dates(project_id, unit) if d.deemed_on and d.deemed_on <= _now().date()]
            if not due:
                raise conflict("deemed_acceptance_not_due")
            unit.accepted_on = min(d.deemed_on for d in due if d.deemed_on).isoformat()
        unit.state = target
        await self._flush_versioned()
        await self._audit(project_id, actor, "acceptance_unit", unit.id, action)
        return unit

    async def refuse(self, project_id: uuid.UUID, unit_id: uuid.UUID, data: Any, actor: uuid.UUID) -> AcceptanceUnit:
        await self.reconcile_handover(project_id)
        unit = await self.repo.get(AcceptanceUnit, project_id, unit_id, lock=True)
        if unit is None:
            raise not_found("not_found")
        concept = await self.require_concept(project_id)
        regime = (await self.catalogue_for(concept)).regime(unit.regime_code)
        if regime is not None and regime.refusal_needs_defect and not data.defects:
            raise QualityConceptError("refusal_needs_defect")
        unit.state = _transition("acceptance", unit.state, "refuse", rationale=data.rationale)
        unit.refusal_reason, unit.refusal_defects = data.rationale, list(data.defects)
        await self.session.flush()
        await self._audit(project_id, actor, "acceptance_unit", unit.id, "refused")
        return unit

    async def record_dates(self, project_id: uuid.UUID, unit_id: uuid.UUID, data: Any) -> AcceptanceUnit:
        """The dates a deemed acceptance counts from. Open until the unit is decided; never in the future."""
        await self.reconcile_handover(project_id)
        unit = await self.repo.get(AcceptanceUnit, project_id, unit_id, lock=True)
        if unit is None:
            raise not_found("not_found")
        _refuse(caps.dates_refusal(unit.state), detail=unit.state)
        raw = data.model_dump(exclude_unset=True)
        today = _now().date()
        for key in ("completion_notice_at", "use_started_at"):
            if raw.get(key) is not None and raw[key] > today:
                raise QualityConceptError("date_in_future", detail=key)
        _assign(unit, {k: _iso(v) for k, v in raw.items()})
        await self._flush_versioned()
        return unit

    async def deemed_dates(
        self, project_id: uuid.UUID, unit: AcceptanceUnit, *, concept: Any = None, catalogue: Any = None
    ) -> list[ev.DeemedDate]:
        """``concept`` and ``catalogue``: already read by a caller that asks about many units."""
        concept = concept or await self.require_concept(project_id)
        regime = (catalogue or await self.catalogue_for(concept)).regime(unit.regime_code)
        if regime is None:
            return []
        holidays = [d for h in concept.holidays or [] if (d := ev.to_date(h))]
        return ev.deemed_dates(
            regime.deemed_acceptance,
            completion_notice_at=unit.completion_notice_at,
            use_started_at=unit.use_started_at,
            deadline_at=unit.deadline_at,
            holidays=holidays,
        )

    async def reconcile_handover(self, project_id: uuid.UUID) -> int:
        """Follow the acts issued or revoked although their event never arrived (rule 15).

        A unit is accepted only through its act, so an accepted unit on a revoked act missed
        the revocation; nothing a person decided is undone. Only acts with a unit that can
        still move are touched, so a project in step costs one read. Called from the unit
        write routes only.
        """
        from app.modules.construction_control.models import HandoverPackage

        await self.reconcile_governance(project_id)
        stmt = (
            select(HandoverPackage.id, HandoverPackage.status, AcceptanceUnit.state)
            .join(AcceptanceUnit, AcceptanceUnit.handover_package_id == HandoverPackage.id)
            .where(AcceptanceUnit.project_id == project_id)
            .where(HandoverPackage.project_id == project_id)
            .where(HandoverPackage.status.in_(("issued", "revoked")))
        )
        issued: set[uuid.UUID] = set()
        revoked: set[uuid.UUID] = set()
        for package_id, status, state in (await self.session.execute(stmt)).all():
            if status == "issued" and _follows_issue(state):
                issued.add(package_id)
            elif status == "revoked" and state in _ACCEPTED_BY_ACT:
                revoked.add(package_id)
        moved = 0
        for package_id in issued:
            moved += len(await self.apply_handover_issued(package_id, None))
        for package_id in revoked:
            moved += len(await self.apply_handover_revoked(package_id))
        return moved

    async def apply_handover_issued(self, package_id: uuid.UUID, issued_at: str | None) -> list[AcceptanceUnit]:
        """Mirror of ``cc.handover.issued``: units pointing at the act are accepted (rule 15).

        Each unit moves on its own: one that cannot (already decided another way) is logged and
        skipped, so it never keeps the other units of the certificate from being accepted.
        """
        from app.modules.construction_control.models import HandoverPackage

        package = await self.session.get(HandoverPackage, package_id)
        if package is None or package.status != "issued":
            return []
        stmt = (
            select(AcceptanceUnit)
            .where(AcceptanceUnit.project_id == package.project_id)
            .where(AcceptanceUnit.handover_package_id == package.id)
            .with_for_update()
        )
        moved = []
        for unit in (await self.session.execute(stmt)).scalars():
            if unit.state in ev.ACCEPTED_STATES:
                continue
            try:
                state = _state_after_issue(unit.state, bool(unit.reservations))
            except QualityConceptError:
                logger.warning(
                    "quality_concept: unit %s in state %s cannot follow handover package %s",
                    unit.id,
                    unit.state,
                    package.id,
                )
                continue
            unit.state = state
            unit.accepted_on = (ev.to_date(issued_at or package.issued_at) or _now().date()).isoformat()
            moved.append(unit)
            self._publish("acceptance.accepted", {"project_id": str(unit.project_id), "unit_id": str(unit.id)})
        await self.session.flush()
        return moved

    async def apply_handover_revoked(self, package_id: uuid.UUID) -> list[AcceptanceUnit]:
        """Mirror of ``cc.handover.revoked``: units accepted by the act are requested again.

        Their confirmed effects are marked revoked, so they are proposed again after a new
        acceptance. Warranty starts already written are not rewound here; the next confirmation
        of the same effect may move exactly those warranties.
        """
        from app.modules.construction_control.models import HandoverPackage

        package = await self.session.get(HandoverPackage, package_id)
        if package is None or package.status != "revoked":
            return []
        stmt = (
            select(AcceptanceUnit)
            .where(AcceptanceUnit.project_id == package.project_id)
            .where(AcceptanceUnit.handover_package_id == package.id)
            .with_for_update()
        )
        moved = []
        for unit in (await self.session.execute(stmt)).scalars():
            if unit.state not in _ACCEPTED_BY_ACT:
                continue
            unit.state = _transition("acceptance", unit.state, "revoke", mirror=True)
            unit.accepted_on = None
            for effect in await self.repo.effects(unit.id):
                effect.outcome = {**(effect.outcome or {}), "revoked_at": _now().isoformat()}
            moved.append(unit)
            self._publish("acceptance.revoked", {"project_id": str(unit.project_id), "unit_id": str(unit.id)})
        await self.session.flush()
        return moved

    async def proposed_effects(
        self, project_id: uuid.UUID, unit: AcceptanceUnit, *, catalogue: Any = None, effects: Any = None
    ) -> list[Any]:
        """``catalogue`` and ``effects`` (of this unit): already read by a caller that asks about many units."""
        if catalogue is None:
            catalogue = await self.catalogue_for(await self.require_concept(project_id))
        regime = catalogue.regime(unit.regime_code)
        if regime is None:
            return []
        if effects is None:
            effects = await self.repo.effects(unit.id)
        applied = [e.effect for e in effects if not (e.outcome or {}).get("revoked_at")]
        return ev.proposed_effects(regime.effects, applied)

    async def confirm_effect(
        self, project_id: uuid.UUID, unit_id: uuid.UUID, data: Any, actor: uuid.UUID
    ) -> AcceptanceEffect:
        """Rule 15: apply one proposed effect on a human confirm; a second confirm returns the first.

        Nothing is stored unless something was written: a warranty effect that finds no warranty
        to start is refused (``no_warranty_to_start``), so it can be confirmed once one exists.
        An effect revoked with its certificate is confirmed again on the same row.
        """
        from app.core.acceptance_effects import apply_effect

        await self.reconcile_handover(project_id)

        unit = await self.get_row(AcceptanceUnit, project_id, unit_id)
        _refuse(caps.effect_refusal(unit.state))
        existing = next((e for e in await self.repo.effects(unit.id) if e.effect == data.effect), None)
        if existing is not None and not (existing.outcome or {}).get("revoked_at"):
            return existing
        concept = await self.require_concept(project_id)
        regime = (await self.catalogue_for(concept)).regime(unit.regime_code)
        spec = next((e for e in (regime.effects if regime else []) if e.effect == data.effect), None)
        if spec is None:
            raise QualityConceptError("effect_not_in_regime")
        accepted = ev.to_date(unit.accepted_on) or _now().date()
        on = data.effective_date or accepted
        if on < accepted:
            raise QualityConceptError("effect_before_acceptance")
        own = set((existing.outcome or {}).get("warranty_ids", [])) if existing is not None else set()
        row = existing or AcceptanceEffect(project_id=project_id, unit_id=unit.id, effect=data.effect, outcome={})
        row.effective_date = on.isoformat()
        row.source_url = spec.source_url or spec.source_title
        row.review_status = spec.review_status.value
        row.confirmed_by, row.confirmed_at = actor, _now()
        try:
            async with self.session.begin_nested():
                if existing is None:
                    await self.repo.add(row)
                if data.effect in WARRANTY_EFFECTS:
                    started = await self._start_warranties(
                        project_id, unit, on, regime.limitation_regime_code if regime else None, data.warranty_ids, own
                    )
                    if not started:
                        raise QualityConceptError("no_warranty_to_start")
                    row.outcome = {"warranty_ids": started}
                else:
                    handled = await apply_effect(
                        self.session,
                        project_id,
                        {
                            "effect": data.effect,
                            "unit_id": str(unit.id),
                            "effective_date": row.effective_date,
                            "package_refs": list(unit.package_refs or []),
                        },
                    )
                    row.outcome = {"handled_by": handled, "package_refs": list(unit.package_refs or [])}
                await self.session.flush()
        except IntegrityError:
            again = next((e for e in await self.repo.effects(unit.id) if e.effect == data.effect), None)
            if again is None:
                raise
            return again
        await self._audit(project_id, actor, "acceptance_effect", row.id, "confirmed", effect=data.effect)
        self._publish(
            "effect.confirmed",
            {
                "project_id": str(project_id),
                "unit_id": str(unit.id),
                "effect": data.effect,
                "effective_date": row.effective_date,
                "package_refs": list(unit.package_refs or []),
            },
        )
        return row

    async def _start_warranties(
        self,
        project_id: uuid.UUID,
        unit: AcceptanceUnit,
        on: date,
        regime_code: str | None,
        warranty_ids: list[uuid.UUID] | None,
        own: set[str],
    ) -> list[str]:
        """Start the warranties in the unit's scope that have no start yet; returns the ids written.

        Written through defects_liability's own service. A warranty that already has a start is
        never touched, whoever set it, except the ones in ``own``: those this unit's own effect
        started before its certificate was revoked. Scope is the unit's packages, matched against
        the warranty's ``work_package`` by package ref, code or title; a unit without packages
        (the total acceptance) covers the project.
        """
        from app.modules.defects_liability.models import DlpWarranty
        from app.modules.defects_liability.schemas import WarrantyUpdate
        from app.modules.defects_liability.service import DefectsLiabilityService

        stmt = select(DlpWarranty).where(DlpWarranty.project_id == project_id)
        if warranty_ids is not None:
            stmt = stmt.where(DlpWarranty.id.in_(warranty_ids))
        rows = list((await self.session.execute(stmt)).scalars())
        if warranty_ids is not None and len(rows) != len(set(warranty_ids)):
            raise not_found("warranty_not_found")
        if warranty_ids is None and unit.package_refs:
            concept = await self.require_concept(project_id)
            names: set[str] = set()
            for p in await self.applicable_packages(concept):
                if p["ref"] in unit.package_refs:
                    names |= {str(v).strip().lower() for v in (p["ref"], p.get("code"), p.get("title")) if v}
            rows = [w for w in rows if (w.work_package or "").strip().lower() in names]
        svc = DefectsLiabilityService(self.session)
        done = []
        for warranty in rows:
            if warranty.warranty_start_date is not None and str(warranty.id) not in own:
                continue
            patch: dict[str, Any] = {"warranty_start_date": on, "handover_date": on}
            if regime_code:
                patch["limitation_regime"] = regime_code
            await svc.update_warranty(project_id, warranty.id, WarrantyUpdate(**patch))
            done.append(str(warranty.id))
        return done

    # ── preservation ────────────────────────────────────────────────────────

    async def create_survey(self, project_id: uuid.UUID, data: Any) -> PreservationSurvey:
        fields = data.model_dump()
        fields["planned_date"] = _iso(fields["planned_date"])
        if fields.get("paired_with_id"):
            await self._check_pair(project_id, fields["subject_ref"], fields["paired_with_id"])
        for key in ("owner_contact_id", "surveyor_contact_id"):
            await self._check_contact(fields.get(key))
        await self._check_trigger_activities(project_id, fields.get("trigger_activities"))
        return await self.repo.add(PreservationSurvey(project_id=project_id, state="planned", **fields))

    async def _check_trigger_activities(self, project_id: uuid.UUID, value: Any) -> None:
        """``{trigger: {"activity_id", "start"}}``: every activity named belongs to this project."""
        for entry in (value or {}).values():
            if isinstance(entry, dict):
                await self._check_activity(project_id, entry.get("activity_id"))

    async def create_expert_report(self, project_id: uuid.UUID, data: Any) -> ExpertReportPlan:
        fields = data.model_dump()
        fields["due_dates"] = [d.isoformat() for d in fields["due_dates"]]
        await self._check_contact(fields.get("expert_contact_id"))
        return await self.repo.add(ExpertReportPlan(project_id=project_id, **fields))

    async def _check_pair(self, project_id: uuid.UUID, subject_ref: str, before_id: uuid.UUID) -> None:
        before = await self.repo.get(PreservationSurvey, project_id, before_id)
        if before is None:
            raise not_found("survey_not_found")
        if before.phase != "before" or before.subject_ref != subject_ref:
            raise QualityConceptError("pair_must_be_before_of_same_subject")

    async def survey_action(
        self, project_id: uuid.UUID, survey_id: uuid.UUID, data: Any, actor: uuid.UUID
    ) -> PreservationSurvey:
        row = await self.get_row(PreservationSurvey, project_id, survey_id)
        # The state machine is asked again below with the note, which a refusal of access must carry.
        if data.action == "refuse_access" and row.access_refused_on:
            _refuse(caps.survey_action_refusal(row.state, data.action, True))
        row.state = _transition("preservation", row.state, data.action, rationale=data.note)
        if data.on is not None and data.on > _now().date():
            raise QualityConceptError("date_in_future", detail="on")
        on = _iso(data.on or _now().date())
        if data.action == "invite":
            row.invitation_sent_on = on
        elif data.action == "record_survey":
            row.survey_date = on
            if data.owner_acknowledged is not None:
                row.owner_acknowledged = data.owner_acknowledged
            if data.acknowledgment_cde_id is not None:
                await self._check_cde(project_id, data.acknowledgment_cde_id)
                row.acknowledgment_cde_id = data.acknowledgment_cde_id
        elif data.action == "refuse_access":
            row.access_refused_on, row.access_refusal_note = on, data.note
        await self.session.flush()
        await self._audit(project_id, actor, "preservation", row.id, data.action)
        return row

    async def patch_survey(self, project_id: uuid.UUID, survey_id: uuid.UUID, data: Any) -> PreservationSurvey:
        fields = data.model_dump(exclude_unset=True)
        if "planned_date" in fields:
            fields["planned_date"] = _iso(fields["planned_date"])
        for key in ("owner_contact_id", "surveyor_contact_id"):
            await self._check_contact(fields.get(key))
        await self._check_trigger_activities(project_id, fields.get("trigger_activities"))
        return await self.patch_row(PreservationSurvey, project_id, survey_id, fields)

    async def delete_survey(self, project_id: uuid.UUID, survey_id: uuid.UUID) -> None:
        """Only a survey nobody acted on can go; a recorded one is evidence."""
        row = await self.get_row(PreservationSurvey, project_id, survey_id)
        _refuse(caps.survey_delete_refusal(row.state), detail=row.state)
        await self.repo.drop_links("preservation", row.id)
        await self.repo.remove(row)

    async def pair_survey(
        self, project_id: uuid.UUID, survey_id: uuid.UUID, before_id: uuid.UUID
    ) -> PreservationSurvey:
        row = await self.get_row(PreservationSurvey, project_id, survey_id)
        _refuse(caps.pair_refusal(row.phase))
        await self._check_pair(project_id, row.subject_ref, before_id)
        row.paired_with_id = before_id
        await self.session.flush()
        return row

    async def preservation_findings(self, project_id: uuid.UUID, today: date) -> list[ev.Finding]:
        subjects, facts = await self._preservation_facts(project_id)
        return ev.preservation_findings(subjects, facts, today)

    async def _preservation_facts(self, project_id: uuid.UUID) -> tuple[list[ev.SubjectFact], list[ev.SurveyFact]]:
        surveys = await self.repo.list(PreservationSurvey, project_id)
        subjects: dict[str, ev.SubjectFact] = {}
        for s in surveys:
            starts = {
                t: ev.to_date((v or {}).get("start"))
                for t, v in (s.trigger_activities or {}).items()
                if isinstance(v, dict)
            }
            prev = subjects.get(s.subject_ref)
            triggers = frozenset(s.influence_triggers or []) | (prev.triggers if prev else frozenset())
            merged = {**(prev.activity_starts if prev else {}), **starts}
            subjects[s.subject_ref] = ev.SubjectFact(s.subject_ref, s.subject_kind, triggers, merged)
        facts = [
            ev.SurveyFact(
                str(s.id),
                s.subject_ref,
                s.phase,
                s.state,
                acknowledged=bool(s.owner_acknowledged),
                access_refused=s.access_refused_on is not None,
                paired_with_id=str(s.paired_with_id) if s.paired_with_id else None,
            )
            for s in surveys
        ]
        return list(subjects.values()), facts

    # ── material test frequency (rule 21) ───────────────────────────────────

    async def material_findings(self, project_id: uuid.UUID) -> list[ev.Finding]:
        concept = await self.require_concept(project_id)
        cat = await self.catalogue_for(concept)
        proofs = [
            p for p in await self.repo.list(ProofRequirement, project_id) if (p.quantity_rule or {}).get("per_quantity")
        ]
        delivery = await self.proof_delivery(project_id, proofs)
        out: list[ev.Finding] = []
        for p in proofs:
            plan = cat.test_plan_for(p.evidence_type)
            per = ev.to_decimal(p.quantity_rule.get("per_quantity"))
            placed = ev.to_decimal(p.quantity_rule.get("placed_quantity"))
            if per is None or per <= 0:
                continue
            for f in ev.material_frequency_short(
                plan_code=plan.code if plan else p.evidence_type,
                per_quantity=per,
                placed=placed,
                passing=delivery[p.id].counted,
                review_status=plan.review_status.value if plan else "unconfirmed",
            ):
                out.append(ev.Finding(f.code, f.severity, str(p.id), f.params))
        return out

    # ── validation payload and readiness ────────────────────────────────────

    async def validation_payload(self, project_id: uuid.UUID, today: date) -> dict[str, Any]:
        """Everything the ``quality_concept`` rule set reads, computed once."""
        from app.modules.commissioning.models import CxSystem

        concept = await self.require_concept(project_id)
        coverage = await self.coverage(project_id)
        stages = await self.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)
        progress = await self.evaluate_progress(project_id)
        units = await self.repo.list(AcceptanceUnit, project_id)
        commissioned_outside = []
        for system in (await self.session.execute(select(CxSystem).where(CxSystem.project_id == project_id))).scalars():
            if system.status == "commissioned" and await self.final_stage_blockers(project_id, system.id):
                commissioned_outside.append(str(system.id))
        deemed: list[dict[str, Any]] = []
        for u in units:
            if u.state in ev.ACCEPTED_STATES or u.state == "refused":
                continue
            deemed += [
                f.as_dict() for f in ev.deemed_due_findings(await self.deemed_dates(project_id, u), today, str(u.id))
            ]
        cat = await self.catalogue_for(concept)
        proofs = {p.id: p for p in await self.repo.list(ProofRequirement, project_id)}
        kind_findings = []
        for link in await self.repo.links_for("proof", list(proofs)):
            et = cat.evidence_type(proofs[link.owner_id].evidence_type)
            if et is None or link.link_kind not in et.fulfilled_by:
                kind_findings.append(ev.Finding("evidence_kind_not_allowed", ref=str(link.id)).as_dict())
        unmet_accepted = [
            str(u.id)
            for u in units
            if u.state == "accepted" and not u.reservations and await self.unmet_preconditions(project_id, u)
        ]
        released_without_gate = [str(r.id) for r, _ in progress if r.state == "released" and r.hold_gate_id is None]
        order_violations = [
            str(r.id)
            for r, results in progress
            if r.state in ("in_test", "passed", "released")
            and any(x.code == "previous_stage_released" and not x.met for x in results)
        ]
        return {
            "state": concept.state,
            "completeness": _findings(await self.completeness(concept)),
            "evidence": coverage["findings"] + kind_findings,
            "unmet_accepted": unmet_accepted,
            "stages": [
                {
                    "code": s.code,
                    "owner_user_id": str(s.owner_user_id) if s.owner_user_id else None,
                    "release_party_role": s.release_party_role,
                }
                for s in stages
            ],
            "stage_order_violations": order_violations,
            "released_without_gate": released_without_gate,
            "units": [{"id": str(u.id), "kind": u.kind, "regime_code": u.regime_code, "state": u.state} for u in units],
            "partial_scoped": [
                str(u.id) for u in units if u.kind in ("partial_package", "partial_section") and not u.package_refs
            ],
            "deemed": deemed,
            "certification": _findings(await self.certification_findings(project_id)),
            "preservation": _findings(await self.preservation_findings(project_id, today)),
            "material": _findings(await self.material_findings(project_id)),
            "commissioned_outside": commissioned_outside,
        }

    async def readiness(self, project_id: uuid.UUID, today: date) -> dict[str, Any]:
        """What the gate evidence reads (see ``evidence``); ``today`` is unused by the gate items."""
        concept = await self.repo.concept(project_id)
        if concept is None:
            return {"concept": False, "state": None, "approved": False, "errors": [], "preservation_unplanned": []}
        errors = [f for f in await self.completeness(concept) if f.severity == ev.ERROR]
        subjects, facts = await self._preservation_facts(project_id)
        return {
            "concept": True,
            "state": concept.state,
            "approved": concept.state in ("approved", "binding"),
            "errors": _findings(errors),
            # Planning the before survey is what the gate asks; carrying it out is rule 19.
            "preservation_unplanned": ev.preservation_unplanned(subjects, facts),
        }


async def commissioning_guard(session: Any, project_id: uuid.UUID, system_id: uuid.UUID) -> list[str]:
    """Registered with ``core.commissioning_stage_guard`` (rule 11)."""
    return await QualityConceptService(session).final_stage_blockers(project_id, system_id)
