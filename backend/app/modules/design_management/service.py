# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management service: every write and every computed view of the module.

Sections, in SPEC build order:
    setup       -- pin a numbering scheme and a reports catalogue; scheme change with renumber (rule 9)
    wbs         -- the one PSP (``ProjectWBS``) with rules 1-4
    roles, approval points (rules 21, 22)
    deliverables (rule 15, computed state)
    numbering   -- preview, allocate under row lock, validate (rules 5-8, 10) and the CDE hook
    drawings    -- the register: a CDE container plus the 1:1 extension (rule 11)
    distribution and releases (rules 12-14)
    reviews, reports (rules 17, 18), permits (rules 19, 20)
    readiness   -- governance evidence (rule 16), frame documents (rule 23), validation payload

Callers pass ids already scoped to a project the caller may access (the router
runs ``verify_project_access``); every child row is looked up by
``(project_id, id)``, so an id from another project is 404.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.demo_history import RECORDING_DEMO_HISTORY
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.design_management import fsm as dfsm
from app.modules.design_management import numbering as nb
from app.modules.design_management import rules as dr
from app.modules.design_management import wbs as wr
from app.modules.design_management import wbs_refs
from app.modules.design_management.catalogue import (
    DEFAULT_REPORTS_ID,
    DEFAULT_SCHEME_ID,
    NUMBERING_KIND,
    REPORTS_KIND,
    DesignReports,
    DrawingNumbering,
    register_kinds,
)
from app.modules.design_management.errors import DesignError, conflict, forbidden, not_found
from app.modules.design_management.hosting import design_host
from app.modules.design_management.models import (
    DesignApprovalPoint,
    DesignDeliverable,
    DesignDistributionRule,
    DesignDrawing,
    DesignNumberCounter,
    DesignNumberReservation,
    DesignPermit,
    DesignPermitItem,
    DesignRelease,
    DesignReport,
    DesignReview,
    DesignReviewComment,
    DesignRole,
    DesignSetup,
)

logger = logging.getLogger(__name__)

_PART_COLUMNS = (
    "originator_code",
    "functional_breakdown",
    "spatial_breakdown",
    "form_code",
    "discipline_code",
    "sequence_number",
)
APPROVAL_TARGET_KIND = "design_approval_point"
RELEASE_TARGET_KIND = "design_release"
#: Metadata key marking a CDE container as a design frame document (server-set only).
FRAME_MARKER = "design_frame_document"
FRAME_CODE_PREFIX = "DESIGN-FRAME-"
#: The registers a frame document is generated from; the same names the export route takes.
FRAME_REGISTERS: tuple[str, ...] = ("register", "matrix", "reports", "permit")

PARTY_KINDS = (
    "owner",
    "lead_designer",
    "discipline_designer",
    "specialist",
    "checker",
    "authority",
    "contractor_designer",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise DesignError("invalid_id", 422, detail=str(value)) from exc


def _uuids(values: Any) -> list[str]:
    return [str(_uuid(v)) for v in (values or [])]


def _violation(code: str, kind: str, row_id: Any, label: str, **extra: Any) -> dict[str, Any]:
    """One finding about a record: ``{code, kind, id, label}``; ``label`` is what a person calls the record."""
    return {"code": code, "kind": kind, "id": _s(row_id), "label": label} | extra


@dataclass(frozen=True)
class Caller:
    """Who asks, as the router's permission checks answered. The service never sees a role."""

    actor_id: uuid.UUID
    edit: bool
    manage: bool
    release: bool


def _flag(refused: DesignError | str | None = None, *, applies: bool = True) -> dict[str, Any]:
    """One ``can`` entry.

    ``applies`` says whether the action exists for this row at all (a state a
    person never types does not apply); ``allowed`` whether this caller may
    take it now; ``reason`` is the code the write would answer with.
    """
    reason = refused.code if isinstance(refused, DesignError) else refused
    return {"allowed": applies and reason is None, "applies": applies, "reason": reason}


def _edge(machine: Any, row: Any, target: str) -> DesignError | None:
    """The refusal of a move the state machine does not have, or ``None``."""
    if machine.has_transition(row.status, target):
        return None
    return conflict("invalid_transition", detail=f"{row.status} -> {target}")


class DesignService:
    """Business logic of design management."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Read-side memo of :meth:`capabilities` only; no write decides from it.
        self._cap_memo: dict[Any, Any] = {}

    # ── plumbing ──────────────────────────────────────────────────────────

    async def _fsm(self, machine: Any, entity: Any, target: str, actor_id: Any, reason: str | None = None) -> None:
        try:
            await machine.apply(
                self.session,
                entity,
                target,
                actor_id=_s(actor_id),
                reason=reason,
                extra_metadata={"project_id": _s(getattr(entity, "project_id", None))},
                entity_type=machine.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _audit(self, actor_id: Any, entity_type: str, entity_id: Any, action: str, **meta: Any) -> None:
        await log_activity(
            self.session,
            actor_id=_s(actor_id),
            entity_type=entity_type,
            entity_id=_s(entity_id),
            action=action,
            metadata={k: _s(v) if isinstance(v, uuid.UUID) else v for k, v in meta.items()},
        )

    def _publish(self, name: str, **data: Any) -> None:
        """Publish after commit. ``name`` is the full event name, written as a literal at every call site."""
        payload = {k: _s(v) if isinstance(v, uuid.UUID) else v for k, v in data.items()}
        publish_after_commit(self.session, name, payload, source_module="oe_design_management")

    async def _get(self, model: Any, project_id: uuid.UUID, row_id: Any, code: str, *, lock: bool = False) -> Any:
        stmt = select(model).where(model.id == _uuid(row_id), model.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise not_found(code)
        return row

    async def _list(self, model: Any, project_id: uuid.UUID, *order: Any) -> list[Any]:
        stmt = select(model).where(model.project_id == project_id)
        if order:
            stmt = stmt.order_by(*order)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    async def _project_lock(self, project_id: uuid.UUID, scope: str) -> None:
        """Serialise one kind of write per project until the transaction ends.

        Two requests that both read "no such code yet" would both insert; the
        advisory lock makes the second wait and then see the first one's row.
        """
        if getattr(getattr(self.session.get_bind(), "dialect", None), "name", "") != "postgresql":
            return
        key = f"design_management:{scope}:{project_id}"
        await self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))

    async def _next_code(self, model: Any, project_id: uuid.UUID, prefix: str) -> str:
        await self._project_lock(project_id, model.__tablename__)
        count = (
            await self.session.execute(select(func.count()).select_from(model).where(model.project_id == project_id))
        ).scalar_one()
        existing = {
            c for (c,) in (await self.session.execute(select(model.code).where(model.project_id == project_id)))
        }
        n = int(count) + 1
        while f"{prefix}-{n:03d}" in existing:
            n += 1
        return f"{prefix}-{n:03d}"

    # ── governance phase model ────────────────────────────────────────────

    async def phases(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """The phases of the project's pinned governance model (SPEC decision 12); empty when none is pinned."""
        from app.modules.project_governance.catalogue import label_of
        from app.modules.project_governance.public import project_catalogue

        catalogue = await project_catalogue(self.session, project_id)
        if catalogue is None:
            return []
        return [
            {"code": p.code, "order": p.order, "spine_key": p.spine_key, "name": label_of(p.name_key, p.labels)}
            for p in sorted(catalogue.phases, key=lambda p: p.order)
        ]

    async def gates_in_use(self, project_id: uuid.UUID) -> bool:
        """Whether the project decides gates at all.

        Nothing in design waits for a gate: approval points and releases are decided on
        approval routes, reports and permits by hand. Without gates the frame document
        never turns binding either, so the registers stay editable. The read says so,
        and the screen names it instead of an unknown gate.
        """
        from app.modules.project_governance.public import project_gates

        return bool(await project_gates(self.session, project_id))

    async def _check_phase(self, project_id: uuid.UUID, phase_code: str | None) -> None:
        if not phase_code:
            return
        codes = {p["code"] for p in await self.phases(project_id)}
        if codes and phase_code not in codes:
            raise DesignError("phase_unknown", 422, detail=phase_code)

    async def _require_phase(self, project_id: uuid.UUID, phase_code: str | None) -> None:
        """A deliverable or review belongs to a phase where the project has phases; without a model it may have none."""
        if not phase_code and await self.phases(project_id):
            raise DesignError("phase_required", 422)

    # ── setup and catalogues ──────────────────────────────────────────────

    async def get_setup(self, project_id: uuid.UUID, *, lock: bool = False) -> DesignSetup | None:
        stmt = select(DesignSetup).where(DesignSetup.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_setup(self, project_id: uuid.UUID, *, lock: bool = False) -> DesignSetup:
        setup = await self.get_setup(project_id, lock=lock)
        if setup is None:
            raise not_found("setup_missing")
        return setup

    async def scheme(self, setup: DesignSetup) -> DrawingNumbering:
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        register_kinds()
        return await resolve_catalogue(
            self.session, setup.scheme_source, setup.scheme_id, setup.scheme_version, kind=NUMBERING_KIND, from_pin=True
        )

    async def reports_catalogue(self, setup: DesignSetup) -> DesignReports:
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        register_kinds()
        return await resolve_catalogue(
            self.session,
            setup.reports_source,
            setup.reports_id,
            setup.reports_version,
            kind=REPORTS_KIND,
            from_pin=True,
        )

    async def _pinnable(self, tenant_id: str | None, source: str, cid: str, version: int | None, kind: str) -> int:
        from app.modules.project_governance.catalogue_store import CatalogueStore

        register_kinds()
        return await CatalogueStore(self.session).assert_pinnable(tenant_id, source, cid, version, kind=kind)

    async def assert_not_binding(self, project_id: uuid.UUID) -> None:
        """Rule 23: once the design frame document is binding, changes go through a governance change request."""
        if RECORDING_DEMO_HISTORY.get():
            # The demo seed writes the history the frame was bound on, not a live change.
            return
        refused = await self.binding_refusal(project_id)
        if refused is not None:
            raise refused

    async def binding_refusal(self, project_id: uuid.UUID) -> DesignError | None:
        """The refusal while the design frame document is binding, or ``None``."""
        from app.modules.project_governance.public import project_documents

        host = await design_host(self.session, project_id)
        if host is None:
            return None
        for d in await project_documents(self.session, project_id):
            if d.code == host.doc_type and d.area_code == host.area_code and d.status == "binding":
                return conflict("binding_requires_change_request")
        return None

    async def set_setup(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        scheme_source: str = "shipped",
        scheme_id: str | None = None,
        scheme_version: int | None = None,
        reports_source: str = "shipped",
        reports_id: str | None = None,
        reports_version: int | None = None,
        four_eyes_release: bool = True,
    ) -> DesignSetup:
        """Pin a scheme and a reports catalogue on a project for the first time."""
        if await self.get_setup(project_id) is not None:
            raise conflict("setup_exists")
        from app.modules.project_governance.public import default_catalogue_pin

        project = await self._project(project_id)
        country = getattr(project, "country_code", None)
        register_kinds()
        if scheme_id is None:
            # Which scheme a country starts with is module 1's to say (pack, regional pack, the one shipped
            # scheme claiming the country). This module only knows what to pin when the port names nothing.
            pin = default_catalogue_pin(NUMBERING_KIND, country)
            if pin is not None:
                scheme_source, scheme_id, scheme_version = pin.source, pin.catalogue_id, pin.version
            else:
                scheme_id = DEFAULT_SCHEME_ID
        if reports_id is None:
            pin = default_catalogue_pin(REPORTS_KIND, country)
            if pin is not None:
                reports_source, reports_id, reports_version = pin.source, pin.catalogue_id, pin.version
            else:
                reports_id = DEFAULT_REPORTS_ID
        sv = await self._pinnable(tenant_id, scheme_source, scheme_id, scheme_version, NUMBERING_KIND)
        rv = await self._pinnable(tenant_id, reports_source, reports_id, reports_version, REPORTS_KIND)
        setup = await self._add(
            DesignSetup(
                project_id=project_id,
                scheme_source=scheme_source,
                scheme_id=scheme_id,
                scheme_version=sv,
                reports_source=reports_source,
                reports_id=reports_id,
                reports_version=rv,
                previous_schemes=[],
                four_eyes_release=four_eyes_release,
                target_suitability={},
                created_by=actor_id,
            )
        )
        await self._audit(actor_id, "design_setup", setup.id, "created", scheme=f"{scheme_source}:{scheme_id}@{sv}")
        self._publish("design_management.setup.pinned", project_id=project_id, scheme_id=scheme_id, version=sv)
        return setup

    async def update_setup(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID) -> DesignSetup:
        setup = await self.require_setup(project_id, lock=True)
        if {"hierarchical_codes", "wbs_separator", "target_suitability"} & data.keys():
            await self.assert_not_binding(project_id)
        for key in (
            "four_eyes_release",
            "default_distribution_purpose",
            "hierarchical_codes",
            "wbs_separator",
            "target_suitability",
            "approval_route_id",
            "release_route_id",
            "lead_designer_role_id",
        ):
            if key in data:
                value = data[key]
                if key.endswith("_id"):
                    value = _uuid(value)
                    if key == "lead_designer_role_id" and value is not None:
                        await self._get(DesignRole, project_id, value, "role_not_found")
                setattr(setup, key, value)
        await self.session.flush()
        await self._audit(actor_id, "design_setup", setup.id, "updated", fields=sorted(data))
        return setup

    async def change_scheme(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        source: str,
        scheme_id: str,
        version: int | None = None,
        reports: bool = False,
    ) -> dict[str, Any]:
        """Rule 9: pin another scheme (or reports catalogue); existing numbers are kept and flagged."""
        await self.assert_not_binding(project_id)
        setup = await self.require_setup(project_id, lock=True)
        if reports:
            setup.reports_version = await self._pinnable(tenant_id, source, scheme_id, version, REPORTS_KIND)
            setup.reports_source, setup.reports_id = source, scheme_id
            await self.session.flush()
            return {"setup": setup, "legacy": 0}
        pinned = await self._pinnable(tenant_id, source, scheme_id, version, NUMBERING_KIND)
        setup.previous_schemes = [
            *(setup.previous_schemes or []),
            {
                "source": setup.scheme_source,
                "id": setup.scheme_id,
                "version": setup.scheme_version,
                "until": _now().isoformat(),
            },
        ]
        setup.scheme_source, setup.scheme_id, setup.scheme_version = source, scheme_id, pinned
        scheme = await self.scheme(setup)
        legacy = 0
        for drawing, container in await self._drawings_with_containers(project_id):
            if not nb.validate(scheme, container.container_code).valid:
                drawing.legacy_scheme = True
                legacy += 1
        await self.session.flush()
        await self._audit(actor_id, "design_setup", setup.id, "scheme_changed", scheme=scheme_id, legacy=legacy)
        self._publish(
            "design_management.setup.scheme_changed", project_id=project_id, scheme_id=scheme_id, legacy=legacy
        )
        return {"setup": setup, "legacy": legacy}

    # ── WBS (rules 1-4) ───────────────────────────────────────────────────

    async def wbs_rows(self, project_id: uuid.UUID) -> list[Any]:
        from app.modules.projects.models import ProjectWBS

        stmt = (
            select(ProjectWBS)
            .where(ProjectWBS.project_id == project_id)
            .order_by(ProjectWBS.level, ProjectWBS.sort_order, ProjectWBS.code)
            # A caller may have changed rows with a bulk UPDATE; read what is stored, not what is cached.
            .execution_options(populate_existing=True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    @staticmethod
    def _node(row: Any) -> wr.Node:
        return wr.Node(row.id, row.parent_id, row.code, bool((row.metadata_ or {}).get("closed")))

    async def _wbs_settings(self, project_id: uuid.UUID) -> tuple[bool, str]:
        setup = await self.get_setup(project_id)
        return (setup.hierarchical_codes, setup.wbs_separator) if setup else (True, ".")

    async def wbs_tree_violations(self, project_id: uuid.UUID) -> list[dict[str, str]]:
        """Rules 1-3 over the stored tree, one entry per node, for ``core/wbs_rules``.

        A project without a design setup does not use design management and is
        not checked at all. The caller diffs this list around a write, so
        violations the tree already had never refuse an unrelated change.
        """
        setup = await self.get_setup(project_id)
        if setup is None:
            return []
        rows = await self.wbs_rows(project_id)
        return wr.tree_errors(
            [self._node(r) for r in rows], hierarchical=setup.hierarchical_codes, separator=setup.wbs_separator
        )

    async def wbs_tree(self, project_id: uuid.UUID) -> dict[str, Any]:
        rows = await self.wbs_rows(project_id)
        counts = await wbs_refs.reference_counts(self.session, project_id, rows)
        duplicates = wr.duplicate_codes(self._node(r) for r in rows)
        return {"rows": rows, "counts": counts, "duplicates": duplicates}

    async def _wbs_get(self, project_id: uuid.UUID, node_id: Any) -> Any:
        from app.modules.projects.models import ProjectWBS

        return await self._get(ProjectWBS, project_id, node_id, "wbs_node_not_found", lock=True)

    def _rule(self, exc: wr.WbsRuleError) -> DesignError:
        return DesignError(exc.code, 409 if exc.code == "wbs_code_duplicate" else 422, detail=exc.detail or None)

    async def _lock_wbs(self, project_id: uuid.UUID) -> None:
        """Serialise WBS writes of one project: the setup row (or project row) is the lock."""
        from app.modules.projects.models import Project

        await self.session.execute(select(Project.id).where(Project.id == project_id).with_for_update())

    async def create_wbs(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID) -> Any:
        from app.modules.projects.models import ProjectWBS

        await self._lock_wbs(project_id)
        rows = await self.wbs_rows(project_id)
        parent_id = _uuid(data.get("parent_id"))
        hierarchical, sep = await self._wbs_settings(project_id)
        code = (data.get("code") or "").strip()
        try:
            wr.check_code(
                [self._node(r) for r in rows], code=code, parent_id=parent_id, hierarchical=hierarchical, separator=sep
            )
        except wr.WbsRuleError as exc:
            raise self._rule(exc) from exc
        parent = next((r for r in rows if r.id == parent_id), None)
        meta = {"kind": data.get("kind") or "package"}
        if data.get("discipline"):
            meta["discipline"] = data["discipline"]
        row = await self._add(
            ProjectWBS(
                project_id=project_id,
                parent_id=parent_id,
                code=code,
                name=data.get("name") or code,
                level=(parent.level + 1) if parent else 0,
                sort_order=int(data.get("sort_order") or 0),
                wbs_type=data.get("wbs_type") or "cost",
                metadata_=meta,
            )
        )
        await self._audit(actor_id, "projects_wbs", row.id, "created", code=code)
        return row

    async def patch_wbs(self, project_id: uuid.UUID, node_id: Any, data: dict[str, Any], *, actor_id: uuid.UUID) -> Any:
        """Rename, re-kind, move (``parent_id``) or renumber (``code``, the subtree follows)."""
        await self._lock_wbs(project_id)
        row = await self._wbs_get(project_id, node_id)
        rows = await self.wbs_rows(project_id)
        nodes = [self._node(r) for r in rows]
        hierarchical, sep = await self._wbs_settings(project_id)
        new_parent = _uuid(data["parent_id"]) if "parent_id" in data else row.parent_id
        new_code = (data.get("code") or row.code).strip()
        try:
            wr.check_code(
                nodes, code=new_code, parent_id=new_parent, node_id=row.id, hierarchical=hierarchical, separator=sep
            )
            plan = wr.renumber_plan(nodes, row.id, new_code, separator=sep) if new_code != row.code else {}
        except wr.WbsRuleError as exc:
            raise self._rule(exc) from exc
        by_id = {r.id: r for r in rows}
        for nid, code in plan.items():
            by_id[nid].code = code
        if new_parent != row.parent_id:
            parent = by_id.get(new_parent) if new_parent else None
            row.parent_id = new_parent
            delta = ((parent.level + 1) if parent else 0) - row.level
            row.level += delta
            for d in wr.descendants(nodes, row.id):
                by_id[d.id].level += delta
        meta = dict(row.metadata_ or {})
        for key in ("kind", "discipline"):
            if key in data:
                meta[key] = data[key]
        row.metadata_ = meta
        if "name" in data:
            row.name = data["name"]
        await self.session.flush()
        await self._audit(actor_id, "projects_wbs", row.id, "updated", renumbered=len(plan))
        return row

    async def renumber_preview(self, project_id: uuid.UUID, node_id: Any, new_code: str) -> list[dict[str, str]]:
        row = await self._wbs_get(project_id, node_id)
        rows = await self.wbs_rows(project_id)
        _h, sep = await self._wbs_settings(project_id)
        try:
            plan = wr.renumber_plan([self._node(r) for r in rows], row.id, new_code, separator=sep)
        except wr.WbsRuleError as exc:
            raise self._rule(exc) from exc
        by_id = {r.id: r for r in rows}
        return [{"id": str(k), "old": by_id[k].code, "new": v} for k, v in plan.items()]

    async def close_wbs(self, project_id: uuid.UUID, node_id: Any, *, closed: bool, actor_id: uuid.UUID) -> Any:
        """Rule 3: closing a node closes its whole subtree in the same call; a node under a closed parent stays closed."""
        await self._lock_wbs(project_id)
        row = await self._wbs_get(project_id, node_id)
        targets = [row]
        if closed:
            rows = await self.wbs_rows(project_id)
            below = {d.id for d in wr.descendants([self._node(r) for r in rows], row.id)}
            targets += [r for r in rows if r.id in below]
        elif row.parent_id is not None:
            parent = await self._wbs_get(project_id, row.parent_id)
            if (parent.metadata_ or {}).get("closed"):
                raise conflict("wbs_node_closed", detail=parent.code)
        for target in targets:
            target.metadata_ = {**(target.metadata_ or {}), "closed": closed}
        await self.session.flush()
        await self._audit(actor_id, "projects_wbs", row.id, "closed" if closed else "reopened")
        return row

    async def delete_wbs(self, project_id: uuid.UUID, node_id: Any, *, actor_id: uuid.UUID) -> None:
        """Rule 3: refused while the node or any descendant is referenced anywhere."""
        await self._lock_wbs(project_id)
        row = await self._wbs_get(project_id, node_id)
        rows = await self.wbs_rows(project_id)
        counts = await wbs_refs.reference_counts(self.session, project_id, rows)
        referenced = {uuid.UUID(k) for k in counts}
        if not wr.deletable([self._node(r) for r in rows], row.id, referenced):
            raise conflict("wbs_node_referenced")
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "projects_wbs", row.id, "deleted")

    async def assert_wbs_usable(self, project_id: uuid.UUID, node_id: Any) -> uuid.UUID | None:
        """A WBS reference from this module: the node exists in the project and is not closed (rule 3)."""
        nid = _uuid(node_id)
        if nid is None:
            return None
        row = await self._wbs_get(project_id, nid)
        if (row.metadata_ or {}).get("closed"):
            raise DesignError("wbs_node_closed", 422, detail=row.code)
        return nid

    async def unresolved_wbs(self, project_id: uuid.UUID) -> list[wbs_refs.Reference]:
        return await wbs_refs.unresolved_references(self.session, project_id, await self.wbs_rows(project_id))

    # ── roles (rule 21) ───────────────────────────────────────────────────

    async def _check_originator(self, project_id: uuid.UUID, role: DesignRole) -> None:
        if role.party_kind != "discipline_designer":
            return
        if not (role.originator_code or "").strip():
            raise DesignError("originator_required", 422)
        await self._project_lock(project_id, "originator")
        stmt = select(DesignRole.id).where(
            DesignRole.project_id == project_id,
            func.upper(DesignRole.originator_code) == role.originator_code.upper(),
            DesignRole.id != role.id,
            DesignRole.party_kind == "discipline_designer",
            DesignRole.status != "released",
        )
        # No autoflush: a patched role would reach the unique index before this check can answer 409.
        with self.session.no_autoflush:
            taken = (await self.session.execute(stmt)).first() is not None
        if taken:
            raise conflict("originator_duplicate")

    async def create_role(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID, tenant_id: str | None = None
    ) -> DesignRole:
        if data.get("party_kind") not in PARTY_KINDS:
            raise DesignError("party_kind_invalid", 422)
        await self.assert_not_binding(project_id)
        await self._contact_in_scope(tenant_id, data.get("contact_id"))
        wbs_ids = [str(await self.assert_wbs_usable(project_id, w)) for w in data.get("responsible_wbs_ids") or []]
        role = DesignRole(
            id=uuid.uuid4(),
            project_id=project_id,
            code=(data.get("code") or await self._next_code(DesignRole, project_id, "ROLE")).strip(),
            title=data.get("title") or "",
            party_kind=data["party_kind"],
            discipline_code=(data.get("discipline_code") or None),
            contact_id=_uuid(data.get("contact_id")),
            user_id=_uuid(data.get("user_id")),
            originator_code=(data.get("originator_code") or "").strip().upper() or None,
            contract_package_id=_uuid(data.get("contract_package_id")),
            responsible_wbs_ids=wbs_ids,
            status="planned",
        )
        await self._project_lock(project_id, DesignRole.__tablename__)
        await self._check_originator(project_id, role)
        await self._unique_code(DesignRole, project_id, role.code)
        await self._add(role)
        await self._audit(actor_id, "design_role", role.id, "created", code=role.code)
        return role

    async def _unique_code(self, model: Any, project_id: uuid.UUID, code: str, row_id: Any = None) -> None:
        stmt = select(model.id).where(model.project_id == project_id, model.code == code)
        if row_id is not None:
            stmt = stmt.where(model.id != row_id)
        if (await self.session.execute(stmt)).first() is not None:
            raise conflict("code_duplicate")

    async def patch_role(
        self,
        project_id: uuid.UUID,
        role_id: Any,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None = None,
    ):
        await self.assert_not_binding(project_id)
        await self._contact_in_scope(tenant_id, data.get("contact_id"))
        role = await self._get(DesignRole, project_id, role_id, "role_not_found", lock=True)
        if "state" in data and data["state"] != role.status:
            refused = _edge(dfsm.ROLE_FSM, role, data["state"])
            if refused is not None:
                raise refused
            await self._fsm(dfsm.ROLE_FSM, role, data["state"], actor_id)
        for key in ("title", "discipline_code", "party_kind"):
            if key in data:
                setattr(role, key, data[key])
        if role.party_kind not in PARTY_KINDS:
            raise DesignError("party_kind_invalid", 422)
        for key in ("contact_id", "user_id", "contract_package_id"):
            if key in data:
                setattr(role, key, _uuid(data[key]))
        if "originator_code" in data:
            role.originator_code = (data["originator_code"] or "").strip().upper() or None
        if "responsible_wbs_ids" in data:
            role.responsible_wbs_ids = [
                str(await self.assert_wbs_usable(project_id, w)) for w in data["responsible_wbs_ids"] or []
            ]
        if "code" in data:
            await self._unique_code(DesignRole, project_id, data["code"], role.id)
            role.code = data["code"]
        await self._check_originator(project_id, role)
        await self.session.flush()
        await self._audit(actor_id, "design_role", role.id, "updated")
        return role

    async def role_references(self, project_id: uuid.UUID, role_id: uuid.UUID) -> list[dict[str, Any]]:
        """Everything in the project that still points at a role, as ``{code, kind, id, label}``."""
        rid = str(role_id)
        out: list[dict[str, Any]] = []

        def hit(kind: str, row: Any) -> None:
            code = getattr(row, "code", None)
            title = getattr(row, "title", None) or getattr(row, "text", None) or ""
            label = " ".join(p for p in (code, title[:80]) if p)
            out.append(_violation("role_in_use", kind, row.id, label, ref=code))

        for kind, model, columns in (
            ("drawing", DesignDrawing, ("role_id",)),
            ("deliverable", DesignDeliverable, ("role_id",)),
            ("approval_point", DesignApprovalPoint, ("approver_role_id",)),
            ("report", DesignReport, ("author_role_id", "checker_role_id")),
            ("distribution_rule", DesignDistributionRule, ("recipient_role_id",)),
            ("review_comment", DesignReviewComment, ("answered_by_role_id",)),
            ("setup", DesignSetup, ("lead_designer_role_id",)),
        ):
            for row in await self._list(model, project_id):
                if any(getattr(row, c) == role_id for c in columns):
                    hit(kind, row)
        for review in await self._list(DesignReview, project_id):
            if rid in [str(x) for x in review.reviewer_role_ids or []]:
                hit("review", review)
        return out

    async def delete_role(self, project_id: uuid.UUID, role_id: Any, *, actor_id: uuid.UUID) -> None:
        await self.assert_not_binding(project_id)
        role = await self._get(DesignRole, project_id, role_id, "role_not_found", lock=True)
        used = await self.role_references(project_id, role.id)
        if used:
            raise conflict("role_in_use", violations=used)
        await self.session.delete(role)
        await self.session.flush()
        await self._audit(actor_id, "design_role", role.id, "deleted")

    async def roles(self, project_id: uuid.UUID) -> list[DesignRole]:
        return await self._list(DesignRole, project_id, DesignRole.code)

    # ── approval points (rule 22) ─────────────────────────────────────────

    async def create_approval_point(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        await self._check_phase(project_id, data.get("phase_code"))
        if data.get("approver_role_id"):
            await self._get(DesignRole, project_id, data["approver_role_id"], "role_not_found")
        await self._gate_in_project(project_id, data.get("governance_gate_id"))
        code = data.get("code") or await self._next_code(DesignApprovalPoint, project_id, "AP")
        await self._unique_code(DesignApprovalPoint, project_id, code)
        row = await self._add(
            DesignApprovalPoint(
                project_id=project_id,
                code=code,
                title=data.get("title") or "",
                phase_code=data.get("phase_code"),
                kind=data["kind"],
                governance_gate_id=_uuid(data.get("governance_gate_id")),
                approver_role_id=_uuid(data.get("approver_role_id")),
                status="open",
                note=data.get("note") or "",
            )
        )
        await self._audit(actor_id, "design_approval_point", row.id, "created", code=code)
        return row

    async def patch_approval_point(self, project_id: uuid.UUID, ap_id: Any, data: dict[str, Any], *, actor_id):
        row = await self._get(DesignApprovalPoint, project_id, ap_id, "approval_point_not_found", lock=True)
        if row.status not in ("open", "rejected"):
            raise conflict("approval_point_locked")
        if "phase_code" in data:
            await self._check_phase(project_id, data["phase_code"])
        for key in ("title", "phase_code", "kind", "note"):
            if key in data:
                setattr(row, key, data[key])
        if data.get("approver_role_id"):
            await self._get(DesignRole, project_id, data["approver_role_id"], "role_not_found")
        if "governance_gate_id" in data:
            await self._gate_in_project(project_id, data["governance_gate_id"])
        for key in ("governance_gate_id", "approver_role_id"):
            if key in data:
                setattr(row, key, _uuid(data[key]))
        await self.session.flush()
        return row

    async def _gate_in_project(self, project_id: uuid.UUID, gate_id: Any) -> uuid.UUID | None:
        """A gate of this project's current phase model, read through module 1's port."""
        from app.modules.project_governance.public import project_gates

        gid = _uuid(gate_id)
        if gid is None:
            return None
        if gid not in {g.id for g in await project_gates(self.session, project_id)}:
            raise not_found("governance_gate_not_found")
        return gid

    async def _contact_in_scope(self, tenant_id: str | None, contact_id: Any) -> uuid.UUID | None:
        """A contact of the caller's tenant. Without a tenant nothing resolves (fails closed)."""
        from app.modules.contacts.repository import ContactRepository

        cid = _uuid(contact_id)
        if cid is None:
            return None
        contact = await ContactRepository(self.session).get(cid)
        owner = str(tenant_id) if tenant_id else None
        if contact is None or owner is None or owner not in (contact.tenant_id, contact.created_by):
            raise not_found("contact_not_found")
        return cid

    OPTION_KINDS = (
        "contacts",
        "contract_packages",
        "governance_gates",
        "recipient_lists",
        "review_cycles",
        "authority_submissions",
        "forms",
        "wbs_nodes",
    )

    async def options(
        self, project_id: uuid.UUID, kind: str, *, actor_id: uuid.UUID, tenant_id: str | None
    ) -> dict[str, Any]:
        """What a reference field of this project may point at: ``{kind, available, reason, items}``.

        Each item is ``{id, label, code}``. The filter is the one the write
        applies, so nothing listed here is refused for not belonging to the
        project. ``available`` is false with a ``reason`` when the source of
        the list is not there (no scheme field, no module); that is not the
        same as an empty list.
        """
        if kind not in self.OPTION_KINDS:
            raise DesignError("option_kind_unknown", 422, detail=kind)
        items: list[dict[str, Any]] = []
        reason: str | None = None

        def add(row_id: Any, label: str, code: str | None = None) -> None:
            items.append({"id": _s(row_id), "label": label, "code": code})

        if kind == "contacts":
            from app.modules.contacts.repository import ContactRepository

            if tenant_id:
                rows, _total = await ContactRepository(self.session).list(owner_id=str(tenant_id), limit=500)
                for c in rows:
                    person = " ".join(p for p in (c.first_name, c.last_name) if p)
                    add(c.id, ", ".join(p for p in (c.company_name, person) if p) or str(c.id))
        elif kind == "contract_packages":
            # Contract packages belong to the delivery model module; this module holds only the soft link.
            reason = "source_not_installed"
        elif kind == "governance_gates":
            from app.modules.project_governance.public import project_gates

            for g in await project_gates(self.session, project_id):
                text = (g.label or {}).get("text") or {}
                add(g.id, text.get("en") or g.code, g.code)
                items[-1]["label_key"] = (g.label or {}).get("key")
                items[-1]["label_text"] = text or None
        elif kind == "recipient_lists":
            from app.modules.file_distribution.models import FileDistributionList

            stmt = (
                select(FileDistributionList)
                .where(
                    (FileDistributionList.project_id == project_id)
                    | (FileDistributionList.project_id.is_(None) & (FileDistributionList.owner_id == actor_id))
                )
                .order_by(FileDistributionList.name)
            )
            for lst in (await self.session.execute(stmt)).scalars():
                add(lst.id, lst.name)
        elif kind == "review_cycles":
            from app.modules.review_authority.models import ReviewCycle

            stmt = select(ReviewCycle).where(ReviewCycle.project_id == project_id).order_by(ReviewCycle.created_at)
            for cycle in (await self.session.execute(stmt)).scalars():
                add(cycle.id, " ".join(p for p in (cycle.authority_name, cycle.submission_ref) if p), cycle.status)
        elif kind == "authority_submissions":
            from app.modules.authority_submission.models import Submission

            stmt = select(Submission).where(Submission.project_id == project_id).order_by(Submission.created_at)
            for sub_row in (await self.session.execute(stmt)).scalars():
                add(sub_row.id, sub_row.title, sub_row.status)
        elif kind == "forms":
            setup = await self.get_setup(project_id)
            field = (await self.scheme(setup)).field("form") if setup is not None else None
            if setup is None:
                reason = "setup_missing"
            elif field is None or field.code_list == "free":
                reason = "scheme_has_no_form_list"
            else:
                for entry in field.code_list:
                    add(entry.code, (entry.labels or {}).get("en") or entry.code, entry.code)
                    items[-1]["label_key"] = entry.label_key or None
                    items[-1]["label_text"] = entry.labels
        elif kind == "wbs_nodes":
            for node in await self.wbs_rows(project_id):
                if not (node.metadata_ or {}).get("closed"):
                    add(node.id, " ".join(p for p in (node.code, node.name) if p), node.code)
        return {"kind": kind, "available": reason is None, "reason": reason, "items": items}

    async def _route(self, project_id: uuid.UUID, kind: str, pinned: uuid.UUID | None) -> Any:
        from app.modules.approval_routes.service import ApprovalRouteService

        svc = ApprovalRouteService(self.session)
        if pinned is not None:
            try:
                route = await svc.get_route(pinned)
            except Exception:
                route = None
            ok = route is not None and route.is_active and route.target_kind == kind
            return route if ok and route.project_id in (None, project_id) else None
        routes = [
            r
            for r in await svc.list_routes(project_id=project_id, target_kind=kind, include_inactive=False)
            if r.project_id in (None, project_id)
        ]
        routes.sort(key=lambda r: (r.project_id is None, r.created_at))
        return routes[0] if routes else None

    async def _start_instance(self, route: Any, kind: str, target_id: uuid.UUID, actor_id: uuid.UUID) -> uuid.UUID:
        from fastapi import HTTPException

        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        try:
            instance = await ApprovalRouteService(self.session).start_instance(
                InstanceCreate(route_id=route.id, target_kind=kind, target_id=target_id), started_by=actor_id
            )
        except HTTPException as exc:
            raise DesignError("route_start_failed", exc.status_code, detail=str(exc.detail)) from exc
        return instance.id

    async def submit_approval_point(self, project_id: uuid.UUID, ap_id: Any, *, actor_id: uuid.UUID):
        row = await self._get(DesignApprovalPoint, project_id, ap_id, "approval_point_not_found", lock=True)
        refused = await self.approval_submit_refusal(row)
        if refused is not None:
            raise refused
        route = await self._pinned_route(project_id, APPROVAL_TARGET_KIND)
        if row.status == "rejected":
            await self._fsm(dfsm.APPROVAL_POINT_FSM, row, "open", actor_id)
        await self._fsm(dfsm.APPROVAL_POINT_FSM, row, "in_review", actor_id)
        row.approval_instance_id = await self._start_instance(route, APPROVAL_TARGET_KIND, row.id, actor_id)
        row.submitted_by = actor_id
        await self.session.flush()
        self._publish("design_management.approval_point.submitted", project_id=project_id, approval_point_id=row.id)
        return row

    async def _pinned_route(self, project_id: uuid.UUID, kind: str) -> Any:
        """The approval route of ``kind`` this project decides with: the one pinned on the setup, else its only one."""
        setup = await self.get_setup(project_id)
        pinned = None
        if setup is not None:
            pinned = setup.approval_route_id if kind == APPROVAL_TARGET_KIND else setup.release_route_id
        return await self._route(project_id, kind, pinned)

    async def approval_submit_refusal(self, row: DesignApprovalPoint) -> DesignError | None:
        """Why this approval point cannot be submitted to its route now, or ``None``."""
        if row.status not in ("open", "rejected"):
            return conflict("invalid_transition", detail=f"{row.status} -> in_review")
        if await self._pinned_route(row.project_id, APPROVAL_TARGET_KIND) is None:
            return DesignError("no_approval_route", 422)
        return None

    @staticmethod
    def approval_reopen_refusal(row: DesignApprovalPoint) -> DesignError | None:
        """Why this approval point cannot be reopened, or ``None``. Only a rejected point is reopened."""
        if row.status != "rejected":
            return conflict("approval_point_not_rejected", detail=row.status)
        return None

    async def reopen_approval_point(self, project_id: uuid.UUID, ap_id: Any, *, actor_id: uuid.UUID):
        """Take a rejected point back to ``open`` so it can be changed and submitted again.

        The rejection stays in the transition log; the decision fields are
        cleared because they describe a verdict that no longer stands.
        """
        row = await self._get(DesignApprovalPoint, project_id, ap_id, "approval_point_not_found", lock=True)
        refused = self.approval_reopen_refusal(row)
        if refused is not None:
            raise refused
        await self._fsm(dfsm.APPROVAL_POINT_FSM, row, "open", actor_id, reason="reopened after rejection")
        row.approval_instance_id = None
        row.decided_by = row.decided_at = None
        await self.session.flush()
        self._publish("design_management.approval_point.open", project_id=project_id, approval_point_id=row.id)
        return row

    async def apply_approval_verdict(
        self, ap_id: uuid.UUID, instance_id: uuid.UUID | None, *, decision: str, decided_by: Any
    ) -> bool:
        """The route decided (rule 22: only the route entitles). Idempotent; four-eyes by submitter."""
        stmt = select(DesignApprovalPoint).where(DesignApprovalPoint.id == ap_id).with_for_update()
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None or row.status != "in_review":
            return False
        if instance_id is not None and row.approval_instance_id != instance_id:
            return False
        decider = _uuid(decided_by)
        if decision == "cancelled":
            # The route was cancelled: nobody decided, the point is open again and can be resubmitted.
            row.approval_instance_id = None
            await self._fsm(dfsm.APPROVAL_POINT_FSM, row, "open", decider, reason="approval route cancelled")
            await self.session.flush()
            self._publish("design_management.approval_point.open", project_id=row.project_id, approval_point_id=row.id)
            return True
        setup = await self.get_setup(row.project_id)
        if decision == "approved" and setup and setup.four_eyes_release and decider and decider == row.submitted_by:
            # The route let the submitter approve their own point; four-eyes refuses it.
            decision = "rejected"
            row.note = (row.note + "\n" if row.note else "") + "four_eyes: approved by the submitter"
        await self._fsm(dfsm.APPROVAL_POINT_FSM, row, "approved" if decision == "approved" else "rejected", decider)
        row.decided_by, row.decided_at = decider, _now()
        await self.session.flush()
        if row.status == "approved":
            self._publish(
                "design_management.approval_point.approved", project_id=row.project_id, approval_point_id=row.id
            )
        else:
            self._publish(
                "design_management.approval_point.rejected", project_id=row.project_id, approval_point_id=row.id
            )
        return True

    async def catch_up_approvals(self, project_id: uuid.UUID) -> int:
        """Apply route verdicts whose event never arrived; called by the list routes.

        The subscriber runs after the route's commit in a session of its own and
        only on PostgreSQL. If it failed, or never ran, the point or release
        would wait for ever; here the route's own instance is read instead.
        """
        from app.modules.approval_routes.models import Instance, StepState

        waiting: list[tuple[str, Any]] = [
            ("point", r)
            for r in await self._list(DesignApprovalPoint, project_id)
            if r.status == "in_review" and r.approval_instance_id is not None
        ]
        waiting += [
            ("release", r)
            for r in await self._list(DesignRelease, project_id)
            if r.status == "ready" and r.approval_status == "pending" and r.approval_instance_id is not None
        ]
        applied = 0
        for kind, row in waiting:
            instance = await self.session.get(Instance, row.approval_instance_id)
            if instance is not None and instance.status == "pending":
                continue
            decision = (
                instance.status
                if instance is not None and instance.status in ("approved", "rejected")
                else ("cancelled")
            )
            decider = None
            if decision != "cancelled":
                decider = (
                    await self.session.execute(
                        select(StepState.approver_user_id)
                        .where(StepState.instance_id == instance.id, StepState.decided_at.is_not(None))
                        .order_by(StepState.decided_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            apply = self.apply_approval_verdict if kind == "point" else self.apply_release_verdict
            applied += bool(await apply(row.id, row.approval_instance_id, decision=decision, decided_by=decider))
        return applied

    # ── deliverables (rule 15) ────────────────────────────────────────────

    async def create_deliverable(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        await self._require_phase(project_id, data.get("phase_code"))
        await self._check_phase(project_id, data.get("phase_code"))
        if data.get("role_id"):
            await self._get(DesignRole, project_id, data["role_id"], "role_not_found")
        code = data.get("code") or await self._next_code(DesignDeliverable, project_id, "DL")
        await self._unique_code(DesignDeliverable, project_id, code)
        row = await self._add(
            DesignDeliverable(
                project_id=project_id,
                code=code,
                title=data.get("title") or "",
                phase_code=data.get("phase_code") or None,
                role_id=_uuid(data.get("role_id")),
                discipline_code=data.get("discipline_code"),
                form_code=data.get("form_code"),
                wbs_node_id=await self.assert_wbs_usable(project_id, data.get("wbs_node_id")),
                planned_count=int(data.get("planned_count") or 1),
                schedule_activity_id=_uuid(data.get("schedule_activity_id")),
                required=bool(data.get("required", True)),
                required_for=_uuids(data.get("required_for")),
                target_suitability=data.get("target_suitability"),
                status="not_started",
            )
        )
        await self._audit(actor_id, "design_deliverable", row.id, "created", code=code)
        return row

    async def patch_deliverable(self, project_id: uuid.UUID, did: Any, data: dict[str, Any], *, actor_id):
        row = await self._get(DesignDeliverable, project_id, did, "deliverable_not_found", lock=True)
        if "planned_count" in data and int(data["planned_count"]) < row.planned_count:
            # Rule 15: a reduced count needs a reason, so "accepted" cannot be reached by shrinking the plan.
            if dr.rationale_error(data.get("planned_count_rationale")):
                raise DesignError("planned_count_reduction_needs_rationale", 422)
            row.planned_count_rationale = data["planned_count_rationale"]
        if "waived" in data:
            if data["waived"] and dr.rationale_error(data.get("waived_rationale")):
                raise DesignError("waiver_needs_rationale", 422)
            row.waived = bool(data["waived"])
            row.waived_rationale = data.get("waived_rationale") or ""
        if "phase_code" in data:
            data["phase_code"] = data["phase_code"] or None
            await self._require_phase(project_id, data["phase_code"])
            await self._check_phase(project_id, data["phase_code"])
        if "wbs_node_id" in data:
            row.wbs_node_id = await self.assert_wbs_usable(project_id, data["wbs_node_id"])
        if data.get("role_id"):
            await self._get(DesignRole, project_id, data["role_id"], "role_not_found")
        for key in ("title", "phase_code", "discipline_code", "form_code", "planned_count", "required"):
            if key in data:
                setattr(row, key, data[key])
        for key in ("role_id", "schedule_activity_id"):
            if key in data:
                setattr(row, key, _uuid(data[key]))
        if "target_suitability" in data:
            row.target_suitability = data["target_suitability"]
        if "required_for" in data:
            row.required_for = _uuids(data["required_for"])
        await self.refresh_deliverable(row)
        await self._audit(actor_id, "design_deliverable", row.id, "updated")
        return row

    async def refresh_deliverable(self, row: DesignDeliverable) -> str:
        """Recompute the state from the linked drawings' CDE states and cache it."""
        from app.modules.cde.models import DocumentContainer

        setup = await self.get_setup(row.project_id)
        stmt = (
            select(DocumentContainer)
            .join(DesignDrawing, DesignDrawing.container_id == DocumentContainer.id)
            .where(DesignDrawing.deliverable_id == row.id, DesignDrawing.project_id == row.project_id)
        )
        containers = list((await self.session.execute(stmt)).scalars().all())
        target = row.target_suitability or ((setup.target_suitability or {}).get(row.phase_code) if setup else None)
        state = dr.deliverable_state(
            [
                dr.DrawingState(c.id, c.cde_state, c.suitability_code, c.current_revision_id is not None)
                for c in containers
            ],
            planned_count=row.planned_count,
            target_suitability=target,
            waived=row.waived,
        )
        row.status = state
        await self.session.flush()
        return state

    async def deliverables(self, project_id: uuid.UUID, *, refresh: bool = True) -> list[DesignDeliverable]:
        rows = await self._list(DesignDeliverable, project_id, DesignDeliverable.phase_code, DesignDeliverable.code)
        if refresh:
            for row in rows:
                await self.refresh_deliverable(row)
        return rows

    async def delete_deliverable(self, project_id: uuid.UUID, did: Any, *, actor_id: uuid.UUID) -> None:
        row = await self._get(DesignDeliverable, project_id, did, "deliverable_not_found")
        for d in (
            await self.session.execute(select(DesignDrawing).where(DesignDrawing.deliverable_id == row.id))
        ).scalars():
            d.deliverable_id = None
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "design_deliverable", row.id, "deleted")

    # ── numbering (rules 5-8, 10) ─────────────────────────────────────────

    async def _field_values(
        self, project_id: uuid.UUID, scheme: DrawingNumbering, given: dict[str, Any], role: DesignRole | None
    ) -> dict[str, str]:
        """Fill each field from what the user typed, else its ``source_field``."""
        project = await self._project(project_id)
        wbs_code = None
        if given.get("wbs_node_id"):
            wbs_code = (await self._wbs_get(project_id, given["wbs_node_id"])).code
        source = {
            "project.code": getattr(project, "project_code", None),
            "role.originator_code": role.originator_code if role else None,
            "role.discipline_code": role.discipline_code if role else None,
            "drawing.phase_code": given.get("phase_code"),
            "drawing.sheet_size": given.get("sheet_size"),
            "wbs.code": wbs_code,
        }
        typed = given.get("fields") or {}
        out: dict[str, str] = {}
        for f in scheme.fields:
            if f.code == "number":
                continue
            value = typed.get(f.code) or source.get(f.source_field) or ""
            out[f.code] = nb.normalise(scheme, str(value))
        return out

    async def _counter_peek(self, project_id: uuid.UUID, key: str) -> int:
        stmt = select(DesignNumberCounter.next_value).where(
            DesignNumberCounter.project_id == project_id, DesignNumberCounter.scope_key == key
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() or 1

    async def _counter_row(self, project_id: uuid.UUID, key: str) -> DesignNumberCounter:
        """The counter row under a row lock, created race-free on first use (insert-on-conflict, then lock)."""
        bind = self.session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", "")
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            await self.session.execute(
                pg_insert(DesignNumberCounter)
                .values(id=uuid.uuid4(), project_id=project_id, scope_key=key, next_value=1)
                .on_conflict_do_nothing(constraint="uq_oe_dsg_counter_scope")
            )
        stmt = (
            select(DesignNumberCounter)
            .where(DesignNumberCounter.project_id == project_id, DesignNumberCounter.scope_key == key)
            .with_for_update()
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = await self._add(DesignNumberCounter(project_id=project_id, scope_key=key, next_value=1))
        return row

    async def _role_for(self, project_id: uuid.UUID, role_id: Any) -> DesignRole | None:
        return await self._get(DesignRole, project_id, role_id, "role_not_found") if role_id else None

    async def preview_number(self, project_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
        """The number that WOULD be allocated now; allocates nothing."""
        setup = await self.require_setup(project_id)
        scheme = await self.scheme(setup)
        values = await self._field_values(
            project_id, scheme, data, await self._role_for(project_id, data.get("role_id"))
        )
        missing = nb.missing_values(scheme, values)
        key = nb.scope_key(scheme, values)
        code = nb.compose(scheme, values, await self._counter_peek(project_id, key))
        return {"number": code, "fields": values, "missing": missing, "validation": nb.validate(scheme, code).as_dict()}

    async def allocate_number(self, project_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
        """Rule 5: allocate under a row lock; concurrent calls never return the same number."""
        setup = await self.require_setup(project_id)
        scheme = await self.scheme(setup)
        role = await self._role_for(project_id, data.get("role_id"))
        values = await self._field_values(project_id, scheme, data, role)
        missing = nb.missing_values(scheme, values)
        if missing:
            raise DesignError(
                "numbering_field_missing",
                422,
                violations=[{"code": "numbering_field_missing", "field": m, "value": None} for m in missing],
            )
        counter = await self._counter_row(project_id, nb.scope_key(scheme, values))
        taken = await self._taken_numbers(project_id)
        # A code can exist without the counter knowing: a container made in CDE before the
        # setup was pinned, or a number of the previous scheme that the new one also composes.
        # Skipping it here is what keeps the generator from proposing the same code forever.
        while True:
            code = nb.compose(scheme, values, counter.next_value)
            result = nb.validate(scheme, code)
            if not result.valid:
                raise DesignError("numbering_invalid", 422, violations=[i.as_dict() for i in result.issues])
            counter.next_value += 1
            if code not in taken:
                break
        await self.session.flush()
        return {"number": code, "fields": values, "parts": result.parts, "scheme_id": scheme.id}

    async def _taken_numbers(self, project_id: uuid.UUID) -> set[str]:
        """Every code that may not be handed out: live container codes, reservations and aliases."""
        from app.modules.cde.models import DocumentContainer

        live = (
            await self.session.execute(
                select(DocumentContainer.container_code).where(DocumentContainer.project_id == project_id)
            )
        ).scalars()
        reserved = (
            await self.session.execute(
                select(DesignNumberReservation.number).where(DesignNumberReservation.project_id == project_id)
            )
        ).scalars()
        return {*live, *reserved, *self._all_aliases(await self._drawings_flat(project_id))}

    async def validate_number(self, project_id: uuid.UUID, code: str) -> dict[str, Any]:
        setup = await self.require_setup(project_id)
        return nb.validate(await self.scheme(setup), code).as_dict()

    async def bulk_validate(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every register drawing against the pinned scheme (rules 6, 7, 21)."""
        setup = await self.require_setup(project_id)
        scheme = await self.scheme(setup)
        originators = await self._active_originators(project_id)
        out = []
        for drawing, c in await self._drawings_with_containers(project_id):
            result = nb.validate(scheme, c.container_code)
            mismatch = nb.parts_mismatch(scheme, c.container_code, self._stored_parts(c)) if result.valid else []
            issues = [i.as_dict() for i in result.issues]
            issues += [{"code": "numbering_parts_mismatch", "field": f, "value": None} for f in mismatch]
            if c.originator_code and c.originator_code.upper() not in originators:
                issues.append({"code": "originator_unknown", "field": "originator", "value": c.originator_code})
            out.append(
                {
                    "drawing_id": str(drawing.id),
                    "container_id": str(c.id),
                    "number": c.container_code,
                    "valid": not issues,
                    "legacy_scheme": drawing.legacy_scheme,
                    "issues": issues,
                }
            )
        return out

    @staticmethod
    def _stored_parts(c: Any) -> dict[str, str | None]:
        return {
            "originator_code": c.originator_code,
            "functional_breakdown": c.functional_breakdown,
            "spatial_breakdown": c.spatial_breakdown,
            "form_code": c.form_code,
            "discipline_code": c.discipline_code,
            "sequence_number": c.sequence_number,
        }

    async def _active_originators(self, project_id: uuid.UUID) -> set[str]:
        """Rule 21: the originator codes of roles that are appointed or active. Planned roles do not count."""
        roles = [r for r in await self.roles(project_id) if r.status in ("appointed", "active")]
        return {r.originator_code.upper() for r in roles if r.originator_code}

    async def check_container_code(
        self, project_id: uuid.UUID, code: str, parts: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """The CDE hook: with a pinned scheme, the code must match it, agree with its parts and pass the counter."""
        setup = await self.get_setup(project_id)
        if setup is None:
            return []
        if await self._is_frame_container(project_id, code):
            return []
        if await self._reserved_elsewhere(project_id, code):
            return [{"code": "number_reserved", "field": None, "value": code}]
        scheme = await self.scheme(setup)
        result = nb.validate(scheme, code)
        if not result.valid:
            return [i.as_dict() for i in result.issues]
        stored = {k: parts.get(k) for k in _PART_COLUMNS}
        if any(stored.values()):
            mismatch = nb.parts_mismatch(scheme, code, stored)
            if mismatch:
                return [{"code": "numbering_parts_mismatch", "field": f, "value": None} for f in mismatch]
        # Rule 8: a typed number moves the counter past it, so the generator never hands it out again.
        seq = nb.sequence_of(scheme, code)
        if seq is not None and result.parts:
            counter = await self._counter_row(project_id, nb.scope_key(scheme, nb.scope_values(result.parts)))
            if counter.next_value <= seq:
                counter.next_value = seq + 1
                await self.session.flush()
        # Rule 8: every accepted number is reserved here, whichever door it came through
        # (the register, a CDE create, a CDE rename), so deleting its container never frees it.
        await self._reserve(project_id, code)
        return []

    async def _is_frame_container(self, project_id: uuid.UUID, code: str) -> bool:
        """An existing container this module created for a frame document; its code is not a drawing number.

        The marker is written under ``cde_naming.server_write`` only, and CDE drops it
        from request metadata, so a client cannot put it on a container of its own.
        """
        from app.modules.cde.models import DocumentContainer

        stmt = select(DocumentContainer.metadata_).where(
            DocumentContainer.project_id == project_id, DocumentContainer.container_code == code
        )
        meta = (await self.session.execute(stmt)).scalars().first()
        return isinstance(meta, dict) and FRAME_MARKER in meta

    async def renumber_preview_drawings(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Rule 9: proposed new numbers for every legacy drawing; nothing is applied."""
        setup = await self.require_setup(project_id)
        scheme = await self.scheme(setup)
        peeks: dict[str, int] = {}
        out = []
        for drawing, c in await self._drawings_with_containers(project_id):
            if not drawing.legacy_scheme:
                continue
            role = await self.session.get(DesignRole, drawing.role_id) if drawing.role_id else None
            values = await self._field_values(
                project_id,
                scheme,
                {
                    "fields": {
                        "originator": c.originator_code,
                        "functional": c.functional_breakdown,
                        "spatial": c.spatial_breakdown,
                        "form": c.form_code,
                        "discipline": c.discipline_code,
                    },
                    "phase_code": drawing.phase_code,
                    "sheet_size": drawing.sheet_size,
                    "wbs_node_id": drawing.wbs_node_id,
                },
                role,
            )
            key = nb.scope_key(scheme, values)
            peeks.setdefault(key, await self._counter_peek(project_id, key))
            proposed = nb.compose(scheme, values, peeks[key])
            peeks[key] += 1
            out.append(
                {
                    "drawing_id": str(drawing.id),
                    "old": c.container_code,
                    "new": proposed,
                    "missing": nb.missing_values(scheme, values),
                }
            )
        return out

    async def renumber_apply(
        self, project_id: uuid.UUID, mapping: dict[str, str], *, actor_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Rule 9: apply a confirmed mapping ``{drawing_id: new number}``; old numbers become aliases."""
        from app.modules.cde.models import DocumentContainer

        await self.assert_not_binding(project_id)
        setup = await self.require_setup(project_id)
        scheme = await self.scheme(setup)
        out = []
        for did, new_code in mapping.items():
            drawing = await self._get(DesignDrawing, project_id, did, "drawing_not_found", lock=True)
            c = await self.session.get(DocumentContainer, drawing.container_id)
            if new_code == c.container_code:
                continue  # unchanged: no alias, no second reservation
            result = nb.validate(scheme, new_code)
            if not result.valid:
                raise DesignError("numbering_invalid", 422, violations=[i.as_dict() for i in result.issues])
            clash = (
                await self.session.execute(
                    select(DocumentContainer.id).where(
                        DocumentContainer.project_id == project_id,
                        DocumentContainer.container_code == new_code,
                        DocumentContainer.id != c.id,
                    )
                )
            ).first()
            if (
                clash is not None
                or new_code in self._all_aliases(await self._drawings_flat(project_id))
                or await self._reserved_elsewhere(project_id, new_code)
            ):
                raise conflict("number_taken", detail=new_code)
            refused = await self.check_container_code(project_id, new_code, {})
            if refused:
                raise DesignError("numbering_invalid", 422, violations=refused)
            columns, extra = nb.container_parts(scheme, result.parts or {})
            drawing.aliases = [*(drawing.aliases or []), c.container_code]
            c.container_code = new_code
            for col, value in columns.items():
                if scheme.field(next(k for k, v in nb.CONTAINER_PART.items() if v == col)) is not None:
                    setattr(c, col, value)
            c.metadata_ = {**(c.metadata_ or {}), "numbering": {"scheme": scheme.id, "parts": extra}}
            drawing.legacy_scheme = False
            drawing.scheme_id, drawing.scheme_version = scheme.id, scheme.version
            out.append({"drawing_id": str(drawing.id), "old": drawing.aliases[-1], "new": new_code})
        await self.session.flush()
        await self._audit(actor_id, "design_setup", setup.id, "renumbered", count=len(out))
        return out

    async def _reserved_elsewhere(self, project_id: uuid.UUID, code: str) -> bool:
        """Rule 8: the number was used once and no live container holds it now (its owner was deleted)."""
        from app.modules.cde.models import DocumentContainer

        reserved = (
            await self.session.execute(
                select(DesignNumberReservation.id).where(
                    DesignNumberReservation.project_id == project_id, DesignNumberReservation.number == code
                )
            )
        ).first()
        if reserved is None:
            return False
        live = (
            await self.session.execute(
                select(DocumentContainer.id).where(
                    DocumentContainer.project_id == project_id, DocumentContainer.container_code == code
                )
            )
        ).first()
        return live is None

    async def _reserve(self, project_id: uuid.UUID, code: str, *, reason: str = "issued") -> None:
        """Record a number as used, once; insert-on-conflict so a racing or repeated reserve is a no-op."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        values = {"id": uuid.uuid4(), "project_id": project_id, "number": code, "reason": reason}
        if getattr(getattr(self.session.get_bind(), "dialect", None), "name", "") == "postgresql":
            await self.session.execute(
                pg_insert(DesignNumberReservation)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_oe_dsg_reservation_number")
            )
            return
        known = select(DesignNumberReservation.id).where(
            DesignNumberReservation.project_id == project_id, DesignNumberReservation.number == code
        )
        if (await self.session.execute(known)).first() is None:
            await self._add(DesignNumberReservation(**values))

    @staticmethod
    def _all_aliases(drawings: list[DesignDrawing]) -> set[str]:
        return {a for d in drawings for a in (d.aliases or [])}

    async def _drawings_flat(self, project_id: uuid.UUID) -> list[DesignDrawing]:
        return await self._list(DesignDrawing, project_id)

    # ── drawings: the register (rule 11) ──────────────────────────────────

    async def _drawings_with_containers(self, project_id: uuid.UUID) -> list[tuple[DesignDrawing, Any]]:
        from app.modules.cde.models import DocumentContainer

        stmt = (
            select(DesignDrawing, DocumentContainer)
            .join(DocumentContainer, DocumentContainer.id == DesignDrawing.container_id)
            .where(DesignDrawing.project_id == project_id)
            .order_by(DocumentContainer.container_code)
        )
        return [(d, c) for d, c in (await self.session.execute(stmt)).all()]

    async def register(self, project_id: uuid.UUID, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """The drawing register: number, title, revision and status from CDE, plus our attributes."""
        from app.modules.cde.models import DocumentRevision

        f = filters or {}
        rows = await self._drawings_with_containers(project_id)
        rev_ids = [c.current_revision_id for _d, c in rows if c.current_revision_id]
        revisions = {}
        if rev_ids:
            for rev in (
                await self.session.execute(select(DocumentRevision).where(DocumentRevision.id.in_(rev_ids)))
            ).scalars():
                revisions[str(rev.id)] = rev
        issues = await self._last_issues(project_id)
        out = []
        q = (f.get("q") or "").strip().casefold()
        for d, c in rows:
            if f.get("phase_code") and d.phase_code != f["phase_code"]:
                continue
            if f.get("discipline_code") and c.discipline_code != f["discipline_code"]:
                continue
            if f.get("deliverable_id") and str(d.deliverable_id) != str(f["deliverable_id"]):
                continue
            if f.get("state") and c.cde_state != f["state"]:
                continue
            if q and q not in c.container_code.casefold() and q not in (d.title or "").casefold():
                if not any(q in a.casefold() for a in d.aliases or []):
                    continue
            rev = revisions.get(str(c.current_revision_id)) if c.current_revision_id else None
            mismatch = bool(d.title_block_number) and d.title_block_number.strip() != c.container_code
            last = issues.get(str(c.current_revision_id)) if c.current_revision_id else None
            out.append(
                {
                    "drawing": d,
                    "container": c,
                    "revision_code": rev.revision_code if rev else None,
                    "title_block_mismatch": mismatch,
                    "last_issue": last,
                }
            )
        return out

    async def _last_issues(self, project_id: uuid.UUID) -> dict[str, dict[str, Any]]:
        """``{revision_id: {"at", "recipients": [...]}}`` from issued releases."""
        out: dict[str, dict[str, Any]] = {}
        for rel in await self._list(DesignRelease, project_id, DesignRelease.issued_at):
            if rel.status != "issued":
                continue
            for entry in rel.issue_plan or []:
                for rid in entry.get("revision_ids", []):
                    slot = out.setdefault(rid, {"at": None, "recipients": []})
                    slot["at"] = rel.issued_at.isoformat() if rel.issued_at else None
                    if entry.get("recipient_key") not in slot["recipients"]:
                        slot["recipients"].append(entry.get("recipient_key"))
        return out

    async def create_drawing(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        """Create the CDE container (number generated or typed) and its register row, in one transaction."""
        from app.modules.cde.schemas import ContainerCreate
        from app.modules.cde.service import CDEService

        setup = await self.require_setup(project_id)
        scheme = await self.scheme(setup)
        role = await self._role_for(project_id, data.get("role_id"))
        if role is not None and role.status == "released":
            raise DesignError("role_not_active", 422)
        await self._check_phase(project_id, data.get("phase_code"))
        wbs_node_id = await self.assert_wbs_usable(project_id, data.get("wbs_node_id"))
        if data.get("deliverable_id"):
            await self._get(DesignDeliverable, project_id, data["deliverable_id"], "deliverable_not_found")
        typed = (data.get("number") or "").strip()
        if typed:
            result = nb.validate(scheme, typed)
            if not result.valid:
                raise DesignError("numbering_invalid", 422, violations=[i.as_dict() for i in result.issues])
            code, parts = typed, result.parts or {}
        else:
            allocated = await self.allocate_number(project_id, data)
            code, parts = allocated["number"], allocated["parts"] or {}
        if code in self._all_aliases(await self._drawings_flat(project_id)) or await self._reserved_elsewhere(
            project_id, code
        ):
            raise conflict("number_taken", detail=code)
        originators = await self._active_originators(project_id)
        if parts.get("originator") and parts["originator"].upper() not in originators:
            raise DesignError("originator_unknown", 422, detail=parts["originator"])
        columns, extra = nb.container_parts(scheme, parts)
        container = await CDEService(self.session).create_container(
            ContainerCreate(
                project_id=project_id,
                container_code=code,
                title=data.get("title") or code,
                cde_state="wip",
                metadata={"numbering": {"scheme": scheme.id, "parts": extra}},
                **{k: v for k, v in columns.items() if v},
            ),
            user_id=_s(actor_id),
        )
        drawing = await self._add(
            DesignDrawing(
                project_id=project_id,
                container_id=container.id,
                title=data.get("title") or "",
                scale=data.get("scale") or "",
                sheet_size=data.get("sheet_size") or "",
                phase_code=data.get("phase_code"),
                deliverable_id=_uuid(data.get("deliverable_id")),
                wbs_node_id=wbs_node_id,
                role_id=role.id if role else None,
                planned_first_issue=data.get("planned_first_issue"),
                forecast_issue=data.get("forecast_issue"),
                schedule_activity_id=_uuid(data.get("schedule_activity_id")),
                scheme_id=scheme.id,
                scheme_version=scheme.version,
                aliases=[],
            )
        )
        await self._audit(actor_id, "design_drawing", drawing.id, "created", number=code)
        self._publish("design_management.drawing.created", project_id=project_id, drawing_id=drawing.id, number=code)
        return drawing, container

    async def patch_drawing(self, project_id: uuid.UUID, did: Any, data: dict[str, Any], *, actor_id: uuid.UUID):
        row = await self._get(DesignDrawing, project_id, did, "drawing_not_found", lock=True)
        if "phase_code" in data:
            await self._check_phase(project_id, data["phase_code"])
        if "wbs_node_id" in data:
            row.wbs_node_id = await self.assert_wbs_usable(project_id, data["wbs_node_id"])
        if data.get("deliverable_id"):
            await self._get(DesignDeliverable, project_id, data["deliverable_id"], "deliverable_not_found")
        if data.get("role_id"):
            await self._get(DesignRole, project_id, data["role_id"], "role_not_found")
        for key in ("title", "scale", "sheet_size", "phase_code", "planned_first_issue", "forecast_issue"):
            if key in data:
                setattr(row, key, data[key] or ("" if key in ("title", "scale", "sheet_size") else None))
        for key in ("deliverable_id", "role_id", "schedule_activity_id"):
            if key in data:
                setattr(row, key, _uuid(data[key]))
        if "title_block_number" in data:
            row.title_block_number = data["title_block_number"] or None
        await self.session.flush()
        await self._audit(actor_id, "design_drawing", row.id, "updated")
        return row

    async def supersede_drawing(self, project_id: uuid.UUID, did: Any, by_container_id: Any, *, actor_id):
        from app.modules.cde.models import DocumentContainer

        row = await self._get(DesignDrawing, project_id, did, "drawing_not_found", lock=True)
        target = await self.session.get(DocumentContainer, _uuid(by_container_id))
        if target is None or target.project_id != project_id or target.id == row.container_id:
            raise not_found("container_not_found")
        row.superseded_by_container_id = target.id
        await self.session.flush()
        await self._audit(actor_id, "design_drawing", row.id, "superseded", by=target.id)
        return row

    async def read_title_block(self, project_id: uuid.UUID, did: Any, sheet_text: str, *, actor_id: uuid.UUID):
        """Rule 11: read the sheet number from title block text and compare it with the container code.

        Nothing is stored when the reader finds no number: raw text kept as a
        "number" would report a mismatch on every real title block.
        """
        from app.modules.documents.sheet_fields import detect_sheet_info

        row = await self._get(DesignDrawing, project_id, did, "drawing_not_found", lock=True)
        number = (detect_sheet_info(sheet_text, title_block_text=sheet_text).get("sheet_number") or "").strip()
        row.title_block_number = number[:255] or None
        await self.session.flush()
        return row

    # ── distribution and releases (rules 12-14) ───────────────────────────

    async def create_dist_rule(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        await self.assert_not_binding(project_id)
        await self._check_recipient(project_id, data, actor_id=actor_id)
        row = DesignDistributionRule(project_id=project_id)
        self._fill_rule(row, data)
        await self._add(row)
        await self._audit(actor_id, "design_dist_rule", row.id, "created")
        return row

    async def _check_recipient(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID) -> None:
        """A list of this project, or the actor's own personal list; never another user's (rule 24)."""
        from app.modules.file_distribution.models import FileDistributionList

        list_id, role_id = _uuid(data.get("recipient_list_id")), _uuid(data.get("recipient_role_id"))
        if bool(list_id) == bool(role_id):
            raise DesignError("recipient_exactly_one", 422)
        if list_id:
            lst = await self.session.get(FileDistributionList, list_id)
            own_personal = lst is not None and lst.project_id is None and lst.owner_id == actor_id
            if lst is None or not (lst.project_id == project_id or own_personal):
                raise not_found("distribution_list_not_found")
        else:
            await self._get(DesignRole, project_id, role_id, "role_not_found")

    @staticmethod
    def _fill_rule(row: DesignDistributionRule, data: dict[str, Any]) -> None:
        for key in ("recipient_list_id", "recipient_role_id"):
            if key in data:
                setattr(row, key, _uuid(data[key]))
        for key in ("discipline_codes", "form_codes", "phase_codes"):
            if key in data:
                setattr(row, key, list(data[key] or []))
        if "wbs_node_ids" in data:
            row.wbs_node_ids = _uuids(data["wbs_node_ids"])
        if "purpose" in data:
            row.purpose = data["purpose"] or ""  # null = the rule applies to releases of any purpose
        for key in ("min_suitability", "format", "copies_paper", "ack_required", "active"):
            if key in data:
                setattr(row, key, data[key])

    async def patch_dist_rule(self, project_id: uuid.UUID, rid: Any, data: dict[str, Any], *, actor_id: uuid.UUID):
        await self.assert_not_binding(project_id)
        row = await self._get(DesignDistributionRule, project_id, rid, "dist_rule_not_found", lock=True)
        merged = {
            "recipient_list_id": data.get("recipient_list_id", row.recipient_list_id),
            "recipient_role_id": data.get("recipient_role_id", row.recipient_role_id),
        }
        await self._check_recipient(project_id, merged, actor_id=actor_id)
        self._fill_rule(row, data)
        await self.session.flush()
        return row

    async def delete_dist_rule(self, project_id: uuid.UUID, rid: Any, *, actor_id: uuid.UUID) -> None:
        row = await self._get(DesignDistributionRule, project_id, rid, "dist_rule_not_found")
        await self.session.delete(row)
        await self.session.flush()

    @staticmethod
    def _recipient_key(rule: DesignDistributionRule) -> str:
        return f"list:{rule.recipient_list_id}" if rule.recipient_list_id else f"role:{rule.recipient_role_id}"

    async def _revision_views(self, project_id: uuid.UUID, revision_ids: list[Any]) -> list[dr.RevisionView]:
        """Current revisions of THIS project's containers; a foreign id is 404 (rule 24).

        Suitability lives on the container and describes its CURRENT revision,
        so a release can only carry that one: a superseded revision has no
        status of its own to check rule 13 against (``revision_not_current``).
        """
        from app.modules.cde.models import DocumentContainer, DocumentRevision

        ids = [_uuid(r) for r in revision_ids]
        if not ids:
            return []
        stmt = (
            select(DocumentRevision, DocumentContainer)
            .join(DocumentContainer, DocumentContainer.id == DocumentRevision.container_id)
            .where(DocumentRevision.id.in_(ids), DocumentContainer.project_id == project_id)
        )
        rows = (await self.session.execute(stmt)).all()
        if len(rows) != len(set(ids)):
            raise not_found("revision_not_found")
        stale = [rev.id for rev, c in rows if _uuid(c.current_revision_id) != rev.id]
        if stale:
            raise DesignError(
                "revision_not_current",
                422,
                violations=[_violation("revision_not_current", "revision", r, "", revision_id=str(r)) for r in stale],
            )
        drawings = {
            d.container_id: d
            for d in (
                await self.session.execute(
                    select(DesignDrawing).where(DesignDrawing.container_id.in_([c.id for _r, c in rows]))
                )
            ).scalars()
        }
        out = []
        for rev, c in rows:
            d = drawings.get(c.id)
            out.append(
                dr.RevisionView(
                    rev.id,
                    c.id,
                    c.suitability_code,
                    c.discipline_code,
                    c.form_code,
                    d.phase_code if d else None,
                    d.wbs_node_id if d else None,
                )
            )
        order = {rid: i for i, rid in enumerate(ids)}
        return sorted(out, key=lambda v: order[v.revision_id])

    async def _issued_pairs(self, project_id: uuid.UUID, exclude: uuid.UUID | None = None) -> set[tuple[str, Any]]:
        out: set[tuple[str, Any]] = set()
        for rel in await self._list(DesignRelease, project_id):
            if rel.status != "issued" or rel.id == exclude:
                continue
            for entry in rel.issue_plan or []:
                for rid in entry.get("revision_ids", []):
                    out.add((entry.get("recipient_key"), uuid.UUID(rid)))
        return out

    async def release_plan(self, project_id: uuid.UUID, release: DesignRelease) -> list[dr.RecipientPlan]:
        rules = [r for r in await self._list(DesignDistributionRule, project_id) if r.active]
        matrix = [
            dr.MatrixRule(
                r.id,
                self._recipient_key(r),
                tuple(r.discipline_codes or ()),
                tuple(r.form_codes or ()),
                tuple(r.phase_codes or ()),
                tuple(uuid.UUID(x) for x in r.wbs_node_ids or ()),
                r.min_suitability,
                r.purpose or "",
            )
            for r in rules
        ]
        views = await self._revision_views(project_id, release.revision_ids or [])
        return dr.distribution_plan(
            matrix, views, purpose=release.purpose, already_issued=await self._issued_pairs(project_id, release.id)
        )

    async def create_release(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        setup = await self.get_setup(project_id)
        purpose = data.get("purpose") or (setup.default_distribution_purpose if setup else "for_information")
        views = await self._revision_views(project_id, data.get("revision_ids") or [])
        code = data.get("code") or await self._next_code(DesignRelease, project_id, "REL")
        await self._unique_code(DesignRelease, project_id, code)
        row = await self._add(
            DesignRelease(
                project_id=project_id,
                code=code,
                title=data.get("title") or code,
                purpose=purpose,
                revision_ids=[str(v.revision_id) for v in views],
                status="draft",
                transmittal_ids=[],
                issue_plan=[],
                prepared_by=actor_id,
                content_changed_by=actor_id,
                approval_status="none",
            )
        )
        await self._audit(actor_id, "design_release", row.id, "created", code=code)
        return row

    async def patch_release(self, project_id: uuid.UUID, rid: Any, data: dict[str, Any], *, actor_id: uuid.UUID):
        row = await self._get(DesignRelease, project_id, rid, "release_not_found", lock=True)
        if row.status != "draft":
            raise conflict("release_not_draft")
        if "revision_ids" in data:
            row.revision_ids = [
                str(v.revision_id) for v in await self._revision_views(project_id, data["revision_ids"])
            ]
        for key in ("title", "purpose"):
            if key in data:
                setattr(row, key, data[key])
        if {"revision_ids", "purpose"} & data.keys():
            # Decision 14: whoever last changed what goes out cannot be the one who approves it.
            row.content_changed_by = actor_id
        await self.session.flush()
        await self._audit(actor_id, "design_release", row.id, "updated", fields=sorted(data))
        return row

    async def release_transition(self, project_id: uuid.UUID, rid: Any, target: str, *, actor_id: uuid.UUID):
        """``ready`` starts the ``design_release`` approval route when four-eyes is on (decision 14)."""
        row = await self._get(DesignRelease, project_id, rid, "release_not_found", lock=True)
        refused = await self.release_transition_refusal(row, target)
        if refused is not None:
            raise refused
        setup = await self.get_setup(project_id)
        route = None
        if target == "ready" and setup is not None and setup.four_eyes_release:
            route = await self._pinned_route(project_id, RELEASE_TARGET_KIND)
        await self._fsm(dfsm.RELEASE_FSM, row, target, actor_id)
        if target == "ready":
            row.content_changed_by = actor_id
            row.approved_by = row.approved_at = None
            row.approval_status = "none"
            if route is not None:
                row.approval_instance_id = await self._start_instance(route, RELEASE_TARGET_KIND, row.id, actor_id)
                row.approval_status = "pending"
        else:
            # Reopened or cancelled: an approval given for the old content does not carry over.
            await self._drop_release_instance(row, actor_id)
        await self.session.flush()
        return row

    async def release_transition_refusal(self, row: DesignRelease, target: str) -> DesignError | None:
        """Why a release cannot move to ``target`` now, or ``None``."""
        if target == "issued":
            return conflict("use_issue")
        refused = _edge(dfsm.RELEASE_FSM, row, target)
        if refused is not None:
            return refused
        if target == "ready":
            try:
                await self._check_release_content(row.project_id, row)
            except DesignError as exc:
                return exc
            setup = await self.get_setup(row.project_id)
            four_eyes = setup is not None and setup.four_eyes_release
            if four_eyes and await self._pinned_route(row.project_id, RELEASE_TARGET_KIND) is None:
                return DesignError("no_approval_route", 422)
        return None

    async def _drop_release_instance(self, row: DesignRelease, actor_id: uuid.UUID | None) -> None:
        from fastapi import HTTPException

        from app.modules.approval_routes.service import ApprovalRouteService

        if row.approval_instance_id is not None and row.approval_status == "pending":
            try:
                await ApprovalRouteService(self.session).cancel_instance(row.approval_instance_id, actor_id=actor_id)
            except HTTPException:
                # Already terminal on the route side; the release still forgets it below.
                logger.warning("design: release %s could not cancel its approval instance", row.id, exc_info=True)
        row.approval_instance_id = None
        row.approved_by = row.approved_at = None
        row.approval_status = "none"

    async def apply_release_verdict(
        self, release_id: uuid.UUID, instance_id: uuid.UUID | None, *, decision: str, decided_by: Any
    ) -> bool:
        """The ``design_release`` route decided. Idempotent; four-eyes against whoever last changed the content."""
        stmt = select(DesignRelease).where(DesignRelease.id == release_id).with_for_update()
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None or row.status != "ready" or row.approval_status != "pending":
            return False
        if instance_id is not None and row.approval_instance_id != instance_id:
            return False
        decider = _uuid(decided_by)
        if decision == "cancelled":
            row.approval_instance_id = None
            row.approval_status = "none"
            await self._fsm(dfsm.RELEASE_FSM, row, "draft", decider, reason="approval route cancelled")
        elif decision == "approved" and self._approve_gate(row, decider) is None:
            row.approval_status, row.approved_by, row.approved_at = "approved", decider, _now()
        else:
            # Rejected, or approved by the person who last changed the content or marked it ready.
            self_approved = decision == "approved"
            row.approval_status = "rejected"
            row.approval_instance_id = None
            await self._fsm(
                dfsm.RELEASE_FSM,
                row,
                "draft",
                decider,
                reason="four_eyes: approver is the preparer or unknown" if self_approved else "approval route rejected",
            )
        await self.session.flush()
        await self._audit(decider, "design_release", row.id, f"approval_{row.approval_status}")
        self._publish(
            "design_management.release.approval",
            project_id=row.project_id,
            release_id=row.id,
            state=row.approval_status,
        )
        return True

    async def release_can(self, row: DesignRelease, *, actor_id: uuid.UUID, may_release: bool) -> dict[str, Any]:
        """What the caller may do with a release, decided by the function ``issue_release`` enforces with."""
        setup = await self.get_setup(row.project_id)
        refused = self._approve_gate(row, actor_id)
        live = row.status in ("draft", "ready")
        return {
            "issue": self._issue_gate(row, setup, actor_id=actor_id, may_release=may_release) | {"applies": live},
            # Entitlement comes from the approval route; this only says what this module would refuse.
            "approve": _flag(refused, applies=row.status == "ready" and row.approval_status == "pending"),
        }

    async def capabilities(self, row: Any, caller: Caller) -> dict[str, Any]:
        """What this caller may do with one row: ``{"transitions": {target: flag}, <action>: flag}``.

        Every flag is ``{allowed, applies, reason}`` and comes from the refusal
        function the write itself raises from, so a button and its request
        cannot disagree. ``transitions`` lists the moves the state machine has
        from the row's current state and that a person may type; states that are
        computed or read from elsewhere are not listed, or do not apply.
        """

        def edit(refused: DesignError | str | None = None, *, applies: bool = True) -> dict[str, Any]:
            return _flag(refused if caller.edit else "forbidden", applies=applies)

        if isinstance(row, DesignRole):
            key = ("binding", row.project_id)
            if key not in self._cap_memo:
                self._cap_memo[key] = await self.binding_refusal(row.project_id)
            bound = self._cap_memo[key]
            return {"transitions": {t: edit(bound) for t in dfsm.ROLE_FSM.allowed_from(row.status)}}
        if isinstance(row, DesignApprovalPoint):
            submits = row.status in ("open", "rejected")
            return {
                "transitions": {},
                "submit": edit(await self.approval_submit_refusal(row) if submits else None, applies=submits),
                "reopen": edit(applies=self.approval_reopen_refusal(row) is None),
            }
        if isinstance(row, DesignDeliverable):
            # The state is computed from the drawings; the one thing a person sets is the waiver.
            return {"transitions": {}, "waive": edit(applies=not row.waived), "unwaive": edit(applies=row.waived)}
        if isinstance(row, DesignRelease):
            moves = [t for t in dfsm.RELEASE_FSM.allowed_from(row.status) if t != "issued"]
            flags = await self.release_can(row, actor_id=caller.actor_id, may_release=caller.release)
            return {"transitions": {t: edit(await self.release_transition_refusal(row, t)) for t in moves}} | flags
        if isinstance(row, DesignReview):
            moves = [t for t in dfsm.REVIEW_FSM.allowed_from(row.status) if t != "concluded"]
            return {
                "transitions": {t: edit(await self.review_transition_refusal(row, t)) for t in moves},
                "conclude": edit(applies=_edge(dfsm.REVIEW_FSM, row, "concluded") is None),
            }
        if isinstance(row, DesignReviewComment):
            return {"transitions": {t: edit() for t in dfsm.COMMENT_FSM.allowed_from(row.status)}}
        if isinstance(row, DesignReport):
            moves = dfsm.REPORT_FSM.allowed_from(row.status)
            return {
                "transitions": {t: edit(await self.report_transition_refusal(row, t)) for t in moves}
            } | self.report_can(row, may_manage=caller.manage)
        if isinstance(row, DesignPermit):
            moves = dfsm.PERMIT_FSM.allowed_from(row.status)
            if row.status == "assembling":
                moves = [*moves, "submitted"]
            out = {}
            for t in moves:
                refused = await self.permit_transition_refusal(row, t, may_manage=caller.manage)
                # A state the linked review cycle decides is not a person's to type.
                read = refused is not None and refused.code == "permit_state_read_from_cycle"
                out[t] = edit(refused, applies=not read)
            return {"transitions": out}
        return {}

    @staticmethod
    def _approve_gate(row: DesignRelease, decider: uuid.UUID | None) -> str | None:
        """Why this person's approval of the release would not count, or ``None`` (decision 14)."""
        if row.status != "ready" or row.approval_status != "pending":
            return "release_not_pending"
        if decider is None or decider == row.content_changed_by:
            return "release_four_eyes"
        return None

    def report_can(self, row: DesignReport, *, may_manage: bool) -> dict[str, Any]:
        """Whether the caller may change the fields a gate reads on this report."""
        reason = None
        if not may_manage:
            reason = "manage_required"
        elif row.status in self.REPORT_FROZEN_STATES:
            reason = "report_fields_frozen"
        return {"edit_gate_fields": _flag(reason)}

    @staticmethod
    def _issue_gate(row: DesignRelease, setup: Any, *, actor_id: uuid.UUID, may_release: bool) -> dict[str, Any]:
        reason = None
        if not may_release:
            reason = "forbidden"
        elif row.status != "ready":
            reason = "release_not_ready"
        elif setup is not None and setup.four_eyes_release and row.approval_status != "approved":
            reason = "release_not_approved"
        return _flag(reason)

    async def _check_release_content(self, project_id: uuid.UUID, row: DesignRelease) -> None:
        if not row.revision_ids:
            raise DesignError("release_empty", 422)
        views = await self._revision_views(project_id, row.revision_ids)
        errors = dr.release_content_errors(views, row.purpose)
        if errors:
            raise DesignError(
                errors[0][1],
                422,
                violations=[_violation(c, "revision", r, "", revision_id=str(r)) for r, c in errors],
            )

    async def _recipient_label(self, project_id: uuid.UUID, key: str) -> str:
        """What a person calls a matrix recipient: the role's title or the list's name; empty when it is gone."""
        from app.modules.file_distribution.models import FileDistributionList

        kind, _, raw = key.partition(":")
        if kind == "list":
            lst = await self.session.get(FileDistributionList, uuid.UUID(raw))
            return lst.name if lst is not None else ""
        role = await self.session.get(DesignRole, uuid.UUID(raw))
        if role is None or role.project_id != project_id:
            return ""
        return role.title or role.code

    async def _recipients_for(self, project_id: uuid.UUID, key: str) -> list[dict[str, Any]]:
        """The people behind a matrix recipient; empty when the list has no member or the role is gone."""
        from app.modules.file_distribution.models import FileDistributionMember

        kind, _, raw = key.partition(":")
        rid = uuid.UUID(raw)
        if kind == "list":
            members = (
                await self.session.execute(select(FileDistributionMember).where(FileDistributionMember.list_id == rid))
            ).scalars()
            return [
                {"recipient_name": m.display_name or m.email, "recipient_email": m.email}
                for m in members
                if (m.email or "").strip() or (m.display_name or "").strip()
            ]
        role = await self.session.get(DesignRole, rid)
        if role is None or role.project_id != project_id:
            return []
        return [{"recipient_name": role.title or role.code, "recipient_user_id": role.user_id}]

    async def issue_release(
        self,
        project_id: uuid.UUID,
        rid: Any,
        *,
        actor_id: uuid.UUID,
        duplicate_reason: str = "",
        may_release: bool = True,
    ) -> DesignRelease:
        """Rule 12: one transmittal per matching recipient with the pinned revisions; rule 14 duplicates need a reason.

        Every transmittal goes out with the RELEASE's purpose (a matrix rule can
        only narrow who receives it), and rule 13 is checked against exactly the
        revisions and the purpose that are sent.
        """
        from app.modules.transmittals.models import Transmittal
        from app.modules.transmittals.schemas import ItemCreate, RecipientCreate, TransmittalCreate
        from app.modules.transmittals.service import TransmittalService

        row = await self._get(DesignRelease, project_id, rid, "release_not_found", lock=True)
        setup = await self.get_setup(project_id)
        gate = self._issue_gate(row, setup, actor_id=actor_id, may_release=may_release)
        if not gate["allowed"]:
            code = gate["reason"]
            if code == "forbidden":
                raise forbidden(code)
            raise conflict(code)
        await self._check_release_content(project_id, row)
        plans = await self.release_plan(project_id, row)
        if not any(p.revision_ids for p in plans):
            raise DesignError("release_no_recipients", 422)
        views = {v.revision_id: v for v in await self._revision_views(project_id, row.revision_ids)}
        names = {p.recipient_key: await self._recipient_label(project_id, p.recipient_key) for p in plans}

        def about(code: str, key: str, **extra: Any) -> dict[str, Any]:
            return _violation(code, "recipient", key.partition(":")[2], names[key], recipient=key, **extra)

        sent_errors = [
            about(code, p.recipient_key, revision_id=str(rev))
            for p in plans
            for rev, code in dr.release_content_errors([views[r] for r in p.revision_ids], p.purpose)
        ]
        if sent_errors:
            raise DesignError(sent_errors[0]["code"], 422, violations=sent_errors)
        if any(p.duplicates for p in plans) and dr.rationale_error(duplicate_reason):
            raise DesignError(
                "duplicate_issue",
                409,
                violations=[
                    about("duplicate_issue", p.recipient_key, revision_id=str(r)) for p in plans for r in p.duplicates
                ],
            )
        people = {p.recipient_key: await self._recipients_for(project_id, p.recipient_key) for p in plans}
        empty = [p.recipient_key for p in plans if p.revision_ids and not people[p.recipient_key]]
        if empty:
            # A transmittal to nobody would pass as issued; the matrix has to be repaired first.
            raise DesignError(
                "release_recipient_empty",
                422,
                violations=[about("release_recipient_empty", k) for k in empty],
            )
        svc = TransmittalService(self.session)
        today = _now().date().isoformat()
        release_id = row.id
        issue_plan, transmittal_ids = [], []
        for plan in plans:
            entry = {
                "recipient_key": plan.recipient_key,
                "transmittal_id": None,
                "purpose": plan.purpose,
                "revision_ids": [str(r) for r in plan.revision_ids],
                "excluded": [{"revision_id": str(r), "reason": c} for r, c in plan.excluded],
                "duplicates": [str(r) for r in plan.duplicates],
            }
            issue_plan.append(entry)
            if not plan.revision_ids:
                continue  # everything excluded for this recipient: recorded, nothing sent
            # One transmittal per recipient: the recipient's name keeps the subjects apart in the list.
            recipient_name = names.get(plan.recipient_key) or ""
            subject = f"{row.code} {row.title}" + (f" - {recipient_name}" if recipient_name else "")
            tr = await svc.create_transmittal(
                TransmittalCreate(
                    project_id=project_id,
                    subject=subject[:500],
                    purpose_code=plan.purpose,
                    issued_date=today,
                    recipients=[RecipientCreate(**r) for r in people[plan.recipient_key]],
                    items=[ItemCreate(revision_id=r, item_number=i) for i, r in enumerate(plan.revision_ids, start=1)],
                    metadata={"design_release_id": str(release_id), "recipient_key": plan.recipient_key},
                ),
                user_id=_s(actor_id),
            )
            entry["transmittal_id"] = str(tr.id)
            transmittal_ids.append(str(tr.id))
        # ``create_transmittal`` rolls the session back on a number collision and retries. That
        # rollback drops this method's row lock and expires ``row``, and discards what the loop
        # wrote before it. Take the lock again on a fresh read and count what survived.
        row = (
            await self.session.execute(
                select(DesignRelease)
                .where(DesignRelease.id == release_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None or row.status != "ready":
            raise conflict("concurrent_issue")
        found = (
            await self.session.execute(
                select(func.count())
                .select_from(Transmittal)
                .where(Transmittal.id.in_([uuid.UUID(t) for t in transmittal_ids]))
            )
        ).scalar_one()
        if found != len(transmittal_ids):
            raise conflict("concurrent_issue")
        for tid in transmittal_ids:
            await svc.issue_transmittal(uuid.UUID(tid))
        row.transmittal_ids, row.issue_plan = transmittal_ids, issue_plan
        row.duplicate_reason = duplicate_reason or ""
        await self._fsm(dfsm.RELEASE_FSM, row, "issued", actor_id)
        row.issued_by, row.issued_at = actor_id, _now()
        await self.session.flush()
        await self._audit(actor_id, "design_release", row.id, "issued", transmittals=len(transmittal_ids))
        self._publish(
            "design_management.release.issued",
            project_id=project_id,
            release_id=row.id,
            transmittal_ids=transmittal_ids,
        )
        return row

    # ── reviews ───────────────────────────────────────────────────────────

    async def create_review(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        await self._require_phase(project_id, data.get("phase_code"))
        await self._check_phase(project_id, data.get("phase_code"))
        for did in data.get("deliverable_ids") or []:
            await self._get(DesignDeliverable, project_id, did, "deliverable_not_found")
        for rid in data.get("reviewer_role_ids") or []:
            await self._get(DesignRole, project_id, rid, "role_not_found")
        code = data.get("code") or await self._next_code(DesignReview, project_id, "REV")
        await self._unique_code(DesignReview, project_id, code)
        row = await self._add(
            DesignReview(
                project_id=project_id,
                code=code,
                title=data.get("title") or code,
                phase_code=data.get("phase_code") or None,
                deliverable_ids=_uuids(data.get("deliverable_ids")),
                reviewer_role_ids=_uuids(data.get("reviewer_role_ids")),
                status="planned",
            )
        )
        await self._audit(actor_id, "design_review", row.id, "created", code=code)
        return row

    async def review_comments(self, project_id: uuid.UUID, review_id: uuid.UUID) -> list[DesignReviewComment]:
        stmt = (
            select(DesignReviewComment)
            .where(DesignReviewComment.project_id == project_id, DesignReviewComment.review_id == review_id)
            .order_by(DesignReviewComment.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def review_transition(self, project_id: uuid.UUID, rid: Any, target: str, *, actor_id: uuid.UUID):
        row = await self._get(DesignReview, project_id, rid, "review_not_found", lock=True)
        refused = await self.review_transition_refusal(row, target)
        if refused is not None:
            raise refused
        await self._fsm(dfsm.REVIEW_FSM, row, target, actor_id)
        await self.session.flush()
        return row

    async def review_transition_refusal(self, row: DesignReview, target: str) -> DesignError | None:
        """Why a review cannot move to ``target`` now, or ``None``."""
        if target == "concluded":
            return conflict("use_conclude")
        refused = _edge(dfsm.REVIEW_FSM, row, target)
        if refused is not None:
            return refused
        if target == "comments_closed":
            comments = await self.review_comments(row.project_id, row.id)
            if any(c.status in ("open", "answered") for c in comments):
                return conflict("review_comments_open")
        return None

    async def conclude_review(self, project_id: uuid.UUID, rid: Any, outcome: str, *, actor_id: uuid.UUID):
        if outcome not in ("accepted", "accepted_with_comments", "rework"):
            raise DesignError("review_outcome_invalid", 422)
        row = await self._get(DesignReview, project_id, rid, "review_not_found", lock=True)
        refused = _edge(dfsm.REVIEW_FSM, row, "concluded")
        if refused is not None:
            raise refused
        await self._fsm(dfsm.REVIEW_FSM, row, "concluded", actor_id)
        row.outcome, row.concluded_by, row.concluded_at = outcome, actor_id, _now()
        await self.session.flush()
        self._publish("design_management.review.concluded", project_id=project_id, review_id=row.id, outcome=outcome)
        return row

    async def add_comment(self, project_id: uuid.UUID, rid: Any, data: dict[str, Any], *, actor_id: uuid.UUID):
        review = await self._get(DesignReview, project_id, rid, "review_not_found", lock=True)
        if review.status not in ("planned", "open"):
            raise conflict("review_not_open")
        container_id = None
        if data.get("revision_id"):
            view = (await self._revision_views(project_id, [data["revision_id"]]))[0]
            container_id = view.container_id
        if not (data.get("text") or "").strip():
            raise DesignError("comment_text_required", 422)
        if data.get("severity", "minor") not in ("minor", "major", "critical"):
            raise DesignError("severity_invalid", 422)
        if review.status == "planned":
            await self._fsm(dfsm.REVIEW_FSM, review, "open", actor_id)
        row = await self._add(
            DesignReviewComment(
                project_id=project_id,
                review_id=review.id,
                container_id=container_id,
                revision_id=_uuid(data.get("revision_id")),
                text=data["text"].strip(),
                severity=data.get("severity", "minor"),
                status="open",
                created_by=actor_id,
            )
        )
        return row

    async def comment_transition(
        self, project_id: uuid.UUID, cid: Any, target: str, *, actor_id: uuid.UUID, answer: str = "", role_id=None
    ):
        row = await self._get(DesignReviewComment, project_id, cid, "comment_not_found", lock=True)
        refused = _edge(dfsm.COMMENT_FSM, row, target)
        if refused is not None:
            raise refused
        if target == "answered":
            if dr.rationale_error(answer):
                raise DesignError("answer_required", 422)
            row.answer = answer
            if role_id:
                row.answered_by_role_id = (await self._get(DesignRole, project_id, role_id, "role_not_found")).id
        await self._fsm(dfsm.COMMENT_FSM, row, target, actor_id)
        await self.session.flush()
        return row

    # ── reports (rules 17, 18) ────────────────────────────────────────────

    async def create_report(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        setup = await self.require_setup(project_id)
        catalogue = await self.reports_catalogue(setup)
        kind = catalogue.kind(data.get("kind_code") or "")
        if kind is None:
            raise DesignError("report_kind_unknown", 422)
        check = data.get("independent_check") or kind.independent_check
        overridden = check != kind.independent_check
        # Rule 18: a catalogue hint overridden needs words.
        if overridden and dr.rationale_error(data.get("rationale")):
            raise DesignError("hint_override_needs_rationale", 422)
        await self._check_phase(project_id, data.get("phase_code"))
        for key in ("author_role_id", "checker_role_id"):
            if data.get(key):
                await self._get(DesignRole, project_id, data[key], "role_not_found")
        container_id = await self._container_in_project(project_id, data.get("container_id"))
        code = data.get("code") or await self._next_code(DesignReport, project_id, "RPT")
        await self._unique_code(DesignReport, project_id, code)
        row = await self._add(
            DesignReport(
                project_id=project_id,
                code=code,
                kind_code=kind.code,
                title=data.get("title") or code,
                phase_code=data.get("phase_code"),
                author_role_id=_uuid(data.get("author_role_id")),
                checker_role_id=_uuid(data.get("checker_role_id")),
                container_id=container_id,
                external_check=bool(data.get("external_check", False)),
                required=bool(data.get("required", True)),
                required_reason="catalogue" if data.get("from_catalogue") else "manual",
                independent_check=check,
                hint_overridden=overridden,
                rationale=data.get("rationale") or "",
                status="required",
                governance_condition_ids=[],
            )
        )
        await self._audit(actor_id, "design_report", row.id, "created", kind=kind.code)
        return row

    async def _container_in_project(self, project_id: uuid.UUID, container_id: Any) -> uuid.UUID | None:
        from app.modules.cde.models import DocumentContainer

        cid = _uuid(container_id)
        if cid is None:
            return None
        c = await self.session.get(DocumentContainer, cid)
        if c is None or c.project_id != project_id:
            raise not_found("container_not_found")
        return cid

    #: Report fields rule 17 and the rule 16 gate read. Changing one needs ``design.manage``.
    REPORT_GATE_FIELDS = ("author_role_id", "checker_role_id", "external_check", "review_cycle_id", "required")
    #: From submission on a set value is frozen; an empty checker or cycle link may still be filled in.
    REPORT_FROZEN_STATES = ("submitted", "under_check", "remarks", "accepted", "rejected")

    def report_gate_gate(self, row: DesignReport, data: dict[str, Any], *, may_manage: bool) -> str | None:
        """Why this patch may not touch the gate fields, or ``None``. The same answer drives ``can.edit_gate_fields``."""
        changed = [
            k
            for k in self.REPORT_GATE_FIELDS
            if k in data and data[k] != (_s(getattr(row, k)) if k.endswith("_id") else getattr(row, k))
        ]
        if not changed:
            return None
        if not may_manage:
            return "manage_required"
        frozen = row.status in self.REPORT_FROZEN_STATES
        if frozen and any(not k.endswith("_id") or getattr(row, k) is not None for k in changed):
            return "report_fields_frozen"
        return None

    async def patch_report(
        self, project_id: uuid.UUID, rid: Any, data: dict[str, Any], *, actor_id: uuid.UUID, may_manage: bool = False
    ):
        row = await self._get(DesignReport, project_id, rid, "report_not_found", lock=True)
        refused = self.report_gate_gate(row, data, may_manage=may_manage)
        if refused == "manage_required":
            raise forbidden(refused)
        if refused:
            raise conflict(refused)
        if data.get("required") is False and row.required:
            # Rule 18: dropping a report from readiness needs words, on this door as on the transition.
            if dr.rationale_error(data.get("rationale")):
                raise DesignError("not_required_needs_rationale", 422)
        if "rationale" in data:
            row.rationale = data["rationale"]
        for key in ("author_role_id", "checker_role_id"):
            if key in data:
                if data[key]:
                    await self._get(DesignRole, project_id, data[key], "role_not_found")
                setattr(row, key, _uuid(data[key]))
        if "container_id" in data:
            row.container_id = await self._container_in_project(project_id, data["container_id"])
        if "review_cycle_id" in data:
            row.review_cycle_id = await self._cycle_in_project(project_id, data["review_cycle_id"])
        if "phase_code" in data:
            await self._check_phase(project_id, data["phase_code"])
        for key in ("title", "phase_code", "external_check", "conditions_text", "required"):
            if key in data:
                setattr(row, key, data[key])
        await self.session.flush()
        await self._audit(actor_id, "design_report", row.id, "updated", fields=sorted(data))
        return row

    async def _cycle_in_project(self, project_id: uuid.UUID, cycle_id: Any) -> uuid.UUID | None:
        from app.modules.review_authority.models import ReviewCycle

        cid = _uuid(cycle_id)
        if cid is None:
            return None
        cycle = await self.session.get(ReviewCycle, cid)
        if cycle is None or cycle.project_id != project_id:
            raise not_found("review_cycle_not_found")
        return cid

    async def _cycle_state(self, cycle_id: uuid.UUID | None) -> str | None:
        from app.modules.review_authority.models import ReviewCycle

        if cycle_id is None:
            return None
        cycle = await self.session.get(ReviewCycle, cycle_id)
        return cycle.status if cycle else None

    async def _party(self, project_id: uuid.UUID, role_id: uuid.UUID | None) -> str | None:
        if role_id is None:
            return None
        role = await self.session.get(DesignRole, role_id)
        if role is None or role.project_id != project_id:
            return None
        return dr.party_key(contact_id=role.contact_id, originator_code=role.originator_code, party_kind=None) or (
            f"role:{role.id}"
        )

    async def report_transition(
        self, project_id: uuid.UUID, rid: Any, target: str, *, actor_id: uuid.UUID, rationale: str = ""
    ) -> DesignReport:
        row = await self._get(DesignReport, project_id, rid, "report_not_found", lock=True)
        refused = await self.report_transition_refusal(row, target)
        if refused is not None:
            raise refused
        if target == "not_required":
            if dr.rationale_error(rationale):
                raise DesignError("not_required_needs_rationale", 422)
            row.rationale = rationale
        await self._fsm(dfsm.REPORT_FSM, row, target, actor_id, reason=rationale or None)
        await self.session.flush()
        self._publish(
            "design_management.report.state_changed", project_id=project_id, report_id=row.id, state=row.status
        )
        return row

    async def report_transition_refusal(self, row: DesignReport, target: str) -> DesignError | None:
        """Why a report cannot move to ``target`` now, or ``None`` (rule 17 on acceptance)."""
        refused = _edge(dfsm.REPORT_FSM, row, target)
        if refused is not None:
            return refused
        if target == "accepted":
            error = dr.report_acceptance_error(
                independent_check=row.independent_check,
                author_party=await self._party(row.project_id, row.author_role_id),
                checker_party=await self._party(row.project_id, row.checker_role_id),
                external=row.external_check,
                cycle_state=await self._cycle_state(row.review_cycle_id),
            )
            if error:
                return DesignError(error, 422)
        return None

    async def sync_report(self, project_id: uuid.UUID, rid: Any, *, actor_id: uuid.UUID) -> DesignReport:
        """Follow the linked external check cycle (read, never typed)."""
        row = await self._get(DesignReport, project_id, rid, "report_not_found", lock=True)
        state = await self._cycle_state(row.review_cycle_id)
        target = dfsm.CYCLE_TO_REPORT.get(state or "")
        if target and target != row.status:
            path = dfsm.permit_path(dfsm.REPORT_FSM, row.status, target)
            for step in path:
                if step == "accepted":
                    return await self.report_transition(project_id, row.id, "accepted", actor_id=actor_id)
                await self._fsm(dfsm.REPORT_FSM, row, step, actor_id, reason="review cycle")
            await self.session.flush()
        return row

    async def report_hints(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Country hints of the pinned catalogue for this project's country (shown, never enforced)."""
        setup = await self.require_setup(project_id)
        catalogue = await self.reports_catalogue(setup)
        project = await self._project(project_id)
        country = (getattr(project, "country_code", None) or "").upper()
        region = (getattr(project, "subdivision_code", None) or "").upper()
        out = []
        for k in catalogue.report_kinds:
            for r in k.country_rules:
                if r.country != country:
                    continue
                if r.region and region and not region.endswith(r.region):
                    continue
                out.append(
                    {
                        "kind_code": k.code,
                        "region": r.region,
                        "text_key": r.text_key,
                        "condition_key": r.condition_key,
                        "source_url": r.source_url,
                        "review_status": str(r.review_status),
                    }
                )
        return out

    # ── permits (rules 19, 20) ────────────────────────────────────────────

    async def create_permit(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID):
        setup = await self.require_setup(project_id)
        catalogue = await self.reports_catalogue(setup)
        if catalogue.profile(data.get("profile_code") or "") is None:
            raise DesignError("permit_profile_unknown", 422)
        code = data.get("code") or await self._next_code(DesignPermit, project_id, "PP")
        await self._unique_code(DesignPermit, project_id, code)
        row = await self._add(
            DesignPermit(
                project_id=project_id,
                code=code,
                title=data.get("title") or code,
                profile_code=data["profile_code"],
                review_cycle_id=await self._cycle_in_project(project_id, data.get("review_cycle_id")),
                authority_submission_id=await self._submission_in_project(
                    project_id, data.get("authority_submission_id")
                ),
                permit_application_id=_uuid(data.get("permit_application_id")),
                target_submission_date=data.get("target_submission_date"),
                schedule_activity_id=_uuid(data.get("schedule_activity_id")),
                status="assembling",
                conditions=[],
            )
        )
        await self._audit(actor_id, "design_permit", row.id, "created", code=code)
        return row

    async def _submission_in_project(self, project_id: uuid.UUID, sid: Any) -> uuid.UUID | None:
        from app.modules.authority_submission.models import Submission

        sub_id = _uuid(sid)
        if sub_id is None:
            return None
        sub = await self.session.get(Submission, sub_id)
        if sub is None or sub.project_id != project_id:
            raise not_found("submission_not_found")
        return sub_id

    async def patch_permit(
        self, project_id: uuid.UUID, pid: Any, data: dict[str, Any], *, actor_id: uuid.UUID, may_manage: bool = False
    ):
        row = await self._get(DesignPermit, project_id, pid, "permit_not_found", lock=True)
        submitted = row.status not in ("assembling", "ready")
        for key in ("review_cycle_id", "authority_submission_id"):
            if key not in data or data[key] == _s(getattr(row, key)) or not submitted:
                continue
            # After submission the package state is read from the cycle: a link is filled in once, never swapped.
            if getattr(row, key) is not None:
                raise conflict("permit_link_frozen")
            if not may_manage:
                raise forbidden("manage_required")
        if "review_cycle_id" in data:
            row.review_cycle_id = await self._cycle_in_project(project_id, data["review_cycle_id"])
        if "authority_submission_id" in data:
            row.authority_submission_id = await self._submission_in_project(project_id, data["authority_submission_id"])
        for key in ("permit_application_id", "schedule_activity_id"):
            if key in data:
                setattr(row, key, _uuid(data[key]))
        for key in ("title", "target_submission_date"):
            if key in data:
                setattr(row, key, data[key])
        await self.session.flush()
        return row

    async def permit_items(self, project_id: uuid.UUID, permit_id: uuid.UUID) -> list[DesignPermitItem]:
        stmt = select(DesignPermitItem).where(
            DesignPermitItem.project_id == project_id, DesignPermitItem.permit_id == permit_id
        )
        return list((await self.session.execute(stmt.order_by(DesignPermitItem.created_at))).scalars().all())

    async def add_permit_item(self, project_id: uuid.UUID, pid: Any, data: dict[str, Any], *, actor_id: uuid.UUID):
        permit = await self._get(DesignPermit, project_id, pid, "permit_not_found", lock=True)
        if permit.status not in ("assembling", "ready"):
            raise conflict("permit_locked")
        kind = data.get("kind")
        if kind not in ("drawing", "report", "form"):
            raise DesignError("permit_item_kind_invalid", 422)
        container_id = await self._container_in_project(project_id, data.get("container_id"))
        report_id = None
        if kind == "report":
            report = await self._get(DesignReport, project_id, data.get("report_id"), "report_not_found")
            report_id, container_id = report.id, report.container_id
        row = await self._add(
            DesignPermitItem(
                project_id=project_id,
                permit_id=permit.id,
                kind=kind,
                title=data.get("title") or "",
                container_id=container_id,
                report_id=report_id,
                required=bool(data.get("required", True)),
            )
        )
        if permit.status == "ready":
            await self._fsm(dfsm.PERMIT_FSM, permit, "assembling", actor_id, reason="item added")
        return row

    async def remove_permit_item(self, project_id: uuid.UUID, pid: Any, item_id: Any, *, actor_id: uuid.UUID):
        permit = await self._get(DesignPermit, project_id, pid, "permit_not_found", lock=True)
        if permit.status not in ("assembling", "ready"):
            raise conflict("permit_locked")
        item = await self._get(DesignPermitItem, project_id, item_id, "permit_item_not_found")
        if item.permit_id != permit.id:
            raise not_found("permit_item_not_found")
        await self.session.delete(item)
        await self.session.flush()

    async def permit_check(self, project_id: uuid.UUID, permit: DesignPermit) -> list[dict[str, Any]]:
        """Rule 19: each item with whether it is present and in a state good enough to submit."""
        from app.modules.cde.models import DocumentContainer

        out = []
        for item in await self.permit_items(project_id, permit.id):
            c = await self.session.get(DocumentContainer, item.container_id) if item.container_id else None
            present = c is not None and c.current_revision_id is not None
            state_ok = present and c.cde_state in ("shared", "published")
            if item.kind == "report" and item.report_id:
                report = await self.session.get(DesignReport, item.report_id)
                state_ok = state_ok and report is not None and report.status in ("submitted", "under_check", "accepted")
            out.append(
                {
                    "item": item,
                    "present": present,
                    "state_ok": state_ok,
                    "current_revision_id": _s(c.current_revision_id) if c else None,
                }
            )
        return out

    #: Authority decisions. Read from the linked review cycle when there is one.
    PERMIT_DECISIONS = ("under_review", "remarks", "approved", "partially_approved", "refused")

    @staticmethod
    def permit_decision_gate(permit: DesignPermit, target: str, *, may_manage: bool) -> str | None:
        """Why an authority decision may not be typed, or ``None``.

        A package without a review cycle has nothing to read its state from, so
        a person with ``design.manage`` records the authority's answer. A partial
        approval is no cycle state at all and is always recorded by a person.
        """
        partial = target == "partially_approved" or permit.status == "partially_approved"
        if permit.review_cycle_id is not None and not partial:
            return "permit_state_read_from_cycle"
        return None if may_manage else "manage_required"

    async def permit_transition(
        self, project_id: uuid.UUID, pid: Any, target: str, *, actor_id: uuid.UUID, may_manage: bool = False
    ):
        permit = await self._get(DesignPermit, project_id, pid, "permit_not_found", lock=True)
        refused = await self.permit_transition_refusal(permit, target, may_manage=may_manage)
        if refused is not None:
            raise refused
        if target == "submitted":
            if permit.status == "assembling":
                await self._fsm(dfsm.PERMIT_FSM, permit, "ready", actor_id)
            for c in await self.permit_check(project_id, permit):
                c["item"].included_revision_id = _uuid(c["current_revision_id"])
            permit.submitted_by, permit.submitted_at = actor_id, _now()
        await self._fsm(dfsm.PERMIT_FSM, permit, target, actor_id)
        await self.session.flush()
        self._publish(
            "design_management.permit.state_changed", project_id=project_id, permit_id=permit.id, state=permit.status
        )
        return permit

    async def permit_transition_refusal(
        self, permit: DesignPermit, target: str, *, may_manage: bool
    ) -> DesignError | None:
        """Why a permit package cannot move to ``target`` now, or ``None``.

        ``submitted`` straight from ``assembling`` is one step for the user
        (the package passes ``ready`` on the way), so it is checked as such.
        """
        via_ready = permit.status == "assembling" and target == "submitted"
        if target not in dfsm.PERMIT_STATES:
            return conflict("invalid_transition", detail=target)
        if target in self.PERMIT_DECISIONS and permit.review_cycle_id is not None:
            # A state the cycle owns is refused as such before the edge is judged: the answer is where to read it.
            gate = self.permit_decision_gate(permit, target, may_manage=may_manage)
            if gate == "permit_state_read_from_cycle":
                return conflict(gate)
        refused = None if via_ready else _edge(dfsm.PERMIT_FSM, permit, target)
        if refused is not None:
            return refused
        if target in ("ready", "submitted"):
            checks = await self.permit_check(permit.project_id, permit)
            if not checks:
                return DesignError("permit_empty", 422)
            missing = dr.permit_missing(
                [
                    dr.PermitItemView(c["item"].id, c["item"].kind, c["item"].required, c["present"], c["state_ok"])
                    for c in checks
                ]
            )
            if missing:
                titles = {c["item"].id: c["item"].title for c in checks}
                return DesignError(
                    "permit_incomplete",
                    422,
                    violations=[
                        _violation("permit_item_missing", "permit_item", m, titles.get(m) or "") for m in missing
                    ],
                )
        elif target in self.PERMIT_DECISIONS:
            gate = self.permit_decision_gate(permit, target, may_manage=may_manage)
            if gate == "manage_required":
                return forbidden(gate)
            if gate:
                return conflict(gate)
        return None

    async def sync_permit(self, project_id: uuid.UUID, pid: Any, *, actor_id: uuid.UUID) -> DesignPermit:
        """States from ``submitted`` on are read from the linked review cycle; content drift is flagged."""
        from app.modules.cde.models import DocumentContainer

        permit = await self._get(DesignPermit, project_id, pid, "permit_not_found", lock=True)
        state = await self._cycle_state(permit.review_cycle_id)
        target = dfsm.CYCLE_TO_PERMIT.get(state or "")
        if target and permit.status not in ("assembling", "ready") and target != permit.status:
            for step in dfsm.permit_path(dfsm.PERMIT_FSM, permit.status, target):
                await self._fsm(dfsm.PERMIT_FSM, permit, step, actor_id, reason="review cycle")
        if permit.submitted_at is not None:
            items = await self.permit_items(project_id, permit.id)
            pinned = {i.container_id: i.included_revision_id for i in items if i.container_id}
            current = {}
            for cid in pinned:
                c = await self.session.get(DocumentContainer, cid)
                current[cid] = c.current_revision_id if c else None
            permit.superseded_content = bool(dr.superseded_items(pinned, current))
        await self.session.flush()
        return permit

    async def propose_conditions(self, project_id: uuid.UUID, pid: Any, texts: list[dict[str, Any]], *, actor_id):
        """Rule 20: conditions recorded on approval start as proposals; nothing is created yet."""
        permit = await self._get(DesignPermit, project_id, pid, "permit_not_found", lock=True)
        if permit.status not in ("approved", "partially_approved"):
            raise conflict("permit_not_approved")
        for t in texts:
            await self._assert_member(project_id, t.get("owner_user_id"))
        added = [
            {
                "id": str(uuid.uuid4()),
                "text": t["text"].strip(),
                "owner_user_id": _s(_uuid(t.get("owner_user_id"))),
                "due_date": t.get("due_date"),
                "state": "proposed",
                "task_id": None,
            }
            for t in texts
            if (t.get("text") or "").strip()
        ]
        permit.conditions = [*(permit.conditions or []), *added]
        await self.session.flush()
        return permit

    async def _assert_member(self, project_id: uuid.UUID, user_id: Any) -> None:
        """A named owner must be able to open this project; an id from elsewhere is refused (rule 24)."""
        from fastapi import HTTPException

        from app.dependencies import verify_project_access

        uid = _uuid(user_id)
        if uid is None:
            return
        try:
            await verify_project_access(project_id, str(uid), self.session)
        except HTTPException as exc:
            raise DesignError("condition_owner_not_member", 422) from exc

    async def confirm_condition(
        self, project_id: uuid.UUID, pid: Any, condition_id: str, *, confirm: bool, actor_id: uuid.UUID
    ) -> DesignPermit:
        """Rule 20: a person confirms ONE condition; only then a task with owner and due date is created."""
        from app.modules.tasks.schemas import TaskCreate
        from app.modules.tasks.service import TaskService

        permit = await self._get(DesignPermit, project_id, pid, "permit_not_found", lock=True)
        conditions = [dict(c) for c in permit.conditions or []]
        entry = next((c for c in conditions if c["id"] == condition_id), None)
        if entry is None:
            raise not_found("condition_not_found")
        if entry["state"] != "proposed":
            raise conflict("condition_not_proposed")
        if confirm:
            if not entry.get("owner_user_id") or not entry.get("due_date"):
                raise DesignError("condition_needs_owner_and_due_date", 422)
            await self._assert_member(project_id, entry["owner_user_id"])
            task = await TaskService(self.session).create_task(
                TaskCreate(
                    project_id=project_id,
                    task_type="task",
                    title=entry["text"][:500],
                    description=f"{permit.code}: {permit.title}"[:5000],
                    responsible_id=entry["owner_user_id"],
                    due_date=entry["due_date"],
                ),
                user_id=_s(actor_id),
            )
            entry.update(state="confirmed", task_id=str(task.id))
        else:
            entry["state"] = "dismissed"
        permit.conditions = conditions
        await self.session.flush()
        await self._audit(actor_id, "design_permit", permit.id, "condition_" + entry["state"], condition=condition_id)
        return permit

    # ── readiness, frame documents, validation ────────────────────────────

    async def readiness(self, project_id: uuid.UUID, phase_code: str | None) -> dr.PhaseBlockers:
        """Rule 16: what still blocks a design phase, or the whole project when ``phase_code`` is ``None``."""
        deliverables = await self.deliverables(project_id)
        reports = await self._list(DesignReport, project_id)
        reviews = {r.id: r for r in await self._list(DesignReview, project_id)}
        majors = [
            reviews[c.review_id].phase_code
            for c in await self._list(DesignReviewComment, project_id)
            if c.severity in ("major", "critical") and c.status in ("open", "answered") and c.review_id in reviews
        ]
        return dr.phase_blockers(
            phase_code,
            deliverables=[(d.code, d.phase_code, d.status, d.required) for d in deliverables],
            reports=[(r.code, r.phase_code, r.status, r.required) for r in reports],
            open_major_comments=majors,
        )

    async def _frame_document(self, project_id: uuid.UUID, *, actor_id: uuid.UUID, governance_manager: bool) -> Any:
        """The governance frame document design writes into; created on first use when the model offers its type.

        Read through module 1's port; the one write (adding the document) is
        module 1's own, under its own rule: the area's owner or deputy, or a
        governance manager.
        """
        from app.modules.project_governance.public import project_areas, project_documents
        from app.modules.project_governance.service import GovernanceService

        await self._project_lock(project_id, "frame_document")
        host = await design_host(self.session, project_id)
        if host is None:
            raise not_found("frame_document_missing")
        area = next((a for a in await project_areas(self.session, project_id) if a.code == host.area_code), None)
        if area is None:
            raise not_found("frame_document_missing")
        for d in await project_documents(self.session, project_id):
            if d.area_id == area.id and d.code == host.doc_type:
                return d
        return await GovernanceService(self.session).create_document(
            project_id, area_id=area.id, doc_type=host.doc_type, actor_id=actor_id, is_manager=governance_manager
        )

    async def _frame_container(self, project_id: uuid.UUID, register: str, *, actor_id: uuid.UUID) -> Any:
        """The one CDE container of a register: a revision stream of its own, found by its fixed code."""
        from app.core.cde_naming import server_write
        from app.modules.cde.models import DocumentContainer
        from app.modules.cde.schemas import ContainerCreate
        from app.modules.cde.service import CDEService

        code = f"{FRAME_CODE_PREFIX}{register.upper()}"
        stmt = select(DocumentContainer).where(
            DocumentContainer.project_id == project_id, DocumentContainer.container_code == code
        )
        container = (await self.session.execute(stmt)).scalars().first()
        if container is not None:
            return container
        # Not a drawing: the code is this module's own and must not be judged by the drawing scheme.
        with server_write():
            return await CDEService(self.session).create_container(
                ContainerCreate(
                    project_id=project_id,
                    container_code=code,
                    title=f"Design {register.replace('_', ' ')}",
                    metadata={FRAME_MARKER: register},
                ),
                user_id=_s(actor_id),
            )

    async def generate_frame_document(
        self,
        project_id: uuid.UUID,
        register: str,
        *,
        actor_id: uuid.UUID,
        file_bytes: bytes,
        file_name: str,
        governance_manager: bool = False,
    ) -> dict[str, Any]:
        """Rule 23: store the generated register and add it as a new revision of that register's own container.

        Each register (drawings, matrix, reports, permit) has one container, so
        its revisions are a history of that register only. The governance frame
        document points at the first register generated unless a container was
        attached to it before; binding it then freezes the design standard.
        ``governance_manager`` is the caller's ``governance.manage`` permission:
        the writes to the governance document follow module 1's own rule.
        """
        import hashlib

        from app.core.storage import get_storage_backend
        from app.modules.cde.schemas import RevisionCreate
        from app.modules.cde.service import CDEService

        if register not in FRAME_REGISTERS:
            raise DesignError("frame_register_unknown", 422, detail=register)
        from app.modules.project_governance.service import GovernanceService

        document = await self._frame_document(project_id, actor_id=actor_id, governance_manager=governance_manager)
        if document.status == "binding":
            raise conflict("binding_requires_change_request")
        container = await self._frame_container(project_id, register, actor_id=actor_id)
        if document.container_id is None:
            await GovernanceService(self.session).attach_container(
                project_id, document.id, container_id=container.id, actor_id=actor_id, is_manager=governance_manager
            )
        digest = hashlib.sha256(file_bytes).hexdigest()
        storage_key = f"design_management/{project_id}/frame/{register}/{digest}.pdf"
        await get_storage_backend().put(storage_key, file_bytes)
        revision = await CDEService(self.session).create_revision(
            container.id,
            RevisionCreate(
                file_name=file_name,
                content_hash=digest,
                file_size=str(len(file_bytes)),
                mime_type="application/pdf",
                storage_key=storage_key,
                change_summary=f"design_management:{register}",
            ),
            user_id=_s(actor_id),
        )
        await self.session.flush()
        await self._audit(actor_id, "design_setup", document.id, "frame_document_generated", register=register)
        return {
            "document_id": str(document.id),
            "register": register,
            "container_id": str(container.id),
            "revision_id": str(revision.id),
            "storage_key": storage_key,
        }

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The one payload the ``design_management`` rule set reads."""
        setup = await self.get_setup(project_id)
        scheme = await self.scheme(setup) if setup else None
        rows = await self.wbs_rows(project_id)
        unresolved = await wbs_refs.unresolved_references(self.session, project_id, rows)
        reports_cat = await self.reports_catalogue(setup) if setup else None
        drawings = []
        for d, c in await self._drawings_with_containers(project_id):
            drawings.append(
                {
                    "id": str(d.id),
                    "number": c.container_code,
                    "parts": self._stored_parts(c),
                    "legacy_scheme": d.legacy_scheme,
                    "title_block_number": d.title_block_number,
                    "originator": c.originator_code,
                }
            )
        releases = []
        for rel in await self._list(DesignRelease, project_id):
            if rel.status in ("ready", "issued"):
                views = await self._revision_views(project_id, rel.revision_ids or [])
                releases.append(
                    {
                        "code": rel.code,
                        "purpose": rel.purpose,
                        "revisions": [{"id": str(v.revision_id), "suitability": v.suitability_code} for v in views],
                    }
                )
        deliverables = await self.deliverables(project_id)
        reports = []
        for r in await self._list(DesignReport, project_id):
            reports.append(
                {
                    "code": r.code,
                    "status": r.status,
                    "independent_check": r.independent_check,
                    "author_party": await self._party(project_id, r.author_role_id),
                    "checker_party": await self._party(project_id, r.checker_role_id),
                    "external": r.external_check,
                    "cycle_state": await self._cycle_state(r.review_cycle_id),
                    "rationale": r.rationale,
                    "hint_overridden": r.hint_overridden,
                }
            )
        permits = []
        for p in await self._list(DesignPermit, project_id):
            checks = await self.permit_check(project_id, p)
            permits.append(
                {
                    "code": p.code,
                    "status": p.status,
                    "superseded_content": p.superseded_content,
                    "missing": len(
                        dr.permit_missing(
                            [
                                dr.PermitItemView(
                                    c["item"].id, c["item"].kind, c["item"].required, c["present"], c["state_ok"]
                                )
                                for c in checks
                            ]
                        )
                    ),
                }
            )
        points = [
            {"code": a.code, "status": a.status, "decided_by": _s(a.decided_by), "submitted_by": _s(a.submitted_by)}
            for a in await self._list(DesignApprovalPoint, project_id)
        ]
        return {
            "scheme": scheme.model_dump(mode="json") if scheme else None,
            "wbs": [{"id": str(r.id), "code": r.code} for r in rows],
            "unresolved": [
                {"module": u.module, "table": u.table, "row_id": u.row_id, "value": u.value} for u in unresolved
            ],
            "drawings": drawings,
            "originators": sorted(await self._active_originators(project_id)),
            "releases": releases,
            "deliverables": [
                {
                    "code": d.code,
                    "phase_code": d.phase_code,
                    "status": d.status,
                    "required": d.required,
                    "planned": d.planned_count,
                }
                for d in deliverables
            ],
            "reports": reports,
            "reports_catalogue": reports_cat.model_dump(mode="json") if reports_cat else None,
            "permits": permits,
            "approval_points": points,
            "four_eyes": bool(setup.four_eyes_release) if setup else True,
        }
