# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Staffing service: plan, positions, fills, handovers, personnel files, documents, travel, leave, retention.

Every write runs in the caller's transaction with its audit entry
(``log_activity``) and its events (``publish_after_commit``).

Approval (lead decision 10): the plan is the content of the governance frame
document that the project's governance catalogue tags as hosting staffing
(``hosting``). This module submits; the gate decision (or an approved frame
change request) binds the document, and ``mirror_binding`` copies that onto
the plan together with a frozen snapshot of the positions. Only a decision
taken after the submission counts. While the plan is in review everything the
reviewer reads stands still. Editing a position afterwards opens a revision;
the bound snapshot stays in force until governance binds the next one (rule 7).

Privacy (SPEC rule 13, section 10): the plan side shows names, roles, FTE,
dates and the cleared-to-work flag only. A personnel file opens through a
relationship to the person and nothing else: the owner or deputy of the
governance area that hosts staffing, the line manager of a position the
person is confirmed on, or the person themself. A permission is needed on top
of the relationship and never replaces it, and whatever sets a relationship
(the line manager of a position) needs the assignment permission. Every read
writes an access audit row. Expiry is the credentials module's (rule 9): this
module creates one validity record per document, for that person, and reads
its status.

The caller arrives as an :class:`Actor`: a user id and the booleans the
router's permission checks produced. No role and no token reach this file.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.project_governance import public as governance
from app.modules.staffing import hosting, rules
from app.modules.staffing.catalogue import (
    DEFAULT_CATALOGUE_ID,
    HEALTH_KIND,
    PHASES,
    STAFFING_MODEL_KIND,
    StaffingModelCatalogue,
    label_of,
    register_kinds,
)
from app.modules.staffing.errors import StaffingError, conflict, forbidden, not_found
from app.modules.staffing.fsm import (
    FILE_FSM,
    FILL_FSM,
    LEAVE_FSM,
    PLAN_EDITABLE,
    PLAN_FSM,
    POSITION_FSM,
    TRAVEL_FSM,
)
from app.modules.staffing.models import (
    HandoverLink,
    LeaveRecord,
    PersonnelDocument,
    PersonnelFile,
    PositionFill,
    StaffingPlan,
    StaffingPosition,
    TravelRecord,
)
from app.modules.staffing.repository import StaffingRepository
from app.modules.staffing.schemas import POSITION_REQUIRED

logger = logging.getLogger(__name__)

MODULE = "staffing"
CUSTOM_ROLE = "custom"
# The states a position is moved to by hand; ``filled`` is derived (rule 2).
POSITION_SETTABLE = ("open", "recruiting", "on_hold", "cancelled")
_GO = ("go", "go_with_conditions")
_POSITION_FIELDS = (
    "custom_label",
    "organisation",
    "title",
    "fte",
    "headcount",
    "entry_date",
    "exit_date",
    "required_before",
    "key_role",
    "handover_role",
    "recruiting_channel",
    "owner_user_id",
    "contract_id",
    "rfq_id",
    "notes",
    "sort_order",
    "role_code",
    "phase",
)
_POSITION_NULLABLE = tuple(k for k in _POSITION_FIELDS if k not in POSITION_REQUIRED)
# What a governance gate reads of a position (rules 5 and 6).
_GATE_FIELDS = ("key_role", "handover_role", "required_before")
# Refusal reasons that are a state conflict; every other reason is a missing permission or relationship.
_CONFLICT_REASONS = frozenset(
    {
        "gate_fields_frozen",
        "already_in_state",
        "file_not_active",
        "file_not_ended",
        "file_not_held",
        "file_anonymised",
        "retention_hold_active",
        "retention_obligation_active",
        "document_without_validity",
        "verifier_is_recorder",
    }
)


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


@dataclass(frozen=True)
class Actor:
    """Who is calling, and what the router's permission checks allow them."""

    user_id: uuid.UUID | None
    personnel_read: bool = False
    personnel_edit: bool = False
    personnel_erase: bool = False
    # May name the line manager of a position, which is what relates somebody to a person.
    assign_owner: bool = False
    # May change what a gate reads of a position.
    manage: bool = False
    # Holds the plan's edit permission. Routes enforce it themselves; views read it for the ``can`` flags.
    edit: bool = False


def _as_actor(actor: Any) -> Actor:
    """A bare user id is a caller with no capability beyond the route's own permission."""
    return actor if isinstance(actor, Actor) else Actor(actor)


def _uid(actor: Any) -> Any:
    return actor.user_id if isinstance(actor, Actor) else actor


_SAME = "same-as-reason"


def _can(allowed: bool, reason: str | None, state_reason: str | None = _SAME) -> dict[str, Any]:
    """One capability for the client: ``allowed``, the refusal code when not, and whether it ``applies``.

    ``state_reason`` is the refusal a caller with every right would get (``None``
    when the state allows the action). Left out, the refusal itself is read,
    which is right for a refusal that is only ever about a right.
    """
    refused = None if allowed else reason
    return rules.capability(refused, refused if state_reason is _SAME else state_reason)


def _refusal(reason: str, **kw: Any) -> StaffingError:
    return StaffingError(reason, 409 if reason in _CONFLICT_REASONS else 403, **kw)


def _refuse_nulls(changes: dict[str, Any], nullable: Iterable[str] = ()) -> None:
    """An explicit null on a field the row cannot leave empty is a 422, never a database error."""
    allowed = set(nullable)
    empty = sorted(k for k, v in changes.items() if v is None and k not in allowed)
    if empty:
        raise StaffingError("field_required", 422, violations=[{"code": "field_required", "ref": k} for k in empty])


def position_dict(p: StaffingPosition) -> dict[str, Any]:
    return {
        "id": p.id,
        "role_code": p.role_code,
        "phase": p.phase,
        "key_role": p.key_role,
        "handover_role": p.handover_role,
        "required_before": p.required_before,
        "entry_date": p.entry_date,
        "exit_date": p.exit_date,
        "fte": Decimal(p.fte),
        "headcount": p.headcount,
        "status": p.status,
    }


def fill_dict(f: PositionFill) -> dict[str, Any]:
    return {
        "id": f.id,
        "position_id": f.position_id,
        "roster_member_id": f.roster_member_id,
        "fte_share": Decimal(f.fte_share),
        "from_date": f.from_date,
        "to_date": f.to_date,
        "status": f.status,
    }


def handover_dict(h: HandoverLink) -> dict[str, Any]:
    return {
        "id": h.id,
        "from_fill_id": h.from_fill_id,
        "to_position_id": h.to_position_id,
        "overlap_days": h.overlap_days,
    }


class StaffingService:
    """Orchestrates the staffing plan and personnel files of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StaffingRepository(session)
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
        """The project's governance catalogue, where the tags that place staffing are read (``hosting``)."""
        if project_id not in self._governance:
            self._governance[project_id] = await hosting.project_catalogue(self.session, project_id)
        return self._governance[project_id]

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    async def catalogue_for(self, plan: StaffingPlan) -> StaffingModelCatalogue:
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        # The triple is the plan's own stored pin, checked when it was written.
        return await resolve_catalogue(
            self.session,
            plan.catalogue_source,
            plan.catalogue_id,
            plan.catalogue_version,
            kind=STAFFING_MODEL_KIND,
            from_pin=True,
        )

    async def _requested_catalogue(
        self, tenant_id: str | None, source: str, cid: str, version: int | None
    ) -> StaffingModelCatalogue:
        """A catalogue named by a request: another tenant's answers 404, the caller's retired one 409."""
        from app.modules.project_governance.catalogue_store import resolve_catalogue
        from app.modules.project_governance.errors import GovernanceError

        try:
            return await resolve_catalogue(
                self.session, source, cid, version, kind=STAFFING_MODEL_KIND, tenant_id=tenant_id
            )
        except GovernanceError as exc:
            raise StaffingError(exc.code, exc.status_code) from exc

    async def _pin(self, tenant_id: str | None, source: str, cid: str, version: int | None) -> int:
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        try:
            return await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, cid, version, kind=STAFFING_MODEL_KIND
            )
        except GovernanceError as exc:
            raise StaffingError(exc.code, exc.status_code) from exc

    async def get_plan(self, project_id: uuid.UUID, *, lock: bool = False) -> StaffingPlan | None:
        return await self.repo.plan(project_id, lock=lock)

    async def require_plan(self, project_id: uuid.UUID, *, lock: bool = False) -> StaffingPlan:
        plan = await self.repo.plan(project_id, lock=lock)
        if plan is None:
            raise not_found("plan_missing")
        return plan

    async def _child(self, model: type, project_id: uuid.UUID, row_id: uuid.UUID, code: str, *, lock=False) -> Any:
        row = await self.repo.child(model, project_id, row_id, lock=lock)
        if row is None:
            raise not_found(code)
        return row

    async def _roster_member(self, project_id: uuid.UUID, roster_member_id: uuid.UUID, *, lock: bool = False) -> Any:
        """Rule 3: a roster member of THIS project, else 404 (another project's id is indistinguishable)."""
        from app.modules.teams.models import RosterMember

        stmt = select(RosterMember).where(RosterMember.id == roster_member_id, RosterMember.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        member = (await self.session.execute(stmt)).scalar_one_or_none()
        if member is None:
            raise not_found("roster_member_not_found")
        return member

    async def _members(self, project_id: uuid.UUID, ids: Iterable[Any]) -> dict[uuid.UUID, Any]:
        from app.modules.teams.models import RosterMember

        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        stmt = select(RosterMember).where(RosterMember.project_id == project_id, RosterMember.id.in_(wanted))
        return {m.id: m for m in (await self.session.execute(stmt)).scalars()}

    # ── plan ───────────────────────────────────────────────────────────────

    async def set_plan(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        catalogue_source: str = "shipped",
        catalogue_id: str | None = None,
        catalogue_version: int | None = None,
        requires_accommodation: bool = False,
        commissioning_date: date | None = None,
    ) -> StaffingPlan:
        """Create the project's plan and pin a staffing catalogue (default: the country's, else neutral)."""
        project = await self._project(project_id)
        if await self.repo.plan(project_id) is not None:
            raise conflict("plan_exists")
        country = getattr(project, "country_code", None)
        cid = catalogue_id
        if cid is None:
            # Governance answers for the country: the active pack's default, else the one shipped catalogue
            # that claims it. Without an answer the module pins its neutral file; it has no country rule.
            pin = governance.default_catalogue_pin(STAFFING_MODEL_KIND, country)
            if pin is not None:
                catalogue_source, cid, catalogue_version = pin.source, pin.catalogue_id, pin.version
            else:
                cid = DEFAULT_CATALOGUE_ID
        version = await self._pin(tenant_id, catalogue_source, cid, catalogue_version)
        plan = StaffingPlan(
            project_id=project_id,
            catalogue_source=catalogue_source,
            catalogue_id=cid,
            catalogue_version=version,
            status="draft",
            requires_accommodation=requires_accommodation,
            commissioning_date=commissioning_date,
            bound_snapshot={},
            created_by=actor_id,
        )
        await self._insert(plan, "plan_exists")
        await self._audit(actor_id, "staffing_plan", plan.id, "plan_created", metadata={"catalogue": cid})
        return plan

    async def patch_plan(self, project_id: uuid.UUID, changes: dict[str, Any], actor_id: Any) -> StaffingPlan:
        """The plan's frame (remote site, commissioning date) is read by rule 6, so it is edited like a position."""
        _refuse_nulls(changes, ("commissioning_date",))
        plan = await self.require_plan(project_id, lock=True)
        new = {
            k: changes[k]
            for k in ("requires_accommodation", "commissioning_date")
            if k in changes and changes[k] != getattr(plan, k)
        }
        if not new:
            return plan
        plan = await self._open_for_edit(project_id, _uid(actor_id))
        for key, value in new.items():
            setattr(plan, key, value)
        await self.session.flush()
        await self._audit(
            _uid(actor_id),
            "staffing_plan",
            plan.id,
            "plan_updated",
            metadata={k: _iso(v) if isinstance(v, date) else v for k, v in new.items()},
        )
        return plan

    async def change_catalogue(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        catalogue_source: str,
        catalogue_id: str,
        catalogue_version: int | None,
        role_mapping: dict[str, str],
    ) -> StaffingPlan:
        """Rule 21: re-pin with a role-code mapping; positions whose role is unmapped become ``custom``."""
        from app.modules.staffing.messages import translate

        plan = await self._open_for_edit(project_id, actor_id)
        old = await self.catalogue_for(plan)
        new, version = await self._change_target(
            tenant_id, catalogue_source, catalogue_id, catalogue_version, role_mapping
        )
        targets = [r.code for r in new.roles]
        unmapped: list[str] = []
        for p in await self.repo.positions(project_id):
            outcome, target = rules.catalogue_change_outcome(p.role_code, CUSTOM_ROLE, role_mapping, targets)
            if outcome == "custom":
                role = old.role(p.role_code)
                p.custom_label = p.custom_label or (translate(role.name_key, "en") if role else p.role_code)
                p.role_code = CUSTOM_ROLE
                unmapped.append(str(p.id))
            else:
                p.role_code = target
        plan.catalogue_source, plan.catalogue_id, plan.catalogue_version = catalogue_source, catalogue_id, version
        await self.session.flush()
        await self._audit(
            actor_id,
            "staffing_plan",
            plan.id,
            "catalogue_changed",
            metadata={"catalogue": catalogue_id, "version": version, "custom_positions": unmapped},
        )
        return plan

    async def _change_target(
        self, tenant_id: str | None, source: str, cid: str, version: int | None, role_mapping: dict[str, str]
    ) -> tuple[StaffingModelCatalogue, int]:
        """The catalogue a change points at, pinnable by this tenant, with a mapping that names its roles only."""
        pinned = await self._pin(tenant_id, source, cid, version)
        new = await self._requested_catalogue(tenant_id, source, cid, pinned)
        bad = [v for v in role_mapping.values() if new.role(v) is None]
        if bad:
            raise StaffingError(
                "role_mapping_unknown_target", 422, violations=[{"code": "role_unknown", "ref": b} for b in bad]
            )
        return new, pinned

    async def preview_catalogue_change(
        self,
        project_id: uuid.UUID,
        *,
        tenant_id: str | None,
        catalogue_source: str,
        catalogue_id: str,
        catalogue_version: int | None,
        role_mapping: dict[str, str],
    ) -> dict[str, Any]:
        """What ``change_catalogue`` would do with this body, position by position. Writes nothing."""
        plan = await self.require_plan(project_id)
        if plan.status == "in_review":
            raise conflict("plan_in_review")
        new, version = await self._change_target(
            tenant_id, catalogue_source, catalogue_id, catalogue_version, role_mapping
        )
        targets = [r.code for r in new.roles]
        positions = []
        for p in await self.repo.positions(project_id):
            outcome, target = rules.catalogue_change_outcome(p.role_code, CUSTOM_ROLE, role_mapping, targets)
            positions.append(
                {
                    "position_id": str(p.id),
                    "role_code": p.role_code,
                    "custom_label": p.custom_label,
                    "title": p.title,
                    "phase": p.phase,
                    "outcome": outcome,
                    "target_role": target,
                }
            )
        return {
            "catalogue_source": catalogue_source,
            "catalogue_id": catalogue_id,
            "catalogue_version": version,
            "custom_role_code": CUSTOM_ROLE,
            "target_roles": [
                {
                    "code": r.code,
                    "name_key": r.name_key,
                    "labels": r.labels,
                    "organisation": r.organisation,
                    "phases": list(r.phases),
                }
                for r in new.roles
            ],
            "positions": positions,
        }

    async def catalogue_view(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The pinned catalogue plus what a client would otherwise hold as literals.

        ``required_before_options`` is the vocabulary a position may wait for;
        ``resolvable`` says whether a phase of this project's governance model
        enables it, that is whether any gate can check it.
        """
        catalogue = await self.catalogue_for(await self.require_plan(project_id))
        body = catalogue.model_dump(mode="json")
        for kind in body["document_kinds"]:
            kind["takes_fit_flag"] = kind["code"] == HEALTH_KIND
        enabled = hosting.enabled_tags(await self._governance_catalogue(project_id))
        body["phases"] = list(PHASES)
        body["custom_role_code"] = CUSTOM_ROLE
        body["required_before_options"] = [
            {"tag": tag, "resolvable": tag in enabled} for tag in sorted(governance.phase_capabilities())
        ]
        return body

    async def plan_view(self, project_id: uuid.UUID, actor: Any = None) -> dict[str, Any]:
        """The plan header. Reading it catches up with a governance approval whose event never arrived."""
        plan = await self.require_plan(project_id)
        if plan.status == "in_review" and plan.governance_document_id is not None:
            await self.mirror_binding(project_id, plan.governance_document_id)
        who = _as_actor(actor)
        has_frame = await self._resolve_frame_document(project_id) is not None
        gates = await hosting.gates_in_use(self.session, project_id)
        four_eyes = await hosting.four_eyes(self.session, project_id)

        def plan_can(action: str) -> dict[str, Any]:
            state = {"has_frame_document": has_frame, "gates_in_use": gates}
            refused = rules.plan_action_refusal(action, plan.status, can_edit=who.edit, **state)
            by_state = rules.plan_action_refusal(action, plan.status, can_edit=True, **state)
            return _can(refused is None, refused, by_state)

        def approve_can() -> dict[str, Any]:
            asked = {"gates_in_use": gates, "four_eyes": four_eyes}
            mine = who.user_id is not None and plan.submitted_by == who.user_id
            refused = rules.plan_approval_refusal(plan.status, can_manage=who.manage, is_submitter=mine, **asked)
            by_state = rules.plan_approval_refusal(plan.status, can_manage=True, is_submitter=False, **asked)
            return _can(refused is None, refused, by_state)

        return {
            "id": str(plan.id),
            "project_id": str(project_id),
            "catalogue_source": plan.catalogue_source,
            "catalogue_id": plan.catalogue_id,
            "catalogue_version": plan.catalogue_version,
            "status": plan.status,
            "requires_accommodation": plan.requires_accommodation,
            "commissioning_date": _iso(plan.commissioning_date),
            "governance_document_id": _s(plan.governance_document_id),
            "submitted_by": _s(plan.submitted_by),
            "submitted_at": _iso(plan.submitted_at),
            "approved_by": _s(plan.approved_by),
            "approved_at": _iso(plan.approved_at),
            "approval_source": plan.approval_source,
            "has_bound_snapshot": bool(plan.bound_snapshot),
            "bound_snapshot": plan.bound_snapshot or None,
            # False on a project without gates: the plan is then approved by hand, and no gate is named.
            "gates_in_use": gates,
            "can": {
                "manage": _can(who.manage, "manage_permission_required"),
                "assign_owner": _can(await self._may_assign_owner(project_id, who), "owner_assignment_forbidden"),
                "submit": plan_can("submit"),
                "return": plan_can("return"),
                "approve": approve_can(),
                "change_catalogue": plan_can("change_catalogue"),
                # Add, edit and delete positions and handovers, the plan's settings, and who fills what.
                "edit": plan_can("edit"),
            },
        }

    async def _open_for_edit(self, project_id: uuid.UUID, actor_id: Any) -> StaffingPlan:
        """Rule 7: draft and revising edit freely; approved or binding opens a revision; in review is locked."""
        plan = await self.require_plan(project_id, lock=True)
        refused = rules.plan_action_refusal("edit", plan.status, can_edit=True)
        if refused:
            raise conflict(refused)
        if plan.status not in PLAN_EDITABLE:
            await self._fsm(PLAN_FSM, plan, "revising", actor_id)
            await self._audit(actor_id, "staffing_plan", plan.id, "revision_opened")
        return plan

    async def _not_in_review(self, project_id: uuid.UUID) -> StaffingPlan:
        """Who fills a position is read by the reviewer (rules 5 and 6), so fills stand still during review.

        Outside review a fill is day to day staffing, not plan structure: it opens no revision.
        """
        plan = await self.require_plan(project_id, lock=True)
        refused = rules.plan_action_refusal("edit", plan.status, can_edit=True)
        if refused:
            raise conflict(refused)
        return plan

    async def _resolve_frame_document(self, project_id: uuid.UUID) -> Any:
        """The governance document that carries the plan: the one whose type the catalogue tags for staffing."""
        host = hosting.host(await self._governance_catalogue(project_id))
        if host is None:
            return None
        # A project pinned before its model gained the document type has no row for it: also nothing.
        documents = await governance.project_documents(self.session, project_id)
        return next((d for d in documents if d.code == host.doc_type), None)

    async def submission_findings(self, project_id: uuid.UUID) -> list[rules.Finding]:
        plan = await self.require_plan(project_id)
        catalogue = await self.catalogue_for(plan)
        positions = [position_dict(p) for p in await self.repo.positions(project_id)]
        fills = [fill_dict(f) for f in await self.repo.fills(project_id)]
        handovers = [handover_dict(h) for h in await self.repo.handovers(project_id)]
        out = rules.submission_findings(catalogue, positions, fills, handovers, plan.commissioning_date)
        for p in await self.repo.positions(project_id):
            for code in rules.position_errors(p.fte, p.headcount, p.entry_date, p.exit_date):
                out.append(rules.Finding(code, str(p.id)))
        out += await self._overallocation_findings(project_id, fills)
        return out

    async def submit(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> StaffingPlan:
        """Rule 6: draft or revising -> in_review, only when the plan is complete and something can approve it."""
        plan = await self.require_plan(project_id, lock=True)
        doc = await self._resolve_frame_document(project_id)
        refused = rules.plan_action_refusal(
            "submit",
            plan.status,
            can_edit=True,
            has_frame_document=doc is not None,
            gates_in_use=await hosting.gates_in_use(self.session, project_id),
        )
        if refused:
            raise conflict(refused)
        await self._refuse_open_findings(project_id)
        await self._fsm(PLAN_FSM, plan, "in_review", actor_id)
        # Without gates no document carries the plan: it is approved by hand.
        plan.governance_document_id = doc.id if doc is not None else None
        plan.submitted_by, plan.submitted_at = actor_id, _now()
        await self.session.flush()
        await self._audit(actor_id, "staffing_plan", plan.id, "plan_submitted")
        self._publish("plan.submitted", {"project_id": str(project_id), "plan_id": str(plan.id)})
        return plan

    async def _refuse_open_findings(self, project_id: uuid.UUID) -> None:
        """Rule 6: an incomplete plan answers 422 with what is missing, at submission and at hand approval alike."""
        findings = [f for f in await self.submission_findings(project_id) if f.severity == rules.ERROR]
        if findings:
            raise StaffingError(findings[0].code, 422, violations=[f.as_dict() for f in findings])

    async def approve_by_hand(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> StaffingPlan:
        """In review -> binding on a project that has no gates to approve the plan.

        Never weaker than the gate: four-eyes holds, and the plan is refused on
        the findings a submission is refused on. The manage right is the route's.
        """
        plan = await self.require_plan(project_id, lock=True)
        refused = rules.plan_approval_refusal(
            plan.status,
            can_manage=True,
            gates_in_use=await hosting.gates_in_use(self.session, project_id),
            four_eyes=await hosting.four_eyes(self.session, project_id),
            is_submitter=plan.submitted_by == actor_id,
        )
        if refused == rules.APPROVER_IS_SUBMITTER:
            raise forbidden(refused)
        if refused:
            raise conflict(refused)
        await self._refuse_open_findings(project_id)
        await self._fsm(PLAN_FSM, plan, "approved", actor_id)
        await self._fsm(PLAN_FSM, plan, "binding", actor_id)
        plan.bound_snapshot = await self.snapshot(project_id)
        plan.approved_by, plan.approved_at, plan.approval_source = actor_id, _now(), "hand"
        plan.bound_revision_id = None
        await self.session.flush()
        await self._audit(actor_id, "staffing_plan", plan.id, "plan_bound", metadata={"source": "hand"})
        return plan

    async def return_plan(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> StaffingPlan:
        plan = await self.require_plan(project_id, lock=True)
        refused = rules.plan_action_refusal("return", plan.status, can_edit=True)
        if refused:
            raise conflict(refused)
        await self._fsm(PLAN_FSM, plan, "draft", actor_id)
        await self._audit(actor_id, "staffing_plan", plan.id, "plan_returned")
        return plan

    async def _approval_of(self, plan: StaffingPlan, doc: Any) -> tuple[Any, datetime, str] | None:
        """Who approved THIS submission, when and how; ``None`` while nobody has.

        The document stays binding between revisions, so its state proves nothing
        about the plan in review. Only a decision taken after the submission counts.
        """
        since = plan.submitted_at
        if since is None:
            return None
        requests = [
            cr
            for cr in await governance.project_change_requests(self.session, plan.project_id, doc.id)
            if cr.status == "approved" and cr.decided_at is not None and cr.decided_at >= since
        ]
        if requests:
            cr = max(requests, key=lambda r: r.decided_at)
            return cr.decided_by, cr.decided_at, "change_request"
        if doc.approved_gate_id is None:
            return None
        decisions = [
            d
            for d in await governance.project_gate_decisions(self.session, plan.project_id, doc.approved_gate_id)
            if d.outcome in _GO and d.decided_at >= since
        ]
        if decisions:
            decision = max(decisions, key=lambda d: d.decided_at)
            return decision.decided_by, decision.decided_at, "gate"
        return None

    async def mirror_binding(self, project_id: uuid.UUID | None, document_id: uuid.UUID) -> bool:
        """The frame document that carries the plan is binding: approve and freeze the submitted plan.

        Idempotent. Called by the governance event and again whenever the plan is read while in review.
        """
        changed = False
        for plan in await self.repo.plans_for_document(document_id):
            if project_id is not None and plan.project_id != project_id:
                continue
            if plan.status != "in_review":
                continue
            documents = await governance.project_documents(self.session, plan.project_id)
            doc = next((d for d in documents if d.id == document_id), None)
            if doc is None or doc.status != "binding":
                continue
            approval = await self._approval_of(plan, doc)
            if approval is None:
                continue
            approver, at, source = approval
            await self._fsm(PLAN_FSM, plan, "approved", approver)
            await self._fsm(PLAN_FSM, plan, "binding", approver)
            plan.bound_snapshot = await self.snapshot(plan.project_id)
            plan.approved_by, plan.approved_at, plan.approval_source = approver, at, source
            plan.bound_revision_id = doc.bound_revision_id
            await self.session.flush()
            await self._audit(approver, "staffing_plan", plan.id, "plan_bound", metadata={"source": source})
            changed = True
        return changed

    async def snapshot(self, project_id: uuid.UUID) -> dict[str, Any]:
        """JSON-safe frozen positions and fills (names excluded: the snapshot outlives anonymisation)."""
        fills = await self.repo.fills(project_id)
        return {
            "taken_at": _now().isoformat(),
            "positions": [
                {k: _json_safe(v) for k, v in position_dict(p).items()}
                | {"organisation": p.organisation, "title": p.title, "custom_label": p.custom_label}
                for p in await self.repo.positions(project_id)
            ],
            "fills": [
                {
                    "position_id": str(f.position_id),
                    "fte_share": str(f.fte_share),
                    "from_date": _iso(f.from_date),
                    "to_date": _iso(f.to_date),
                    "status": f.status,
                }
                for f in fills
            ],
        }

    # ── positions ──────────────────────────────────────────────────────────

    def _check_position(self, catalogue: StaffingModelCatalogue, values: dict[str, Any]) -> None:
        code = values["role_code"]
        role = catalogue.role(code)
        if code == CUSTOM_ROLE:
            if not values.get("custom_label") or not values.get("organisation"):
                raise StaffingError("custom_role_needs_label", 422)
        elif role is None:
            raise StaffingError("role_unknown", 422)
        elif values["phase"] not in role.phases:
            raise StaffingError("phase_not_for_role", 422)
        org = values.get("organisation")
        if org not in {o.code for o in catalogue.organisations}:
            raise StaffingError("organisation_unknown", 422)
        try:
            values["fte"] = rules.dec(values["fte"])
        except ValueError as exc:
            raise StaffingError("fte_out_of_range", 422) from exc
        errors = rules.position_errors(
            values["fte"], values["headcount"], values.get("entry_date"), values.get("exit_date")
        )
        if errors:
            raise StaffingError(errors[0], 422, violations=[{"code": e, "ref": code} for e in errors])

    def _gate_defaults(self, role: Any, phase: str) -> dict[str, Any]:
        """What the catalogue says a gate reads of a position of this role."""
        tag = role.required_before if role is not None and phase != "operation" else None
        return {
            "key_role": bool(role and role.key_role),
            "handover_role": bool(role and role.handover_role),
            "required_before": tag,
        }

    async def create_position(self, project_id: uuid.UUID, data: dict[str, Any], actor: Any) -> StaffingPosition:
        who = _as_actor(actor)
        plan = await self._open_for_edit(project_id, who.user_id)
        catalogue = await self.catalogue_for(plan)
        role = catalogue.role(data["role_code"])
        values = {k: v for k, v in data.items() if v is not None and k in _POSITION_FIELDS}
        values.setdefault("organisation", role.organisation if role else None)
        values.setdefault("fte", role.default_fte if role else "1")
        values.setdefault("headcount", 1)
        defaults = self._gate_defaults(role, data["phase"])
        for key, default in defaults.items():
            if default is not None:
                values.setdefault(key, default)
        # Planning a key role as an ordinary one is the same change as switching the flag off later.
        if not who.manage and any(values.get(k) != default for k, default in defaults.items()):
            raise forbidden("manage_permission_required")
        if values.get("owner_user_id") is not None:
            await self._check_owner(project_id, who, values["owner_user_id"])
        self._check_position(catalogue, values)
        row = await self.repo.add(StaffingPosition(project_id=project_id, plan_id=plan.id, status="open", **values))
        await self._audit(
            who.user_id,
            "staffing_position",
            row.id,
            "position_created",
            metadata={"role": row.role_code, "owner_user_id": _s(row.owner_user_id)},
        )
        return row

    async def positions_from_catalogue(
        self,
        project_id: uuid.UUID,
        phase: str,
        role_codes: list[str] | None,
        entry_date: date | None,
        actor_id: Any,
    ) -> list[StaffingPosition]:
        """One position per catalogue role of ``phase`` (or the listed roles), skipping roles already planned."""
        plan = await self.require_plan(project_id)
        catalogue = await self.catalogue_for(plan)
        existing = {(p.role_code, p.phase) for p in await self.repo.positions(project_id) if p.status != "cancelled"}
        unknown = [c for c in role_codes or [] if catalogue.role(c) is None]
        if unknown:
            raise StaffingError("role_unknown", 422, violations=[{"code": "role_unknown", "ref": c} for c in unknown])
        out = []
        for role in catalogue.roles:
            if phase not in role.phases or (role_codes and role.code not in role_codes):
                continue
            if (role.code, phase) in existing:
                continue
            out.append(
                await self.create_position(
                    project_id, {"role_code": role.code, "phase": phase, "entry_date": entry_date}, actor_id
                )
            )
        return out

    async def update_position(
        self, project_id: uuid.UUID, position_id: uuid.UUID, changes: dict[str, Any], actor: Any
    ) -> StaffingPosition:
        who = _as_actor(actor)
        row = await self._child(StaffingPosition, project_id, position_id, "position_not_found", lock=True)
        changes = dict(changes)
        status = changes.pop("status", None)
        if status == "filled":
            raise StaffingError("status_is_derived", 422)
        _refuse_nulls(changes, _POSITION_NULLABLE)
        plan = await self._open_for_edit(project_id, who.user_id)
        catalogue = await self.catalogue_for(plan)
        values = {k: getattr(row, k) for k in _POSITION_FIELDS}
        values.update({k: v for k, v in changes.items() if k in _POSITION_FIELDS})
        if any(values[k] != getattr(row, k) for k in _GATE_FIELDS):
            allowed, reason = rules.gate_fields_access(row.status, can_manage=who.manage)
            if not allowed:
                raise _refusal(reason)
        owner_changed = values["owner_user_id"] != row.owner_user_id
        if owner_changed:
            await self._check_owner(project_id, who, values["owner_user_id"])
        self._check_position(catalogue, values)
        previous_owner = row.owner_user_id
        for k in _POSITION_FIELDS:
            setattr(row, k, values[k])
        if status is not None:
            await self.set_position_status(project_id, position_id, status, who.user_id)
        await self.session.flush()
        await self._audit(who.user_id, "staffing_position", row.id, "position_updated")
        if owner_changed:
            # Who is related to the people on this position changed: its own audit line.
            await self._audit(
                who.user_id,
                "staffing_position",
                row.id,
                "position_owner_changed",
                metadata={"from": _s(previous_owner), "to": _s(row.owner_user_id)},
            )
        return row

    async def set_position_status(self, project_id: uuid.UUID, position_id: uuid.UUID, status: str, actor_id: Any):
        """Rule 2: ``filled`` cannot be set; it is what confirmed fills make of an open position."""
        if status == "filled":
            raise StaffingError("status_is_derived", 422)
        actor_id = _uid(actor_id)
        row = await self._child(StaffingPosition, project_id, position_id, "position_not_found", lock=True)
        plan = await self.require_plan(project_id, lock=True)
        refused = rules.position_status_refusal(
            row.status,
            status,
            plan.status,
            can_edit=True,
            transition_exists=POSITION_FSM.has_transition(row.status, status),
        )
        if refused:
            raise conflict(refused)
        await self._open_for_edit(project_id, actor_id)
        previous = row.status
        await self._fsm(POSITION_FSM, row, status, actor_id)
        await self.session.flush()
        self._publish(
            "position.status_changed",
            {"project_id": str(project_id), "position_id": str(row.id), "from": previous, "to": status},
        )
        return row

    async def request_resource(self, project_id: uuid.UUID, position_id: uuid.UUID, actor: Any) -> StaffingPosition:
        """A recruiting position opens one request in the resources module and keeps its id (SPEC section 8).

        The id is set here and nowhere else; a client cannot point a position at somebody else's request.
        """
        from app.modules.resources.schemas import ResourceRequestCreate
        from app.modules.resources.service import ResourcesService

        actor_id = _uid(actor)
        row = await self._child(StaffingPosition, project_id, position_id, "position_not_found", lock=True)
        refused = self._resource_request_refusal(row, can_edit=True)
        if refused:
            raise StaffingError(refused, 422 if refused == "position_dates_required" else 409)
        catalogue = await self.catalogue_for(await self.require_plan(project_id))
        title = row.title or row.custom_label or label_of(catalogue.role(row.role_code), "en", row.role_code)
        request = await ResourcesService(self.session).request_resource(
            ResourceRequestCreate(
                project_id=project_id,
                title=title,
                description=row.notes,
                start_at=datetime.combine(row.entry_date, time.min, tzinfo=UTC),
                end_at=datetime.combine(row.exit_date, time.max, tzinfo=UTC),
                quantity=row.headcount,
            ),
            user_id=_s(actor_id),
        )
        row.resource_request_id = request.id
        await self.session.flush()
        await self._audit(
            actor_id, "staffing_position", row.id, "resource_requested", metadata={"request_id": str(request.id)}
        )
        return row

    @staticmethod
    def _resource_request_refusal(row: StaffingPosition, *, can_edit: bool) -> str | None:
        return rules.resource_request_refusal(
            row.status,
            has_request=row.resource_request_id is not None,
            entry_date=row.entry_date,
            exit_date=row.exit_date,
            can_edit=can_edit,
        )

    async def delete_position(self, project_id: uuid.UUID, position_id: uuid.UUID, actor_id: Any) -> None:
        actor_id = _uid(actor_id)
        row = await self._child(StaffingPosition, project_id, position_id, "position_not_found", lock=True)
        await self._open_for_edit(project_id, actor_id)
        if await self.repo.fills(project_id, position_id=row.id):
            raise conflict("position_has_fills")
        await self.repo.delete(row)
        await self._audit(actor_id, "staffing_position", position_id, "position_deleted")

    async def position_views(self, project_id: uuid.UUID, actor: Any = None) -> list[dict[str, Any]]:
        """Plan rows: role, organisation, phase, FTE, dates, effective status, and per fill name + cleared flag."""
        who = _as_actor(actor)
        positions = await self.repo.positions(project_id)
        fills = await self.repo.fills(project_id)
        members = await self._members(project_id, [f.roster_member_id for f in fills])
        cleared = await self.cleared_map(project_id)
        fill_dicts = [fill_dict(f) for f in fills]
        plan = await self.get_plan(project_id)
        plan_status = plan.status if plan is not None else "draft"
        may_assign = await self._may_assign_owner(project_id, who)

        def fill_can(f: PositionFill, p: StaffingPosition) -> dict[str, Any]:
            def one(action: str) -> dict[str, Any]:
                def refusal(*, can_edit: bool, own: bool) -> str | None:
                    return rules.fill_action_refusal(
                        action,
                        f.status,
                        plan_status,
                        can_edit=can_edit,
                        anonymised=f.roster_member_id is None,
                        confirms_own_position=own,
                    )

                refused = refusal(can_edit=who.edit, own=self._confirms_own_position(p, who, may_assign))
                return _can(refused is None, refused, refusal(can_edit=True, own=False))

            return {"confirm": one("confirm"), "end": one("end"), "delete": one("delete")}

        def status_can(p: StaffingPosition) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for target in POSITION_SETTABLE:
                exists = POSITION_FSM.has_transition(p.status, target)
                refused, by_state = (
                    rules.position_status_refusal(
                        p.status, target, plan_status, can_edit=can_edit, transition_exists=exists
                    )
                    for can_edit in (who.edit, True)
                )
                out[target] = _can(refused is None, refused, by_state)
            return out

        out = []
        for p in positions:
            own = [f for f in fills if f.position_id == p.id]
            request_refused = self._resource_request_refusal(p, can_edit=who.edit)
            out.append(
                {
                    "id": str(p.id),
                    "role_code": p.role_code,
                    "custom_label": p.custom_label,
                    "organisation": p.organisation,
                    "phase": p.phase,
                    "title": p.title,
                    "fte": str(p.fte),
                    "headcount": p.headcount,
                    "entry_date": _iso(p.entry_date),
                    "exit_date": _iso(p.exit_date),
                    "required_before": p.required_before,
                    "key_role": p.key_role,
                    "handover_role": p.handover_role,
                    "status": rules.effective_position_status(position_dict(p), fill_dicts),
                    "stored_status": p.status,
                    "recruiting_channel": p.recruiting_channel,
                    "owner_user_id": _s(p.owner_user_id),
                    "resource_request_id": _s(p.resource_request_id),
                    "contract_id": _s(p.contract_id),
                    "rfq_id": _s(p.rfq_id),
                    "notes": p.notes,
                    "covered_fte": str(rules.covered_fte([fill_dict(f) for f in own], p.entry_date)),
                    "fills": [self._fill_view(f, members, cleared) | {"can": fill_can(f, p)} for f in own],
                    "can": {
                        "gate_fields": _can(*rules.gate_fields_access(p.status, can_manage=who.manage)),
                        "status": status_can(p),
                        "request_resource": _can(
                            request_refused is None, request_refused, self._resource_request_refusal(p, can_edit=True)
                        ),
                    },
                }
            )
        return out

    @staticmethod
    def _confirms_own_position(position: StaffingPosition, who: Actor, may_assign: bool) -> bool:
        """Four eyes on a confirmation: the line manager of the position, unless they may name line managers anyway."""
        return who.user_id is not None and position.owner_user_id == who.user_id and not may_assign

    def _fill_view(self, f: PositionFill, members: dict, cleared: dict) -> dict[str, Any]:
        member = members.get(f.roster_member_id)
        return {
            "id": str(f.id),
            "position_id": str(f.position_id),
            "roster_member_id": _s(f.roster_member_id),
            "name": member.display_name if member is not None else None,
            "fte_share": str(f.fte_share),
            "from_date": _iso(f.from_date),
            "to_date": _iso(f.to_date),
            "status": f.status,
            "cleared_to_work": cleared.get(f.roster_member_id),
        }

    # ── fills (rules 3, 4) ─────────────────────────────────────────────────

    async def create_fill(
        self, project_id: uuid.UUID, position_id: uuid.UUID, data: dict[str, Any], actor_id: Any
    ) -> PositionFill:
        actor_id = _uid(actor_id)
        await self._not_in_review(project_id)
        position = await self._child(StaffingPosition, project_id, position_id, "position_not_found")
        await self._roster_member(project_id, data["roster_member_id"])
        error = rules.fill_share_error(data.get("fte_share", "1"), data["from_date"], data.get("to_date"))
        if error:
            raise StaffingError(error, 422)
        row = await self.repo.add(
            PositionFill(
                project_id=project_id,
                position_id=position.id,
                roster_member_id=data["roster_member_id"],
                fte_share=rules.dec(data.get("fte_share", "1")),
                from_date=data["from_date"],
                to_date=data.get("to_date"),
                status="proposed",
            )
        )
        await self._audit(actor_id, "staffing_fill", row.id, "fill_proposed")
        return row

    async def _overallocation_findings(self, project_id: uuid.UUID, fills: list[dict[str, Any]]) -> list[rules.Finding]:
        by_person: dict[Any, list[dict[str, Any]]] = {}
        for f in fills:
            if f["roster_member_id"] is not None:
                by_person.setdefault(f["roster_member_id"], []).append(f)
        out = []
        for member_id, own in by_person.items():
            hit = rules.first_overallocated_day(own)
            if hit is not None:
                out.append(rules.Finding("person_overallocated", str(member_id), rules.ERROR, hit[0].isoformat()))
        return out

    async def _cross_project_warning(self, member: Any, fill: PositionFill) -> dict[str, Any] | None:
        """Rule 4, across projects: a warning from ``resources.Assignment`` of the person's linked resource."""
        if getattr(member, "resource_id", None) is None:
            return None
        from app.modules.resources.models import Assignment

        start = datetime.combine(fill.from_date, datetime.min.time(), tzinfo=UTC)
        stmt = select(func.coalesce(func.sum(Assignment.allocation_percent), 0)).where(
            Assignment.resource_id == member.resource_id,
            Assignment.project_id != fill.project_id,
            Assignment.start_at <= start + timedelta(days=1),
            Assignment.end_at >= start,
        )
        other = int((await self.session.execute(stmt)).scalar() or 0)
        total = Decimal(other) / Decimal(100) + Decimal(fill.fte_share)
        if total > rules.ONE:
            return {"code": "person_overallocated_across_projects", "severity": "warning", "total_fte": str(total)}
        return None

    async def confirm_fill(self, project_id: uuid.UUID, fill_id: uuid.UUID, actor: Any) -> tuple[PositionFill, list]:
        """Rule 4 under a row lock on the person, so two concurrent confirms cannot both pass.

        A confirmed fill is what relates the position's line manager to the person
        (rule 13), so that manager does not confirm it themself.
        """
        who = _as_actor(actor)
        plan = await self._not_in_review(project_id)
        fill = await self._child(PositionFill, project_id, fill_id, "fill_not_found", lock=True)
        position = await self._child(StaffingPosition, project_id, fill.position_id, "position_not_found")
        refused = rules.fill_action_refusal(
            "confirm",
            fill.status,
            plan.status,
            can_edit=True,
            anonymised=fill.roster_member_id is None,
            confirms_own_position=self._confirms_own_position(
                position, who, await self._may_assign_owner(project_id, who)
            ),
        )
        if refused == "owner_cannot_confirm_own_fill":
            raise forbidden(refused)
        if refused:
            raise conflict(refused)
        member = await self._roster_member(project_id, fill.roster_member_id, lock=True)
        mine = await self.repo.fills(project_id, roster_member_id=fill.roster_member_id)
        others = [fill_dict(f) for f in mine if f.id != fill.id]
        candidate = {**fill_dict(fill), "status": "confirmed"}
        hit = rules.first_overallocated_day([*others, candidate])
        if hit is not None:
            raise StaffingError(
                "person_overallocated",
                422,
                violations=[{"code": "person_overallocated", "ref": hit[0].isoformat(), "total_fte": str(hit[1])}],
            )
        await self._fsm(FILL_FSM, fill, "confirmed", who.user_id)
        await self.session.flush()
        warnings = []
        cross = await self._cross_project_warning(member, fill)
        if cross:
            warnings.append(cross)
        cleared = (await self.cleared_map(project_id)).get(fill.roster_member_id)
        if cleared is False:
            warnings.append({"code": "not_cleared_to_work", "severity": "error"})
            self._publish(
                "person.not_cleared",
                {"project_id": str(project_id), "roster_member_id": str(fill.roster_member_id)},
            )
        # Rule 18: on a remote site the person needs a bed on their first day.
        first_day = min(f.from_date for f in mine if f.status == "confirmed")
        bed = rules.accommodation_finding(
            plan.requires_accommodation,
            first_day,
            await self.bookings_for(project_id, fill.roster_member_id),
            str(fill.roster_member_id),
        )
        if bed is not None:
            warnings.append(bed.as_dict())
        await self._audit(who.user_id, "staffing_fill", fill.id, "fill_confirmed")
        self._publish(
            "fill.confirmed",
            {"project_id": str(project_id), "fill_id": str(fill.id), "position_id": str(fill.position_id)},
        )
        return fill, warnings

    async def end_fill(self, project_id: uuid.UUID, fill_id: uuid.UUID, actor_id: Any) -> PositionFill:
        """End a confirmed fill today (the server's day; a fill that never began ends on its first day)."""
        actor_id = _uid(actor_id)
        plan = await self._not_in_review(project_id)
        fill = await self._child(PositionFill, project_id, fill_id, "fill_not_found", lock=True)
        refused = rules.fill_action_refusal("end", fill.status, plan.status, can_edit=True)
        if refused:
            raise conflict(refused)
        end = rules.fill_end_date(fill.from_date, _today(), fill.to_date)
        await self._fsm(FILL_FSM, fill, "ended", actor_id)
        fill.to_date = end
        await self.session.flush()
        await self._audit(actor_id, "staffing_fill", fill.id, "fill_ended", metadata={"to_date": end.isoformat()})
        self._publish("fill.ended", {"project_id": str(project_id), "fill_id": str(fill.id)})
        return fill

    async def delete_fill(self, project_id: uuid.UUID, fill_id: uuid.UUID, actor_id: Any) -> None:
        plan = await self._not_in_review(project_id)
        fill = await self._child(PositionFill, project_id, fill_id, "fill_not_found", lock=True)
        refused = rules.fill_action_refusal("delete", fill.status, plan.status, can_edit=True)
        if refused:
            raise conflict(refused)
        await self.repo.delete(fill)
        await self._audit(_uid(actor_id), "staffing_fill", fill_id, "fill_deleted")

    # ── handovers ──────────────────────────────────────────────────────────

    async def create_handover(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> HandoverLink:
        actor_id = _uid(actor_id)
        await self._open_for_edit(project_id, actor_id)
        fill = await self._child(PositionFill, project_id, data["from_fill_id"], "fill_not_found")
        await self._child(StaffingPosition, project_id, data["to_position_id"], "position_not_found")
        # Rule 6 asks for knowledge to move between positions; a link back to the giver's own moves nothing.
        if fill.position_id == data["to_position_id"]:
            raise StaffingError("handover_same_position", 422)
        row = await self.repo.add(HandoverLink(project_id=project_id, status="planned", **data))
        await self._audit(actor_id, "staffing_handover", row.id, "handover_created")
        return row

    async def update_handover(
        self, project_id: uuid.UUID, handover_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ) -> HandoverLink:
        actor_id = _uid(actor_id)
        _refuse_nulls(changes)
        await self._open_for_edit(project_id, actor_id)
        row = await self._child(HandoverLink, project_id, handover_id, "handover_not_found", lock=True)
        for k, v in changes.items():
            setattr(row, k, v)
        await self.session.flush()
        await self._audit(actor_id, "staffing_handover", row.id, "handover_updated")
        return row

    async def delete_handover(self, project_id: uuid.UUID, handover_id: uuid.UUID, actor_id: Any) -> None:
        actor_id = _uid(actor_id)
        await self._open_for_edit(project_id, actor_id)
        row = await self._child(HandoverLink, project_id, handover_id, "handover_not_found")
        await self.repo.delete(row)
        await self._audit(actor_id, "staffing_handover", handover_id, "handover_deleted")

    async def handover_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        return [
            {
                "id": str(h.id),
                "from_fill_id": str(h.from_fill_id),
                "to_position_id": str(h.to_position_id),
                "overlap_days": h.overlap_days,
                "scope": h.scope,
                "status": h.status,
            }
            for h in await self.repo.handovers(project_id)
        ]

    # ── org chart ──────────────────────────────────────────────────────────

    async def org_chart(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Per phase, per organisation: positions with their people and vacancies."""
        views = await self.position_views(project_id)
        phases: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for v in views:
            if v["status"] == "cancelled":
                continue
            people = [
                {"name": f["name"], "fte_share": f["fte_share"], "status": f["status"]}
                for f in v["fills"]
                if f["status"] != "ended"
            ]
            phases.setdefault(v["phase"], {}).setdefault(v["organisation"], []).append(
                {
                    "position_id": v["id"],
                    "role_code": v["role_code"],
                    "custom_label": v["custom_label"],
                    "title": v["title"],
                    "key_role": v["key_role"],
                    "vacant": v["status"] != "filled",
                    "people": people,
                }
            )
        return {
            "phases": [
                {"phase": ph, "organisations": [{"organisation": o, "positions": ps} for o, ps in orgs.items()]}
                for ph, orgs in phases.items()
            ]
        }

    # ── documents, clearance, compliance (rules 8, 9) ──────────────────────

    async def _credentials(self, project_id: uuid.UUID, ids: Iterable[Any]) -> dict[uuid.UUID, Any]:
        from app.modules.credentials.models import Credential

        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        stmt = select(Credential).where(Credential.project_id == project_id, Credential.id.in_(wanted))
        return {c.id: c for c in (await self.session.execute(stmt)).scalars()}

    def _status_on(self, credential: Any, day: date) -> str:
        """Rule 9: the credentials module's own derivation, asked about ``day``."""
        from app.modules.credentials.service import CredentialService

        return CredentialService(self.session).effective_status(credential, today=day)

    async def people(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Each person with a non-ended fill: roles, first start, requirements, documents and clearance."""
        plan = await self.require_plan(project_id)
        catalogue = await self.catalogue_for(plan)
        positions = {p.id: p for p in await self.repo.positions(project_id)}
        fills = [f for f in await self.repo.fills(project_id) if f.status != "ended" and f.roster_member_id]
        files = {f.roster_member_id: f for f in await self.repo.files(project_id) if f.roster_member_id}
        docs = await self.repo.documents(project_id)
        creds = await self._credentials(project_id, [d.credential_id for d in docs])
        members = await self._members(project_id, [f.roster_member_id for f in fills])
        out: list[dict[str, Any]] = []
        for member_id in dict.fromkeys(f.roster_member_id for f in fills):
            own = [f for f in fills if f.roster_member_id == member_id]
            confirmed = [f for f in own if f.status == "confirmed"]
            pfile = files.get(member_id)
            roles = [positions[f.position_id].role_code for f in own if f.position_id in positions]
            required = rules.required_document_kinds(
                catalogue,
                roles,
                pfile.employment_basis if pfile else "employee",
                bool(pfile and pfile.nationality_required),
            )
            start = min((f.from_date for f in confirmed), default=None) or min(f.from_date for f in own)
            day = max(start, _today())
            documents: dict[str, dict[str, Any]] = {}
            for d in docs:
                if pfile is None or d.personnel_file_id != pfile.id:
                    continue
                cred = creds.get(d.credential_id)
                documents[d.document_kind] = {
                    "status_on_start": self._status_on(cred, day) if cred is not None else None,
                    "status": self._status_on(cred, _today()) if cred is not None else None,
                    "valid_until": cred.valid_until if cred is not None else None,
                    "waived": d.waived,
                }
            clearance = rules.clearance(required, documents)
            member = members.get(member_id)
            out.append(
                {
                    "roster_member_id": member_id,
                    "name": member.display_name if member is not None else None,
                    "user_id": getattr(member, "user_id", None),
                    "file_id": pfile.id if pfile else None,
                    "file_status": pfile.status if pfile else None,
                    "roles": roles,
                    "position_ids": [f.position_id for f in own],
                    "start": start,
                    "end": max((f.to_date for f in own if f.to_date), default=None),
                    "confirmed": bool(confirmed),
                    "required": required,
                    "documents": documents,
                    **clearance,
                }
            )
        return out

    async def cleared_map(self, project_id: uuid.UUID) -> dict[Any, bool]:
        if await self.repo.plan(project_id) is None:
            return {}
        return {p["roster_member_id"]: p["cleared"] for p in await self.people(project_id)}

    async def compliance_matrix(self, project_id: uuid.UUID, actor: Any = None) -> dict[str, Any]:
        """People x document kinds, cell = valid / expiring / expired / missing / waived / not_required. Status only.

        Which document a person lacks is personal data of that person, and for
        the health certificate data of a special category. A row therefore
        carries cells only for a caller who may open that person's file (rule
        13, the same decision as the file itself). Everybody else gets the
        person's name, roles and cleared flag, which the plan shows anyway, and
        ``summary``: counts per document kind over the people whose rows are
        withheld, only for groups too large to name anybody, and never for a
        kind of a special category. A call without an actor sees no cell.
        """
        who = _as_actor(actor)
        plan = await self.require_plan(project_id)
        catalogue = await self.catalogue_for(plan)
        people = await self.people(project_id)
        today = _today()
        kinds = [d.code for d in catalogue.document_kinds if any(d.code in p["required"] for p in people)]
        files = {f.id: f for f in await self.repo.files(project_id)}
        rows = []
        shown: set[str] = set()
        withheld: list[dict[str, Any]] = []
        for p in people:
            pfile = files.get(p["file_id"]) or PersonnelFile(
                project_id=project_id, roster_member_id=p["roster_member_id"]
            )
            allowed, reason, _relation = await self.file_access(project_id, pfile, who, edit=False)
            cells: dict[str, dict[str, Any]] = {}
            if allowed:
                cells = {k: rules.compliance_cell(k in p["required"], p["documents"].get(k), today) for k in kinds}
                shown |= set(cells)
            else:
                withheld.append(p)
            rows.append(
                {
                    "roster_member_id": str(p["roster_member_id"]),
                    "name": p["name"],
                    "roles": p["roles"],
                    "file_id": _s(p["file_id"]) if allowed else None,
                    "cleared_to_work": p["cleared"],
                    "cells": cells,
                    "can": {"see_documents": _can(allowed, reason)},
                }
            )
        special = [d.code for d in catalogue.document_kinds if d.special_category]
        return {
            "document_kinds": [k for k in kinds if k in shown],
            "items": rows,
            "total": len(rows),
            "summary": rules.compliance_summary(withheld, kinds, special, today),
            "summary_min_group": rules.SUMMARY_MIN_GROUP,
        }

    # ── personnel files: access (rule 13) ──────────────────────────────────

    async def _area_people(self, project_id: uuid.UUID, *, deputy: bool = True) -> set[uuid.UUID]:
        """Owner (and deputy) of the governance area that hosts staffing; nobody when the catalogue tags none."""
        host = hosting.host(await self._governance_catalogue(project_id))
        if host is None:
            return set()
        out: set[uuid.UUID] = set()
        for area in await governance.project_areas(self.session, project_id):
            if area.code == host.area_code:
                people = (area.owner_user_id, area.deputy_user_id) if deputy else (area.owner_user_id,)
                out |= {u for u in people if u is not None}
        return out

    async def _position_owners_of(self, project_id: uuid.UUID, roster_member_id: uuid.UUID | None) -> set[uuid.UUID]:
        """Line managers of the person: the owners of the positions they are confirmed on.

        A proposed fill relates nobody: anyone with the plan permission can propose one.
        Once no assignment runs, the managers of the ended ones remain, so that
        somebody can still close the file.
        """
        if roster_member_id is None:
            return set()
        stmt = (
            select(StaffingPosition.owner_user_id, PositionFill.status)
            .join(PositionFill, PositionFill.position_id == StaffingPosition.id)
            .where(
                PositionFill.project_id == project_id,
                PositionFill.roster_member_id == roster_member_id,
                PositionFill.status.in_(("confirmed", "ended")),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        running = any(status == "confirmed" for _owner, status in rows)
        return {owner for owner, status in rows if owner is not None and (status == "confirmed" or not running)}

    async def _relationship(
        self, project_id: uuid.UUID, roster_member_id: uuid.UUID | None, actor: Actor
    ) -> str | None:
        """``self``, ``area_owner``, ``position_owner`` or None."""
        if actor.user_id is None:
            return None
        if roster_member_id is not None:
            member = (await self._members(project_id, [roster_member_id])).get(roster_member_id)
            if member is not None and member.user_id == actor.user_id:
                return "self"
        if actor.user_id in await self._area_people(project_id):
            return "area_owner"
        if actor.user_id in await self._position_owners_of(project_id, roster_member_id):
            return "position_owner"
        return None

    async def _may_assign_owner(self, project_id: uuid.UUID, actor: Actor) -> bool:
        """Naming a line manager decides who may open a person's file, so it sits above the personnel tier:
        the assignment permission, or the owner of the hosting area who also holds personnel edit."""
        if actor.assign_owner:
            return True
        if actor.user_id is None or not actor.personnel_edit:
            return False
        return actor.user_id in await self._area_people(project_id)

    async def _check_owner(self, project_id: uuid.UUID, actor: Actor, owner_id: uuid.UUID | None) -> None:
        if not await self._may_assign_owner(project_id, actor):
            raise forbidden("owner_assignment_forbidden")
        if owner_id is not None and not await governance.user_can_access_project(self.session, project_id, owner_id):
            raise StaffingError("owner_not_project_member", 422)

    async def file_access(
        self, project_id: uuid.UUID, pfile: PersonnelFile, actor: Actor, *, edit: bool
    ) -> tuple[bool, str | None, str | None]:
        """``(allowed, reason, relation)``: the one decision behind every personnel route and ``can`` flag."""
        relation = await self._relationship(project_id, pfile.roster_member_id, actor)
        allowed, reason = rules.file_access(
            relation, can_read=actor.personnel_read, can_edit=actor.personnel_edit, edit=edit
        )
        return allowed, reason, relation

    async def open_file(
        self, project_id: uuid.UUID, file_id: uuid.UUID, actor: Actor, *, edit: bool = False, lock: bool = False
    ) -> PersonnelFile:
        """Load a file the actor may open; every successful read writes ``personnel_file.read``."""
        pfile = await self._child(PersonnelFile, project_id, file_id, "file_not_found", lock=lock)
        allowed, reason, relation = await self.file_access(project_id, pfile, actor, edit=edit)
        if not allowed:
            raise _refusal(reason)
        if not edit:
            await self._audit(
                actor.user_id,
                "staffing_personnel_file",
                pfile.id,
                "personnel_file.read",
                metadata={"relation": relation},
            )
        return pfile

    async def can_open(self, project_id: uuid.UUID, pfile: PersonnelFile, actor: Actor) -> bool:
        return (await self.file_access(project_id, pfile, actor, edit=False))[0]

    async def require_own_file(self, project_id: uuid.UUID, pfile: PersonnelFile, actor: Actor) -> None:
        """The export of a file goes to the person it is about and to nobody else (rule 20)."""
        if await self._relationship(project_id, pfile.roster_member_id, actor) != "self":
            raise forbidden("own_file_only")

    # ── personnel files: lifecycle ─────────────────────────────────────────

    async def create_file(self, project_id: uuid.UUID, data: dict[str, Any], actor: Actor) -> PersonnelFile:
        await self.require_plan(project_id)
        await self._roster_member(project_id, data["roster_member_id"])
        row = PersonnelFile(project_id=project_id, status="active", activity_counts={}, **data)
        allowed, reason, _relation = await self.file_access(project_id, row, actor, edit=True)
        if not allowed:
            raise _refusal(reason)
        if await self.repo.file_for_member(project_id, data["roster_member_id"]) is not None:
            raise conflict("file_exists")
        await self._insert(row, "file_exists")
        await self._audit(actor.user_id, "staffing_personnel_file", row.id, "file_created")
        return row

    async def update_file(
        self, project_id: uuid.UUID, file_id: uuid.UUID, changes: dict[str, Any], actor: Actor
    ) -> PersonnelFile:
        _refuse_nulls(changes)
        pfile = await self.open_file(project_id, file_id, actor, edit=True, lock=True)
        if pfile.status == "anonymised":
            raise conflict("file_anonymised")
        for k, v in changes.items():
            setattr(pfile, k, v)
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_personnel_file", pfile.id, "file_updated")
        return pfile

    async def _file_docs_for_retention(self, project_id: uuid.UUID, pfile: PersonnelFile) -> list[dict[str, Any]]:
        docs = await self.repo.documents(project_id, pfile.id)
        creds = await self._credentials(project_id, [d.credential_id for d in docs])
        return [
            {
                "document_kind": d.document_kind,
                "valid_until": getattr(creds.get(d.credential_id), "valid_until", None),
            }
            for d in docs
        ]

    async def _assignment_start(self, project_id: uuid.UUID, roster_member_id: uuid.UUID | None) -> date | None:
        if roster_member_id is None:
            return None
        fills = await self.repo.fills(project_id, roster_member_id=roster_member_id)
        return min((f.from_date for f in fills), default=None)

    async def _retention(self, project_id: uuid.UUID, pfile: PersonnelFile, today: date) -> dict[str, Any]:
        """What the file's retention rules say now: the due date, whether a legal duty still runs, the action."""
        catalogue = await self.catalogue_for(await self.require_plan(project_id))
        docs = await self._file_docs_for_retention(project_id, pfile)
        start = await self._assignment_start(project_id, pfile.roster_member_id)
        running, until = rules.legal_obligation_running(
            catalogue, docs, assignment_start=start, assignment_end=pfile.ended_on, today=today
        )
        return {
            "due": rules.retention_due(catalogue, docs, assignment_start=start, assignment_end=pfile.ended_on),
            "duty_running": running,
            "duty_until": until,
            "action": rules.retention_action(catalogue, docs),
        }

    async def end_file(self, project_id: uuid.UUID, file_id: uuid.UUID, actor: Actor) -> PersonnelFile:
        """Rule 14: the assignment ends today; ``retention_due_at`` is the latest end of the documents' rules.

        The day is the server's. A date from the client would let the caller place
        the retention end in the past, which is erasure without the erase permission.
        """
        pfile = await self.open_file(project_id, file_id, actor, edit=True, lock=True)
        refused = rules.file_transition_refusal("end", pfile.status)
        if refused:
            raise _refusal(refused)
        await self._fsm(FILE_FSM, pfile, "ended", actor.user_id)
        pfile.ended_on = _today()
        pfile.retention_due_at = (await self._retention(project_id, pfile, pfile.ended_on))["due"]
        await self.session.flush()
        await self._audit(
            actor.user_id,
            "staffing_personnel_file",
            pfile.id,
            "file_ended",
            metadata={"retention_due_at": _iso(pfile.retention_due_at)},
        )
        return pfile

    async def hold_file(self, project_id: uuid.UUID, file_id: uuid.UUID, rationale: str, actor: Actor):
        """A legal hold stops the retention end of an ended file; a running assignment has nothing to hold."""
        pfile = await self.open_file(project_id, file_id, actor, edit=True, lock=True)
        if not rationale.strip():
            raise StaffingError("hold_needs_rationale", 422)
        refused = rules.file_transition_refusal("hold", pfile.status)
        if refused:
            raise _refusal(refused)
        await self._fsm(FILE_FSM, pfile, "retention_hold", actor.user_id)
        pfile.hold_rationale, pfile.held_by = rationale, actor.user_id
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_personnel_file", pfile.id, "file_held", reason=rationale)
        return pfile

    async def release_file(self, project_id: uuid.UUID, file_id: uuid.UUID, actor: Actor) -> PersonnelFile:
        """Back to ``ended`` with the end and retention dates it was held with; the sweep takes it from there."""
        pfile = await self.open_file(project_id, file_id, actor, edit=True, lock=True)
        refused = rules.file_transition_refusal("release", pfile.status)
        if refused:
            raise _refusal(refused)
        await self._fsm(FILE_FSM, pfile, "ended", actor.user_id)
        pfile.hold_rationale, pfile.held_by = "", None
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_personnel_file", pfile.id, "file_released")
        return pfile

    async def erase_refusal(
        self, project_id: uuid.UUID, pfile: PersonnelFile, actor: Actor
    ) -> tuple[str | None, str | None]:
        """Why this caller cannot erase this file now (code, detail), or ``(None, None)``. Rule 15."""
        if not actor.personnel_erase:
            return "erase_permission_required", None
        refused = rules.file_transition_refusal("erase", pfile.status)
        if refused:
            return refused, None
        state = await self._retention(project_id, pfile, _today())
        if state["duty_running"]:
            return "retention_obligation_active", _iso(state["duty_until"]) or "open"
        return None, None

    async def erase_file(self, project_id: uuid.UUID, file_id: uuid.UUID, rationale: str, actor: Actor):
        """Rule 15: anonymise now, unless a statutory retention duty still runs or a legal hold is set."""
        if not rationale.strip():
            raise StaffingError("erasure_needs_rationale", 422)
        pfile = await self._child(PersonnelFile, project_id, file_id, "file_not_found", lock=True)
        refused, detail = await self.erase_refusal(project_id, pfile, actor)
        if refused:
            raise _refusal(refused, detail=detail)
        await self.anonymise(pfile, actor.user_id, reason=rationale)
        return pfile

    async def apply_retention(self, pfile: PersonnelFile, actor_id: Any, *, today: date) -> str:
        """Retention end of one ended file: ``deleted``, ``anonymised`` or ``kept``.

        The stored date is only what made the sweep look. The rules are read again
        here: a legal duty that still runs, or a date that moved because a document
        was added after the file ended, keeps the file and corrects the column.
        """
        if pfile.status != "ended":
            return "kept"
        state = await self._retention(pfile.project_id, pfile, today)
        if state["duty_running"] or state["due"] is None or state["due"] > today:
            if pfile.retention_due_at != state["due"]:
                pfile.retention_due_at = state["due"]
                await self.session.flush()
                await self._audit(
                    actor_id,
                    "staffing_personnel_file",
                    pfile.id,
                    "retention_date_corrected",
                    metadata={"retention_due_at": _iso(state["due"])},
                )
            return "kept"
        if state["action"] == "delete":
            await self.delete_file(pfile, actor_id)
            return "deleted"
        await self.anonymise(pfile, actor_id)
        return "anonymised"

    async def _remove_personal_data(self, pfile: PersonnelFile) -> dict[str, dict[str, int]]:
        """Delete travel, leave and documents (with their validity records) and cut every link to the person.

        Returns the monthly travel and leave counts, the only thing an anonymous record keeps of them.
        """
        from app.modules.accommodation.models import Accommodation, Booking, Room
        from app.modules.credentials.service import CredentialService

        project_id = pfile.project_id
        counts: dict[str, dict[str, int]] = {}
        for t in await self.repo.travels(project_id, pfile.id):
            bucket = counts.setdefault(t.depart_date.strftime("%Y-%m"), {"travel": 0, "leave": 0})
            bucket["travel"] += 1
            await self.session.delete(t)
        for lv in await self.repo.leaves(project_id, pfile.id):
            bucket = counts.setdefault(lv.from_date.strftime("%Y-%m"), {"travel": 0, "leave": 0})
            bucket["leave"] += 1
            await self.session.delete(lv)
        creds = CredentialService(self.session)
        for d in await self.repo.documents(project_id, pfile.id):
            # One validity record per document (unique in the database), so this never removes another person's.
            if d.credential_id is not None and (await self._credentials(project_id, [d.credential_id])):
                await creds.delete_credential(d.credential_id)
            await self.session.delete(d)
        member_id = pfile.roster_member_id
        if member_id is not None:
            for f in await self.repo.fills(project_id, roster_member_id=member_id):
                f.roster_member_id = None
            beds = (
                select(Booking)
                .join(Room, Room.id == Booking.room_id)
                .join(Accommodation, Accommodation.id == Room.accommodation_id)
                .where(Accommodation.project_id == project_id, Booking.roster_member_id == member_id)
            )
            for booking in (await self.session.execute(beds)).scalars():
                booking.roster_member_id = None
        await self.session.flush()
        return counts

    async def anonymise(self, pfile: PersonnelFile, actor_id: Any, *, reason: str = "retention_due") -> None:
        """Keep the anonymous record: no person, no documents, travel and leave as monthly counts only."""
        project_id = pfile.project_id
        await self._fsm(FILE_FSM, pfile, "anonymised", actor_id)
        pfile.activity_counts = await self._remove_personal_data(pfile)
        pfile.roster_member_id = None
        pfile.employer_organisation = ""
        pfile.hold_rationale, pfile.held_by = "", None
        pfile.anonymised_at = _now()
        await self.session.flush()
        await self._audit(actor_id, "staffing_personnel_file", pfile.id, "file_anonymised", reason=reason)
        self._publish("file.anonymised", {"project_id": str(project_id), "file_id": str(pfile.id)})

    async def delete_file(self, pfile: PersonnelFile, actor_id: Any, *, reason: str = "retention_due") -> None:
        """The retention rules of the file all say ``delete``: nothing of it is kept."""
        project_id, file_id = pfile.project_id, pfile.id
        await self._remove_personal_data(pfile)
        await self.session.delete(pfile)
        await self.session.flush()
        await self._audit(actor_id, "staffing_personnel_file", file_id, "file_deleted", reason=reason)
        self._publish("file.deleted", {"project_id": str(project_id), "file_id": str(file_id)})

    async def file_candidates(self, project_id: uuid.UUID, actor: Actor) -> list[dict[str, Any]]:
        """People on the plan who have no personnel file yet, and whether the caller may open one for them."""
        out = []
        for p in await self.people(project_id):
            if p["file_id"] is not None:
                continue
            draft = PersonnelFile(project_id=project_id, roster_member_id=p["roster_member_id"])
            allowed, reason, _relation = await self.file_access(project_id, draft, actor, edit=True)
            out.append(
                {
                    "roster_member_id": str(p["roster_member_id"]),
                    "name": p["name"],
                    "roles": p["roles"],
                    "can": {"create_file": _can(allowed, reason)},
                }
            )
        return out

    async def file_list(self, project_id: uuid.UUID, actor: Actor) -> list[dict[str, Any]]:
        """Restricted list: name, roles, dates, cleared flag, file status and whether the caller may open it."""
        people = {p["roster_member_id"]: p for p in await self.people(project_id)}
        members = await self._members(project_id, [f.roster_member_id for f in await self.repo.files(project_id)])
        out = []
        for f in await self.repo.files(project_id):
            p = people.get(f.roster_member_id, {})
            member = members.get(f.roster_member_id)
            allowed, reason, _relation = await self.file_access(project_id, f, actor, edit=False)
            out.append(
                {
                    "id": str(f.id),
                    "roster_member_id": _s(f.roster_member_id),
                    "name": member.display_name if member is not None else None,
                    "roles": p.get("roles", []),
                    "start": _iso(p.get("start")),
                    "end": _iso(p.get("end")),
                    "cleared_to_work": p.get("cleared"),
                    "status": f.status,
                    "can": {"open": _can(allowed, reason)},
                    "can_open": allowed,
                }
            )
        return out

    async def file_view(self, project_id: uuid.UUID, pfile: PersonnelFile, actor: Actor) -> dict[str, Any]:
        """The full file (after ``open_file``): header, documents, health flag, accommodation, travel, leave."""
        plan = await self.require_plan(project_id)
        catalogue = await self.catalogue_for(plan)
        people = {p["roster_member_id"]: p for p in await self.people(project_id)}
        person = people.get(pfile.roster_member_id, {}) if pfile.roster_member_id else {}
        members = await self._members(project_id, [pfile.roster_member_id])
        member = members.get(pfile.roster_member_id)
        travels = await self.repo.travels(project_id, pfile.id)
        leaves = await self.repo.leaves(project_id, pfile.id)
        warnings = [
            f.as_dict()
            for f in rules.travel_findings([_travel_dict(t) for t in travels], person.get("end"), pfile.status)
        ]
        gate_dates = await self._key_gate_dates_for(project_id, pfile.roster_member_id)
        for lv in leaves:
            warnings += [
                f.as_dict()
                for f in rules.leave_findings(_leave_dict(lv), [_travel_dict(t) for t in travels], gate_dates)
            ]
        bookings = await self.bookings_for(project_id, pfile.roster_member_id)
        if person.get("confirmed"):
            acc = rules.accommodation_finding(
                plan.requires_accommodation, person.get("start"), bookings, str(pfile.roster_member_id)
            )
            if acc is not None:
                warnings.append(acc.as_dict())
        editable, why_not, relation = await self.file_access(project_id, pfile, actor, edit=True)
        if editable and pfile.status == "anonymised":
            editable, why_not = False, "file_anonymised"
        erase_refused, _detail = await self.erase_refusal(project_id, pfile, actor)

        def transition(action: str) -> dict[str, Any]:
            by_state = rules.file_transition_refusal(action, pfile.status)
            refused = why_not if not editable else by_state
            return _can(refused is None, refused, by_state)

        return {
            "id": str(pfile.id),
            "roster_member_id": _s(pfile.roster_member_id),
            "name": member.display_name if member is not None else None,
            "employer_organisation": pfile.employer_organisation,
            "employment_basis": pfile.employment_basis,
            "nationality_required": pfile.nationality_required,
            "lawful_basis": pfile.lawful_basis,
            "status": pfile.status,
            "ended_on": _iso(pfile.ended_on),
            "retention_due_at": _iso(pfile.retention_due_at),
            "hold_rationale": pfile.hold_rationale,
            "anonymised_at": _iso(pfile.anonymised_at),
            "activity_counts": pfile.activity_counts or {},
            "roles": person.get("roles", []),
            "start": _iso(person.get("start")),
            "end": _iso(person.get("end")),
            "cleared_to_work": person.get("cleared"),
            "missing": person.get("missing", []),
            "expired": person.get("expired", []),
            "documents": await self.document_views(
                project_id, pfile, catalogue, person.get("required", []), actor=actor, editable=editable
            ),
            "accommodation": [{k: _iso(v) if isinstance(v, date) else v for k, v in b.items()} for b in bookings],
            "travel": [_travel_view(t) for t in travels],
            "leave": [_leave_view(lv) for lv in leaves],
            "warnings": warnings,
            "can": {
                "edit": _can(editable, why_not, "file_anonymised" if pfile.status == "anonymised" else None),
                "end": transition("end"),
                "hold": transition("hold"),
                "release": transition("release"),
                "erase": _can(
                    erase_refused is None, erase_refused, rules.file_transition_refusal("erase", pfile.status)
                ),
                "export": _can(relation == "self", "own_file_only"),
            },
            "can_edit": editable,
        }

    async def access_log(self, project_id: uuid.UUID, pfile: PersonnelFile) -> list[dict[str, Any]]:
        from app.core.audit_log import ActivityLog

        stmt = (
            select(ActivityLog)
            .where(ActivityLog.entity_type == "staffing_personnel_file", ActivityLog.entity_id == str(pfile.id))
            .order_by(ActivityLog.created_at.desc())
            .limit(200)
        )
        return [
            {"actor_id": _s(r.actor_id), "action": r.action, "at": _iso(r.created_at)}
            for r in (await self.session.execute(stmt)).scalars()
        ]

    # ── documents (rules 8, 11, 12) ────────────────────────────────────────

    def _verify_refusal(self, row: PersonnelDocument | None, actor: Actor | None) -> str | None:
        """Why this caller cannot verify this document, or None. Four eyes: the recorder never verifies."""
        if row is None or row.credential_id is None:
            return "document_without_validity"
        if row.verified_at is not None:
            return "already_in_state"
        if actor is not None and row.recorded_by is not None and row.recorded_by == actor.user_id:
            return "verifier_is_recorder"
        return None

    async def document_views(
        self,
        project_id: uuid.UUID,
        pfile: PersonnelFile,
        catalogue: StaffingModelCatalogue,
        required: list[str],
        *,
        actor: Actor | None = None,
        editable: bool = False,
    ) -> list[dict[str, Any]]:
        docs = {d.document_kind: d for d in await self.repo.documents(project_id, pfile.id)}
        creds = await self._credentials(project_id, [d.credential_id for d in docs.values()])
        out = []
        for kind in dict.fromkeys([*required, *docs]):
            d = docs.get(kind)
            cred = creds.get(d.credential_id) if d is not None else None
            refused = "personnel_permission_missing" if not editable else self._verify_refusal(d, actor)
            out.append(
                {
                    "id": _s(d.id) if d else None,
                    "document_kind": kind,
                    "required": kind in required,
                    "status": self._status_on(cred, _today()) if cred is not None else None,
                    "issued_at": _iso(getattr(cred, "issued_at", None)),
                    "valid_until": _iso(getattr(cred, "valid_until", None)),
                    "number_last4": d.number_last4 if d else None,
                    "recorded_by": _s(d.recorded_by) if d else None,
                    "verified_by": _s(d.verified_by) if d else None,
                    "verified_at": _iso(d.verified_at) if d else None,
                    "waived": bool(d and d.waived),
                    "waiver_rationale": d.waiver_rationale if d else "",
                    "fit_for_role": d.fit_for_role if d and kind == HEALTH_KIND else None,
                    "special_category": bool(
                        catalogue.document_kind(kind) and catalogue.document_kind(kind).special_category
                    ),
                    "can": {"verify": _can(refused is None, refused, self._verify_refusal(d, None))},
                }
            )
        return out

    async def record_document(
        self, project_id: uuid.UUID, file_id: uuid.UUID, data: dict[str, Any], actor: Actor
    ) -> PersonnelDocument:
        """Record a document of this person: its validity window and at most the number's last 4.

        The validity record lives in the credentials module so its expiry engine
        covers it (rule 9), and it is created here, for this person, one per
        document. A request cannot name an existing credential: that is how one
        person's permit ended up on another person's file.
        """
        from app.modules.credentials.schemas import CredentialCreate, CredentialUpdate
        from app.modules.credentials.service import CredentialService

        pfile = await self.open_file(project_id, file_id, actor, edit=True, lock=True)
        if pfile.status == "anonymised":
            raise conflict("file_anonymised")
        catalogue = await self.catalogue_for(await self.require_plan(project_id))
        kind = catalogue.document_kind(data["document_kind"])
        if kind is None:
            raise StaffingError("document_kind_unknown", 422)
        try:
            last4 = rules.masked_number(data.get("number_last4"), kind.store_number)
        except ValueError as exc:
            raise StaffingError(str(exc), 422) from exc
        if data.get("fit_for_role") is not None and kind.code != HEALTH_KIND:
            raise StaffingError("fit_flag_only_for_health", 422)
        issued, until = data.get("issued_at"), data.get("valid_until")
        existing = {d.document_kind: d for d in await self.repo.documents(project_id, pfile.id)}
        row = existing.get(kind.code)
        current = None
        if row is not None and row.credential_id is not None:
            current = (await self._credentials(project_id, [row.credential_id])).get(row.credential_id)
        starts = issued if issued is not None else getattr(current, "issued_at", None)
        ends = until if until is not None else getattr(current, "valid_until", None)
        if starts is not None and ends is not None and ends < starts:
            raise StaffingError("validity_dates_invalid", 422)
        member = (await self._members(project_id, [pfile.roster_member_id])).get(pfile.roster_member_id)
        if member is None:
            raise not_found("roster_member_not_found")
        if row is None:
            row = await self.repo.add(
                PersonnelDocument(project_id=project_id, personnel_file_id=pfile.id, document_kind=kind.code)
            )
        registry = CredentialService(self.session)
        if current is None:
            created = await registry.create_credential(
                CredentialCreate(
                    project_id=project_id,
                    holder_name=member.display_name,
                    credential_type=kind.credential_type,
                    issued_at=issued,
                    valid_until=until,
                    notify_days_before=kind.default_notify_days_before,
                ),
                user_id=_s(actor.user_id),
                personnel=True,
            )
            row.credential_id = created.id
        else:
            window = {k: v for k, v in (("issued_at", issued), ("valid_until", until)) if v is not None}
            if window:
                await registry.update_credential(current.id, CredentialUpdate(**window), personnel=True)
        if last4 is not None:
            row.number_last4 = last4
        if data.get("fit_for_role") is not None:
            row.fit_for_role = data["fit_for_role"]
        # A new statement about the document: whoever checked the old one has not checked this one.
        row.recorded_by, row.verified_by, row.verified_at = actor.user_id, None, None
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_personnel_document", row.id, "document_recorded")
        if pfile.status == "ended":
            # A document added after the end can lengthen the retention; the stored date follows.
            pfile.retention_due_at = (await self._retention(project_id, pfile, _today()))["due"]
            await self.session.flush()
        return row

    async def verify_document(self, project_id: uuid.UUID, file_id: uuid.UUID, document_id: uuid.UUID, actor: Actor):
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        row = await self._child(PersonnelDocument, project_id, document_id, "document_not_found", lock=True)
        if row.personnel_file_id != pfile.id:
            raise not_found("document_not_found")
        refused = self._verify_refusal(row, actor)
        if refused:
            raise _refusal(refused)
        row.verified_by, row.verified_at = actor.user_id, _now()
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_personnel_document", row.id, "document_verified")
        return row

    async def waive_document(
        self, project_id: uuid.UUID, file_id: uuid.UUID, document_kind: str, rationale: str, actor: Actor
    ) -> PersonnelDocument:
        pfile = await self.open_file(project_id, file_id, actor, edit=True, lock=True)
        if pfile.status == "anonymised":
            raise conflict("file_anonymised")
        catalogue = await self.catalogue_for(await self.require_plan(project_id))
        if catalogue.document_kind(document_kind) is None:
            raise StaffingError("document_kind_unknown", 422)
        if not rationale.strip():
            raise StaffingError("waiver_needs_rationale", 422)
        existing = {d.document_kind: d for d in await self.repo.documents(project_id, pfile.id)}
        row = existing.get(document_kind)
        if row is not None and row.waived:
            raise conflict("already_in_state")
        if row is None:
            row = await self.repo.add(
                PersonnelDocument(project_id=project_id, personnel_file_id=pfile.id, document_kind=document_kind)
            )
        row.waived, row.waiver_rationale = True, rationale
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_personnel_document", row.id, "document_waived", reason=rationale)
        return row

    # ── accommodation (rule 18, read only) ─────────────────────────────────

    async def bookings_for(self, project_id: uuid.UUID, roster_member_id: uuid.UUID | None) -> list[dict[str, Any]]:
        if roster_member_id is None:
            return []
        from app.modules.accommodation.models import Accommodation, Booking, Room

        stmt = (
            select(Booking, Room.label, Accommodation.name)
            .join(Room, Room.id == Booking.room_id)
            .join(Accommodation, Accommodation.id == Room.accommodation_id)
            .where(Accommodation.project_id == project_id, Booking.roster_member_id == roster_member_id)
            .order_by(Booking.check_in)
        )
        return [
            {
                "id": str(b.id),
                "room": room,
                "accommodation": acc,
                "check_in": b.check_in,
                "check_out": b.check_out,
                "status": b.status,
            }
            for b, room, acc in (await self.session.execute(stmt)).all()
        ]

    # ── travel and leave (rules 16, 17) ────────────────────────────────────

    async def create_travel(self, project_id: uuid.UUID, file_id: uuid.UUID, data: dict[str, Any], actor: Actor):
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        if pfile.status == "anonymised":
            raise conflict("file_anonymised")
        values = _travel_values(data)
        row = await self.repo.add(
            TravelRecord(project_id=project_id, personnel_file_id=pfile.id, status="planned", **values)
        )
        await self._audit(actor.user_id, "staffing_travel", row.id, "travel_created")
        return row

    async def update_travel(
        self, project_id: uuid.UUID, file_id: uuid.UUID, travel_id: uuid.UUID, changes: dict[str, Any], actor: Actor
    ) -> TravelRecord:
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        row = await self._child(TravelRecord, project_id, travel_id, "travel_not_found", lock=True)
        if row.personnel_file_id != pfile.id:
            raise not_found("travel_not_found")
        changes = dict(changes)
        status = changes.pop("status", None)
        _refuse_nulls(changes, ("return_date", "cost"))
        if status:
            await self._fsm(TRAVEL_FSM, row, status, actor.user_id)
        for k, v in _travel_values({**_travel_view_raw(row), **changes}).items():
            setattr(row, k, v)
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_travel", row.id, "travel_updated")
        return row

    async def delete_travel(self, project_id: uuid.UUID, file_id: uuid.UUID, travel_id: uuid.UUID, actor: Actor):
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        row = await self._child(TravelRecord, project_id, travel_id, "travel_not_found")
        if row.personnel_file_id != pfile.id:
            raise not_found("travel_not_found")
        await self.repo.delete(row)
        await self._audit(actor.user_id, "staffing_travel", travel_id, "travel_deleted")

    async def _leave_types(self, project_id: uuid.UUID) -> set[str]:
        catalogue = await self.catalogue_for(await self.require_plan(project_id))
        return {lt.code for lt in catalogue.leave_types}

    async def create_leave(self, project_id: uuid.UUID, file_id: uuid.UUID, data: dict[str, Any], actor: Actor):
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        if pfile.status == "anonymised":
            raise conflict("file_anonymised")
        if data["leave_type"] not in await self._leave_types(project_id):
            raise StaffingError("leave_type_unknown", 422)
        if data["to_date"] < data["from_date"]:
            raise StaffingError("exit_before_entry", 422)
        row = await self.repo.add(
            LeaveRecord(project_id=project_id, personnel_file_id=pfile.id, status="requested", **data)
        )
        await self._audit(actor.user_id, "staffing_leave", row.id, "leave_requested")
        warnings = rules.leave_findings(
            _leave_dict(row),
            [_travel_dict(t) for t in await self.repo.travels(project_id, pfile.id)],
            await self._key_gate_dates_for(project_id, pfile.roster_member_id),
        )
        return row, [w.as_dict() for w in warnings]

    async def update_leave(
        self, project_id: uuid.UUID, file_id: uuid.UUID, leave_id: uuid.UUID, changes: dict[str, Any], actor: Actor
    ) -> LeaveRecord:
        """Type and dates of a leave that is still a request; an approval covers what was approved."""
        _refuse_nulls(changes)
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        row = await self._child(LeaveRecord, project_id, leave_id, "leave_not_found", lock=True)
        if row.personnel_file_id != pfile.id:
            raise not_found("leave_not_found")
        if row.status != "requested":
            raise conflict("leave_not_requested")
        if "leave_type" in changes and changes["leave_type"] not in await self._leave_types(project_id):
            raise StaffingError("leave_type_unknown", 422)
        merged = {"from_date": row.from_date, "to_date": row.to_date, **changes}
        if merged["to_date"] < merged["from_date"]:
            raise StaffingError("exit_before_entry", 422)
        for k, v in changes.items():
            setattr(row, k, v)
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_leave", row.id, "leave_updated")
        return row

    async def set_leave_status(
        self, project_id: uuid.UUID, file_id: uuid.UUID, leave_id: uuid.UUID, status: str, actor: Actor
    ) -> LeaveRecord:
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        row = await self._child(LeaveRecord, project_id, leave_id, "leave_not_found", lock=True)
        if row.personnel_file_id != pfile.id:
            raise not_found("leave_not_found")
        await self._fsm(LEAVE_FSM, row, status, actor.user_id)
        if status == "approved":
            row.approved_by, row.approved_at = actor.user_id, _now()
        await self.session.flush()
        await self._audit(actor.user_id, "staffing_leave", row.id, f"leave_{status}")
        return row

    async def delete_leave(self, project_id: uuid.UUID, file_id: uuid.UUID, leave_id: uuid.UUID, actor: Actor):
        pfile = await self.open_file(project_id, file_id, actor, edit=True)
        row = await self._child(LeaveRecord, project_id, leave_id, "leave_not_found")
        if row.personnel_file_id != pfile.id:
            raise not_found("leave_not_found")
        await self.repo.delete(row)
        await self._audit(actor.user_id, "staffing_leave", leave_id, "leave_deleted")

    async def _gates(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """The project's live gates, each with what the phase behind it enables and its planned date.

        A position never names a gate. It names what must be enabled (a tag), and
        the gate is whichever one leads into a phase carrying that tag, read now.
        """
        catalogue = await self._governance_catalogue(project_id)
        return [
            {"code": g.code, "enabled": hosting.enabled_by(catalogue, g.to_phase), "date": g.target_date}
            for g in await governance.project_gates(self.session, project_id)
        ]

    async def _key_gate_dates_for(self, project_id: uuid.UUID, roster_member_id: uuid.UUID | None) -> list[date]:
        if roster_member_id is None:
            return []
        positions = {p.id: p for p in await self.repo.positions(project_id)}
        tags = set()
        for f in await self.repo.fills(project_id, roster_member_id=roster_member_id):
            p = positions.get(f.position_id)
            if p is not None and p.key_role and p.required_before:
                tags.add(p.required_before)
        if not tags:
            return []
        return sorted({g["date"] for g in await self._gates(project_id) if g["date"] and g["enabled"] & tags})

    # ── upcoming (screen 5) ────────────────────────────────────────────────

    async def upcoming(self, project_id: uuid.UUID, actor: Actor, days: int = 90) -> dict[str, Any]:
        """Expiring documents, mobilisations in the next 14 days, leave; only of files the caller may open."""
        today = _today()
        files = [f for f in await self.repo.files(project_id) if await self.can_open(project_id, f, actor)]
        ids = {f.id for f in files}
        members = await self._members(project_id, [f.roster_member_id for f in files])
        names = {f.id: getattr(members.get(f.roster_member_id), "display_name", None) for f in files}
        docs = [d for d in await self.repo.documents(project_id) if d.personnel_file_id in ids]
        creds = await self._credentials(project_id, [d.credential_id for d in docs])
        expiring = []
        for d in docs:
            cred = creds.get(d.credential_id)
            if cred is None or cred.valid_until is None:
                continue
            left = (cred.valid_until - today).days
            if left <= days:
                expiring.append(
                    {
                        "file_id": str(d.personnel_file_id),
                        "name": names.get(d.personnel_file_id),
                        "document_kind": d.document_kind,
                        "valid_until": _iso(cred.valid_until),
                        "days": left,
                        "status": self._status_on(cred, today),
                        "bucket": 30 if left <= 30 else 60 if left <= 60 else 90,
                    }
                )
        mobilisations = [
            {**_travel_view(t), "file_id": str(t.personnel_file_id), "name": names.get(t.personnel_file_id)}
            for t in await self.repo.travels(project_id)
            if t.personnel_file_id in ids
            and t.kind == "mobilisation"
            and t.status != "cancelled"
            and today <= t.depart_date <= today + timedelta(days=14)
        ]
        leave = [
            {**_leave_view(lv), "file_id": str(lv.personnel_file_id), "name": names.get(lv.personnel_file_id)}
            for lv in await self.repo.leaves(project_id)
            if lv.personnel_file_id in ids and lv.status in ("requested", "approved") and lv.to_date >= today
        ]
        return {
            "expiring": sorted(expiring, key=lambda e: e["days"]),
            "mobilisations": mobilisations,
            "leave": leave,
        }

    # ── planned vs actual (rule 19, read only) ─────────────────────────────

    async def planned_vs_actual(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """FTE-days planned per position vs hours booked on the fills' linked resources in field time.

        Both sides count working days of the project's calendar: planned days are the
        working days from entry to today (or exit), and booked hours become days at
        the calendar's hours per day. Calendar days against worked hours would show
        a shortfall on every position by construction.
        """
        from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
        from app.modules.schedule.service import ScheduleService, compute_duration, get_work_calendar

        region = await ScheduleService(self.session).resolve_project_region(project_id)
        hours_per_day = Decimal(str(get_work_calendar(region)["hours_per_day"]))
        positions = await self.repo.positions(project_id)
        fills = await self.repo.fills(project_id)
        members = await self._members(project_id, [f.roster_member_id for f in fills])
        today = _today()
        out = []
        for p in positions:
            if p.status == "cancelled" or p.entry_date is None:
                continue
            end = min(p.exit_date or today, today)
            working = compute_duration(p.entry_date.isoformat(), end.isoformat(), region) if end >= p.entry_date else 0
            planned = Decimal(p.fte) * p.headcount * working
            resources = {
                getattr(members.get(f.roster_member_id), "resource_id", None)
                for f in fills
                if f.position_id == p.id and f.status != "proposed"
            } - {None}
            hours = Decimal("0")
            if resources:
                stmt = (
                    select(func.coalesce(func.sum(FieldTimesheetLine.hours), 0))
                    .join(FieldTimesheet, FieldTimesheet.id == FieldTimesheetLine.timesheet_id)
                    .where(
                        FieldTimesheet.project_id == project_id,
                        FieldTimesheetLine.resource_id.in_(resources),
                        FieldTimesheet.date >= p.entry_date,
                        FieldTimesheet.date <= end,
                    )
                )
                hours = Decimal(str((await self.session.execute(stmt)).scalar() or 0))
            actual = (hours / hours_per_day).quantize(Decimal("0.01"))
            out.append(
                {
                    "position_id": str(p.id),
                    "role_code": p.role_code,
                    "working_days": working,
                    "hours_per_day": str(hours_per_day),
                    "planned_fte_days": str(planned.quantize(Decimal("0.01"))),
                    "actual_hours": str(hours),
                    "actual_fte_days": str(actual),
                    "variance_fte_days": str((actual - planned).quantize(Decimal("0.01"))),
                    "linked_resources": len(resources),
                }
            )
        return out

    # ── readiness, validation ──────────────────────────────────────────────

    async def readiness(self, project_id: uuid.UUID, gate_code: str) -> dict[str, Any]:
        """What the governance gate reads of the staffing plan (rule 5, section 7).

        The gate is matched to positions by what the phase behind it enables. A key
        position whose requirement no phase of the governance model enables cannot
        be checked at any gate; it is listed in ``unresolved_tags`` so the evidence
        says ``unknown`` instead of passing in silence.
        """
        plan = await self.get_plan(project_id)
        if plan is None:
            return {"in_use": False}
        gate = next((g for g in await self._gates(project_id) if g["code"] == gate_code), None)
        if gate is None:
            raise not_found("gate_not_found")
        catalogue = await self._governance_catalogue(project_id)
        positions = [position_dict(p) for p in await self.repo.positions(project_id)]
        fills = [fill_dict(f) for f in await self.repo.fills(project_id)]
        key = rules.key_role_gate_findings(positions, fills, gate["enabled"], gate["date"])
        errors = [f for f in await self.submission_findings(project_id) if f.severity == rules.ERROR]
        asked = {
            p["required_before"]
            for p in positions
            if p["key_role"] and p["required_before"] and p["status"] != "cancelled"
        }
        frame = await self._resolve_frame_document(project_id)
        return {
            "in_use": True,
            "status": plan.status,
            # Submitted or later. Approval itself is the gate decision, so it cannot be a precondition of the gate.
            "submitted": plan.status in ("in_review", "approved", "binding")
            or (plan.status == "revising" and bool(plan.bound_snapshot)),
            # The model hosts staffing but the project has no document row for it: nothing can be read.
            "frame_document_missing": frame is None,
            "frame_required": frame is not None and gate_code in frame.required_at_gates,
            "key_roles_required": bool(asked & gate["enabled"]),
            "key_role_findings": [f.as_dict() for f in key],
            "unresolved_tags": sorted(asked - hosting.enabled_tags(catalogue)),
            "open_key_roles": rules.open_key_positions(positions, fills, gate["enabled"]),
            "errors": [f.as_dict() for f in errors],
        }

    async def validation_payload(self, project_id: uuid.UUID, actor: Any = None) -> dict[str, Any]:
        """What the staffing rules read. Per person, only what the caller may read in that person's file.

        Which of a person's documents is missing or expired, and whether they
        have a bed, is that person's file (rule 13). For anybody the caller may
        not open the file of, those facts are withheld and the rules about them
        say nothing; ``restricted_people`` counts how many that is.
        """
        who = _as_actor(actor)
        plan = await self.require_plan(project_id)
        catalogue = await self.catalogue_for(plan)
        people = await self.people(project_id)
        files = await self.repo.files(project_id)
        by_id = {f.id: f for f in files}
        restricted = 0
        for p in people:
            pfile = by_id.get(p["file_id"]) or PersonnelFile(
                project_id=project_id, roster_member_id=p["roster_member_id"]
            )
            allowed, _reason, _relation = await self.file_access(project_id, pfile, who, edit=False)
            p["restricted"] = not allowed
            if allowed:
                p["bookings"] = await self.bookings_for(project_id, p["roster_member_id"])
            else:
                restricted += 1
                p["bookings"], p["missing"], p["expired"], p["documents"] = [], [], [], {}
        retention: list[dict[str, Any]] = []
        for f in files:
            if f.status == "ended" and f.retention_due_at is None:
                retention.append({"id": str(f.id), "assigned": False})
            elif f.status in ("ended", "retention_hold"):
                retention.append({"id": str(f.id), "assigned": True})
        return {
            "catalogue": catalogue,
            "plan": {
                "status": plan.status,
                "commissioning_date": plan.commissioning_date,
                "requires_accommodation": plan.requires_accommodation,
            },
            "positions": [position_dict(p) for p in await self.repo.positions(project_id)],
            "fills": [fill_dict(f) for f in await self.repo.fills(project_id)],
            "handovers": [handover_dict(h) for h in await self.repo.handovers(project_id)],
            "gates": await self._gates(project_id),
            "people": people,
            "documents": [
                {
                    "id": str(d.id),
                    "document_kind": d.document_kind,
                    "number_last4": d.number_last4,
                    "fit_for_role": d.fit_for_role,
                }
                for d in await self.repo.documents(project_id)
            ],
            "retention": retention,
            "restricted_people": restricted,
        }

    # ── reminders (rule 10) ────────────────────────────────────────────────

    async def reminder_recipients(self, credential_id: uuid.UUID) -> list[tuple[PersonnelDocument, set[uuid.UUID]]]:
        """Line managers of the person, the owner of the hosting area, and the person if a platform user."""
        out = []
        for d in await self.repo.documents_for_credential(credential_id):
            pfile = await self.repo.child(PersonnelFile, d.project_id, d.personnel_file_id)
            if pfile is None or pfile.roster_member_id is None or pfile.status == "anonymised":
                continue
            recipients = await self._position_owners_of(d.project_id, pfile.roster_member_id)
            recipients |= await self._area_people(d.project_id, deputy=False)
            member = (await self._members(d.project_id, [pfile.roster_member_id])).get(pfile.roster_member_id)
            if member is not None and member.user_id is not None:
                recipients.add(member.user_id)
            out.append((d, recipients))
        return out

    async def send_expiry_reminders(self, data: dict[str, Any]) -> int:
        """Notify rule 10 recipients of a ``credentials.expiry.alert``. Body: kind and date only."""
        from app.modules.notifications.service import NotificationService

        credential_id = _uuid(data.get("credential_id"))
        if credential_id is None:
            return 0
        sent = 0
        for doc, recipients in await self.reminder_recipients(credential_id):
            if not recipients:
                continue
            await NotificationService(self.session).notify_users(
                sorted(recipients, key=str),
                "staffing_document_expiry",
                "notifications.staffing.document_expiry.title",
                entity_type="staffing_personnel_file",
                entity_id=str(doc.personnel_file_id),
                body_key="notifications.staffing.document_expiry.body",
                body_context={
                    "document_kind": doc.document_kind,
                    "valid_until": data.get("valid_until"),
                    "status": data.get("status"),
                },
                action_url=f"/projects/{doc.project_id}/staffing/files/{doc.personnel_file_id}",
            )
            sent += len(recipients)
        return sent


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


def _json_safe(value: Any) -> Any:
    """ISO strings for dates, str for Decimal and UUID: what a JSON column accepts on every engine."""
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    return value


def _travel_values(data: dict[str, Any]) -> dict[str, Any]:
    out = {
        k: data.get(k)
        for k in ("kind", "from_place", "to_place", "depart_date", "return_date", "booking_ref", "currency")
    }
    out = {
        k: ("" if v is None and k in ("from_place", "to_place", "booking_ref", "currency") else v)
        for k, v in out.items()
    }
    cost = data.get("cost")
    if cost is not None and cost != "":
        error = rules.money_error(cost)
        if error:
            raise StaffingError(error, 422)
        out["cost"] = rules.dec(cost)
        if not out["currency"]:
            raise StaffingError("currency_required", 422)
        if len(out["currency"]) != 3 or not out["currency"].isalpha():
            raise StaffingError("currency_invalid", 422)
    else:
        out["cost"] = None
    if out["return_date"] is not None and out["return_date"] < out["depart_date"]:
        raise StaffingError("exit_before_entry", 422)
    return out


def _travel_view_raw(t: TravelRecord) -> dict[str, Any]:
    return {
        "kind": t.kind,
        "from_place": t.from_place,
        "to_place": t.to_place,
        "depart_date": t.depart_date,
        "return_date": t.return_date,
        "booking_ref": t.booking_ref,
        "cost": t.cost,
        "currency": t.currency,
    }


def _travel_dict(t: TravelRecord) -> dict[str, Any]:
    return {**_travel_view_raw(t), "id": str(t.id), "status": t.status}


def _travel_view(t: TravelRecord) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "kind": t.kind,
        "from_place": t.from_place,
        "to_place": t.to_place,
        "depart_date": _iso(t.depart_date),
        "return_date": _iso(t.return_date),
        "booking_ref": t.booking_ref,
        "cost": _s(t.cost),
        "currency": t.currency,
        "status": t.status,
    }


def _leave_dict(lv: LeaveRecord) -> dict[str, Any]:
    return {"id": str(lv.id), "from_date": lv.from_date, "to_date": lv.to_date, "status": lv.status}


def _leave_view(lv: LeaveRecord) -> dict[str, Any]:
    return {
        "id": str(lv.id),
        "leave_type": lv.leave_type,
        "from_date": _iso(lv.from_date),
        "to_date": _iso(lv.to_date),
        "status": lv.status,
        "approved_by": _s(lv.approved_by),
        "approved_at": _iso(lv.approved_at),
    }
