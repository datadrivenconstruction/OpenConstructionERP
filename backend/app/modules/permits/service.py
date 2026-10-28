# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permits service: roadmap, applications and clocks, decisions, permits and the condition register.

Every write runs in the caller's transaction with its audit entry
(``log_activity``) and its events (``publish_after_commit``). Requirement state,
forecasts, conflicts, overdue flags and readiness are derived on read; only
what an authority or a person decided is stored.

Decision flow (rules 7, 8, 10, 13, 14)::

    record_decision -- lock the application, refuse a second decision (409),
                       check the outcome's own rules, write the immutable
                       decision, then by application kind:
                         new / early_start      -> permit + its conditions
                         variation / amendment  -> new permit, parent superseded,
                                                   conditions carried forward
                         extension_of_validity  -> parent permit's lapse date moved
                         discharge_of_conditions-> listed conditions discharged
                       partially_granted adds a follow-up requirement for the rest.

Dates the authority sets are calendar dates; the platform keeps no project
time zone, so the date recorded is the date that counts. Timestamps are UTC.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.demo_history import RECORDING_DEMO_HISTORY
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.permits import conditions as cnd
from app.modules.permits import guards
from app.modules.permits import hosting as hst
from app.modules.permits import roadmap as rm
from app.modules.permits.catalogue import (
    APPLICANT_ROLES,
    CONDITION_KINDS,
    CONDITION_TRIGGERS,
    PERMIT_TYPE_KIND,
    PermitType,
    PermitTypeCatalogue,
    default_catalogue_id,
    merged,
    register_kind,
    shipped_catalogues,
)
from app.modules.permits.clock import ClockError, ClockEvent, ClockSpec, check_extension, check_stop
from app.modules.permits.clock import deemed_proposal as clock_deemed
from app.modules.permits.clock import duration_days as clock_duration
from app.modules.permits.clock import forecast as clock_forecast
from app.modules.permits.errors import PermitError, conflict, forbidden, not_found
from app.modules.permits.fsm import (
    APPLICATION_FSM,
    APPLICATION_KINDS,
    CONDITION_FSM,
    DECISION_OUTCOMES,
    PERMIT_FSM,
    USER_TARGETS,
)
from app.modules.permits.models import (
    ClockEvent as ClockEventRow,
)
from app.modules.permits.models import (
    ConditionDischarge,
    ConditionEvidence,
    Permit,
    PermitApplication,
    PermitCondition,
    PermitDecision,
    PermitRequirement,
    PermitRoadmap,
    RequirementDependency,
)
from app.modules.permits.repository import PermitRepository

logger = logging.getLogger(__name__)

MODULE = "permits"
TARGET_KIND = "permit_application"
DECIDABLE = guards.DECIDABLE
NOT_REFUSED = ("granted", "granted_with_conditions", "partially_granted", "deemed_granted")
PERMIT_KINDS = ("new", "early_start", "variation", "amendment_non_material")
CHILD_KINDS = ("variation", "amendment_non_material", "extension_of_validity", "discharge_of_conditions")
# Child applications that change the permit itself and so stay with the permit's own requirement.
SAME_REQUIREMENT_KINDS = ("variation", "amendment_non_material", "extension_of_validity")
# A parent permit a child application may still be filed for or decided on.
LIVE_PARENT = ("in_force", "suspended")
# Catalogue category of the permit type a discharge application is filed under when it has its own clock.
DISCHARGE_CATEGORY = "discharge"
# Allocation the delivery model answers for changes to an issued permit (rule 2).
CONDITIONS_CHANGE_ALLOCATION = "permit_conditions_change"
EVIDENCE_KINDS = (
    "cde_revision",
    "inspection",
    "commissioning_item",
    "report",
    "photo",
    "external_url",
    "discharge_decision",
)
# Evidence kinds that point at a record of another module: the reference is mandatory and checked.
LINKED_EVIDENCE = ("cde_revision", "inspection", "commissioning_item", "discharge_decision")
BREACH_REF_KINDS = ("safety_observation", "inspection", "manual")
# Frame documents of rule 18 and the register each one is the export of.
REGISTERS: tuple[str, ...] = ("roadmap", "permits", "conditions")
# Requirement fields that decide what a gate reads or who may edit the row: ``permits.manage`` only.
MANAGED_REQUIREMENT_FIELDS = ("applicable", "conflict_accepted", "responsible_user_id")
# Condition fields a gate reads. Changing one needs ``permits.manage`` and an open condition.
GATE_CONDITION_FIELDS = guards.GATE_FIELDS
# A date the authority or the applicant acted on may be at most this far ahead of the server's
# UTC date (the project may sit in a time zone ahead of UTC).
FUTURE_SLACK_DAYS = 1

# Default applicant resolvers (rule 2). A delivery-model module registers
# ``(session, project_id, allocation_category) -> applicant role | None``.
ApplicantResolver = Callable[[AsyncSession, uuid.UUID, str], Any]
_APPLICANT_RESOLVERS: dict[str, ApplicantResolver] = {}
# Owners of soft links this module cannot look up itself because the module that owns the row is
# optional: ``(session, row id) -> owning project id | None``. Without a resolver the link is refused.
LinkResolver = Callable[[AsyncSession, uuid.UUID], Any]
_LINK_RESOLVERS: dict[str, LinkResolver] = {}


def register_applicant_resolver(name: str, resolver: ApplicantResolver) -> None:
    """Register (or replace by name) a source of default applicants, e.g. the delivery model's allocations."""
    _APPLICANT_RESOLVERS[name] = resolver


def unregister_applicant_resolver(name: str) -> None:
    _APPLICANT_RESOLVERS.pop(name, None)


def register_link_resolver(kind: str, resolver: LinkResolver) -> None:
    """Register who can say which project a soft-linked row of ``kind`` belongs to (e.g. ``delivery_model``)."""
    _LINK_RESOLVERS[kind] = resolver


def unregister_link_resolver(kind: str) -> None:
    _LINK_RESOLVERS.pop(kind, None)


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise PermitError("id_invalid", 422, detail=str(value)[:80]) from exc


def _binding_status(doc: Any) -> str:
    """Rule 18: the roadmap is ``agreed`` exactly while its governance frame document is binding."""
    return "agreed" if doc is not None and doc.status == "binding" else "draft"


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """A free-text reference read as an id, where it is one."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _today() -> date:
    """The server's date. Write paths never take the date from the client."""
    return datetime.now(UTC).date()


def _not_in_future(value: date | None, today: date) -> None:
    if value is not None and (value - today).days > FUTURE_SLACK_DAYS:
        raise PermitError("date_in_future", 422, detail=value.isoformat())


class PermitService:
    """Orchestrates the permits of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PermitRepository(session)
        register_kind()

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

    def _readiness_changed(self, project_id: uuid.UUID) -> None:
        """Anything a readiness check reads has changed: a decision, a permit state, a condition."""
        self._publish("readiness.changed", {"project_id": str(project_id)})

    async def _fsm(self, fsm: Any, row: Any, target: str, actor_id: Any, reason: str | None = None) -> None:
        try:
            await fsm.apply(
                self.session,
                row,
                target,
                actor_id=_s(actor_id),
                reason=reason,
                extra_metadata={"project_id": _s(row.project_id)},
                entity_type=fsm.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _notify(self, user_id: Any, kind: str, entity_type: str, entity_id: Any, ctx: dict[str, Any]) -> None:
        """Best effort, inside a savepoint so a failure never poisons the write."""
        if not user_id:
            return
        try:
            from app.modules.notifications.service import NotificationService

            async with self.session.begin_nested():
                await NotificationService(self.session).create(
                    user_id=user_id,
                    notification_type=f"permits_{kind}",
                    title_key=f"notifications.permits.{kind}.title",
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    body_key=f"notifications.permits.{kind}.body",
                    body_context=ctx,
                    action_url=f"/projects/{ctx.get('project_id')}/permits",
                    metadata=ctx,
                )
        except Exception:
            logger.debug("permits: notification %s failed", kind, exc_info=True)

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    # ── soft links (rule 24: anything of another project is 404) ───────────

    async def _check_link(self, kind: str, ref_id: Any, project_id: uuid.UUID) -> None:
        rid = _uuid(ref_id)
        if rid is None:
            return
        if kind == "gate_condition":
            from app.modules.project_governance import public

            if not any(c.id == rid for c in await public.project_conditions(self.session, project_id)):
                raise not_found("gate_condition_not_found")
            return
        owner = await self._link_project(kind, rid)
        if owner != project_id:
            raise not_found(f"{kind}_not_found")

    async def _check_member(self, project_id: uuid.UUID, user_id: Any) -> None:
        """Whoever is named responsible or owner gets the record and its notifications: only a
        person with access to the project (its owner, a team member, an admin) may be named."""
        uid = _uuid(user_id)
        if uid is None:
            return
        from app.modules.project_governance.public import user_can_access_project

        if not await user_can_access_project(self.session, project_id, uid):
            raise PermitError("user_not_on_project", 422)

    async def _link_project(self, kind: str, rid: uuid.UUID) -> uuid.UUID | None:
        if kind == "activity":
            from app.modules.schedule.models import Activity, Schedule

            stmt = select(Schedule.project_id).join(Activity, Activity.schedule_id == Schedule.id)
            return (await self.session.execute(stmt.where(Activity.id == rid))).scalar_one_or_none()
        if kind in ("cde_revision", "document_revision"):
            from app.modules.cde.models import DocumentContainer, DocumentRevision

            stmt = select(DocumentContainer.project_id).join(
                DocumentRevision, DocumentRevision.container_id == DocumentContainer.id
            )
            return (await self.session.execute(stmt.where(DocumentRevision.id == rid))).scalar_one_or_none()
        simple: dict[str, tuple[str, str]] = {
            "cde_container": ("app.modules.cde.models", "DocumentContainer"),
            "review_cycle": ("app.modules.review_authority.models", "ReviewCycle"),
            "submission": ("app.modules.authority_submission.models", "Submission"),
            "inspection": ("app.modules.inspections.models", "QualityInspection"),
            "safety_observation": ("app.modules.safety.models", "SafetyObservation"),
            "route_assessment": ("app.modules.project_route.models", "RouteAssessment"),
        }
        if kind == "commissioning_item":
            from app.modules.commissioning.models import CxChecklist, CxChecklistItem, CxSystem

            stmt = (
                select(CxSystem.project_id)
                .join(CxChecklist, CxChecklist.system_id == CxSystem.id)
                .join(CxChecklistItem, CxChecklistItem.checklist_id == CxChecklist.id)
                .where(CxChecklistItem.id == rid)
            )
            return (await self.session.execute(stmt)).scalar_one_or_none()
        if kind in _LINK_RESOLVERS:
            return await _LINK_RESOLVERS[kind](self.session, rid)
        if kind not in simple:
            # Nobody can vouch for the row: an id that cannot be checked is not stored.
            raise PermitError("link_unverifiable", 422, detail=kind)
        import importlib

        module, name = simple[kind]
        model = getattr(importlib.import_module(module), name)
        return (await self.session.execute(select(model.project_id).where(model.id == rid))).scalar_one_or_none()

    async def _check_route(self, route_id: Any, project_id: uuid.UUID) -> None:
        """The internal-release route must be one this project may use, for this kind of target, and active.

        ``approval_routes`` looks a route up by id alone, so the test is made here, both when the
        route is stored on the roadmap and again when an instance is started from it. A route of
        another project answers 404 like a missing one. So does a route with no project: such a
        row carries nothing that says whose it is, so it cannot be shown to belong to the caller's
        tenant, and governance pins only routes of the project itself for the same reason.
        """
        from app.modules.approval_routes.models import Route

        rid = _uuid(route_id)
        if rid is None:
            return
        route = await self.session.get(Route, rid)
        if route is None or route.project_id != project_id:
            raise not_found("approval_route_not_found")
        if route.target_kind != TARGET_KIND or not route.is_active:
            raise PermitError("approval_route_not_usable", 422)

    # ── catalogue ──────────────────────────────────────────────────────────

    async def catalogue_for(self, roadmap: PermitRoadmap) -> PermitTypeCatalogue:
        """The pinned catalogue with its ``extends`` chain resolved."""
        from app.modules.project_governance.catalogue_store import resolve_catalogue
        from app.modules.project_governance.errors import GovernanceError

        try:
            obj = await resolve_catalogue(
                self.session,
                roadmap.catalogue_source,
                roadmap.catalogue_id,
                roadmap.catalogue_version,
                kind=PERMIT_TYPE_KIND,
                # The pin was checked when it was stored and keeps resolving for every project member.
                from_pin=True,
            )
        except GovernanceError as exc:
            raise PermitError(exc.code, exc.status_code) from exc
        shipped = shipped_catalogues()
        try:
            return merged(obj, lambda cid: shipped[cid])
        except (KeyError, ValueError) as exc:
            raise PermitError("catalogue_invalid", 422, detail=str(exc)) from exc

    async def _types(self, roadmap: PermitRoadmap) -> dict[str, PermitType]:
        return (await self.catalogue_for(roadmap)).type_map()

    def _type(self, types: dict[str, PermitType], code: str) -> PermitType:
        t = types.get(code)
        if t is None:
            raise PermitError("unknown_permit_type", 422)
        return t

    # ── calendar ───────────────────────────────────────────────────────────

    async def working_day(self, project_id: uuid.UUID) -> Callable[[date], bool]:
        """The project's working-day calendar, resolved the way the schedule resolves it."""
        from app.modules.schedule.service import ScheduleService, get_work_calendar

        svc = ScheduleService(self.session)
        try:
            region = await svc.resolve_project_region(project_id)
            sub = await svc.resolve_project_subdivision(project_id)
        except Exception:
            region, sub = None, None
        cal = get_work_calendar(region, sub)
        work_days = set(cal.get("work_days") or ())
        holidays_of = cal.get("holidays")
        cache: dict[int, frozenset[date]] = {}

        def is_working(d: date) -> bool:
            if d.weekday() not in work_days:
                return False
            if callable(holidays_of):
                if d.year not in cache:
                    cache[d.year] = frozenset(holidays_of(d.year))
                return d not in cache[d.year]
            return True

        return is_working

    # ── roadmap ────────────────────────────────────────────────────────────

    async def get_roadmap(self, project_id: uuid.UUID) -> PermitRoadmap:
        """The roadmap row as stored. A read: it writes nothing (see :meth:`roadmap_view`)."""
        roadmap = await self.repo.get_roadmap(project_id)
        if roadmap is None:
            raise not_found("roadmap_missing")
        return roadmap

    async def roadmap_view(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The roadmap as served: ``state`` and the frame document are derived from governance on read.

        The stored columns are brought in line only by a write (:meth:`_structural_guard`),
        so a GET never changes a row.
        """
        roadmap = await self.get_roadmap(project_id)
        doc = await self._roadmap_document(project_id)
        return {
            **roadmap_out(roadmap),
            "state": _binding_status(doc),
            "governance_document_id": str(doc.id) if doc is not None else _s(roadmap.governance_document_id),
            "gates_in_use": await self.gates_in_use(project_id),
        }

    async def gates_in_use(self, project_id: uuid.UUID) -> bool:
        """Whether the project has gates at all. Without them nothing in permits waits for a gate
        or a frame document: the roadmap stays ``draft`` and every step is taken by hand."""
        from app.modules.project_governance import public

        return bool(await public.project_gates(self.session, project_id))

    async def _roadmap_document(self, project_id: uuid.UUID) -> Any:
        """The frame document the governance model hosts permits in, as the port lists it; ``None``
        when the model hosts permits nowhere or the project has no row for that document yet."""
        from app.modules.project_governance import public

        host = await public.host_for(self.session, project_id, hst.SUBJECT)
        if host is None:
            return None
        documents = await public.project_documents(self.session, project_id)
        return next((d for d in documents if d.code == host.doc_type), None)

    async def _mirror_binding(self, roadmap: PermitRoadmap) -> None:
        """Rule 18: ``agreed`` mirrors the governance binding state of the roadmap frame document."""
        doc = await self._roadmap_document(roadmap.project_id)
        status = _binding_status(doc)
        if doc is not None and roadmap.governance_document_id != doc.id:
            roadmap.governance_document_id = doc.id
        if roadmap.status != status:
            roadmap.status = status
            await self.session.flush()

    async def _structural_guard(self, roadmap: PermitRoadmap, change_request_id: Any) -> str | None:
        """Rule 18: after binding, ONE structural roadmap change needs ONE approved frame change request.

        The request is used up by the change: its id goes onto the roadmap and into the audit
        entry of the change, and a second change naming it is refused. The caller holds the
        roadmap row lock, so two changes cannot spend the same request. Returns the id spent,
        ``None`` while the roadmap is still a draft.
        """
        await self._mirror_binding(roadmap)
        if roadmap.status != "agreed":
            return None
        if RECORDING_DEMO_HISTORY.get():
            # The demo seed writes the history the frame was bound on, not a live change.
            return None
        from app.modules.project_governance import public

        crid = _uuid(change_request_id)
        if crid is None or roadmap.governance_document_id is None:
            raise conflict("roadmap_binding_change_request_required")
        requests = await public.project_change_requests(
            self.session, roadmap.project_id, roadmap.governance_document_id
        )
        if not any(r.id == crid and r.status == "approved" for r in requests):
            raise conflict("roadmap_binding_change_request_required")
        used = list(roadmap.consumed_change_request_ids or [])
        if str(crid) in used:
            raise conflict("change_request_already_used")
        # A new list: the JSON column only notices a new object.
        roadmap.consumed_change_request_ids = [*used, str(crid)]
        return str(crid)

    async def hosting(self, project_id: uuid.UUID, roadmap: PermitRoadmap | None = None) -> hst.Hosting:
        """Where permits live in the project's governance model, resolved now from catalogue tags."""
        return await hst.project_hosting(self.session, project_id, roadmap)

    async def set_roadmap(
        self,
        project_id: uuid.UUID,
        *,
        tenant_id: str | None,
        actor_id: uuid.UUID,
        catalogue_source: str | None = None,
        catalogue_id: str | None = None,
        catalogue_version: int | None = None,
        jurisdiction: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> PermitRoadmap:
        """Create the roadmap (country default catalogue) or re-pin / change its settings."""
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        project = await self._project(project_id)
        roadmap = await self.repo.get_roadmap(project_id, lock=True)
        country = getattr(project, "country_code", None)
        juris = (jurisdiction or (roadmap.jurisdiction if roadmap else "") or _project_jurisdiction(project)).upper()
        source = catalogue_source or (roadmap.catalogue_source if roadmap else "shipped")
        if roadmap is None and catalogue_id is None and catalogue_source is None:
            # A new roadmap: the active pack's default for this country first, the module's own after.
            from app.modules.project_governance.public import default_catalogue_pin

            pin = default_catalogue_pin(PERMIT_TYPE_KIND, country, getattr(project, "subdivision_code", None))
            if pin is not None:
                source, catalogue_id = pin.source, pin.catalogue_id
                catalogue_version = catalogue_version or pin.version
        cid = catalogue_id or (roadmap.catalogue_id if roadmap else default_catalogue_id(country, juris))
        repin = roadmap is None or any(v is not None for v in (catalogue_source, catalogue_id, catalogue_version))
        if repin:
            try:
                version = await CatalogueStore(self.session).assert_pinnable(
                    tenant_id, source, cid, catalogue_version, kind=PERMIT_TYPE_KIND
                )
            except GovernanceError as exc:
                raise PermitError(exc.code, exc.status_code) from exc
        else:
            version = roadmap.catalogue_version
        before = None
        if roadmap is None:
            # No row to lock yet: two first PUTs both get here, the unique key lets one through.
            roadmap = PermitRoadmap(
                project_id=project_id,
                catalogue_source=source,
                catalogue_id=cid,
                catalogue_version=version,
                jurisdiction=juris,
                created_by=actor_id,
            )
            try:
                async with self.session.begin_nested():
                    await self.repo.add(roadmap)
            except IntegrityError as exc:
                raise conflict("concurrent_roadmap") from exc
            action = "roadmap_created"
        else:
            before = {"catalogue": f"{roadmap.catalogue_source}:{roadmap.catalogue_id}@{roadmap.catalogue_version}"}
            roadmap.catalogue_source, roadmap.catalogue_id, roadmap.catalogue_version = source, cid, version
            roadmap.jurisdiction = juris
            action = "roadmap_updated"
        for key, value in (settings or {}).items():
            if value is None:
                # An explicit null clears a link; a setting that always has a value cannot be null.
                if key in ("roadmap_area_code", "conditions_area_code"):
                    # No override: the area is resolved from the governance model again.
                    setattr(roadmap, key, "")
                elif key in ("route_assessment_id", "approval_route_id", "delivery_model_id"):
                    setattr(roadmap, key, None)
                else:
                    raise PermitError("field_not_nullable", 422, detail=key)
                continue
            if key == "route_assessment_id":
                await self._check_link("route_assessment", value, project_id)
                roadmap.route_assessment_id = _uuid(value)
            elif key == "approval_route_id":
                await self._check_route(value, project_id)
                roadmap.approval_route_id = _uuid(value)
            elif key == "delivery_model_id":
                await self._check_link("delivery_model", value, project_id)
                roadmap.delivery_model_id = _uuid(value)
            elif key in ("internal_review", "escalation_days", "buffer_days", "roadmap_area_code"):
                setattr(roadmap, key, value)
            elif key == "conditions_area_code":
                roadmap.conditions_area_code = value
        # A pinned catalogue whose parent is gone, or one that lacks a type or clock variant the
        # roadmap already uses, is refused now and not at the next read.
        types = await self._types(roadmap)
        await self._assert_catalogue_covers(roadmap, types)
        await self.session.flush()
        after = {"catalogue": f"{roadmap.catalogue_source}:{roadmap.catalogue_id}@{roadmap.catalogue_version}"}
        await self._audit(actor_id, "permit_roadmap", roadmap.id, action, before_state=before, metadata=after)
        return roadmap

    async def _assert_catalogue_covers(self, roadmap: PermitRoadmap, types: dict[str, PermitType]) -> None:
        """Refuse a catalogue that lacks a permit type or a clock variant the project already uses."""
        reqs = await self.repo.list_requirements(roadmap.project_id)
        used = {r.permit_type_code for r in reqs} | {
            p.permit_type_code for p in await self.repo.list_permits(roadmap.project_id)
        }
        missing = sorted(used - set(types))
        if missing:
            raise conflict("catalogue_drops_used_type", detail=",".join(missing))
        for r in reqs:
            if not r.clock_variant:
                continue
            try:
                ClockSpec.from_catalogue(types[r.permit_type_code].clock, r.clock_variant)
            except ClockError as exc:
                raise conflict(
                    "catalogue_drops_used_variant", detail=f"{r.permit_type_code}:{r.clock_variant}"
                ) from exc

    async def require_roadmap(self, project_id: uuid.UUID, *, lock: bool = False) -> PermitRoadmap:
        roadmap = await self.repo.get_roadmap(project_id, lock=lock)
        if roadmap is None:
            raise not_found("roadmap_missing")
        return roadmap

    # ── default applicant (rule 2) ─────────────────────────────────────────

    async def default_applicant(self, project_id: uuid.UUID, ptype: PermitType) -> tuple[str, str]:
        """``(role, source)``: the delivery model's allocation when one answers, else the catalogue default."""
        return await self.allocated_applicant(
            project_id, ptype.allocation_category, ptype.default_applicant_role, "catalogue"
        )

    async def allocated_applicant(
        self, project_id: uuid.UUID, category: str, otherwise: str, otherwise_source: str
    ) -> tuple[str, str]:
        """``(role, source)`` for one allocation category; ``otherwise`` when no delivery model answers."""
        for name, resolver in list(_APPLICANT_RESOLVERS.items()):
            try:
                async with self.session.begin_nested():
                    role = await resolver(self.session, project_id, category)
            except Exception:
                logger.warning("permits: applicant resolver %s failed", name, exc_info=True)
                continue
            if role in APPLICANT_ROLES:
                return role, "allocation"
        return otherwise, otherwise_source

    # ── route proposals (rule 1) ───────────────────────────────────────────

    async def _assessment(self, project_id: uuid.UUID, assessment_id: Any) -> Any:
        from app.modules.project_route.models import RouteAssessment

        aid = _uuid(assessment_id)
        stmt = select(RouteAssessment).where(RouteAssessment.project_id == project_id)
        if aid is not None:
            stmt = stmt.where(RouteAssessment.id == aid)
        else:
            stmt = stmt.where(RouteAssessment.status == "confirmed").order_by(RouteAssessment.created_at.desc())
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            raise not_found("route_assessment_not_found")
        if row.status != "confirmed":
            raise conflict("route_assessment_not_confirmed")
        return row

    async def propose(self, project_id: uuid.UUID, assessment_id: Any = None) -> dict[str, Any]:
        """Requirements the confirmed route implies. Proposals only: nothing is written (principle 7)."""
        roadmap = await self.require_roadmap(project_id)
        assessment = await self._assessment(project_id, assessment_id)
        route = assessment.determined_route
        out: dict[str, Any] = {"route": route, "route_assessment_id": str(assessment.id), "proposals": []}
        if route == "exempt":
            out["reason"] = "route_exempt"
            return out
        if route == "undetermined":
            out["reason"] = "route_undetermined"
            return out
        types = await self._types(roadmap)
        present = {r.permit_type_code for r in await self.repo.list_requirements(project_id)}
        wanted: list[str] = [t.code for t in types.values() if route in t.triggered_by_route]
        # Prerequisites typed ``granted`` come along: the main permit cannot be filed without them.
        i = 0
        while i < len(wanted):
            for r in types[wanted[i]].requires:
                if r.code not in wanted and r.code in types:
                    wanted.append(r.code)
            i += 1
        for code in wanted:
            t = types[code]
            role, source = await self.default_applicant(project_id, t)
            out["proposals"].append(
                {
                    "permit_type_code": code,
                    "name_key": t.name_key,
                    "category": t.category,
                    "applicant_role": role,
                    "applicant_source": source,
                    "already_present": code in present,
                    "requires": [{"code": r.code, "on": r.on} for r in t.requires],
                }
            )
        if not out["proposals"]:
            out["reason"] = "no_types_for_route"
        return out

    async def accept_proposals(
        self,
        project_id: uuid.UUID,
        codes: list[str],
        *,
        actor_id: uuid.UUID,
        assessment_id: Any = None,
        change_request_id: Any = None,
    ) -> list[PermitRequirement]:
        """A human accepts proposals one by one (codes); each becomes a requirement with catalogue dependencies."""
        roadmap = await self.require_roadmap(project_id, lock=True)
        spent = await self._structural_guard(roadmap, change_request_id)
        proposal = await self.propose(project_id, assessment_id)
        offered = {p["permit_type_code"]: p for p in proposal["proposals"]}
        unknown = [c for c in codes if c not in offered]
        if unknown:
            raise PermitError("proposal_not_offered", 422, detail=",".join(unknown))
        types = await self._types(roadmap)
        existing = {r.permit_type_code: r for r in await self.repo.list_requirements(project_id)}
        created: list[PermitRequirement] = []
        for code in codes:
            if code in existing:
                continue
            p = offered[code]
            req = await self.repo.add(
                PermitRequirement(
                    project_id=project_id,
                    permit_type_code=code,
                    applicant_role=p["applicant_role"],
                    applicant_source=p["applicant_source"],
                    proposed_from_route=proposal["route"],
                    sort_order=len(existing) + len(created),
                )
            )
            created.append(req)
            existing[code] = req
        for req in created:
            for r in types[req.permit_type_code].requires:
                dep = existing.get(r.code)
                if dep is not None:
                    await self.repo.add(
                        RequirementDependency(
                            project_id=project_id, requirement_id=req.id, depends_on_id=dep.id, dep_type=r.on
                        )
                    )
        if proposal.get("route_assessment_id"):
            roadmap.route_assessment_id = _uuid(proposal["route_assessment_id"])
        await self.session.flush()
        for req in created:
            await self._audit(
                actor_id,
                "permit_requirement",
                req.id,
                "requirement_accepted_from_route",
                metadata={"change_request_id": spent},
            )
        return created

    # ── requirements ───────────────────────────────────────────────────────

    async def create_requirement(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> PermitRequirement:
        roadmap = await self.require_roadmap(project_id, lock=True)
        spent = await self._structural_guard(roadmap, data.pop("change_request_id", None))
        dependencies = data.pop("dependencies", None) or []
        ptype = self._type(await self._types(roadmap), data["permit_type_code"])
        role, source = await self.default_applicant(project_id, ptype)
        if data.get("applicant_role") and data["applicant_role"] != role:
            if not (data.get("applicant_rationale") or "").strip():
                raise PermitError("applicant_override_needs_rationale", 422)
            role, source = data["applicant_role"], "override"
        await self._check_requirement_links(project_id, data)
        await self._check_member(project_id, data.get("responsible_user_id"))
        count = len(await self.repo.list_requirements(project_id))
        req = await self.repo.add(
            PermitRequirement(
                project_id=project_id,
                permit_type_code=ptype.code,
                title=data.get("title") or "",
                applicable=data.get("applicable", True),
                applicability_rationale=data.get("applicability_rationale") or "",
                applicant_role=role,
                applicant_source=source,
                applicant_rationale=data.get("applicant_rationale") or "",
                applicant_party=data.get("applicant_party") or "",
                applicant_contact_id=_uuid(data.get("applicant_contact_id")),
                responsible_user_id=_uuid(data.get("responsible_user_id")),
                planned_submit_date=data.get("planned_submit_date"),
                needed_by_activity_id=_uuid(data.get("needed_by_activity_id")),
                needed_by_date=data.get("needed_by_date"),
                clock_variant=data.get("clock_variant") or "",
                expected_decision_date=data.get("expected_decision_date"),
                schedule_activity_id=_uuid(data.get("schedule_activity_id")),
                # Only a code the caller names is stored; the hosting area is resolved on read.
                governance_area_code=data.get("governance_area_code") or "",
                sort_order=count,
            )
        )
        if req.clock_variant:
            self._spec(ptype, req.clock_variant)
        if not req.applicable and not req.applicability_rationale.strip():
            raise PermitError("not_applicable_needs_rationale", 422)
        if dependencies:
            # A new requirement and the edges it waits on are one structural change (one change request).
            await self._write_dependencies(project_id, req.id, dependencies)
        await self._audit(
            actor_id, "permit_requirement", req.id, "requirement_created", metadata={"change_request_id": spent}
        )
        return req

    async def _check_requirement_links(self, project_id: uuid.UUID, data: dict[str, Any]) -> None:
        for key in ("needed_by_activity_id", "schedule_activity_id"):
            if data.get(key):
                await self._check_link("activity", data[key], project_id)

    async def update_requirement(
        self,
        project_id: uuid.UUID,
        rid: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> PermitRequirement:
        """Operational fields, by the requirement's responsible user or a holder of ``permits.manage``.

        ``applicable`` and ``conflict_accepted`` decide what a gate reads and who is responsible
        decides who may edit: all three need ``permits.manage``. ``applicable`` is also structural
        (rule 18) and frozen once an application of the requirement has left ``planned``.
        """
        # The roadmap row lock serialises the change-request spend of a structural change.
        roadmap = await self.require_roadmap(project_id, lock=True)
        req = await self.repo.get_requirement(project_id, rid, lock=True)
        if req is None:
            raise not_found("requirement_not_found")
        guards.requirement_edit(req, actor_id, can_manage)
        change_request_id = data.pop("change_request_id", None)
        changed = {k for k, v in data.items() if getattr(req, k, None) != (_uuid(v) if k.endswith("_id") else v)}
        if changed & set(MANAGED_REQUIREMENT_FIELDS) and not can_manage:
            raise forbidden("manage_required", detail=",".join(sorted(changed & set(MANAGED_REQUIREMENT_FIELDS))))
        spent = None
        if "applicable" in changed:
            apps = [a for a in await self.repo.list_applications(project_id) if a.requirement_id == rid]
            if any(a.status not in ("planned", "withdrawn") for a in apps):
                raise conflict("requirement_field_frozen", detail="applicable")
            spent = await self._structural_guard(roadmap, change_request_id)
        await self._check_requirement_links(project_id, data)
        if "responsible_user_id" in changed:
            await self._check_member(project_id, data["responsible_user_id"])
        if "applicant_role" in data and data["applicant_role"] and data["applicant_role"] != req.applicant_role:
            if not (data.get("applicant_rationale") or "").strip():
                raise PermitError("applicant_override_needs_rationale", 422)
            req.applicant_source = "override"
        for key, value in data.items():
            if key.endswith("_id") and key not in ("permit_type_code",):
                value = _uuid(value)
            setattr(req, key, value)
        if req.clock_variant:
            self._spec(self._type(await self._types(roadmap), req.permit_type_code), req.clock_variant)
        if not req.applicable and not (req.applicability_rationale or "").strip():
            raise PermitError("not_applicable_needs_rationale", 422)
        await self.session.flush()
        await self._audit(
            actor_id,
            "permit_requirement",
            req.id,
            "requirement_updated",
            metadata={**_jsonable(data), "change_request_id": spent},
        )
        if changed & {"applicable", "conflict_accepted"}:
            self._readiness_changed(project_id)
        return req

    async def delete_requirement(
        self, project_id: uuid.UUID, rid: uuid.UUID, *, actor_id: uuid.UUID, change_request_id: Any = None
    ) -> None:
        roadmap = await self.require_roadmap(project_id, lock=True)
        req = await self.repo.get_requirement(project_id, rid, lock=True)
        if req is None:
            raise not_found("requirement_not_found")
        apps = [a for a in await self.repo.list_applications(project_id) if a.requirement_id == rid]
        guards.requirement_delete(apps)
        spent = await self._structural_guard(roadmap, change_request_id)
        await self.session.delete(req)
        await self.session.flush()
        await self._audit(
            actor_id, "permit_requirement", rid, "requirement_deleted", metadata={"change_request_id": spent}
        )

    async def set_dependencies(
        self,
        project_id: uuid.UUID,
        rid: uuid.UUID,
        deps: list[dict[str, Any]],
        *,
        actor_id: uuid.UUID,
        change_request_id: Any = None,
    ) -> list[RequirementDependency]:
        """Replace one requirement's dependencies; a cycle is refused (rule 3)."""
        roadmap = await self.require_roadmap(project_id, lock=True)
        req = await self.repo.get_requirement(project_id, rid, lock=True)
        if req is None:
            raise not_found("requirement_not_found")
        spent = await self._structural_guard(roadmap, change_request_id)
        rows = await self._write_dependencies(project_id, rid, deps)
        await self._audit(
            actor_id,
            "permit_requirement",
            rid,
            "dependencies_set",
            metadata={"count": len(rows), "change_request_id": spent},
        )
        return rows

    async def _write_dependencies(
        self, project_id: uuid.UUID, rid: uuid.UUID, deps: list[dict[str, Any]]
    ) -> list[RequirementDependency]:
        ids = {r.id for r in await self.repo.list_requirements(project_id)}
        new_edges = []
        seen: set[uuid.UUID] = set()
        for d in deps:
            target = _uuid(d["depends_on_id"])
            if target not in ids:
                raise not_found("requirement_not_found")
            if target in seen:
                raise PermitError("dependency_duplicate", 422, detail=str(target))
            seen.add(target)
            if d.get("on", "granted") not in ("granted", "submitted"):
                raise PermitError("dependency_type_invalid", 422)
            new_edges.append(rm.Edge(str(rid), str(target), d.get("on", "granted")))
        existing = [e for e in await self.repo.list_dependencies(project_id) if e.requirement_id != rid]
        graph = [rm.Edge(str(e.requirement_id), str(e.depends_on_id), e.dep_type) for e in existing] + new_edges
        cycle = rm.find_cycle(graph)
        if cycle is not None:
            raise PermitError("dependency_cycle", 422, detail=" -> ".join(cycle))
        for e in await self.repo.list_dependencies(project_id):
            if e.requirement_id == rid:
                await self.session.delete(e)
        await self.session.flush()
        rows = [
            await self.repo.add(
                RequirementDependency(
                    project_id=project_id, requirement_id=rid, depends_on_id=_uuid(e.depends_on), dep_type=e.on
                )
            )
            for e in new_edges
        ]
        return rows

    # ── derived state ──────────────────────────────────────────────────────

    async def state_snapshot(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Everything derived about the roadmap in one pass: per requirement state, latest application."""
        reqs = await self.repo.list_requirements(project_id)
        apps = await self.repo.list_applications(project_id)
        decisions = await self.repo.list_decisions(project_id)
        edges = [
            rm.Edge(str(e.requirement_id), str(e.depends_on_id), e.dep_type)
            for e in await self.repo.list_dependencies(project_id)
        ]
        current = _current_decisions(decisions)
        latest: dict[str, PermitApplication] = {}
        for a in apps:
            if a.kind not in ("new", "early_start"):
                continue
            k = str(a.requirement_id)
            if k not in latest or a.attempt > latest[k].attempt:
                latest[k] = a
        # A requirement of a discharge type carries discharge applications only; its newest is its attempt.
        for a in apps:
            k = str(a.requirement_id)
            if a.kind != "discharge_of_conditions":
                continue
            if k not in latest or (latest[k].kind == a.kind and a.attempt > latest[k].attempt):
                latest[k] = a
        # A favourable decision grants something only while a permit of the requirement is in force.
        live = {str(p.requirement_id) for p in await self.repo.list_permits(project_id) if p.status == "in_force"}
        submitted = {k: a.status in rm.SUBMITTED_STATES for k, a in latest.items()}
        states: dict[str, str] = {}
        # Two passes: a dependency's own state must be known before its dependant's.
        order = _topo([str(r.id) for r in reqs], edges)
        req_by = {str(r.id): r for r in reqs}
        for rid in order:
            r = req_by[rid]
            a = latest.get(rid)
            dec = current.get(str(a.id)) if a else None
            view = None
            if a is not None:
                permit_live = a.kind not in PERMIT_KINDS or rid in live
                view = rm.AttemptView(a.status, dec.outcome if dec else None, permit_live)
            unmet = rm.unmet_dependencies(rid, edges, states, submitted)
            states[rid] = rm.derive_state(r.applicable, view, not unmet)
        pending = {str(d.application_id) for d in current.values() if d.conditions_pending}
        return {
            "requirements": reqs,
            "applications": apps,
            "decisions": current,
            "edges": edges,
            "latest": latest,
            "states": states,
            "submitted": submitted,
            "conditions_pending": {k for k, a in latest.items() if str(a.id) in pending},
        }

    async def requirement_state(self, project_id: uuid.UUID, rid: uuid.UUID) -> str | None:
        snap = await self.state_snapshot(project_id)
        return snap["states"].get(str(rid))

    # ── clocks and timeline (rules 4, 5, 6) ────────────────────────────────

    def _spec(self, ptype: PermitType, variant: str | None) -> ClockSpec:
        try:
            return ClockSpec.from_catalogue(ptype.clock, variant or None)
        except ClockError as exc:
            raise PermitError(exc.code, 422) from exc

    def _app_spec(self, app: PermitApplication, ptype: PermitType, variant: str | None) -> ClockSpec:
        """The clock of one application.

        A discharge application filed under the permit's own requirement has no clock of its
        own in the data: the period of the permit type is the period of the permit, not of a
        discharge. It is reported as unknown (rule 5) and never borrowed. Filed under a
        requirement of a discharge type it runs on that type's clock and deemed outcome.
        """
        if app.kind == "discharge_of_conditions" and ptype.category != DISCHARGE_CATEGORY:
            return ClockSpec(None, None)
        return self._spec(ptype, variant)

    async def clock_of(
        self,
        app: PermitApplication,
        ptype: PermitType,
        variant: str,
        today: date,
        working_day: Callable[[date], bool],
        expected: date | None = None,
    ) -> dict[str, Any]:
        spec = self._app_spec(app, ptype, variant)
        events = [
            ClockEvent(e.kind, e.event_date, e.period, e.unit, e.reason)
            for e in await self.repo.list_clock_events(app.project_id, app.id)
        ]
        result = clock_forecast(
            spec,
            received_at=app.received_at,
            validated_at=app.validated_at,
            events=events,
            today=today,
            working_day=working_day,
            expected_date=expected,
        )
        out = result.as_dict()
        out["deemed_proposal"] = clock_deemed(spec, result, today=today, decided=app.status == "decided")
        out["deemed_requires_notice"] = spec.deemed_requires_notice
        out["period"] = spec.period
        out["unit"] = spec.unit
        out["start_event"] = spec.start_event
        return out

    async def timeline(self, project_id: uuid.UUID, today: date) -> dict[str, Any]:
        """Rule 6: needed-by, latest submit, forecast decision and conflicts per requirement."""
        roadmap = await self.require_roadmap(project_id)
        types = await self._types(roadmap)
        snap = await self.state_snapshot(project_id)
        wd = await self.working_day(project_id)
        activities = await self._activities(project_id, [r.needed_by_activity_id for r in snap["requirements"]])
        inputs = []
        clocks: dict[str, dict[str, Any]] = {}
        for r in snap["requirements"]:
            rid = str(r.id)
            ptype = types.get(r.permit_type_code)
            spec = self._spec(ptype, r.clock_variant) if ptype else ClockSpec(None, None)
            act = activities.get(str(r.needed_by_activity_id)) if r.needed_by_activity_id else None
            need, basis = rm.needed_by(act, r.needed_by_date)
            fc, reason, settled = None, None, False
            a = snap["latest"].get(rid)
            dec = snap["decisions"].get(str(a.id)) if a is not None else None
            if a is not None and a.status == "decided" and dec is not None:
                # The authority has answered: the date is a fact, not a forecast, and a grant leaves
                # no conflict behind. A refusal has no date to hold against the schedule.
                settled = snap["states"].get(rid) in cnd.GRANTED_REQ
                fc = dec.decision_date if settled else None
                reason = "decided" if settled else dec.outcome
            elif a is not None and a.status == "withdrawn":
                reason = "withdrawn"
            elif a is not None and ptype is not None and a.status not in ("planned", "preparing", "internal_review"):
                clocks[rid] = await self.clock_of(a, ptype, r.clock_variant, today, wd, r.expected_decision_date)
                fc = date.fromisoformat(clocks[rid]["forecast"]) if clocks[rid]["forecast"] else None
                reason = clocks[rid]["reason"]
            elif spec.period is None:
                fc = r.expected_decision_date
                reason = "no_statutory_period"
            inputs.append(
                rm.TimelineInput(
                    rid,
                    need,
                    basis,
                    clock_duration(spec, today, wd) if spec.period else None,
                    roadmap.buffer_days,
                    fc,
                    reason,
                    r.planned_submit_date,
                    r.conflict_accepted,
                    settled,
                )
            )
        rows = rm.timeline(inputs, snap["edges"])
        out = []
        for row, r in zip(rows, snap["requirements"], strict=True):
            d = row.as_dict()
            d["state"] = snap["states"].get(str(r.id))
            d["estimate"] = bool(clocks.get(str(r.id), {}).get("estimate")) or (
                d["forecast_reason"] == "no_statutory_period" and d["forecast_decision"] is not None
            )
            d["clock"] = clocks.get(str(r.id))
            out.append(d)
        return {"items": out, "edges": [e.__dict__ for e in snap["edges"]]}

    async def _activities(self, project_id: uuid.UUID, ids: list[Any]) -> dict[str, dict[str, Any]]:
        wanted = [i for i in ids if i]
        if not wanted:
            return {}
        from app.modules.schedule.models import Activity, Schedule

        stmt = (
            select(Activity)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Schedule.project_id == project_id, Activity.id.in_(wanted))
        )
        return {
            str(a.id): {
                "id": str(a.id),
                "name": a.name,
                "late_start": a.late_start,
                "early_start": a.early_start,
                "constraint_date": a.constraint_date,
            }
            for a in (await self.session.execute(stmt)).scalars().all()
        }

    async def push_milestone(
        self, project_id: uuid.UUID, rid: uuid.UUID, *, actor_id: uuid.UUID, today: date | None = None
    ) -> dict[str, Any]:
        """Rule 6, explicit user action only: write the forecast decision as a schedule milestone."""
        from app.modules.schedule.schemas import ActivityCreate, ActivityUpdate
        from app.modules.schedule.service import ScheduleService

        today = today or _today()
        req = await self.repo.get_requirement(project_id, rid, lock=True)
        if req is None:
            raise not_found("requirement_not_found")
        row = next(r for r in (await self.timeline(project_id, today))["items"] if r["requirement_id"] == str(rid))
        when = row["forecast_decision"] or row["latest_decision"]
        if when is None:
            raise PermitError("no_forecast_to_push", 422)
        svc = ScheduleService(self.session)
        if req.schedule_activity_id is not None:
            await self._check_link("activity", req.schedule_activity_id, project_id)
            await svc.update_activity(
                req.schedule_activity_id, ActivityUpdate(start_date=when, end_date=when), actor_id=str(actor_id)
            )
            action = "milestone_updated"
        else:
            listed = await svc.list_schedules_for_project(project_id)
            schedules = listed[0] if isinstance(listed, tuple) else listed
            if not schedules:
                raise PermitError("no_schedule", 422)
            act = await svc.create_activity(
                ActivityCreate(
                    schedule_id=schedules[0].id,
                    name=(req.title or req.permit_type_code)[:255],
                    start_date=when,
                    end_date=when,
                    activity_type="milestone",
                ),
                actor_id=str(actor_id),
            )
            req.schedule_activity_id = act.id
            action = "milestone_created"
        await self.session.flush()
        await self._audit(actor_id, "permit_requirement", rid, action, metadata={"date": when})
        return {"requirement_id": str(rid), "schedule_activity_id": str(req.schedule_activity_id), "date": when}

    # ── applications ───────────────────────────────────────────────────────

    async def create_application(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> PermitApplication:
        roadmap = await self.require_roadmap(project_id)
        rid = _uuid(data["requirement_id"])
        req = await self.repo.get_requirement(project_id, rid, lock=True)
        if req is None:
            raise not_found("requirement_not_found")
        kind = data.get("kind") or "new"
        if kind not in APPLICATION_KINDS:
            raise PermitError("application_kind_invalid", 422)
        types = await self._types(roadmap)
        ptype = self._type(types, req.permit_type_code)
        if kind == "early_start" and ptype.scope != "early_start":
            raise PermitError("early_start_needs_early_start_type", 422)
        parent = None
        if kind in CHILD_KINDS:
            parent_id = _uuid(data.get("parent_permit_id"))
            parent = await self.repo.get_permit(project_id, parent_id, lock=True) if parent_id else None
            if parent is None:
                raise not_found("permit_not_found")
            # Rule 14: only a permit that still exists in law can be varied, extended or discharged.
            # A lapsed permit can still be extended (rule 9), nothing else.
            allowed = (*LIVE_PARENT, "lapsed") if kind == "extension_of_validity" else LIVE_PARENT
            if parent.status not in allowed:
                raise conflict("parent_permit_not_live", detail=parent.status)
            own = parent.requirement_id == rid
            if kind in SAME_REQUIREMENT_KINDS and not own:
                raise PermitError("parent_permit_of_other_requirement", 422)
            if kind == "discharge_of_conditions" and not own and ptype.category != DISCHARGE_CATEGORY:
                raise PermitError("parent_permit_of_other_requirement", 422)
        all_apps = await self.repo.list_applications(project_id)
        cond_ids: list[str] = []
        if kind == "discharge_of_conditions":
            pending = {
                str(cid)
                for a in all_apps
                if a.kind == kind and a.status not in ("decided", "withdrawn")
                for cid in a.discharges_condition_ids or []
            }
            for raw in data.get("discharges_condition_ids") or []:
                c = await self.repo.get_condition(project_id, _uuid(raw))
                if c is None or c.permit_id != parent.id:
                    raise not_found("condition_not_found")
                if not c.confirmed:
                    # Rule 15: a proposal nobody confirmed is not a condition yet.
                    raise conflict("condition_not_confirmed")
                if c.status not in ("open", "evidence_submitted"):
                    raise conflict("condition_not_open")
                if str(c.id) in pending:
                    # Two applications for one condition: the refusal of one would undo the other.
                    raise conflict("condition_in_open_discharge_application", detail=c.number)
                if str(c.id) not in cond_ids:
                    cond_ids.append(str(c.id))
            if not cond_ids:
                raise PermitError("discharge_needs_conditions", 422)
        applicant_role, applicant_source = "", ""
        if kind in ("discharge_of_conditions", "variation", "amendment_non_material"):
            # Rule 2: who files a change to an issued permit is the delivery model's own allocation.
            applicant_role, applicant_source = await self.allocated_applicant(
                project_id, CONDITIONS_CHANGE_ALLOCATION, req.applicant_role, "requirement"
            )
        same = [a for a in all_apps if a.requirement_id == rid and a.kind == kind]
        if kind in ("new", "early_start") and any(a.status not in ("decided", "withdrawn") for a in same):
            raise conflict("application_open")
        for key in ("review_cycle_ids",):
            for v in data.get(key) or []:
                await self._check_link("review_cycle", v, project_id)
        await self._check_link("submission", data.get("submission_id"), project_id)
        await self._check_link("cde_container", data.get("cde_container_id"), project_id)
        app = PermitApplication(
            project_id=project_id,
            requirement_id=rid,
            attempt=max((a.attempt for a in same), default=0) + 1,
            kind=kind,
            parent_permit_id=parent.id if parent else None,
            discharges_condition_ids=cond_ids,
            applicant_role=applicant_role,
            applicant_source=applicant_source,
            authority_name=data.get("authority_name") or "",
            authority_reference=data.get("authority_reference") or "",
            review_cycle_ids=[str(v) for v in data.get("review_cycle_ids") or []],
            submission_id=_uuid(data.get("submission_id")),
            cde_container_id=_uuid(data.get("cde_container_id")),
            created_by=actor_id,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(app)
        except IntegrityError as exc:
            raise conflict("concurrent_application") from exc
        await self._audit(actor_id, "permit_application", app.id, "application_created", metadata={"kind": kind})
        return app

    async def update_application(
        self, project_id: uuid.UUID, aid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> PermitApplication:
        app = await self.repo.get_application(project_id, aid, lock=True)
        if app is None:
            raise not_found("application_not_found")
        if set(data) - {"appeal_note"}:
            # The appeal note is the one thing still written on a closed application.
            guards.application_edit(app)
        for key in ("submitted_at", "received_at", "validated_at"):
            _not_in_future(data.get(key), _today())
        for v in data.get("review_cycle_ids") or []:
            await self._check_link("review_cycle", v, project_id)
        await self._check_link("submission", data.get("submission_id"), project_id)
        await self._check_link("cde_container", data.get("cde_container_id"), project_id)
        for key, value in data.items():
            if key == "review_cycle_ids":
                value = [str(v) for v in value or []]
            elif key in ("submission_id", "cde_container_id"):
                value = _uuid(value)
            setattr(app, key, value)
        await self.session.flush()
        await self._audit(actor_id, "permit_application", app.id, "application_updated", metadata=_jsonable(data))
        return app

    async def transition_application(
        self,
        project_id: uuid.UUID,
        aid: uuid.UUID,
        target: str,
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
        on_date: date | None = None,
        today: date | None = None,
        reason: str | None = None,
    ) -> PermitApplication:
        """User transitions; ``decided`` only by recording a decision."""
        if target not in USER_TARGETS:
            raise PermitError("transition_not_allowed", 422)
        today = today or _today()
        _not_in_future(on_date, today)
        roadmap = await self.require_roadmap(project_id)
        app = await self.repo.get_application(project_id, aid, lock=True)
        if app is None:
            raise not_found("application_not_found")
        guards.application_transition(app, target, roadmap.internal_review)
        when = on_date or today
        if target == "submitted":
            await self._admit_submit(roadmap, app, can_manage)
            app.submitted_at = app.submitted_at or when
            app.received_at = app.received_at or when
        if target == "validated":
            app.validated_at = when
        if target == "internal_review" and roadmap.approval_route_id is not None:
            await self._start_internal_release(roadmap, app, actor_id)
        previous = app.status
        await self._fsm(APPLICATION_FSM, app, target, actor_id, reason)
        if app.kind == "discharge_of_conditions":
            await self._discharge_app_moved(app, previous, target, actor_id)
        await self.session.flush()
        if target == "submitted":
            self._publish(
                "application.submitted",
                {
                    "project_id": str(project_id),
                    "application_id": str(app.id),
                    "requirement_id": str(app.requirement_id),
                },
            )
        return app

    async def _admit_submit(self, roadmap: PermitRoadmap, app: PermitApplication, can_manage: bool) -> None:
        """Rule 3 (dependencies) and the internal release of lead decision k, once it runs.

        Whether the project has an internal release at all is the guard's question
        (``guards.application_transition``); this asks what only a query answers.
        """
        if app.kind in ("new", "early_start"):
            snap = await self.state_snapshot(app.project_id)
            unmet = rm.unmet_dependencies(str(app.requirement_id), snap["edges"], snap["states"], snap["submitted"])
            if unmet:
                raise PermitError("dependency_not_met", 422, detail=",".join(unmet))
        if app.status == "internal_review" and app.approval_instance_id is not None:
            from app.modules.approval_routes.models import Instance

            inst = await self.session.get(Instance, app.approval_instance_id)
            if inst is None or inst.status != "approved":
                raise conflict("internal_release_pending")
        elif app.status == "internal_review" and not can_manage:
            raise forbidden("release_needs_manager")

    async def _start_internal_release(self, roadmap: PermitRoadmap, app: PermitApplication, actor_id: Any) -> None:
        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        # Checked again here: the route may have been archived or moved since it was stored.
        await self._check_route(roadmap.approval_route_id, app.project_id)
        inst = await ApprovalRouteService(self.session).start_instance(
            InstanceCreate(route_id=roadmap.approval_route_id, target_kind=TARGET_KIND, target_id=app.id),
            started_by=_uuid(actor_id),
        )
        app.approval_instance_id = inst.id

    async def apply_route_verdict(self, aid: uuid.UUID, *, instance_id: Any, verdict: str) -> None:
        """An internal release rejected or cancelled sends the application back to preparation."""
        app = (
            await self.session.execute(select(PermitApplication).where(PermitApplication.id == aid).with_for_update())
        ).scalar_one_or_none()
        if app is None or app.status != "internal_review" or _s(app.approval_instance_id) != _s(instance_id):
            return
        if verdict in ("rejected", "cancelled"):
            await self._fsm(APPLICATION_FSM, app, "preparing", None, f"internal release {verdict}")
            app.approval_instance_id = None
            await self.session.flush()

    async def _discharge_app_moved(self, app: PermitApplication, previous: str, target: str, actor_id: Any) -> None:
        conds = [
            await self.repo.get_condition(app.project_id, _uuid(c), lock=True) for c in app.discharges_condition_ids
        ]
        for c in conds:
            if c is None:
                continue
            if target == "submitted" and c.status in ("open", "evidence_submitted"):
                await self._fsm(CONDITION_FSM, c, "discharge_applied", actor_id, "discharge applied for")
            elif target == "withdrawn" and c.status == "discharge_applied":
                await self._fsm(CONDITION_FSM, c, "open", actor_id, "discharge application withdrawn")

    async def add_clock_event(
        self, project_id: uuid.UUID, aid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> ClockEventRow:
        roadmap = await self.require_roadmap(project_id)
        app = await self.repo.get_application(project_id, aid, lock=True)
        if app is None:
            raise not_found("application_not_found")
        guards.application_clock(app)
        req = await self.repo.get_requirement(project_id, app.requirement_id)
        ptype = self._type(await self._types(roadmap), req.permit_type_code)
        spec = self._app_spec(app, ptype, req.clock_variant)
        _not_in_future(data["at"], _today())
        existing = [
            ClockEvent(e.kind, e.event_date, e.period, e.unit, e.reason)
            for e in await self.repo.list_clock_events(project_id, aid)
        ]
        new = ClockEvent(data["kind"], data["at"], data.get("period"), data.get("unit"), data.get("reason") or "")
        try:
            check_stop(spec, existing, new)
            check_extension(spec, existing, new)
        except ClockError as exc:
            raise PermitError(exc.code, 422) from exc
        row = await self.repo.add(
            ClockEventRow(
                project_id=project_id,
                application_id=aid,
                kind=new.kind,
                event_date=new.at,
                period=new.period,
                unit=new.unit,
                reason=new.reason,
                created_by=actor_id,
            )
        )
        if new.kind == "stop" and app.status in ("submitted", "validated", "under_review"):
            await self._fsm(APPLICATION_FSM, app, "info_requested", actor_id, new.reason or "clock stopped")
        elif new.kind == "resume" and app.status == "info_requested":
            await self._fsm(APPLICATION_FSM, app, "under_review", actor_id, "clock resumed")
        await self._audit(actor_id, "permit_application", aid, f"clock_{new.kind}", metadata=_jsonable(data))
        return row

    # ── decisions (rules 7, 8, 10, 13, 14) ─────────────────────────────────

    async def record_decision(
        self,
        project_id: uuid.UUID,
        aid: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        today: date | None = None,
    ) -> dict[str, Any]:
        today = today or _today()
        for key in ("decision_date", "served_date"):
            _not_in_future(data.get(key), today)
        _check_security(data.get("security_amount"), data.get("security_currency"))
        roadmap = await self.require_roadmap(project_id)
        app = await self.repo.get_application(project_id, aid, lock=True)
        if app is None:
            raise not_found("application_not_found")
        guards.application_decide(app)
        outcome = data["outcome"]
        if outcome not in DECISION_OUTCOMES:
            raise PermitError("outcome_invalid", 422)
        req = await self.repo.get_requirement(project_id, app.requirement_id, lock=True)
        types = await self._types(roadmap)
        ptype = self._type(types, req.permit_type_code)
        conds_in = list(data.get("conditions") or [])
        await self._check_link("cde_revision", data.get("document_revision_id"), project_id)
        for raw in data.get("scope_activity_ids") or []:
            await self._check_link("activity", raw, project_id)
        if outcome == "granted_with_conditions" and not conds_in and not data.get("conditions_pending"):
            raise PermitError("conditional_grant_needs_conditions", 422)
        if outcome == "partially_granted" and not (data.get("scope_note") or "").strip():
            raise PermitError("partial_grant_needs_scope", 422)
        if outcome == "deemed_granted":
            wd = await self.working_day(project_id)
            clock = await self.clock_of(app, ptype, req.clock_variant, today, wd)
            if clock["deemed_proposal"] is None:
                raise PermitError("deemed_not_available", 422)
            if clock["deemed_requires_notice"] and not data.get("document_revision_id"):
                raise PermitError("deemed_needs_notice", 422)
        if outcome in NOT_REFUSED and app.kind in CHILD_KINDS and app.kind != "discharge_of_conditions":
            # Rule 14: the parent may have been revoked, lapsed or already varied since the filing.
            parent = await self.repo.get_permit(project_id, app.parent_permit_id, lock=True)
            allowed = (*LIVE_PARENT, "lapsed") if app.kind == "extension_of_validity" else LIVE_PARENT
            if parent is None or parent.status not in allowed:
                raise conflict("parent_permit_not_live", detail=parent.status if parent else "")
        if _is_early(app, ptype) and outcome in NOT_REFUSED and not data.get("conditions_pending"):
            # Rule 10. With "conditions to follow" the same test runs when the register is completed.
            _check_early_start_purposes(ptype, [(c.get("kind"), c.get("purpose")) for c in conds_in])
        for c in conds_in:
            _validate_condition_input(c)
        snapshot = {
            "outcome": outcome,
            # JSON column: store the ISO date, not the date object the request parsed.
            "decision_date": _iso(data["decision_date"]),
            "reference": data.get("reference") or "",
            "scope_note": data.get("scope_note") or "",
            "conditions": [{"number": c["number"], "text": c["text"]} for c in conds_in],
        }
        decision = PermitDecision(
            project_id=project_id,
            application_id=aid,
            revision=1,
            outcome=outcome,
            decision_date=data["decision_date"],
            served_date=data.get("served_date"),
            reference=data.get("reference") or "",
            scope_note=data.get("scope_note") or "",
            scope_activity_ids=[str(v) for v in data.get("scope_activity_ids") or []],
            conditions_pending=bool(data.get("conditions_pending")),
            appeal_deadline=data.get("appeal_deadline"),
            document_revision_id=_uuid(data.get("document_revision_id")),
            content_hash=_hash(snapshot),
            deemed=outcome == "deemed_granted",
            decided_by=actor_id,
            snapshot=snapshot,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(decision)
        except IntegrityError as exc:
            raise conflict("concurrent_decision") from exc
        await self._fsm(APPLICATION_FSM, app, "decided", actor_id, f"decision {outcome}")
        result: dict[str, Any] = {"decision": decision, "permit": None, "follow_up_requirement": None}
        if outcome in NOT_REFUSED and app.kind in PERMIT_KINDS:
            result["permit"] = await self._grant(app, req, ptype, decision, conds_in, data, actor_id)
        elif outcome in NOT_REFUSED and app.kind == "extension_of_validity":
            await self._extend(app, ptype, actor_id)
        if app.kind == "discharge_of_conditions":
            await self._apply_discharge_decision(app, decision, data, actor_id)
        if outcome == "partially_granted" and app.kind in ("new", "early_start"):
            result["follow_up_requirement"] = await self.repo.add(
                PermitRequirement(
                    project_id=project_id,
                    permit_type_code=req.permit_type_code,
                    title=f"{req.title or req.permit_type_code} (remaining scope)"[:255],
                    applicant_role=req.applicant_role,
                    applicant_source=req.applicant_source,
                    responsible_user_id=req.responsible_user_id,
                    governance_area_code=req.governance_area_code,
                    follow_up_of_id=req.id,
                    sort_order=req.sort_order + 1,
                )
            )
        if outcome == "refused":
            result["next"] = ["resubmit", "appeal_note"]
        await self.session.flush()
        await self._audit(
            actor_id,
            "permit_application",
            aid,
            "decision_recorded",
            metadata={"outcome": outcome, "decision_id": str(decision.id)},
        )
        self._publish(
            "decision.recorded",
            {"project_id": str(project_id), "application_id": str(aid), "outcome": outcome},
        )
        self._readiness_changed(project_id)
        return result

    async def correct_decision(
        self, project_id: uuid.UUID, did: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> PermitDecision:
        """Correct how a decision was recorded: a new immutable revision that supersedes the old one.

        The outcome and the conditions are what the authority decided and cannot be corrected
        here; a different outcome is a different decision (resubmission, variation, appeal). The
        dates, the reference, the scope note and the notice document can. The permit moves to
        the new revision and its not-started lapse date is counted again from the served date.
        """
        today = _today()
        old = await self.repo.get_decision(project_id, did, lock=True)
        if old is None:
            raise not_found("decision_not_found")
        newest = _current_decisions(await self.repo.list_decisions(project_id)).get(str(old.application_id))
        guards.decision_current(old, newest)
        if not (data.get("reason") or "").strip():
            raise PermitError("correction_needs_reason", 422)
        for key in ("decision_date", "served_date"):
            _not_in_future(data.get(key), today)
        await self._check_link("cde_revision", data.get("document_revision_id"), project_id)
        fields = ("decision_date", "served_date", "reference", "scope_note", "appeal_deadline", "document_revision_id")
        values = {k: (data[k] if k in data else getattr(old, k)) for k in fields}
        if values["decision_date"] is None:
            raise PermitError("field_not_nullable", 422, detail="decision_date")
        values["document_revision_id"] = _uuid(values["document_revision_id"])
        values["reference"] = values["reference"] or ""
        values["scope_note"] = values["scope_note"] or ""
        if old.outcome == "partially_granted" and not values["scope_note"].strip():
            raise PermitError("partial_grant_needs_scope", 422)
        snapshot = {
            **(old.snapshot or {}),
            "decision_date": _iso(values["decision_date"]),
            "reference": values["reference"],
            "scope_note": values["scope_note"],
            "correction_reason": data["reason"].strip(),
        }
        new = PermitDecision(
            project_id=project_id,
            application_id=old.application_id,
            revision=old.revision + 1,
            supersedes_id=old.id,
            outcome=old.outcome,
            scope_activity_ids=list(old.scope_activity_ids or []),
            conditions_pending=old.conditions_pending,
            content_hash=_hash(snapshot),
            deemed=old.deemed,
            decided_by=actor_id,
            snapshot=snapshot,
            **values,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(new)
        except IntegrityError as exc:
            raise conflict("concurrent_decision") from exc
        permit = (await self.session.execute(select(Permit).where(Permit.decision_id == old.id))).scalar_one_or_none()
        if permit is not None:
            permit.decision_id = new.id
            permit.reference = new.reference
            served = new.served_date or new.decision_date
            moved = served != (old.served_date or old.decision_date)
            if moved and permit.valid_until is not None and permit.start_notified_at is None:
                # The not-started lapse date runs from the day the decision was served; an
                # extension already granted keeps its distance from that day.
                validity = await self._validity(permit)
                was = cnd.valid_until(old.served_date or old.decision_date, None, validity)
                now = cnd.valid_until(served, None, validity)
                if was is not None and now is not None:
                    permit.valid_until = permit.valid_until + (now - was)
        await self.session.flush()
        await self._audit(
            actor_id,
            "permit_decision",
            new.id,
            "decision_corrected",
            before_state={"decision_id": str(old.id), "revision": old.revision},
            metadata={"revision": new.revision, "reason": data["reason"].strip()},
        )
        self._publish(
            "decision.recorded",
            {"project_id": str(project_id), "application_id": str(old.application_id), "outcome": old.outcome},
        )
        return new

    async def _grant(
        self,
        app: PermitApplication,
        req: PermitRequirement,
        ptype: PermitType,
        decision: PermitDecision,
        conds_in: list[dict[str, Any]],
        data: dict[str, Any],
        actor_id: Any,
    ) -> Permit:
        served = decision.served_date or decision.decision_date
        security = data.get("security_amount")
        permit = await self.repo.add(
            Permit(
                project_id=app.project_id,
                requirement_id=req.id,
                application_id=app.id,
                decision_id=decision.id,
                permit_type_code=req.permit_type_code,
                scope="partial" if decision.outcome == "partially_granted" else ptype.scope,
                status="in_force",
                reference=decision.reference,
                revocable=ptype.revocable,
                security_amount=Decimal(str(security)) if security not in (None, "") else None,
                security_currency=(data.get("security_currency") or "").upper(),
                valid_until=cnd.valid_until(served, None, ptype.validity),
            )
        )
        if app.kind in ("variation", "amendment_non_material") and app.parent_permit_id is not None:
            await self._vary(app, permit, conds_in, data.get("removed_condition_numbers") or [], actor_id)
        else:
            for c in conds_in:
                await self._add_condition(permit, c, decision_id=decision.id, actor_id=actor_id)
        self._publish(
            "permit.state_changed",
            {"project_id": str(app.project_id), "permit_id": str(permit.id), "state": "in_force"},
        )
        return permit

    async def _vary(
        self, app: PermitApplication, permit: Permit, conds_in: list[dict[str, Any]], removed: list[str], actor_id: Any
    ) -> None:
        """Rule 14: supersede the parent permit and its conditions, carry forward the rest."""
        parent = await self.repo.get_permit(app.project_id, app.parent_permit_id, lock=True)
        old_rows = await self.repo.conditions_of_permit(app.project_id, parent.id)
        old = [
            cnd.OldCondition(str(c.id), c.number, c.text, c.kind, c.trigger, c.status, c.confirmed) for c in old_rows
        ]
        new = [cnd.NewCondition(c["number"], c["text"], c["kind"], c["trigger"]) for c in conds_in]
        by_number = {c["number"]: c for c in conds_in}
        old_by_id = {str(c.id): c for c in old_rows}
        moved: dict[str, str] = {}  # old condition id -> the condition that carries it on
        for carried in cnd.carry_forward(old, new, removed):
            src = old_by_id.get(carried.original_id or "")
            base = by_number.get(carried.number) or (_condition_payload(src) if src is not None else {})
            copied = src is not None and not carried.replaced
            row = await self._add_condition(
                permit,
                {
                    **base,
                    "number": carried.number,
                    "text": carried.text,
                    "kind": carried.kind,
                    "trigger": carried.trigger,
                    # A copy stays what it was: an AI proposal keeps its confidence and its span.
                    "confidence": src.confidence if copied else None,
                    "text_span": src.text_span if copied else "",
                    "passage": src.source_passage if copied else "",
                },
                decision_id=permit.decision_id,
                actor_id=actor_id,
                original_id=_uuid(carried.original_id),
                source=src.source if copied else "manual",
                confirmed=carried.confirmed,
                named_now=False,
            )
            if src is None:
                continue
            moved[str(src.id)] = str(row.id)
            # Evidence follows the condition whether or not it reopens (rule 14).
            for ev in await self.repo.list_evidence(app.project_id, src.id):
                await self.repo.add(
                    ConditionEvidence(
                        project_id=app.project_id,
                        condition_id=row.id,
                        kind=ev.kind,
                        ref_id=ev.ref_id,
                        content_hash=ev.content_hash,
                        note=ev.note,
                        added_by=ev.added_by,
                    )
                )
            if not carried.keep_state:
                continue
            row.status = carried.keep_state
            row.evidence_submitted_by = src.evidence_submitted_by
            row.breach_ref_kind, row.breach_ref_id, row.breach_note = (
                src.breach_ref_kind,
                src.breach_ref_id,
                src.breach_note,
            )
            # How it was closed travels with it, pointing back at the original record.
            for d in await self.repo.list_discharges(app.project_id, src.id):
                await self.repo.add(
                    ConditionDischarge(
                        project_id=app.project_id,
                        condition_id=row.id,
                        mode=d.mode,
                        decided_by=d.decided_by,
                        discharge_application_id=d.discharge_application_id,
                        verifier_user_id=d.verifier_user_id,
                        discharged_on=d.discharged_on,
                        document_revision_id=d.document_revision_id,
                        note=d.note,
                        evidence_snapshot=list(d.evidence_snapshot or []),
                        carried_from_id=d.carried_from_id or d.id,
                    )
                )
        # A discharge application still with the authority now names the carried condition, so
        # its decision reaches a live row instead of a superseded one.
        for other in await self.repo.list_applications(app.project_id):
            if other.kind != "discharge_of_conditions" or other.status in ("decided", "withdrawn"):
                continue
            ids = [str(i) for i in other.discharges_condition_ids or []]
            if any(i in moved for i in ids):
                other.discharges_condition_ids = [moved.get(i, i) for i in ids]
                other.parent_permit_id = permit.id
        for c in old_rows:
            if c.status != "superseded" and c.status != "waived":
                await self._fsm(CONDITION_FSM, c, "superseded", actor_id, "permit varied")
        await self._fsm(PERMIT_FSM, parent, "superseded", actor_id, "varied")
        parent.superseded_by_id = permit.id
        permit.valid_until = parent.valid_until
        permit.start_notified_at = parent.start_notified_at
        permit.paused_since = parent.paused_since

    async def _extend(self, app: PermitApplication, ptype: PermitType, actor_id: Any) -> None:
        parent = await self.repo.get_permit(app.project_id, app.parent_permit_id, lock=True)
        if parent.valid_until is None:
            return
        new_until = cnd.extended_until(parent.valid_until, ptype.validity)
        if new_until is None:
            raise PermitError("validity_extension_not_in_catalogue", 422)
        parent.valid_until = new_until
        if parent.status == "lapsed":
            await self._fsm(PERMIT_FSM, parent, "in_force", actor_id, "validity extended")
        await self._audit(
            actor_id, "authority_permit", parent.id, "validity_extended", metadata={"until": str(new_until)}
        )

    async def _apply_discharge_decision(
        self, app: PermitApplication, decision: PermitDecision, data: dict[str, Any], actor_id: Any
    ) -> None:
        """Rule 13: a decided discharge application discharges each listed condition it names."""
        listed = list(app.discharges_condition_ids)
        granted = decision.outcome in NOT_REFUSED
        # ``None`` = the authority discharged everything applied for. An empty list is an answer
        # too: it discharged none of them (partial discharge per condition, rule 13).
        named = data.get("discharged_condition_ids")
        chosen = {str(c) for c in (listed if named is None else named)} if granted else set()
        if chosen - set(listed):
            raise PermitError("condition_not_in_application", 422)
        mode = "deemed_discharged" if decision.deemed else "authority_discharged"
        for raw in listed:
            c = await self.repo.get_condition(app.project_id, _uuid(raw), lock=True)
            if c is None or c.status != "discharge_applied":
                continue
            if raw in chosen:
                await self._fsm(CONDITION_FSM, c, "discharged", actor_id, mode)
                await self.repo.add(
                    ConditionDischarge(
                        project_id=app.project_id,
                        condition_id=c.id,
                        mode=mode,
                        decided_by=actor_id,
                        discharge_application_id=app.id,
                        discharged_on=decision.decision_date,
                        document_revision_id=decision.document_revision_id,
                        evidence_snapshot=await self._evidence_snapshot(c),
                    )
                )
                self._publish(
                    "condition.discharged",
                    {"project_id": str(app.project_id), "condition_id": str(c.id), "mode": mode},
                )
            else:
                await self._fsm(CONDITION_FSM, c, "open", actor_id, "discharge refused")

    async def deemed_status(self, project_id: uuid.UUID, aid: uuid.UUID, today: date) -> dict[str, Any]:
        """Rule 7: the deemed outcome the module PROPOSES; it takes effect only through ``record_decision``."""
        roadmap = await self.require_roadmap(project_id)
        app = await self.repo.get_application(project_id, aid)
        if app is None:
            raise not_found("application_not_found")
        req = await self.repo.get_requirement(project_id, app.requirement_id)
        ptype = self._type(await self._types(roadmap), req.permit_type_code)
        clock = await self.clock_of(app, ptype, req.clock_variant, today, await self.working_day(project_id))
        return {
            "application_id": str(aid),
            "proposal": clock["deemed_proposal"],
            "requires_notice": clock["deemed_requires_notice"],
            "clock": clock,
        }

    # ── permits ────────────────────────────────────────────────────────────

    async def _validity(self, permit: Permit) -> Any:
        roadmap = await self.require_roadmap(permit.project_id)
        ptype = (await self._types(roadmap)).get(permit.permit_type_code)
        return ptype.validity if ptype is not None else None

    async def notify_start(
        self, project_id: uuid.UUID, pid: uuid.UUID, on_date: date, *, actor_id: uuid.UUID
    ) -> Permit:
        """Rule 9: a start notice ends the not-started lapse clock."""
        _not_in_future(on_date, _today())
        permit = await self.repo.get_permit(project_id, pid, lock=True)
        if permit is None:
            raise not_found("permit_not_found")
        guards.permit_start(permit)
        permit.start_notified_at = on_date
        permit.valid_until = None
        await self.session.flush()
        await self._audit(actor_id, "authority_permit", pid, "start_notified", metadata={"date": on_date.isoformat()})
        return permit

    async def notify_interruption(
        self, project_id: uuid.UUID, pid: uuid.UUID, on_date: date | None, *, resumed: bool, actor_id: uuid.UUID
    ) -> Permit:
        """Rule 9, ``lapse_if_paused``: started work that stops puts the permit back on a lapse clock.

        Recording the interruption sets the lapse date from the catalogue period; recording
        that work resumed clears it. Where the catalogue gives no such period nothing lapses
        and the interruption is only noted.
        """
        today = _today()
        _not_in_future(on_date, today)
        permit = await self.repo.get_permit(project_id, pid, lock=True)
        if permit is None:
            raise not_found("permit_not_found")
        guards.permit_interruption(permit, resumed)
        when = on_date or today
        if resumed:
            if when < permit.paused_since:
                raise PermitError("resume_before_interruption", 422)
            permit.paused_since, permit.valid_until = None, None
            action = "work_resumed"
        else:
            if when < permit.start_notified_at:
                raise PermitError("interruption_before_start", 422)
            permit.paused_since = when
            permit.valid_until = cnd.paused_until(when, await self._validity(permit))
            action = "work_interrupted"
        await self.session.flush()
        await self._audit(actor_id, "authority_permit", pid, action, metadata={"date": when.isoformat()})
        return permit

    async def transition_permit(
        self, project_id: uuid.UUID, pid: uuid.UUID, target: str, *, actor_id: uuid.UUID, reason: str | None
    ) -> Permit:
        permit = await self.repo.get_permit(project_id, pid, lock=True)
        if permit is None:
            raise not_found("permit_not_found")
        guards.permit_transition(permit, target)
        await self._fsm(PERMIT_FSM, permit, target, actor_id, reason)
        await self.session.flush()
        self._publish("permit.state_changed", {"project_id": str(project_id), "permit_id": str(pid), "state": target})
        self._readiness_changed(project_id)
        return permit

    # ── conditions ─────────────────────────────────────────────────────────

    async def _add_condition(
        self,
        permit: Permit,
        c: dict[str, Any],
        *,
        decision_id: Any,
        actor_id: Any,
        source: str = "manual",
        confirmed: bool = True,
        original_id: uuid.UUID | None = None,
        named_now: bool = True,
    ) -> PermitCondition:
        """Store one condition. ``named_now`` is False where the owner is carried over from the
        condition this one replaces (a variation), not named by the caller."""
        _validate_condition_input(c)
        await self._check_link("gate_condition", c.get("gate_condition_id"), permit.project_id)
        if named_now:
            await self._check_member(permit.project_id, c.get("owner_user_id"))
        row = PermitCondition(
            project_id=permit.project_id,
            permit_id=permit.id,
            number=str(c["number"]).strip(),
            text=c["text"],
            text_hash=cnd.text_hash(c["text"]),
            kind=c["kind"],
            national_kind=c.get("national_kind") or "",
            trigger=c.get("trigger") or "",
            stage_ref=c.get("stage_ref") or "",
            event_text=c.get("event_text") or "",
            due_date=c.get("due_date"),
            topic=c.get("topic") or "other",
            purpose=c.get("purpose") or "",
            owner_user_id=_uuid(c.get("owner_user_id")),
            responsible_party=c.get("responsible_party") or "",
            requires_authority_approval=bool(c.get("requires_authority_approval")),
            evidence_required=c.get("evidence_required") or "",
            hse_override=c.get("hse_relevant"),
            source=source,
            confidence=Decimal(str(c["confidence"])) if c.get("confidence") is not None else None,
            text_span=c.get("text_span") or "",
            source_passage=c.get("passage") or "",
            confirmed=confirmed,
            gate_condition_id=_uuid(c.get("gate_condition_id")),
            original_id=original_id,
            decision_id=_uuid(decision_id),
            created_by=_uuid(actor_id),
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(row)
        except IntegrityError as exc:
            raise conflict("condition_number_taken") from exc
        if confirmed:
            self._publish(
                "condition.created",
                {"project_id": str(permit.project_id), "condition_id": str(row.id), "permit_id": str(permit.id)},
            )
            await self._notify(
                row.owner_user_id,
                "condition_assigned",
                "permit_condition",
                row.id,
                {"project_id": str(permit.project_id), "number": row.number},
            )
        return row

    async def create_condition(
        self, project_id: uuid.UUID, pid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> PermitCondition:
        permit = await self.repo.get_permit(project_id, pid)
        if permit is None:
            raise not_found("permit_not_found")
        row = await self._add_condition(permit, data, decision_id=permit.decision_id, actor_id=actor_id)
        await self._audit(actor_id, "permit_condition", row.id, "condition_created")
        self._readiness_changed(project_id)
        return row

    async def complete_register(self, project_id: uuid.UUID, did: uuid.UUID, *, actor_id: uuid.UUID) -> PermitDecision:
        """Conditions announced as "to follow" are all entered: the register is complete again (rule 8)."""
        dec = await self.repo.get_decision(project_id, did, lock=True)
        if dec is None:
            raise not_found("decision_not_found")
        newest = _current_decisions(await self.repo.list_decisions(project_id)).get(str(dec.application_id))
        guards.decision_complete_register(dec, newest)
        permit = (await self.session.execute(select(Permit).where(Permit.decision_id == dec.id))).scalar_one_or_none()
        if permit is not None:
            conds = [c for c in await self.repo.conditions_of_permit(project_id, permit.id) if c.confirmed]
            if dec.outcome == "granted_with_conditions" and not conds:
                raise PermitError("conditional_grant_needs_conditions", 422)
            roadmap = await self.require_roadmap(project_id)
            ptype = (await self._types(roadmap)).get(permit.permit_type_code)
            if permit.scope == "early_start" or (ptype is not None and ptype.scope == "early_start"):
                # Rule 10: "conditions to follow" postponed this test at the decision, it does not waive it.
                live = [(c.kind, c.purpose) for c in conds if c.status not in ("superseded", "waived")]
                _check_early_start_purposes(ptype, live)
        # The decision row stays immutable in substance; only the register flag is cleared.
        dec.conditions_pending = False
        await self.session.flush()
        await self._audit(actor_id, "permit_decision", did, "register_completed")
        self._readiness_changed(project_id)
        return dec

    async def _owned_condition(
        self, project_id: uuid.UUID, cid: uuid.UUID, actor_id: uuid.UUID, can_manage: bool, *, lock: bool = True
    ) -> PermitCondition:
        """The condition, for its owner or a holder of ``permits.manage`` acting in the owner's place."""
        c = await self.repo.get_condition(project_id, cid, lock=lock)
        if c is None:
            raise not_found("condition_not_found")
        guards.condition_owned(c, actor_id, can_manage)
        return c

    async def update_condition(
        self,
        project_id: uuid.UUID,
        cid: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> PermitCondition:
        c = await self._owned_condition(project_id, cid, actor_id, can_manage)
        guards.condition_edit(c)
        if "text" in data and c.status not in ("open",):
            raise conflict("condition_text_frozen")
        current = {**_condition_payload(c), "gate_condition_id": c.gate_condition_id}
        changed = {
            k
            for k, v in data.items()
            if k in current and current[k] != (_uuid(v) if k in ("owner_user_id", "gate_condition_id") else v)
        }
        # What a gate reads (finding 4) and who the owner is (four-eyes, rule 13) are settled
        # while the condition is open and stay as they are afterwards.
        guarded = changed & set(GATE_CONDITION_FIELDS)
        if guarded and not can_manage:
            raise forbidden("manage_required", detail=",".join(sorted(guarded)))
        guards.condition_frozen(c, changed & {*GATE_CONDITION_FIELDS, "owner_user_id"})
        if data.get("gate_condition_id"):
            await self._check_link("gate_condition", data["gate_condition_id"], project_id)
        if "owner_user_id" in changed:
            await self._check_member(project_id, data["owner_user_id"])
        # C5: the condition is validated as it will be stored, a cleared field included. Clearing
        # the due date of a ``by_date`` condition is refused like creating one without it.
        merged_input = {**_condition_payload(c), **data}
        _validate_condition_input(merged_input)
        before = _condition_payload(c)
        for key, value in data.items():
            if key in ("owner_user_id", "gate_condition_id"):
                value = _uuid(value)
            if key == "hse_relevant":
                key = "hse_override"
            setattr(c, key, value)
        if "text" in data:
            c.text_hash = cnd.text_hash(c.text)
        await self.session.flush()
        await self._audit(
            actor_id,
            "permit_condition",
            cid,
            "condition_updated",
            before_state=_jsonable(before),
            metadata=_jsonable(data),
        )
        if "owner_user_id" in data and data["owner_user_id"]:
            await self._notify(
                c.owner_user_id,
                "condition_assigned",
                "permit_condition",
                c.id,
                {"project_id": str(project_id), "number": c.number},
            )
        if guarded:
            self._readiness_changed(project_id)
        return c

    async def assign_owner(
        self, project_id: uuid.UUID, ids: list[uuid.UUID], owner: uuid.UUID, *, actor_id: uuid.UUID
    ) -> list[PermitCondition]:
        """Bulk assignment, behind ``permits.manage`` at the router."""
        out = []
        for cid in ids:
            out.append(
                await self.update_condition(
                    project_id, cid, {"owner_user_id": owner}, actor_id=actor_id, can_manage=True
                )
            )
        return out

    async def add_evidence(
        self,
        project_id: uuid.UUID,
        cid: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> ConditionEvidence:
        c = await self._owned_condition(project_id, cid, actor_id, can_manage)
        kind = data["kind"]
        if kind not in EVIDENCE_KINDS:
            raise PermitError("evidence_kind_invalid", 422)
        guards.condition_add_evidence(c)
        ref = str(data.get("ref_id") or "").strip()
        content_hash = ""
        if kind in LINKED_EVIDENCE:
            # A link that names nothing proves nothing: the reference is mandatory and must be
            # a record of this project.
            if not ref:
                raise PermitError("evidence_ref_required", 422)
            rid = _uuid(ref)
        if kind in ("cde_revision", "inspection", "commissioning_item"):
            await self._check_link(kind, rid, project_id)
            if kind == "cde_revision":
                from app.modules.cde.models import DocumentRevision

                rev = await self.session.get(DocumentRevision, rid)
                content_hash = (rev.content_hash or "") if rev else ""
        elif kind == "discharge_decision":
            dec = await self.repo.get_decision(project_id, rid)
            if dec is None:
                raise not_found("decision_not_found")
            content_hash = dec.content_hash
        elif not ref and not (data.get("note") or "").strip():
            raise PermitError("evidence_empty", 422)
        row = await self.repo.add(
            ConditionEvidence(
                project_id=project_id,
                condition_id=cid,
                kind=kind,
                ref_id=ref,
                content_hash=content_hash,
                note=data.get("note") or "",
                added_by=actor_id,
            )
        )
        await self._audit(actor_id, "permit_condition", cid, "evidence_added", metadata={"kind": kind, "ref": ref})
        return row

    async def remove_evidence(
        self, project_id: uuid.UUID, cid: uuid.UUID, eid: uuid.UUID, *, actor_id: uuid.UUID, can_manage: bool
    ) -> None:
        c = await self._owned_condition(project_id, cid, actor_id, can_manage)
        guards.condition_remove_evidence(c)
        ev = await self.repo.get_evidence(project_id, eid)
        if ev is None or ev.condition_id != cid:
            raise not_found("evidence_not_found")
        await self.session.delete(ev)
        await self.session.flush()
        if c.status == "evidence_submitted" and not await self.repo.list_evidence(project_id, cid):
            await self._fsm(CONDITION_FSM, c, "open", actor_id, "evidence withdrawn")
            c.evidence_submitted_by = None
        await self._audit(actor_id, "permit_condition", cid, "evidence_removed", metadata={"evidence_id": str(eid)})

    async def submit_evidence(
        self, project_id: uuid.UUID, cid: uuid.UUID, *, actor_id: uuid.UUID, can_manage: bool
    ) -> PermitCondition:
        c = await self._owned_condition(project_id, cid, actor_id, can_manage)
        guards.condition_submit_evidence(c, len(await self.repo.list_evidence(project_id, cid)))
        await self._fsm(CONDITION_FSM, c, "evidence_submitted", actor_id, "evidence submitted")
        # Who certified the evidence: this person can never verify the discharge (rule 13).
        c.evidence_submitted_by = actor_id
        await self.session.flush()
        return c

    async def _involved(self, c: PermitCondition) -> set[uuid.UUID]:
        """Everyone who cannot be the second pair of eyes: the owner, the submitter, whoever added evidence."""
        people = {c.owner_user_id, c.evidence_submitted_by}
        people |= {e.added_by for e in await self.repo.list_evidence(c.project_id, c.id)}
        return {p for p in people if p is not None}

    async def discharge_capability(
        self, project_id: uuid.UUID, cid: uuid.UUID, *, actor_id: uuid.UUID, can_verify: bool
    ) -> dict[str, Any]:
        """``can`` flags for the three manual discharge modes, from the very checks that enforce them."""
        c = await self.repo.get_condition(project_id, cid)
        if c is None:
            raise not_found("condition_not_found")
        return self._discharge_can(c, guards.Caller(actor_id, verify=can_verify), await self._involved(c))

    def _discharge_can(self, c: PermitCondition, caller: guards.Caller, involved: set[uuid.UUID]) -> dict[str, Any]:
        # A document can still be attached: only what a document cannot cure is a reason.
        return {
            mode: guards.flag(
                lambda: guards.needs_verify(caller),
                lambda mode=mode: guards.condition_discharge(c, mode, caller.actor_id, involved, has_document=True),
            )
            for mode in guards.DISCHARGE_MODES
        }

    async def _discharge_target(self, c: PermitCondition, mode: str, actor_id: uuid.UUID, *, has_document: bool) -> str:
        """Every rule of a manual discharge; returns the condition state it leads to."""
        return guards.condition_discharge(c, mode, actor_id, await self._involved(c), has_document=has_document)

    async def _evidence_snapshot(self, c: PermitCondition) -> list[dict[str, Any]]:
        return [
            {"id": str(e.id), "kind": e.kind, "ref_id": e.ref_id, "content_hash": e.content_hash}
            for e in await self.repo.list_evidence(c.project_id, c.id)
        ]

    async def discharge(
        self,
        project_id: uuid.UUID,
        cid: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        today: date | None = None,
    ) -> ConditionDischarge:
        """Rule 13 and lead decision j: a manual discharge is always four-eyes.

        The verifier is never the owner, the person who submitted the evidence, or anyone who
        added a piece of it. ``decided_by`` records who certified (the submitter), the verifier
        who confirmed.
        """
        today = today or _today()
        _not_in_future(data.get("on_date"), today)
        c = await self.repo.get_condition(project_id, cid, lock=True)
        if c is None:
            raise not_found("condition_not_found")
        mode = data["mode"]
        when = data.get("on_date") or today
        doc = _uuid(data.get("document_revision_id"))
        target = await self._discharge_target(c, mode, actor_id, has_document=doc is not None)
        await self._check_link("cde_revision", doc, project_id)
        await self._fsm(CONDITION_FSM, c, target, actor_id, mode)
        row = await self.repo.add(
            ConditionDischarge(
                project_id=project_id,
                condition_id=cid,
                mode=mode,
                decided_by=c.evidence_submitted_by if mode == "self_certified" else actor_id,
                verifier_user_id=actor_id,
                discharged_on=when,
                document_revision_id=doc,
                note=data.get("note") or "",
                evidence_snapshot=await self._evidence_snapshot(c),
            )
        )
        await self._audit(actor_id, "permit_condition", cid, "condition_discharged", metadata={"mode": mode})
        self._publish("condition.discharged", {"project_id": str(project_id), "condition_id": str(cid), "mode": mode})
        self._readiness_changed(project_id)
        return row

    async def ongoing(
        self,
        project_id: uuid.UUID,
        cid: uuid.UUID,
        target: str,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool,
    ) -> PermitCondition:
        """Rule 16: an ongoing condition is in compliance or in breach; a breach never closes itself."""
        c = await self._owned_condition(project_id, cid, actor_id, can_manage) if target != "breach" else None
        if c is None:
            c = await self.repo.get_condition(project_id, cid, lock=True)
            if c is None:
                raise not_found("condition_not_found")
        guards.condition_ongoing(c, target)
        if target == "breach":
            kind = data.get("ref_kind") or "manual"
            if kind not in BREACH_REF_KINDS:
                raise PermitError("breach_ref_invalid", 422)
            if kind != "manual":
                # A breach that points at a record names the record.
                if _uuid(data.get("ref_id")) is None:
                    raise PermitError("breach_ref_required", 422)
                await self._check_link(kind, data.get("ref_id"), project_id)
            c.breach_ref_kind, c.breach_ref_id = kind, _uuid(data.get("ref_id"))
            c.breach_note = data.get("note") or ""
        await self._fsm(CONDITION_FSM, c, target, actor_id, data.get("note"))
        await self.session.flush()
        await self._audit(actor_id, "permit_condition", cid, f"condition_{target}", metadata=_jsonable(data))
        self._readiness_changed(project_id)
        if target == "breach":
            self._publish("condition.breach", {"project_id": str(project_id), "condition_id": str(cid)})
            await self._notify(
                c.owner_user_id, "condition_breach", "permit_condition", cid, {"project_id": str(project_id)}
            )
        return c

    async def propose_conditions(
        self,
        project_id: uuid.UUID,
        pid: uuid.UUID,
        proposals: list[dict[str, Any]],
        *,
        actor_id: uuid.UUID,
    ) -> list[PermitCondition]:
        """Rule 15: AI-extracted proposals, stored unconfirmed; they count nowhere until a human confirms."""
        permit = await self.repo.get_permit(project_id, pid)
        if permit is None:
            raise not_found("permit_not_found")
        out = []
        for p in proposals:
            if p.get("confidence") is None:
                raise PermitError("proposal_needs_confidence", 422)
            # A passage is a quotation checked against the notice, which only the extraction can
            # do (``extract_conditions``): one that merely arrives in a request is not stored.
            out.append(
                await self._add_condition(
                    permit,
                    {**p, "passage": ""},
                    decision_id=permit.decision_id,
                    actor_id=actor_id,
                    source="ai_extracted",
                    confirmed=False,
                )
            )
        await self._audit(actor_id, "authority_permit", pid, "conditions_proposed", metadata={"count": len(out)})
        return out

    async def confirm_proposal(
        self, project_id: uuid.UUID, cid: uuid.UUID, accept: bool, *, actor_id: uuid.UUID
    ) -> PermitCondition | None:
        c = await self.repo.get_condition(project_id, cid, lock=True)
        if c is None:
            raise not_found("condition_not_found")
        guards.condition_confirm(c)
        if not accept:
            await self.session.delete(c)
            await self.session.flush()
            await self._audit(actor_id, "permit_condition", cid, "proposal_rejected")
            return None
        c.confirmed = True
        await self.session.flush()
        await self._audit(actor_id, "permit_condition", cid, "proposal_confirmed")
        self._publish("condition.created", {"project_id": str(project_id), "condition_id": str(cid)})
        self._readiness_changed(project_id)
        return c

    async def condition_to_requirement(
        self, project_id: uuid.UUID, cid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> dict[str, Any]:
        """Rule 23: a measurable limit becomes a ``requirements`` row; the condition keeps a soft link."""
        from app.modules.requirements.models import RequirementSet
        from app.modules.requirements.schemas import RequirementCreate, RequirementSetCreate
        from app.modules.requirements.service import RequirementsService

        c = await self.repo.get_condition(project_id, cid, lock=True)
        if c is None:
            raise not_found("condition_not_found")
        guards.condition_link_requirement(c)
        permit = await self.repo.get_permit(project_id, c.permit_id)
        phase = {"before_occupation": "handover", "after_completion": "operation"}.get(c.trigger, "construction")
        try:
            payload = RequirementCreate(
                entity=data["entity"],
                attribute=data["attribute"],
                constraint_type=data.get("constraint_type") or "equals",
                constraint_value=str(data.get("constraint_value") or ""),
                unit=data.get("unit") or "",
                source_ref=f"{permit.reference or permit.permit_type_code} / {c.number}"[:500],
                originator_role="authority",
                phase=phase,
            )
        except ValidationError as exc:
            # The other module's schema is the authority on its own fields: its refusal is a 422 here.
            fields = ",".join(sorted({str(e["loc"][0]) for e in exc.errors() if e.get("loc")}))
            raise PermitError("requirement_input_invalid", 422, detail=fields) from exc
        svc = RequirementsService(self.session)
        set_name = "Permit conditions"
        existing = (
            (
                await self.session.execute(
                    select(RequirementSet).where(
                        RequirementSet.project_id == project_id, RequirementSet.name == set_name
                    )
                )
            )
            .scalars()
            .first()
        )
        rset = existing or await svc.create_set(
            RequirementSetCreate(project_id=project_id, name=set_name, source_type="manual"), user_id=str(actor_id)
        )
        req = await svc.add_requirement(rset.id, payload, user_id=str(actor_id))
        c.requirement_id = req.id
        await self.session.flush()
        await self._audit(
            actor_id, "permit_condition", cid, "requirement_created", metadata={"requirement": str(req.id)}
        )
        return {"condition_id": str(cid), "requirement_id": str(req.id), "requirement_set_id": str(rset.id)}

    # ── readiness (rules 11, 12, 19, 20) ───────────────────────────────────

    async def views(self, project_id: uuid.UUID, today: date) -> dict[str, Any]:
        """Pure-function inputs built once from the rows."""
        roadmap = await self.repo.get_roadmap(project_id)
        types = await self._types(roadmap) if roadmap else {}
        snap = await self.state_snapshot(project_id)
        tl = {r["requirement_id"]: r for r in (await self.timeline(project_id, today))["items"]} if roadmap else {}
        reqs = []
        for r in snap["requirements"]:
            t = types.get(r.permit_type_code)
            row = tl.get(str(r.id), {})
            reqs.append(
                cnd.ReqView(
                    str(r.id),
                    r.permit_type_code,
                    t.category if t else "other",
                    t.scope if t else "full",
                    tuple(t.enables) if t else (),
                    snap["states"].get(str(r.id), "not_started"),
                    r.applicable,
                    bool(row.get("schedule_conflict")),
                    r.conflict_accepted,
                    str(r.id) in snap["conditions_pending"],
                    r.title,
                    _filed(snap["latest"].get(str(r.id))),
                    r.needed_by_date,
                )
            )
        permits_rows = await self.repo.list_permits(project_id)
        decisions = {str(d.id): d for d in snap["decisions"].values()}
        permits = []
        for p in permits_rows:
            t = types.get(p.permit_type_code)
            dec = decisions.get(str(p.decision_id))
            permits.append(
                cnd.PermitView(
                    str(p.id),
                    str(p.requirement_id),
                    p.permit_type_code,
                    t.category if t else "other",
                    p.scope,
                    p.status,
                    tuple(t.enables) if t else (),
                    tuple(dec.scope_activity_ids) if dec else (),
                    tuple(r.code for r in t.requires) if t else (),
                )
            )
        conds = [_cond_view(c) for c in await self.repo.list_conditions(project_id)]
        return {"roadmap": roadmap, "reqs": reqs, "permits": permits, "conds": conds, "snap": snap}

    async def readiness(
        self, project_id: uuid.UUID, gate: str, today: date, *, enables: Any = None, needed_from: date | None = None
    ) -> dict[str, Any]:
        """One readiness check: ``start`` | ``handover`` | ``register`` | ``roadmap``.

        ``needed_from`` (start check only) is the date the check is made for, the target date of
        the governance gate being read: a permit the roadmap needs only after it is a warning,
        not a blocker (``conditions.start_readiness``). Left out, it is the target date of the
        project's gate into construction (:meth:`start_needed_from`), so this screen and the
        gate say the same; where no such gate carries a date every missing permit blocks.

        ``enables`` (roadmap check only) is what the next phase needs a permit for; the caller
        resolves it from the governance catalogue's phase tags. Left out, the check asks for
        what the start of construction needs.
        """
        if gate not in ("start", "handover", "register", "roadmap"):
            raise PermitError("gate_invalid", 422)
        v = await self.views(project_id, today)
        if v["roadmap"] is None:
            return {"gate": gate, "status": "no_roadmap", "items": []}
        if gate == "start":
            if needed_from is None:
                needed_from = await self.start_needed_from(project_id, today)
            out = cnd.start_readiness(v["reqs"], v["permits"], v["conds"], needed_from).as_dict()
            out["needed_from"] = needed_from.isoformat() if needed_from else None
            needing = {
                str(r.needed_by_activity_id): str(r.id) for r in v["snap"]["requirements"] if r.needed_by_activity_id
            }
            scopes = {p.requirement_id: p.scope_activity_ids for p in v["permits"] if p.scope == "partial"}
            for p in v["permits"]:
                if p.scope == "partial":
                    for a in p.scope_activity_ids:
                        needing.setdefault(a, p.requirement_id)
            out["activities"] = cnd.blocked_activities(needing, scopes, v["snap"]["states"])
            return out
        if gate == "handover":
            return cnd.handover_readiness(v["reqs"], v["permits"], v["conds"]).as_dict()
        if gate == "register":
            return cnd.register_readiness(v["reqs"], v["conds"]).as_dict()
        return cnd.roadmap_readiness(v["reqs"], hst.DEFAULT_ENABLES if enables is None else enables).as_dict()

    async def start_needed_from(self, project_id: uuid.UUID, today: date) -> date | None:
        """The day the start of construction is planned for: the gate into it, read through the port.

        The earliest target date among the gates into a phase that enables the start of
        construction, never earlier than ``today``. ``None`` when the project has no such gate
        or none of them carries a date.
        """
        from app.modules.project_governance import public

        phases = set(await public.phases_enabling(self.session, project_id, "construction_start"))
        if not phases:
            return None
        gates = await public.project_gates(self.session, project_id)
        planned = [g.target_date for g in gates if g.to_phase in phases and g.target_date is not None]
        return max(min(planned), today) if planned else None

    async def readiness_for_phase(self, project_id: uuid.UUID, phase_code: str, today: date) -> dict[str, Any]:
        """The roadmap check for the gate into one governance phase, by that phase's catalogue tags."""
        roadmap = await self.repo.get_roadmap(project_id)
        hosting = await self.hosting(project_id, roadmap)
        if phase_code not in hosting.phases:
            raise PermitError("phase_unknown", 422, detail=phase_code)
        out = await self.readiness(project_id, "roadmap", today, enables=hosting.enables(phase_code))
        out["phase"] = phase_code
        out["checks"] = list(hosting.gates(phase_code))
        return out

    # ── overdue and lapse sweep (rules 9, 17) ──────────────────────────────

    async def sweep_targets(self, project_id: uuid.UUID, today: date) -> dict[str, list[uuid.UUID]]:
        """What the overdue and lapse sweep has to look at in one project. Reads only."""
        conditions = [
            c.id
            for c in await self.repo.list_conditions(project_id)
            if cnd.is_overdue(_cond_view(c), today) and (c.overdue_notified_at is None or c.escalated_at is None)
        ]
        permits = [p.id for p in await self.repo.list_permits(project_id) if _lapse_reason(p, today)]
        return {"conditions": conditions, "permits": permits}

    async def sweep_condition(self, project_id: uuid.UUID, cid: uuid.UUID, today: date) -> dict[str, bool]:
        """Rule 17 for one condition: tell the owner and the project lead, then escalate to the area owner.

        ``escalated_at`` is set only when somebody was actually told. A condition whose area has
        no owner yet (or whose governance model does not say which area hosts permits) stays due
        for escalation and is picked up by a later sweep.
        """
        from app.modules.project_governance import public
        from app.modules.projects.models import Project

        out = {"notified": False, "escalated": False, "unescalated": False}
        c = await self.repo.get_condition(project_id, cid, lock=True)
        if c is None or not cnd.is_overdue(_cond_view(c), today):
            return out
        roadmap = await self.require_roadmap(project_id)
        now = datetime.now(UTC)
        ctx = {"project_id": str(project_id), "number": c.number, "due_date": _iso(c.due_date)}
        if c.overdue_notified_at is None:
            project = await self.session.get(Project, project_id)
            c.overdue_notified_at = now
            for uid in {c.owner_user_id, getattr(project, "owner_id", None)} - {None}:
                await self._notify(uid, "condition_overdue", "permit_condition", c.id, ctx)
            self._publish("condition.overdue", {"project_id": str(project_id), "condition_id": str(c.id)})
            out["notified"] = True
        if c.escalated_at is None and cnd.escalation_due(c.due_date, today, roadmap.escalation_days):
            # HSE topics escalate to the area hosting the condition register, the rest to the roadmap's.
            hosting = await self.hosting(project_id, roadmap)
            hse = cnd.hse_relevant(c.topic, c.hse_override)
            area_code = hosting.conditions_area if hse else hosting.roadmap_area
            areas = await public.project_areas(self.session, project_id) if area_code else ()
            area = next((a for a in areas if a.code == area_code), None)
            if area is not None and area.owner_user_id:
                await self._notify(area.owner_user_id, "condition_escalated", "permit_condition", c.id, ctx)
                c.escalated_at = now
                out["escalated"] = True
            else:
                out["unescalated"] = True
        await self.session.flush()
        return out

    async def sweep_permit(self, project_id: uuid.UUID, pid: uuid.UUID, today: date, actor_id: Any = None) -> bool:
        """Rule 9 for one permit: past its lapse date with work not started, or interrupted too long."""
        p = await self.repo.get_permit(project_id, pid, lock=True)
        reason = _lapse_reason(p, today) if p is not None else None
        if reason is None:
            return False
        await self._fsm(PERMIT_FSM, p, "lapsed", actor_id, reason)
        await self.session.flush()
        self._publish("permit.state_changed", {"project_id": str(project_id), "permit_id": str(pid), "state": "lapsed"})
        self._readiness_changed(project_id)
        return True

    async def escalate(
        self, project_id: uuid.UUID, *, actor_id: uuid.UUID | None, today: date | None = None
    ) -> dict[str, Any]:
        """The sweep of one project on demand, in the caller's transaction (the scheduled job runs per item)."""
        today = today or _today()
        await self.require_roadmap(project_id)
        targets = await self.sweep_targets(project_id, today)
        notified, escalated, unescalated, lapsed = [], [], [], []
        for cid in targets["conditions"]:
            done = await self.sweep_condition(project_id, cid, today)
            for name, bucket in (("notified", notified), ("escalated", escalated), ("unescalated", unescalated)):
                if done[name]:
                    bucket.append(str(cid))
        for pid in targets["permits"]:
            if await self.sweep_permit(project_id, pid, today, actor_id):
                lapsed.append(str(pid))
        return {"notified": notified, "escalated": escalated, "unescalated": unescalated, "lapsed": lapsed}

    # ── what the caller may do (``can`` flags) ─────────────────────────────
    #
    # Every flag is the guard of the write run dry (see ``guards``): ``{allowed, applies, reason}``
    # with the error code the write would answer with. What only the request body can decide
    # (a date in the future, a missing document) is not in a flag.

    async def roadmap_can(self, project_id: uuid.UUID, caller: guards.Caller) -> dict[str, Any]:
        doc = await self._roadmap_document(project_id)
        # Once the frame document is binding each structural change spends one approved change request.
        binding = {"change_request_required": doc is not None and doc.status == "binding"}
        manage = guards.flag(lambda: guards.needs_manage(caller))
        return {
            "edit": manage,
            "add_requirement": {**manage, **binding},
            "accept_proposals": {**manage, **binding},
            "escalate": manage,
            "publish_frame_document": guards.flag(
                lambda: guards.needs_manage(caller), lambda: guards.frame_document(doc)
            ),
        }

    def requirement_can(
        self, req: PermitRequirement, applications: list[PermitApplication], caller: guards.Caller, binding: bool
    ) -> dict[str, Any]:
        cr = {"change_request_required": binding}
        manage = guards.flag(lambda: guards.needs_manage(caller))
        edit = guards.flag(lambda: guards.needs_edit(caller))
        return {
            "edit": guards.flag(
                lambda: guards.needs_edit(caller),
                lambda: guards.requirement_edit(req, caller.actor_id, caller.manage),
            ),
            # ``applicable``, ``conflict_accepted`` and the responsible user.
            "manage_fields": manage,
            "delete": {
                **guards.flag(lambda: guards.needs_manage(caller), lambda: guards.requirement_delete(applications)),
                **cr,
            },
            "set_dependencies": {**manage, **cr},
            "create_application": edit,
            "push_milestone": edit,
        }

    async def application_can(
        self, app: PermitApplication, roadmap: PermitRoadmap, caller: guards.Caller, *, deep: bool = False
    ) -> dict[str, Any]:
        """Flags of one application.

        ``deep`` also asks what only a query can answer (unmet dependencies, the internal
        release) for the move to ``submitted``; a list leaves that to the detail read.
        """
        transition = {
            t: guards.flag(
                lambda: guards.needs_edit(caller),
                lambda t=t: guards.application_transition(app, t, roadmap.internal_review),
            )
            for t in guards.TARGET_ORDER
        }
        if deep and transition["submitted"]["allowed"]:
            try:
                await self._admit_submit(roadmap, app, caller.manage)
            except PermitError as exc:
                transition["submitted"] = guards.refused(exc.code)
        return {
            "edit": guards.flag(lambda: guards.needs_edit(caller), lambda: guards.application_edit(app)),
            "clock": guards.flag(lambda: guards.needs_edit(caller), lambda: guards.application_clock(app)),
            "decide": guards.flag(lambda: guards.needs_manage(caller), lambda: guards.application_decide(app)),
            "transition": transition,
        }

    def decision_can(
        self, decision: PermitDecision, newest: PermitDecision | None, caller: guards.Caller
    ) -> dict[str, Any]:
        return {
            "correct": guards.flag(
                lambda: guards.needs_manage(caller), lambda: guards.decision_current(decision, newest)
            ),
            "complete_register": guards.flag(
                lambda: guards.needs_manage(caller), lambda: guards.decision_complete_register(decision, newest)
            ),
        }

    async def permit_can(
        self, permit: Permit, caller: guards.Caller, no_provider: PermitError | None
    ) -> dict[str, Any]:
        """Flags of one permit. ``no_provider`` is the refusal of :meth:`_ai_refusal` for this caller."""

        def edit() -> None:
            guards.needs_edit(caller)

        def manage() -> None:
            guards.needs_manage(caller)

        return {
            "start": guards.flag(edit, lambda: guards.permit_start(permit)),
            "interrupt": guards.flag(edit, lambda: guards.permit_interruption(permit, False)),
            "resume": guards.flag(edit, lambda: guards.permit_interruption(permit, True)),
            "transition": {
                t: guards.flag(manage, lambda t=t: guards.permit_transition(permit, t)) for t in guards.PERMIT_TARGETS
            },
            "add_condition": guards.flag(manage),
            "propose_conditions": await self._can_propose(permit, caller, no_provider),
        }

    def condition_can(
        self, c: PermitCondition, caller: guards.Caller, evidence_count: int, involved: set[uuid.UUID]
    ) -> dict[str, Any]:
        """Flags of one condition. ``involved``: its owner, who submitted and who added evidence."""

        def edit() -> None:
            guards.needs_edit(caller)

        def manage() -> None:
            guards.needs_manage(caller)

        def owned() -> None:
            guards.condition_owned(c, caller.actor_id, caller.manage)

        return {
            "edit": guards.flag(edit, owned, lambda: guards.condition_edit(c)),
            # ``kind``, ``trigger``, ``purpose``, ``requires_authority_approval``: what a gate reads.
            "manage_fields": guards.flag(manage, lambda: guards.condition_gate_fields(c)),
            "assign": guards.flag(manage, lambda: guards.condition_assign(c)),
            "add_evidence": guards.flag(edit, owned, lambda: guards.condition_add_evidence(c)),
            "remove_evidence": guards.flag(edit, owned, lambda: guards.condition_remove_evidence(c)),
            "submit_evidence": guards.flag(edit, owned, lambda: guards.condition_submit_evidence(c, evidence_count)),
            "breach": guards.flag(edit, lambda: guards.condition_ongoing(c, "breach")),
            "in_compliance": guards.flag(edit, owned, lambda: guards.condition_ongoing(c, "in_compliance")),
            "confirm": guards.flag(edit, lambda: guards.condition_confirm(c)),
            "link_requirement": guards.flag(edit, lambda: guards.condition_link_requirement(c)),
            "discharge": self._discharge_can(c, caller, involved),
        }

    # ── condition proposals read out of the notice (rule 15) ───────────────

    async def _extraction_source(self, permit: Permit) -> Any:
        """The CDE revision of the decision notice the permit was issued with."""
        from app.modules.cde.models import DocumentRevision

        decision = await self.repo.get_decision(permit.project_id, permit.decision_id) if permit.decision_id else None
        revision_id = decision.document_revision_id if decision is not None else None
        if revision_id is None:
            raise conflict("permit_has_no_document")
        revision = await self.session.get(DocumentRevision, revision_id)
        if revision is None or not revision.storage_key:
            raise PermitError("document_unreadable", 422)
        return revision

    async def _ai_provider(self, actor_id: uuid.UUID | None) -> tuple[str, str, str | None]:
        """The caller's configured AI provider, from the platform's own AI settings. No second client."""
        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository

        settings = await AISettingsRepository(self.session).get_by_user_id(actor_id) if actor_id else None
        try:
            return resolve_provider_key_model(settings)
        except ValueError as exc:
            raise conflict("ai_not_configured") from exc

    async def _ai_refusal(self, actor_id: uuid.UUID | None) -> PermitError | None:
        try:
            await self._ai_provider(actor_id)
        except PermitError as exc:
            return exc
        return None

    async def _can_propose(
        self, permit: Permit, caller: guards.Caller, no_provider: PermitError | None
    ) -> dict[str, Any]:
        """The extraction's own preconditions, in the order the extraction checks them."""
        try:
            guards.needs_edit(caller)
            await self._extraction_source(permit)
            if no_provider is not None:
                raise no_provider
        except PermitError as exc:
            return guards.refused(exc.code)
        return guards.flag()

    async def extract_conditions(self, project_id: uuid.UUID, pid: uuid.UUID, *, actor_id: uuid.UUID) -> dict[str, Any]:
        """Read the permit's decision notice and store the conditions the AI finds as UNCONFIRMED proposals.

        Nothing extracted counts anywhere until a person confirms it (rule 15). A condition the
        permit already carries, by text or by number, is not proposed again, so running the
        extraction twice adds nothing.
        """
        import asyncio

        import httpx

        from app.core.storage import get_storage_backend
        from app.modules.ai import ai_client
        from app.modules.file_search.extractors import extract_text
        from app.modules.permits import extraction

        permit = await self.repo.get_permit(project_id, pid)
        if permit is None:
            raise not_found("permit_not_found")
        revision = await self._extraction_source(permit)
        provider, api_key, model = await self._ai_provider(actor_id)
        try:
            payload = await get_storage_backend().get(revision.storage_key)
        except FileNotFoundError as exc:
            raise PermitError("document_unreadable", 422) from exc
        document = (await asyncio.to_thread(extract_text, payload, revision.mime_type)).text
        if not document.strip():
            # A scan without a text layer, or a file type nothing here can read.
            raise PermitError("document_has_no_text", 422)
        prompt, cut = extraction.build_prompt(document)
        try:
            answer, _tokens = await ai_client.call_ai(
                provider, api_key, extraction.system_prompt(), prompt, model=model, max_tokens=8000
            )
        except (ValueError, httpx.HTTPError) as exc:
            logger.warning("permits: condition extraction failed at the AI provider for permit %s: %s", pid, exc)
            raise PermitError("ai_request_failed", 502) from exc
        parsed = extraction.parse_response(ai_client.extract_json(answer), document)
        if parsed is None:
            raise PermitError("ai_response_unreadable", 502)
        existing = [c for c in await self.repo.conditions_of_permit(project_id, pid) if c.status != "superseded"]
        known_texts = {c.text_hash for c in existing}
        known_numbers = {c.number for c in existing}
        rows: list[PermitCondition] = []
        already_known = 0
        for p in parsed.proposals:
            if cnd.text_hash(p["text"]) in known_texts or p["number"].strip() in known_numbers:
                already_known += 1
                continue
            rows.append(
                await self._add_condition(
                    permit, p, decision_id=permit.decision_id, actor_id=actor_id, source="ai_extracted", confirmed=False
                )
            )
            known_numbers.add(p["number"].strip())
        await self._audit(
            actor_id,
            "authority_permit",
            pid,
            "conditions_extracted",
            metadata={
                "document_revision_id": str(revision.id),
                "proposed": len(rows),
                "already_known": already_known,
                "rejected": parsed.rejected,
            },
        )
        return {"items": rows, "already_known": already_known, "rejected": parsed.rejected, "document_cut": cut}

    async def evidence_rows(self, project_id: uuid.UUID, cid: uuid.UUID) -> list[dict[str, Any]]:
        """Evidence of one condition; a linked document revision carries its document title and revision label."""
        from app.modules.cde.models import DocumentContainer, DocumentRevision

        rows = await self.repo.list_evidence(project_id, cid)
        ids = [rid for e in rows if e.kind == "cde_revision" and (rid := _uuid_or_none(e.ref_id)) is not None]
        named: dict[str, tuple[str, str]] = {}
        if ids:
            stmt = (
                select(DocumentRevision.id, DocumentContainer.title, DocumentRevision.revision_code)
                .join(DocumentContainer, DocumentRevision.container_id == DocumentContainer.id)
                .where(DocumentRevision.id.in_(ids), DocumentContainer.project_id == project_id)
            )
            named = {str(i): (title or "", code or "") for i, title, code in (await self.session.execute(stmt)).all()}
        out = []
        for e in rows:
            title, label = named.get(str(_uuid_or_none(e.ref_id)), ("", ""))
            out.append({**evidence_out(e), "ref_title": title or None, "ref_revision": label or None})
        return out

    # ── read models ────────────────────────────────────────────────────────

    async def condition_rows(
        self, project_id: uuid.UUID, today: date, caller: guards.Caller | None = None
    ) -> list[dict[str, Any]]:
        """The condition register; with a ``caller`` every row says what that caller may do to it."""
        permits = {str(p.id): p for p in await self.repo.list_permits(project_id)}
        evidence: dict[str, int] = {}
        added: dict[str, set[uuid.UUID]] = {}
        for e in await self.repo.list_evidence(project_id):
            evidence[str(e.condition_id)] = evidence.get(str(e.condition_id), 0) + 1
            if e.added_by is not None:
                added.setdefault(str(e.condition_id), set()).add(e.added_by)
        out = []
        for c in await self.repo.list_conditions(project_id):
            v = _cond_view(c)
            p = permits.get(str(c.permit_id))
            out.append(
                {
                    **condition_out(c),
                    "permit_reference": p.reference if p else "",
                    "permit_type_code": p.permit_type_code if p else "",
                    "overdue": cnd.is_overdue(v, today),
                    "breach_risk": cnd.breach_risk(v, today),
                    "evidence_count": evidence.get(str(c.id), 0),
                }
            )
            if caller is not None:
                involved = {u for u in (c.owner_user_id, c.evidence_submitted_by) if u is not None}
                involved |= added.get(str(c.id), set())
                out[-1]["can"] = self.condition_can(c, caller, evidence.get(str(c.id), 0), involved)
        return out

    async def permit_rows(
        self, project_id: uuid.UUID, today: date, caller: guards.Caller | None = None
    ) -> list[dict[str, Any]]:
        out = []
        # Whether an AI provider is configured is one question per caller, not one per permit.
        no_provider = await self._ai_refusal(caller.actor_id) if caller is not None else None
        for p in await self.repo.list_permits(project_id):
            d = permit_out(p)
            d["lapse_warning"] = cnd.lapse_warning(p.valid_until, today) if p.status in ("in_force", "lapsed") else None
            if caller is not None:
                d["can"] = await self.permit_can(p, caller, no_provider)
            out.append(d)
        return out

    async def register_rows(self, project_id: uuid.UUID, register: str, today: date) -> list[dict[str, Any]]:
        """Rows of one exported register: ``roadmap`` | ``permits`` | ``conditions``."""
        if register == "roadmap":
            rows = (await self.timeline(project_id, today))["items"]
            reqs = {str(r.id): r for r in await self.repo.list_requirements(project_id)}
            for row in rows:
                r = reqs.get(row["requirement_id"])
                row["permit_type_code"] = r.permit_type_code if r else ""
                row["title"] = r.title if r else ""
                row["applicant_role"] = r.applicant_role if r else ""
            return rows
        if register == "permits":
            return await self.permit_rows(project_id, today)
        if register == "conditions":
            return [r for r in await self.condition_rows(project_id, today) if r["confirmed"]]
        raise PermitError("register_invalid", 422)

    async def publish_frame_document(
        self, project_id: uuid.UUID, register: str, *, actor_id: uuid.UUID, locale: str = "en"
    ) -> dict[str, Any]:
        """Rule 18: store the export of a register as a new CDE revision of the governance frame document.

        Which frame document that is, the governance model says (the document hosting
        permits); this module names none. The revision lands in the container that
        document already has, with the hash of the very bytes stored, so the gate binds
        what was exported and a change request can propose it.
        """
        from app.core.storage import get_storage_backend
        from app.modules.cde.schemas import RevisionCreate
        from app.modules.cde.service import CDEService
        from app.modules.permits.export import render

        if register not in REGISTERS:
            raise PermitError("register_invalid", 422)
        project = await self._project(project_id)
        await self.require_roadmap(project_id)
        doc = await self._roadmap_document(project_id)
        guards.frame_document(doc)
        doc_type = doc.code
        await self._check_link("cde_container", doc.container_id, project_id)
        today = _today()
        content = render(
            register,
            await self.register_rows(project_id, register, today),
            project_name=getattr(project, "name", "") or "",
            locale=locale,
            as_of=today.isoformat(),
            fmt="pdf",
        )
        digest = hashlib.sha256(content).hexdigest()
        key = f"permits/{project_id}/frame/{doc_type}/{digest}.pdf"
        await get_storage_backend().put(key, content)
        revision = await CDEService(self.session).create_revision(
            doc.container_id,
            RevisionCreate(
                file_name=f"{doc_type}_{today.isoformat()}.pdf",
                file_size=str(len(content)),
                mime_type="application/pdf",
                storage_key=key,
                content_hash=digest,
                change_summary=f"Permits register export ({register}) as of {today.isoformat()}",
            ),
            user_id=str(actor_id),
        )
        await self._audit(
            actor_id,
            "permit_roadmap",
            doc.id,
            "frame_document_published",
            metadata={"doc_type": doc_type, "revision_id": str(revision.id), "content_hash": digest},
        )
        return {
            "doc_type": doc_type,
            "register": register,
            "governance_document_id": str(doc.id),
            "container_id": str(doc.container_id),
            "revision_id": str(revision.id),
            "content_hash": digest,
        }

    async def validation_payload(self, project_id: uuid.UUID, today: date) -> dict[str, Any]:
        roadmap = await self.repo.get_roadmap(project_id)
        tl = (await self.timeline(project_id, today))["items"] if roadmap else []
        catalogue = (await self.catalogue_for(roadmap)).model_dump(mode="json") if roadmap else None
        snap = await self.state_snapshot(project_id)
        apps = [application_out(a) for a in snap["applications"]]
        decisions = [decision_out(d) for d in snap["decisions"].values()]
        return {
            "today": today.isoformat(),
            "catalogue": catalogue,
            "requirements": [
                {**requirement_out(r), "state": snap["states"].get(str(r.id))} for r in snap["requirements"]
            ],
            "edges": [e.__dict__ for e in snap["edges"]],
            "timeline": tl,
            "applications": apps,
            "decisions": decisions,
            "permits": await self.permit_rows(project_id, today),
            "conditions": await self.condition_rows(project_id, today),
            "discharges": [discharge_out(d) for d in await self.repo.list_discharges(project_id)],
        }


# ── helpers ─────────────────────────────────────────────────────────────────


def _topo(nodes: list[str], edges: list[rm.Edge]) -> list[str]:
    deps: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        if e.requirement in deps:
            deps[e.requirement].append(e.depends_on)
    out: list[str] = []
    seen: set[str] = set()

    def visit(n: str) -> None:
        if n in seen or n not in deps:
            return
        seen.add(n)
        for m in deps[n]:
            visit(m)
        out.append(n)

    for n in nodes:
        visit(n)
    return out


def _current_decisions(decisions: list[PermitDecision]) -> dict[str, PermitDecision]:
    """Per application, the newest revision (a correction supersedes)."""
    out: dict[str, PermitDecision] = {}
    for d in decisions:
        k = str(d.application_id)
        if k not in out or d.revision > out[k].revision:
            out[k] = d
    return out


def _project_jurisdiction(project: Any) -> str:
    """ISO 3166-2 when the project records a subdivision of its own country, else the country (decision i)."""
    country = (getattr(project, "country_code", None) or "").strip().upper()
    sub = (getattr(project, "subdivision_code", None) or "").strip().upper()
    return sub if country and sub.startswith(f"{country}-") else country


def _filed(app: PermitApplication | None) -> bool:
    """The application is with the authority: filed and not yet decided or withdrawn."""
    return app is not None and app.status in DECIDABLE


def _is_early(app: PermitApplication, ptype: PermitType) -> bool:
    return app.kind == "early_start" or ptype.scope == "early_start"


def _check_early_start_purposes(ptype: PermitType | None, conditions: list[tuple[Any, Any]]) -> None:
    """Rule 10: an early start carries an obligation to restore, and to give security where the type allows one."""
    purposes = {purpose for kind, purpose in conditions if kind == "obligation"}
    needed = {"restoration", "security"} if ptype is not None and ptype.security_possible else {"restoration"}
    if not needed <= purposes:
        raise PermitError("early_start_needs_restoration_and_security", 422, detail=",".join(sorted(needed)))


def _check_security(amount: Any, currency: Any) -> None:
    """Money is an amount with its currency, both or neither."""
    has_amount = amount not in (None, "")
    if has_amount != bool((currency or "").strip()):
        raise PermitError("security_needs_amount_and_currency", 422)
    if has_amount:
        value = Decimal(str(amount))
        if not value.is_finite() or value < 0 or value.as_tuple().exponent < -4 or value >= Decimal(10) ** 14:
            raise PermitError("security_amount_invalid", 422)


def _lapse_reason(p: Permit, today: date) -> str | None:
    """Why an in-force permit has lapsed by ``today`` (rule 9), or ``None`` while it has not."""
    if p.status != "in_force" or p.valid_until is None or p.valid_until >= today:
        return None
    if p.start_notified_at is None:
        return "not started within validity"
    if p.paused_since is not None:
        return "work interrupted beyond the allowed period"
    return None


def _validate_condition_input(c: dict[str, Any]) -> None:
    if not str(c.get("number") or "").strip():
        raise PermitError("condition_needs_number", 422)
    if not (c.get("text") or "").strip():
        raise PermitError("condition_needs_text", 422)
    if c.get("kind") not in CONDITION_KINDS:
        raise PermitError("condition_kind_invalid", 422)
    trigger = c.get("trigger") or ""
    if trigger and trigger not in CONDITION_TRIGGERS:
        raise PermitError("condition_trigger_invalid", 422)
    if trigger == "before_stage" and not (c.get("stage_ref") or "").strip():
        raise PermitError("stage_trigger_needs_stage", 422)
    if trigger == "by_date" and not c.get("due_date"):
        raise PermitError("date_trigger_needs_due_date", 422)
    if trigger == "on_event" and not (c.get("event_text") or "").strip():
        raise PermitError("event_trigger_needs_text", 422)
    if (c.get("topic") or "other") not in cnd.TOPICS:
        raise PermitError("condition_topic_invalid", 422)
    if (c.get("purpose") or "") not in ("", "restoration", "security"):
        raise PermitError("condition_purpose_invalid", 422)


def _cond_view(c: PermitCondition) -> cnd.CondView:
    return cnd.CondView(
        str(c.id),
        c.number,
        str(c.permit_id),
        c.kind,
        c.trigger,
        c.status,
        _s(c.owner_user_id),
        c.confirmed,
        c.due_date,
        c.topic,
        _s(c.gate_condition_id),
        c.purpose,
    )


def _condition_payload(c: PermitCondition) -> dict[str, Any]:
    return {
        "number": c.number,
        "text": c.text,
        "kind": c.kind,
        "national_kind": c.national_kind,
        "trigger": c.trigger,
        "stage_ref": c.stage_ref,
        "event_text": c.event_text,
        "due_date": c.due_date,
        "topic": c.topic,
        "purpose": c.purpose,
        "owner_user_id": c.owner_user_id,
        "responsible_party": c.responsible_party,
        "requires_authority_approval": c.requires_authority_approval,
        "evidence_required": c.evidence_required,
    }


def _jsonable(data: Any) -> Any:
    return json.loads(json.dumps(data, default=str)) if data is not None else None


def requirement_out(r: PermitRequirement) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "project_id": str(r.project_id),
        "permit_type_code": r.permit_type_code,
        "title": r.title,
        "applicable": r.applicable,
        "applicability_rationale": r.applicability_rationale,
        "applicant_role": r.applicant_role,
        "applicant_source": r.applicant_source,
        "applicant_rationale": r.applicant_rationale,
        "applicant_party": r.applicant_party,
        "applicant_contact_id": _s(r.applicant_contact_id),
        "responsible_user_id": _s(r.responsible_user_id),
        "planned_submit_date": _iso(r.planned_submit_date),
        "needed_by_activity_id": _s(r.needed_by_activity_id),
        "needed_by_date": _iso(r.needed_by_date),
        "clock_variant": r.clock_variant,
        "expected_decision_date": _iso(r.expected_decision_date),
        "schedule_activity_id": _s(r.schedule_activity_id),
        "governance_area_code": r.governance_area_code,
        "conflict_accepted": r.conflict_accepted,
        "follow_up_of_id": _s(r.follow_up_of_id),
        "proposed_from_route": r.proposed_from_route,
        "sort_order": r.sort_order,
    }


def application_out(a: PermitApplication) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "requirement_id": str(a.requirement_id),
        "attempt": a.attempt,
        "kind": a.kind,
        "parent_permit_id": _s(a.parent_permit_id),
        "discharges_condition_ids": list(a.discharges_condition_ids or []),
        "applicant_role": a.applicant_role or None,
        "applicant_source": a.applicant_source or None,
        "authority_name": a.authority_name,
        "authority_reference": a.authority_reference,
        "submitted_at": _iso(a.submitted_at),
        "received_at": _iso(a.received_at),
        "validated_at": _iso(a.validated_at),
        "review_cycle_ids": list(a.review_cycle_ids or []),
        "submission_id": _s(a.submission_id),
        "cde_container_id": _s(a.cde_container_id),
        "approval_instance_id": _s(a.approval_instance_id),
        "state": a.status,
        "appeal_note": a.appeal_note,
    }


def clock_event_out(e: ClockEventRow) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "application_id": str(e.application_id),
        "kind": e.kind,
        "at": _iso(e.event_date),
        "period": e.period,
        "unit": e.unit,
        "reason": e.reason,
    }


def decision_out(d: PermitDecision) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "application_id": str(d.application_id),
        "revision": d.revision,
        "supersedes_id": _s(d.supersedes_id),
        "outcome": d.outcome,
        "decision_date": _iso(d.decision_date),
        "served_date": _iso(d.served_date),
        "reference": d.reference,
        "scope_note": d.scope_note,
        "scope_activity_ids": list(d.scope_activity_ids or []),
        "conditions_pending": d.conditions_pending,
        "appeal_deadline": _iso(d.appeal_deadline),
        "document_revision_id": _s(d.document_revision_id),
        "content_hash": d.content_hash,
        "deemed": d.deemed,
        "decided_by": _s(d.decided_by),
    }


def permit_out(p: Permit) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "requirement_id": str(p.requirement_id),
        "application_id": str(p.application_id),
        "decision_id": str(p.decision_id),
        "permit_type_code": p.permit_type_code,
        "scope": p.scope,
        "state": p.status,
        "reference": p.reference,
        "revocable": p.revocable,
        "security_amount": None if p.security_amount is None else str(p.security_amount),
        "security_currency": p.security_currency,
        "start_notified_at": _iso(p.start_notified_at),
        "paused_since": _iso(p.paused_since),
        "valid_until": _iso(p.valid_until),
        "superseded_by_id": _s(p.superseded_by_id),
    }


def condition_out(c: PermitCondition) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "permit_id": str(c.permit_id),
        "number": c.number,
        "text": c.text,
        "kind": c.kind,
        "national_kind": c.national_kind,
        "trigger": c.trigger,
        "stage_ref": c.stage_ref,
        "event_text": c.event_text,
        "due_date": _iso(c.due_date),
        "topic": c.topic,
        "purpose": c.purpose,
        "owner_user_id": _s(c.owner_user_id),
        "evidence_submitted_by": _s(c.evidence_submitted_by),
        "responsible_party": c.responsible_party,
        "requires_authority_approval": c.requires_authority_approval,
        "evidence_required": c.evidence_required,
        "requirement_id": _s(c.requirement_id),
        "hse_relevant": cnd.hse_relevant(c.topic, c.hse_override),
        "state": c.status,
        "source": c.source,
        "confidence": None if c.confidence is None else str(c.confidence),
        "text_span": c.text_span,
        "passage": c.source_passage,
        "confirmed": c.confirmed,
        "gate_condition_id": _s(c.gate_condition_id),
        "original_id": _s(c.original_id),
        "breach_ref_kind": c.breach_ref_kind,
        "breach_ref_id": _s(c.breach_ref_id),
        "breach_note": c.breach_note,
    }


def evidence_out(e: ConditionEvidence) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "condition_id": str(e.condition_id),
        "kind": e.kind,
        "ref_id": e.ref_id,
        "content_hash": e.content_hash,
        "note": e.note,
        "added_by": _s(e.added_by),
        "added_at": e.created_at.isoformat() if e.created_at else None,
    }


def discharge_out(d: ConditionDischarge) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "condition_id": str(d.condition_id),
        "mode": d.mode,
        "decided_by": _s(d.decided_by),
        "discharge_application_id": _s(d.discharge_application_id),
        "verifier_user_id": _s(d.verifier_user_id),
        "date": _iso(d.discharged_on),
        "document_revision_id": _s(d.document_revision_id),
        "note": d.note,
        "evidence_snapshot": d.evidence_snapshot,
        "carried_from_id": _s(d.carried_from_id),
    }


def roadmap_out(r: PermitRoadmap) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "project_id": str(r.project_id),
        "catalogue_source": r.catalogue_source,
        "catalogue_id": r.catalogue_id,
        "catalogue_version": r.catalogue_version,
        "jurisdiction": r.jurisdiction,
        "route_assessment_id": _s(r.route_assessment_id),
        "delivery_model_id": _s(r.delivery_model_id),
        "governance_document_id": _s(r.governance_document_id),
        "state": r.status,
        "roadmap_area_code": r.roadmap_area_code,
        "conditions_area_code": r.conditions_area_code,
        "internal_review": r.internal_review,
        "approval_route_id": _s(r.approval_route_id),
        "escalation_days": r.escalation_days,
        "buffer_days": r.buffer_days,
        "consumed_change_request_ids": list(r.consumed_change_request_ids or []),
    }
