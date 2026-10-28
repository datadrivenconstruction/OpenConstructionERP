# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commitment release service: matrix, items, releases, recompute, guard check and exposure.

Every write runs in the caller's transaction with its audit entry
(``log_activity``) and its events (``publish_after_commit``). Amounts are
derived on read (``figures``); the only figures frozen are the ones a release
decision captures at request time (amount, FX rate and date, tier, schedule
version), because a decision must keep saying what it decided on.

Release flow (SPEC rules 2, 4, 5, 11, 12, 19)::

    request_release  -- lock item, refuse a second pending request (409),
                        evaluate DoA on the cumulative amount in the schedule
                        currency, start an approval instance on the tier route
    apply_route_verdict (from the approval_routes subscriber)
                     -- completed: released / partially_released
                        rejected: back to the state before, attempt + 1
    withdraw         -- the requester cancels the instance, attempt + 1
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.commitment_release import drawdown, figures
from app.modules.commitment_release import evaluator as ev
from app.modules.commitment_release.catalogue import (
    ABORT_BASIS_KIND,
    AUTHORITY_SCHEDULE_KIND,
    DEFAULT_SCHEDULE_ID,
    AbortBasis,
    AuthoritySchedule,
    parse_amount,
    register_kinds,
)
from app.modules.commitment_release.errors import CommitmentError, conflict, forbidden, not_found
from app.modules.commitment_release.exposure import ScheduleEntry, TermsInput, combine_exposures, compute_exposure
from app.modules.commitment_release.fsm import ITEM_FSM, RECOMPUTED, REQUESTABLE, WORKING
from app.modules.commitment_release.fx import FxQuote, FxRateMissing, norm, resolve_quote
from app.modules.commitment_release.models import (
    AbortScenario,
    AbortTerms,
    AuthorityAssignment,
    CommitmentItem,
    CommitmentLink,
    CommitmentMatrix,
    CommitmentPrecondition,
    ReleaseDecision,
)
from app.modules.commitment_release.preconditions import precondition_reader
from app.modules.commitment_release.repository import CommitmentRepository

logger = logging.getLogger(__name__)

MODULE = "commitment_release"
TARGET_KIND = "commitment_release"
ZERO = Decimal("0")
ENFORCEMENT = ("off", "warn", "block")
FX_POLICIES = ("fx_service_rate_set", "project_rates")
PLANNED_SOURCES = ("budget_line", "cost_line", "boq_position", "manual")
PRECONDITION_KINDS = (
    "manual",
    "gate_decided",
    "frame_document_binding",
    "funding_approved",
    "permit",
    "budget_available",
    "public_commitment_appropriation",
)
STORED_PRECONDITIONS = ("manual", "permit", "public_commitment_appropriation")
# What a readiness gate reads from an item. Changing one needs ``commitment.manage`` and is only
# possible while the item is still ``planned``.
GATE_FIELDS = ("gate_code", "governance_area_code", "deferred", "deferred_reason")
# What decides the tier a request is judged on. Frozen once a release was ever requested.
SPLIT_FIELDS = ("split_group", "flags")
# Who owns the item decides who may NOT approve it (four eyes): manage only, ``planned`` only.
OWNER_FIELDS = ("owner_user_id",)
ENDED = ("aborted", "transferred")
# Preconditions whose state is read from another module; nobody ticks them by hand.
LINKED_PRECONDITIONS = ("gate_decided", "frame_document_binding", "funding_approved")
# The commitment type an abort is judged as (SPEC rule 15); a schedule without it cannot decide one.
ABORT_TYPE = "termination_settlement"


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _ref_uuid(value: Any) -> uuid.UUID | None:
    """A stored reference as an id, or ``None`` when the text is not one (it then names nothing)."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _day(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso_day(value: Any) -> str | None:
    """A date as the ISO text its ``String(40)`` column stores; asyncpg refuses a ``date`` bound to VARCHAR."""
    if value is None or value == "":
        return None
    day = _day(value)
    if day is None:
        raise CommitmentError("date_invalid", 422)
    return day.isoformat()


def _money_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _amount(value: Any, code: str = "amount_invalid") -> Decimal:
    try:
        return parse_amount(value)
    except ValueError as exc:
        raise CommitmentError(code, 422) from exc


class CommitmentService:
    """Orchestrates the matrix of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CommitmentRepository(session)
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
        """``name`` is the full event name, written out at the call: the wiring test reads the source."""
        publish_after_commit(self.session, name, data, source_module=MODULE)

    async def _fsm(self, item: CommitmentItem, target: str, actor_id: Any, reason: str | None = None, **meta: Any):
        try:
            await ITEM_FSM.apply(
                self.session,
                item,
                target,
                actor_id=_s(actor_id),
                reason=reason,
                extra_metadata={"project_id": _s(item.project_id), **meta},
                entity_type=ITEM_FSM.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _notify(self, user_id: Any, kind: str, item: CommitmentItem, ctx: dict[str, Any]) -> None:
        """Best effort, inside a savepoint so a failure never poisons the write."""
        if not user_id:
            return
        try:
            from app.modules.notifications.service import NotificationService

            async with self.session.begin_nested():
                await NotificationService(self.session).create(
                    user_id=user_id,
                    notification_type=f"commitment_{kind}",
                    title_key=f"notifications.commitment.{kind}.title",
                    entity_type="commitment_item",
                    entity_id=str(item.id),
                    body_key=f"notifications.commitment.{kind}.body",
                    body_context=ctx,
                    action_url=f"/projects/{item.project_id}/commitments?item={item.id}",
                    metadata=ctx,
                )
        except Exception:
            logger.debug("commitment notification %s skipped", kind, exc_info=True)

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    @staticmethod
    def _project_rates(project: Any) -> tuple[str, dict[str, str]]:
        base = norm(getattr(project, "currency", "") or "")
        rates: dict[str, str] = {}
        raw = getattr(project, "fx_rates", None)
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict) and entry.get("code") and entry.get("rate"):
                    rates[norm(str(entry["code"]))] = str(entry["rate"]).strip()
        return base, rates

    async def quote(self, matrix: CommitmentMatrix, project: Any, from_ccy: str, to_ccy: str, on_date: date) -> FxQuote:
        base, rates = self._project_rates(project)
        return await resolve_quote(
            self.session,
            from_currency=from_ccy or base,
            to_currency=to_ccy or base,
            on_date=on_date,
            project_id=matrix.project_id,
            base=base,
            project_rates=rates,
            policy=matrix.fx_policy,
        )

    # ── matrix ─────────────────────────────────────────────────────────────

    async def get_matrix(self, project_id: uuid.UUID, *, lock: bool = False) -> CommitmentMatrix | None:
        return await self.repo.get_matrix(project_id, lock=lock)

    async def require_matrix(self, project_id: uuid.UUID, *, lock: bool = False) -> CommitmentMatrix:
        matrix = await self.repo.get_matrix(project_id, lock=lock)
        if matrix is None:
            raise not_found("matrix_missing")
        return matrix

    async def schedule_for(self, matrix: CommitmentMatrix) -> AuthoritySchedule:
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        return await resolve_catalogue(
            self.session,
            matrix.schedule_source,
            matrix.schedule_id,
            matrix.schedule_version,
            kind=AUTHORITY_SCHEDULE_KIND,
            # The matrix row is a pin the server stored after checking it: it keeps resolving for
            # every member of the project and after the catalogue is retired.
            from_pin=True,
        )

    async def abort_basis(self, source: str, code: str, version: int | None) -> AbortBasis:
        """The basis a stored abort-terms row names. The row was checked when it was written."""
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        return await resolve_catalogue(self.session, source, code, version, kind=ABORT_BASIS_KIND, from_pin=True)

    def schedule_currency(self, schedule: AuthoritySchedule, project: Any) -> str:
        return norm(schedule.currency) or norm(getattr(project, "currency", "") or "")

    async def set_matrix(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        schedule_source: str | None = None,
        schedule_id: str | None = None,
        schedule_version: int | None = None,
        enforcement: str | None = None,
        fx_policy: str | None = None,
        require_link: bool | None = None,
        legal_entity_id: uuid.UUID | None = None,
    ) -> CommitmentMatrix:
        """Create the matrix or change its settings. Pinning a new schedule version keeps decided releases as they are."""
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        project = await self._project(project_id)
        matrix = await self.repo.get_matrix(project_id, lock=True)
        if enforcement is not None and enforcement not in ENFORCEMENT:
            raise CommitmentError("enforcement_invalid", 422)
        if fx_policy is not None and fx_policy not in FX_POLICIES:
            raise CommitmentError("fx_policy_invalid", 422)
        if matrix is None and schedule_id is None and schedule_source is None:
            # A new matrix with no schedule named: the governance port is the only country default.
            # It answers for the active pack, the regional packs and the shipped schedule that claims
            # the country; when it has no answer the neutral schedule is pinned.
            from app.modules.project_governance.public import default_catalogue_pin

            pin = default_catalogue_pin(AUTHORITY_SCHEDULE_KIND, getattr(project, "country_code", None))
            if pin is not None:
                schedule_source, schedule_id, schedule_version = pin.source, pin.catalogue_id, pin.version
        source = schedule_source or (matrix.schedule_source if matrix else "shipped")
        sid = schedule_id or (matrix.schedule_id if matrix else DEFAULT_SCHEDULE_ID)
        before: dict[str, Any] = {}
        if matrix is None or schedule_id is not None or schedule_version is not None or schedule_source is not None:
            try:
                version = await CatalogueStore(self.session).assert_pinnable(
                    tenant_id, source, sid, schedule_version, kind=AUTHORITY_SCHEDULE_KIND
                )
            except GovernanceError as exc:
                raise CommitmentError(exc.code, exc.status_code) from exc
        else:
            version = matrix.schedule_version
        if matrix is not None and (source, sid, version) != (
            matrix.schedule_source,
            matrix.schedule_id,
            matrix.schedule_version,
        ):
            await self._refuse_incompatible_schedule(project, matrix, source, sid, version, tenant_id)
        if matrix is None:
            matrix = await self.repo.add(
                CommitmentMatrix(
                    project_id=project_id,
                    schedule_source=source,
                    schedule_id=sid,
                    schedule_version=version,
                    enforcement=enforcement or "warn",
                    fx_policy=fx_policy or "fx_service_rate_set",
                    require_link=bool(require_link),
                    tier_routes={},
                    generated_routes={},
                    legal_entity_id=legal_entity_id,
                    created_by=actor_id,
                )
            )
            action = "matrix_created"
        else:
            before = {
                "schedule": f"{matrix.schedule_source}:{matrix.schedule_id}@{matrix.schedule_version}",
                "enforcement": matrix.enforcement,
                "fx_policy": matrix.fx_policy,
            }
            matrix.schedule_source, matrix.schedule_id, matrix.schedule_version = source, sid, version
            if enforcement is not None:
                matrix.enforcement = enforcement
            if fx_policy is not None:
                matrix.fx_policy = fx_policy
            if require_link is not None:
                matrix.require_link = require_link
            if legal_entity_id is not None:
                matrix.legal_entity_id = legal_entity_id
            action = "matrix_updated"
        await self.session.flush()
        after = {
            "schedule": f"{matrix.schedule_source}:{matrix.schedule_id}@{matrix.schedule_version}",
            "enforcement": matrix.enforcement,
            "fx_policy": matrix.fx_policy,
        }
        await self._audit(actor_id, "commitment_matrix", matrix.id, action, before_state=before or None, metadata=after)
        self._publish("commitment_release.matrix.set", {"project_id": str(project_id), **after})
        return matrix

    async def _refuse_incompatible_schedule(
        self, project: Any, matrix: CommitmentMatrix, source: str, sid: str, version: int, tenant_id: str | None
    ) -> None:
        """Review finding 8: a new schedule must be able to read what the matrix already holds.

        Released amounts are stored in the schedule currency they were judged in and are summed as
        such, so a schedule in another currency would add euros as pounds. An item whose type the
        new schedule does not know could not be evaluated at all. Both are refused, by name.
        """
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        new = await resolve_catalogue(
            self.session, source, sid, version, kind=AUTHORITY_SCHEDULE_KIND, tenant_id=tenant_id
        )
        new_ccy = self.schedule_currency(new, project)
        held = sorted({r.schedule_currency for r in await self.repo.list_releases(matrix.project_id)} - {new_ccy})
        if held:
            raise conflict("schedule_currency_mismatch", detail=f"{', '.join(held)} -> {new_ccy}")
        types = {i.commitment_type for i in await self.repo.list_items(matrix.project_id) if i.status not in ENDED}
        missing = sorted(types - new.type_codes())
        if missing:
            raise conflict("schedule_type_mismatch", detail=", ".join(missing))

    # ── authority assignments and generated tier routes ────────────────────

    async def put_assignments(
        self, project_id: uuid.UUID, rows: list[dict[str, Any]], *, actor_id: uuid.UUID, today: date
    ) -> list[AuthorityAssignment]:
        """Replace the project's assignments; then regenerate untouched tier routes."""
        from app.modules.project_governance.public import user_can_access_project

        await self.require_matrix(project_id, lock=True)
        for r in rows:
            if not r.get("user_id"):
                # A deputy or a validity window describes an approver; without one there is nothing
                # to stand in for and nothing to limit.
                raise CommitmentError("assignment_needs_approver", 422, detail=str(r.get("project_role") or ""))
            for key in ("user_id", "deputy_user_id"):
                if r.get(key) and not await user_can_access_project(self.session, project_id, _uuid(r[key])):
                    raise CommitmentError("assignee_not_project_member", 422)
            vf, vt = _day(r.get("valid_from")), _day(r.get("valid_to"))
            if vf and vt and vt < vf:
                raise CommitmentError("assignment_window_inverted", 422)
        existing = await self.repo.list_assignments(project_id)
        for row in existing:
            await self.session.delete(row)
        await self.session.flush()
        out = []
        for r in rows:
            out.append(
                await self.repo.add(
                    AuthorityAssignment(
                        project_id=project_id,
                        project_role=str(r["project_role"]),
                        user_id=_uuid(r["user_id"]),
                        deputy_user_id=_uuid(r.get("deputy_user_id")),
                        valid_from=_s(r.get("valid_from")),
                        valid_to=_s(r.get("valid_to")),
                    )
                )
            )
        await self._audit(
            actor_id, "commitment_matrix", project_id, "assignments_replaced", metadata={"count": len(out)}
        )
        await self.generate_routes(project_id, actor_id=actor_id, today=today, force=False)
        return out

    @staticmethod
    def _active(a: AuthorityAssignment, today: date) -> bool:
        vf, vt = _day(a.valid_from), _day(a.valid_to)
        return (vf is None or vf <= today) and (vt is None or today <= vt)

    async def _tier_users(self, project_id: uuid.UUID, schedule: AuthoritySchedule, today: date) -> dict[str, list]:
        assignments = [a for a in await self.repo.list_assignments(project_id) if self._active(a, today)]
        out: dict[str, list] = {}
        for t in schedule.tiers:
            if t.approver.kind == "project_role":
                out[t.code] = [a.user_id for a in assignments if a.project_role == t.approver.ref]
            elif t.approver.kind == "user":
                out[t.code] = [_uuid(t.approver.ref)]
            else:
                out[t.code] = [t.approver.ref]
        return out

    @staticmethod
    def _fingerprint(steps: list[Any]) -> str:
        parts = [
            (s.ordinal, _s(s.approver_user_id), s.approver_role, s.mode, s.sla_hours, s.required_approver_count)
            for s in sorted(steps, key=lambda x: x.ordinal)
        ]
        return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()

    async def generate_routes(
        self, project_id: uuid.UUID, *, actor_id: uuid.UUID, today: date, force: bool
    ) -> dict[str, str]:
        """One approval route per tier from the schedule and the assignments (lead decision g).

        A route this module generated and nobody edited since is replaced; an
        edited one is kept and reported as ``edited`` unless ``force``. A tier
        nobody fills yet gets no route (``unfilled``). ``all`` tiers become one
        user step per assignee in order; ``any`` tiers one step for the first
        assignee (a stand-in is an approval_routes delegation).
        """
        from app.modules.approval_routes.schemas import RouteCreate, StepCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        matrix = await self.require_matrix(project_id, lock=True)
        schedule = await self.schedule_for(matrix)
        users = await self._tier_users(project_id, schedule, today)
        svc = ApprovalRouteService(self.session)
        report: dict[str, str] = {}
        tier_routes = dict(matrix.tier_routes or {})
        generated = dict(matrix.generated_routes or {})
        for tier in schedule.tiers:
            approvers = [u for u in users.get(tier.code, []) if u]
            if not approvers:
                report[tier.code] = "unfilled"
                continue
            if tier.approver.kind == "role":
                steps = [
                    StepCreate(
                        ordinal=1, approver_role=str(approvers[0]), mode=tier.steps_mode, sla_hours=tier.sla_hours
                    )
                ]
            else:
                chosen = approvers if tier.steps_mode == "all" else approvers[:1]
                steps = [
                    StepCreate(ordinal=i + 1, approver_user_id=u, mode="any", sla_hours=tier.sla_hours)
                    for i, u in enumerate(chosen)
                ]
            prev = generated.get(tier.code) or {}
            prev_id = _uuid(prev.get("route_id"))
            current = tier_routes.get(tier.code)
            if current and current != prev.get("route_id"):
                # A manager pinned this tier by hand: it is theirs until they unpin it, forced or not.
                report[tier.code] = "pinned"
                continue
            if prev_id is not None:
                try:
                    prev_route = await svc.get_route(prev_id)
                    prev_steps = await svc.list_steps(prev_id)
                except Exception:
                    prev_route, prev_steps = None, []
                if prev_route is not None:
                    edited = self._fingerprint(prev_steps) != prev.get("fingerprint") or prev_route.name != prev.get(
                        "name"
                    )
                    if edited and not force:
                        report[tier.code] = "edited"
                        continue
                    wanted = [(s.ordinal, _s(s.approver_user_id), s.approver_role) for s in steps]
                    have = [(s.ordinal, _s(s.approver_user_id), s.approver_role) for s in prev_steps]
                    if not edited and wanted == sorted(have) and prev_route.is_active:
                        report[tier.code] = "unchanged"
                        continue
                    prev_route.is_active = False
            name = f"commitment release: {tier.code}"
            route = await svc.create_route(
                RouteCreate(project_id=project_id, name=name, target_kind=TARGET_KIND, steps=steps),
                created_by=actor_id,
            )
            # No ``system_key``: it is unique across all projects and marks a
            # locked preset. The matrix tracks its routes in ``tier_routes``.
            new_steps = await svc.list_steps(route.id)
            generated[tier.code] = {
                "route_id": str(route.id),
                "fingerprint": self._fingerprint(new_steps),
                "name": name,
            }
            tier_routes[tier.code] = str(route.id)
            report[tier.code] = "replaced" if prev_id else "created"
        matrix.tier_routes = tier_routes
        matrix.generated_routes = generated
        await self.session.flush()
        await self._audit(actor_id, "commitment_matrix", matrix.id, "tier_routes_generated", metadata=report)
        return report

    async def pin_tier_route(
        self, project_id: uuid.UUID, tier_code: str, route_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> CommitmentMatrix:
        """A manager pins a hand-built route for one tier instead of the generated one."""
        from app.modules.approval_routes.service import ApprovalRouteService

        matrix = await self.require_matrix(project_id, lock=True)
        schedule = await self.schedule_for(matrix)
        if tier_code not in schedule.tier_order():
            raise CommitmentError("tier_unknown", 422)
        try:
            route = await ApprovalRouteService(self.session).get_route(route_id)
        except Exception as exc:
            raise not_found("route_not_found") from exc
        if route.target_kind != TARGET_KIND:
            raise not_found("route_not_found")
        if route.project_id is None:
            # A route without a project is shared by every project of the install and has no
            # tenant: pinning one would let people outside this project decide its releases.
            raise CommitmentError("route_must_belong_to_project", 422)
        if route.project_id != project_id:
            raise not_found("route_not_found")
        routes = dict(matrix.tier_routes or {})
        routes[tier_code] = str(route_id)
        matrix.tier_routes = routes
        # The manager accepts the route as it stands now. Its steps can still be edited by anyone who
        # may write routes, so a release is only started on a route whose steps match this record.
        generated = dict(matrix.generated_routes or {})
        generated[tier_code] = {
            "pinned": {
                "route_id": str(route_id),
                "fingerprint": self._fingerprint(await ApprovalRouteService(self.session).list_steps(route_id)),
                "accepted_by": str(actor_id),
            }
        }
        matrix.generated_routes = generated
        await self.session.flush()
        await self._audit(
            actor_id, "commitment_matrix", matrix.id, "tier_route_pinned", metadata={tier_code: str(route_id)}
        )
        return matrix

    async def route_states(self, matrix: CommitmentMatrix) -> dict[str, str]:
        """Per tier: ``generated``, ``pinned``, ``changed`` (edited since accepted; a manager pins it
        again before a release can be requested), or ``none`` when the tier has no usable route."""
        from app.modules.approval_routes.service import ApprovalRouteService

        routes = ApprovalRouteService(self.session)
        out: dict[str, str] = {}
        for tier_code, raw in (matrix.tier_routes or {}).items():
            route_id = _uuid(raw)
            route = await routes.repo.get_route(route_id) if route_id else None
            if route is None or not route.is_active or route.project_id != matrix.project_id:
                out[tier_code] = "none"
            elif not await self._route_accepted(matrix, tier_code, route.id):
                out[tier_code] = "changed"
            else:
                entry = (matrix.generated_routes or {}).get(tier_code) or {}
                out[tier_code] = "generated" if entry.get("route_id") == str(route.id) else "pinned"
        return out

    async def _route_accepted(self, matrix: CommitmentMatrix, tier_code: str, route_id: uuid.UUID) -> bool:
        """Whether the route's steps are still the ones this module generated or a manager pinned."""
        from app.modules.approval_routes.service import ApprovalRouteService

        entry = (matrix.generated_routes or {}).get(tier_code) or {}
        pinned = entry.get("pinned") or {}
        if entry.get("route_id") == str(route_id):
            accepted = entry.get("fingerprint")
        elif pinned.get("route_id") == str(route_id):
            accepted = pinned.get("fingerprint")
        else:
            return False
        return accepted == self._fingerprint(await ApprovalRouteService(self.session).list_steps(route_id))

    async def unpin_tier_route(
        self, project_id: uuid.UUID, tier_code: str, *, actor_id: uuid.UUID, today: date
    ) -> CommitmentMatrix:
        """Give a tier back to the generated route (the only way a pinned route is ever replaced)."""
        matrix = await self.require_matrix(project_id, lock=True)
        schedule = await self.schedule_for(matrix)
        if tier_code not in schedule.tier_order():
            raise CommitmentError("tier_unknown", 422)
        routes = dict(matrix.tier_routes or {})
        routes.pop(tier_code, None)
        generated = dict(matrix.generated_routes or {})
        generated.pop(tier_code, None)
        matrix.tier_routes, matrix.generated_routes = routes, generated
        await self.session.flush()
        await self._audit(actor_id, "commitment_matrix", matrix.id, "tier_route_unpinned", metadata={"tier": tier_code})
        await self.generate_routes(project_id, actor_id=actor_id, today=today, force=False)
        return matrix

    # ── items ──────────────────────────────────────────────────────────────

    async def get_item(self, project_id: uuid.UUID, item_id: uuid.UUID, *, lock: bool = False) -> CommitmentItem:
        item = await self.repo.get_item(project_id, item_id, lock=lock)
        if item is None:
            raise not_found("item_not_found")
        return item

    @staticmethod
    def may_edit(item: CommitmentItem, actor_id: uuid.UUID | None, manage: bool) -> bool:
        """An item is worked on by its owner, the person who created it, or a manager.

        ``manage`` is the router's ``commitment.manage`` permission check, passed down as a
        boolean; the service never reads a role. The same function answers the ``can`` flags.
        """
        return manage or (actor_id is not None and actor_id in (item.owner_user_id, item.created_by))

    def _require_edit(self, item: CommitmentItem, actor_id: uuid.UUID | None, manage: bool) -> None:
        if not self.may_edit(item, actor_id, manage):
            raise forbidden("not_item_owner")

    async def _check_item_fields(
        self, project_id: uuid.UUID, data: dict[str, Any], schedule: AuthoritySchedule
    ) -> None:
        ctype = data.get("commitment_type")
        if ctype is not None and ctype not in schedule.type_codes():
            raise CommitmentError("commitment_type_unknown", 422)
        src = data.get("planned_source")
        if src is not None:
            if src not in PLANNED_SOURCES:
                raise CommitmentError("planned_source_invalid", 422)
            if src == "manual":
                if data.get("planned_manual_amount") in (None, "") or not data.get("currency"):
                    raise CommitmentError("manual_amount_needs_currency", 422)
                if _amount(data["planned_manual_amount"]) < 0:
                    raise CommitmentError("amount_invalid", 422)
            else:
                sid = _uuid(data.get("planned_source_id"))
                if sid is None or not await figures.planned_source_in_project(self.session, project_id, src, sid):
                    raise not_found("planned_source_not_found")
        if data.get("need_activity_id"):
            _ls, _sd, found = await figures.activity_dates(self.session, project_id, _uuid(data["need_activity_id"]))
            if not found:
                raise not_found("activity_not_found")
        if data.get("requisition_id"):
            if await figures.requisition_lead_time(self.session, project_id, _uuid(data["requisition_id"])) is None:
                raise not_found("requisition_not_found")
        if data.get("plant_item_id"):
            # Unknown, of another project, or no plant register installed: nothing this row could
            # read its dates from, so the link is not stored.
            known = await figures.plant_item_dates_of(
                self.session, project_id, _uuid(data["plant_item_id"]), today=datetime.now(UTC).date()
            )
            if known is None:
                raise not_found("plant_item_not_found")
        for flag in data.get("flags") or []:
            if flag not in {f.code for f in schedule.novelty_flags}:
                raise CommitmentError("flag_unknown", 422)
        await self._check_gate_fields(project_id, data)

    async def _check_gate_fields(self, project_id: uuid.UUID, data: dict[str, Any]) -> None:
        """Rule 22: gate evidence is asked per gate and management area, so an item that names a gate names
        its area too; otherwise no evidence call would ever see it. Both must exist in the project's
        governance model when it has one."""
        gate, area = data.get("gate_code"), data.get("governance_area_code")
        if not gate and not area:
            return
        if gate and not area:
            raise CommitmentError("governance_area_required", 422)
        from app.modules.project_governance.public import project_areas, project_catalogue, project_gates

        if await project_catalogue(self.session, project_id) is None:
            return
        if area and area not in {a.code for a in await project_areas(self.session, project_id)}:
            raise CommitmentError("governance_area_unknown", 422)
        if gate and gate not in {g.code for g in await project_gates(self.session, project_id)}:
            raise CommitmentError("gate_unknown", 422)

    async def create_item(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID, manage: bool = False
    ) -> CommitmentItem:
        if data.get("owner_user_id") not in (None, actor_id) and not manage:
            # The owner is barred from approving (four eyes): only a manager names somebody else.
            raise forbidden("manage_required", detail="owner_user_id")
        matrix = await self.require_matrix(project_id)
        schedule = await self.schedule_for(matrix)
        await self._check_item_fields(project_id, data, schedule)
        if data.get("planned_source") != "manual":
            data = {**data, "planned_manual_amount": None}
        fields = {
            k: v for k, v in data.items() if hasattr(CommitmentItem, k) and k not in ("id", "status", "project_id")
        }
        if fields.get("planned_manual_amount") is not None:
            fields["planned_manual_amount"] = _amount(fields["planned_manual_amount"])
        if fields.get("currency"):
            fields["currency"] = norm(fields["currency"])
        if "latest_decision_date_fixed" in fields:
            fields["latest_decision_date_fixed"] = _iso_day(fields["latest_decision_date_fixed"])
        item = CommitmentItem(
            project_id=project_id,
            status="planned",
            attempt_no=1,
            owner_user_id=fields.pop("owner_user_id", None) or actor_id,
            created_by=actor_id,
            flags=list(fields.pop("flags", None) or []),
            **fields,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(item)
        except IntegrityError as exc:
            raise conflict("item_code_taken") from exc
        await self._audit(
            actor_id, "commitment_item", item.id, "created", to_status="planned", metadata={"code": item.code}
        )
        self._publish("commitment_release.item.created", {"project_id": str(project_id), "item_id": str(item.id)})
        return item

    _PATCHABLE = (
        "title",
        "commitment_type",
        "cost_line_id",
        "control_account_id",
        "cost_bearer_legal_entity_id",
        "funding_application_id",
        "risk_id",
        "governance_area_code",
        "gate_code",
        "deferred",
        "deferred_reason",
        "split_group",
        "owner_user_id",
        "planned_source",
        "planned_source_id",
        "planned_manual_amount",
        "currency",
        "need_activity_id",
        "requisition_id",
        "plant_item_id",
        "lead_time_days",
        "decision_buffer_days",
        "latest_decision_date_fixed",
        "flags",
    )

    async def update_item(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        changes: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        manage: bool = False,
    ) -> CommitmentItem:
        item = await self.get_item(project_id, item_id, lock=True)
        self._require_edit(item, actor_id, manage)
        if item.status in ENDED:
            raise conflict("item_closed")
        if changes.get("commitment_type", item.commitment_type) != item.commitment_type and item.status != "planned":
            raise conflict("type_fixed_after_release")
        for key in ("title", "commitment_type", "planned_source", "deferred", "deferred_reason", "flags"):
            # These columns are NOT NULL (``flags``: a list). An explicit null is invalid input, not a 500.
            if key in changes and changes[key] is None:
                raise CommitmentError("field_required", 422, detail=key)
        changed = {k for k, v in changes.items() if k in self._PATCHABLE and _s(getattr(item, k)) != _s(v)}
        if "flags" in changes and list(changes["flags"]) != list(item.flags or []):
            changed.add("flags")
        guarded = changed & {*GATE_FIELDS, *OWNER_FIELDS}
        refusal = self.gate_fields_refusal(item, manage) if guarded else None
        if refusal == "manage_required":
            raise forbidden(refusal, detail=", ".join(sorted(guarded)))
        if refusal:
            raise conflict(refusal, detail=", ".join(sorted(guarded)))
        split = changed & set(SPLIT_FIELDS)
        if split and await self.repo.has_release(item.id):
            # Review finding 7: the group and the flags decide the tier; they cannot move after a request.
            raise conflict("field_frozen", detail=", ".join(sorted(split)))
        merged = {**changes}
        if "planned_source" in changes or "planned_manual_amount" in changes or "currency" in changes:
            merged.setdefault("planned_source", item.planned_source)
            merged.setdefault("planned_manual_amount", item.planned_manual_amount)
            merged.setdefault("currency", item.currency)
            merged.setdefault("planned_source_id", item.planned_source_id)
        if "gate_code" in changes or "governance_area_code" in changes:
            merged.setdefault("gate_code", item.gate_code)
            merged.setdefault("governance_area_code", item.governance_area_code)
        matrix = await self.require_matrix(project_id)
        await self._check_item_fields(project_id, merged, await self.schedule_for(matrix))
        if changes.get("deferred") and not str(changes.get("deferred_reason") or item.deferred_reason).strip():
            raise CommitmentError("deferral_needs_reason", 422)
        before = {k: _s(getattr(item, k)) for k in changes if k in self._PATCHABLE}
        for k, v in changes.items():
            if k not in self._PATCHABLE:
                continue
            if k == "planned_manual_amount" and v is not None:
                v = _amount(v)
            if k == "currency" and v:
                v = norm(v)
            if k == "latest_decision_date_fixed":
                v = _iso_day(v)
            setattr(item, k, v)
        if item.planned_source != "manual":
            item.planned_manual_amount = None
        await self.session.flush()
        await self._audit(
            actor_id,
            "commitment_item",
            item.id,
            "updated",
            before_state=before,
            metadata={k: _s(getattr(item, k)) for k in before},
        )
        return item

    async def set_hold(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        hold: bool,
        actor_id: uuid.UUID,
        reason: str,
        manage: bool,
    ) -> CommitmentItem:
        item = await self.get_item(project_id, item_id, lock=True)
        self._refuse(self.hold_refusal(item, manage, hold=hold))
        if hold:
            item.status_before = item.status
            await self._fsm(item, "on_hold", actor_id, reason)
        else:
            target = item.status_before or "planned"
            item.status_before = None
            await self._fsm(item, target, actor_id, reason)
        return item

    # ── links ──────────────────────────────────────────────────────────────

    async def add_link(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        kind: str,
        document_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
        manage: bool = False,
    ) -> CommitmentLink:
        """Count a document in this item. Another project's document is 404; a document counts once (409)."""
        item = await self.get_item(project_id, item_id, lock=True)
        self._require_edit(item, actor_id, manage)
        if kind not in figures.LINK_KINDS:
            raise CommitmentError("link_kind_invalid", 422)
        if kind == "contingency_drawdown":
            raise CommitmentError("link_kind_not_supported", 422)
        if not await figures.document_in_project(self.session, project_id, kind, document_id):
            raise not_found("document_not_found")
        if item.status in ENDED:
            raise conflict("item_closed")
        if await self.repo.find_link(project_id, kind, document_id) is not None:
            raise conflict("document_linked_elsewhere")
        if kind in figures.CHANGE_KINDS:
            await self._refuse_change_away_from_its_contract(project_id, item, kind, document_id)
        elif kind == "contract":
            await self._refuse_contract_away_from_its_changes(project_id, item, document_id)
        link = CommitmentLink(
            project_id=project_id, item_id=item.id, kind=kind, target_id=document_id, created_by=actor_id
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(link)
        except IntegrityError as exc:
            raise conflict("document_linked_elsewhere") from exc
        await self._audit(
            actor_id, "commitment_item", item.id, "link_added", metadata={"kind": kind, "document_id": str(document_id)}
        )
        await self.recompute_item(project_id, item.id, actor_id=actor_id)
        return link

    async def adopt_award_drafts(self, project_id: uuid.UUID) -> int:
        """Link the contract and the order an award drafted to the item that holds the award.

        The award's own link is provenance; the money counts on the documents drafted from it, and
        those carry the award in their metadata. Without this the item never reads committed unless
        someone links the drafts by hand. A draft already linked anywhere is left alone. Returns
        the number of links written.
        """
        from app.modules.contracts.models import Contract
        from app.modules.procurement.models import PurchaseOrder

        links = await self.repo.list_links(project_id)
        award = {(lk.kind, str(lk.target_id)): lk.item_id for lk in links if lk.kind in figures.AWARD_KINDS}
        if not award:
            return 0
        linked = {(lk.kind, lk.target_id) for lk in links}
        written = 0
        for kind, model in (("contract", Contract), ("purchase_order", PurchaseOrder)):
            rows = await self.session.execute(select(model.id, model.metadata_).where(model.project_id == project_id))
            for doc_id, meta in rows.all():
                if (kind, doc_id) in linked or not isinstance(meta, dict):
                    continue
                item_id = next(
                    (
                        award[(award_kind, str(meta[key]).strip())]
                        for key, award_kind in figures.AWARD_META_KEYS.items()
                        if meta.get(key) and (award_kind, str(meta[key]).strip()) in award
                    ),
                    None,
                )
                if item_id is None:
                    continue
                item = await self.get_item(project_id, item_id, lock=True)
                if item.status in ENDED:
                    continue
                try:
                    async with self.session.begin_nested():
                        await self.repo.add(
                            CommitmentLink(project_id=project_id, item_id=item.id, kind=kind, target_id=doc_id)
                        )
                except IntegrityError:
                    # Linked by somebody else in the meantime: a document counts once.
                    continue
                await self._audit(
                    None,
                    "commitment_item",
                    item.id,
                    "award_draft_linked",
                    metadata={"kind": kind, "document_id": str(doc_id)},
                )
                await self.recompute_item(project_id, item.id, locked=item)
                written += 1
        return written

    async def overdue_items(self, project_id: uuid.UUID, *, today: date) -> list[tuple[uuid.UUID, str]]:
        """``(item id, latest decision date)`` of every item whose decision date has passed unreleased."""
        data = await self.item_views(project_id, today=today)
        return [
            (uuid.UUID(v["id"]), v["latest_decision_date"])
            for v in data["items"]
            if v["decision_overdue"] and v["latest_decision_date"]
        ]

    async def escalate_overdue(
        self, project_id: uuid.UUID, item_id: uuid.UUID, *, today: date, due: str | None = None
    ) -> bool:
        """SPEC rule 8: tell the owner and the holders of the tier that the decision date has passed.

        Once per item and decision date: the audit row of the escalation is the record, and a
        date that moves is escalated again. Returns True when notifications were sent.
        """
        from app.core.audit_log import ActivityLog

        item = await self.get_item(project_id, item_id, lock=True)
        sent = await self.session.execute(
            select(ActivityLog.metadata_).where(
                ActivityLog.entity_type == "commitment_item",
                ActivityLog.entity_id == str(item.id),
                ActivityLog.action == "decision_overdue_escalated",
            )
        )
        told = {m.get("latest_decision_date") for m in sent.scalars().all() if isinstance(m, dict)}
        if due is not None and due in told:
            # The pass that found the item overdue hands its date in: an item already told about
            # that date costs one read, not the whole project's figures again.
            return False
        due = dict(await self.overdue_items(project_id, today=today)).get(item.id)
        if due is None or due in told:
            return False
        project = await self._project(project_id)
        people: list[uuid.UUID] = [item.owner_user_id] if item.owner_user_id else []
        planned, _ccy, _note = await figures.planned_amount(self.session, item, norm(project.currency))
        if planned is not None and planned > 0:
            # The tier the planned amount calls for names who would decide. An item that cannot be
            # evaluated yet (no rate, type outside the schedule) still reaches its owner.
            try:
                route = await self._evaluate(item, planned, None, today=today)
                people += [u for u in route["holders"] if u not in people]
                people += [u for u in map(_uuid, route["approvers"]) if u is not None and u not in people]
            except CommitmentError as exc:
                logger.info("commitment: overdue item %s has no tier to tell (%s)", item.id, exc.code)
        ctx = {"project_id": str(project_id), "code": item.code, "latest_decision_date": due}
        for user in people:
            await self._notify(user, "decision_overdue", item, ctx)
        await self._audit(
            None,
            "commitment_item",
            item.id,
            "decision_overdue_escalated",
            metadata={"latest_decision_date": due, "notified": [str(u) for u in people]},
        )
        self._publish(
            "commitment_release.item.decision_overdue",
            {"project_id": str(project_id), "item_id": str(item.id), "due": due},
        )
        return True

    async def _refuse_change_away_from_its_contract(
        self, project_id: uuid.UUID, item: CommitmentItem, kind: str, document_id: uuid.UUID
    ) -> None:
        """A change is linked on the item that holds its contract, whatever the item's type (rule 7).

        Once the contract's header carries the change, the money sits on the contract's item. A
        release decided on another item would then cover nothing, and the contract's item would ask
        for a new release of money that was released elsewhere.
        """
        contract_id = (await figures.change_host(self.session, project_id, kind, document_id)).contract_id
        if contract_id is None:
            return
        host = await self.repo.find_link(project_id, "contract", contract_id)
        if host is not None and host.item_id != item.id:
            raise CommitmentError("change_belongs_to_contract_item", 422)

    async def _refuse_contract_away_from_its_changes(
        self, project_id: uuid.UUID, item: CommitmentItem, contract_id: uuid.UUID
    ) -> None:
        """The same shape from the other side: a contract joins the item its linked changes are on."""
        for lk in await self.repo.list_links(project_id):
            if lk.kind not in figures.CHANGE_KINDS or lk.item_id == item.id:
                continue
            if (await figures.change_host(self.session, project_id, lk.kind, lk.target_id)).contract_id == contract_id:
                raise CommitmentError("change_belongs_to_contract_item", 422)

    async def remove_link(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        link_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        manage: bool = False,
    ) -> None:
        item = await self.get_item(project_id, item_id, lock=True)
        self._require_edit(item, actor_id, manage)
        if item.status in ENDED:
            raise conflict("item_closed")
        links = [lk for lk in await self.repo.list_links(project_id, [item.id]) if lk.id == link_id]
        if not links:
            raise not_found("link_not_found")
        await self.session.delete(links[0])
        await self.session.flush()
        await self._audit(
            actor_id,
            "commitment_item",
            item.id,
            "link_removed",
            metadata={"kind": links[0].kind, "document_id": str(links[0].document_id)},
        )
        await self.recompute_item(project_id, item.id, actor_id=actor_id)

    # ── preconditions ──────────────────────────────────────────────────────

    async def add_precondition(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        kind: str,
        ref_id: str | None,
        text: str,
        actor_id: uuid.UUID,
        manage: bool = False,
    ) -> CommitmentPrecondition:
        item = await self.get_item(project_id, item_id)
        self._require_edit(item, actor_id, manage)
        if item.status in ENDED:
            raise conflict("item_closed")
        if kind not in PRECONDITION_KINDS:
            raise CommitmentError("precondition_kind_invalid", 422)
        if kind in ("gate_decided", "frame_document_binding", "funding_approved") and not ref_id:
            raise CommitmentError("precondition_needs_ref", 422)
        self._refuse_with(await self.precondition_ref_refusal(project_id, kind, ref_id))
        row = await self.repo.add(
            CommitmentPrecondition(
                project_id=project_id, item_id=item.id, kind=kind, ref_id=ref_id, text=text, state="open"
            )
        )
        await self._audit(
            actor_id, "commitment_item", item.id, "precondition_added", metadata={"kind": kind, "ref": ref_id}
        )
        return row

    @staticmethod
    def _refuse_with(refusal: tuple[str, int] | None) -> None:
        if refusal is not None:
            raise CommitmentError(refusal[0], refusal[1])

    async def linked_targets(self, project_id: uuid.UUID, rows: Any) -> dict[str, Any]:
        """What the linked preconditions in ``rows`` can name, read once for all of them.

        The governance port is asked once for gates and once for frame documents, and the funding
        applications are one query, however many rows and items there are; a kind no row uses is
        not read at all.
        """
        kinds = {p.kind for p in rows}
        targets: dict[str, Any] = {"gates": (), "documents": (), "funding": {}}
        if "gate_decided" in kinds:
            from app.modules.project_governance.public import project_gates

            targets["gates"] = await project_gates(self.session, project_id)
        if "frame_document_binding" in kinds:
            from app.modules.project_governance.public import project_documents

            targets["documents"] = await project_documents(self.session, project_id)
        wanted = {_ref_uuid(p.ref_id) for p in rows if p.kind == "funding_approved"} - {None}
        if wanted:
            from app.modules.funding.models import FundingApplication

            found = await self.session.execute(
                select(FundingApplication.id, FundingApplication.status).where(
                    FundingApplication.project_id == project_id, FundingApplication.id.in_(wanted)
                )
            )
            targets["funding"] = {row.id: row.status for row in found}
        return targets

    @staticmethod
    def linked_verdict(kind: str, ref_id: str | None, targets: dict[str, Any]) -> tuple[str, str | None]:
        """``(state, unreachable_reason)`` of a linked precondition against ``linked_targets``.

        The reason is set when the precondition names a gate of a project without gates, or a gate,
        document or application the project does not have: it can then never be met.
        """
        if kind == "gate_decided":
            if not targets["gates"]:
                return "open", "gates_not_in_use"
            mine = [g for g in targets["gates"] if g.code == ref_id]
            if not mine:
                return "open", "gate_unknown"
            ok = any(g.status == "decided" and g.last_outcome.startswith("go") for g in mine)
            return ("met" if ok else "open"), None
        if kind == "frame_document_binding":
            wanted = _ref_uuid(ref_id)
            mine = [d for d in targets["documents"] if d.id == wanted]
            if not mine:
                return "open", "frame_document_not_found"
            return ("met" if any(d.status == "binding" for d in mine) else "open"), None
        if kind == "funding_approved":
            wanted = _ref_uuid(ref_id)
            if wanted not in targets["funding"]:
                return "open", "funding_application_not_found"
            return ("met" if targets["funding"][wanted] == "approved" else "open"), None
        raise ValueError(f"not a linked precondition kind: {kind}")

    async def precondition_ref_refusal(
        self, project_id: uuid.UUID, kind: str, ref_id: str | None
    ) -> tuple[str, int] | None:
        """Why a linked precondition cannot wait for what it names: ``(code, status)`` or ``None``.

        A precondition that is read from another module is met only by that module. One that names a
        gate of a project without gates, or a document or application the project does not have,
        could never be met and never be ticked by hand, and under ``block`` the item could then
        never be released. So it is not stored. A project that does not use gates waits for no gate.
        """
        if kind not in LINKED_PRECONDITIONS:
            return None
        row = SimpleNamespace(kind=kind, ref_id=ref_id)
        reason = self.linked_verdict(kind, ref_id, await self.linked_targets(project_id, [row]))[1]
        if reason is None:
            return None
        return reason, (422 if reason in ("gates_not_in_use", "gate_unknown") else 404)

    @staticmethod
    def remove_precondition_refusal(item: CommitmentItem, manage: bool) -> str | None:
        """Why this person may not take a precondition off the item now; the same for every row of it."""
        if not manage:
            return "manage_required"
        if item.status in ENDED:
            return "item_closed"
        # The running request was judged with its preconditions on it.
        return "release_pending" if item.status == "release_requested" else None

    async def remove_precondition(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        precondition_id: uuid.UUID,
        *,
        reason: str,
        actor_id: uuid.UUID,
        manage: bool = False,
    ) -> None:
        """Take a precondition off an item: a manager, with a reason, while no request is running.

        Without this a precondition added by mistake, or one that waits for a gate the project does
        not have, stays for ever. The reason and who removed it are recorded.
        """
        item = await self.get_item(project_id, item_id, lock=True)
        self._refuse(self.remove_precondition_refusal(item, manage))
        if not reason.strip():
            raise CommitmentError("rationale_required", 422)
        row = await self.repo.get_precondition(project_id, item_id, precondition_id)
        if row is None:
            raise not_found("precondition_not_found")
        meta = {"kind": row.kind, "ref": row.ref_id, "text": row.text, "state": row.state, "reason": reason.strip()}
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "commitment_item", item.id, "precondition_removed", metadata=meta)

    async def confirm_precondition(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        precondition_id: uuid.UUID,
        *,
        met: bool,
        evidence_ref: str,
        actor_id: uuid.UUID,
        manage: bool = False,
    ) -> CommitmentPrecondition:
        item = await self.get_item(project_id, item_id, lock=True)
        self._require_edit(item, actor_id, manage)
        if item.status in ENDED:
            raise conflict("item_closed")
        row = await self.repo.get_precondition(project_id, item_id, precondition_id)
        if row is None:
            raise not_found("precondition_not_found")
        if row.kind not in STORED_PRECONDITIONS or (precondition_reader(row.kind) is not None and row.ref_id):
            raise CommitmentError("precondition_is_computed", 422)
        if met and row.kind == "public_commitment_appropriation" and not evidence_ref.strip():
            raise CommitmentError("precondition_needs_evidence", 422)
        row.state = "met" if met else "open"
        row.evidence_ref = evidence_ref
        row.confirmed_by = actor_id if met else None
        row.confirmed_at = datetime.now(UTC) if met else None
        await self.session.flush()
        await self._audit(
            actor_id,
            "commitment_item",
            item_id,
            "precondition_confirmed" if met else "precondition_reopened",
            metadata={"precondition_id": str(row.id)},
        )
        return row

    async def precondition_states(
        self,
        project_id: uuid.UUID,
        rows: list[CommitmentPrecondition],
        *,
        planned: Decimal | None,
        cumulative: Decimal,
        targets: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Each precondition with its state; linked kinds are read from their modules now.

        ``targets`` is ``linked_targets`` of at least these rows; a caller that reads many items
        passes the one it loaded for all of them.
        """
        if targets is None:
            targets = await self.linked_targets(project_id, rows)
        out = []
        for p in rows:
            state = p.state
            # Set when the row was stored before the check on write existed, or its target was
            # removed since: it can never be met, and the screen says so.
            unreachable = None
            if p.kind in LINKED_PRECONDITIONS:
                state, unreachable = self.linked_verdict(p.kind, p.ref_id, targets)
            elif p.kind == "budget_available":
                state = "met" if planned is not None and cumulative <= planned else "open"
            reader = precondition_reader(p.kind)
            if reader is not None and p.ref_id:
                # A module that owns this kind of record (a permit register) answers for it; the
                # stored tick is only the answer while nothing does.
                state = "met" if await reader(self.session, project_id, p.ref_id) else "open"
            out.append(
                {
                    "id": str(p.id),
                    "kind": p.kind,
                    "ref_id": p.ref_id,
                    "text": p.text,
                    "state": state,
                    "unreachable_reason": unreachable,
                    "evidence_ref": p.evidence_ref,
                    "confirmed_by": _s(p.confirmed_by),
                    "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
                }
            )
        return out

    async def _successor(self, item: CommitmentItem, actor_id: uuid.UUID | None) -> dict[str, Any] | None:
        """Where a handed-over item went. The ids always; ``can_open`` and the names only for a reader who may open
        the receiving project, so a hand-over does not publish another project's titles."""
        from app.modules.project_governance.public import user_can_access_project

        if item.transferred_to_item_id is None:
            return None
        target = await self.session.get(CommitmentItem, item.transferred_to_item_id)
        if target is None:
            return None
        same = target.project_id == item.project_id
        can_open = same or (
            actor_id is not None and await user_can_access_project(self.session, target.project_id, actor_id)
        )
        project = await self._project(target.project_id) if can_open else None
        return {
            "project_id": str(target.project_id),
            "item_id": str(target.id),
            "same_project": same,
            "can_open": can_open,
            "project_name": project.name if project is not None else None,
            "code": target.code if can_open else None,
            "title": target.title if can_open else None,
        }

    async def linked_state(self, project_id: uuid.UUID, kind: str, ref_id: str | None) -> str:
        """The state of one linked precondition, read now."""
        row = SimpleNamespace(kind=kind, ref_id=ref_id)
        return self.linked_verdict(kind, ref_id, await self.linked_targets(project_id, [row]))[0]

    # ── derived figures ────────────────────────────────────────────────────

    async def committed_for_items(
        self, matrix: CommitmentMatrix, project: Any, schedule: AuthoritySchedule, *, on_date: date
    ) -> tuple[dict[uuid.UUID, list[figures.LinkFigure]], dict[uuid.UUID, Decimal | None], dict[uuid.UUID, str | None]]:
        """``(figures per item, committed in schedule currency or None, reason)`` over the whole project."""
        links = await self.repo.list_links(matrix.project_id)
        figs = await figures.link_figures(self.session, matrix.project_id, links, basis=schedule.basis)
        target = self.schedule_currency(schedule, project)
        per_item: dict[uuid.UUID, list[figures.LinkFigure]] = {}
        for f in figs:
            per_item.setdefault(f.item_id, []).append(f)
        committed: dict[uuid.UUID, Decimal | None] = {}
        reason: dict[uuid.UUID, str | None] = {}
        for item_id, fl in per_item.items():
            try:
                committed[item_id] = await self.item_committed(matrix, project, target, fl, on_date=on_date)
                reason[item_id] = None
            except FxRateMissing:
                committed[item_id], reason[item_id] = None, "fx_rate_missing"
        return per_item, committed, reason

    async def item_committed(
        self,
        matrix: CommitmentMatrix,
        project: Any,
        target_currency: str,
        figs: list[figures.LinkFigure],
        *,
        on_date: date,
        without_link: uuid.UUID | None = None,
        plus: tuple[tuple[Decimal, str], ...] = (),
    ) -> Decimal:
        """What one item commits, in ``target_currency``. The ONE sum behind the matrix, recompute and the guard.

        The guard asks the same question for a document that is about to change: ``without_link``
        leaves that document's present figure out and ``plus`` adds what it would become.

        Raises:
            FxRateMissing: a figure has no rate into the target; never converted 1:1.
        """
        parts = [(f.amount, f.currency) for f in figs if f.amount and f.link_id != without_link]
        total = ZERO
        for amount, currency in [*parts, *plus]:
            total += (await self.quote(matrix, project, currency, target_currency, on_date)).apply(amount)
        return total

    @staticmethod
    def released_in_schedule_currency(releases: list[ReleaseDecision]) -> Decimal:
        return sum(
            (r.amount_in_schedule_currency for r in releases if r.purpose == "release" and r.outcome == "released"),
            ZERO,
        )

    @staticmethod
    def expired_in_schedule_currency(releases: list[ReleaseDecision], day: date) -> Decimal:
        """The released money whose ``valid_until`` lies before ``day`` (the server day, never a caller's)."""
        return sum(
            (
                r.amount_in_schedule_currency
                for r in releases
                if r.purpose == "release"
                and r.outcome == "released"
                and r.valid_until
                and r.valid_until < day.isoformat()
            ),
            ZERO,
        )

    async def item_views(
        self,
        project_id: uuid.UUID,
        *,
        today: date,
        item_ids: list[uuid.UUID] | None = None,
        with_exposure: bool = False,
        actor_id: uuid.UUID | None = None,
        manage: bool = False,
    ) -> dict[str, Any]:
        """Items with every derived figure, flag and (optionally) abort exposure, plus base-currency totals.

        ``can`` on each item says what ``actor_id`` may do to it now, each with the refusal code when
        not. It is answered by the very functions the writes enforce, so a button and its 4xx agree.
        """
        matrix = await self.require_matrix(project_id)
        project = await self._project(project_id)
        schedule = await self.schedule_for(matrix)
        sched_ccy = self.schedule_currency(schedule, project)
        base = norm(project.currency)
        items = await self.repo.list_items(project_id)
        if item_ids is not None:
            items = [i for i in items if i.id in set(item_ids)]
        ids = [i.id for i in items]
        releases = await self.repo.list_releases(project_id, ids)
        pre = await self.repo.list_preconditions(project_id, ids)
        pre_targets = await self.linked_targets(project_id, pre)
        terms = await self.repo.list_abort_terms(project_id, ids) if with_exposure else []
        per_item, committed, committed_reason = await self.committed_for_items(matrix, project, schedule, on_date=today)
        tol = schedule.variation_tolerance
        views = []
        totals = {"planned": ZERO, "released": ZERO, "released_in_force": ZERO, "committed": ZERO}
        # One read of the plant register for every linked item of this read.
        plants = await figures.plant_items_dates_of(
            self.session, project_id, [i.plant_item_id for i in items if i.plant_item_id is not None], today=today
        )
        unconverted: set[str] = set()
        currencies: set[str] = set()
        for item in items:
            rel = [r for r in releases if r.item_id == item.id]
            released = self.released_in_schedule_currency(rel)
            planned, planned_ccy, planned_note = await figures.planned_amount(self.session, item, base)
            late, start, _found = await figures.activity_dates(self.session, project_id, item.need_activity_id)
            plant = plants.get(item.plant_item_id) if item.plant_item_id is not None else None
            lead, lead_source = ev.lead_time_in_force(
                plant_item_days=plant.lead_time_days if plant is not None else None,
                own_days=item.lead_time_days,
                requisition_days=await figures.requisition_lead_time(self.session, project_id, item.requisition_id)
                if item.lead_time_days is None
                else None,
            )
            dd = ev.decision_date_for_item(
                plant_latest_order=plant.latest_order_date if plant is not None else None,
                plant_need_date=plant.need_date if plant is not None else None,
                late_start=late,
                start_date=start,
                fixed=item.latest_decision_date_fixed,
                lead_time_days=lead,
                decision_buffer_days=item.decision_buffer_days,
            )
            planned_sched = None
            if planned is not None:
                try:
                    planned_sched = (await self.quote(matrix, project, planned_ccy, sched_ccy, today)).apply(planned)
                except FxRateMissing:
                    planned_sched = None
            required_now = None
            if planned_sched is not None and planned_sched > 0 and item.commitment_type in schedule.type_codes():
                r = ev.required_tier(schedule, item.commitment_type, max(planned_sched, released), item.flags or [])
                required_now = r.tier_code or ev.ESCALATE_OUTSIDE
            comm = committed.get(item.id, ZERO)
            ceiling = ev.tolerance_ceiling(released, parse_amount(tol.absolute), parse_amount(tol.percent))
            pre_states = await self.precondition_states(
                project_id,
                [p for p in pre if p.item_id == item.id],
                planned=planned_sched,
                cumulative=released,
                targets=pre_targets,
            )
            expired = self.expired_in_schedule_currency(rel, today)
            in_force = ev.release_in_force(released, expired, comm) if comm is not None else None
            if comm is None:
                new_money = "fx_rate_missing"
            elif in_force > comm:
                new_money = None
            else:
                # Nothing left to bind: because a release ran out of date, or because none covers more.
                new_money = "release_expired" if in_force < released else "commitment_not_released"
            view = {
                "released_in_force": _money_str(in_force),
                # True while the passed date is what stops further money; a renewal clears it.
                "release_expired": new_money == "release_expired",
                "released_lapsed": _money_str(released - in_force) if in_force is not None else None,
                "expired_release_dates": sorted(
                    {
                        r.valid_until
                        for r in rel
                        if r.purpose == "release"
                        and r.outcome == "released"
                        and r.valid_until
                        and r.valid_until < today.isoformat()
                    }
                ),
                "id": str(item.id),
                "code": item.code,
                "title": item.title,
                "commitment_type": item.commitment_type,
                "status": item.status,
                "attempt_no": item.attempt_no,
                "flags": list(item.flags or []),
                "cost_line_id": _s(item.cost_line_id),
                "control_account_id": _s(item.control_account_id),
                "cost_bearer_legal_entity_id": _s(item.cost_bearer_legal_entity_id or matrix.legal_entity_id),
                "funding_application_id": _s(item.funding_application_id),
                "risk_id": _s(item.risk_id),
                "governance_area_code": item.governance_area_code,
                "gate_code": item.gate_code,
                "deferred": item.deferred,
                "deferred_reason": item.deferred_reason,
                "split_group": item.split_group,
                "owner_user_id": _s(item.owner_user_id),
                "planned_source": item.planned_source,
                "planned_source_id": _s(item.planned_source_id),
                "need_activity_id": _s(item.need_activity_id),
                "requisition_id": _s(item.requisition_id),
                "lead_time_days": item.lead_time_days,
                "plant_item_id": _s(item.plant_item_id),
                # The plant item as the register names it; null when unlinked or no longer known there.
                "plant_item_code": plant.code if plant is not None else None,
                # The row names a plant item the register does not answer for (removed there, or the
                # plant register is not installed): the row's own figures are in force.
                "plant_item_missing": item.plant_item_id is not None and plant is None,
                # The register's own status, when it serves one. A cancelled item still gives its dates.
                "plant_item_status": getattr(plant, "status", None) if plant is not None else None,
                "plant_item_cancelled": plant is not None and getattr(plant, "status", None) == "cancelled",
                "lead_time_in_force_days": lead,
                "lead_time_source": lead_source,
                "decision_buffer_days": item.decision_buffer_days,
                "latest_decision_date_fixed": item.latest_decision_date_fixed,
                "planned": {"amount": _money_str(planned), "currency": planned_ccy, "note": planned_note},
                "schedule_currency": sched_ccy,
                "planned_in_schedule_currency": _money_str(planned_sched),
                "released": _money_str(released),
                "committed": _money_str(comm),
                "committed_reason": committed_reason.get(item.id),
                "release_ceiling_with_tolerance": _money_str(ceiling),
                "over_release": comm is not None and comm > ceiling,
                "required_tier_for_planned": required_now,
                "latest_decision_date": dd.latest.isoformat() if dd.latest else None,
                "date_basis": dd.basis,
                "decision_overdue": ev.decision_overdue(dd.latest, today, item.status, released),
                "preconditions": pre_states,
                "open_preconditions": sum(1 for p in pre_states if p["state"] != "met"),
                "links": [f.as_dict() for f in per_item.get(item.id, [])],
                "pending_release_id": next((str(r.id) for r in rel if r.outcome == "pending"), None),
                "pending_purpose": next((r.purpose for r in rel if r.outcome == "pending"), None),
                "transferred_to_item_id": _s(item.transferred_to_item_id),
                "transferred_to": await self._successor(item, actor_id),
                "abort": self._abort_out(rel, per_item.get(item.id, [])),
                "can": {
                    **await self._can(
                        item, next((r for r in rel if r.outcome == "pending"), None), actor_id, manage, today
                    ),
                    # Whether a further contract, order or change could be bound under this item now.
                    "commit_new": {"allowed": new_money is None, "reason": new_money},
                },
            }
            if with_exposure:
                view["exposure"] = await self._exposure_for(
                    item,
                    per_item.get(item.id, []),
                    [t for t in terms if t.item_id == item.id],
                    matrix,
                    project,
                    today,
                    basis=schedule.basis,
                )
            views.append(view)
            currencies.add(sched_ccy)
            for key, value in (
                ("planned", planned_sched),
                ("released", released),
                # What a reader may still count as authority: never the lapsed part of a release.
                ("released_in_force", in_force),
                ("committed", comm),
            ):
                if value is None:
                    unconverted.add(key)
                    continue
                try:
                    totals[key] += (await self.quote(matrix, project, sched_ccy, base, today)).apply(value)
                except FxRateMissing:
                    unconverted.add(key)
            currencies.add(planned_ccy)
        return {
            "items": views,
            "totals": {
                "currency": base,
                **{k: _money_str(v) for k, v in totals.items()},
                "released_lapsed": _money_str(totals["released"] - totals["released_in_force"])
                if not {"released", "released_in_force"} & unconverted
                else None,
                "mixed_currency": len({c for c in currencies if c}) > 1,
                "incomplete": sorted(unconverted),
            },
        }

    @staticmethod
    def _abort_out(releases: list[ReleaseDecision], figs: list[figures.LinkFigure]) -> dict[str, Any] | None:
        """The decided abort of an item and the documents whose own termination follows it (rule 15).

        This module ends the item, never a document: ``follow_up`` names each linked contract or
        purchase order that still binds money, for the screen to link to that document's own action.
        """
        done = next((r for r in reversed(releases) if r.purpose == "abort" and r.outcome == "aborted"), None)
        if done is None:
            return None
        follow_up = [
            {
                "kind": f.kind,
                "document_id": str(f.document_id),
                "action": "terminate" if f.kind == "contract" else "cancel",
                "status": f.status,
            }
            for f in figs
            if f.kind in ("contract", "purchase_order") and f.found and f.counts and not f.closed
        ]
        return {
            "release_id": str(done.id),
            "decided_at": done.decided_at.isoformat() if done.decided_at else None,
            "decided_by": _s(done.decided_by),
            "reason": done.tranche_note,
            "residual_loss": str(done.requested_amount),
            "currency": done.currency,
            "follow_up": follow_up,
        }

    async def _can(
        self,
        item: CommitmentItem,
        pending: ReleaseDecision | None,
        actor_id: uuid.UUID | None,
        manage: bool,
        today: date,
    ) -> dict[str, dict[str, Any]]:
        def flag(code: str | None) -> dict[str, Any]:
            return {"allowed": code is None, "reason": code}

        decide = "no_pending_release"
        if pending is not None:
            decide = (await self._decide_check(item, pending, actor_id, today))[0]
        request = self.request_refusal(item, actor_id, manage)
        return {
            "edit": flag(self.edit_refusal(item, actor_id, manage)),
            "link": flag(self.edit_refusal(item, actor_id, manage)),
            "request_release": flag(request),
            "request_abort": flag(request),
            "withdraw": flag(self.withdraw_refusal(pending, actor_id, manage)),
            "decide": flag(decide),
            "hold": flag(self.hold_refusal(item, manage, hold=True)),
            "resume": flag(self.hold_refusal(item, manage, hold=False)),
            "transfer": flag(self.transfer_refusal(item, manage)),
            "defer": flag(self.defer_refusal(item, manage)),
            "edit_gate_fields": flag(self.gate_fields_refusal(item, manage)),
            # One verdict for every precondition of the item; the rows do not differ. ``applies`` is
            # false on an ended item, where removal does not exist: the screen hides the action there
            # and shows it disabled with the reason otherwise.
            "remove_precondition": {
                **flag(self.remove_precondition_refusal(item, manage)),
                "applies": item.status not in ENDED,
            },
        }

    # ── abort exposure ─────────────────────────────────────────────────────

    async def _terms_input(self, row: AbortTerms) -> tuple[TermsInput, AbortBasis | None]:
        from app.modules.project_governance.errors import GovernanceError

        basis = None
        if row.basis_code:
            try:
                basis = await self.abort_basis(row.basis_source, row.basis_code, row.basis_version)
            except GovernanceError:
                # The pinned basis no longer resolves: the exposure says so (``abort_basis_unknown``).
                basis = None
        terms = TermsInput(
            basis_code=row.basis_code,
            cancellation_schedule=tuple(_schedule_entry(e) for e in row.cancellation_schedule or []),
            transfer_value=row.transfer_value_estimate,
            salvage_value=row.salvage_value_estimate,
            saved_cost=row.saved_cost_estimate,
            other_charge=row.other_charge_estimate,
            parameters={k: str(v) for k, v in (row.parameters or {}).items()},
        )
        return terms, basis

    async def _exposure_for(
        self,
        item: CommitmentItem,
        figs: list[figures.LinkFigure],
        terms_rows: list[AbortTerms],
        matrix: CommitmentMatrix,
        project: Any,
        as_of: date,
        basis: str = "net",
    ) -> dict[str, Any]:
        """Abort exposure of one item in base currency (SPEC rule 14). ``basis`` is the schedule's net or gross.

        Terms entered for one linked document apply to that document's committed and sunk money;
        the item's own terms apply to everything else. Each part is computed on its own and the
        parts are added, and one unknown part makes the item's residual unknown, never a partial sum.
        """
        base = norm(project.currency)
        by_scope = {t.scope: t for t in terms_rows}
        # scope -> [committed, sunk parts] in base currency; "item" takes every link without own terms.
        groups: dict[str, list[Any]] = {}
        try:
            raw_sunk = await figures.sunk_by_link(self.session, item.project_id, figs, basis=basis)
            for f in figs:
                scope = str(f.link_id) if str(f.link_id) in by_scope else "item"
                group = groups.setdefault(scope, [ZERO, dict.fromkeys(figures.SUNK_PARTS, ZERO)])
                if f.amount:
                    group[0] += (await self.quote(matrix, project, f.currency, base, as_of)).apply(f.amount)
                for part, amount, ccy in raw_sunk.get(f.link_id, []):
                    group[1][part] += (await self.quote(matrix, project, ccy or base, base, as_of)).apply(amount)
        except FxRateMissing:
            return {"residual_loss": None, "reason": "fx_rate_missing", "currency": base}
        if "item" not in groups and ("item" in by_scope or not groups):
            groups["item"] = [ZERO, dict.fromkeys(figures.SUNK_PARTS, ZERO)]
        parts: list[tuple[str, Any, AbortTerms | None]] = []
        for scope, (committed, sunk) in groups.items():
            row = by_scope.get(scope)
            terms, basis = await self._terms_input(row) if row is not None else (None, None)
            e = compute_exposure(
                committed=committed,
                sunk_parts=sunk,
                terms=terms,
                basis=basis,
                as_of=as_of,
                progress_pct=row.progress_pct if row is not None else None,
            )
            parts.append((scope, e, row))
        if len(parts) == 1:
            scope, e, row = parts[0]
            out = e.as_dict()
        else:
            out = combine_exposures([e for _s, e, _r in parts]).as_dict()
            out["parts"] = [{"scope": scope, **e.as_dict()} for scope, e, _r in parts]
            row = by_scope.get("item")
        out["currency"] = base
        out["as_of"] = as_of.isoformat()
        out["basis_code"] = row.basis_code if row is not None else None
        out["transferable"] = row.transferable if row is not None else None
        return out

    async def exposure(self, project_id: uuid.UUID, *, as_of: date) -> dict[str, Any]:
        """Per-item exposure and the project total, with the count of items whose residual is unknown."""
        data = await self.item_views(project_id, today=as_of, with_exposure=True)
        total = ZERO
        unknown = 0
        rows = []
        for v in data["items"]:
            e = v["exposure"]
            if e.get("residual_loss") is None:
                unknown += 1
            else:
                total += Decimal(e["residual_loss"])
            rows.append({"item_id": v["id"], "code": v["code"], "status": v["status"], **e})
        return {
            "as_of": as_of.isoformat(),
            "currency": data["totals"]["currency"],
            "items": rows,
            "total_residual_loss": str(total),
            "unknown_count": unknown,
        }

    async def save_scenario(
        self, project_id: uuid.UUID, *, as_of: date, label: str, actor_id: uuid.UUID
    ) -> AbortScenario:
        payload = await self.exposure(project_id, as_of=as_of)
        row = await self.repo.add(
            AbortScenario(
                project_id=project_id, as_of=as_of.isoformat(), label=label, payload=payload, created_by=actor_id
            )
        )
        await self._audit(
            actor_id, "commitment_matrix", project_id, "abort_scenario_saved", metadata={"scenario_id": str(row.id)}
        )
        return row

    async def _refuse_foreign_parameters(self, row: AbortTerms | None, data: dict[str, Any]) -> None:
        """The parameters the terms will hold after this write must belong to the basis they will name."""
        from app.modules.commitment_release.catalogue import parameter_violation

        parameters = data.get("parameters")
        if parameters is None:
            parameters = (row.parameters if row is not None else None) or {}
        if not parameters:
            return
        if "basis_code" in data:
            code, source, version = data["basis_code"], data.get("basis_source"), data.get("basis_version")
        else:
            code, source, version = (
                (row.basis_code, row.basis_source, row.basis_version) if row is not None else (None, None, None)
            )
        basis = await self.abort_basis(source or "shipped", code, version) if code else None
        violation = parameter_violation(basis, parameters)
        if violation:
            raise CommitmentError(violation[0], 422, detail=violation[1])

    async def put_abort_terms(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        manage: bool = False,
        tenant_id: str | None = None,
    ) -> AbortTerms:
        item = await self.get_item(project_id, item_id, lock=True)
        self._require_edit(item, actor_id, manage)
        scope = "item"
        if data.get("link_id"):
            link_id = _uuid(data["link_id"])
            if link_id not in {lk.id for lk in await self.repo.list_links(project_id, [item.id])}:
                raise not_found("link_not_found")
            scope = str(link_id)
        if data.get("basis_code"):
            from app.modules.project_governance.catalogue_store import CatalogueStore
            from app.modules.project_governance.errors import GovernanceError

            source = data.get("basis_source") or "shipped"
            try:
                # Review finding 5: the store checks the catalogue against the CALLER's tenant; a
                # basis of another tenant does not resolve, exactly like one that does not exist.
                version = await CatalogueStore(self.session).assert_pinnable(
                    tenant_id, source, data["basis_code"], data.get("basis_version"), kind=ABORT_BASIS_KIND
                )
            except GovernanceError as exc:
                raise CommitmentError("abort_basis_unknown", 422) from exc
            data = {**data, "basis_source": source, "basis_version": version}
        for entry in data.get("cancellation_schedule") or []:
            try:
                _schedule_entry(entry)
            except (KeyError, ValueError, TypeError) as exc:
                raise CommitmentError("cancellation_schedule_invalid", 422) from exc
        if data.get("transferable", "no") not in ("no", "to_project", "resale"):
            raise CommitmentError("transferable_invalid", 422)
        row = await self.repo.get_abort_terms(item.id, scope)
        await self._refuse_foreign_parameters(row, data)
        before = None
        if row is None:
            row = AbortTerms(project_id=project_id, item_id=item.id, scope=scope)
            self.session.add(row)
        else:
            before = {"basis_code": row.basis_code, "transferable": row.transferable}
        for key in (
            "basis_code",
            "basis_source",
            "basis_version",
            "cancellation_schedule",
            "parameters",
            "transferable",
            "notice_days",
            "source_note",
        ):
            if key in data:
                setattr(
                    row,
                    key,
                    data[key]
                    if data[key] is not None or key in ("basis_code", "basis_version", "notice_days")
                    else getattr(row, key),
                )
        for key in (
            "transfer_value_estimate",
            "salvage_value_estimate",
            "saved_cost_estimate",
            "other_charge_estimate",
            "progress_pct",
        ):
            if key in data:
                setattr(row, key, None if data[key] in (None, "") else _amount(data[key]))
        row.entered_by = actor_id
        row.entered_at = datetime.now(UTC)
        await self.session.flush()
        await self._audit(
            actor_id,
            "commitment_item",
            item.id,
            "abort_terms_set",
            before_state=before,
            metadata={"scope": scope, "basis_code": row.basis_code, "transferable": row.transferable},
        )
        return row

    # ── releases ───────────────────────────────────────────────────────────

    async def _group_others(self, item: CommitmentItem) -> Decimal:
        """What the other items of the split group already hold: released AND still pending.

        A pending request counts in full. Otherwise two items of one group could each ask for an
        amount just under a band at the same time and both be judged on their own request.
        """
        if not item.split_group:
            return ZERO
        others = [i.id for i in await self.repo.items_in_group(item.project_id, item.split_group) if i.id != item.id]
        rows = await self.repo.list_releases(item.project_id, others)
        return sum(
            (
                r.amount_in_schedule_currency
                for r in rows
                if r.purpose == "release" and r.outcome in ("released", "pending")
            ),
            ZERO,
        )

    async def _lock_for_request(self, project_id: uuid.UUID, item_id: uuid.UUID) -> CommitmentItem:
        """Lock the item, and with it every item of its split group, always in id order."""
        seen = await self.get_item(project_id, item_id)
        if seen.split_group:
            await self.repo.items_in_group(project_id, seen.split_group, lock=True)
        item = await self.get_item(project_id, item_id, lock=True)
        if item.split_group != seen.split_group:
            # The group changed between the read and the lock; the caller tries again on fresh data.
            raise conflict("item_changed")
        return item

    async def preview_release(
        self, project_id: uuid.UUID, item_id: uuid.UUID, amount: Any, currency: str | None, *, today: date
    ) -> dict[str, Any]:
        """What a release request would need, without writing: tier, approvers, FX, open preconditions."""
        item = await self.get_item(project_id, item_id)
        return await self._evaluate(item, _amount(amount), currency, today=today)

    async def _evaluate(
        self, item: CommitmentItem, amount: Decimal, currency: str | None, *, today: date
    ) -> dict[str, Any]:
        if amount <= 0:
            raise CommitmentError("amount_not_positive", 422)
        matrix = await self.require_matrix(item.project_id)
        project = await self._project(item.project_id)
        schedule = await self.schedule_for(matrix)
        if not ev.in_force(schedule, today):
            # The pinned version's own validity window has passed (or not begun): pin the one in force.
            raise conflict("schedule_not_in_force")
        if item.commitment_type not in schedule.type_codes():
            raise CommitmentError("commitment_type_unknown", 422)
        sched_ccy = self.schedule_currency(schedule, project)
        ccy = norm(currency) or norm(item.currency) or norm(project.currency)
        try:
            q = await self.quote(matrix, project, ccy, sched_ccy, today)
        except FxRateMissing as exc:
            raise CommitmentError("fx_rate_missing", 422, detail=f"{exc.from_currency}->{exc.to_currency}") from exc
        converted = q.apply(amount)
        releases = await self.repo.list_releases(item.project_id, [item.id])
        released = self.released_in_schedule_currency(releases)
        expired = self.expired_in_schedule_currency(releases, today)
        if expired > 0:
            # A renewed release goes the same route as a first one. It adds to what is still in force:
            # the expired part counts only as far as money is committed under it.
            _figs, bound_by_item, _why = await self.committed_for_items(matrix, project, schedule, on_date=today)
            bound = bound_by_item.get(item.id, ZERO)
            if bound is None:
                raise CommitmentError("fx_rate_missing", 422)
            released = ev.release_in_force(released, expired, bound)
        group = await self._group_others(item)
        evaluated = ev.evaluated_amount(
            request=converted,
            released_on_item=released,
            released_on_group_others=group,
            aggregation=schedule.aggregation,
        )
        tier = ev.required_tier(schedule, item.commitment_type, evaluated, item.flags or [])
        route = await self._route_for(matrix, schedule, item.project_id, tier, today)
        planned, planned_ccy, _note = await figures.planned_amount(self.session, item, norm(project.currency))
        planned_sched = None
        if planned is not None:
            try:
                planned_sched = (await self.quote(matrix, project, planned_ccy, sched_ccy, today)).apply(planned)
            except FxRateMissing:
                planned_sched = None
        pre = await self.precondition_states(
            item.project_id,
            await self.repo.list_preconditions(item.project_id, [item.id]),
            planned=planned_sched,
            cumulative=released + converted,
        )
        return {
            "matrix": matrix,
            "schedule": schedule,
            "quote": q,
            "amount": amount,
            "currency": ccy,
            "schedule_currency": sched_ccy,
            "converted": converted,
            "released_before": released,
            "group_released": group,
            "evaluated": evaluated,
            "tier": tier,
            **route,
            "planned_in_schedule_currency": planned_sched,
            "preconditions": pre,
            "open_preconditions": [p for p in pre if p["state"] != "met"],
        }

    async def _route_for(
        self, matrix: CommitmentMatrix, schedule: AuthoritySchedule, project_id: uuid.UUID, tier: Any, today: date
    ) -> dict[str, Any]:
        """The route of the required tier and everyone who may decide on it.

        ``approvers`` lists the users (or ``role:<name>``) the route's steps name, followed by the
        other holders of the tier: every active assignee of an ``any`` tier and every deputy. A
        route has one step per ordinal, so those others decide by taking the step over
        (:meth:`decide_release`), not by a step of their own.
        """
        from app.modules.approval_routes.service import ApprovalRouteService

        route_tier = tier.tier_code or (schedule.tiers[-1].code if tier.escalate_outside else None)
        route_id = _uuid((matrix.tier_routes or {}).get(route_tier)) if route_tier else None
        approvers: list[str] = []
        holders: dict[uuid.UUID, uuid.UUID] = {}
        if route_id is not None:
            # A generated route is an ordinary route: a manager may delete or deactivate it. Either
            # reads as "no route for this tier", never a 500. A route of no project is never used.
            routes = ApprovalRouteService(self.session)
            route = await routes.repo.get_route(route_id)
            if route is None or not route.is_active or route.project_id != project_id:
                route_id = None
            else:
                approvers = [
                    _s(s.approver_user_id) or f"role:{s.approver_role}" for s in await routes.list_steps(route_id)
                ]
                holders = await self.tier_holders(matrix, schedule, route_tier, route_id, today)
                approvers += [str(u) for u in holders if str(u) not in approvers]
        return {"route_tier": route_tier, "route_id": route_id, "approvers": approvers, "holders": holders}

    async def tier_holders(
        self,
        matrix: CommitmentMatrix,
        schedule: AuthoritySchedule,
        tier_code: str | None,
        route_id: uuid.UUID | None,
        today: date,
    ) -> dict[uuid.UUID, uuid.UUID]:
        """``{who may decide: the assignee they decide for}`` on the generated route of a project-role tier.

        Every active assignee of the tier's role (themselves) and each deputy (for their assignee).
        Empty for a hand-pinned route: its author named the deciders, and nobody else is added.
        """
        if tier_code is None or route_id is None or tier_code not in schedule.tier_order():
            return {}
        tier = schedule.tier(tier_code)
        generated = (matrix.generated_routes or {}).get(tier_code) or {}
        if tier.approver.kind != "project_role" or generated.get("route_id") != str(route_id):
            return {}
        out: dict[uuid.UUID, uuid.UUID] = {}
        for a in await self.repo.list_assignments(matrix.project_id):
            if a.project_role != tier.approver.ref or not self._active(a, today):
                continue
            out.setdefault(a.user_id, a.user_id)
            if a.deputy_user_id is not None:
                out.setdefault(a.deputy_user_id, a.user_id)
        return out

    @staticmethod
    def evaluation_out(e: dict[str, Any]) -> dict[str, Any]:
        t = e["tier"]
        return {
            "amount": str(e["amount"]),
            "currency": e["currency"],
            "schedule_currency": e["schedule_currency"],
            "amount_in_schedule_currency": str(e["converted"]),
            "fx": e["quote"].as_dict(),
            "released_before": str(e["released_before"]),
            "group_released": str(e["group_released"]),
            "evaluated_amount": str(e["evaluated"]),
            "required_tier": t.tier_code,
            "escalate_outside": t.escalate_outside,
            "band_code": t.band_code,
            "raised_by": list(t.raised_by),
            "route_tier": e["route_tier"],
            "route_id": _s(e["route_id"]),
            "approvers": e["approvers"],
            "schedule": f"{e['matrix'].schedule_source}:{e['matrix'].schedule_id}@{e['matrix'].schedule_version}",
            "open_preconditions": e["open_preconditions"],
        }

    async def _expired_assignment_in_route(
        self, matrix: CommitmentMatrix, schedule: AuthoritySchedule, tier_code: str, route_id: uuid.UUID, today: date
    ) -> bool:
        """Rule 9: a generated route whose pinned approver no longer holds a valid assignment."""
        from app.modules.approval_routes.service import ApprovalRouteService

        tier = schedule.tier(tier_code)
        if tier.approver.kind != "project_role":
            return False
        generated = (matrix.generated_routes or {}).get(tier_code) or {}
        if generated.get("route_id") != str(route_id):
            return False
        valid = {
            a.user_id
            for a in await self.repo.list_assignments(matrix.project_id)
            if a.project_role == tier.approver.ref and self._active(a, today)
        }
        steps = await ApprovalRouteService(self.session).list_steps(route_id)
        return any(s.approver_user_id is not None and s.approver_user_id not in valid for s in steps)

    # Refusals shared by the write that enforces them and the ``can`` flags the screens read.
    _REFUSAL_STATUS = {
        "not_item_owner": 403,
        "manage_required": 403,
        "not_requester": 403,
        "not_entitled_decider": 403,
        "four_eyes_violation": 403,
    }

    @classmethod
    def _refuse(cls, code: str | None) -> None:
        if code:
            raise CommitmentError(code, cls._REFUSAL_STATUS.get(code, 409))

    @classmethod
    def edit_refusal(cls, item: CommitmentItem, actor_id: uuid.UUID | None, manage: bool) -> str | None:
        if not cls.may_edit(item, actor_id, manage):
            return "not_item_owner"
        return "item_closed" if item.status in ENDED else None

    @classmethod
    def request_refusal(cls, item: CommitmentItem, actor_id: uuid.UUID | None, manage: bool) -> str | None:
        """Why this person may not ask for a release (or an abort) of the item now; None when they may."""
        if not cls.may_edit(item, actor_id, manage):
            return "not_item_owner"
        if item.status == "release_requested":
            return "release_pending"
        return None if item.status in REQUESTABLE else "invalid_transition"

    @classmethod
    def defer_refusal(cls, item: CommitmentItem, manage: bool) -> str | None:
        """Deferring an item changes what a gate reads, so it is one of the gate fields."""
        return cls.gate_fields_refusal(item, manage)

    @staticmethod
    def gate_fields_refusal(item: CommitmentItem, manage: bool) -> str | None:
        """Why the gate, area, deferral and owner fields of an item may not change, or ``None``.

        ``update_item`` raises exactly this, and ``can.edit_gate_fields`` reports it: a manager, and
        only while the item is planned.
        """
        if item.status in ENDED:
            return "item_closed"
        if not manage:
            return "manage_required"
        return None if item.status == "planned" else "field_frozen"

    @staticmethod
    def withdraw_refusal(pending: ReleaseDecision | None, actor_id: uuid.UUID | None, manage: bool) -> str | None:
        if pending is None:
            return "no_pending_release"
        return None if manage or pending.requested_by == actor_id else "not_requester"

    @staticmethod
    def transfer_refusal(item: CommitmentItem, manage: bool) -> str | None:
        if not manage:
            return "manage_required"
        if item.status == "release_requested":
            return "release_pending"
        return None if item.status in WORKING else "invalid_transition"

    @staticmethod
    def hold_refusal(item: CommitmentItem, manage: bool, *, hold: bool) -> str | None:
        if not manage:
            return "manage_required"
        if hold:
            return None if item.status in WORKING else "invalid_transition"
        return None if item.status == "on_hold" else "invalid_transition"

    async def barred_from_deciding(self, item: CommitmentItem, requested_by: uuid.UUID | None) -> set[uuid.UUID]:
        """Four eyes: whoever asked, owns the item or confirmed one of its preconditions does not decide it."""
        pre = await self.repo.list_preconditions(item.project_id, [item.id])
        return {u for u in (requested_by, item.owner_user_id, *(p.confirmed_by for p in pre)) if u is not None}

    async def _require_route(self, e: dict[str, Any], item: CommitmentItem, actor_id: uuid.UUID, today: date) -> Any:
        """The tier whose route decides, after the checks every request passes (route, assignment, four eyes)."""
        matrix, schedule = e["matrix"], e["schedule"]
        if e["route_id"] is None:
            raise conflict("no_route_for_tier", detail=e["route_tier"])
        if not await self._route_accepted(matrix, e["route_tier"], e["route_id"]):
            # Somebody rewrote the route's steps after it was generated or pinned (routes are editable
            # with the ordinary route permission). A manager pins it again to accept the new steps.
            raise conflict("route_changed_since_accepted", detail=e["route_tier"])
        if await self._expired_assignment_in_route(matrix, schedule, e["route_tier"], e["route_id"], today):
            raise conflict("assignment_expired")
        route_tier = schedule.tier(e["route_tier"])
        if route_tier.four_eyes:
            barred = {str(u) for u in await self.barred_from_deciding(item, actor_id)}
            # A role step names nobody in particular, so somebody eligible may always hold the role.
            if not [a for a in e["approvers"] if a.startswith("role:") or a not in barred]:
                code = "four_eyes_requester_is_approver" if str(actor_id) in e["approvers"] else "four_eyes_no_approver"
                raise forbidden(code)
        return route_tier

    async def _open_decision(
        self, item: CommitmentItem, decision: ReleaseDecision, route_id: uuid.UUID, actor_id: uuid.UUID, **meta: Any
    ) -> ReleaseDecision:
        """Store the request, start its approval instance and move the item to ``release_requested``."""
        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        try:
            async with self.session.begin_nested():
                await self.repo.add(decision)
        except IntegrityError as exc:
            raise conflict("release_pending") from exc
        instance = await ApprovalRouteService(self.session).start_instance(
            InstanceCreate(route_id=route_id, target_kind=TARGET_KIND, target_id=decision.id), started_by=actor_id
        )
        decision.approval_instance_id = instance.id
        item.status_before = item.status
        await self._fsm(item, "release_requested", actor_id, attempt=item.attempt_no, release_id=str(decision.id))
        await self._audit(
            actor_id,
            "commitment_release",
            decision.id,
            "abort_requested" if decision.purpose == "abort" else "requested",
            metadata={"item_id": str(item.id), "tier": decision.required_tier, **meta},
        )
        self._publish(
            "commitment_release.release.requested",
            {
                "project_id": str(item.project_id),
                "item_id": str(item.id),
                "release_id": str(decision.id),
                "purpose": decision.purpose,
            },
        )
        return decision

    async def _snapshot(self, item: CommitmentItem, e: dict[str, Any], four_eyes: bool, today: date) -> dict[str, Any]:
        """What the decider is shown, frozen: the evaluation, every linked document with its amount, the
        preconditions, and a hash of exactly that content so a later reader can tell it was not edited."""
        project = await self._project(item.project_id)
        per_item, committed, reason = await self.committed_for_items(e["matrix"], project, e["schedule"], on_date=today)
        content = {
            "evaluation": self.evaluation_out(e),
            "links": [f.as_dict() for f in per_item.get(item.id, [])],
            "committed": _money_str(committed.get(item.id, ZERO)),
            "committed_reason": reason.get(item.id),
            "preconditions": e["preconditions"],
            "four_eyes": four_eyes,
        }
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()
        return {**content, "content_hash": digest, "requested_at": datetime.now(UTC).isoformat()}

    async def request_release(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        amount: Any,
        currency: str | None,
        tranche_note: str,
        external_approval_ref: str,
        actor_id: uuid.UUID,
        today: date,
        manage: bool = False,
    ) -> ReleaseDecision:
        """Rule 2 with rules 4, 18 and 19: evaluate the authority and start the tier's approval."""
        item = await self._lock_for_request(project_id, item_id)
        self._refuse(self.request_refusal(item, actor_id, manage))
        if [r for r in await self.repo.list_releases(project_id, [item.id]) if r.outcome == "pending"]:
            raise conflict("release_pending")
        e = await self._evaluate(item, _amount(amount), currency, today=today)
        matrix, tier = e["matrix"], e["tier"]
        self._check_external_reference(tier, external_approval_ref)
        if e["open_preconditions"] and matrix.enforcement == "block":
            raise conflict(
                "preconditions_open",
                violations=[
                    {"code": "precondition_open", "ref": p["id"], "kind": p["kind"]} for p in e["open_preconditions"]
                ],
            )
        route_tier = await self._require_route(e, item, actor_id, today)
        if item.commitment_type == drawdown.ITEM_TYPE:
            await self._drawdown_cover(
                item, matrix, e["released_before"] + e["converted"], e["schedule_currency"], today
            )
        decision = ReleaseDecision(
            project_id=project_id,
            item_id=item.id,
            attempt=item.attempt_no,
            purpose="release",
            requested_amount=e["amount"],
            currency=e["currency"],
            schedule_currency=e["schedule_currency"],
            amount_in_schedule_currency=e["converted"],
            fx_rate_used=str(e["quote"].rate),
            fx_rate_date=e["quote"].as_of.isoformat() if e["quote"].as_of else None,
            fx_source=e["quote"].source,
            evaluated_amount=e["evaluated"],
            cumulative_after=e["released_before"] + e["converted"],
            required_tier=tier.tier_code,
            escalate_outside=tier.escalate_outside,
            external_approval_ref=external_approval_ref,
            schedule_source=matrix.schedule_source,
            schedule_id=matrix.schedule_id,
            schedule_version=matrix.schedule_version,
            outcome="pending",
            requested_by=actor_id,
            snapshot=await self._snapshot(item, e, route_tier.four_eyes, today),
            tranche_note=tranche_note,
        )
        return await self._open_decision(
            item,
            decision,
            e["route_id"],
            actor_id,
            amount=str(e["converted"]),
            warnings=[p["kind"] for p in e["open_preconditions"]],
        )

    @staticmethod
    def _check_external_reference(tier: Any, external_approval_ref: str) -> None:
        """An amount above every tier needs the outside approval's reference; any other must not carry one.

        A reference is evidence that somebody outside the schedule agreed. Kept on a request a tier
        decides, it would say an outside approval was part of a decision it was not. The same rule
        for a release and for an abort.
        """
        if tier.escalate_outside and not external_approval_ref.strip():
            raise CommitmentError("external_approval_required", 422)
        if external_approval_ref.strip() and not tier.escalate_outside:
            raise CommitmentError("external_approval_not_required", 422)

    async def request_abort(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        reason: str,
        actor_id: uuid.UUID,
        today: date,
        manage: bool = False,
        external_approval_ref: str = "",
    ) -> ReleaseDecision:
        """SPEC rule 15: stopping an item is decided on the tier its residual loss calls for.

        The loss is the item's abort exposure today, in the schedule currency, judged as a
        ``termination_settlement``. Unknown exposure is refused: the tier cannot be named without
        it, and guessing one would be deciding the authority by accident. This module never
        terminates a document; the aborted item names the documents whose own termination follows.
        """
        item = await self._lock_for_request(project_id, item_id)
        self._refuse(self.request_refusal(item, actor_id, manage))
        if not reason.strip():
            raise CommitmentError("rationale_required", 422)
        if [r for r in await self.repo.list_releases(project_id, [item.id]) if r.outcome == "pending"]:
            raise conflict("release_pending")
        e, exposure = await self._abort_evaluation(item, today)
        matrix, tier, q = e["matrix"], e["tier"], e["quote"]
        loss, loss_sched, judged = e["amount"], e["converted"], e["evaluated"]
        base, sched_ccy = e["currency"], e["schedule_currency"]
        self._check_external_reference(tier, external_approval_ref)
        route_tier = await self._require_route(e, item, actor_id, today)
        snapshot = await self._snapshot(item, e, route_tier.four_eyes, today)
        snapshot["exposure"] = exposure
        decision = ReleaseDecision(
            project_id=project_id,
            item_id=item.id,
            attempt=item.attempt_no,
            purpose="abort",
            requested_amount=loss,
            currency=base,
            schedule_currency=sched_ccy,
            amount_in_schedule_currency=loss_sched,
            fx_rate_used=str(q.rate),
            fx_rate_date=q.as_of.isoformat() if q.as_of else None,
            fx_source=q.source,
            evaluated_amount=judged,
            cumulative_after=e["released_before"],
            required_tier=tier.tier_code,
            escalate_outside=tier.escalate_outside,
            external_approval_ref=external_approval_ref.strip(),
            schedule_source=matrix.schedule_source,
            schedule_id=matrix.schedule_id,
            schedule_version=matrix.schedule_version,
            outcome="pending",
            requested_by=actor_id,
            snapshot=snapshot,
            tranche_note=reason,
        )
        return await self._open_decision(item, decision, e["route_id"], actor_id, residual_loss=str(loss_sched))

    async def preview_abort(self, project_id: uuid.UUID, item_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """What an abort request would need, without writing: the loss, the tier and the outside reference.

        The same evaluation the request runs, so the form and the 4xx agree. Refusals that depend on
        the person or on a pending request are not part of it; ``can.request_abort`` says those.
        """
        item = await self.get_item(project_id, item_id)
        e, exposure = await self._abort_evaluation(item, today)
        return {
            **self.evaluation_out(e),
            "residual_loss": str(e["amount"]),
            "external_approval_required": e["tier"].escalate_outside,
            "exposure": exposure,
        }

    async def _abort_evaluation(self, item: CommitmentItem, today: date) -> tuple[dict[str, Any], dict[str, Any]]:
        """The tier a stop of ``item`` is judged on today, and the exposure it was read from."""
        project_id = item.project_id
        matrix = await self.require_matrix(project_id)
        project = await self._project(project_id)
        schedule = await self.schedule_for(matrix)
        if not ev.in_force(schedule, today):
            raise conflict("schedule_not_in_force")
        if ABORT_TYPE not in schedule.type_codes():
            raise CommitmentError("abort_type_not_in_schedule", 422)
        view = (await self.item_views(project_id, today=today, item_ids=[item.id], with_exposure=True))["items"][0]
        exposure = view["exposure"]
        if exposure.get("residual_loss") is None:
            raise CommitmentError("abort_exposure_unknown", 422, detail=exposure.get("reason"))
        loss = Decimal(exposure["residual_loss"])
        base, sched_ccy = norm(project.currency), self.schedule_currency(schedule, project)
        try:
            q = await self.quote(matrix, project, base, sched_ccy, today)
        except FxRateMissing as exc:
            raise CommitmentError("fx_rate_missing", 422, detail=f"{exc.from_currency}->{exc.to_currency}") from exc
        loss_sched = q.apply(loss)
        # Judged on the signed figure: a stop that loses nothing, or recovers more than it cost, fits
        # the lowest band and so the lowest tier that may settle a termination.
        judged = loss_sched
        tier = ev.required_tier(schedule, ABORT_TYPE, judged, item.flags or [])
        e: dict[str, Any] = {
            "matrix": matrix,
            "schedule": schedule,
            "quote": q,
            "amount": loss,
            "currency": base,
            "schedule_currency": sched_ccy,
            "converted": loss_sched,
            "released_before": self.released_in_schedule_currency(await self.repo.list_releases(project_id, [item.id])),
            "group_released": ZERO,
            "evaluated": judged,
            "tier": tier,
            **await self._route_for(matrix, schedule, project_id, tier, today),
            "preconditions": [],
            "open_preconditions": [],
        }
        return e, exposure

    async def withdraw_release(
        self, project_id: uuid.UUID, item_id: uuid.UUID, *, actor_id: uuid.UUID, manage: bool = False, reason: str
    ) -> ReleaseDecision:
        """Rule 12: the requester (or a manager) withdraws a pending request; the instance is cancelled."""
        from app.modules.approval_routes.service import ApprovalRouteService

        item = await self.get_item(project_id, item_id, lock=True)
        pending = [r for r in await self.repo.list_releases(project_id, [item.id]) if r.outcome == "pending"]
        decision = pending[0] if pending else None
        self._refuse(self.withdraw_refusal(decision, actor_id, manage))
        assert decision is not None
        if decision.approval_instance_id is not None:
            try:
                async with self.session.begin_nested():
                    await ApprovalRouteService(self.session).cancel_instance(
                        decision.approval_instance_id, actor_id=actor_id, reason=reason or "withdrawn"
                    )
            except HTTPException as exc:
                # The instance was decided or cancelled in the meantime: there is nothing left to cancel.
                logger.info("commitment: instance %s already closed (%s)", decision.approval_instance_id, exc.detail)
        await self._close_decision(item, decision, "withdrawn", decided_by=actor_id, rationale=reason)
        return decision

    async def _close_decision(
        self,
        item: CommitmentItem,
        decision: ReleaseDecision,
        outcome: str,
        *,
        decided_by: uuid.UUID | None,
        rationale: str = "",
        on_behalf_of: uuid.UUID | None = None,
    ) -> None:
        if decision.outcome != "pending":
            raise conflict("release_decided")
        abort = decision.purpose == "abort"
        if abort and outcome == "released":
            outcome = "aborted"
        balance: drawdown.LineBalance | None = None
        if outcome == "released" and item.commitment_type == drawdown.ITEM_TYPE:
            # Rule 17, checked again at approval: money another drawdown took while this request
            # waited is never overdrawn. The shortfall turns the approval into a coded rejection
            # (the safe direction); the item can be requested again.
            try:
                balance = await self._drawdown_cover(
                    item,
                    await self.require_matrix(item.project_id),
                    decision.cumulative_after,
                    decision.schedule_currency,
                    datetime.now(UTC).date(),
                )
            except CommitmentError as exc:
                # Insufficient cover, a line that is gone or a rate that is missing: the approval
                # cannot write the drawdown, so the request is closed as rejected with the code.
                # Leaving it pending would strand it, since its approval instance is already decided.
                if exc.code not in drawdown.REFUSALS:
                    raise
                outcome, rationale = "rejected", exc.code
        decision.outcome = outcome
        decision.decided_by = decided_by
        decision.on_behalf_of = on_behalf_of
        decision.decided_at = datetime.now(UTC)
        decision.rationale = rationale or ""
        if outcome == "released":
            target = await self._released_state(item, decision)
        elif outcome == "aborted":
            target = "aborted"
        else:
            target = item.status_before or "planned"
        # Every closed decision frees the next attempt number: a second tranche after a release is a new
        # attempt too, and reusing the number would collide on ``uq_oe_cmt_release_attempt``.
        item.attempt_no += 1
        item.status_before = None
        await self._fsm(item, target, decided_by, rationale or None, release_id=str(decision.id), outcome=outcome)
        await self._audit(
            decided_by,
            "commitment_release",
            decision.id,
            outcome,
            metadata={"item_id": str(item.id), "on_behalf_of": _s(on_behalf_of), "purpose": decision.purpose},
        )
        # One literal per outcome: the wiring test reads event names from the source of each call.
        ended = {"project_id": str(item.project_id), "item_id": str(item.id), "release_id": str(decision.id)}
        if outcome == "aborted":
            self._publish("commitment_release.item.aborted", ended)
        elif outcome == "released":
            self._publish("commitment_release.release.released", ended)
        elif outcome == "rejected":
            self._publish("commitment_release.release.rejected", ended)
        else:
            self._publish("commitment_release.release.withdrawn", ended)
        if outcome in ("released", "rejected", "aborted"):
            await self._notify(
                decision.requested_by,
                f"release_{outcome}",
                item,
                {"project_id": str(item.project_id), "code": item.code},
            )
        if outcome == "released":
            if balance is not None:
                await self._write_drawdown(item, decision, decided_by, balance)
            await self.recompute_item(item.project_id, item.id, actor_id=decided_by, locked=item)

    async def _drawdown_cover(
        self, item: CommitmentItem, matrix: CommitmentMatrix, cumulative: Decimal, sched_ccy: str, today: date
    ) -> drawdown.LineBalance:
        """Rule 17: the line must still hold the cumulative drawdown, in its own currency."""
        project = await self._project(item.project_id)
        balance = await drawdown.line_for(self.session, project, item)
        try:
            quote = await self.quote(matrix, project, sched_ccy, balance.currency, today)
        except FxRateMissing as exc:
            raise CommitmentError("fx_rate_missing", 422, detail=f"{exc.from_currency}->{exc.to_currency}") from exc
        drawdown.require_cover(balance, quote.apply(cumulative))
        return balance

    async def _write_drawdown(
        self, item: CommitmentItem, decision: ReleaseDecision, decided_by: Any, balance: drawdown.LineBalance
    ) -> None:
        """Rule 17: an approved release writes the item's cumulative drawdown onto its contingency line."""
        matrix = await self.require_matrix(item.project_id)
        today = datetime.now(UTC).date()
        project = await self._project(item.project_id)
        amount = (await self.quote(matrix, project, decision.schedule_currency, balance.currency, today)).apply(
            decision.cumulative_after
        )
        await drawdown.write(
            self.session,
            project_id=item.project_id,
            item=item,
            balance=balance,
            amount=amount,
            release_id=decision.id,
            decided_by=decided_by,
            decided_at=(decision.decided_at or datetime.now(UTC)).isoformat(),
        )
        await self._audit(
            decided_by,
            "commitment_item",
            item.id,
            "contingency_drawdown_written",
            metadata={"budget_id": str(balance.budget_id), "amount": str(amount), "currency": balance.currency},
        )

    async def _released_state(self, item: CommitmentItem, decision: ReleaseDecision) -> str:
        """``released`` when the cumulative release covers the planned amount, else ``partially_released`` (rule 5)."""
        matrix = await self.require_matrix(item.project_id)
        project = await self._project(item.project_id)
        schedule = await self.schedule_for(matrix)
        planned, ccy, _n = await figures.planned_amount(self.session, item, norm(project.currency))
        if planned is None:
            return "released"
        try:
            on = _day(decision.fx_rate_date) or datetime.now(UTC).date()
            planned_sched = (
                await self.quote(matrix, project, ccy, self.schedule_currency(schedule, project), on)
            ).apply(planned)
        except FxRateMissing:
            return "released"
        return "released" if decision.cumulative_after >= planned_sched else "partially_released"

    async def apply_route_verdict(
        self,
        release_id: uuid.UUID,
        *,
        instance_id: uuid.UUID | None,
        verdict: str,
        decided_by: Any,
        comment: str | None = None,
    ) -> bool:
        """The approval route decided. Idempotent: acts once, only on the instance the request started.

        Returns True when the decision was applied.
        """
        seen = await self.repo.get_release(release_id)
        if seen is None:
            return False
        # Item first, then the request, both read afresh under their locks: a withdrawal that
        # committed while this waited has already closed the request, and must not be undone.
        item = await self.get_item(seen.project_id, seen.item_id, lock=True)
        decision = await self.repo.get_release(release_id, lock=True)
        if decision is None or decision.outcome != "pending":
            return False
        if instance_id is not None and decision.approval_instance_id != instance_id:
            return False
        decider = _uuid(decided_by)
        if verdict == "approved":
            if decision.snapshot.get("four_eyes") and decider in await self.barred_from_deciding(
                item, decision.requested_by
            ):
                await self._close_decision(
                    item, decision, "rejected", decided_by=decider, rationale="four_eyes_violation"
                )
                return True
            if not await self._approved_by_tier_holders(decision, decider):
                # The route says approved, but not by people who hold the tier: a step handed to
                # somebody else in approval_routes does not carry the tier's authority with it.
                await self._close_decision(
                    item, decision, "rejected", decided_by=decider, rationale="decider_not_tier_holder"
                )
                return True
            on_behalf = await self._on_behalf_of(decision, decider)
            await self._close_decision(
                item, decision, "released", decided_by=decider, on_behalf_of=on_behalf, rationale=comment or ""
            )
        elif verdict == "rejected":
            await self._close_decision(item, decision, "rejected", decided_by=decider, rationale=comment or "")
        elif verdict == "cancelled":
            await self._close_decision(
                item, decision, "withdrawn", decided_by=decider, rationale=comment or "cancelled"
            )
        else:
            return False
        return True

    async def _approved_by_tier_holders(self, decision: ReleaseDecision, decider: uuid.UUID | None) -> bool:
        """Whether everyone who approved the request's route holds the tier it was decided on.

        Holders are the active assignees of the tier's role and their deputies (generated route of
        a project-role tier) or the users the route's steps name, each with their active delegates;
        a role step is held by whoever has that role. A request without an instance has no approver.
        """
        from app.modules.approval_routes import delegation_engine
        from app.modules.approval_routes.service import (
            ApprovalRouteService,
            _caller_role_satisfies,
            delegation_views_from_rows,
        )
        from app.modules.users.models import User

        if decision.approval_instance_id is None:
            return False
        routes = ApprovalRouteService(self.session)
        instance = await routes.get_instance(decision.approval_instance_id)
        steps = await routes.list_steps(instance.route_id)
        approved = {
            st.approver_user_id
            for st in await routes.repo.list_step_states(instance.id)
            if st.decision == "approved" and st.approver_user_id is not None
        }
        if decider is not None:
            approved.add(decider)
        if not approved:
            return False
        now = datetime.now(UTC)
        matrix = await self.require_matrix(decision.project_id)
        tier_code = (decision.snapshot.get("evaluation") or {}).get("route_tier")
        holders = set(
            await self.tier_holders(matrix, await self.schedule_for(matrix), tier_code, instance.route_id, now.date())
        )
        if not holders:
            holders = {s.approver_user_id for s in steps if s.approver_user_id is not None}
        views = delegation_views_from_rows(await routes.repo.list_active_delegations())
        for user in list(holders):
            holders |= delegation_engine.eligible_deciders(user, views, now=now, project_id=decision.project_id)
        roles = [s.approver_role for s in steps if s.approver_role]
        for user in approved - holders:
            row = await self.session.get(User, user)
            if row is None or not any(_caller_role_satisfies(row.role, r) for r in roles):
                return False
        return True

    async def _on_behalf_of(self, decision: ReleaseDecision, decider: uuid.UUID | None) -> uuid.UUID | None:
        """Rule 9: when a deputy or a delegate decided, name the approver they decided for."""
        from app.modules.approval_routes.service import ApprovalRouteService

        if decision.approval_instance_id is None or decider is None:
            return None
        svc = ApprovalRouteService(self.session)
        instance = await svc.get_instance(decision.approval_instance_id)
        steps = await svc.list_steps(instance.route_id)
        pinned = {s.approver_user_id for s in steps if s.approver_user_id is not None}
        if not pinned or decider in pinned:
            return None
        matrix = await self.require_matrix(decision.project_id)
        holders = await self.tier_holders(
            matrix,
            await self.schedule_for(matrix),
            (decision.snapshot.get("evaluation") or {}).get("route_tier"),
            instance.route_id,
            (decision.decided_at or datetime.now(UTC)).date(),
        )
        if decider in holders:
            # An assignee of the tier decides in their own right; a deputy decides for their assignee.
            return None if holders[decider] == decider else holders[decider]
        return sorted(pinned, key=str)[0] if len(pinned) == 1 else None

    async def _decide_check(
        self,
        item: CommitmentItem,
        decision: ReleaseDecision | None,
        actor_id: uuid.UUID | None,
        today: date,
        caller_role: str | None = None,
    ) -> tuple[str | None, bool, Any, Any]:
        """``(refusal code or None, takes the step over, instance, current step)`` for one person and one request.

        ``caller_role`` is the role of the request; a read that has none (a list of items) uses the
        role stored for the person.
        """
        from app.modules.approval_routes.service import ApprovalRouteService, _caller_role_satisfies
        from app.modules.users.models import User

        if decision is None or decision.approval_instance_id is None:
            return "no_pending_release", False, None, None
        routes = ApprovalRouteService(self.session)
        instance = await routes.get_instance(decision.approval_instance_id)
        steps = [s for s in await routes.list_steps(instance.route_id) if s.ordinal == instance.current_step_ordinal]
        if instance.status != "pending" or not steps:
            return "no_pending_release", False, instance, None
        step = steps[0]
        if actor_id is None:
            return "not_entitled_decider", False, instance, step
        if decision.snapshot.get("four_eyes") and actor_id in await self.barred_from_deciding(
            item, decision.requested_by
        ):
            return "four_eyes_violation", False, instance, step
        entitled = await routes.entitled_deciders(instance, step, now=datetime.now(UTC))
        if entitled is None:
            # A role step: approval_routes will check the caller's role, so the flag and the
            # refusal say the same thing it will say.
            role = caller_role
            if role is None:
                person = await self.session.get(User, actor_id)
                role = person.role if person is not None else None
            if step.approver_role and not _caller_role_satisfies(role, step.approver_role):
                return "not_entitled_decider", False, instance, step
            return None, False, instance, step
        if actor_id in entitled:
            return None, False, instance, step
        matrix = await self.require_matrix(item.project_id)
        schedule = await self.schedule_for(matrix)
        tier_code = (decision.snapshot.get("evaluation") or {}).get("route_tier")
        holders = await self.tier_holders(matrix, schedule, tier_code, instance.route_id, today)
        principal = holders.get(actor_id)
        if principal is None:
            return "not_entitled_decider", False, instance, step
        if schedule.tier(tier_code).steps_mode != "any" and step.approver_user_id != principal:
            # Every assignee of an ``all`` tier must decide: only that assignee's own deputy stands in.
            return "not_entitled_decider", False, instance, step
        if actor_id == instance.started_by:
            # approval_routes never hands a step to the person who started the approval.
            return "not_entitled_decider", False, instance, step
        return None, True, instance, step

    async def decide_release(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        decision: str,
        comment: str,
        conditions: str,
        valid_until: Any,
        actor_id: uuid.UUID,
        caller_role: str | None,
        today: date,
    ) -> ReleaseDecision:
        """Decide the pending request as a holder of its tier (review finding 13).

        The approval route keeps one step per ordinal, pinned to one person. Any other active
        assignee of an ``any`` tier, and a deputy, decide by taking that step over first; the
        decision itself is still an approval_routes decision, so its history and its events are the
        usual ones. A rejection needs its reason (SPEC rule 11).
        """
        from app.modules.approval_routes.schemas import DecisionSubmit
        from app.modules.approval_routes.service import ApprovalRouteService

        item = await self.get_item(project_id, item_id, lock=True)
        pending = [r for r in await self.repo.list_releases(project_id, [item.id]) if r.outcome == "pending"]
        row = pending[0] if pending else None
        code, takeover, instance, step = await self._decide_check(item, row, actor_id, today, caller_role)
        self._refuse(code)
        assert row is not None
        if decision not in ("approved", "rejected"):
            raise CommitmentError("decision_invalid", 422)
        if decision == "rejected" and not comment.strip():
            raise CommitmentError("rationale_required", 422)
        routes = ApprovalRouteService(self.session)
        if takeover:
            # ``manage``: this module resolved the actor as a holder of the tier just above.
            await routes.reassign_current_step(
                instance.id, to_user_id=actor_id, actor_id=actor_id, reason="commitment tier holder", manage=True
            )
        if decision == "approved":
            # A tier with several steps has several approvers. Each one's conditions are kept, and
            # the release is valid until the earliest date any of them gave.
            said = (conditions or "").strip()
            kept = [line for line in (row.conditions or "").split("\n") if line.strip()]
            if said and said not in kept:
                kept.append(said)
            row.conditions = "\n".join(kept)
            until = _iso_day(valid_until)
            if until and (not row.valid_until or until < row.valid_until):
                row.valid_until = until
        await routes.submit_decision(
            instance.id,
            DecisionSubmit(step_id=step.id, decision=decision, comment=comment or None),
            approver_id=actor_id,
            caller_role=caller_role,
        )
        await self.session.flush()
        instance = await routes.get_instance(instance.id)
        if instance.status in ("approved", "rejected"):
            # Applied here, in the caller's transaction; the route's own event then finds the request
            # closed and does nothing.
            await self.apply_route_verdict(
                row.id, instance_id=instance.id, verdict=instance.status, decided_by=actor_id, comment=comment
            )
        return row

    async def transfer_item(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        target_project_id: uuid.UUID,
        target_item_id: uuid.UUID,
        reason: str,
        actor_id: uuid.UUID,
        manage: bool,
    ) -> CommitmentItem:
        """SPEC rule 16: the item ends as ``transferred``; its links move to the target, its decisions stay.

        A linked document belongs to its project, so links can only follow into an item of the same
        project. An item that still has links is not transferred to another project (409): the
        documents are moved or closed in their own modules first.
        """
        if (target_project_id, target_item_id) == (project_id, item_id):
            raise CommitmentError("transfer_target_invalid", 422)
        if not reason.strip():
            raise CommitmentError("rationale_required", 422)
        # Both rows are locked in id order, whatever the direction of the transfer.
        rows: dict[uuid.UUID, CommitmentItem] = {}
        for pid, iid in sorted([(project_id, item_id), (target_project_id, target_item_id)], key=lambda p: str(p[1])):
            rows[iid] = await self.get_item(pid, iid, lock=True)
        item, target = rows[item_id], rows[target_item_id]
        self._refuse(self.transfer_refusal(item, manage))
        if target.status not in WORKING:
            raise conflict("transfer_target_not_open")
        links = await self.repo.list_links(project_id, [item.id])
        if links and target_project_id != project_id:
            raise conflict("transfer_links_stay_in_project")
        moved = {str(lk.id) for lk in links}
        for lk in links:
            lk.item_id = target.id
        for terms in await self.repo.list_abort_terms(project_id, [item.id]):
            if terms.scope in moved:
                terms.item_id = target.id
        item.transferred_to_item_id = target.id
        await self.session.flush()
        await self._fsm(item, "transferred", actor_id, reason, target_item_id=str(target.id))
        meta = {"from_item_id": str(item.id), "to_item_id": str(target.id), "links": len(links)}
        await self._audit(actor_id, "commitment_item", item.id, "transferred", metadata={**meta, "reason": reason})
        await self._audit(actor_id, "commitment_item", target.id, "transfer_received", metadata=meta)
        self._publish(
            "commitment_release.item.transferred", {"project_id": str(project_id), "item_id": str(item.id), **meta}
        )
        if links:
            await self.recompute_item(target.project_id, target.id, actor_id=actor_id, locked=target)
        return item

    async def references(self, project_id: uuid.UUID) -> dict[str, Any]:
        """What the item and precondition forms let a person pick, read from the modules that own it.

        Gates and areas are the project's own governance rows, labelled from the catalogue the
        project pinned; frame documents and funding applications are what a linked precondition
        names. Every list is empty for a project without a governance model (``has_model`` says so).
        """
        from app.modules.funding.models import FundingApplication
        from app.modules.project_governance.public import (
            project_areas,
            project_catalogue,
            project_documents,
            project_gates,
        )

        has_model = await project_catalogue(self.session, project_id) is not None
        gates = await project_gates(self.session, project_id)
        areas = await project_areas(self.session, project_id)
        documents = await project_documents(self.session, project_id)
        funding = await self.session.execute(
            select(FundingApplication.id, FundingApplication.code, FundingApplication.title, FundingApplication.status)
            .where(FundingApplication.project_id == project_id)
            .order_by(FundingApplication.code)
        )
        plant_register, plant_items = await figures.plant_item_options(self.session, project_id)
        return {
            "has_model": has_model,
            # False: this project does not use gates. Nothing waits for a gate there, and a release is
            # decided by the tier of the authority schedule alone.
            "gates_in_use": bool(gates),
            # ``available`` is false when the plant register is not installed: there is nothing to link to.
            "plant_items": {"available": plant_register, "items": plant_items},
            "gates": [
                {
                    "code": g.code,
                    "name": g.label,
                    "status": g.status,
                    "last_outcome": g.last_outcome or None,
                }
                for g in gates
            ],
            "areas": [
                {
                    "code": a.code,
                    "name": {"key": None, "text": {"en": a.name_override}} if a.name_override else a.label,
                }
                for a in areas
            ],
            "frame_documents": [
                {
                    "id": str(d.id),
                    "doc_type": d.code,
                    "name": d.label,
                    "area_code": d.area_code,
                    "status": d.status,
                }
                for d in documents
            ],
            "funding_applications": [
                {"id": str(i), "code": code, "title": title, "status": status}
                for i, code, title, status in funding.all()
            ],
        }

    async def transfer_targets(
        self, project_id: uuid.UUID, item_id: uuid.UUID, *, accessible: set[uuid.UUID] | None, manage: bool
    ) -> list[dict[str, Any]]:
        """Where the item may be handed over: this project first, then the caller's other projects
        that have a matrix. ``accessible`` is the caller's project set (None: no restriction). Each
        project carries ``can`` by the rule :meth:`transfer_item` enforces, and its open items."""
        from app.modules.projects.models import Project

        item = await self.get_item(project_id, item_id)
        refusal = self.transfer_refusal(item, manage)
        has_links = bool(await self.repo.list_links(project_id, [item.id]))
        stmt = select(Project.id, Project.name).join(CommitmentMatrix, CommitmentMatrix.project_id == Project.id)
        if accessible is not None:
            stmt = stmt.where(Project.id.in_(accessible | {project_id}))
        rows = (await self.session.execute(stmt.order_by(Project.name))).all()
        out: list[dict[str, Any]] = []
        for pid, name in sorted(rows, key=lambda r: (r[0] != project_id, r[1] or "")):
            code = refusal or ("transfer_links_stay_in_project" if has_links and pid != project_id else None)
            items = [
                {"id": str(i.id), "code": i.code, "title": i.title}
                for i in await self.repo.list_items(pid)
                if i.id != item.id and i.status in WORKING
            ]
            out.append(
                {
                    "project_id": str(pid),
                    "project_name": name,
                    "same_project": pid == project_id,
                    "can": {"allowed": code is None, "reason": code},
                    "items": items,
                }
            )
        return out

    async def history(self, project_id: uuid.UUID, item_id: uuid.UUID) -> list[ReleaseDecision]:
        item = await self.get_item(project_id, item_id)
        return await self.repo.list_releases(project_id, [item.id])

    # ── recompute from linked documents (rule 6) ───────────────────────────

    async def recompute_item(
        self, project_id: uuid.UUID, item_id: uuid.UUID, *, actor_id: Any = None, locked: CommitmentItem | None = None
    ) -> CommitmentItem:
        """Move ``released / committed / closed / re_release_required`` from the linked documents. Only writer of those."""
        item = locked or await self.get_item(project_id, item_id, lock=True)
        if item.status not in RECOMPUTED:
            return item
        matrix = await self.require_matrix(project_id)
        project = await self._project(project_id)
        schedule = await self.schedule_for(matrix)
        today = datetime.now(UTC).date()
        per_item, committed, reason = await self.committed_for_items(matrix, project, schedule, on_date=today)
        figs = per_item.get(item.id, [])
        comm = committed.get(item.id, ZERO)
        if comm is None:
            return item
        released = self.released_in_schedule_currency(await self.repo.list_releases(project_id, [item.id]))
        tol = schedule.variation_tolerance
        ceiling = ev.tolerance_ceiling(released, parse_amount(tol.absolute), parse_amount(tol.percent))
        counting = [f for f in figs if f.counts]
        if comm > ceiling:
            target = "re_release_required"
        elif counting and all(f.closed for f in counting):
            target = "closed"
        elif comm > 0:
            target = "committed"
        else:
            target = await self._released_state_from_amount(item, released, matrix, project, schedule, today)
        if target != item.status:
            await self._fsm(item, target, actor_id, "recomputed from linked documents", committed=str(comm))
            if target == "re_release_required":
                await self._notify(
                    item.owner_user_id,
                    "re_release_required",
                    item,
                    {
                        "project_id": str(project_id),
                        "code": item.code,
                        "committed": str(comm),
                        "released": str(released),
                    },
                )
                self._publish(
                    "commitment_release.item.re_release_required",
                    {"project_id": str(project_id), "item_id": str(item.id)},
                )
        return item

    async def _released_state_from_amount(self, item, released, matrix, project, schedule, today) -> str:
        planned, ccy, _n = await figures.planned_amount(self.session, item, norm(project.currency))
        if planned is None:
            return "released"
        try:
            p = (await self.quote(matrix, project, ccy, self.schedule_currency(schedule, project), today)).apply(
                planned
            )
        except FxRateMissing:
            return "released"
        return "released" if released >= p else "partially_released"

    async def recompute_documents(self, kind: str, document_ids: list[uuid.UUID]) -> int:
        """Recompute every item that links one of these documents (event subscribers)."""
        links = await self.repo.links_for_documents(kind, document_ids)
        for link in links:
            await self.recompute_item(link.project_id, link.item_id)
        return len(links)

    # ── guard check (rule 3) ───────────────────────────────────────────────

    async def check_document(
        self,
        project_id: uuid.UUID,
        *,
        kind: str,
        document_id: uuid.UUID | None,
        new_amount: Any,
        currency: str,
        actor_id: Any = None,
        parent_kind: str | None = None,
        parent_id: uuid.UUID | None = None,
        gross_amount: Any = None,
    ) -> dict[str, Any]:
        """Would binding ``new_amount`` on this document stay within its item's release (plus tolerance)?

        A linked document replaces its own figure (``new_amount`` is its new total). A change order or
        variation is asked on the item of its contract when that contract is in the matrix, because
        that is where its money counts once the contract header carries it (``new_amount`` is the
        change's own amount). A contingency drawdown confirmed for a risk (``document_id`` is the
        risk) is asked on the drawdown item that names that risk.

        The committed sum is :meth:`item_committed`, the same one the matrix and recompute read.

        Pure: writes nothing. The guard (:mod:`.guard`) records a ``warn`` or ``block``; the
        ``/check`` preview records nothing.
        """
        matrix = await self.repo.get_matrix(project_id)
        if matrix is None or matrix.enforcement == "off":
            return {"result": "ok", "reasons": [], "item_id": None}
        severity = "block" if matrix.enforcement == "block" else "warn"
        project = await self._project(project_id)
        schedule = await self.schedule_for(matrix)
        today = datetime.now(UTC).date()
        sched_ccy = self.schedule_currency(schedule, project)
        if schedule.basis == "gross" and gross_amount is not None:
            new_amount = gross_amount
        new = (_amount(new_amount), norm(currency))
        not_in_matrix = {
            "result": severity if matrix.require_link else "ok",
            "reasons": [{"code": "commitment_not_in_matrix"}] if matrix.require_link else [],
            "item_id": None,
        }
        item_ids: list[uuid.UUID]
        try:
            if kind == "contingency_drawdown":
                rows = await self.repo.items_by_risk(project_id, document_id, drawdown.ITEM_TYPE) if document_id else []
                item_ids = [i.id for i in rows if i.status not in ENDED]
                if not item_ids:
                    return not_in_matrix
                would_commit = (await self.quote(matrix, project, new[1], sched_ccy, today)).apply(new[0])
                # The drawdown record is written when the release is approved, so the released
                # money is already drawn: a passed date takes nothing back from it.
                bound_now = self.released_in_schedule_currency(await self.repo.list_releases(project_id, item_ids))
            else:
                link = await self.repo.find_link(project_id, kind, document_id) if document_id else None
                own_link_id = link.id if link is not None else None
                adds = True
                if kind in figures.CHANGE_KINDS:
                    host = None
                    if document_id is not None:
                        host = await figures.change_host(self.session, project_id, kind, document_id)
                        if host.contract_id is not None:
                            parent_kind, parent_id = "contract", host.contract_id
                    parent = None
                    if parent_kind and parent_id:
                        parent = await self.repo.find_link(project_id, parent_kind, parent_id)
                    if parent is not None:
                        link = parent
                        # Already inside the header: the contract's figure carries it, nothing is added twice.
                        adds = not (host is not None and host.posted)
                elif link is None and parent_kind and parent_id:
                    link = await self.repo.find_link(project_id, parent_kind, parent_id)
                if link is None:
                    return not_in_matrix
                item_ids = [link.item_id]
                per_item, _committed, _r = await self.committed_for_items(matrix, project, schedule, on_date=today)
                bound_now = await self.item_committed(
                    matrix, project, sched_ccy, per_item.get(link.item_id, []), on_date=today
                )
                would_commit = await self.item_committed(
                    matrix,
                    project,
                    sched_ccy,
                    per_item.get(link.item_id, []),
                    on_date=today,
                    # The document's present figure is replaced by its new amount.
                    without_link=own_link_id,
                    plus=(new,) if adds else (),
                )
        except FxRateMissing:
            return {"result": severity, "reasons": [{"code": "fx_rate_missing"}], "item_id": str(item_ids[0])}
        releases = await self.repo.list_releases(project_id, item_ids)
        decided = self.released_in_schedule_currency(releases)
        expired = self.expired_in_schedule_currency(releases, today)
        # A release past its date covers what is bound under it today and nothing new (bound_now).
        released = ev.release_in_force(decided, expired, bound_now)
        tol = schedule.variation_tolerance
        ceiling = ev.tolerance_ceiling(released, parse_amount(tol.absolute), parse_amount(tol.percent))
        if released > 0 and would_commit <= ceiling:
            return {"result": "ok", "reasons": [], "item_id": str(item_ids[0])}
        would_fit_in_date = decided > 0 and would_commit <= ev.tolerance_ceiling(
            decided, parse_amount(tol.absolute), parse_amount(tol.percent)
        )
        reason = {
            # Only the passed date stands in the way: say so, a renewed release is what is needed.
            "code": "release_expired" if released < decided and would_fit_in_date else "commitment_not_released",
            "released": str(released),
            "ceiling": str(ceiling),
            "would_commit": str(would_commit),
            "currency": sched_ccy,
        }
        return {"result": severity, "reasons": [reason], "item_id": str(item_ids[0])}

    # ── gate evidence, validation payload, export rows ─────────────────────

    async def gate_items(self, project_id: uuid.UUID, gate_code: str, area_code: str | None) -> list[CommitmentItem]:
        items = [i for i in await self.repo.list_items(project_id) if i.gate_code == gate_code]
        return [i for i in items if area_code is None or i.governance_area_code == area_code]

    async def validation_payload(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        matrix = await self.require_matrix(project_id)
        schedule = await self.schedule_for(matrix)
        data = await self.item_views(project_id, today=today, with_exposure=True)
        releases = await self.repo.list_releases(project_id)
        links = await self.repo.list_links(project_id)
        groups: dict[str, list[dict[str, Any]]] = {}
        for v in data["items"]:
            if v["split_group"]:
                groups.setdefault(v["split_group"], []).append(v)
        return {
            "today": today.isoformat(),
            "schedule": schedule.model_dump(mode="json"),
            "items": data["items"],
            "releases": [
                {
                    "id": str(r.id),
                    "item_id": str(r.item_id),
                    "outcome": r.outcome,
                    "required_tier": r.required_tier,
                    "evaluated_amount": str(r.evaluated_amount),
                    "commitment_type": next(
                        (v["commitment_type"] for v in data["items"] if v["id"] == str(r.item_id)), None
                    ),
                    "flags": next((v["flags"] for v in data["items"] if v["id"] == str(r.item_id)), []),
                    "schedule_version": r.schedule_version,
                    "escalate_outside": r.escalate_outside,
                }
                for r in releases
            ],
            "links": [
                {"kind": lk.kind, "document_id": str(lk.document_id), "item_id": str(lk.item_id)} for lk in links
            ],
            "split_groups": {k: [x["id"] for x in v] for k, v in groups.items()},
        }


def _schedule_entry(raw: dict[str, Any]) -> ScheduleEntry:
    if not isinstance(raw, dict) or not raw.get("milestone"):
        raise ValueError("milestone required")
    from_date = _day(raw.get("from_date"))
    progress = parse_amount(raw["progress_pct"]) if raw.get("progress_pct") not in (None, "") else None
    if from_date is None and progress is None:
        raise ValueError("from_date or progress_pct required")
    amount = parse_amount(raw["charge_amount"]) if raw.get("charge_amount") not in (None, "") else None
    pct = parse_amount(raw["charge_pct"]) if raw.get("charge_pct") not in (None, "") else None
    if (amount is None) == (pct is None):
        raise ValueError("exactly one of charge_amount or charge_pct")
    return ScheduleEntry(str(raw["milestone"]), from_date, progress, amount, pct)
