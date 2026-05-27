# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Data access for the clash detection module."""

from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.clash.models import (
    ClashCluster,
    ClashIssue,
    ClashResult,
    ClashRun,
    ClashSuppression,
)
from app.modules.clash.schemas import (
    CLASH_PROPERTY_GROUP_PREFIX,
    SEVERITY_ORDER,
)

# Property keys already surfaced by the four built-in facets — never
# re-advertised as an open-ended ``property:<key>`` grouping.
_BUILTIN_PROPERTY_KEYS = frozenset(
    {
        "category",
        "rvt_category",
        "ifc_class",
        "revit_category",
        "ifc_type",
        "ifc_entity",
        "IfcEntity",
    }
)
# Noise gates for the per-property key enumeration.
_PROPERTY_MIN_COVERAGE = 0.01  # key must be on ≥ 1 % of scanned elements
_PROPERTY_MAX_DISTINCT = 500  # near-unique keys (ids, GUIDs) are useless
_PROPERTY_MAX_KEYS = 60  # cap the selector to the top-N by coverage


class ClashRepository:
    """‌⁠‍CRUD for clash runs/results + the BIM element feed for the engine."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── BIM element feed (broad-phase input) ───────────────────────────

    async def models_for_project(self, project_id: uuid.UUID) -> list[BIMModel]:
        """‌⁠‍Every BIM model belonging to ``project_id`` (newest first)."""
        stmt = select(BIMModel).where(BIMModel.project_id == project_id).order_by(BIMModel.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def elements_with_geometry(self, model_ids: list[uuid.UUID]) -> list[BIMElement]:
        """Load every element of ``model_ids`` that carries a bounding box.

        Elements without geometry (annotations, schedules) can't clash, so
        they're filtered out at the query to keep the broad phase lean.
        """
        if not model_ids:
            return []
        stmt = select(BIMElement).where(
            BIMElement.model_id.in_(model_ids),
            BIMElement.bounding_box.is_not(None),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def categories_for_models(
        self, model_ids: list[uuid.UUID]
    ) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        """Distinct element_type and discipline facets (+ counts).

        Only counts elements that carry a bounding box — i.e. exactly the
        elements the clash broad phase will actually feed — so the Set A /
        Set B pickers never advertise a type that can't clash. Returns
        ``(element_types, disciplines)``, each a list of
        ``(value, count)`` sorted by count desc then value.
        """
        if not model_ids:
            return [], []

        async def _facet(col) -> list[tuple[str, int]]:
            stmt = (
                select(col, func.count())
                .where(
                    BIMElement.model_id.in_(model_ids),
                    BIMElement.bounding_box.is_not(None),
                    col.is_not(None),
                    col != "",
                )
                .group_by(col)
                .order_by(func.count().desc(), col)
            )
            return [(str(v), int(n)) for v, n in (await self.session.execute(stmt)).all()]

        return (
            await _facet(BIMElement.element_type),
            await _facet(BIMElement.discipline),
        )

    @staticmethod
    def _category_of(props: dict | None, element_type: str | None) -> str:
        """Resolve an element's source-native category.

        DDC/Revit elements carry ``rvt_category`` / ``category`` and IFC
        elements ``ifc_class`` in ``properties``; fall back to the
        indexed ``element_type`` so every clashable element is grouped
        under *some* category.
        """
        p = props or {}
        for key in ("category", "rvt_category", "ifc_class", "revit_category"):
            v = p.get(key)
            if v:
                return str(v).strip()
        return (element_type or "").strip()

    @staticmethod
    def _ifc_entity_of(props: dict | None) -> str:
        """Raw IFC entity (``IfcWall``…) — only present on IFC sources."""
        p = props or {}
        for key in ("ifc_type", "ifc_entity", "IfcEntity"):
            v = p.get(key)
            if v:
                return str(v).strip()
        return ""

    @staticmethod
    def _is_scalar(v: object) -> bool:
        """A property value usable as a facet — not a dict/list container.

        ``bool`` is a scalar (it survives the ``int`` subclass check too);
        ``None`` is treated as "absent" by the callers, never as a value.
        """
        return isinstance(v, (str, int, float, bool))

    async def _scan_facets_for_models(
        self, model_ids: list[uuid.UUID], property_key: str | None
    ) -> tuple[
        Counter[str],
        Counter[str],
        Counter[str],
        Counter[str],
        Counter[str],
        dict[str, set[str]],
    ]:
        """Single streaming pass over the models' clashable elements.

        Returns, in one scan, the type / category / ifc_entity value
        counters, the per-property-*key* coverage counter
        (``prop_key_c``), the value counter for a specific
        ``property_key`` (``prop_val_c`` — empty when ``property_key`` is
        ``None``), and the per-key distinct-value sets used to drop
        near-unique keys. Only bounding-box-carrying elements are scanned
        (exactly what the broad phase feeds).
        """
        type_c: Counter[str] = Counter()
        cat_c: Counter[str] = Counter()
        ifc_c: Counter[str] = Counter()
        prop_key_c: Counter[str] = Counter()
        prop_val_c: Counter[str] = Counter()
        distinct: dict[str, set[str]] = {}

        stmt = select(BIMElement.element_type, BIMElement.properties).where(
            BIMElement.model_id.in_(model_ids),
            BIMElement.bounding_box.is_not(None),
        )
        for etype, props in (await self.session.execute(stmt)).all():
            et = (etype or "").strip()
            if et:
                type_c[et] += 1
            cat = self._category_of(props, etype)
            if cat:
                cat_c[cat] += 1
            ent = self._ifc_entity_of(props)
            if ent:
                ifc_c[ent] += 1
            if not isinstance(props, dict):
                continue
            for key, val in props.items():
                if key in _BUILTIN_PROPERTY_KEYS or val is None or not self._is_scalar(val):
                    continue
                prop_key_c[key] += 1
                distinct.setdefault(key, set()).add(str(val))
                if property_key is not None and key == property_key:
                    sv = str(val).strip()
                    if sv:
                        prop_val_c[sv] += 1
        return type_c, cat_c, ifc_c, prop_key_c, prop_val_c, distinct

    @staticmethod
    def _enumerate_property_keys(
        prop_key_c: Counter[str],
        distinct: dict[str, set[str]],
        scanned: int,
    ) -> list[tuple[str, int]]:
        """Top enumerable property keys (key, element-coverage count).

        Drops keys present on fewer than 1 % of scanned elements, keys
        with more than 500 distinct values, then sorts by coverage desc
        (key asc tie-break) and caps to the top 60. ``scanned`` is the
        number of elements the single pass actually visited.
        """
        if scanned <= 0:
            return []
        floor = max(1, int(scanned * _PROPERTY_MIN_COVERAGE))
        kept = [
            (k, n) for k, n in prop_key_c.items() if n >= floor and len(distinct.get(k, ())) <= _PROPERTY_MAX_DISTINCT
        ]
        kept.sort(key=lambda kv: (-kv[1], kv[0]))
        return kept[:_PROPERTY_MAX_KEYS]

    async def grouping_facets_for_models(
        self, model_ids: list[uuid.UUID], group_by: str
    ) -> tuple[list[tuple[str, int]], set[str], list[tuple[str, int]]]:
        """Distinct (value, count) facets for a chosen grouping parameter.

        Only counts bounding-box-carrying elements (exactly what the
        broad phase feeds). ``group_by`` is one of
        ``discipline | type | category | ifc_entity`` *or* the
        open-ended ``property:<key>`` form (facet = distinct
        string-coerced/trimmed values of that element property). Returns
        ``(chosen_facets, available_builtins, available_properties)``
        where ``available_builtins`` is the set of *built-in* params
        that actually have data (so the UI can hide e.g. ``ifc_entity``
        on a pure-Revit project) and ``available_properties`` is the
        enumerated ``(key, coverage)`` list for the open-ended selector.
        Sorted by count desc then value. Folded into one element stream.
        """
        if not model_ids:
            return [], set(), []

        # Discipline facet stays in SQL (indexed column); everything
        # else is derived from the single Python stream below.
        discs = (await self.categories_for_models(model_ids))[1]

        prop_key = None
        if group_by.startswith(CLASH_PROPERTY_GROUP_PREFIX):
            prop_key = group_by[len(CLASH_PROPERTY_GROUP_PREFIX) :]

        (
            type_c,
            cat_c,
            ifc_c,
            prop_key_c,
            prop_val_c,
            distinct,
        ) = await self._scan_facets_for_models(model_ids, prop_key)
        scanned = sum(type_c.values())

        avail: set[str] = set()
        if discs:
            avail.add("discipline")
        if type_c:
            avail.add("type")
        if cat_c:
            avail.add("category")
        if ifc_c:
            avail.add("ifc_entity")

        available_props = self._enumerate_property_keys(prop_key_c, distinct, scanned)

        def _sorted(c: Counter[str]) -> list[tuple[str, int]]:
            return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))

        chosen: list[tuple[str, int]]
        if prop_key is not None:
            chosen = _sorted(prop_val_c)
        elif group_by == "discipline":
            chosen = discs
        elif group_by == "category":
            chosen = _sorted(cat_c)
        elif group_by == "ifc_entity":
            chosen = _sorted(ifc_c)
        else:  # "type" — the default / safe fallback
            chosen = _sorted(type_c)
        return chosen, avail, available_props

    # ── ClashRun ───────────────────────────────────────────────────────

    def add_run(self, run: ClashRun) -> None:
        self.session.add(run)

    async def get_run(self, project_id: uuid.UUID, run_id: uuid.UUID) -> ClashRun | None:
        stmt = select(ClashRun).where(ClashRun.id == run_id, ClashRun.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_runs(self, project_id: uuid.UUID) -> list[ClashRun]:
        stmt = select(ClashRun).where(ClashRun.project_id == project_id).order_by(ClashRun.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_run(self, run: ClashRun) -> None:
        await self.session.delete(run)
        await self.session.flush()

    # ── ClashResult ────────────────────────────────────────────────────

    def add_results(self, results: list[ClashResult]) -> None:
        self.session.add_all(results)

    async def clear_results(self, run_id: uuid.UUID) -> None:
        """Wipe a run's results (re-run replaces, never appends)."""
        await self.session.execute(delete(ClashResult).where(ClashResult.run_id == run_id))
        await self.session.flush()

    async def get_result(self, run_id: uuid.UUID, result_id: uuid.UUID) -> ClashResult | None:
        stmt = select(ClashResult).where(ClashResult.id == result_id, ClashResult.run_id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _severity_rank():
        """SQL expression ranking severity worst→least (critical=0…low=3).

        Unknown / legacy values sort last so a missing severity never
        floats to the top of a ``order_by=severity`` list.
        """
        return case(
            *((ClashResult.severity == sev, rank) for sev, rank in SEVERITY_ORDER.items()),
            else_=len(SEVERITY_ORDER),
        )

    async def list_results(
        self,
        run_id: uuid.UUID,
        *,
        status: str | None = None,
        clash_type: str | None = None,
        discipline: str | None = None,
        discipline_a: str | None = None,
        discipline_b: str | None = None,
        severity: str | None = None,
        order_by: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[ClashResult], int]:
        base = select(ClashResult).where(ClashResult.run_id == run_id)
        if status:
            base = base.where(ClashResult.status == status)
        if clash_type:
            base = base.where(ClashResult.clash_type == clash_type)
        if discipline:
            base = base.where((ClashResult.a_discipline == discipline) | (ClashResult.b_discipline == discipline))
        # Symmetric pair filter — the coordination-hub trade matrix drill-
        # down passes both halves, and a clash (X,Y) must match whether it
        # was stored as (X,Y) or (Y,X). When only one half is given, fall
        # back to the single-discipline behaviour (matches either column).
        if discipline_a and discipline_b:
            base = base.where(
                ((ClashResult.a_discipline == discipline_a) & (ClashResult.b_discipline == discipline_b))
                | ((ClashResult.a_discipline == discipline_b) & (ClashResult.b_discipline == discipline_a))
            )
        elif discipline_a:
            base = base.where((ClashResult.a_discipline == discipline_a) | (ClashResult.b_discipline == discipline_a))
        elif discipline_b:
            base = base.where((ClashResult.a_discipline == discipline_b) | (ClashResult.b_discipline == discipline_b))
        if severity:
            base = base.where(ClashResult.severity == severity)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        if order_by == "severity":
            ordered = base.order_by(
                self._severity_rank(),
                ClashResult.penetration_m.desc(),
            )
        else:  # default / legacy ordering
            ordered = base.order_by(
                ClashResult.clash_type,
                ClashResult.penetration_m.desc(),
            )
        rows = (await self.session.execute(ordered.offset(offset).limit(limit))).scalars().all()
        return list(rows), int(total)

    async def all_results(self, run_id: uuid.UUID) -> list[ClashResult]:
        """Every result row of a run (compare / carry-forward source)."""
        stmt = select(ClashResult).where(ClashResult.run_id == run_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_prior_completed_run(
        self,
        project_id: uuid.UUID,
        model_ids: list[str],
        exclude_run_id: uuid.UUID,
    ) -> ClashRun | None:
        """Most recent completed run of this project sharing a model.

        Used by carry-forward: scan completed runs newest-first and pick
        the first whose ``model_ids`` overlap the new run's models. The
        model overlap is checked in Python because ``model_ids`` is an
        untyped JSON/TEXT column (no portable JSON-contains across the
        SQLite-dev / Postgres-prod split). Defensive: returns ``None``
        rather than raising on any malformed legacy payload.
        """
        stmt = (
            select(ClashRun)
            .where(
                ClashRun.project_id == project_id,
                ClashRun.id != exclude_run_id,
                ClashRun.status == "completed",
            )
            .order_by(ClashRun.created_at.desc())
        )
        wanted = {str(m) for m in (model_ids or [])}
        for run in (await self.session.execute(stmt)).scalars().all():
            try:
                prior = {str(m) for m in (run.model_ids or [])}
            except TypeError:
                continue
            if wanted & prior:
                return run
        return None

    async def results_for_export(self, run_id: uuid.UUID, result_ids: list[uuid.UUID] | None) -> list[ClashResult]:
        """Resolve the export selection — explicit ids or all OPEN clashes."""
        stmt = select(ClashResult).where(ClashResult.run_id == run_id)
        if result_ids:
            stmt = stmt.where(ClashResult.id.in_(result_ids))
        else:
            stmt = stmt.where(ClashResult.status.in_(("new", "active", "reviewed")))
        return list((await self.session.execute(stmt)).scalars().all())

    # ── ClashCluster (Wave A4) ─────────────────────────────────────────

    def add_clusters(self, clusters: list[ClashCluster]) -> None:
        """Bulk-add cluster label rows for a run. Caller flushes."""
        if clusters:
            self.session.add_all(clusters)

    async def clear_clusters(self, run_id: uuid.UUID) -> None:
        """Wipe a run's persisted cluster labels (re-run replaces)."""
        await self.session.execute(delete(ClashCluster).where(ClashCluster.run_id == run_id))

    async def clusters_for_run(self, run_id: uuid.UUID) -> list[ClashCluster]:
        """Every persisted cluster label for a run, lowest id first."""
        stmt = select(ClashCluster).where(ClashCluster.run_id == run_id).order_by(ClashCluster.cluster_id.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    # ── ClashIssue (smart-issue identity across re-runs) ───────────────

    async def get_issue_by_signature(self, project_id: uuid.UUID, signature_hash: str) -> ClashIssue | None:
        """Find the smart issue for a given project + signature hash."""
        stmt = select(ClashIssue).where(
            ClashIssue.project_id == project_id,
            ClashIssue.signature_hash == signature_hash,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_issue(self, project_id: uuid.UUID, issue_id: uuid.UUID) -> ClashIssue | None:
        """Fetch a single smart issue (project-scoped — IDOR-safe)."""
        stmt = select(ClashIssue).where(
            ClashIssue.id == issue_id,
            ClashIssue.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def add_issue(self, issue: ClashIssue) -> None:
        """Stage a new smart issue for insert. Caller flushes."""
        self.session.add(issue)

    async def next_issue_seq(self, project_id: uuid.UUID) -> int:
        """Next monotonic 1-based counter for ``server_assigned_id``.

        Computed as ``COUNT(*) + 1`` over the project's issues. We don't
        need true gap-free monotonicity (an issue can never be deleted
        through the public API — only archived), and ``COUNT`` is index-
        backed via ``ix_clash_issue_project`` so this stays cheap.
        Concurrent run executions on the same project are serialized at
        the request level (one FastAPI worker per ``create_run`` call),
        so two issues never race for the same counter.
        """
        stmt = select(func.count()).select_from(ClashIssue).where(ClashIssue.project_id == project_id)
        n = (await self.session.execute(stmt)).scalar_one()
        return int(n or 0) + 1

    async def list_issues(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[ClashIssue, int]], int]:
        """List smart issues for a project + each row's member-count.

        Returns ``(rows, total)`` where ``rows`` is
        ``[(ClashIssue, member_count), ...]`` and ``member_count`` is the
        number of :class:`ClashResult` rows pointing at the issue. One
        round-trip per page — the count subquery is on the indexed
        ``issue_id`` column so even a large project stays cheap.
        """
        base = select(ClashIssue).where(ClashIssue.project_id == project_id)
        if status:
            base = base.where(ClashIssue.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        ordered = base.order_by(ClashIssue.created_at.desc(), ClashIssue.id.asc())
        rows = list((await self.session.execute(ordered.offset(offset).limit(limit))).scalars().all())
        # Member-count subquery per page (one round-trip).
        if rows:
            ids = [r.id for r in rows]
            cstmt = (
                select(ClashResult.issue_id, func.count())
                .where(ClashResult.issue_id.in_(ids))
                .group_by(ClashResult.issue_id)
            )
            counts = {iid: int(c) for iid, c in (await self.session.execute(cstmt)).all()}
        else:
            counts = {}
        return [(r, counts.get(r.id, 0)) for r in rows], int(total)

    async def signatures_present_in_run(self, run_id: uuid.UUID) -> set[str]:
        """Distinct ``signature_hash`` values present in a single run."""
        stmt = (
            select(ClashResult.signature_hash)
            .where(
                ClashResult.run_id == run_id,
                ClashResult.signature_hash != "",
            )
            .distinct()
        )
        return {str(s) for (s,) in (await self.session.execute(stmt)).all() if s}

    async def issues_for_project(self, project_id: uuid.UUID) -> list[ClashIssue]:
        """Every smart issue belonging to a project (no pagination)."""
        stmt = select(ClashIssue).where(ClashIssue.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def issues_by_signatures(self, project_id: uuid.UUID, signatures: list[str]) -> dict[str, ClashIssue]:
        """Fetch many issues at once, keyed by ``signature_hash``."""
        if not signatures:
            return {}
        stmt = select(ClashIssue).where(
            ClashIssue.project_id == project_id,
            ClashIssue.signature_hash.in_(signatures),
        )
        out: dict[str, ClashIssue] = {}
        for issue in (await self.session.execute(stmt)).scalars().all():
            out[str(issue.signature_hash)] = issue
        return out

    async def previous_run(
        self,
        project_id: uuid.UUID,
        exclude_run_id: uuid.UUID,
    ) -> ClashRun | None:
        """Most-recent completed run of a project, excluding ``exclude_run_id``.

        Used by ``finalize_run`` to diff "current vs last" without needing
        the caller to pass the prior run id explicitly. Ignores ``failed``
        runs so a single bad run doesn't break the chain.
        """
        stmt = (
            select(ClashRun)
            .where(
                ClashRun.project_id == project_id,
                ClashRun.id != exclude_run_id,
                ClashRun.status == "completed",
            )
            .order_by(ClashRun.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── ClashSuppression ───────────────────────────────────────────────

    async def get_suppression(self, project_id: uuid.UUID, signature_hash: str) -> ClashSuppression | None:
        """One per-project suppression row, or ``None``."""
        stmt = select(ClashSuppression).where(
            ClashSuppression.project_id == project_id,
            ClashSuppression.signature_hash == signature_hash,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def add_suppression(self, suppression: ClashSuppression) -> None:
        self.session.add(suppression)

    async def delete_suppression(self, suppression: ClashSuppression) -> None:
        await self.session.delete(suppression)
        await self.session.flush()

    async def suppressed_signatures_for_project(self, project_id: uuid.UUID) -> set[str]:
        """Set of suppressed ``signature_hash`` values for a project."""
        stmt = select(ClashSuppression.signature_hash).where(ClashSuppression.project_id == project_id)
        return {str(s) for (s,) in (await self.session.execute(stmt)).all() if s}

    async def get_issues_by_ids(self, project_id: uuid.UUID, issue_ids: list[uuid.UUID]) -> list[ClashIssue]:
        """Project-scoped fetch of many issues by id (IDOR-safe).

        Issues whose ``id`` isn't in the project are silently dropped so
        the caller sees only authorized rows — same defensive pattern the
        single-issue ``get_issue`` follows. Empty input → empty list.
        """
        if not issue_ids:
            return []
        stmt = select(ClashIssue).where(
            ClashIssue.project_id == project_id,
            ClashIssue.id.in_(issue_ids),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_suppressions_by_signatures(
        self, project_id: uuid.UUID, signatures: list[str]
    ) -> dict[str, ClashSuppression]:
        """Fetch many suppression rows at once, keyed by ``signature_hash``."""
        if not signatures:
            return {}
        stmt = select(ClashSuppression).where(
            ClashSuppression.project_id == project_id,
            ClashSuppression.signature_hash.in_(signatures),
        )
        out: dict[str, ClashSuppression] = {}
        for row in (await self.session.execute(stmt)).scalars().all():
            out[str(row.signature_hash)] = row
        return out
