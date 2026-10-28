# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Stakeholders service: register, assessments, plan, events, commitments, roles, bodies, mandates.

Every write runs in the caller's transaction with its audit entry
(``log_activity``, or the FSM's own entry for a state change) and its events
(``publish_after_commit``). The pure rules live in ``analysis``,
``recurrence`` and ``mandates``; this class feeds them rows and enforces
what has to hold at write time.

Links into other modules are checked on write and answer 404 when the row is
missing or belongs to another project or tenant (rule 22): contacts through
``contacts.lookup.assignable_contact`` (tenant scoped), roster entries,
meetings, correspondence, risks and CDE containers by ``project_id``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.core.i18n import get_locale
from app.modules.stakeholders import analysis as an
from app.modules.stakeholders import mandates as md
from app.modules.stakeholders import recurrence as rc
from app.modules.stakeholders.authority import authority_evaluator, release_item_checker
from app.modules.stakeholders.catalogue import (
    DEFAULT_FRAMEWORK_ID,
    FRAMEWORK_KIND,
    StakeholderFramework,
    default_framework_pin,
    register_kind,
)
from app.modules.stakeholders.errors import StakeholderError, conflict, forbidden, not_found
from app.modules.stakeholders.fsm import (
    COMMITMENT_FSM,
    COMMITMENT_OPEN,
    COMMITMENT_STATES,
    EVENT_FSM,
    MANDATE_TARGETS,
    PLAN_FSM,
)
from app.modules.stakeholders.messages import translate
from app.modules.stakeholders.models import (
    CommunicationPlanItem,
    EngagementEvent,
    GovernanceBody,
    GovernanceBodyMember,
    Mandate,
    ProjectRole,
    Stakeholder,
    StakeholderAssessment,
    StakeholderCommitment,
    StakeholderSettings,
)
from app.modules.stakeholders.repository import StakeholderRepository

logger = logging.getLogger(__name__)

MODULE = "stakeholders"
TARGET_KIND = "stakeholder_commitment"
COMMITMENT_DECISION = "stakeholder_commitment"
# Frozen once a commitment leaves ``proposed``: the decider agreed to exactly these.
COMMITMENT_FROZEN = frozenset({"text", "cost_estimate", "currency"})
# The risk module's own category for an obligation towards third parties that was not met.
BREACH_RISK_CATEGORY = "regulatory"
COMMITMENT_CATEGORIES: tuple[str, ...] = (
    "noise",
    "traffic",
    "working_hours",
    "information",
    "compensation",
    "design_change",
    "access",
    "environment",
    "other",
)
SOURCE_KINDS: tuple[str, ...] = ("event", "meeting", "correspondence", "permit_condition", "manual")
STAKEHOLDER_STATUSES: tuple[str, ...] = ("active", "dormant", "archived")
TRIGGER_KINDS: tuple[str, ...] = ("gate", "event")
# Event names a plan item with ``trigger_kind: event`` may listen to (subscribed in ``events``).
EVENT_TRIGGERS: tuple[str, ...] = (
    "project_governance.gate.decided",
    "project_governance.phase.changed",
    "stakeholders.commitment.fulfilled",
)
# The listened events the governance module publishes. A project run without gates has no gate to decide
# and no phase to change, so none of them can ever fire there. Derived, so a new governance event joins by
# being listed above.
GATE_BOUND_EVENT_TRIGGERS: tuple[str, ...] = tuple(n for n in EVENT_TRIGGERS if n.startswith("project_governance."))


def trigger_needs_gates(kind: str | None, ref: str | None) -> bool:
    """Whether a plan trigger can only fire on a project that uses gates."""
    return kind == "gate" or (kind == "event" and ref in GATE_BOUND_EVENT_TRIGGERS)


QUORUM_KINDS: tuple[str, ...] = ("min_members", "majority", "unanimous")
LIVE_PLAN: tuple[str, ...] = ("planned", "active")
_OVERDUE_OPEN: tuple[str, ...] = ("proposed", "agreed", "in_progress")


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, float) or isinstance(value, bool):
        raise StakeholderError("invalid_amount")
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise StakeholderError("invalid_amount") from exc
    if not out.is_finite() or out < 0:
        raise StakeholderError("invalid_amount")
    exponent = out.as_tuple().exponent
    if (isinstance(exponent, int) and exponent < -4) or out >= Decimal(10) ** 14:
        # The column is Numeric(18, 4); anything wider is a 500 on PostgreSQL, so it is refused here.
        raise StakeholderError("invalid_amount")
    return out


def commitment_actions(
    *,
    status: str,
    pending: bool,
    has_owner_and_due: bool,
    is_owner: bool,
    can_edit: bool,
    routed: bool,
    flags: list[str],
    is_decider: bool,
) -> dict[str, dict[str, Any]]:
    """The ``can`` block of one commitment: ``{applies, allowed, reason}`` per action.

    ``applies`` is false when the action does not exist in this state (the
    screen hides it). It is true with ``allowed`` false and a reason when the
    caller lacks a right or a precondition that can be met (the screen shows it
    disabled with the reason). The reasons are the error codes the write
    itself would answer.
    """

    def verdict(reason: str | None) -> dict[str, Any]:
        return {"applies": reason != "invalid_transition", "allowed": reason is None, "reason": reason}

    def move(target: str) -> str | None:
        if not can_edit:
            return "no_permission"
        if pending:
            return "approval_pending"
        if not COMMITMENT_FSM.has_transition(status, target):
            return "invalid_transition"
        if target == "agreed" and not has_owner_and_due:
            return "owner_and_due_required"
        if target == "verified" and is_owner:
            return "owner_cannot_verify"
        if target in MANDATE_TARGETS:
            if "mandate_missing" in flags:
                return "mandate_missing"
            if routed:
                return None
            if "body_inquorate" in flags:
                return "body_inquorate"
            if not is_decider:
                return "not_decider"
        return None

    out = {target: verdict(move(target)) for target in COMMITMENT_STATES if target != "proposed"}
    # A closed commitment takes no edit at all (the write answers the same), so the action does not apply.
    closed = COMMITMENT_FSM.is_terminal(status)
    out["edit"] = verdict(
        "invalid_transition" if closed else "no_permission" if not can_edit else "approval_pending" if pending else None
    )
    return out


class StakeholderService:
    """Orchestrates the stakeholder register and the project organisation of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StakeholderRepository(session)
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
        publish_after_commit(self.session, f"{MODULE}.{name}", an.jsonable(data), source_module=MODULE)

    async def _fsm(
        self, fsm: Any, row: Any, target: str, actor_id: Any, reason: str | None = None, **meta: Any
    ) -> None:
        try:
            await fsm.apply(
                self.session,
                row,
                target,
                actor_id=_s(actor_id),
                reason=reason,
                extra_metadata=an.jsonable({"project_id": row.project_id, **meta}),
                entity_type=fsm.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _notify(self, user_id: Any, kind: str, entity_type: str, entity_id: Any, url: str, ctx: dict) -> None:
        """Best effort, inside a savepoint so a failure never poisons the write."""
        if not user_id:
            return
        try:
            from app.modules.notifications.service import NotificationService

            async with self.session.begin_nested():
                await NotificationService(self.session).create(
                    user_id=user_id,
                    notification_type=f"stakeholders_{kind}",
                    title_key=f"notifications.stakeholders.{kind}.title",
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    body_key=f"notifications.stakeholders.{kind}.body",
                    body_context=an.jsonable(ctx),
                    action_url=url,
                    metadata=an.jsonable(ctx),
                )
        except Exception:
            logger.debug("stakeholders notification %s skipped", kind, exc_info=True)

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    async def is_member(self, project_id: uuid.UUID, user_id: uuid.UUID | None) -> bool:
        """Owner, team member or admin (the same answer module 1 uses for area owners)."""
        if user_id is None:
            return False
        from app.modules.teams.access import is_project_member
        from app.modules.users.models import User

        project = await self._project(project_id)
        if project.owner_id == user_id:
            return True
        user = await self.session.get(User, user_id)
        if user is None:
            return False
        if (user.role or "") == "admin":
            return True
        return await is_project_member(self.session, project_id, user_id)

    async def _require_member(self, project_id: uuid.UUID, user_id: Any) -> uuid.UUID | None:
        uid = _uuid(user_id)
        if user_id not in (None, "") and uid is None:
            raise StakeholderError("user_not_project_member")
        if uid is not None and not await self.is_member(project_id, uid):
            raise StakeholderError("user_not_project_member")
        return uid

    # ── links into other modules (rule 22) ─────────────────────────────────

    async def _contact(self, contact_id: Any, actor_id: Any, *, linked: Any = ()) -> Any:
        """Check that the caller may link this contact.

        ``linked`` are contact ids the record being rewritten already carries.
        A full replace resends them, and the caller need not own a contact a
        colleague linked earlier: keeping a link is not creating one.
        """
        from fastapi import HTTPException

        from app.modules.contacts.lookup import assignable_contact

        cid = _uuid(contact_id)
        if cid is None:
            raise not_found("contact_not_found")
        if cid in {_uuid(x) for x in linked if x}:
            return None
        try:
            return await assignable_contact(self.session, cid, _s(actor_id))
        except HTTPException as exc:
            raise not_found("contact_not_found") from exc

    async def _in_project(self, model: Any, project_id: uuid.UUID, row_id: Any, code: str) -> Any:
        rid = _uuid(row_id)
        row = await self.session.get(model, rid) if rid is not None else None
        if row is None or getattr(row, "project_id", None) != project_id:
            raise not_found(code)
        return row

    async def _meeting(self, project_id: uuid.UUID, meeting_id: Any) -> Any:
        from app.modules.meetings.models import Meeting

        return await self._in_project(Meeting, project_id, meeting_id, "meeting_not_found")

    async def _correspondence(self, project_id: uuid.UUID, cid: Any) -> Any:
        from app.modules.correspondence.models import Correspondence

        return await self._in_project(Correspondence, project_id, cid, "correspondence_not_found")

    async def _risk(self, project_id: uuid.UUID, risk_id: Any) -> Any:
        from app.modules.risk.models import RiskItem

        return await self._in_project(RiskItem, project_id, risk_id, "risk_not_found")

    async def _release_item(self, project_id: uuid.UUID, item_id: Any) -> uuid.UUID:
        """A release item belongs to the commitment release module, so that module says whether it is the project's.

        With no checker registered nobody can say, and an unchecked id is never stored.
        """
        rid = _uuid(item_id)
        checker = release_item_checker()
        if checker is None:
            raise conflict("release_items_unavailable")
        if rid is None or not (await checker(self.session, project_id, rid)).item_valid:
            raise not_found("release_item_not_found")
        return rid

    async def _task(self, project_id: uuid.UUID, task_id: Any) -> Any:
        from app.modules.tasks.models import Task

        return await self._in_project(Task, project_id, task_id, "task_not_found")

    async def _requirement(self, project_id: uuid.UUID, requirement_id: Any) -> uuid.UUID:
        """A requirement belongs to a project through its set."""
        from app.modules.requirements.models import Requirement, RequirementSet

        rid = _uuid(requirement_id)
        found = None
        if rid is not None:
            stmt = (
                select(Requirement.id)
                .join(RequirementSet, RequirementSet.id == Requirement.requirement_set_id)
                .where(Requirement.id == rid, RequirementSet.project_id == project_id)
            )
            found = (await self.session.execute(stmt)).scalar_one_or_none()
        if found is None:
            raise not_found("requirement_not_found")
        return found

    # ── what the pickers offer ─────────────────────────────────────────────

    async def gates(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """The project's gates in order, named for the request locale; empty without a phase model."""
        from app.modules.project_governance.messages import translate as governance_text
        from app.modules.project_governance.public import project_gates

        locale = get_locale() or "en"
        out = []
        for gate in await project_gates(self.session, project_id):
            text = gate.label.get("text") or {}
            key = gate.label.get("key")
            name = text.get(locale) or text.get("en") or (governance_text(key, locale=locale) if key else "")
            if name == key:
                # No translation for this key in the bundle: the code is more honest than a raw key.
                name = ""
            out.append({"code": gate.code, "name": name or gate.code, "status": gate.status})
        return out

    async def requirement_options(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every requirement of the project's requirement sets, for the commitment link picker."""
        from app.modules.requirements.models import Requirement, RequirementSet

        stmt = (
            select(Requirement, RequirementSet.name)
            .join(RequirementSet, RequirementSet.id == Requirement.requirement_set_id)
            .where(RequirementSet.project_id == project_id)
            .order_by(RequirementSet.name, Requirement.entity, Requirement.attribute)
        )
        return [
            {
                "id": str(r.id),
                "set_id": str(r.requirement_set_id),
                "set_name": set_name,
                "entity": r.entity,
                "attribute": r.attribute,
                "constraint_type": r.constraint_type,
                "constraint_value": r.constraint_value,
                "unit": r.unit,
                "status": r.status,
            }
            for r, set_name in (await self.session.execute(stmt)).all()
        ]

    async def release_item_options(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Release items a commitment may link to. ``available`` is false while no module provides them."""
        from app.modules.stakeholders.authority import release_item_lister

        lister = release_item_lister()
        if lister is None:
            return {"items": [], "available": False, "reason": "commitment_release_not_installed"}
        items = await lister(self.session, project_id)
        return {
            "items": [{"id": str(i.id), "code": i.code, "title": i.title} for i in items],
            "available": True,
            "reason": None,
        }

    async def _roster(self, project_id: uuid.UUID, roster_id: Any) -> Any:
        from app.modules.teams.models import RosterMember

        return await self._in_project(RosterMember, project_id, roster_id, "roster_member_not_found")

    async def _container(self, project_id: uuid.UUID, container_id: Any) -> Any:
        from app.modules.cde.models import DocumentContainer

        return await self._in_project(DocumentContainer, project_id, container_id, "container_not_found")

    async def _stakeholder_ids(self, project_id: uuid.UUID, ids: list[Any] | None) -> list[str]:
        out: list[str] = []
        for raw in ids or []:
            row = await self.repo.get_in_project(Stakeholder, project_id, _uuid(raw) or uuid.uuid4())
            if row is None:
                raise not_found("stakeholder_not_found")
            if str(row.id) not in out:
                out.append(str(row.id))
        return out

    # ── settings and framework ─────────────────────────────────────────────

    async def framework(
        self, source: str, fid: str, version: int | None, *, tenant_id: str | None = None, from_pin: bool = False
    ) -> StakeholderFramework:
        """Resolve a framework.

        ``from_pin`` is for a triple the server stored on the project: it keeps
        resolving for every project member and after the framework is retired.
        Anything that came from a request passes the caller's ``tenant_id``
        instead; a foreign tenant framework is then unknown and a retired one
        is refused. With neither, nothing of the tenant source resolves.
        """
        from app.modules.project_governance.catalogue_store import resolve_catalogue
        from app.modules.project_governance.errors import GovernanceError

        try:
            return await resolve_catalogue(
                self.session, source, fid, version, kind=FRAMEWORK_KIND, tenant_id=tenant_id, from_pin=from_pin
            )
        except GovernanceError as exc:
            raise StakeholderError(exc.code, exc.status_code, detail=exc.detail) from exc

    async def get_settings(self, project_id: uuid.UUID) -> StakeholderSettings | None:
        return await self.repo.get_settings(project_id)

    async def require_settings(self, project_id: uuid.UUID, *, lock: bool = False) -> StakeholderSettings:
        settings = await self.repo.get_settings(project_id, lock=lock)
        if settings is None:
            raise not_found("settings_missing")
        return settings

    async def context(self, project_id: uuid.UUID) -> tuple[StakeholderSettings, StakeholderFramework]:
        settings = await self.require_settings(project_id)
        fw = await self.framework(
            settings.framework_source, settings.framework_id, settings.framework_version, from_pin=True
        )
        return settings, fw

    async def put_settings(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID, tenant_id: str | None = None
    ) -> StakeholderSettings:
        """Pin a framework (default by the project's country) and set register options.

        The first pin copies the framework's mandate template into the project
        when the project has no mandate rows yet. A tenant framework is checked
        against the caller's tenant on the EFFECTIVE source and id, so a body
        that inherits ``tenant`` from the stored pin cannot name a foreign one.
        """
        project = await self._project(project_id)
        settings = await self.repo.get_settings(project_id, lock=True)
        source = data.get("framework_source") or (settings.framework_source if settings else "shipped")
        fid = data.get("framework_id") or (settings.framework_id if settings else None)
        version = data.get("framework_version")
        if settings is None and not data.get("framework_id") and not data.get("framework_source"):
            # A first pin that names nothing: the installation's default for this project's country.
            source, fid, version = default_framework_pin(getattr(project, "country_code", None))
        if settings is not None and fid == settings.framework_id and version is None and not data.get("framework_id"):
            version = settings.framework_version
        fid = fid or DEFAULT_FRAMEWORK_ID
        repinned = settings is None or (source, str(fid)) != (settings.framework_source, settings.framework_id)
        # The stored pin keeps resolving as it is. A new id or version came from the request, so it resolves
        # for the caller's tenant only (foreign: unknown_catalogue, retired: catalogue_retired).
        from_request = repinned or data.get("framework_version") is not None
        fw = await self.framework(source, fid, version, tenant_id=tenant_id, from_pin=not from_request)
        method = data.get("analysis_method") or (settings.analysis_method if settings else fw.default_method)
        if fw.method(method) is None:
            raise StakeholderError("unknown_method")
        route_id = data.get("commitment_route_id", settings.commitment_route_id if settings else None)
        if route_id is not None:
            await self._check_route(project_id, route_id)
        # What the resolver takes back: a shipped framework by its id, a tenant one by the uuid of its row.
        # The body of a tenant framework carries its code as ``id``, which resolves nothing.
        pin_id = fw.id if source == "shipped" else str(fid)
        created = settings is None
        if settings is None:
            settings = StakeholderSettings(project_id=project_id, created_by=actor_id, owner_area_code="")
            settings.framework_source, settings.framework_id = source, pin_id
            settings.framework_version, settings.analysis_method = fw.version, method
            try:
                async with self.session.begin_nested():
                    self.session.add(settings)
                    await self.session.flush()
            except IntegrityError as exc:
                # Two first pins at once: the row lock cannot serialise what does not exist yet.
                raise conflict("concurrent_change") from exc
        settings.framework_source = source
        settings.framework_id = pin_id
        settings.framework_version = fw.version
        settings.analysis_method = method
        settings.review_interval_days = int(data.get("review_interval_days") or settings.review_interval_days or 90)
        if "owner_area_code" in data:
            # An explicit override only. Left empty, the hosting area is read from the governance catalogue's tags.
            settings.owner_area_code = (data["owner_area_code"] or "").strip()
        settings.commitment_route_id = _uuid(route_id)
        await self.session.flush()
        if created and not await self.repo.mandates(project_id):
            await self._create_template_bodies(project_id, fw)
            for row in fw.mandate_template:
                self.session.add(
                    Mandate(
                        project_id=project_id,
                        decision_type=row.decision_type,
                        scope="",
                        holder_kind=row.holder_kind,
                        holder_code=row.holder_code,
                        letter=row.letter,
                        limit_ref=self._limit_ref(fw, row.decision_type),
                    )
                )
            await self.session.flush()
        await self._audit(
            actor_id,
            "stakeholder_settings",
            settings.id,
            "pinned" if created else "updated",
            metadata=an.jsonable({"framework": f"{source}:{fw.id}@{fw.version}", "method": method}),
        )
        return settings

    async def _create_template_bodies(self, project_id: uuid.UUID, fw: StakeholderFramework) -> None:
        """Create the governance bodies the mandate template names, empty.

        The template gives decisions to bodies by body type code. Without the
        body the copied matrix could not be saved back (its holder would be
        unknown) and the decision would have a decider that does not exist.
        """
        existing = {b.code for b in await self.repo.bodies(project_id)}
        types = {b.code: b for b in fw.body_types}
        for code in dict.fromkeys(r.holder_code for r in fw.mandate_template if r.holder_kind == "body"):
            body_type = types.get(code)
            if body_type is None or code in existing:
                continue
            name = (body_type.labels or {}).get(get_locale() or "en") or (
                translate(body_type.name_key, locale=get_locale() or "en") if body_type.name_key else code
            )
            self.session.add(
                GovernanceBody(
                    project_id=project_id,
                    code=code,
                    body_type=code,
                    name=name[:255],
                    decision_level=body_type.default_decision_level,
                )
            )
        await self.session.flush()

    async def host_area_code(
        self, project_id: uuid.UUID, settings: StakeholderSettings | None = None, *, subject: str = "stakeholders"
    ) -> str | None:
        """The area that hosts a subject of this module: the project's override, else the phase model's tag."""
        from app.modules.stakeholders import hosting

        settings = settings or await self.repo.get_settings(project_id)
        if settings is not None and settings.owner_area_code:
            return settings.owner_area_code
        catalogue = await hosting.project_catalogue(self.session, project_id)
        found = hosting.host(catalogue, subject) if catalogue is not None else None
        return found.area_code if found is not None else None

    async def _check_route(self, project_id: uuid.UUID, route_id: Any) -> None:
        from app.modules.approval_routes.models import Route

        route = await self.session.get(Route, _uuid(route_id)) if _uuid(route_id) else None
        if route is None or route.target_kind != TARGET_KIND or route.project_id not in (None, project_id):
            raise not_found("no_commitment_route")

    @staticmethod
    def _limit_ref(fw: StakeholderFramework, decision_type: str) -> dict[str, Any] | None:
        dt = fw.decision_type(decision_type)
        if dt is None or not dt.commitment_type:
            return None
        return {"authority_schedule": "pinned", "commitment_type": dt.commitment_type}

    # ── stakeholders ───────────────────────────────────────────────────────

    async def get_stakeholder(self, project_id: uuid.UUID, sid: uuid.UUID, *, lock: bool = False) -> Stakeholder:
        row = await self.repo.get_in_project(Stakeholder, project_id, sid, lock=lock)
        if row is None:
            raise not_found("stakeholder_not_found")
        return row

    async def _stakeholder_fields(
        self,
        project_id: uuid.UUID,
        fw: StakeholderFramework,
        data: dict[str, Any],
        actor_id: Any,
        row: Stakeholder | None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "category" in data:
            if fw.category(data["category"]) is None:
                raise StakeholderError("unknown_category")
            out["category"] = data["category"]
        if data.get("contact_id"):
            await self._contact(data["contact_id"], actor_id, linked=[row.contact_id] if row is not None else ())
            out["contact_id"] = _uuid(data["contact_id"])
        elif "contact_id" in data:
            out["contact_id"] = None
        if data.get("parent_stakeholder_id"):
            parent = await self.get_stakeholder(project_id, _uuid(data["parent_stakeholder_id"]) or uuid.uuid4())
            if row is not None:
                # Walk up from the new parent: reaching this row again would close a loop.
                seen: set[uuid.UUID] = set()
                node: Stakeholder | None = parent
                while node is not None and node.id not in seen:
                    if node.id == row.id:
                        raise StakeholderError("invalid_parent")
                    seen.add(node.id)
                    node = (
                        await self.repo.get_in_project(Stakeholder, project_id, node.parent_stakeholder_id)
                        if node.parent_stakeholder_id
                        else None
                    )
            out["parent_stakeholder_id"] = parent.id
        elif "parent_stakeholder_id" in data:
            out["parent_stakeholder_id"] = None
        for key in ("user_id", "relationship_owner_user_id"):
            if key in data:
                out[key] = await self._require_member(project_id, data[key])
        if data.get("risk_id"):
            out["risk_id"] = (await self._risk(project_id, data["risk_id"])).id
        elif "risk_id" in data:
            out["risk_id"] = None
        for key in ("display_name", "interests", "expectations", "concerns"):
            if key in data and data[key] is not None:
                out[key] = str(data[key]).strip()
        for key in ("is_group", "is_confidential"):
            if key in data and data[key] is not None:
                out[key] = bool(data[key])
        if "group_size_estimate" in data:
            out["group_size_estimate"] = data["group_size_estimate"]
        if "geo" in data:
            out["geo"] = an.jsonable(data["geo"]) if data["geo"] else None
        if "status" in data and data["status"] is not None:
            if data["status"] not in STAKEHOLDER_STATUSES:
                raise StakeholderError("invalid_status")
            out["status"] = data["status"]
        return out

    async def create_stakeholder(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> Stakeholder:
        """Rule 1 (category from the pinned framework) and rule 17 (private persons confidential)."""
        _settings, fw = await self.context(project_id)
        if "category" not in data:
            raise StakeholderError("unknown_category")
        fields = await self._stakeholder_fields(project_id, fw, data, actor_id, None)
        category = fw.category(fields["category"])
        assert category is not None
        if not fields.get("contact_id") and not fields.get("display_name"):
            raise StakeholderError("display_name_required")
        if category.private_person and fields.get("contact_id") and not fields.get("is_group"):
            # The name of a private person lives in contacts only, so erasing the contact erases it here too.
            fields["display_name"] = ""
        if "is_confidential" not in fields:
            # Rule 17 protects a private person. A group ("residents of the north boundary") names nobody.
            fields["is_confidential"] = category.private_person and not fields.get("is_group")
        code = (data.get("code") or "").strip() or await self.repo.next_code(Stakeholder, project_id, "S-")
        if await self.repo.stakeholder_by_code(project_id, code) is not None:
            raise conflict("duplicate_code")
        row = Stakeholder(project_id=project_id, code=code, created_by=actor_id, **fields)
        try:
            async with self.session.begin_nested():
                await self.repo.add(row)
        except IntegrityError as exc:
            raise conflict("duplicate_code") from exc
        await self._audit(actor_id, "stakeholder", row.id, "created", metadata={"code": code, "category": row.category})
        self._publish(
            "stakeholder.created", {"project_id": project_id, "stakeholder_id": row.id, "category": row.category}
        )
        return row

    async def update_stakeholder(
        self, project_id: uuid.UUID, sid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> Stakeholder:
        _settings, fw = await self.context(project_id)
        row = await self.get_stakeholder(project_id, sid, lock=True)
        fields = await self._stakeholder_fields(project_id, fw, data, actor_id, row)
        if "code" in data and data["code"] and data["code"] != row.code:
            if await self.repo.stakeholder_by_code(project_id, data["code"]) is not None:
                raise conflict("duplicate_code")
            fields["code"] = data["code"]
        contact = fields.get("contact_id", row.contact_id)
        if not contact and not fields.get("display_name", row.display_name):
            raise StakeholderError("display_name_required")
        category = fw.category(fields.get("category", row.category))
        if category and category.private_person and contact and not fields.get("is_group", row.is_group):
            # Same rule as create: the name of a private person lives in contacts only.
            fields["display_name"] = ""
        before = {k: _s(getattr(row, k)) for k in fields}
        try:
            async with self.session.begin_nested():
                for k, v in fields.items():
                    setattr(row, k, v)
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict("duplicate_code") from exc
        await self._audit(
            actor_id,
            "stakeholder",
            row.id,
            "updated",
            metadata=an.jsonable({"before": before, "after": {k: _s(v) for k, v in fields.items()}}),
        )
        return row

    async def archive_stakeholder(self, project_id: uuid.UUID, sid: uuid.UUID, *, actor_id: uuid.UUID) -> Stakeholder:
        """DELETE keeps history: the stakeholder is archived, its assessments and commitments stay."""
        row = await self.get_stakeholder(project_id, sid, lock=True)
        if row.status != "archived":
            row.status = "archived"
            await self.session.flush()
            await self._audit(actor_id, "stakeholder", row.id, "archived")
        return row

    async def _contacts(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
        if not ids:
            return {}
        from app.modules.contacts.models import Contact

        rows = (await self.session.execute(select(Contact).where(Contact.id.in_(ids)))).scalars().all()
        return {r.id: r for r in rows}

    @staticmethod
    def _contact_name(contact: Any) -> str:
        from app.modules.contacts.lookup import contact_display_name

        return contact_display_name(contact)

    async def stakeholder_views(
        self, project_id: uuid.UUID, *, can_read_personal: bool, today: date, method: str | None = None
    ) -> list[dict[str, Any]]:
        """Register rows with name resolution, masking (rule 17) and the computed flags (rules 3, 4)."""
        settings, fw = await self.context(project_id)
        method_code = method or settings.analysis_method
        rows = await self.repo.stakeholders(project_id)
        assessments = await self.repo.assessments(project_id)
        views = [self._assessment_view(a) for a in assessments]
        latest_any = an.latest_by_stakeholder(views)
        contacts = await self._contacts({r.contact_id for r in rows if r.contact_id})
        commitments = await self.repo.commitments(project_id)
        open_by: dict[str, int] = {}
        for c in commitments:
            if c.status in COMMITMENT_OPEN:
                for sid in c.stakeholder_ids or []:
                    open_by[sid] = open_by.get(sid, 0) + 1
        out = []
        for r in rows:
            sid = str(r.id)
            current = an.current_classification(views, sid, method_code)
            latest = latest_any.get(sid)
            category = fw.category(r.category)
            external = bool(category and category.kind == "external")
            name = self._resolve_name(r, contacts, can_read_personal)
            out.append(
                {
                    **self.stakeholder_out(r),
                    **name,
                    **(self.masked_fields() if name["masked"] else {}),
                    "classification": current.classification if current else an.NOT_ASSESSED,
                    "method_code": method_code,
                    "engagement_current": latest.engagement_current if latest else None,
                    "engagement_desired": latest.engagement_desired if latest else None,
                    "engagement_gap": an.engagement_gap(
                        fw, latest.engagement_current if latest else None, latest.engagement_desired if latest else None
                    ),
                    "attitude": None,
                    "last_assessed_at": latest.assessed_at.isoformat() if latest else None,
                    "review_due": r.status == "active"
                    and an.review_due(
                        latest_at=latest.assessed_at if latest else None,
                        external=external,
                        interval_days=settings.review_interval_days,
                        today=today,
                    ),
                    "external": external,
                    "open_commitments": open_by.get(sid, 0),
                }
            )
        att = {
            a.stakeholder_id: a.attitude
            for a in sorted(assessments, key=lambda a: _aware(a.assessed_at))
            if a.attitude is not None
        }
        for v in out:
            v["attitude"] = att.get(uuid.UUID(v["id"]))
        return out

    def _resolve_name(
        self, row: Stakeholder, contacts: dict[uuid.UUID, Any], can_read_personal: bool
    ) -> dict[str, Any]:
        anonymised = False
        if row.contact_id:
            contact = contacts.get(row.contact_id)
            name = self._contact_name(contact) if contact is not None else ""
            anonymised = not name
            name = name or None
            if row.display_name and not anonymised:
                name = f"{row.display_name} ({name})" if row.is_group else name
        else:
            name = row.display_name or None
        masked = bool(row.is_confidential and not can_read_personal and not anonymised)
        return {"name": None if masked else name, "masked": masked, "anonymised": anonymised}

    @staticmethod
    def masked_fields() -> dict[str, Any]:
        """What a reader without ``stakeholders.read_personal`` gets in place of the identifying fields (rule 17).

        ``display_name`` holds the name whenever no contact is linked and ``geo``
        is the home address of a private person, so both go with the name.
        """
        return {"display_name": "", "geo": None}

    @staticmethod
    def stakeholder_out(r: Stakeholder) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "project_id": str(r.project_id),
            "code": r.code,
            "display_name": r.display_name,
            "category": r.category,
            "contact_id": _s(r.contact_id),
            "is_group": r.is_group,
            "group_size_estimate": r.group_size_estimate,
            "parent_stakeholder_id": _s(r.parent_stakeholder_id),
            "user_id": _s(r.user_id),
            "interests": r.interests,
            "expectations": r.expectations,
            "concerns": r.concerns,
            "relationship_owner_user_id": _s(r.relationship_owner_user_id),
            "geo": r.geo,
            "is_confidential": r.is_confidential,
            "status": r.status,
            "risk_id": _s(r.risk_id),
        }

    # ── assessments ────────────────────────────────────────────────────────

    @staticmethod
    def _assessment_view(a: StakeholderAssessment) -> an.AssessmentView:
        return an.AssessmentView(
            str(a.stakeholder_id),
            a.method_code,
            a.classification,
            a.engagement_current,
            a.engagement_desired,
            _aware(a.assessed_at) or _now(),
        )

    async def assess(
        self,
        project_id: uuid.UUID,
        sid: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        now: datetime | None = None,
    ) -> StakeholderAssessment:
        """Append one assessment (rule 2: scores validated, classification derived, never accepted)."""
        settings, fw = await self.context(project_id)
        stakeholder = await self.get_stakeholder(project_id, sid)
        code = data.get("method_code") or settings.analysis_method
        method = fw.method(code)
        if method is None:
            raise StakeholderError("unknown_method")
        try:
            scores = an.validate_scores(method, dict(data.get("scores") or {}))
        except an.ScoreError as exc:
            raise StakeholderError(
                "invalid_scores",
                violations=[{"code": c, "dimension": d} for d, c in exc.problems],
            ) from exc
        levels = fw.engagement_order()
        for key in ("engagement_current", "engagement_desired"):
            if data.get(key) is not None and data[key] not in levels:
                raise StakeholderError("unknown_engagement_level")
        attitude = data.get("attitude")
        if attitude is not None and (
            isinstance(attitude, bool) or not isinstance(attitude, int) or not -2 <= attitude <= 2
        ):
            raise StakeholderError("invalid_scores", violations=[{"code": "out_of_range", "dimension": "attitude"}])
        row = StakeholderAssessment(
            project_id=project_id,
            stakeholder_id=stakeholder.id,
            method_code=method.code,
            method_version=method.version,
            scores=an.jsonable(scores),
            classification=an.classify(method, scores),
            engagement_current=data.get("engagement_current"),
            engagement_desired=data.get("engagement_desired"),
            attitude=attitude,
            rationale=(data.get("rationale") or "").strip(),
            assessed_by=actor_id,
            assessed_at=now or _now(),
        )
        await self.repo.add(row)
        stakeholder.review_notified_at = None
        await self.session.flush()
        await self._audit(
            actor_id,
            "stakeholder",
            stakeholder.id,
            "assessed",
            metadata=an.jsonable({"method": method.code, "classification": row.classification, "scores": scores}),
        )
        self._publish(
            "stakeholder.assessed",
            {
                "project_id": project_id,
                "stakeholder_id": stakeholder.id,
                "assessment_id": row.id,
                "classification": row.classification,
            },
        )
        return row

    async def list_assessments(self, project_id: uuid.UUID, sid: uuid.UUID) -> list[StakeholderAssessment]:
        await self.get_stakeholder(project_id, sid)
        return await self.repo.assessments(project_id, sid)

    @staticmethod
    def assessment_out(a: StakeholderAssessment) -> dict[str, Any]:
        return {
            "id": str(a.id),
            "stakeholder_id": str(a.stakeholder_id),
            "method_code": a.method_code,
            "method_version": a.method_version,
            "scores": a.scores,
            "classification": a.classification,
            "engagement_current": a.engagement_current,
            "engagement_desired": a.engagement_desired,
            "attitude": a.attitude,
            "rationale": a.rationale,
            "assessed_by": _s(a.assessed_by),
            "assessed_at": _aware(a.assessed_at).isoformat() if a.assessed_at else None,
        }

    async def grid(
        self, project_id: uuid.UUID, *, method: str | None, can_read_personal: bool, today: date
    ) -> dict[str, Any]:
        """Computed grid positions under one method (rule 3): stakeholders without one are ``not_assessed``."""
        settings, fw = await self.context(project_id)
        code = method or settings.analysis_method
        m = fw.method(code)
        if m is None:
            raise StakeholderError("unknown_method")
        views = await self.stakeholder_views(project_id, can_read_personal=can_read_personal, today=today, method=code)
        latest: dict[str, StakeholderAssessment] = {}
        for a in await self.repo.assessments(project_id):
            if a.method_code == code and str(a.stakeholder_id) not in latest:
                latest[str(a.stakeholder_id)] = a  # repository orders newest first
        items = []
        for v in views:
            if v["status"] == "archived":
                continue
            a = latest.get(v["id"])
            items.append(
                {
                    "stakeholder_id": v["id"],
                    "code": v["code"],
                    "name": v["name"],
                    "masked": v["masked"],
                    "anonymised": v["anonymised"],
                    "category": v["category"],
                    "classification": a.classification if a else an.NOT_ASSESSED,
                    "position": an.grid_position(m, a.scores) if a else None,
                    "scores": a.scores if a else None,
                    "assessment_id": str(a.id) if a else None,
                }
            )
        return {
            "method_code": m.code,
            "method_version": m.version,
            "dimensions": [d.model_dump() for d in m.dimensions],
            "classes": [c.model_dump() for c in m.classes],
            "items": items,
        }

    # ── communication plan ────────────────────────────────────────────────

    async def get_plan_item(
        self, project_id: uuid.UUID, pid: uuid.UUID, *, lock: bool = False
    ) -> CommunicationPlanItem:
        row = await self.repo.get_in_project(CommunicationPlanItem, project_id, pid, lock=lock)
        if row is None:
            raise not_found("plan_item_not_found")
        return row

    async def _plan_fields(
        self, project_id: uuid.UUID, fw: StakeholderFramework, data: dict[str, Any], row: CommunicationPlanItem | None
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "audience_stakeholder_ids" in data:
            out["audience_stakeholder_ids"] = await self._stakeholder_ids(project_id, data["audience_stakeholder_ids"])
        if "audience_categories" in data:
            cats = list(dict.fromkeys(data["audience_categories"] or []))
            if any(fw.category(c) is None for c in cats):
                raise StakeholderError("unknown_category")
            out["audience_categories"] = cats
        if "audience_body_id" in data:
            if data["audience_body_id"]:
                out["audience_body_id"] = (
                    await self.get_body(project_id, _uuid(data["audience_body_id"]) or uuid.uuid4())
                ).id
            else:
                out["audience_body_id"] = None
        if "participation_level" in data and data["participation_level"] is not None:
            if data["participation_level"] not in fw.level_order():
                raise StakeholderError("unknown_participation_level")
            out["participation_level"] = data["participation_level"]
        if "channel" in data and data["channel"] is not None:
            if data["channel"] not in {c.code for c in fw.channels}:
                raise StakeholderError("unknown_channel")
            out["channel"] = data["channel"]
        if "format_code" in data:
            if data["format_code"] and fw.format(data["format_code"]) is None:
                raise StakeholderError("unknown_format")
            out["format_code"] = data["format_code"] or None
        if "frequency" in data:
            try:
                out["frequency"] = rc.normalise(data["frequency"])
            except rc.RecurrenceError as exc:
                raise StakeholderError("invalid_frequency", detail=str(exc)) from exc
        if "trigger_kind" in data:
            if data["trigger_kind"] not in (None, *TRIGGER_KINDS):
                raise StakeholderError("schedule_or_trigger")
            out["trigger_kind"] = data["trigger_kind"]
        if "trigger_ref" in data:
            out["trigger_ref"] = (data["trigger_ref"] or "").strip()
        if "owner_user_id" in data:
            out["owner_user_id"] = await self._require_member(project_id, data["owner_user_id"])
        for key in ("starts_on", "ends_on"):
            if key in data:
                out[key] = _day(data[key])
        for key in ("title", "purpose", "key_message"):
            if key in data and data[key] is not None:
                out[key] = str(data[key]).strip()
        merged = {
            k: out.get(k, getattr(row, k, None) if row is not None else None)
            for k in (
                "audience_stakeholder_ids",
                "audience_categories",
                "audience_body_id",
                "trigger_kind",
                "trigger_ref",
                "starts_on",
                "ends_on",
            )
        }
        if not (merged["audience_stakeholder_ids"] or merged["audience_categories"] or merged["audience_body_id"]):
            raise StakeholderError("audience_required")
        if merged["trigger_kind"] is None and merged["starts_on"] is None:
            raise StakeholderError("schedule_or_trigger")
        if merged["trigger_kind"] == "event" and merged["trigger_ref"] not in EVENT_TRIGGERS:
            raise StakeholderError("schedule_or_trigger")
        if trigger_needs_gates(merged["trigger_kind"], merged["trigger_ref"]) and (
            {"trigger_kind", "trigger_ref"} & set(out)
        ):
            codes = {g["code"] for g in await self.gates(project_id)}
            if not codes:
                # Nothing would ever make such an item due: the project is run without gates.
                raise StakeholderError("gates_not_in_use")
            # For a gate trigger empty means every gate. A named gate must be one of this project's.
            if merged["trigger_kind"] == "gate" and merged["trigger_ref"] and merged["trigger_ref"] not in codes:
                raise StakeholderError("unknown_gate")
        if merged["starts_on"] and merged["ends_on"] and merged["ends_on"] < merged["starts_on"]:
            raise StakeholderError("invalid_validity")
        return out

    async def _done_occurrences(self, item: CommunicationPlanItem) -> list[date]:
        return [
            e.occurrence_date or e.held_on
            for e in await self.repo.plan_events(item.id)
            if e.status == "held" and (e.occurrence_date or e.held_on) is not None
        ]

    async def _recompute_next_due(self, item: CommunicationPlanItem) -> None:
        if item.status not in LIVE_PLAN:
            item.next_due = None
            return
        item.next_due = rc.next_due(
            frequency=item.frequency,
            trigger_kind=item.trigger_kind,
            starts_on=item.starts_on,
            ends_on=item.ends_on,
            done=await self._done_occurrences(item),
            triggered_on=item.triggered_on,
        )

    async def create_plan_item(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> CommunicationPlanItem:
        _settings, fw = await self.context(project_id)
        if data.get("format_code") and not data.get("participation_level"):
            fmt = fw.format(data["format_code"])
            if fmt is not None:
                data = {**data, "participation_level": fmt.default_level}
                if not data.get("channel") and fmt.default_channels:
                    data["channel"] = fmt.default_channels[0]
        for key in ("participation_level", "channel", "title"):
            if not data.get(key):
                raise StakeholderError(
                    {"participation_level": "unknown_participation_level", "channel": "unknown_channel"}.get(
                        key, "title_required"
                    )
                )
        fields = await self._plan_fields(project_id, fw, data, None)
        status = data.get("status") or "planned"
        if status not in LIVE_PLAN:
            raise StakeholderError("invalid_transition")
        row = CommunicationPlanItem(project_id=project_id, created_by=actor_id, status=status, **fields)
        if row.trigger_kind:
            row.frequency = rc.ONCE
        await self.repo.add(row)
        await self._recompute_next_due(row)
        await self.session.flush()
        await self._audit(actor_id, "stakeholder_plan_item", row.id, "created", metadata={"title": row.title})
        return row

    async def update_plan_item(
        self, project_id: uuid.UUID, pid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> CommunicationPlanItem:
        _settings, fw = await self.context(project_id)
        row = await self.get_plan_item(project_id, pid, lock=True)
        fields = await self._plan_fields(project_id, fw, data, row)
        for k, v in fields.items():
            setattr(row, k, v)
        target = data.get("status")
        if target and target != row.status:
            await self._fsm(PLAN_FSM, row, target, actor_id)
        await self._recompute_next_due(row)
        await self.session.flush()
        await self._audit(actor_id, "stakeholder_plan_item", row.id, "updated", metadata=an.jsonable(fields))
        return row

    async def delete_plan_item(self, project_id: uuid.UUID, pid: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        row = await self.get_plan_item(project_id, pid, lock=True)
        await self._audit(actor_id, "stakeholder_plan_item", row.id, "deleted", metadata={"title": row.title})
        await self.repo.delete(row)

    @staticmethod
    def plan_overdue(item: CommunicationPlanItem, today: date) -> bool:
        """Rule 6: due date passed and no occurrence recorded for it (recording advances ``next_due``)."""
        return item.status in LIVE_PLAN and item.next_due is not None and item.next_due < today

    def plan_out(self, r: CommunicationPlanItem, today: date) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "title": r.title,
            "purpose": r.purpose,
            "key_message": r.key_message,
            "audience_stakeholder_ids": list(r.audience_stakeholder_ids or []),
            "audience_categories": list(r.audience_categories or []),
            "audience_body_id": _s(r.audience_body_id),
            "participation_level": r.participation_level,
            "channel": r.channel,
            "format_code": r.format_code,
            "frequency": r.frequency,
            "trigger_kind": r.trigger_kind,
            "trigger_ref": r.trigger_ref,
            "triggered_on": _s(r.triggered_on),
            "owner_user_id": _s(r.owner_user_id),
            "starts_on": _s(r.starts_on),
            "ends_on": _s(r.ends_on),
            "status": r.status,
            "next_due": _s(r.next_due),
            "overdue": self.plan_overdue(r, today),
        }

    async def due(self, project_id: uuid.UUID, *, start: date, end: date, today: date) -> list[dict[str, Any]]:
        """The communication calendar: computed occurrences in ``[start, end]`` plus overdue items."""
        out: list[dict[str, Any]] = []
        for item in await self.repo.plan_items(project_id):
            if item.status not in LIVE_PLAN:
                continue
            done = set(await self._done_occurrences(item))
            dates: list[date] = []
            if item.trigger_kind:
                if item.next_due and start <= item.next_due <= end:
                    dates = [item.next_due]
            elif item.starts_on is not None:
                dates = [
                    d
                    for d in rc.occurrences_between(item.frequency, item.starts_on, start, end)
                    if item.ends_on is None or d <= item.ends_on
                ]
            if self.plan_overdue(item, today) and item.next_due not in dates and item.next_due is not None:
                dates.insert(0, item.next_due)
            for d in dates:
                out.append(
                    {
                        "plan_item_id": str(item.id),
                        "title": item.title,
                        "date": d.isoformat(),
                        "done": d in done,
                        "overdue": d < today and d not in done and item.next_due is not None and d >= item.next_due,
                        "participation_level": item.participation_level,
                        "channel": item.channel,
                        "owner_user_id": _s(item.owner_user_id),
                    }
                )
        out.sort(key=lambda r: (r["date"], r["title"]))
        return out

    # ── engagement events ─────────────────────────────────────────────────

    async def get_event(self, project_id: uuid.UUID, eid: uuid.UUID, *, lock: bool = False) -> EngagementEvent:
        row = await self.repo.get_in_project(EngagementEvent, project_id, eid, lock=lock)
        if row is None or row.deleted_at is not None:
            raise not_found("event_not_found")
        return row

    async def _event_fields(
        self, project_id: uuid.UUID, fw: StakeholderFramework, data: dict[str, Any]
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "participation_level" in data and data["participation_level"] is not None:
            if data["participation_level"] not in fw.level_order():
                raise StakeholderError("unknown_participation_level")
            out["participation_level"] = data["participation_level"]
        if "format_code" in data:
            if data["format_code"] and fw.format(data["format_code"]) is None:
                raise StakeholderError("unknown_format")
            out["format_code"] = data["format_code"] or None
        if "stakeholder_ids" in data:
            out["stakeholder_ids"] = await self._stakeholder_ids(project_id, data["stakeholder_ids"])
        if "meeting_id" in data:
            out["meeting_id"] = (await self._meeting(project_id, data["meeting_id"])).id if data["meeting_id"] else None
        if "correspondence_ids" in data:
            out["correspondence_ids"] = [
                str((await self._correspondence(project_id, c)).id)
                for c in dict.fromkeys(data["correspondence_ids"] or [])
            ]
        if "cde_container_ids" in data:
            out["cde_container_ids"] = [
                str((await self._container(project_id, c)).id) for c in dict.fromkeys(data["cde_container_ids"] or [])
            ]
        for key in ("held_on", "occurrence_date"):
            if key in data:
                out[key] = _day(data[key])
        for key in ("title", "location", "outcome", "feedback_summary"):
            if key in data and data[key] is not None:
                out[key] = str(data[key]).strip()
        if "attendance_count" in data:
            out["attendance_count"] = data["attendance_count"]
        return out

    async def create_event(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> EngagementEvent:
        """An event, ad hoc or against a plan item; a held one advances the item's ``next_due`` (rule 7)."""
        _settings, fw = await self.context(project_id)
        item = None
        if data.get("plan_item_id"):
            item = await self.get_plan_item(project_id, _uuid(data["plan_item_id"]) or uuid.uuid4(), lock=True)
            data = {
                "participation_level": item.participation_level,
                "format_code": item.format_code,
                "title": item.title,
                **{k: v for k, v in data.items() if v is not None},
            }
            if not data.get("occurrence_date"):
                held = _day(data.get("held_on"))
                data["occurrence_date"] = (
                    rc.occurrence_for(
                        frequency=item.frequency,
                        trigger_kind=item.trigger_kind,
                        starts_on=item.starts_on,
                        held_on=held,
                        next_due=item.next_due,
                        done=await self._done_occurrences(item),
                    )
                    if held is not None
                    else item.next_due
                )
        elif data.get("format_code") and not data.get("participation_level"):
            fmt = fw.format(data["format_code"])
            if fmt is not None:
                data = {**data, "participation_level": fmt.default_level}
        if not data.get("title"):
            raise StakeholderError("title_required")
        if not data.get("participation_level"):
            raise StakeholderError("unknown_participation_level")
        status = data.get("status") or ("held" if data.get("held_on") else "planned")
        if status not in ("planned", "held"):
            raise StakeholderError("invalid_transition")
        if status == "held" and not data.get("held_on"):
            raise StakeholderError("held_on_required")
        fields = await self._event_fields(project_id, fw, data)
        row = EngagementEvent(
            project_id=project_id, plan_item_id=item.id if item else None, status=status, created_by=actor_id, **fields
        )
        await self.repo.add(row)
        if item is not None:
            await self._recompute_next_due(item)
            await self.session.flush()
        await self._audit(actor_id, "stakeholder_event", row.id, f"created_{status}", metadata={"title": row.title})
        return row

    async def update_event(
        self, project_id: uuid.UUID, eid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> EngagementEvent:
        _settings, fw = await self.context(project_id)
        row = await self.get_event(project_id, eid, lock=True)
        target = data.get("status")
        fields = await self._event_fields(project_id, fw, {k: v for k, v in data.items() if k != "status"})
        for k, v in fields.items():
            setattr(row, k, v)
        if target and target != row.status:
            if target == "held" and row.held_on is None:
                raise StakeholderError("held_on_required")
            await self._fsm(EVENT_FSM, row, target, actor_id)
        await self.session.flush()
        if row.plan_item_id:
            item = await self.get_plan_item(project_id, row.plan_item_id, lock=True)
            await self._recompute_next_due(item)
            await self.session.flush()
        await self._audit(actor_id, "stakeholder_event", row.id, "updated", metadata=an.jsonable(fields))
        return row

    async def delete_event(self, project_id: uuid.UUID, eid: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        """Soft delete (rule 9): commitments keep their source link and snapshot."""
        row = await self.get_event(project_id, eid, lock=True)
        row.deleted_at = _now()
        await self.session.flush()
        if row.plan_item_id:
            item = await self.get_plan_item(project_id, row.plan_item_id, lock=True)
            await self._recompute_next_due(item)
            await self.session.flush()
        await self._audit(actor_id, "stakeholder_event", row.id, "deleted", metadata={"title": row.title})

    def event_out(self, r: EngagementEvent, fw: StakeholderFramework | None, today: date) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "plan_item_id": _s(r.plan_item_id),
            "occurrence_date": _s(r.occurrence_date),
            "format_code": r.format_code,
            "participation_level": r.participation_level,
            "title": r.title,
            "held_on": _s(r.held_on),
            "location": r.location,
            "stakeholder_ids": list(r.stakeholder_ids or []),
            "attendance_count": r.attendance_count,
            "outcome": r.outcome,
            "feedback_summary": r.feedback_summary,
            "meeting_id": _s(r.meeting_id),
            "correspondence_ids": list(r.correspondence_ids or []),
            "cde_container_ids": list(r.cde_container_ids or []),
            "status": r.status,
            "feedback_not_reported": bool(
                fw
                and an.feedback_not_reported(
                    fw,
                    level=r.participation_level,
                    status=r.status,
                    held_on=r.held_on,
                    feedback_summary=r.feedback_summary,
                    today=today,
                )
            ),
            "feedback_due_on": _s(an.feedback_due_on(r.held_on, fw.feedback_due_days)) if fw and r.held_on else None,
        }

    # ── commitments ───────────────────────────────────────────────────────

    async def get_commitment(
        self, project_id: uuid.UUID, cid: uuid.UUID, *, lock: bool = False
    ) -> StakeholderCommitment:
        row = await self.repo.get_in_project(StakeholderCommitment, project_id, cid, lock=lock)
        if row is None:
            raise not_found("commitment_not_found")
        return row

    async def _source(self, project_id: uuid.UUID, kind: str, ref: Any) -> tuple[str, dict[str, Any]]:
        """Resolve a commitment source and freeze its title and date (rule 9)."""
        if kind not in SOURCE_KINDS:
            raise StakeholderError("invalid_source")
        if kind == "event":
            ev = await self.get_event(project_id, _uuid(ref) or uuid.uuid4())
            return str(ev.id), {"title": ev.title, "date": _s(ev.held_on or ev.occurrence_date)}
        if kind == "meeting":
            m = await self._meeting(project_id, ref)
            return str(m.id), {"title": m.title, "date": (m.meeting_date or "")[:10] or None}
        if kind == "correspondence":
            c = await self._correspondence(project_id, ref)
            day = c.date_received or (c.created_at.date().isoformat() if c.created_at else None)
            return str(c.id), {"title": c.subject, "date": day}
        if kind == "permit_condition":
            text = str(ref or "").strip()
            if not text:
                raise StakeholderError("invalid_source")
            return text[:255], {"title": text[:255], "date": None}
        return "", {"title": "", "date": None}

    async def _commitment_fields(self, project_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "stakeholder_ids" in data:
            ids = await self._stakeholder_ids(project_id, data["stakeholder_ids"])
            if not ids:
                raise StakeholderError("audience_required")
            out["stakeholder_ids"] = ids
        if "category" in data and data["category"] is not None:
            if data["category"] not in COMMITMENT_CATEGORIES:
                raise StakeholderError("invalid_category")
            out["category"] = data["category"]
        if "owner_user_id" in data:
            out["owner_user_id"] = await self._require_member(project_id, data["owner_user_id"])
        if "due_date" in data:
            out["due_date"] = _day(data["due_date"])
        for key in ("text", "verification"):
            if key in data and data[key] is not None:
                out[key] = str(data[key]).strip()
        if "cost_estimate" in data:
            out["cost_estimate"] = _amount(data["cost_estimate"])
        if "currency" in data and data["currency"] is not None:
            currency = str(data["currency"]).strip().upper()
            if len(currency) != 3 or not currency.isalpha():
                raise StakeholderError("currency_required")
            out["currency"] = currency
        if "risk_id" in data:
            out["risk_id"] = (await self._risk(project_id, data["risk_id"])).id if data["risk_id"] else None
        if "task_id" in data:
            out["task_id"] = (await self._task(project_id, data["task_id"])).id if data["task_id"] else None
        if "requirement_id" in data:
            out["requirement_id"] = (
                await self._requirement(project_id, data["requirement_id"]) if data["requirement_id"] else None
            )
        if "release_item_id" in data:
            out["release_item_id"] = (
                await self._release_item(project_id, data["release_item_id"]) if data["release_item_id"] else None
            )
        return out

    async def _project_currency(self, project_id: uuid.UUID) -> str:
        """The currency an amount without one takes; an amount never stays without a currency."""
        project = await self._project(project_id)
        currency = (getattr(project, "currency", "") or "").strip().upper()
        if len(currency) != 3:
            raise StakeholderError("currency_required")
        return currency

    async def create_commitment(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> StakeholderCommitment:
        await self.context(project_id)
        if not (data.get("text") or "").strip():
            raise StakeholderError("text_required")
        if not data.get("stakeholder_ids"):
            raise StakeholderError("audience_required")
        kind = data.get("source_kind") or "manual"
        ref, snapshot = await self._source(project_id, kind, data.get("source_ref"))
        fields = await self._commitment_fields(project_id, data)
        if fields.get("cost_estimate") is not None and not fields.get("currency"):
            fields["currency"] = await self._project_currency(project_id)
        code = await self.repo.next_code(StakeholderCommitment, project_id, "C-")
        row = StakeholderCommitment(
            project_id=project_id,
            code=code,
            source_kind=kind,
            source_ref=ref,
            source_snapshot=an.jsonable(snapshot),
            created_by=actor_id,
            **fields,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(row)
        except IntegrityError as exc:
            raise conflict("concurrent_change") from exc
        await self._audit(
            actor_id, "stakeholder_commitment", row.id, "created", metadata={"code": code, "source": kind}
        )
        return row

    async def update_commitment(
        self,
        project_id: uuid.UUID,
        cid: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool = False,
    ) -> StakeholderCommitment:
        row = await self.get_commitment(project_id, cid, lock=True)
        if COMMITMENT_FSM.is_terminal(row.status):
            raise conflict("invalid_transition")
        if row.pending_target:
            # The approver is looking at this text and this amount; they stay as they are until the verdict.
            raise conflict("approval_pending")
        fields = await self._commitment_fields(project_id, data)
        changed = {k for k, v in fields.items() if getattr(row, k) != v}
        if row.status != "proposed" and changed & COMMITMENT_FROZEN:
            # What was agreed is what the decider saw; a new promise is a new commitment.
            raise conflict("commitment_frozen")
        if row.status != "proposed" and "owner_user_id" in changed and not can_manage:
            # The owner may not verify their own commitment, so who the owner is cannot be moved freely.
            raise forbidden("owner_change_needs_manage")
        amount = fields.get("cost_estimate", row.cost_estimate)
        if amount is not None and not fields.get("currency", row.currency):
            fields["currency"] = await self._project_currency(project_id)
        for k, v in fields.items():
            setattr(row, k, v)
        await self.session.flush()
        await self._audit(actor_id, "stakeholder_commitment", row.id, "updated", metadata=an.jsonable(fields))
        return row

    @staticmethod
    def commitment_overdue(c: StakeholderCommitment, today: date) -> bool:
        """Rule 18 flag: an open commitment past its due date."""
        return c.status in _OVERDUE_OPEN and c.due_date is not None and c.due_date < today

    async def transition_commitment(
        self,
        project_id: uuid.UUID,
        cid: uuid.UUID,
        target: str,
        *,
        actor_id: uuid.UUID,
        rationale: str = "",
        communicated_back_at: datetime | None = None,
        loop_not_required_rationale: str = "",
        create_risk: bool = False,
        today: date,
    ) -> tuple[StakeholderCommitment, list[str]]:
        """Move a commitment. Returns the row and warnings.

        ``agreed`` / ``withdrawn`` are mandate decisions (rule 10): the decider of
        ``stakeholder_commitment`` confirms directly, or, when the framework names
        an approval target kind, an approval instance is started and the
        transition waits for it. ``breached`` needs a rationale and may open a
        risk (rule 18). ``verified`` needs the loop closed (rule 19).
        """
        settings, fw = await self.context(project_id)
        row = await self.get_commitment(project_id, cid, lock=True)
        if row.pending_target and not await self._reconcile_pending(row):
            raise conflict("approval_pending")
        if not COMMITMENT_FSM.has_transition(row.status, target):
            raise conflict("invalid_transition", detail=f"{row.status} -> {target}")
        warnings: list[str] = []
        rationale = (rationale or "").strip()
        if target == "withdrawn" and not rationale:
            raise StakeholderError("rationale_required")
        if target == "agreed":
            if row.owner_user_id is None or row.due_date is None:
                raise StakeholderError("owner_and_due_required")
            warnings += await self._check_release_item(project_id, row)
        if target == "breached":
            if not rationale:
                raise StakeholderError("rationale_required")
            row.breach_rationale = rationale
            if create_risk and row.risk_id is None:
                row.risk_id = await self._open_risk(project_id, row, actor_id)
        if target == "verified":
            if row.owner_user_id is not None and row.owner_user_id == actor_id:
                # Four eyes: whoever keeps the commitment does not confirm that it was kept.
                raise forbidden("owner_cannot_verify")
            loop = (loop_not_required_rationale or "").strip()
            if communicated_back_at is not None:
                row.communicated_back_at = _aware(communicated_back_at)
            if loop:
                row.loop_not_required_rationale = loop
            if row.communicated_back_at is None and not row.loop_not_required_rationale:
                raise StakeholderError("verification_needs_loop_closed")
        if target in MANDATE_TARGETS:
            resolution = await self.who_decides(project_id, COMMITMENT_DECISION, "", today=today)
            if "mandate_missing" in resolution["flags"]:
                raise StakeholderError("mandate_missing")
            dt = fw.decision_type(COMMITMENT_DECISION)
            if dt is not None and dt.approval_target_kind == TARGET_KIND:
                await self._start_commitment_approval(settings, row, target, rationale, actor_id)
                return row, warnings
            if "body_inquorate" in resolution["flags"]:
                # One member cannot speak for a body that could not meet.
                raise conflict("body_inquorate")
            if str(actor_id) not in resolution["user_ids"]:
                raise forbidden("not_decider")
            row.decision_ref = an.jsonable(
                {
                    "mode": "direct",
                    "decision_type": COMMITMENT_DECISION,
                    "holder_kind": resolution["holder_kind"],
                    "holder_code": resolution["holder_code"],
                    "decided_by": actor_id,
                    "decided_at": _now(),
                    "target": target,
                }
            )
        if target == "withdrawn":
            row.withdraw_rationale = rationale
        await self._fsm(COMMITMENT_FSM, row, target, actor_id, reason=rationale or None)
        await self.session.flush()
        self._after_commitment_transition(row, target)
        return row, warnings

    def _after_commitment_transition(self, row: StakeholderCommitment, target: str) -> None:
        if target in ("agreed", "fulfilled", "breached", "withdrawn", "verified"):
            self._publish(
                f"commitment.{target}",
                {
                    "project_id": row.project_id,
                    "commitment_id": row.id,
                    "stakeholder_ids": row.stakeholder_ids,
                    "risk_id": row.risk_id,
                },
            )

    async def _check_release_item(self, project_id: uuid.UUID, row: StakeholderCommitment) -> list[str]:
        """Rule 10: a commitment with a cost needs a module 2 release item when a matrix exists."""
        if row.cost_estimate is None:
            return []
        checker = release_item_checker()
        if checker is None:
            return ["release_item_not_checked"]
        answer = await checker(self.session, project_id, row.release_item_id)
        if not answer.has_matrix:
            return ["no_commitment_matrix"]
        if row.release_item_id is None or not answer.item_valid:
            raise StakeholderError("release_item_required")
        return []

    async def _start_commitment_approval(
        self,
        settings: StakeholderSettings,
        row: StakeholderCommitment,
        target: str,
        rationale: str,
        actor_id: uuid.UUID,
    ) -> None:
        from fastapi import HTTPException

        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        if settings.commitment_route_id is None:
            raise StakeholderError("no_commitment_route")
        try:
            async with self.session.begin_nested():
                instance = await ApprovalRouteService(self.session).start_instance(
                    InstanceCreate(route_id=settings.commitment_route_id, target_kind=TARGET_KIND, target_id=row.id),
                    started_by=actor_id,
                )
        except HTTPException as exc:
            code = "approval_pending" if exc.status_code == 409 else "no_commitment_route"
            raise StakeholderError(code, 409 if code == "approval_pending" else 422) from exc
        row.approval_instance_id = instance.id
        row.pending_target = target
        row.pending_rationale = rationale
        await self.session.flush()
        await self._audit(
            actor_id,
            "stakeholder_commitment",
            row.id,
            "approval_requested",
            metadata=an.jsonable({"target": target, "instance_id": instance.id}),
        )

    async def _reconcile_pending(self, row: StakeholderCommitment) -> bool:
        """Catch up with an approval whose verdict never reached this module.

        The verdict arrives through an event subscriber in its own session. If
        that failed, the commitment would wait for ever. So before answering
        ``approval_pending`` the instance itself is asked: a terminal one is
        applied here and now. Returns whether the wait is over.
        """
        from app.modules.approval_routes.models import Instance

        instance = await self.session.get(Instance, row.approval_instance_id) if row.approval_instance_id else None
        status = getattr(instance, "status", None)
        if instance is None:
            status = "cancelled"
        if status not in ("approved", "rejected", "cancelled"):
            return False
        await self._apply_verdict(row, verdict=status, decided_by=getattr(instance, "decided_by", None))
        return True

    async def apply_route_verdict(self, instance_id: uuid.UUID, *, verdict: str, decided_by: Any) -> bool:
        """Terminal approval verdict: approved applies the pending transition, anything else clears it."""
        row = await self.repo.commitment_by_instance(instance_id)
        if row is None or not row.pending_target:
            return False
        await self._apply_verdict(row, verdict=verdict, decided_by=decided_by)
        return True

    async def _apply_verdict(self, row: StakeholderCommitment, *, verdict: str, decided_by: Any) -> None:
        instance_id = row.approval_instance_id
        target = row.pending_target
        rationale = row.pending_rationale
        row.pending_target = None
        row.pending_rationale = ""
        if verdict != "approved":
            await self._audit(decided_by, "stakeholder_commitment", row.id, f"approval_{verdict}")
            await self.session.flush()
            return
        row.decision_ref = an.jsonable(
            {
                "mode": "approval",
                "decision_type": COMMITMENT_DECISION,
                "approval_instance_id": instance_id,
                "decided_by": _s(decided_by),
                "decided_at": _now(),
                "target": target,
            }
        )
        if target == "withdrawn":
            row.withdraw_rationale = rationale
        await self._fsm(
            COMMITMENT_FSM, row, target, decided_by, reason=rationale or None, approval_instance_id=instance_id
        )
        await self.session.flush()
        self._after_commitment_transition(row, target)

    async def _open_risk(
        self, project_id: uuid.UUID, row: StakeholderCommitment, actor_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Rule 18 option: a confirmed breach opens a risk through the risk service (risk owns the record)."""
        from app.modules.risk.schemas import RiskCreate
        from app.modules.risk.service import RiskService

        risk = await RiskService(self.session).create_risk(
            RiskCreate(
                project_id=project_id,
                title=translate("stakeholders.risk.breach_title", locale=get_locale() or "en", code=row.code)[:255],
                description=f"{row.text}\n\n{row.breach_rationale}"[:5000],
                category=BREACH_RISK_CATEGORY,
                owner_user_id=row.owner_user_id,
            ),
            user_id=_s(actor_id),
        )
        return risk.id

    def commitment_out(self, r: StakeholderCommitment, today: date) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "code": r.code,
            "stakeholder_ids": list(r.stakeholder_ids or []),
            "source_kind": r.source_kind,
            "source_ref": r.source_ref,
            "source_snapshot": r.source_snapshot or {},
            "text": r.text,
            "category": r.category,
            "owner_user_id": _s(r.owner_user_id),
            "due_date": _s(r.due_date),
            "verification": r.verification,
            "cost_estimate": None if r.cost_estimate is None else str(r.cost_estimate),
            "currency": r.currency,
            "release_item_id": _s(r.release_item_id),
            "task_id": _s(r.task_id),
            "risk_id": _s(r.risk_id),
            "requirement_id": _s(r.requirement_id),
            "status": r.status,
            "overdue": self.commitment_overdue(r, today),
            "decision_ref": r.decision_ref or {},
            "approval_instance_id": _s(r.approval_instance_id),
            "pending_target": r.pending_target,
            "withdraw_rationale": r.withdraw_rationale,
            "breach_rationale": r.breach_rationale,
            "communicated_back_at": _aware(r.communicated_back_at).isoformat() if r.communicated_back_at else None,
            "loop_not_required_rationale": r.loop_not_required_rationale,
        }

    async def commitment_can(
        self,
        project_id: uuid.UUID,
        rows: list[StakeholderCommitment],
        *,
        actor_id: uuid.UUID,
        can_edit: bool,
        today: date,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """What the caller may do with each commitment, with the reason when not (same checks as the writes)."""
        _settings, fw = await self.context(project_id)
        resolution = await self.who_decides(project_id, COMMITMENT_DECISION, "", today=today)
        dt = fw.decision_type(COMMITMENT_DECISION)
        routed = dt is not None and dt.approval_target_kind == TARGET_KIND
        return {
            str(r.id): commitment_actions(
                status=r.status,
                pending=bool(r.pending_target),
                has_owner_and_due=r.owner_user_id is not None and r.due_date is not None,
                is_owner=r.owner_user_id is not None and r.owner_user_id == actor_id,
                can_edit=can_edit,
                routed=routed,
                flags=resolution["flags"],
                is_decider=str(actor_id) in resolution["user_ids"],
            )
            for r in rows
        }

    # ── daily sweep (rules 4, 6, 18) ──────────────────────────────────────

    async def sweep(self, project_id: uuid.UUID, *, today: date) -> dict[str, int]:
        """Notify once: review due (per interval), plan overdue (per occurrence), commitment overdue (once)."""
        settings, fw = await self.context(project_id)
        counts = {"review_due": 0, "plan_overdue": 0, "commitment_overdue": 0}
        latest = an.latest_by_stakeholder(self._assessment_view(a) for a in await self.repo.assessments(project_id))
        owners: dict[str, uuid.UUID | None] = {}
        for s in await self.repo.stakeholders(project_id):
            owners[str(s.id)] = s.relationship_owner_user_id
            if s.status != "active":
                continue
            cat = fw.category(s.category)
            last = latest.get(str(s.id))
            if not an.review_due(
                latest_at=last.assessed_at if last else None,
                external=bool(cat and cat.kind == "external"),
                interval_days=settings.review_interval_days,
                today=today,
            ):
                continue
            notified = _aware(s.review_notified_at)
            if notified is not None and (today - notified.date()).days <= settings.review_interval_days:
                continue
            s.review_notified_at = _now()
            counts["review_due"] += 1
            await self._notify(
                s.relationship_owner_user_id,
                "review_due",
                "stakeholder",
                s.id,
                f"/projects/{project_id}/stakeholders?stakeholder={s.id}",
                {"code": s.code},
            )
        for item in await self.repo.plan_items(project_id):
            if not self.plan_overdue(item, today) or item.overdue_notified_for == item.next_due:
                continue
            item.overdue_notified_for = item.next_due
            counts["plan_overdue"] += 1
            await self._notify(
                item.owner_user_id,
                "plan_overdue",
                "stakeholder_plan_item",
                item.id,
                f"/projects/{project_id}/stakeholders/communication?item={item.id}",
                {"title": item.title, "due": item.next_due},
            )
        for c in await self.repo.commitments(project_id):
            if not self.commitment_overdue(c, today) or c.breach_notified_on is not None:
                continue
            c.breach_notified_on = today
            counts["commitment_overdue"] += 1
            ctx = {"code": c.code, "due": c.due_date}
            url = f"/projects/{project_id}/stakeholders/commitments?commitment={c.id}"
            recipients = {c.owner_user_id, *(owners.get(sid) for sid in c.stakeholder_ids or [])}
            for uid in sorted((u for u in recipients if u), key=str):
                await self._notify(uid, "commitment_overdue", "stakeholder_commitment", c.id, url, ctx)
        await self.session.flush()
        return counts

    # ── plan triggers (rule 6) ────────────────────────────────────────────

    async def fire_trigger(self, project_id: uuid.UUID, kind: str, ref: str, *, on: date) -> int:
        """A gate moved to review (``gate``, ref = gate code) or a listened event fired (``event``)."""
        fired = 0
        for item in await self.repo.plan_items(project_id):
            if item.status not in LIVE_PLAN or item.trigger_kind != kind:
                continue
            if item.trigger_ref and item.trigger_ref != ref:
                continue
            item.triggered_on = on
            await self._recompute_next_due(item)
            fired += 1
        await self.session.flush()
        return fired

    # ── roles ─────────────────────────────────────────────────────────────

    async def _holders(self, project_id: uuid.UUID) -> tuple[list[ProjectRole], list[md.Holder], dict[uuid.UUID, Any]]:
        from app.modules.teams.models import RosterMember

        roles = await self.repo.roles(project_id)
        roster_ids = {r.roster_member_id for r in roles if r.roster_member_id} | {
            r.deputy_roster_member_id for r in roles if r.deputy_roster_member_id
        }
        roster: dict[uuid.UUID, Any] = {}
        if roster_ids:
            rows = (await self.session.execute(select(RosterMember).where(RosterMember.id.in_(roster_ids)))).scalars()
            roster = {r.id: r for r in rows}
        holders = []
        for r in roles:
            member = roster.get(r.roster_member_id) if r.roster_member_id else None
            holders.append(
                md.Holder(
                    role_code=r.role_code,
                    user_id=_s(member.user_id) if member is not None and member.user_id else None,
                    contact_id=_s(r.holder_contact_id)
                    or (_s(member.contact_id) if member is not None and member.contact_id else None),
                    roster_member_id=_s(r.roster_member_id),
                    valid_from=r.valid_from,
                    valid_to=r.valid_to,
                    conflict_rationale=r.conflict_rationale or "",
                )
            )
        return roles, holders, roster

    async def _bodies(self, project_id: uuid.UUID) -> tuple[list[GovernanceBody], list[md.Body]]:
        bodies = await self.repo.bodies(project_id)
        members = await self.repo.body_members(project_id)
        by_body: dict[uuid.UUID, list[GovernanceBodyMember]] = {}
        for m in members:
            by_body.setdefault(m.body_id, []).append(m)
        out = [
            md.Body(
                code=b.code,
                quorum_kind=b.quorum_kind,
                quorum_min=b.quorum_min,
                decision_level=b.decision_level,
                members=tuple(
                    md.Member(
                        role_code=m.role_code,
                        user_id=_s(m.user_id),
                        contact_id=_s(m.contact_id),
                        voting=m.voting,
                        valid_from=m.valid_from,
                        valid_to=m.valid_to,
                    )
                    for m in by_body.get(b.id, [])
                ),
            )
            for b in bodies
        ]
        return bodies, out

    @staticmethod
    def _mandate_rows(rows: list[Mandate]) -> list[md.MandateRow]:
        return [md.MandateRow(r.decision_type, r.holder_kind, r.holder_code, r.letter, r.scope or "") for r in rows]

    async def roles_view(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        _settings, fw = await self.context(project_id)
        roles, holders, roster = await self._holders(project_id)
        contacts = await self._contacts({r.holder_contact_id for r in roles if r.holder_contact_id})
        items = []
        for r, h in zip(roles, holders, strict=True):
            member = roster.get(r.roster_member_id) if r.roster_member_id else None
            contact = contacts.get(r.holder_contact_id) if r.holder_contact_id else None
            items.append(
                {
                    "id": str(r.id),
                    "role_code": r.role_code,
                    "custom_label": r.custom_label,
                    "roster_member_id": _s(r.roster_member_id),
                    "holder_contact_id": _s(r.holder_contact_id),
                    "deputy_roster_member_id": _s(r.deputy_roster_member_id),
                    "holder_name": (member.display_name if member is not None else None)
                    or (self._contact_name(contact) if contact is not None else None),
                    "user_id": h.user_id,
                    "valid_from": _s(r.valid_from),
                    "valid_to": _s(r.valid_to),
                    "valid_today": h.valid_on(today),
                    "conflict_rationale": r.conflict_rationale,
                }
            )
        defined = [
            {
                "code": r.code,
                "name_key": r.name_key,
                "holder_kind": r.holder_kind,
                "multi": r.multi,
                "required": r.required,
            }
            for r in fw.roles
        ]
        return {
            "roles": defined,
            "holders": items,
            "vacant": md.vacant_roles(fw, holders, today, required_only=False),
            "vacant_required": md.vacant_roles(fw, holders, today, required_only=True),
        }

    async def put_role_holders(
        self,
        project_id: uuid.UUID,
        role_code: str,
        holders_in: list[dict[str, Any]],
        *,
        actor_id: uuid.UUID,
        custom_label: str = "",
        today: date,
    ) -> dict[str, Any]:
        """Replace the holders of one role (rule 14) and publish ``stakeholders.role.changed`` (rule 16)."""
        _settings, fw = await self.context(project_id)
        await self.require_settings(project_id, lock=True)  # serialises concurrent replace-all writes
        role = fw.role(role_code)
        current = [r for r in await self.repo.roles(project_id) if r.role_code == role_code]
        linked = [r.holder_contact_id for r in current]
        existing_custom = [r for r in current if r.custom_label]
        if role is None and not (custom_label.strip() or existing_custom):
            raise StakeholderError("unknown_role")
        label = custom_label.strip() or (existing_custom[0].custom_label if existing_custom else "")
        _roles_before, holders_before, _roster = await self._holders(project_id)
        old_users = sorted(
            {h.user_id for h in holders_before if h.role_code == role_code and h.user_id and h.valid_on(today)}
        )
        new_rows: list[ProjectRole] = []
        for h in holders_in:
            roster_id, contact_id = h.get("roster_member_id"), h.get("holder_contact_id")
            if bool(roster_id) == bool(contact_id):
                raise StakeholderError("holder_required")
            vf, vt = _day(h.get("valid_from")), _day(h.get("valid_to"))
            if vf and vt and vt < vf:
                raise StakeholderError("invalid_validity")
            if roster_id:
                member = await self._roster(project_id, roster_id)
                if member.user_id is not None and not await self.is_member(project_id, member.user_id):
                    raise StakeholderError("user_not_project_member")
            else:
                await self._contact(contact_id, actor_id, linked=linked)
            deputy = h.get("deputy_roster_member_id")
            if deputy:
                await self._roster(project_id, deputy)
            new_rows.append(
                ProjectRole(
                    project_id=project_id,
                    role_code=role_code,
                    custom_label=label if role is None else "",
                    roster_member_id=_uuid(roster_id),
                    holder_contact_id=_uuid(contact_id),
                    deputy_roster_member_id=_uuid(deputy),
                    valid_from=vf,
                    valid_to=vt,
                    conflict_rationale=(h.get("conflict_rationale") or "").strip(),
                    created_by=actor_id,
                )
            )
        if role is not None and not role.multi and _overlapping([(r.valid_from, r.valid_to) for r in new_rows]):
            raise StakeholderError("role_not_multi")
        for old in [r for r in await self.repo.roles(project_id) if r.role_code == role_code]:
            await self.session.delete(old)
        await self.session.flush()
        for r in new_rows:
            self.session.add(r)
        await self.session.flush()
        conflicts = await self._enforce_conflicts(project_id, fw, today)
        _roles_after, holders_after, _r2 = await self._holders(project_id)
        new_users = sorted(
            {h.user_id for h in holders_after if h.role_code == role_code and h.user_id and h.valid_on(today)}
        )
        hints = await self._area_owner_hints(project_id, set(old_users) - set(new_users))
        await self._audit(
            actor_id,
            "stakeholder_role",
            role_code,
            "holders_set",
            metadata=an.jsonable({"role_code": role_code, "before": old_users, "after": new_users}),
        )
        self._publish(
            "role.changed",
            {
                "project_id": project_id,
                "role_code": role_code,
                "previous_user_ids": old_users,
                "user_ids": new_users,
            },
        )
        return {
            "conflicts": [_conflict_out(c) for c in conflicts],
            "hints": hints,
            "warnings": await self._frame_warnings(project_id),
        }

    async def _enforce_conflicts(
        self, project_id: uuid.UUID, fw: StakeholderFramework, today: date
    ) -> list[md.Conflict]:
        """Rule 12 at write time.

        An error-severity conflict refuses the write. A warning conflict needs a
        rationale on a holder row of that person in one of the roles involved
        (the acknowledgement); without it the write is refused too. Acknowledged
        warnings are returned so the screen keeps showing them.
        """
        _roles, holders, _roster = await self._holders(project_id)
        _bodies, bodies = await self._bodies(project_id)
        found = md.conflicts(fw, self._mandate_rows(await self.repo.mandates(project_id)), holders, bodies, today)
        errors = [c for c in found if c.severity == "error"]
        if errors:
            raise StakeholderError("self_approval_forbidden", violations=[_conflict_out(c) for c in errors])
        open_warnings = [c for c in found if not c.acknowledged]
        if open_warnings:
            raise StakeholderError("conflict_not_acknowledged", violations=[_conflict_out(c) for c in open_warnings])
        return found

    async def _area_owner_hints(self, project_id: uuid.UUID, removed_users: set[str]) -> list[dict[str, Any]]:
        """Rule 16: module 1 area owners are not changed, but a hint names areas the old holder owns."""
        if not removed_users:
            return []
        from app.modules.project_governance.public import project_areas

        return [
            {"code": "area_owner_was_previous_holder", "area_code": a.code, "owner_user_id": str(a.owner_user_id)}
            for a in await project_areas(self.session, project_id)
            if a.owner_user_id is not None and str(a.owner_user_id) in removed_users
        ]

    async def _frame_warnings(self, project_id: uuid.UUID) -> list[str]:
        """Rule 21 / decision n: editing the organisation after the gate warns that the frame document is binding."""

        documents = await self.frame_documents(project_id, "organisation")
        return ["frame_document_binding"] if any(d.status == "binding" for d in documents) else []

    # ── bodies ────────────────────────────────────────────────────────────

    async def get_body(self, project_id: uuid.UUID, bid: uuid.UUID, *, lock: bool = False) -> GovernanceBody:
        row = await self.repo.get_in_project(GovernanceBody, project_id, bid, lock=lock)
        if row is None:
            raise not_found("body_not_found")
        return row

    async def _body_fields(
        self, project_id: uuid.UUID, fw: StakeholderFramework, data: dict[str, Any]
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "body_type" in data and data["body_type"] is not None:
            if data["body_type"] not in {b.code for b in fw.body_types}:
                raise StakeholderError("unknown_body_type")
            out["body_type"] = data["body_type"]
        if "chair_role_code" in data:
            if data["chair_role_code"] and fw.role(data["chair_role_code"]) is None:
                raise StakeholderError("unknown_role")
            out["chair_role_code"] = data["chair_role_code"] or None
        if "quorum_kind" in data and data["quorum_kind"] is not None:
            if data["quorum_kind"] not in QUORUM_KINDS:
                raise StakeholderError("invalid_quorum")
            out["quorum_kind"] = data["quorum_kind"]
        if "quorum_min" in data:
            out["quorum_min"] = data["quorum_min"]
        if "terms_container_id" in data:
            out["terms_container_id"] = (
                (await self._container(project_id, data["terms_container_id"])).id
                if data["terms_container_id"]
                else None
            )
        for key in ("name", "meeting_series_ref"):
            if key in data and data[key] is not None:
                out[key] = str(data[key]).strip()
        if "decision_level" in data and data["decision_level"] is not None:
            out["decision_level"] = int(data["decision_level"])
        return out

    async def create_body(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID) -> GovernanceBody:
        _settings, fw = await self.context(project_id)
        fields = await self._body_fields(project_id, fw, data)
        if "body_type" not in fields:
            raise StakeholderError("unknown_body_type")
        code = (data.get("code") or fields["body_type"]).strip()
        if not fields.get("name"):
            fields["name"] = code
        if "decision_level" not in fields:
            bt = next(b for b in fw.body_types if b.code == fields["body_type"])
            fields["decision_level"] = bt.default_decision_level
        if fields.get("quorum_kind") == "min_members" and not fields.get("quorum_min"):
            raise StakeholderError("invalid_quorum")
        row = GovernanceBody(project_id=project_id, code=code, **fields)
        try:
            async with self.session.begin_nested():
                await self.repo.add(row)
        except IntegrityError as exc:
            raise conflict("duplicate_code") from exc
        await self._audit(actor_id, "stakeholder_body", row.id, "created", metadata={"code": code})
        return row

    async def update_body(
        self, project_id: uuid.UUID, bid: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> GovernanceBody:
        _settings, fw = await self.context(project_id)
        row = await self.get_body(project_id, bid, lock=True)
        fields = await self._body_fields(project_id, fw, data)
        for k, v in fields.items():
            setattr(row, k, v)
        if row.quorum_kind == "min_members" and not row.quorum_min:
            raise StakeholderError("invalid_quorum")
        await self.session.flush()
        await self._audit(actor_id, "stakeholder_body", row.id, "updated", metadata=an.jsonable(fields))
        return row

    async def delete_body(self, project_id: uuid.UUID, bid: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        row = await self.get_body(project_id, bid, lock=True)
        if any(m.holder_kind == "body" and m.holder_code == row.code for m in await self.repo.mandates(project_id)):
            raise conflict("body_in_use")
        await self._audit(actor_id, "stakeholder_body", row.id, "deleted", metadata={"code": row.code})
        await self.repo.delete(row)

    async def put_members(
        self, project_id: uuid.UUID, bid: uuid.UUID, members: list[dict[str, Any]], *, actor_id: uuid.UUID, today: date
    ) -> list[GovernanceBodyMember]:
        _settings, fw = await self.context(project_id)
        await self.require_settings(project_id, lock=True)  # serialises concurrent replace-all writes
        body = await self.get_body(project_id, bid, lock=True)
        linked = [x.contact_id for x in await self.repo.body_members(project_id) if x.body_id == body.id]
        rows: list[GovernanceBodyMember] = []
        custom_roles = {r.role_code for r in await self.repo.roles(project_id)}
        for m in members:
            given = [k for k in ("role_code", "user_id", "contact_id") if m.get(k)]
            if len(given) != 1:
                raise StakeholderError("invalid_member")
            if m.get("role_code") and fw.role(m["role_code"]) is None and m["role_code"] not in custom_roles:
                raise StakeholderError("unknown_role")
            if m.get("user_id"):
                await self._require_member(project_id, m["user_id"])
            if m.get("contact_id"):
                await self._contact(m["contact_id"], actor_id, linked=linked)
            vf, vt = _day(m.get("valid_from")), _day(m.get("valid_to"))
            if vf and vt and vt < vf:
                raise StakeholderError("invalid_validity")
            rows.append(
                GovernanceBodyMember(
                    project_id=project_id,
                    body_id=body.id,
                    role_code=m.get("role_code") or None,
                    user_id=_uuid(m.get("user_id")),
                    contact_id=_uuid(m.get("contact_id")),
                    voting=bool(m.get("voting", True)),
                    valid_from=vf,
                    valid_to=vt,
                )
            )
        for old in [x for x in await self.repo.body_members(project_id) if x.body_id == body.id]:
            await self.session.delete(old)
        await self.session.flush()
        for r in rows:
            self.session.add(r)
        await self.session.flush()
        await self._enforce_conflicts(project_id, fw, today)
        await self._audit(actor_id, "stakeholder_body", body.id, "members_set", metadata={"count": len(rows)})
        return rows

    async def bodies_view(self, project_id: uuid.UUID, *, today: date) -> list[dict[str, Any]]:
        bodies, parsed = await self._bodies(project_id)
        _roles, holders, _roster = await self._holders(project_id)
        members = await self.repo.body_members(project_id)
        out = []
        for b, p in zip(bodies, parsed, strict=True):
            needed, present = md.quorum_needed(p, today), md.body_present(p, holders, today)
            out.append(
                {
                    "id": str(b.id),
                    "code": b.code,
                    "body_type": b.body_type,
                    "name": b.name,
                    "chair_role_code": b.chair_role_code,
                    "quorum_kind": b.quorum_kind,
                    "quorum_min": b.quorum_min,
                    "decision_level": b.decision_level,
                    "meeting_series_ref": b.meeting_series_ref,
                    "terms_container_id": _s(b.terms_container_id),
                    "members": [
                        {
                            "id": str(m.id),
                            "role_code": m.role_code,
                            "user_id": _s(m.user_id),
                            "contact_id": _s(m.contact_id),
                            "voting": m.voting,
                            "valid_from": _s(m.valid_from),
                            "valid_to": _s(m.valid_to),
                            "valid_today": md.Member(valid_from=m.valid_from, valid_to=m.valid_to).valid_on(today),
                        }
                        for m in members
                        if m.body_id == b.id
                    ],
                    "quorum_needed": needed,
                    "quorum_present": present,
                    "inquorate": present < needed,
                }
            )
        return out

    # ── mandates ──────────────────────────────────────────────────────────

    async def matrix(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        _settings, fw = await self.context(project_id)
        rows = await self.repo.mandates(project_id)
        _roles, holders, _roster = await self._holders(project_id)
        _bodies_rows, bodies = await self._bodies(project_id)
        parsed = self._mandate_rows(rows)
        return {
            "decision_types": [d.model_dump() for d in fw.decision_types],
            "roles": sorted({*(r.code for r in fw.roles), *(h.role_code for h in holders)}),
            "bodies": [b.code for b in bodies],
            "rows": [
                {
                    "id": str(r.id),
                    "decision_type": r.decision_type,
                    "scope": r.scope,
                    "holder_kind": r.holder_kind,
                    "holder_code": r.holder_code,
                    "letter": r.letter,
                    "scope_note": r.scope_note,
                    "limit_ref": r.limit_ref,
                }
                for r in rows
            ],
            "missing": md.missing_deciders(fw, parsed),
            "conflicts": [_conflict_out(c) for c in md.conflicts(fw, parsed, holders, bodies, today)],
        }

    async def put_mandates(
        self, project_id: uuid.UUID, rows_in: list[dict[str, Any]], *, actor_id: uuid.UUID, today: date
    ) -> dict[str, Any]:
        """Replace the matrix. Two deciders for one type and scope is refused (rule 13)."""
        _settings, fw = await self.context(project_id)
        await self.require_settings(project_id, lock=True)  # serialises concurrent matrix writes
        role_codes = {r.code for r in fw.roles} | {r.role_code for r in await self.repo.roles(project_id)}
        body_codes = {b.code for b in await self.repo.bodies(project_id)}
        parsed: list[md.MandateRow] = []
        seen: set[tuple[str, str, str, str]] = set()
        for r in rows_in:
            dt = r.get("decision_type")
            if fw.decision_type(dt or "") is None:
                raise StakeholderError("unknown_decision_type")
            kind, code, letter = r.get("holder_kind"), r.get("holder_code"), r.get("letter")
            if letter not in ("P", "D", "A", "C", "I"):
                raise StakeholderError("invalid_letter")
            if kind == "role" and code not in role_codes:
                raise StakeholderError("unknown_role")
            if kind == "body" and code not in body_codes:
                raise not_found("unknown_body")
            if kind not in ("role", "body"):
                raise StakeholderError("unknown_role")
            scope = (r.get("scope") or "").strip()
            key = (dt, scope, kind, code)
            if key in seen:
                raise StakeholderError("duplicate_code")
            seen.add(key)
            parsed.append(md.MandateRow(dt, kind, code, letter, scope))
        twice = [{"decision_type": dt, "scope": sc} for (dt, sc), n in md.decider_counts(parsed).items() if n > 1]
        if twice:
            raise StakeholderError("two_deciders", violations=twice)
        for old in await self.repo.mandates(project_id, lock=True):
            await self.session.delete(old)
        await self.session.flush()
        notes = {
            (r.get("decision_type"), (r.get("scope") or "").strip(), r.get("holder_kind"), r.get("holder_code")): r
            for r in rows_in
        }
        for p in parsed:
            src = notes[(p.decision_type, p.scope, p.holder_kind, p.holder_code)]
            self.session.add(
                Mandate(
                    project_id=project_id,
                    decision_type=p.decision_type,
                    scope=p.scope,
                    holder_kind=p.holder_kind,
                    holder_code=p.holder_code,
                    letter=p.letter,
                    scope_note=(src.get("scope_note") or "").strip(),
                    limit_ref=self._limit_ref(fw, p.decision_type),
                )
            )
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict("concurrent_change") from exc
        conflicts = await self._enforce_conflicts(project_id, fw, today)
        await self._audit(actor_id, "stakeholder_mandate", project_id, "matrix_set", metadata={"rows": len(parsed)})
        self._publish("mandate.changed", {"project_id": project_id, "rows": len(parsed)})
        return {
            "conflicts": [_conflict_out(c) for c in conflicts],
            "missing": md.missing_deciders(fw, parsed),
            "warnings": await self._frame_warnings(project_id),
        }

    async def _party_names(
        self, project_id: uuid.UUID, parties: list[md.Party], roster: dict[uuid.UUID, Any]
    ) -> list[str | None]:
        """A display name per party: the roster entry, else the contact, else the user's account name."""
        from app.modules.teams.models import RosterMember
        from app.modules.users.models import User

        contacts = await self._contacts({_uuid(p.contact_id) for p in parties if p.contact_id})
        user_ids = {_uuid(p.user_id) for p in parties if p.user_id}
        by_user: dict[str, str] = {}
        if user_ids:
            users = await self.session.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
            by_user = {str(uid): name for uid, name in users.all() if name}
            entries = await self.session.execute(
                select(RosterMember.user_id, RosterMember.display_name).where(
                    RosterMember.project_id == project_id, RosterMember.user_id.in_(user_ids)
                )
            )
            # The project's own people list wins over the account name.
            by_user.update({str(uid): name for uid, name in entries.all() if name})
        out: list[str | None] = []
        for p in parties:
            member = roster.get(_uuid(p.roster_member_id)) if p.roster_member_id else None
            contact = contacts.get(_uuid(p.contact_id)) if p.contact_id else None
            out.append(
                (member.display_name if member is not None else None)
                or (self._contact_name(contact) if contact is not None else None)
                or by_user.get(p.user_id or "")
                or None
            )
        return out

    async def who_decides(
        self,
        project_id: uuid.UUID,
        decision_type: str,
        scope: str,
        *,
        today: date,
        amount: Any = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        """Rule 11: the deciding role or body resolved to people; money tier delegated to module 2."""
        _settings, fw = await self.context(project_id)
        dt = fw.decision_type(decision_type)
        if dt is None:
            raise StakeholderError("unknown_decision_type")
        _roles, holders, roster = await self._holders(project_id)
        _b, bodies = await self._bodies(project_id)
        res = md.who_decides(
            self._mandate_rows(await self.repo.mandates(project_id)), decision_type, scope, holders, bodies, today
        )
        names = await self._party_names(project_id, res.parties, roster)
        out: dict[str, Any] = {
            "decision_type": decision_type,
            "scope": scope,
            "holder_kind": res.holder_kind,
            "holder_code": res.holder_code,
            # Who may decide: voting seats only. ``parties`` lists everyone seated, with the flag.
            "user_ids": res.voting_user_ids,
            "parties": [
                {
                    "user_id": p.user_id,
                    "contact_id": p.contact_id,
                    "roster_member_id": p.roster_member_id,
                    "role_code": p.via_role,
                    "voting": p.voting,
                    "name": names[i],
                }
                for i, p in enumerate(res.parties)
            ],
            "quorum_needed": res.quorum_needed,
            "quorum_present": res.quorum_present,
            "flags": list(res.flags),
            "approval_target_kind": dt.approval_target_kind,
            "commitment_type": dt.commitment_type,
            "authority": None,
        }
        value = _amount(amount)
        if dt.commitment_type and value is not None:
            evaluator = authority_evaluator()
            if evaluator is None:
                out["flags"].append("authority_not_evaluated")
            else:
                project = await self._project(project_id)
                ccy = (currency or getattr(project, "currency", "") or "").upper()
                answer = await evaluator(self.session, project_id, dt.commitment_type, value, ccy, today)
                out["authority"] = {
                    "tier_code": answer.tier_code,
                    "approver_user_ids": list(answer.approver_user_ids),
                    "escalate_outside": answer.escalate_outside,
                    "schedule": answer.schedule,
                    "amount": str(value),
                    "currency": ccy,
                    "flags": list(answer.flags),
                }
        return out

    async def conflicts(self, project_id: uuid.UUID, *, today: date) -> list[dict[str, Any]]:
        _settings, fw = await self.context(project_id)
        _roles, holders, _roster = await self._holders(project_id)
        _b, bodies = await self._bodies(project_id)
        rows = self._mandate_rows(await self.repo.mandates(project_id))
        return [_conflict_out(c) for c in md.conflicts(fw, rows, holders, bodies, today)]

    # ── frame documents (rule 21) ─────────────────────────────────────────

    async def frame_documents(self, project_id: uuid.UUID, which: str) -> list[Any]:
        """The module 1 frame documents one export of this module is filed into.

        Module 1 keys a document by (area, document type). Both come from the
        phase model's ``hosts`` tag for this export, never from a code. Empty
        when the model hosts the subject nowhere, and also when the project
        was pinned before its model gained the document type.
        """
        from app.modules.project_governance.public import project_documents
        from app.modules.stakeholders import hosting

        catalogue = await hosting.project_catalogue(self.session, project_id)
        found = hosting.host(catalogue, hosting.EXPORT_TAGS[which]) if catalogue is not None else None
        if found is None:
            return []
        return [
            d
            for d in await project_documents(self.session, project_id)
            if d.code == found.doc_type and d.area_code == found.area_code
        ]

    async def filing_can(self, project_id: uuid.UUID, *, can_manage: bool) -> dict[str, dict[str, Any]]:
        """Whether each export can be filed as a frame document: ``{applies, allowed, reason}`` per export.

        A project run without gates has no frame documents, so the action does
        not exist there. Where it exists and is refused, the reason is the code
        the write would answer.
        """
        from app.modules.stakeholders import hosting

        in_use = await hosting.project_catalogue(self.session, project_id) is not None
        out: dict[str, dict[str, Any]] = {}
        for which in hosting.EXPORT_TAGS:
            if not in_use:
                out[which] = {"applies": False, "allowed": False, "reason": "gates_not_in_use"}
                continue
            docs = [d for d in await self.frame_documents(project_id, which) if d.container_id is not None]
            reason = (
                "no_permission"
                if not can_manage
                else "frame_document_missing"
                if not docs
                else "frame_document_read_only"
                if any(d.read_only for d in docs)
                else None
            )
            out[which] = {"applies": True, "allowed": reason is None, "reason": reason}
        return out

    async def file_frame_document(
        self,
        project_id: uuid.UUID,
        *,
        which: str,
        content: bytes,
        file_name: str,
        mime_type: str,
        actor_id: uuid.UUID,
        change_reason: str = "",
        change_impact: str = "",
        can_manage_governance: bool = False,
    ) -> dict[str, Any]:
        """File a generated export as a new CDE revision of its frame document (rule 21).

        Before the gate the revision is simply the pending one; module 1 makes
        it binding at the gate. Once the document is binding, the new revision
        is proposed through a module 1 change request, which needs a reason.
        A read-only document takes no revision at all.
        """
        from fastapi import HTTPException

        from app.core.storage import get_storage_backend
        from app.modules.cde.schemas import RevisionCreate
        from app.modules.cde.service import CDEService
        from app.modules.project_governance.errors import GovernanceError
        from app.modules.project_governance.service import GovernanceService

        await self.require_settings(project_id)
        docs = [d for d in await self.frame_documents(project_id, which) if d.container_id is not None]
        if not docs:
            raise conflict("frame_document_missing")
        if any(d.read_only for d in docs):
            raise conflict("frame_document_read_only")
        binding = [d for d in docs if d.status == "binding"]
        reason = (change_reason or "").strip()
        if binding and not reason:
            raise StakeholderError("change_reason_required")
        filed: list[dict[str, Any]] = []
        for doc in docs:
            key = f"stakeholders/{project_id}/{uuid.uuid4().hex}_{file_name}"
            await get_storage_backend().put(key, content)
            try:
                revision = await CDEService(self.session).create_revision(
                    doc.container_id,
                    RevisionCreate(
                        file_name=file_name, file_size=str(len(content)), mime_type=mime_type, storage_key=key
                    ),
                    user_id=str(actor_id),
                )
            except HTTPException as exc:
                raise conflict("frame_document_missing", detail=str(exc.detail)) from exc
            change_request_id = None
            if doc.status == "binding":
                try:
                    request = await GovernanceService(self.session).create_change_request(
                        project_id,
                        doc.id,
                        reason=reason,
                        impact=(change_impact or "").strip(),
                        proposed_revision_id=revision.id,
                        actor_id=actor_id,
                        # Module 1 decides who may propose a change: its manager, or the area's owner.
                        is_manager=can_manage_governance,
                    )
                except GovernanceError as exc:
                    raise StakeholderError(exc.code, exc.status_code, detail=exc.detail) from exc
                change_request_id = str(request.id)
            await self._audit(
                actor_id,
                "stakeholder_frame_document",
                doc.id,
                "filed",
                metadata=an.jsonable({"revision_id": revision.id, "file_name": file_name, "doc_type": doc.code}),
            )
            filed.append(
                {
                    "document_id": str(doc.id),
                    "doc_type": doc.code,
                    "container_id": str(doc.container_id),
                    "revision_id": str(revision.id),
                    "change_request_id": change_request_id,
                }
            )
        return {**filed[0], "documents": filed, "warnings": ["frame_document_binding"] if binding else []}

    # ── readiness (rule 20) and validation payload ────────────────────────

    async def readiness(self, project_id: uuid.UUID, *, today: date) -> dict[str, dict[str, Any]]:
        """The five governance evidence checks, each ``{status, counts}``."""
        settings, fw = await self.context(project_id)
        stakeholders = [s for s in await self.repo.stakeholders(project_id) if s.status == "active"]
        assessments = await self.repo.assessments(project_id)
        assessed = {str(a.stakeholder_id) for a in assessments}
        external = [s for s in stakeholders if (c := fw.category(s.category)) and c.kind == "external"]
        external_assessed = [s for s in external if str(s.id) in assessed]
        gaps = await self.key_stakeholders_without_plan(project_id, settings, fw)
        rows = self._mandate_rows(await self.repo.mandates(project_id))
        missing = md.missing_deciders(fw, rows)
        _roles, holders, _roster = await self._holders(project_id)
        vacant = md.vacant_roles(fw, holders, today, required_only=True)
        commitments = await self.repo.commitments(project_id)
        from app.modules.stakeholders import evidence

        unexplained = [c.code for c in commitments if c.status == "breached" and not c.breach_rationale.strip()]
        overdue = [c.code for c in commitments if self.commitment_overdue(c, today)]

        def check(ok: bool, **counts: Any) -> dict[str, Any]:
            return {"status": "met" if ok else "not_met", **counts}

        return {
            "register_present": check(bool(external_assessed), external=len(external), assessed=len(external_assessed)),
            "key_stakeholders_planned": check(not gaps, without_plan=len(gaps), refs=gaps),
            "mandates_complete": check(not missing, missing=len(missing), refs=missing),
            "roles_filled": check(not vacant, vacant=len(vacant), refs=vacant),
            "commitments_tracked": evidence.commitments_tracked(
                unexplained, overdue, warnings=evidence.warning_state_served()
            ),
        }

    async def overdue_commitments(self, project_id: uuid.UUID, *, today: date) -> list[dict[str, str]]:
        """Open promises past their due date, oldest first: ``{code, due_date}``."""
        rows = [c for c in await self.repo.commitments(project_id) if self.commitment_overdue(c, today)]
        return [{"code": c.code, "due_date": c.due_date.isoformat()} for c in sorted(rows, key=lambda c: c.due_date)]

    async def key_stakeholders_without_plan(
        self, project_id: uuid.UUID, settings: StakeholderSettings, fw: StakeholderFramework
    ) -> list[str]:
        """Rule 5: ``manage_closely`` (current method) with a positive gap and no live plan item covering them."""
        stakeholders = {str(s.id): s for s in await self.repo.stakeholders(project_id) if s.status == "active"}
        views = [self._assessment_view(a) for a in await self.repo.assessments(project_id)]
        latest = an.latest_by_stakeholder(views)
        plans = [p for p in await self.repo.plan_items(project_id) if p.status in LIVE_PLAN]
        out = []
        for sid, s in stakeholders.items():
            current = an.current_classification(views, sid, settings.analysis_method)
            if current is None or current.classification != "manage_closely":
                continue
            last = latest.get(sid)
            gap = an.engagement_gap(
                fw, last.engagement_current if last else None, last.engagement_desired if last else None
            )
            if gap is None or gap <= 0:
                continue
            covered = any(
                sid in (p.audience_stakeholder_ids or []) or s.category in (p.audience_categories or []) for p in plans
            )
            if not covered:
                out.append(s.code)
        return sorted(out)

    async def validation_payload(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """Everything the ``stakeholders`` rule set reads, as JSON values."""
        settings, fw = await self.context(project_id)
        views = await self.stakeholder_views(project_id, can_read_personal=False, today=today)
        events = await self.repo.events(project_id)
        _roles, holders, _roster = await self._holders(project_id)
        _b, bodies = await self._bodies(project_id)
        rows = self._mandate_rows(await self.repo.mandates(project_id))
        return an.jsonable(
            {
                "today": today,
                "framework": fw.model_dump(mode="json"),
                "stakeholders": [
                    {"code": v["code"], "category": v["category"], "status": v["status"], "review_due": v["review_due"]}
                    for v in views
                ],
                "key_without_plan": await self.key_stakeholders_without_plan(project_id, settings, fw),
                "events": [
                    {
                        "title": e.title,
                        "id": e.id,
                        "feedback_not_reported": an.feedback_not_reported(
                            fw,
                            level=e.participation_level,
                            status=e.status,
                            held_on=e.held_on,
                            feedback_summary=e.feedback_summary,
                            today=today,
                        ),
                    }
                    for e in events
                ],
                "commitments": [
                    {
                        "code": c.code,
                        "status": c.status,
                        "owner": c.owner_user_id,
                        "due_date": c.due_date,
                        "overdue": self.commitment_overdue(c, today),
                        "breach_rationale": c.breach_rationale,
                    }
                    for c in await self.repo.commitments(project_id)
                ],
                "missing_deciders": md.missing_deciders(fw, rows),
                "conflicts": [_conflict_out(c) for c in md.conflicts(fw, rows, holders, bodies, today)],
                "vacant_required": md.vacant_roles(fw, holders, today, required_only=True),
                "bodies": [
                    {
                        "code": b.code,
                        "needed": md.quorum_needed(b, today),
                        "present": md.body_present(b, holders, today),
                    }
                    for b in bodies
                ],
            }
        )


def _overlapping(windows: list[tuple[date | None, date | None]]) -> bool:
    lo, hi = date.min, date.max
    spans = sorted(((a or lo), (b or hi)) for a, b in windows)
    return any(spans[i + 1][0] <= spans[i][1] for i in range(len(spans) - 1))


def _conflict_out(c: md.Conflict) -> dict[str, Any]:
    return {
        "decision_type": c.decision_type,
        "scope": c.scope,
        "user_id": c.user_id,
        "letters": list(c.letters),
        "roles": list(c.roles),
        "severity": c.severity,
        "acknowledged": c.acknowledged,
    }
