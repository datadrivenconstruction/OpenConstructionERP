"""Dashboard rollup aggregation service.

Each ``compute_*`` function executes ONE query (or a small fixed number)
across all of the caller's accessible projects, replacing the per-project
``Promise.all`` fan-out the frontend used to do (50 projects = 50 HTTP
calls per widget). Money fields are returned as Decimal-as-string per
the architecture guide §10.

Imports of sibling-module models are done **inside** each function so the
dashboard module stays loadable even when an optional dependency module
(safety, clash, finance, ...) is disabled on a given install.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Numeric, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.partner_pack.scope import scope_project_query
from app.modules.projects.models import Project
from app.modules.users.models import User

logger = logging.getLogger(__name__)

# Canonical widget IDs the rollup endpoint understands. Mirrors
# ``DASHBOARD_WIDGETS`` (wave 2) in the frontend registry.
KNOWN_WIDGETS: frozenset[str] = frozenset(
    {
        # Wave-2 dashboard widgets (cross-project rollups on /dashboard surface).
        "boq_summary",
        "validation_score",
        "clash_health",
        "schedule_critical",
        "risk_top",
        "hse_scorecard",
        "procurement_pipeline",
        "budget_variance",
        "change_orders",
        "weather_site",
        # Project-detail widgets (W23 P0 - single-project rollups on
        # /projects/:id; each scoped to the requested project_id via the same
        # rollup endpoint). Replaces the per-widget useQuery fan-out that
        # used to cause 502 spikes on project-page load.
        "project_rfi_inbox",
        "project_change_orders_pulse",
        "project_daily_diary",
        "project_hse_incidents",
        "project_variations",
        "project_quality_ncr",
        "project_compliance_summary",
        "project_budget_burn",
    }
)


# ─── Access control ─────────────────────────────────────────────────────────


async def is_admin(session: AsyncSession, user_id: str) -> bool:
    """Return True when the caller has the admin role."""
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return False
    try:
        user = await session.get(User, uid)
    except Exception:  # noqa: BLE001 - defensive
        return False
    return user is not None and getattr(user, "role", "") == "admin"


async def accessible_projects(
    session: AsyncSession,
    user_id: str,
    *,
    requested_ids: list[uuid.UUID] | None = None,
) -> list[Project]:
    """Return Project rows the caller may see.

    Admins see all (non-archived). Regular users see only their own.
    When ``requested_ids`` is provided we silently drop ids that are
    not accessible - never raise 403, the parent router returns 404 /
    empty per the IDOR posture.
    """
    admin = await is_admin(session, user_id)
    stmt = select(Project).where(Project.status != "archived")
    # When a partner pack is active the whole workspace is scoped to that
    # pack's projects. This intentionally overrides admin-sees-all so the
    # rollup widgets match the (already scoped) projects page and dashboard
    # cards; a no-op when no pack is active.
    stmt = scope_project_query(stmt, Project)
    if not admin:
        try:
            uid = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            return []
        stmt = stmt.where(Project.owner_id == uid)
    if requested_ids:
        stmt = stmt.where(Project.id.in_(requested_ids))
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


# ─── Decimal helpers ────────────────────────────────────────────────────────


def _to_decimal(value: Any) -> Decimal:
    """Best-effort coercion to ``Decimal('0')`` on bad input."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value: Decimal) -> str:
    """Format a Decimal as a string with 2dp - JS-safe."""
    return f"{value.quantize(Decimal('0.01'))}"


# BOQ Position money/quantity columns are String(50) (legacy SQLite-era
# storage kept for migration compatibility). To aggregate them in SQL we
# guard the CAST with a numeric-shape regex so a malformed value degrades
# to 0 - mirroring ``_to_decimal`` - instead of aborting the statement.
# Uses the PostgreSQL ``~`` regex operator; the platform is
# PostgreSQL-only since v6.6.0 (tests included), so no dialect branch is
# needed.
_NUMERIC_SHAPE_RE = r"^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)$"


def _sql_decimal(col: Any) -> Any:
    """SQL expression: CAST ``col`` to NUMERIC, or 0 when not numeric-shaped."""
    return case((col.op("~")(_NUMERIC_SHAPE_RE), cast(col, Numeric)), else_=0)


# ─── Widget aggregators ─────────────────────────────────────────────────────


async def compute_boq_summary(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Sum BOQ totals + position health counts grouped by project.

    Includes ``active_boqs`` (status not in ``archived/closed/cancelled/
    rejected``) and a ``last_boq`` pointer so the KpiRibbon + lastBoq logic
    in DashboardPage can stop fanning out ``/v1/boq/boqs/?project_id=…``
    per project (v4.6.2 N+1 nuke 2026-05-24).
    """
    from app.modules.boq.models import BOQ, Position  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {
            "total_boqs": 0,
            "active_boqs": 0,
            "total_value_eur": "0.00",
            "by_currency": [],
            "multi_currency": False,
            "position_count": 0,
            "positions_missing_quantity": 0,
            "positions_zero_price": 0,
            "last_boq": None,
            "by_project": [],
        }

    # Per-project BOQ count + status + updated_at so we can pick the most-
    # recently-edited BOQ and count active vs inactive in one query.
    boq_meta_stmt = select(
        BOQ.id,
        BOQ.project_id,
        BOQ.name,
        BOQ.status,
        BOQ.updated_at,
    ).where(BOQ.project_id.in_(project_ids))
    boq_meta_rows = (await session.execute(boq_meta_stmt)).all()

    boq_count_by_project: dict[uuid.UUID, int] = defaultdict(int)
    inactive_statuses = {"archived", "closed", "cancelled", "rejected"}
    active_count = 0
    latest_boq: dict[str, Any] | None = None
    latest_ts: float = float("-inf")
    project_currency_by_id = {p.id: getattr(p, "currency", "EUR") or "EUR" for p in projects}
    project_name_by_id = {p.id: p.name for p in projects}

    for boq_id, project_id, boq_name, status_, updated_at in boq_meta_rows:
        boq_count_by_project[project_id] += 1
        if (status_ or "").lower() not in inactive_statuses:
            active_count += 1
        # ``updated_at`` may be a datetime (PG) or an ISO string (SQLite shim).
        ts: float | None = None
        if updated_at is None:
            ts = None
        elif isinstance(updated_at, datetime):
            ts = updated_at.replace(tzinfo=UTC if updated_at.tzinfo is None else updated_at.tzinfo).timestamp()
        else:
            try:
                ts = datetime.fromisoformat(str(updated_at)).timestamp()
            except ValueError:
                ts = None
        if ts is not None and ts > latest_ts:
            latest_ts = ts
            iso = updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at)
            latest_boq = {
                "id": str(boq_id),
                "name": boq_name or "-",
                "project_id": str(project_id),
                "project_name": project_name_by_id.get(project_id, "-"),
                "currency": project_currency_by_id.get(project_id, "EUR"),
                "status": status_,
                "updated_at": iso,
                # Position counts + totals filled in below from the position pass.
                "position_count": 0,
                "grand_total": "0.00",
            }

    # Per-project / per-BOQ position aggregates - computed in SQL (COUNT +
    # SUM ... GROUP BY) instead of pulling every Position row across every
    # project into Python. quantity/unit_rate/total are stored as String,
    # so each goes through the regex-guarded CAST in ``_sql_decimal``
    # (malformed value -> 0, exactly like ``_to_decimal``). The effective
    # row total mirrors the previous Python logic: prefer the stored total
    # unless it is NULL/empty/"0", else quantity * unit_rate.
    _qty = _sql_decimal(Position.quantity)
    _rate = _sql_decimal(Position.unit_rate)
    _row_total = case(
        (
            and_(Position.total.is_not(None), Position.total != "", Position.total != "0"),
            _sql_decimal(Position.total),
        ),
        else_=_qty * _rate,
    )
    pos_agg_stmt = (
        select(
            BOQ.id,
            BOQ.project_id,
            func.count(Position.id),
            func.sum(_row_total),
            func.sum(case((_qty == 0, 1), else_=0)),
            func.sum(case((_rate == 0, 1), else_=0)),
        )
        .join(BOQ, BOQ.id == Position.boq_id)
        .where(BOQ.project_id.in_(project_ids))
        .group_by(BOQ.id, BOQ.project_id)
    )
    pos_agg_rows = (await session.execute(pos_agg_stmt)).all()

    per_project: dict[uuid.UUID, dict[str, Any]] = defaultdict(
        lambda: {
            "total": Decimal("0"),
            "positions": 0,
            "missing_qty": 0,
            "zero_price": 0,
        },
    )
    per_boq: dict[uuid.UUID, dict[str, Any]] = {}
    for boq_id, project_id, positions, total_sum, missing_qty, zero_price in pos_agg_rows:
        total = _to_decimal(total_sum)
        bucket = per_project[project_id]
        bucket["positions"] += int(positions or 0)
        bucket["total"] += total
        bucket["missing_qty"] += int(missing_qty or 0)
        bucket["zero_price"] += int(zero_price or 0)
        per_boq[boq_id] = {"total": total, "positions": int(positions or 0)}

    by_project: list[dict[str, Any]] = []
    overall_total = Decimal("0")
    overall_positions = 0
    overall_missing = 0
    overall_zero_price = 0
    # Group BOQ value by the owning project's currency. There is no
    # cross-project rate table, so summing EUR + GBP + USD into one scalar
    # is financially meaningless - keep per-currency subtotals and flag
    # ``multi_currency`` (mirrors projects/router.py budget rollup).
    totals_by_currency_map: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for p in projects:
        bucket = per_project.get(
            p.id,
            {
                "total": Decimal("0"),
                "positions": 0,
                "missing_qty": 0,
                "zero_price": 0,
            },
        )
        currency = getattr(p, "currency", "EUR") or "EUR"
        by_project.append(
            {
                "project_id": str(p.id),
                "project_name": p.name,
                "boq_count": boq_count_by_project.get(p.id, 0),
                "total_value": _money(bucket["total"]),
                "currency": currency,
                "position_count": bucket["positions"],
                "positions_missing_quantity": bucket["missing_qty"],
                "positions_zero_price": bucket["zero_price"],
            },
        )
        totals_by_currency_map[currency] += bucket["total"]
        overall_total += bucket["total"]
        overall_positions += bucket["positions"]
        overall_missing += bucket["missing_qty"]
        overall_zero_price += bucket["zero_price"]

    by_currency = [
        {"currency": cur, "total_value": _money(total)} for cur, total in sorted(totals_by_currency_map.items())
    ]
    multi_currency = len(totals_by_currency_map) > 1

    if latest_boq is not None:
        try:
            latest_id = uuid.UUID(latest_boq["id"])
            stats = per_boq.get(latest_id)
            if stats is not None:
                latest_boq["position_count"] = stats["positions"]
                latest_boq["grand_total"] = _money(stats["total"])
        except (ValueError, KeyError):
            pass

    return {
        "total_boqs": sum(boq_count_by_project.values()),
        "active_boqs": active_count,
        # Legacy flat scalar kept for backward compatibility. When
        # ``multi_currency`` is true it mixes currencies and must NOT be
        # rendered as a single headline figure - use ``by_currency``.
        "total_value_eur": _money(overall_total),
        "by_currency": by_currency,
        "multi_currency": multi_currency,
        "position_count": overall_positions,
        "positions_missing_quantity": overall_missing,
        "positions_zero_price": overall_zero_price,
        "last_boq": latest_boq,
        "by_project": by_project,
    }


async def compute_validation_score(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Average of the latest-per-project ValidationReport.score."""
    from app.modules.validation.models import ValidationReport  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {
            "avg": None,
            "passed": 0,
            "warnings": 0,
            "errors": 0,
            "by_project": [],
        }

    # Pull the most-recent N reports per project set - small payload (no
    # ``results`` column) ordered DESC so the Python "first-seen = latest"
    # shortcut works.  Cap at 10 × project count (at most ~500 for a
    # large install) so a project with thousands of historical reports
    # doesn't drag in megabytes of rows just to find its latest score.
    _report_cap = max(len(project_ids) * 10, 100)
    stmt = (
        select(
            ValidationReport.id,
            ValidationReport.project_id,
            ValidationReport.status,
            ValidationReport.score,
            ValidationReport.created_at,
        )
        .where(ValidationReport.project_id.in_(project_ids))
        .order_by(ValidationReport.created_at.desc())
        .limit(_report_cap)
    )
    rows = (await session.execute(stmt)).all()

    counts_by_project: dict[uuid.UUID, dict[str, int]] = defaultdict(
        lambda: {"passed": 0, "warnings": 0, "errors": 0},
    )
    latest_score_by_project: dict[uuid.UUID, float | None] = {}

    for _rid, project_id, status_, score_s, _created in rows:
        bucket = counts_by_project[project_id]
        if status_ == "passed":
            bucket["passed"] += 1
        elif status_ == "warnings":
            bucket["warnings"] += 1
        elif status_ in {"errors", "failed"}:
            bucket["errors"] += 1
        # First time we see this project (rows ordered DESC) → latest.
        if project_id not in latest_score_by_project:
            try:
                latest_score_by_project[project_id] = float(score_s) if score_s is not None else None
            except (ValueError, TypeError):
                latest_score_by_project[project_id] = None

    by_project: list[dict[str, Any]] = []
    overall_passed = 0
    overall_warnings = 0
    overall_errors = 0
    scores_for_avg: list[float] = []

    for p in projects:
        bucket = counts_by_project.get(p.id, {"passed": 0, "warnings": 0, "errors": 0})
        score = latest_score_by_project.get(p.id)
        if score is not None:
            scores_for_avg.append(score)
        by_project.append(
            {
                "project_id": str(p.id),
                "project_name": p.name,
                "avg_score": score,
                "passed": bucket["passed"],
                "warnings": bucket["warnings"],
                "errors": bucket["errors"],
            },
        )
        overall_passed += bucket["passed"]
        overall_warnings += bucket["warnings"]
        overall_errors += bucket["errors"]

    avg = sum(scores_for_avg) / len(scores_for_avg) if scores_for_avg else None
    return {
        "avg": avg,
        "passed": overall_passed,
        "warnings": overall_warnings,
        "errors": overall_errors,
        "by_project": by_project,
    }


async def compute_clash_health(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Count clash issues by status + priority, grouped by project."""
    from app.modules.clash.models import ClashIssue  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {
            "total": 0,
            "open": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "pct_resolved": 0,
            "by_project": [],
        }

    # Grouped COUNT in SQL instead of pulling one row per clash issue into
    # Python - the result set is at most (projects x statuses x priorities)
    # rows regardless of how many issues exist.
    stmt = (
        select(
            ClashIssue.project_id,
            ClashIssue.status,
            ClashIssue.priority,
            func.count(ClashIssue.id),
        )
        .where(ClashIssue.project_id.in_(project_ids))
        .group_by(ClashIssue.project_id, ClashIssue.status, ClashIssue.priority)
    )
    rows = (await session.execute(stmt)).all()

    per_project: dict[uuid.UUID, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "open": 0, "high": 0, "medium": 0, "low": 0},
    )
    closed_statuses = {"resolved", "ignored", "archived"}
    for project_id, status_, priority, count_ in rows:
        n = int(count_ or 0)
        bucket = per_project[project_id]
        bucket["total"] += n
        if status_ not in closed_statuses:
            bucket["open"] += n
            if priority in {"high", "critical"}:
                bucket["high"] += n
            elif priority == "medium":
                bucket["medium"] += n
            elif priority == "low":
                bucket["low"] += n

    by_project: list[dict[str, Any]] = []
    total = 0
    total_open = 0
    total_high = 0
    total_medium = 0
    total_low = 0
    for p in projects:
        bucket = per_project.get(p.id, {"total": 0, "open": 0, "high": 0, "medium": 0, "low": 0})
        by_project.append(
            {
                "project_id": str(p.id),
                "project_name": p.name,
                **bucket,
            },
        )
        total += bucket["total"]
        total_open += bucket["open"]
        total_high += bucket["high"]
        total_medium += bucket["medium"]
        total_low += bucket["low"]

    resolved = total - total_open
    pct_resolved = round(100 * resolved / total) if total > 0 else 0
    return {
        "total": total,
        "open": total_open,
        "high": total_high,
        "medium": total_medium,
        "low": total_low,
        "pct_resolved": pct_resolved,
        "by_project": by_project,
    }


async def compute_schedule_critical(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Top-5 critical-path activities across the caller's schedules.

    Also returns ``total_schedules`` so the KpiRibbon's "Schedule Status"
    tile can stop fanning out ``/v1/schedule/schedules/?project_id=…`` per
    project (v4.6.2 N+1 nuke 2026-05-24).
    """
    from app.modules.schedule.models import Activity, Schedule  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"top": [], "total_schedules": 0}

    project_name_by_id = {p.id: p.name for p in projects}

    # Total schedules across the caller's projects - one COUNT query, NOT a
    # per-project fan-out.
    sched_count_stmt = select(func.count(Schedule.id)).where(
        Schedule.project_id.in_(project_ids),
    )
    total_schedules = int((await session.execute(sched_count_stmt)).scalar() or 0)

    # Cap at 1000 rows - the dashboard only ever shows the top-5 critical
    # activities. Without a limit, large schedules (5K+ activities per
    # project × 50 projects) pull megabytes of data into Python just to
    # sort and slice [:5]. Ordering by is_critical DESC puts flagged rows
    # first so the early cutoff still surfaces the most relevant ones.
    stmt = (
        select(
            Activity.id,
            Activity.name,
            Schedule.project_id,
            Activity.start_date,
            Activity.end_date,
            Activity.status,
            Activity.is_critical,
            Activity.total_float,
        )
        .join(Schedule, Schedule.id == Activity.schedule_id)
        .where(Schedule.project_id.in_(project_ids))
        .order_by(Activity.is_critical.desc())
        .limit(10000)
    )
    rows = (await session.execute(stmt)).all()

    if not rows:
        return {"top": [], "total_schedules": total_schedules}

    flagged = [r for r in rows if r[6] is True]
    pool = flagged if flagged else rows

    def _sort_key(r: Any) -> float:
        try:
            return datetime.fromisoformat(r[3]).timestamp() if r[3] else float("inf")
        except ValueError:
            return float("inf")

    top = sorted(pool, key=_sort_key)[:5]

    return {
        "total_schedules": total_schedules,
        "top": [
            {
                "id": str(r[0]),
                "name": r[1] or "-",
                "project_id": str(r[2]),
                "project_name": project_name_by_id.get(r[2], "-"),
                "start_date": r[3],
                "end_date": r[4],
                "status": r[5],
                "is_critical": bool(r[6]),
                "total_float": r[7],
            }
            for r in top
        ],
    }


async def compute_risk_top(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Top-5 risks across projects by probability × impact severity."""
    from app.modules.risk.models import RiskItem as Risk  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"top": []}

    project_name_by_id = {p.id: p.name for p in projects}

    stmt = select(
        Risk.id,
        Risk.project_id,
        Risk.title,
        Risk.probability,
        Risk.impact_severity,
        Risk.risk_score,
        Risk.status,
    ).where(Risk.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    # severity → numeric weight for ranking; matches the frontend's
    # rough "score = prob × impact" ordering.
    severity_weight = {
        "low": 1.0,
        "medium": 2.0,
        "high": 3.0,
        "critical": 4.0,
        "catastrophic": 5.0,
    }

    enriched: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        rid, project_id, title, prob_s, sev, score_s, status_ = r
        try:
            prob = float(prob_s) if prob_s is not None else 0.0
        except (ValueError, TypeError):
            prob = 0.0
        try:
            persisted_score = float(score_s) if score_s is not None else 0.0
        except (ValueError, TypeError):
            persisted_score = 0.0
        impact_weight = severity_weight.get(sev or "medium", 2.0)
        # Prefer the persisted ``risk_score`` (computed by the risk
        # module's own scoring service) when it's > 0; otherwise fall
        # back to a uniform prob × impact heuristic so risks without
        # a computed score still surface.
        rank = persisted_score if persisted_score > 0 else prob * impact_weight
        enriched.append(
            (
                rank,
                {
                    "id": str(rid),
                    "project_id": str(project_id),
                    "project_name": project_name_by_id.get(project_id, "-"),
                    "title": title,
                    "score": round(rank, 3),
                    "probability": prob,
                    "impact_severity": sev or "medium",
                    "status": status_,
                },
            ),
        )

    enriched.sort(key=lambda x: x[0], reverse=True)
    return {"top": [item for _, item in enriched[:5]]}


async def compute_hse_scorecard(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """HSE incident counts + days-since-last grouped by project."""
    from app.modules.safety.models import SafetyIncident  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {
            "total": 0,
            "last_30d": 0,
            "near_miss": 0,
            "recordables": 0,
            "days_since_last": None,
            "by_project": [],
        }

    stmt = select(
        SafetyIncident.project_id,
        SafetyIncident.incident_date,
        SafetyIncident.incident_type,
        SafetyIncident.severity,
        SafetyIncident.osha_recordable,
    ).where(SafetyIncident.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    now = datetime.now(UTC)
    cutoff_30d = now - timedelta(days=30)

    per_project: dict[uuid.UUID, dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "last_30d": 0,
            "near_miss": 0,
            "recordables": 0,
            "last_date": None,
        },
    )
    serious_severities = {"moderate", "major", "critical", "fatal"}

    for project_id, incident_date_s, itype, severity, osha in rows:
        bucket = per_project[project_id]
        bucket["total"] += 1
        # ``incident_date`` is ISO YYYY-MM-DD string per safety/models.py.
        incident_dt: datetime | None = None
        if incident_date_s:
            try:
                incident_dt = datetime.fromisoformat(incident_date_s).replace(
                    tzinfo=UTC,
                )
            except ValueError:
                incident_dt = None
        if incident_dt:
            if incident_dt >= cutoff_30d:
                bucket["last_30d"] += 1
            current_last = bucket["last_date"]
            if current_last is None or incident_dt > current_last:
                bucket["last_date"] = incident_dt
        if itype == "near_miss":
            bucket["near_miss"] += 1
        if osha or (severity and severity in serious_severities):
            bucket["recordables"] += 1

    by_project: list[dict[str, Any]] = []
    total = 0
    total_30d = 0
    total_near_miss = 0
    total_recordables = 0
    overall_last_date: datetime | None = None

    for p in projects:
        bucket = per_project.get(
            p.id,
            {
                "total": 0,
                "last_30d": 0,
                "near_miss": 0,
                "recordables": 0,
                "last_date": None,
            },
        )
        last_date: datetime | None = bucket["last_date"]
        days_since_last = (now - last_date).days if last_date is not None else None
        by_project.append(
            {
                "project_id": str(p.id),
                "project_name": p.name,
                "total": bucket["total"],
                "last_30d": bucket["last_30d"],
                "near_miss": bucket["near_miss"],
                "recordables": bucket["recordables"],
                "days_since_last": days_since_last,
            },
        )
        total += bucket["total"]
        total_30d += bucket["last_30d"]
        total_near_miss += bucket["near_miss"]
        total_recordables += bucket["recordables"]
        if last_date and (overall_last_date is None or last_date > overall_last_date):
            overall_last_date = last_date

    overall_days_since = (now - overall_last_date).days if overall_last_date is not None else None
    return {
        "total": total,
        "last_30d": total_30d,
        "near_miss": total_near_miss,
        "recordables": total_recordables,
        "days_since_last": overall_days_since,
        "by_project": by_project,
    }


async def compute_procurement_pipeline(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Counts of POs by lifecycle status across the caller's projects."""
    from app.modules.procurement.models import PurchaseOrder  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"rfqs_pending": 0, "pos_issued": 0, "pos_received": 0}

    stmt = (
        select(PurchaseOrder.status, func.count(PurchaseOrder.id))
        .where(PurchaseOrder.project_id.in_(project_ids))
        .group_by(PurchaseOrder.status)
    )
    rows = (await session.execute(stmt)).all()
    counts: dict[str, int] = {r[0]: r[1] for r in rows}

    pending_states = {"draft", "pending", "open"}
    issued_states = {"issued", "sent", "approved"}
    received_states = {"received", "closed", "completed"}

    return {
        "rfqs_pending": sum(counts.get(s, 0) for s in pending_states),
        "pos_issued": sum(counts.get(s, 0) for s in issued_states),
        "pos_received": sum(counts.get(s, 0) for s in received_states),
    }


async def compute_budget_variance(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Top 3 over-budget projects (revised_budget - actual)."""
    from app.modules.finance.models import ProjectBudget  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"over_budget_count": 0, "top_over": []}

    project_name_by_id = {p.id: p.name for p in projects}
    project_currency_by_id = {p.id: getattr(p, "currency", "EUR") or "EUR" for p in projects}

    stmt = select(
        ProjectBudget.project_id,
        ProjectBudget.currency_code,
        ProjectBudget.original_budget,
        ProjectBudget.revised_budget,
        ProjectBudget.actual,
    ).where(ProjectBudget.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    per_project: dict[uuid.UUID, dict[str, Any]] = defaultdict(
        lambda: {
            "planned": Decimal("0"),
            "actual": Decimal("0"),
            "currency": "",
        },
    )
    for project_id, currency, orig, rev, actual in rows:
        bucket = per_project[project_id]
        planned = _to_decimal(rev) if _to_decimal(rev) > 0 else _to_decimal(orig)
        bucket["planned"] += planned
        bucket["actual"] += _to_decimal(actual)
        # Use the first non-empty currency code we encounter; fall back
        # to the project's currency when the budget row didn't stamp one.
        if not bucket["currency"] and currency:
            bucket["currency"] = currency

    enriched: list[dict[str, Any]] = []
    for project_id, bucket in per_project.items():
        variance = bucket["actual"] - bucket["planned"]
        if variance <= 0:
            continue
        pct = int(round(100 * variance / bucket["planned"])) if bucket["planned"] > 0 else 0
        enriched.append(
            {
                "project_id": str(project_id),
                "project_name": project_name_by_id.get(project_id, "-"),
                "currency": bucket["currency"] or project_currency_by_id.get(project_id, "EUR"),
                "planned": _money(bucket["planned"]),
                "actual": _money(bucket["actual"]),
                "variance": _money(variance),
                "pct": pct,
            },
        )

    enriched.sort(key=lambda x: Decimal(x["variance"]), reverse=True)
    return {"over_budget_count": len(enriched), "top_over": enriched[:3]}


async def compute_change_orders(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Open change-order count + total cost impact + top 3 pending."""
    from app.modules.changeorders.models import ChangeOrder  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    project_name_by_id = {p.id: p.name for p in projects}
    fallback_currency = (getattr(projects[0], "currency", "EUR") if projects else "EUR") or "EUR"

    if not project_ids:
        return {
            "open_count": 0,
            "total_impact": "0.00",
            "currency": fallback_currency,
            "by_currency": [],
            "multi_currency": False,
            "top_pending": [],
        }

    # Each change-order row may carry its own currency; fall back to the
    # owning project's real currency (never a hardcoded "EUR") when the row
    # didn't stamp one.
    project_currency_by_id = {p.id: getattr(p, "currency", "") or "" for p in projects}

    closed_statuses = ("approved", "rejected", "closed")
    open_filter = ChangeOrder.status.not_in(closed_statuses)

    # Aggregate in SQL (COUNT + SUM ... GROUP BY) instead of pulling every
    # change-order row across every project into Python. ``cost_impact`` is
    # MoneyType (NUMERIC on PostgreSQL), so SUM is numeric-safe and comes
    # back as Decimal. Grouping by (project_id, currency) keeps the per-row
    # currency-resolution semantics: the row's own currency, else the
    # owning project's real currency, else the fallback.
    agg_stmt = (
        select(
            ChangeOrder.project_id,
            ChangeOrder.currency,
            func.count(ChangeOrder.id),
            func.sum(ChangeOrder.cost_impact),
        )
        .where(ChangeOrder.project_id.in_(project_ids), open_filter)
        .group_by(ChangeOrder.project_id, ChangeOrder.currency)
    )
    agg_rows = (await session.execute(agg_stmt)).all()

    # Money bug fix: ChangeOrder.cost_impact rows can be in different ISO
    # currencies (BRL, EUR, USD ...). There is no cross-project FX table
    # here, so blending them into one ``total_impact`` scalar and stamping
    # it with projects[0].currency is financially meaningless. We keep the
    # legacy ``total_impact`` scalar for back-compat (flagged by
    # ``multi_currency`` so the UI knows not to render it as a headline)
    # and add an FX-correct per-currency breakdown - same shape as
    # ``compute_boq_summary``.
    open_count = 0
    total_impact = Decimal("0")
    impact_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for project_id, row_currency, count_, impact_sum in agg_rows:
        open_count += int(count_ or 0)
        impact = _to_decimal(impact_sum)
        total_impact += impact
        # Use the row's own currency, else the project's real currency.
        currency = row_currency or project_currency_by_id.get(project_id, "") or fallback_currency
        impact_by_currency[currency] += impact

    by_currency = [
        {"currency": cur, "total_impact": _money(total)} for cur, total in sorted(impact_by_currency.items())
    ]
    multi_currency = len(impact_by_currency) > 1

    # Detail columns only for the 3 rows the widget actually renders.
    # (The previous code took the first 3 open rows in DB order - no
    # explicit ordering existed, so none is added here.)
    top_stmt = (
        select(
            ChangeOrder.id,
            ChangeOrder.project_id,
            ChangeOrder.code,
            ChangeOrder.title,
            ChangeOrder.status,
            ChangeOrder.cost_impact,
            ChangeOrder.currency,
        )
        .where(ChangeOrder.project_id.in_(project_ids), open_filter)
        .limit(3)
    )
    top_pending = (await session.execute(top_stmt)).all()
    return {
        "open_count": open_count,
        # Legacy flat scalar kept for backward compatibility. When
        # ``multi_currency`` is true it mixes ISO currencies and must NOT
        # be rendered as a single headline figure - use ``by_currency``.
        "total_impact": _money(total_impact),
        "currency": fallback_currency,
        "by_currency": by_currency,
        "multi_currency": multi_currency,
        "top_pending": [
            {
                "id": str(r[0]),
                "project_id": str(r[1]),
                "project_name": project_name_by_id.get(r[1], "-"),
                "code": r[2],
                "title": r[3],
                "status": r[4],
                "cost_impact": _money(_to_decimal(r[5])),
                # Per-row currency, real project currency, or last-resort
                # fallback - never a hardcoded "EUR".
                "currency": r[6] or project_currency_by_id.get(r[1], "") or fallback_currency,
            }
            for r in top_pending
        ],
    }


async def compute_weather_site(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Latest WeatherRecord for the first project that has geo coords + diary entry.

    No external HTTP fetch (the frontend already falls back to open-meteo
    client-side when our diary store is empty). This endpoint surfaces
    only the DB-cached weather row, so the rollup stays sync + fast.
    """
    from app.modules.daily_diary.models import WeatherRecord  # noqa: PLC0415

    # Pick the first project with any address coords for the header card.
    first_geo = next(
        (
            p
            for p in projects
            if isinstance(getattr(p, "address", None), dict)
            and p.address.get("lat") is not None
            and p.address.get("lng") is not None
        ),
        None,
    )
    if first_geo is None and projects:
        first_geo = projects[0]
    if first_geo is None:
        return {
            "project_id": None,
            "project_name": None,
            "city": None,
            "temperature_c": None,
            "conditions": None,
            "source": None,
        }

    stmt = (
        select(WeatherRecord)
        .where(WeatherRecord.project_id == first_geo.id)
        .order_by(WeatherRecord.captured_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()

    address: dict[str, Any] = getattr(first_geo, "address", None) or {}
    city = address.get("city") if isinstance(address, dict) else None

    if row is None:
        return {
            "project_id": str(first_geo.id),
            "project_name": first_geo.name,
            "city": city,
            "temperature_c": None,
            "conditions": None,
            "source": None,
        }

    return {
        "project_id": str(first_geo.id),
        "project_name": first_geo.name,
        "city": city,
        "temperature_c": (float(row.temperature_c) if row.temperature_c is not None else None),
        "conditions": row.conditions_text,
        "source": row.source,
    }


# ─── Project-detail widget aggregators (W23 P0) ─────────────────────────────
#
# These widgets sit on /projects/:id and used to do their own ``useQuery``
# in ProjectWidgets.tsx - one HTTP call per widget = ~8 parallel requests
# on every project-page load. The aggregators below mirror each widget's
# original endpoint contract closely enough that the frontend can swap to
# them without changing its render logic.
#
# Per-widget the function signature is ``(session, projects)`` - the
# rollup router scopes ``projects`` to the single requested project via
# the ``project_ids=<id>`` query param, so these aggregators just operate
# on whatever ``projects`` list they receive (1 element on /projects/:id,
# N elements if a caller ever calls them in cross-project mode).


async def compute_project_rfi_inbox(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Open RFIs for the given project(s), latest first, capped at 5.

    Mirrors ``GET /v1/rfi/?project_id=X&status=open&limit=5``. The widget
    expects an array shape, so we return ``{"items": [...]}`` and the
    frontend reads ``data.items``.
    """
    from app.modules.rfi.models import RFI  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"items": []}

    stmt = (
        select(
            RFI.id,
            RFI.rfi_number,
            RFI.subject,
            RFI.status,
            RFI.created_at,
            RFI.response_due_date,
        )
        .where(RFI.project_id.in_(project_ids))
        .where(RFI.status.in_(("draft", "open", "pending", "awaiting_response")))
        .order_by(RFI.created_at.desc())
        .limit(5)
    )
    rows = (await session.execute(stmt)).all()

    items: list[dict[str, Any]] = []
    for rid, number, subject, status_, created_at, due_date in rows:
        items.append(
            {
                "id": str(rid),
                "number": number,
                "subject": subject,
                "status": status_,
                "created_at": (
                    created_at.isoformat()
                    if isinstance(created_at, datetime)
                    else (str(created_at) if created_at else None)
                ),
                "due_date": due_date,
            },
        )
    return {"items": items}


async def compute_project_change_orders_pulse(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Open / pending / approved counts + approved value for change orders.

    Mirrors ``GET /v1/changeorders/summary/?project_id=X``. Money returned
    as Decimal-as-string.
    """
    from app.modules.changeorders.models import ChangeOrder  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    fallback_currency = (getattr(projects[0], "currency", "EUR") if projects else "EUR") or "EUR"

    if not project_ids:
        return {
            "open_count": 0,
            "pending_count": 0,
            "approved_count": 0,
            "total_value": "0.00",
            "approved_value": "0.00",
            "currency": fallback_currency,
        }

    stmt = select(
        ChangeOrder.status,
        ChangeOrder.cost_impact,
        ChangeOrder.currency,
    ).where(ChangeOrder.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    open_count = 0
    pending_count = 0
    approved_count = 0
    total_value = Decimal("0")
    approved_value = Decimal("0")
    closed_states = {"approved", "rejected", "closed"}
    pending_states = {"submitted", "in_review", "pending"}
    currency_seen = ""

    for status_, cost_impact, currency in rows:
        impact = _to_decimal(cost_impact)
        total_value += impact
        if currency and not currency_seen:
            currency_seen = currency
        if status_ not in closed_states:
            open_count += 1
        if status_ in pending_states:
            pending_count += 1
        if status_ == "approved":
            approved_count += 1
            approved_value += impact

    return {
        "open_count": open_count,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "total_value": _money(total_value),
        "approved_value": _money(approved_value),
        "currency": currency_seen or fallback_currency,
    }


async def compute_project_daily_diary(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Latest diary entry across the requested projects.

    Mirrors ``GET /v1/daily-diary/diaries/?project_id=X&limit=1``. The
    widget reads ``data[0]`` (array shape) so we return a single-element
    list to preserve the contract.
    """
    from app.modules.daily_diary.models import DailyDiary  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"items": []}

    stmt = (
        select(
            DailyDiary.id,
            DailyDiary.diary_date,
            DailyDiary.status,
            DailyDiary.weather_summary,
            DailyDiary.labour_count,
            DailyDiary.notes,
        )
        .where(DailyDiary.project_id.in_(project_ids))
        .order_by(DailyDiary.diary_date.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return {"items": []}

    diary_id, diary_date, status_, weather, labour, notes = row
    return {
        "items": [
            {
                "id": str(diary_id),
                "diary_date": diary_date,
                "status": status_,
                "weather_summary": weather,
                # ``manpower_total`` is the frontend's field name; the DB
                # stores it as ``labour_count``.
                "manpower_total": labour,
                "narrative": notes,
            },
        ],
    }


async def compute_project_hse_incidents(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Open HSE incident investigations for the project(s).

    Mirrors ``GET /v1/hse/investigations/?project_id=X&limit=20``. The
    widget computes severity counts client-side; we pre-aggregate to
    keep the payload tiny.

    Investigations key on ``incident_ref`` (a SafetyIncident UUID) rather
    than directly on ``project_id`` - same approach as
    ``HSEAdvancedRepository.list_for_project``. Failures (e.g. safety
    module disabled) degrade to zero counts, matching the dashboard
    module's general "don't break the page" posture.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from app.modules.hse_advanced.models import (  # noqa: PLC0415
        HSEIncidentInvestigation,
    )

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"items": [], "high": 0, "medium": 0, "low": 0, "total": 0}

    # Resolve incident_ids belonging to these projects through the safety
    # table without coupling to its ORM model.
    try:
        placeholders = ",".join(f":pid_{i}" for i in range(len(project_ids)))
        params = {f"pid_{i}": str(pid) for i, pid in enumerate(project_ids)}
        result = await session.execute(
            text(
                f"SELECT id, severity FROM oe_safety_incident WHERE project_id IN ({placeholders})",
            ),
            params,
        )
        incident_severity_by_id: dict[str, str | None] = {str(row[0]): row[1] for row in result.all()}
    except Exception:
        # safety module missing - keep the page rendering with empty data.
        return {"items": [], "high": 0, "medium": 0, "low": 0, "total": 0}

    if not incident_severity_by_id:
        return {"items": [], "high": 0, "medium": 0, "low": 0, "total": 0}

    stmt = select(
        HSEIncidentInvestigation.id,
        HSEIncidentInvestigation.incident_ref,
        HSEIncidentInvestigation.status,
    ).where(
        HSEIncidentInvestigation.incident_ref.in_(
            list(incident_severity_by_id.keys()),
        ),
    )
    rows = (await session.execute(stmt)).all()

    counts = {"high": 0, "medium": 0, "low": 0, "total": 0}
    items: list[dict[str, Any]] = []
    closed = {"closed", "archived"}
    for inv_id, ref, status_ in rows:
        if status_ in closed:
            continue
        counts["total"] += 1
        sev = (incident_severity_by_id.get(str(ref)) or "").lower()
        if "high" in sev or "crit" in sev or "fatal" in sev:
            counts["high"] += 1
        elif "med" in sev or "moderate" in sev:
            counts["medium"] += 1
        else:
            counts["low"] += 1
        items.append(
            {
                "id": str(inv_id),
                "status": status_,
                "severity": incident_severity_by_id.get(str(ref)),
            },
        )
    return {**counts, "items": items}


async def compute_project_variations(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Open variation requests + disputed value rollup.

    Mirrors ``GET /v1/variations/variation-requests/?project_id=X``.
    Frontend reads ``stats.open`` (counts) and ``stats.disputedValue`` -
    we pre-compute both. ``disputed`` is read from the row's metadata
    JSON (``metadata_.disputed``); pre-W23 the widget assumed a column
    of that name, but the model only carries it as a metadata flag.
    """
    from app.modules.variations.models import VariationRequest  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    fallback_currency = (getattr(projects[0], "currency", "EUR") if projects else "EUR") or "EUR"

    if not project_ids:
        return {
            "open": 0,
            "disputed_value": "0.00",
            "currency": fallback_currency,
            "items": [],
        }

    stmt = select(
        VariationRequest.id,
        VariationRequest.status,
        VariationRequest.estimated_cost_impact,
        VariationRequest.currency,
        VariationRequest.metadata_,
    ).where(VariationRequest.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    closed = {"closed", "rejected", "approved", "withdrawn"}
    open_count = 0
    disputed_value = Decimal("0")
    currency_seen = ""
    items: list[dict[str, Any]] = []
    for vr_id, status_, est_value, currency, meta in rows:
        if status_ not in closed:
            open_count += 1
        if currency and not currency_seen:
            currency_seen = currency
        disputed = bool(isinstance(meta, dict) and meta.get("disputed"))
        impact = _to_decimal(est_value)
        if disputed:
            disputed_value += impact
        items.append(
            {
                "id": str(vr_id),
                "status": status_,
                "estimated_value": _money(impact),
                "disputed": disputed,
            },
        )

    return {
        "open": open_count,
        "disputed_value": _money(disputed_value),
        "currency": currency_seen or fallback_currency,
        "items": items,
    }


async def compute_project_quality_ncr(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Open NCR counts + severity breakdown.

    Mirrors ``GET /v1/qms/ncrs/?project_id=X``. The widget computes
    counts client-side; we pre-aggregate.
    """
    from app.modules.qms.models import QMSNCR  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"open": 0, "major": 0, "minor": 0, "items": []}

    stmt = select(
        QMSNCR.id,
        QMSNCR.status,
        QMSNCR.severity,
    ).where(QMSNCR.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    closed = {"closed", "verified"}
    counts = {"open": 0, "major": 0, "minor": 0}
    items: list[dict[str, Any]] = []
    for ncr_id, status_, severity in rows:
        if status_ in closed:
            continue
        counts["open"] += 1
        sev = (severity or "").lower()
        if "maj" in sev or "crit" in sev or "high" in sev:
            counts["major"] += 1
        else:
            counts["minor"] += 1
        items.append(
            {"id": str(ncr_id), "status": status_, "severity": severity},
        )
    return {**counts, "items": items}


async def compute_project_compliance_summary(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Compliance-doc bucket counts: active / expiring / expired.

    Mirrors ``GET /v1/compliance-docs/?project_id=X``. The model already
    persists a derived ``status`` column so we just bucket by that, with
    a manual ``expires_at`` re-check (the persisted value can be stale
    until the next write).
    """
    from app.modules.compliance_docs.models import ComplianceDoc  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    if not project_ids:
        return {"active": 0, "expiring": 0, "expired": 0, "items": []}

    stmt = select(
        ComplianceDoc.id,
        ComplianceDoc.status,
        ComplianceDoc.expires_at,
        ComplianceDoc.doc_type,
    ).where(ComplianceDoc.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    now = datetime.now(UTC).date()
    in30 = now + timedelta(days=30)

    counts = {"active": 0, "expiring": 0, "expired": 0}
    items: list[dict[str, Any]] = []
    for doc_id, status_, expires_at, doc_type in rows:
        # Trust the persisted status when present, but re-derive on the
        # fly so the dashboard reflects today's date even if the row was
        # last written months ago.
        bucket: str
        try:
            if expires_at and expires_at < now:
                bucket = "expired"
            elif expires_at and expires_at < in30:
                bucket = "expiring"
            else:
                bucket = "active"
        except TypeError:
            bucket = status_ or "active"

        counts[bucket] = counts.get(bucket, 0) + 1
        items.append(
            {
                "id": str(doc_id),
                "status": status_,
                "expires_at": (expires_at.isoformat() if expires_at is not None else None),
                "doc_type": doc_type,
            },
        )
    return {**counts, "items": items}


async def compute_project_budget_burn(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, Any]:
    """Planned-vs-actual totals for the project budget.

    Mirrors ``GET /v1/costmodel/projects/X/5d/dashboard/`` at the level
    of detail the widget actually uses (totals + currency; the spark
    series is left empty because the same N+1 fan-out concerns apply to
    EVM snapshots - a dedicated time-series endpoint can light it up
    later without changing the contract here). Money fields are Decimal-
    as-string per the architecture guide §10.
    """
    from app.modules.finance.models import ProjectBudget  # noqa: PLC0415

    project_ids = [p.id for p in projects]
    fallback_currency = (getattr(projects[0], "currency", "EUR") if projects else "EUR") or "EUR"

    if not project_ids:
        return {
            "planned_total": "0.00",
            "actual_total": "0.00",
            "currency": fallback_currency,
            "series": [],
        }

    stmt = select(
        ProjectBudget.currency_code,
        ProjectBudget.original_budget,
        ProjectBudget.revised_budget,
        ProjectBudget.actual,
    ).where(ProjectBudget.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).all()

    planned = Decimal("0")
    actual = Decimal("0")
    currency_seen = ""
    for currency_code, orig, rev, actual_v in rows:
        rev_d = _to_decimal(rev)
        plan_line = rev_d if rev_d > 0 else _to_decimal(orig)
        planned += plan_line
        actual += _to_decimal(actual_v)
        if currency_code and not currency_seen:
            currency_seen = currency_code

    return {
        "planned_total": _money(planned),
        "actual_total": _money(actual),
        "currency": currency_seen or fallback_currency,
        # Time series is intentionally empty for v1 - see docstring.
        "series": [],
    }


# ─── Dispatch ───────────────────────────────────────────────────────────────


_COMPUTE_MAP: dict[str, Any] = {
    "boq_summary": compute_boq_summary,
    "validation_score": compute_validation_score,
    "clash_health": compute_clash_health,
    "schedule_critical": compute_schedule_critical,
    "risk_top": compute_risk_top,
    "hse_scorecard": compute_hse_scorecard,
    "procurement_pipeline": compute_procurement_pipeline,
    "budget_variance": compute_budget_variance,
    "change_orders": compute_change_orders,
    "weather_site": compute_weather_site,
    # Project-detail widgets (W23 P0).
    "project_rfi_inbox": compute_project_rfi_inbox,
    "project_change_orders_pulse": compute_project_change_orders_pulse,
    "project_daily_diary": compute_project_daily_diary,
    "project_hse_incidents": compute_project_hse_incidents,
    "project_variations": compute_project_variations,
    "project_quality_ncr": compute_project_quality_ncr,
    "project_compliance_summary": compute_project_compliance_summary,
    "project_budget_burn": compute_project_budget_burn,
}


async def compute_rollup(
    session: AsyncSession,
    projects: list[Project],
    widgets: list[str],
) -> dict[str, Any]:
    """Compute the requested widget payloads in one go.

    A failure inside a single widget aggregator is logged + that widget
    is dropped from the response - one disabled module (eg. ``oe_clash``
    removed on a slim install) must not break the rest of the dashboard.
    """
    result: dict[str, Any] = {}
    for widget_id in widgets:
        compute = _COMPUTE_MAP.get(widget_id)
        if compute is None:
            continue
        try:
            result[widget_id] = await compute(session, projects)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Dashboard widget %s aggregation failed: %s",
                widget_id,
                exc,
                exc_info=True,
            )
            # On PostgreSQL a failed statement aborts the whole transaction;
            # without rolling back, every later widget on the shared session
            # would die with InFailedSQLTransactionError and return nothing.
            # Roll back to a clean state so one missing optional table only
            # drops its own widget.
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            # Skip - frontend treats absence as "module not available".
            continue
    return result
