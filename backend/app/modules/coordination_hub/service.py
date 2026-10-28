# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Read-only aggregator for the Coordination Hub dashboard.

The service issues lightweight per-category SELECT-COUNT statements (one
per data point) against the existing sibling-module tables. There is
NEVER a Python-side join, an ORM hydration of a list and a manual
``len()``, or an N+1 - every count is its own ``func.count()`` query.

Each sub-count is wrapped in :func:`_safe_count` so a missing table /
mid-migration deploy / dropped dependency on a smaller install never
takes the whole dashboard down. The contract is "honest zero + a
WARNING log line", not "500 + scary stack trace".

That contract covers the optional-module imports too. A module that was
never installed is the expected condition and stays at DEBUG; a module
that IS installed and failed is logged with its traceback through
:func:`_optional_module_unavailable`. A zero the operator cannot tell
apart from a real zero is not an honest zero.

A small in-memory dict caches the assembled dashboard payload per
project for ``_DASHBOARD_TTL_SECONDS`` so the polling UI does not slam
the count queries on every tick.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.coordination_hub.intl import normalise_trade
from app.modules.coordination_hub.models import (
    DEFAULT_THRESHOLDS,
    KNOWN_METRICS,
    CoordinationThreshold,
)
from app.modules.coordination_hub.schemas import (
    CANONICAL_TRADES,
    BCFActivityStats,
    ClashDelta,
    ClashStats,
    CoordinationDashboardResponse,
    CoordinationThresholdsResponse,
    FederationStats,
    RulePackStats,
    SmartViewStats,
    ThresholdAlert,
    ThresholdLevel,
    ThresholdRow,
    TimelineEvent,
    TimelineResponse,
    TradeMatrixCell,
    TradeMatrixResponse,
)

logger = logging.getLogger(__name__)

#: Seconds the dashboard payload stays cached per project before the
#: aggregator re-queries the counts. 30 s matches the polling cadence
#: the UI uses (React Query ``staleTime``); shorter and we'd race
#: ourselves on every tick, longer and the operator sees stale numbers.
_DASHBOARD_TTL_SECONDS = 30.0

#: Module-scoped cache. Keyed by ``project_id``; value is the tuple
#: ``(payload, monotonic_ts)``. Process-local - no cross-worker share -
#: which is fine because the cache is purely a request-rate dampener.
_DASHBOARD_CACHE: dict[uuid.UUID, tuple[CoordinationDashboardResponse, float]] = {}

#: Hard cap on the number of timeline events the aggregator returns. The
#: UI scrolls a vertical list; beyond ~50 the value of older events
#: drops off a cliff. Bigger windows are unioned + truncated server-side.
_TIMELINE_MAX_EVENTS = 50

#: Look-back window (in days) for the BCF activity rollup. Mirrors the
#: ``topics_*_30d`` schema field name; promoted to a named constant so a
#: future BCF tuning sprint can change the window without grepping for
#: literal ``30`` across the service.
_BCF_ACTIVITY_WINDOW_DAYS = 30


# ── Discipline normalisation ────────────────────────────────────────────────


def _normalise_trade(value: str | None) -> str:
    """Collapse a free-text discipline label to one of CANONICAL_TRADES.

    Thin wrapper over :func:`app.modules.coordination_hub.intl.normalise_trade`,
    which folds case and accents and recognises the common discipline
    labels in English, German, French, Spanish, Italian and Russian. The
    six canonical buckets the dashboard needs are unchanged; a BIM export
    labelled in any of those languages now resolves instead of falling to
    ``"other"``. Unknown labels still land on ``"other"`` so the matrix
    never silently drops a clash. The signature is kept so existing
    callers and tests are unaffected.
    """
    return normalise_trade(value)


# ── Defensive aggregation primitives ────────────────────────────────────────


async def _safe_rollback(session: AsyncSession) -> None:
    """Roll an aborted (read-only) statement back so the next one can run.

    On PostgreSQL a failed statement aborts the whole transaction; the
    sub-aggregators run sequentially on the shared session, so without a
    rollback one missing optional table would cascade
    ``InFailedSQLTransactionError`` into every later counter and silently
    zero the dashboard.
    """
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001
        pass


def _optional_module_unavailable(label: str, exc: BaseException) -> None:
    """Log a sibling-module import that did not resolve.

    The sub-aggregators import their source module inside a broad ``try`` so
    a smaller install (module never shipped) reports an empty section rather
    than 500-ing the dashboard. That broad catch also swallows a module that
    IS installed and blew up on import, which reaches the operator as a zero
    with nothing anywhere to explain it.

    Args:
        label: The sibling module being imported, used to identify the probe.
        exc: The exception the import raised.
    """
    if isinstance(exc, ImportError):
        # Designed, expected condition on a smaller install.
        logger.debug("coordination_hub: %s module not installed - reporting empty", label)
    else:
        logger.exception(
            "coordination_hub: %s import failed unexpectedly - reporting empty",
            label,
        )


async def _safe_count(
    session: AsyncSession,
    stmt: Any,
    *,
    label: str,
) -> int:
    """Execute ``stmt`` (a ``SELECT COUNT``); return ``0`` on any DB error.

    The sub-module's table may not exist on a stripped-down install (the
    coordination hub is OPT-IN for several BIM sub-modules). Catching
    here lets the rest of the dashboard answer truthfully.
    """
    try:
        result = await session.execute(stmt)
        value = result.scalar()
        return int(value or 0)
    except SQLAlchemyError as exc:
        logger.warning(
            "coordination_hub: safe-count failed for %s - returning 0 (%s)",
            label,
            exc.__class__.__name__,
        )
        await _safe_rollback(session)
        return 0
    except Exception:  # noqa: BLE001 - defensive: never 500 the dashboard
        logger.exception(
            "coordination_hub: unexpected error counting %s - returning 0",
            label,
        )
        await _safe_rollback(session)
        return 0


async def _safe_scalar(
    session: AsyncSession,
    stmt: Any,
    *,
    label: str,
) -> Any:
    """Same defensive wrapper for any scalar lookup (``MAX(ts)`` etc.)."""
    try:
        result = await session.execute(stmt)
        return result.scalar()
    except SQLAlchemyError as exc:
        logger.warning(
            "coordination_hub: safe-scalar failed for %s - returning None (%s)",
            label,
            exc.__class__.__name__,
        )
        await _safe_rollback(session)
        return None
    except Exception:  # noqa: BLE001
        logger.exception(
            "coordination_hub: unexpected error fetching %s - returning None",
            label,
        )
        await _safe_rollback(session)
        return None


async def _safe_list(
    session: AsyncSession,
    stmt: Any,
    *,
    label: str,
) -> list[Any]:
    """Same defensive wrapper for a list of rows."""
    try:
        result = await session.execute(stmt)
        return list(result.all())
    except SQLAlchemyError as exc:
        logger.warning(
            "coordination_hub: safe-list failed for %s - returning [] (%s)",
            label,
            exc.__class__.__name__,
        )
        await _safe_rollback(session)
        return []
    except Exception:  # noqa: BLE001
        logger.exception(
            "coordination_hub: unexpected error fetching %s - returning []",
            label,
        )
        await _safe_rollback(session)
        return []


# ── Core service ───────────────────────────────────────────────────────────


class CoordinationHubService:
    """Read-only aggregator over the BIM-coordination sibling modules.

    Construct one per request via the FastAPI session dependency. Holds
    the session by reference; issues only SELECTs (no flush, no commit,
    no event-bus emission).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Federation rollup ──────────────────────────────────────────────────

    async def _federation_stats(self, project_id: uuid.UUID) -> FederationStats:
        try:
            from app.modules.bim_hub.models import (
                BIMFederation,
                BIMFederationModel,
                BIMModel,
            )
        except Exception as exc:  # pragma: no cover - bim_hub always present today
            _optional_module_unavailable("bim_hub", exc)
            return FederationStats()

        count = await _safe_count(
            self.session,
            select(func.count(BIMFederation.id)).where(BIMFederation.project_id == project_id),
            label="federations",
        )

        # Member count joined to project - never trust the join row alone
        # because deleted federations cascade and there could be orphans
        # mid-migration.
        members_stmt = (
            select(func.count(BIMFederationModel.id))
            .join(
                BIMFederation,
                BIMFederation.id == BIMFederationModel.federation_id,
            )
            .where(BIMFederation.project_id == project_id)
        )
        members = await _safe_count(self.session, members_stmt, label="federation_members")

        elements_stmt = select(func.coalesce(func.sum(BIMModel.element_count), 0)).where(
            BIMModel.project_id == project_id
        )
        elements = await _safe_count(self.session, elements_stmt, label="bim_elements")

        return FederationStats(
            count=count,
            total_members=members,
            total_elements=elements,
        )

    # ── Clash rollup ────────────────────────────────────────────────────────

    async def _clash_stats(self, project_id: uuid.UUID) -> ClashStats:
        try:
            from app.modules.clash.models import (
                ClashResult,
                ClashRun,
            )
            from app.modules.clash.schemas import OPEN_STATUSES
        except Exception as exc:  # pragma: no cover
            _optional_module_unavailable("clash", exc)
            return ClashStats()

        base_join = (
            ClashRun,
            ClashResult.run_id == ClashRun.id,
        )

        open_q = (
            select(func.count(ClashResult.id))
            .join(*base_join)
            .where(
                and_(
                    ClashRun.project_id == project_id,
                    ClashResult.status.in_(OPEN_STATUSES),
                )
            )
        )
        resolved_q = (
            select(func.count(ClashResult.id))
            .join(*base_join)
            .where(
                and_(
                    ClashRun.project_id == project_id,
                    ClashResult.status.in_(("approved", "resolved")),
                )
            )
        )
        ignored_q = (
            select(func.count(ClashResult.id))
            .join(*base_join)
            .where(
                and_(
                    ClashRun.project_id == project_id,
                    ClashResult.status == "ignored",
                )
            )
        )

        open_count = await _safe_count(self.session, open_q, label="clash_open")
        resolved_count = await _safe_count(self.session, resolved_q, label="clash_resolved")
        ignored_count = await _safe_count(self.session, ignored_q, label="clash_ignored")

        last_run_at = await _safe_scalar(
            self.session,
            select(func.max(ClashRun.completed_at)).where(ClashRun.project_id == project_id),
            label="clash_last_run",
        )

        delta = await self._clash_delta(project_id)

        return ClashStats(
            open_count=open_count,
            resolved_count=resolved_count,
            ignored_count=ignored_count,
            delta_since_last_run=delta,
            last_run_at=last_run_at,
        )

    async def _clash_delta(self, project_id: uuid.UUID) -> ClashDelta:
        """Approximate run-to-run delta using ClashIssue lifecycle status.

        A ``ClashIssue`` flips ``new`` on first sighting, ``persisted`` on
        any subsequent sighting, ``resolved`` when the most-recent run
        does NOT include the signature, and ``ignored`` when manually
        suppressed. We treat:

            new          → ``delta.new``       (created this period)
            resolved     → ``delta.resolved``  (left this period)
            reopened     → derived heuristic: persisted issues whose
                           ``resolved_run_id`` is non-null (they came
                           back). Best-effort - the schema doesn't track
                           a true reopen count.

        The window is "since the latest run" - we don't filter by ts
        here because the lifecycle column is the canonical signal. When
        the issue table is missing or unreadable the delta is zeroed.
        """
        try:
            from app.modules.clash.models import ClashIssue
        except Exception as exc:
            _optional_module_unavailable("clash", exc)
            return ClashDelta()

        new_q = select(func.count(ClashIssue.id)).where(
            and_(
                ClashIssue.project_id == project_id,
                ClashIssue.status == "new",
            )
        )
        resolved_q = select(func.count(ClashIssue.id)).where(
            and_(
                ClashIssue.project_id == project_id,
                ClashIssue.status == "resolved",
            )
        )
        # A reopen is a persisted issue that previously hit a resolved
        # run (resolved_run_id is non-null). It's an honest under-count
        # - the schema doesn't have a dedicated reopen-counter - but
        # better than zero for the heat-map signal.
        reopened_q = select(func.count(ClashIssue.id)).where(
            and_(
                ClashIssue.project_id == project_id,
                ClashIssue.status == "persisted",
                ClashIssue.resolved_run_id.is_not(None),
            )
        )

        new_n = await _safe_count(self.session, new_q, label="delta_new")
        resolved_n = await _safe_count(self.session, resolved_q, label="delta_resolved")
        reopened_n = await _safe_count(self.session, reopened_q, label="delta_reopened")
        return ClashDelta(new=new_n, resolved=resolved_n, reopened=reopened_n)

    # ── Rule pack rollup ────────────────────────────────────────────────────

    async def _rule_pack_stats(self, project_id: uuid.UUID) -> RulePackStats:
        try:
            from app.modules.bim_requirements.models import (
                BIMRequirement,
                BIMRequirementSet,
            )
        except Exception as exc:
            _optional_module_unavailable("bim_requirements", exc)
            return RulePackStats()

        installed = await _safe_count(
            self.session,
            select(func.count(BIMRequirementSet.id)).where(BIMRequirementSet.project_id == project_id),
            label="rule_pack_installed",
        )
        # Active vs disabled requirement rows. These are CONFIGURATION
        # states (``is_active`` flag), NOT the result of running an
        # evaluation engine against a model: ``last_check_pass_count`` is
        # really "rules currently active" and ``last_check_fail_count`` is
        # "rules explicitly disabled". The UI relabels them honestly
        # ("active / disabled") and the health banner does NOT treat a
        # disabled rule as a failing check. A future real-evaluation hook
        # can populate true pass/fail counts without changing the wire
        # shape.
        active_q = (
            select(func.count(BIMRequirement.id))
            .join(
                BIMRequirementSet,
                BIMRequirementSet.id == BIMRequirement.requirement_set_id,
            )
            .where(
                and_(
                    BIMRequirementSet.project_id == project_id,
                    BIMRequirement.is_active.is_(True),
                )
            )
        )
        inactive_q = (
            select(func.count(BIMRequirement.id))
            .join(
                BIMRequirementSet,
                BIMRequirementSet.id == BIMRequirement.requirement_set_id,
            )
            .where(
                and_(
                    BIMRequirementSet.project_id == project_id,
                    BIMRequirement.is_active.is_(False),
                )
            )
        )
        last_at = await _safe_scalar(
            self.session,
            select(func.max(BIMRequirementSet.updated_at)).where(BIMRequirementSet.project_id == project_id),
            label="rule_pack_last_at",
        )
        return RulePackStats(
            installed_count=installed,
            last_check_pass_count=await _safe_count(self.session, active_q, label="rule_pack_pass"),
            last_check_fail_count=await _safe_count(self.session, inactive_q, label="rule_pack_fail"),
            last_check_at=last_at,
        )

    # ── Smart view rollup ───────────────────────────────────────────────────

    async def _smart_view_stats(self, project_id: uuid.UUID) -> SmartViewStats:
        try:
            from app.modules.smart_views.models import SmartView
        except Exception as exc:
            _optional_module_unavailable("smart_views", exc)
            return SmartViewStats()

        # Project-scoped views are addressed by ``scope_id == project_id``
        # and are a true per-project count. User-scoped ("personal")
        # views are owned by a user GLOBALLY and carry no project link,
        # so ``user_count`` is deliberately an ALL-PROJECTS figure - there
        # is no cheap user-project join to scope it. The UI must label it
        # "personal views (all projects)" rather than implying it is
        # project-scoped; this matches how coordination tools surface their
        # personal-view drawer (one global list across projects).
        project_count = await _safe_count(
            self.session,
            select(func.count(SmartView.id)).where(
                and_(
                    SmartView.scope_type == "project",
                    SmartView.scope_id == project_id,
                )
            ),
            label="smart_views_project",
        )
        user_count = await _safe_count(
            self.session,
            select(func.count(SmartView.id)).where(SmartView.scope_type == "user"),
            label="smart_views_user",
        )
        return SmartViewStats(user_count=user_count, project_count=project_count)

    # ── BCF activity rollup ─────────────────────────────────────────────────

    async def _bcf_activity_stats(self, project_id: uuid.UUID) -> BCFActivityStats:
        try:
            from app.modules.bcf.models import BCFTopic
        except Exception as exc:
            _optional_module_unavailable("bcf", exc)
            return BCFActivityStats()

        thirty_days_ago = datetime.now(UTC) - timedelta(days=_BCF_ACTIVITY_WINDOW_DAYS)
        # BCF tracks an authoring metadata.modified_date + a server
        # created_at. The hub treats Base.created_at as the canonical
        # "exported from OCERP" timestamp (the row was written on
        # export/import); BCF source files might have older mtimes.
        exported_q = select(func.count(BCFTopic.id)).where(
            and_(
                BCFTopic.project_id == project_id,
                BCFTopic.created_at >= thirty_days_ago,
            )
        )
        # We don't yet split BCF import vs export at the row level -
        # there is no ``direction`` column on ``BCFTopic``. ``imported``
        # is conservatively counted as topics whose ``creation_author``
        # is set + differs from ``created_by``; absent that we surface
        # the same number twice rather than fabricating a 0. The UI
        # treats this as a coarse activity-level signal anyway.
        imported_q = select(func.count(BCFTopic.id)).where(
            and_(
                BCFTopic.project_id == project_id,
                BCFTopic.created_at >= thirty_days_ago,
                BCFTopic.creation_author.is_not(None),
            )
        )
        last_export = await _safe_scalar(
            self.session,
            select(func.max(BCFTopic.created_at)).where(BCFTopic.project_id == project_id),
            label="bcf_last_export",
        )
        return BCFActivityStats(
            topics_exported_30d=await _safe_count(self.session, exported_q, label="bcf_exported"),
            topics_imported_30d=await _safe_count(self.session, imported_q, label="bcf_imported"),
            last_export_at=last_export,
        )

    # ── Cost impact ─────────────────────────────────────────────────────────

    async def _open_cost_impact_total(self, project_id: uuid.UUID) -> float:
        """Delegate to the clash_cost_impact service when available."""
        try:
            from app.modules.clash_cost_impact.service import (
                ClashCostImpactService,
            )
        except Exception as exc:
            _optional_module_unavailable("clash_cost_impact", exc)
            return 0.0
        try:
            svc = ClashCostImpactService(self.session)
            payload = await svc.rollup_for_project(project_id)
        except SQLAlchemyError as exc:
            logger.warning(
                "coordination_hub: cost-impact rollup failed (%s)",
                exc.__class__.__name__,
            )
            return 0.0
        except Exception:  # noqa: BLE001
            logger.exception("coordination_hub: cost-impact rollup error")
            return 0.0
        if not payload:
            return 0.0
        total = payload.get("total_open_impact", 0.0)
        try:
            return float(total)
        except (TypeError, ValueError):
            # Not user data: the rollup is an internal contract that owes us a
            # number. A non-numeric total means that contract broke, and the
            # dashboard would otherwise show a confident zero cost impact.
            logger.warning(
                "coordination_hub: cost-impact rollup returned a non-numeric total %r - returning 0",
                total,
            )
            return 0.0

    # ── Public surface ──────────────────────────────────────────────────────

    async def dashboard(
        self,
        project_id: uuid.UUID,
        *,
        currency: str,
        use_cache: bool = True,
    ) -> CoordinationDashboardResponse:
        """Build the full project-level coordination payload.

        ``currency`` comes from the owning project - we don't read it
        here so the router can return a 404 before the heavy aggregation
        runs.
        """
        if use_cache:
            cached = _DASHBOARD_CACHE.get(project_id)
            if cached is not None:
                payload, ts = cached
                if time.monotonic() - ts < _DASHBOARD_TTL_SECONDS:
                    return payload

        now = datetime.now(UTC)
        # Per-counter errors are already swallowed inside _safe_count; the
        # outer sub-aggregators only raise on truly unexpected failures.
        # Run them SEQUENTIALLY on the shared self.session: an AsyncSession is
        # not safe for concurrent use, and on PostgreSQL (the v6 default) a
        # concurrent fan-out would interleave statements on one connection and
        # one failing query would abort the shared transaction - turning the
        # rest of the dashboard into silent zeros. The per-counter _safe_*
        # helpers roll the session back on error so a missing optional table
        # cannot cascade to its neighbours.
        federations = await self._federation_stats(project_id)
        clashes = await self._clash_stats(project_id)
        rule_packs = await self._rule_pack_stats(project_id)
        smart_views = await self._smart_view_stats(project_id)
        bcf = await self._bcf_activity_stats(project_id)
        cost_total = await self._open_cost_impact_total(project_id)

        payload = CoordinationDashboardResponse(
            project_id=project_id,
            currency=currency,
            as_of=now,
            federations=federations,
            clashes=clashes,
            rule_packs=rule_packs,
            smart_views=smart_views,
            bcf_activity=bcf,
            open_cost_impact_total=cost_total,
        )
        if use_cache:
            _DASHBOARD_CACHE[project_id] = (payload, time.monotonic())
        return payload

    @staticmethod
    def invalidate_cache(project_id: uuid.UUID | None = None) -> None:
        """Drop the cache for one project (or every project when None)."""
        if project_id is None:
            _DASHBOARD_CACHE.clear()
        else:
            _DASHBOARD_CACHE.pop(project_id, None)

    # ── Trade matrix ────────────────────────────────────────────────────────

    async def trade_matrix(self, project_id: uuid.UUID, *, currency: str = "") -> TradeMatrixResponse:
        """6×6 discipline-pair heat-map of OPEN clashes for ``project_id``.

        Rows / cols come from :data:`CANONICAL_TRADES`; cells aggregate
        ``count`` (all statuses), ``open``, ``resolved`` and the summed
        open ``cost_impact`` (rework + labour) of that pair. A pair is
        normalised symmetrically (row index ≤ col index) so we never
        produce duplicate cells like (struct, arch) AND (arch, struct).

        The cost weighting reuses the :mod:`clash_cost_impact` kernel
        (same arithmetic the cost dashboard shows) so a "weight by money"
        toggle in the UI is honest end to end, not a fresh client guess.
        When the cost module is unavailable the cells still carry counts
        and ``cost_impact`` degrades to ``0`` - the matrix never 500s.
        """
        try:
            from app.modules.clash.models import ClashResult, ClashRun
            from app.modules.clash.schemas import OPEN_STATUSES
        except Exception as exc:
            _optional_module_unavailable("clash", exc)
            return TradeMatrixResponse(
                project_id=project_id,
                trades=list(CANONICAL_TRADES),
                cells=[],
                currency=currency,
            )

        stmt = (
            select(
                ClashResult.a_discipline,
                ClashResult.b_discipline,
                ClashResult.status,
                func.count(ClashResult.id),
            )
            .join(ClashRun, ClashRun.id == ClashResult.run_id)
            .where(ClashRun.project_id == project_id)
            .group_by(
                ClashResult.a_discipline,
                ClashResult.b_discipline,
                ClashResult.status,
            )
        )
        rows = await _safe_list(self.session, stmt, label="trade_matrix")
        if not rows:
            return TradeMatrixResponse(
                project_id=project_id,
                trades=list(CANONICAL_TRADES),
                cells=[],
                currency=currency,
            )

        # Pair-key → (count, open, resolved). The pair is sorted
        # alphabetically by canonical-trade name so (mep, struct) and
        # (struct, mep) collapse to the same cell.
        agg: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"count": 0, "open": 0, "resolved": 0})
        for a, b, status_, n in rows:
            row = _normalise_trade(a)
            col = _normalise_trade(b)
            if row > col:
                row, col = col, row
            cell = agg[(row, col)]
            n_int = int(n or 0)
            cell["count"] += n_int
            if status_ in OPEN_STATUSES:
                cell["open"] += n_int
            elif status_ in ("approved", "resolved"):
                cell["resolved"] += n_int

        # Cost weighting per canonical pair. Best-effort: a missing cost
        # module / priced-rework leaves every pair at Decimal("0").
        cost_by_pair = await self._cost_impact_by_canonical_pair(project_id)

        cells = [
            TradeMatrixCell(
                row=row,
                col=col,
                count=v["count"],
                open=v["open"],
                resolved=v["resolved"],
                cost_impact=cost_by_pair.get((row, col), Decimal("0")),
            )
            for (row, col), v in agg.items()
        ]
        # Sort by canonical-trade index so the UI grid renders
        # deterministically (snapshot-friendly).
        idx = {t: i for i, t in enumerate(CANONICAL_TRADES)}
        cells.sort(key=lambda c: (idx.get(c.row, 999), idx.get(c.col, 999)))
        total_cost = sum((c.cost_impact for c in cells), Decimal("0"))
        return TradeMatrixResponse(
            project_id=project_id,
            trades=list(CANONICAL_TRADES),
            cells=cells,
            currency=currency,
            total_cost_impact=total_cost,
        )

    async def _cost_impact_by_canonical_pair(self, project_id: uuid.UUID) -> dict[tuple[str, str], Decimal]:
        """Open cost-impact summed per canonical (row, col) trade pair.

        Reuses the :class:`ClashCostImpactService` per-clash arithmetic
        kernel so the money figure matches the cost dashboard exactly,
        then re-buckets each clash into the matrix's own 6-trade
        vocabulary (the cost service keeps mechanical / electrical /
        plumbing separate; the matrix folds all three into ``mep``).

        Returns an empty dict on any failure - the matrix degrades to a
        count-only view rather than 500ing. Reads BOQ positions ONCE for
        the whole project so we never N+1 over clashes.
        """
        try:
            from app.modules.clash.models import ClashResult, ClashRun
            from app.modules.clash.schemas import OPEN_STATUSES
            from app.modules.clash_cost_impact.service import (
                ClashCostImpactService,
            )
        except Exception as exc:
            _optional_module_unavailable("clash / clash_cost_impact", exc)
            return {}

        cost_svc = ClashCostImpactService(self.session)
        project = await cost_svc._load_project(project_id)  # noqa: SLF001
        if project is None:
            return {}

        # ``select(Entity)`` rows come back as 1-tuple ``Row`` objects from
        # ``.all()``; use ``.scalars()`` so we iterate the ORM instances
        # directly (a ``Row`` is not an ``isinstance`` of ``tuple``).
        try:
            result = await self.session.execute(
                select(ClashResult)
                .join(ClashRun, ClashRun.id == ClashResult.run_id)
                .where(
                    and_(
                        ClashRun.project_id == project_id,
                        ClashResult.status.in_(OPEN_STATUSES),
                    )
                )
            )
            open_clashes = list(result.scalars().all())
        except SQLAlchemyError as exc:
            logger.warning(
                "coordination_hub: cost-matrix clash load failed - returning an empty cost matrix (%s)",
                exc.__class__.__name__,
            )
            await _safe_rollback(self.session)
            return {}
        except Exception:  # noqa: BLE001
            logger.exception("coordination_hub: cost-matrix clash load failed")
            await _safe_rollback(self.session)
            return {}
        if not open_clashes:
            return {}

        try:
            positions = await cost_svc._positions_for_project(project_id)  # noqa: SLF001
        except SQLAlchemyError as exc:
            logger.warning(
                "coordination_hub: cost-matrix positions load failed - returning an empty cost matrix (%s)",
                exc.__class__.__name__,
            )
            await _safe_rollback(self.session)
            return {}
        except Exception:  # noqa: BLE001
            logger.exception("coordination_hub: cost-matrix positions load failed")
            await _safe_rollback(self.session)
            return {}

        out: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        skipped = 0
        for clash in open_clashes:
            try:
                affected = cost_svc._affected_positions(clash, positions)  # noqa: SLF001
                _, clash_total = cost_svc._compute_impact(clash, project, affected)  # noqa: SLF001
            except Exception:  # noqa: BLE001 - never let one bad row break the matrix
                # Every skipped clash is money missing from the matrix the
                # operator reads. Tally them and report once below rather
                # than emitting a log line per row.
                skipped += 1
                continue
            a = _normalise_trade(getattr(clash, "a_discipline", None))
            b = _normalise_trade(getattr(clash, "b_discipline", None))
            if a > b:
                a, b = b, a
            out[(a, b)] += clash_total
        if skipped:
            logger.warning(
                "coordination_hub: cost-matrix skipped %s of %s open clashes that failed to price - "
                "the matrix understates the cost impact",
                skipped,
                len(open_clashes),
            )
        return dict(out)

    # ── Timeline ────────────────────────────────────────────────────────────

    async def timeline(self, project_id: uuid.UUID, *, days: int = 30) -> TimelineResponse:
        """Activity stream - UNION of created-rows across sibling modules.

        We pull at most ``_TIMELINE_MAX_EVENTS`` per source then merge +
        truncate; this keeps each query bounded and lets a noisy source
        not starve a quieter one. Order is ``ts DESC``.
        """
        window_start = datetime.now(UTC) - timedelta(days=max(1, days))
        events: list[TimelineEvent] = []
        events.extend(await self._timeline_clash_runs(project_id, window_start))
        events.extend(await self._timeline_federations(project_id, window_start))
        events.extend(await self._timeline_rule_packs(project_id, window_start))
        events.extend(await self._timeline_bcf_topics(project_id, window_start))
        events.sort(
            key=lambda e: e.ts or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return TimelineResponse(
            project_id=project_id,
            events=events[:_TIMELINE_MAX_EVENTS],
        )

    async def _timeline_clash_runs(self, project_id: uuid.UUID, window_start: datetime) -> list[TimelineEvent]:
        try:
            from app.modules.clash.models import ClashRun
        except Exception as exc:
            _optional_module_unavailable("clash", exc)
            return []
        stmt = (
            select(
                ClashRun.id,
                ClashRun.name,
                ClashRun.created_at,
                ClashRun.created_by,
                ClashRun.total_clashes,
                ClashRun.status,
            )
            .where(
                and_(
                    ClashRun.project_id == project_id,
                    ClashRun.created_at >= window_start,
                )
            )
            .order_by(ClashRun.created_at.desc())
            .limit(_TIMELINE_MAX_EVENTS)
        )
        rows = await _safe_list(self.session, stmt, label="timeline_clash")
        out: list[TimelineEvent] = []
        for rid, name, ts, by, total, status_ in rows:
            completed = status_ == "completed"
            total_int = int(total or 0)
            status_label = status_ or "pending"
            summary = (
                f"Clash run '{name}' completed - {total_int} clashes"
                if completed
                else f"Clash run '{name}' - {status_label}"
            )
            out.append(
                TimelineEvent(
                    ts=ts,
                    type="clash_run",
                    params={
                        "name": name,
                        "total": total_int,
                        "status": status_label,
                        # Sub-type so the client picks the right template
                        # without re-deriving "completed" from status.
                        "kind": "completed" if completed else "pending",
                    },
                    summary=summary,
                    user_id=str(by) if by else None,
                    target=f"/clash?run={rid}",
                )
            )
        return out

    async def _timeline_federations(self, project_id: uuid.UUID, window_start: datetime) -> list[TimelineEvent]:
        try:
            from app.modules.bim_hub.models import BIMFederation
        except Exception as exc:
            _optional_module_unavailable("bim_hub", exc)
            return []
        stmt = (
            select(
                BIMFederation.id,
                BIMFederation.name,
                BIMFederation.created_at,
            )
            .where(
                and_(
                    BIMFederation.project_id == project_id,
                    BIMFederation.created_at >= window_start,
                )
            )
            .order_by(BIMFederation.created_at.desc())
            .limit(_TIMELINE_MAX_EVENTS)
        )
        rows = await _safe_list(self.session, stmt, label="timeline_federation")
        return [
            TimelineEvent(
                ts=ts,
                type="federation_created",
                params={"name": name},
                summary=f"Federation '{name}' created",
                user_id=None,
                target=f"/bim/federations?id={fid}",
            )
            for fid, name, ts in rows
        ]

    async def _timeline_rule_packs(self, project_id: uuid.UUID, window_start: datetime) -> list[TimelineEvent]:
        try:
            from app.modules.bim_requirements.models import BIMRequirementSet
        except Exception as exc:
            _optional_module_unavailable("bim_requirements", exc)
            return []
        stmt = (
            select(
                BIMRequirementSet.id,
                BIMRequirementSet.name,
                BIMRequirementSet.created_at,
                BIMRequirementSet.created_by,
            )
            .where(
                and_(
                    BIMRequirementSet.project_id == project_id,
                    BIMRequirementSet.created_at >= window_start,
                )
            )
            .order_by(BIMRequirementSet.created_at.desc())
            .limit(_TIMELINE_MAX_EVENTS)
        )
        rows = await _safe_list(self.session, stmt, label="timeline_rules")
        return [
            TimelineEvent(
                ts=ts,
                type="rule_pack_installed",
                params={"name": name},
                summary=f"Rule pack '{name}' installed",
                user_id=str(by) if by else None,
                target="/bim/rules?mode=requirements",
            )
            for _rid, name, ts, by in rows
        ]

    async def _timeline_bcf_topics(self, project_id: uuid.UUID, window_start: datetime) -> list[TimelineEvent]:
        try:
            from app.modules.bcf.models import BCFTopic
        except Exception as exc:
            _optional_module_unavailable("bcf", exc)
            return []
        stmt = (
            select(
                BCFTopic.id,
                BCFTopic.title,
                BCFTopic.created_at,
                BCFTopic.created_by,
                BCFTopic.topic_status,
            )
            .where(
                and_(
                    BCFTopic.project_id == project_id,
                    BCFTopic.created_at >= window_start,
                )
            )
            .order_by(BCFTopic.created_at.desc())
            .limit(_TIMELINE_MAX_EVENTS)
        )
        rows = await _safe_list(self.session, stmt, label="timeline_bcf")
        return [
            TimelineEvent(
                ts=ts,
                type="bcf_export",
                params={"name": title, "status": status_},
                summary=f"BCF topic '{title}' ({status_})",
                user_id=str(by) if by else None,
                target="/bcf",
            )
            for _tid, title, ts, by, status_ in rows
        ]

    # ── Threshold seeding / read / update ──────────────────────────────────

    async def _existing_thresholds(self, project_id: uuid.UUID) -> dict[str, CoordinationThreshold]:
        """Return ``{metric: row}`` for already-persisted thresholds."""
        stmt = select(CoordinationThreshold).where(CoordinationThreshold.project_id == project_id)
        try:
            result = await self.session.execute(stmt)
            rows = list(result.scalars().all())
        except SQLAlchemyError as exc:
            logger.warning(
                "coordination_hub: threshold read failed (%s)",
                exc.__class__.__name__,
            )
            return {}
        return {row.metric: row for row in rows}

    async def _seed_default_thresholds(
        self,
        project_id: uuid.UUID,
        existing: dict[str, CoordinationThreshold],
    ) -> dict[str, CoordinationThreshold]:
        """Insert any missing default row; idempotent + race-tolerant.

        On a unique-constraint collision (parallel first-read from two
        workers) we swallow the error and re-fetch - both writers wind
        up with the same canonical row set.
        """
        missing = [(m, w, e) for (m, w, e) in DEFAULT_THRESHOLDS if m not in existing]
        if not missing:
            return existing
        for metric, warn, error in missing:
            row = CoordinationThreshold(
                project_id=project_id,
                metric=metric,
                warn_value=warn,
                error_value=error,
                enabled=True,
            )
            self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            # Another worker beat us - re-read.
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.warning(
                "coordination_hub: threshold seed failed (%s); evaluation will fall back to ephemeral defaults",
                exc.__class__.__name__,
            )
            return existing
        return await self._existing_thresholds(project_id)

    async def get_or_seed_thresholds(
        self, project_id: uuid.UUID, *, allow_seed: bool = True
    ) -> list[CoordinationThreshold]:
        """Return the project's thresholds; seed defaults on first call.

        The seeding path is best-effort: if the DB rejects the writes
        (e.g. a read-only replica) we still return ephemeral default
        rows so the caller can render a working dashboard.

        ``allow_seed=False`` skips the DB insert entirely and falls
        through to ephemeral defaults - used when the caller only holds
        ``coordination.read`` so a VIEWER never silently triggers DB
        writes by polling the dashboard.
        """
        existing = await self._existing_thresholds(project_id)
        if allow_seed and len(existing) < len(DEFAULT_THRESHOLDS):
            existing = await self._seed_default_thresholds(project_id, existing)
        # If seeding still didn't land any row (read-only DB / patched
        # session), fall back to ephemeral defaults so evaluation never
        # 500s for the lack of persisted rows.
        if not existing:
            return [
                CoordinationThreshold(
                    project_id=project_id,
                    metric=m,
                    warn_value=w,
                    error_value=e,
                    enabled=True,
                )
                for (m, w, e) in DEFAULT_THRESHOLDS
            ]
        # Preserve canonical metric ordering for snapshot-friendly output.
        order = {m: i for i, (m, _w, _e) in enumerate(DEFAULT_THRESHOLDS)}
        return sorted(
            existing.values(),
            key=lambda r: order.get(r.metric, len(order)),
        )

    async def update_threshold(
        self,
        project_id: uuid.UUID,
        metric: str,
        *,
        warn_value: Decimal | None,
        error_value: Decimal | None,
        enabled: bool | None,
    ) -> CoordinationThreshold:
        """Patch one threshold; seed the default row first when missing."""
        if metric not in KNOWN_METRICS:
            raise ValueError(f"Unknown threshold metric '{metric}'")

        # Ensure the row exists before we update it.
        rows = await self.get_or_seed_thresholds(project_id)
        target: CoordinationThreshold | None = next((r for r in rows if r.metric == metric), None)
        if target is None or target.id is None:
            # Ephemeral fallback path - promote to a real row before edit.
            for m, w, e in DEFAULT_THRESHOLDS:
                if m == metric:
                    target = CoordinationThreshold(
                        project_id=project_id,
                        metric=m,
                        warn_value=w,
                        error_value=e,
                        enabled=True,
                    )
                    self.session.add(target)
                    break
        assert target is not None  # KNOWN_METRICS guarantees a default
        # Compute the post-patch values so we can sanity-check the pair
        # BEFORE touching the row. An inverted warn/error pair (warn >
        # error) breaks the evaluator's elif-cascade silently - the
        # error tier would never trigger because the warn comparison
        # would always be hit first. Reject explicitly with a 422-able
        # ValueError so the operator sees the mistake.
        new_warn = warn_value if warn_value is not None else target.warn_value
        new_error = error_value if error_value is not None else target.error_value
        if new_warn is not None and new_error is not None and new_warn > new_error:
            raise ValueError(
                f"warn_value must be less than or equal to error_value (got warn={new_warn}, error={new_error})"
            )
        if warn_value is not None:
            target.warn_value = warn_value
        if error_value is not None:
            target.error_value = error_value
        if enabled is not None:
            target.enabled = enabled
        await self.session.commit()
        await self.session.refresh(target)
        # Structured audit-style log line - threshold edits change the
        # project's alarm bar and should be traceable post-hoc without
        # diff-ing the DB.
        logger.info(
            "coordination_hub: threshold updated project=%s metric=%s warn=%s error=%s enabled=%s",
            project_id,
            metric,
            target.warn_value,
            target.error_value,
            target.enabled,
        )
        # Invalidate the dashboard cache so the new threshold takes
        # effect on the very next poll.
        self.invalidate_cache(project_id)
        return target

    # ── Threshold evaluation ───────────────────────────────────────────────

    async def _open_clashes_total(self, project_id: uuid.UUID) -> int:
        try:
            from app.modules.clash.models import ClashResult, ClashRun
            from app.modules.clash.schemas import OPEN_STATUSES
        except Exception as exc:
            _optional_module_unavailable("clash", exc)
            return 0
        stmt = (
            select(func.count(ClashResult.id))
            .join(ClashRun, ClashRun.id == ClashResult.run_id)
            .where(
                and_(
                    ClashRun.project_id == project_id,
                    ClashResult.status.in_(OPEN_STATUSES),
                )
            )
        )
        return await _safe_count(self.session, stmt, label="th_open_total")

    async def _high_severity_open_clashes(self, project_id: uuid.UUID) -> int:
        try:
            from app.modules.clash.models import ClashResult, ClashRun
            from app.modules.clash.schemas import OPEN_STATUSES
        except Exception as exc:
            _optional_module_unavailable("clash", exc)
            return 0
        stmt = (
            select(func.count(ClashResult.id))
            .join(ClashRun, ClashRun.id == ClashResult.run_id)
            .where(
                and_(
                    ClashRun.project_id == project_id,
                    ClashResult.status.in_(OPEN_STATUSES),
                    ClashResult.severity.in_(("critical", "high")),
                )
            )
        )
        return await _safe_count(self.session, stmt, label="th_high_sev")

    async def _project_budget_decimal(self, project_id: uuid.UUID) -> Decimal | None:
        """Resolve the project's budget; ``None`` when not set.

        ``Project.budget_estimate`` is stored as a string for legacy
        currency-formatting reasons; we Decimal-parse defensively.
        """
        try:
            from app.modules.projects.models import Project
        except Exception as exc:
            _optional_module_unavailable("projects", exc)
            return None
        stmt = select(Project.budget_estimate).where(Project.id == project_id)
        raw = await _safe_scalar(self.session, stmt, label="project_budget")
        if not raw:
            return None
        try:
            value = Decimal(str(raw).strip().replace(",", ""))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return value if value > 0 else None

    async def _cost_impact_pct_of_budget(self, project_id: uuid.UUID) -> Decimal:
        budget = await self._project_budget_decimal(project_id)
        if budget is None:
            return Decimal("0")
        total = await self._open_cost_impact_total(project_id)
        try:
            total_dec = Decimal(str(total))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")
        if total_dec <= 0:
            return Decimal("0")
        return (total_dec / budget * Decimal("100")).quantize(Decimal("0.0001"))

    async def _model_age_days_max(self, project_id: uuid.UUID) -> Decimal:
        """Days since the most-recent BIM model upload for this project.

        Returns ``Decimal('99999')`` when no model has ever been uploaded
        so the alarm fires loudly on an empty project - coordination
        without any model is the strongest possible signal.
        """
        try:
            from app.modules.bim_hub.models import BIMModel
        except Exception as exc:
            _optional_module_unavailable("bim_hub", exc)
            return Decimal("0")
        stmt = select(func.max(BIMModel.created_at)).where(BIMModel.project_id == project_id)
        last = await _safe_scalar(self.session, stmt, label="model_age_last")
        if last is None:
            return Decimal("99999")
        # SQLite gives a naive datetime; assume UTC so the math is sane.
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - last
        return Decimal(str(max(0, delta.days)))

    async def evaluate_thresholds(
        self, project_id: uuid.UUID, *, allow_seed: bool = True
    ) -> CoordinationThresholdsResponse:
        """Compute current metric values + tag each row warn / error / ok.

        ``allow_seed=False`` lets read-only callers (VIEWER role hitting
        the GET endpoint) get a working evaluation without triggering
        the default-threshold DB seed - that write is reserved for
        callers holding ``coordination.write``.
        """
        rows = await self.get_or_seed_thresholds(project_id, allow_seed=allow_seed)

        # Compute every metric once so we never run an N×N query.
        open_total = Decimal(str(await self._open_clashes_total(project_id)))
        high_sev = Decimal(str(await self._high_severity_open_clashes(project_id)))
        pct_budget = await self._cost_impact_pct_of_budget(project_id)
        model_age = await self._model_age_days_max(project_id)
        metric_values: dict[str, Decimal] = {
            "open_clashes_total": open_total,
            "high_severity_clashes": high_sev,
            "open_cost_impact_pct_of_budget": pct_budget,
            "model_age_days_max": model_age,
        }

        out_rows: list[ThresholdRow] = []
        alerts: list[ThresholdAlert] = []
        for row in rows:
            current = metric_values.get(row.metric, Decimal("0"))
            level: ThresholdLevel
            threshold: Decimal
            if not row.enabled:
                level = "ok"
                threshold = row.warn_value
                message = "Threshold disabled."
            elif current >= row.error_value and row.error_value > 0:
                level = "error"
                threshold = row.error_value
                message = f"{row.metric} reached {current} (error ≥ {row.error_value})"
            elif current >= row.warn_value and row.warn_value > 0:
                level = "warn"
                threshold = row.warn_value
                message = f"{row.metric} reached {current} (warn ≥ {row.warn_value})"
            else:
                level = "ok"
                threshold = row.warn_value
                message = ""
            out_rows.append(
                ThresholdRow(
                    metric=row.metric,
                    warn_value=row.warn_value,
                    error_value=row.error_value,
                    enabled=row.enabled,
                    current_value=current,
                    level=level,
                    message=message,
                )
            )
            if level in ("warn", "error"):
                alerts.append(
                    ThresholdAlert(
                        metric=row.metric,
                        current_value=current,
                        threshold_value=threshold,
                        level=level,
                        message=message,
                    )
                )
        # Sort alerts: error first, then warn - most-urgent at the top.
        alerts.sort(key=lambda a: (0 if a.level == "error" else 1, a.metric))
        return CoordinationThresholdsResponse(
            project_id=project_id,
            thresholds=out_rows,
            alerts=alerts,
        )

    # ── Snapshot export ────────────────────────────────────────────────────

    async def export_snapshot_csv(self, project_id: uuid.UUID, *, currency: str) -> str:
        """Render the project's coordination snapshot as a single CSV string.

        One file a coordinator can attach to meeting minutes: the headline
        KPIs, the threshold-alert status, and the per-discipline-pair
        breakdown with cost weighting. Built off the SAME aggregator the
        dashboard renders (no fresh, divergent computation) and never
        cached so an export always reflects live numbers.

        The CSV uses a leading ``section`` column so the three logical
        blocks (kpi / alert / trade_pair) stay one parseable file - Excel
        and pandas both read it back without per-block re-splitting.
        """
        import csv
        import io

        # Bypass the dashboard TTL cache so an export is always fresh - a
        # coordinator clicking Export right after a clash run must not get
        # a 30s-stale snapshot stamped onto the meeting record.
        dashboard = await self.dashboard(project_id, currency=currency, use_cache=False)
        matrix = await self.trade_matrix(project_id, currency=currency)
        thresholds = await self.evaluate_thresholds(project_id, allow_seed=False)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["section", "key", "value", "detail", "currency"])

        # Block 1 - headline KPIs.
        cur = dashboard.currency or currency or ""
        writer.writerow(["kpi", "as_of", dashboard.as_of.isoformat(), "", ""])
        writer.writerow(["kpi", "open_clashes", dashboard.clashes.open_count, "", ""])
        writer.writerow(["kpi", "resolved_clashes", dashboard.clashes.resolved_count, "", ""])
        writer.writerow(["kpi", "ignored_clashes", dashboard.clashes.ignored_count, "", ""])
        writer.writerow(
            [
                "kpi",
                "open_cost_impact_total",
                format(dashboard.open_cost_impact_total, "f"),
                "",
                cur,
            ]
        )
        writer.writerow(["kpi", "federations", dashboard.federations.count, "", ""])
        writer.writerow(["kpi", "rule_packs_installed", dashboard.rule_packs.installed_count, "", ""])
        writer.writerow(["kpi", "bcf_topics_30d", dashboard.bcf_activity.topics_exported_30d, "", ""])

        # Block 2 - threshold alerts (every metric, with its current level).
        for tr in thresholds.thresholds:
            writer.writerow(
                [
                    "alert",
                    tr.metric,
                    format(tr.current_value, "f"),
                    f"{tr.level} (warn>={format(tr.warn_value, 'f')}, "
                    f"error>={format(tr.error_value, 'f')}, "
                    f"enabled={tr.enabled})",
                    "",
                ]
            )

        # Block 3 - per-discipline-pair breakdown with cost weighting.
        for cell in matrix.cells:
            # Skip empty pairs so the export is a signal, not a 36-row grid.
            if cell.count == 0 and cell.cost_impact == 0:
                continue
            writer.writerow(
                [
                    "trade_pair",
                    f"{cell.row} x {cell.col}",
                    cell.open,
                    f"total={cell.count}, resolved={cell.resolved}, cost_impact={format(cell.cost_impact, 'f')}",
                    matrix.currency or cur,
                ]
            )

        return buf.getvalue()
