"""Project state collector — gathers project data from all modules.

Uses raw SQL via session.execute(text(...)) for speed and to avoid
circular imports with other module services. All queries are project-scoped
and run in parallel via asyncio.gather().
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── State dataclasses ──────────────────────────────────────────────────────


@dataclass
class BOQState:
    """Bill of Quantities domain state."""

    exists: bool = False
    total_items: int = 0
    items_with_zero_price: int = 0
    items_with_zero_quantity: int = 0
    sections_count: int = 0
    resources_linked: int = 0
    resources_total: int = 0
    last_modified: str | None = None
    validation_errors: int = 0
    export_ready: bool = False
    completion_pct: float = 0.0


@dataclass
class ScheduleState:
    """Schedule domain state."""

    exists: bool = False
    activities_count: int = 0
    linked_to_boq: bool = False
    has_critical_path: bool = False
    baseline_set: bool = False
    duration_days: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    completion_pct: float = 0.0


@dataclass
class TakeoffState:
    """Takeoff / CAD domain state."""

    files_uploaded: int = 0
    files_processed: int = 0
    formats: list[str] = field(default_factory=list)
    quantities_extracted: int = 0
    linked_to_boq: bool = False
    completion_pct: float = 0.0


@dataclass
class ValidationState:
    """Validation domain state."""

    last_run: str | None = None
    total_errors: int = 0
    critical_errors: int = 0
    warnings: int = 0
    passed_rules: int = 0
    total_rules: int = 0
    completion_pct: float = 0.0


@dataclass
class RiskState:
    """Risk register domain state."""

    register_exists: bool = False
    total_risks: int = 0
    high_severity_unmitigated: int = 0
    contingency_set: bool = False
    completion_pct: float = 0.0


@dataclass
class TenderingState:
    """Tendering domain state."""

    bid_packages: int = 0
    bids_received: int = 0
    bids_compared: bool = False
    completion_pct: float = 0.0


@dataclass
class DocumentsState:
    """Documents domain state."""

    total_files: int = 0
    categories_covered: list[str] = field(default_factory=list)
    completion_pct: float = 0.0


@dataclass
class ReportsState:
    """Reports domain state."""

    reports_generated: int = 0
    last_report: str | None = None
    completion_pct: float = 0.0


@dataclass
class CostModelState:
    """5D cost model domain state."""

    budget_set: bool = False
    baseline_exists: bool = False
    actuals_linked: bool = False
    earned_value_active: bool = False
    completion_pct: float = 0.0


@dataclass
class ProjectState:
    """Complete snapshot of a project's state across all modules."""

    project_id: str = ""
    project_type: str = ""
    project_name: str = ""
    region: str = ""
    standard: str = ""
    currency: str = ""
    created_at: str = ""
    collected_at: str = ""

    boq: BOQState = field(default_factory=BOQState)
    schedule: ScheduleState = field(default_factory=ScheduleState)
    takeoff: TakeoffState = field(default_factory=TakeoffState)
    validation: ValidationState = field(default_factory=ValidationState)
    risk: RiskState = field(default_factory=RiskState)
    tendering: TenderingState = field(default_factory=TenderingState)
    documents: DocumentsState = field(default_factory=DocumentsState)
    reports: ReportsState = field(default_factory=ReportsState)
    cost_model: CostModelState = field(default_factory=CostModelState)


# ── Collector ──────────────────────────────────────────────────────────────


async def _collect_project_info(
    session: AsyncSession,
    project_id: str,
) -> dict[str, Any]:
    """Fetch basic project info."""
    try:
        row = (
            await session.execute(
                text(
                    "SELECT name, region, classification_standard, currency, "
                    "project_type, created_at "
                    "FROM oe_projects_project WHERE id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()
        if row:
            return {
                "name": row[0] or "",
                "region": row[1] or "",
                "standard": row[2] or "",
                "currency": row[3] or "",
                "project_type": row[4] or "",
                "created_at": str(row[5]) if row[5] else "",
            }
    except Exception:
        logger.debug("Could not fetch project info for %s", project_id)
    return {
        "name": "",
        "region": "",
        "standard": "",
        "currency": "",
        "project_type": "",
        "created_at": "",
    }


async def _collect_boq(
    session: AsyncSession,
    project_id: str,
) -> BOQState:
    """Collect BOQ domain state."""
    state = BOQState()
    try:
        # Count BOQs and positions
        boq_rows = (
            await session.execute(
                text(
                    "SELECT b.id, b.updated_at FROM oe_boq_boq b "
                    "WHERE b.project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).fetchall()

        if not boq_rows:
            return state

        state.exists = True
        boq_ids = [str(r[0]) for r in boq_rows]

        # Find latest modification time
        timestamps = [str(r[1]) for r in boq_rows if r[1]]
        if timestamps:
            state.last_modified = max(timestamps)

        # Count positions across all BOQs
        if boq_ids:
            # Build a safe IN clause with bind parameters
            placeholders = ", ".join(f":bid{i}" for i in range(len(boq_ids)))
            params: dict[str, Any] = {f"bid{i}": bid for i, bid in enumerate(boq_ids)}

            pos_stats = (
                await session.execute(
                    text(
                        f"SELECT "
                        f"  COUNT(*) AS total, "
                        f"  SUM(CASE WHEN (unit_rate = '0' OR unit_rate = '0.00' OR unit_rate = '' OR unit_rate IS NULL) AND parent_id IS NOT NULL THEN 1 ELSE 0 END) AS zero_price, "
                        f"  SUM(CASE WHEN (quantity = '0' OR quantity = '0.00' OR quantity = '' OR quantity IS NULL) AND parent_id IS NOT NULL THEN 1 ELSE 0 END) AS zero_qty, "
                        f"  SUM(CASE WHEN parent_id IS NULL THEN 1 ELSE 0 END) AS sections, "
                        f"  SUM(CASE WHEN validation_status = 'errors' THEN 1 ELSE 0 END) AS val_errors "
                        f"FROM oe_boq_position WHERE boq_id IN ({placeholders})"
                    ),
                    params,
                )
            ).first()

            if pos_stats:
                state.total_items = pos_stats[0] or 0
                state.items_with_zero_price = pos_stats[1] or 0
                state.items_with_zero_quantity = pos_stats[2] or 0
                state.sections_count = pos_stats[3] or 0
                state.validation_errors = pos_stats[4] or 0

        # Completion percentage: items with valid prices / total items (excluding sections)
        leaf_items = state.total_items - state.sections_count
        if leaf_items > 0:
            items_ok = leaf_items - max(state.items_with_zero_price, state.items_with_zero_quantity)
            state.completion_pct = max(0.0, min(1.0, items_ok / leaf_items))
        elif state.sections_count > 0:
            state.completion_pct = 0.3  # Has structure but no items

        state.export_ready = (
            state.total_items > 0
            and state.items_with_zero_price == 0
            and state.items_with_zero_quantity == 0
        )

    except Exception:
        logger.debug("Could not collect BOQ state for %s", project_id, exc_info=True)
    return state


async def _collect_schedule(
    session: AsyncSession,
    project_id: str,
) -> ScheduleState:
    """Collect schedule domain state."""
    state = ScheduleState()
    try:
        sched_row = (
            await session.execute(
                text(
                    "SELECT id, start_date, end_date "
                    "FROM oe_schedule_schedule WHERE project_id = :pid LIMIT 1"
                ),
                {"pid": project_id},
            )
        ).first()

        if not sched_row:
            return state

        state.exists = True
        schedule_id = str(sched_row[0])
        state.start_date = sched_row[1]
        state.end_date = sched_row[2]

        # Count activities
        act_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*), "
                    "  SUM(CASE WHEN dependencies != '[]' AND dependencies IS NOT NULL THEN 1 ELSE 0 END) "
                    "FROM oe_schedule_activity WHERE schedule_id = :sid"
                ),
                {"sid": schedule_id},
            )
        ).first()

        if act_row:
            state.activities_count = act_row[0] or 0
            has_deps = (act_row[1] or 0) > 0
            state.has_critical_path = has_deps

        # Check baseline
        baseline_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM oe_schedule_baseline "
                    "WHERE schedule_id = :sid"
                ),
                {"sid": schedule_id},
            )
        ).first()
        state.baseline_set = bool(baseline_row and baseline_row[0] > 0)

        # Calculate duration
        if state.start_date and state.end_date:
            try:
                from datetime import date as dt_date

                sd = dt_date.fromisoformat(state.start_date[:10])
                ed = dt_date.fromisoformat(state.end_date[:10])
                state.duration_days = (ed - sd).days
            except (ValueError, TypeError):
                pass

        # Completion estimate
        if state.activities_count > 0:
            pct = 0.3  # base for existing schedule
            if state.has_critical_path:
                pct += 0.2
            if state.baseline_set:
                pct += 0.2
            if state.start_date and state.end_date:
                pct += 0.3
            state.completion_pct = min(1.0, pct)

    except Exception:
        logger.debug("Could not collect schedule state for %s", project_id, exc_info=True)
    return state


async def _collect_takeoff(
    session: AsyncSession,
    project_id: str,
) -> TakeoffState:
    """Collect takeoff / CAD domain state."""
    state = TakeoffState()
    try:
        doc_rows = (
            await session.execute(
                text(
                    "SELECT file_type, status FROM oe_takeoff_document "
                    "WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).fetchall()

        state.files_uploaded = len(doc_rows)
        if state.files_uploaded == 0:
            return state

        formats_set: set[str] = set()
        processed = 0
        for row in doc_rows:
            if row[0]:
                formats_set.add(row[0])
            if row[1] in ("processed", "completed", "done"):
                processed += 1

        state.files_processed = processed
        state.formats = sorted(formats_set)

        # Count measurements
        meas_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM oe_takeoff_measurement "
                    "WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()
        state.quantities_extracted = (meas_row[0] or 0) if meas_row else 0

        # Completion
        if state.files_uploaded > 0:
            pct = 0.3  # files uploaded
            if state.files_processed > 0:
                pct += 0.3 * min(1.0, state.files_processed / state.files_uploaded)
            if state.quantities_extracted > 0:
                pct += 0.4
            state.completion_pct = min(1.0, pct)

    except Exception:
        logger.debug("Could not collect takeoff state for %s", project_id, exc_info=True)
    return state


async def _collect_validation(
    session: AsyncSession,
    project_id: str,
) -> ValidationState:
    """Collect validation domain state."""
    state = ValidationState()
    try:
        # Get the latest validation report for this project
        report = (
            await session.execute(
                text(
                    "SELECT created_at, error_count, warning_count, "
                    "  passed_count, total_rules, status "
                    "FROM oe_validation_report "
                    "WHERE project_id = :pid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"pid": project_id},
            )
        ).first()

        if not report:
            return state

        state.last_run = str(report[0]) if report[0] else None
        state.total_errors = report[1] or 0
        state.critical_errors = report[1] or 0  # all errors are treated as critical
        state.warnings = report[2] or 0
        state.passed_rules = report[3] or 0
        state.total_rules = report[4] or 0

        # Completion: 1.0 if no critical errors, scaled by passed/total otherwise
        if state.total_rules > 0:
            if state.critical_errors == 0:
                state.completion_pct = 1.0
            else:
                state.completion_pct = max(
                    0.0,
                    min(0.9, state.passed_rules / state.total_rules),
                )
        elif state.last_run:
            state.completion_pct = 0.5  # ran but no rules counted

    except Exception:
        logger.debug("Could not collect validation state for %s", project_id, exc_info=True)
    return state


async def _collect_risk(
    session: AsyncSession,
    project_id: str,
) -> RiskState:
    """Collect risk register domain state."""
    state = RiskState()
    try:
        risk_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*), "
                    "  SUM(CASE WHEN impact_severity IN ('high', 'very_high', 'critical') "
                    "    AND (mitigation_strategy = '' OR mitigation_strategy IS NULL) "
                    "    THEN 1 ELSE 0 END), "
                    "  SUM(CASE WHEN contingency_plan != '' AND contingency_plan IS NOT NULL "
                    "    THEN 1 ELSE 0 END) "
                    "FROM oe_risk_register WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()

        if not risk_row or risk_row[0] == 0:
            return state

        state.register_exists = True
        state.total_risks = risk_row[0] or 0
        state.high_severity_unmitigated = risk_row[1] or 0
        state.contingency_set = (risk_row[2] or 0) > 0

        # Completion
        if state.total_risks > 0:
            pct = 0.4  # register exists
            mitigated = state.total_risks - state.high_severity_unmitigated
            pct += 0.4 * (mitigated / state.total_risks)
            if state.contingency_set:
                pct += 0.2
            state.completion_pct = min(1.0, pct)

    except Exception:
        logger.debug("Could not collect risk state for %s", project_id, exc_info=True)
    return state


async def _collect_tendering(
    session: AsyncSession,
    project_id: str,
) -> TenderingState:
    """Collect tendering domain state."""
    state = TenderingState()
    try:
        pkg_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM oe_tendering_package "
                    "WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()
        state.bid_packages = (pkg_row[0] or 0) if pkg_row else 0

        if state.bid_packages > 0:
            bid_row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM oe_tendering_bid b "
                        "JOIN oe_tendering_package p ON b.package_id = p.id "
                        "WHERE p.project_id = :pid"
                    ),
                    {"pid": project_id},
                )
            ).first()
            state.bids_received = (bid_row[0] or 0) if bid_row else 0
            state.bids_compared = state.bids_received >= 2

        # Completion
        if state.bid_packages > 0:
            pct = 0.3
            if state.bids_received > 0:
                pct += 0.4
            if state.bids_compared:
                pct += 0.3
            state.completion_pct = min(1.0, pct)

    except Exception:
        logger.debug("Could not collect tendering state for %s", project_id, exc_info=True)
    return state


async def _collect_documents(
    session: AsyncSession,
    project_id: str,
) -> DocumentsState:
    """Collect documents domain state."""
    state = DocumentsState()
    try:
        doc_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*), GROUP_CONCAT(DISTINCT category) "
                    "FROM oe_documents_document WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()

        if doc_row:
            state.total_files = doc_row[0] or 0
            if doc_row[1]:
                state.categories_covered = [
                    c.strip() for c in str(doc_row[1]).split(",") if c.strip()
                ]

        if state.total_files > 0:
            state.completion_pct = min(1.0, 0.3 + 0.1 * len(state.categories_covered))

    except Exception:
        logger.debug("Could not collect documents state for %s", project_id, exc_info=True)
    return state


async def _collect_reports(
    session: AsyncSession,
    project_id: str,
) -> ReportsState:
    """Collect reports domain state."""
    state = ReportsState()
    try:
        rep_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*), MAX(created_at) "
                    "FROM oe_reporting_generated WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()

        if rep_row:
            state.reports_generated = rep_row[0] or 0
            state.last_report = str(rep_row[1]) if rep_row[1] else None

        if state.reports_generated > 0:
            state.completion_pct = min(1.0, 0.5 + 0.1 * state.reports_generated)

    except Exception:
        logger.debug("Could not collect reports state for %s", project_id, exc_info=True)
    return state


async def _collect_cost_model(
    session: AsyncSession,
    project_id: str,
) -> CostModelState:
    """Collect 5D cost model domain state."""
    state = CostModelState()
    try:
        # Check budget lines
        budget_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM oe_costmodel_budget_line "
                    "WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()
        has_budget = bool(budget_row and budget_row[0] > 0)
        state.budget_set = has_budget

        # Check EVM snapshots
        snap_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*), "
                    "  SUM(CASE WHEN actual_cost != '0' AND actual_cost != '' THEN 1 ELSE 0 END), "
                    "  SUM(CASE WHEN earned_value != '0' AND earned_value != '' THEN 1 ELSE 0 END) "
                    "FROM oe_costmodel_snapshot WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()

        if snap_row and snap_row[0]:
            state.baseline_exists = snap_row[0] > 0
            state.actuals_linked = (snap_row[1] or 0) > 0
            state.earned_value_active = (snap_row[2] or 0) > 0

        # Completion
        pct = 0.0
        if state.budget_set:
            pct += 0.3
        if state.baseline_exists:
            pct += 0.3
        if state.actuals_linked:
            pct += 0.2
        if state.earned_value_active:
            pct += 0.2
        state.completion_pct = min(1.0, pct)

    except Exception:
        logger.debug("Could not collect cost model state for %s", project_id, exc_info=True)
    return state


# ── Main collector function ────────────────────────────────────────────────


async def collect_project_state(
    session: AsyncSession,
    project_id: str,
) -> ProjectState:
    """Collect complete project state across all modules in parallel.

    Args:
        session: Async database session.
        project_id: UUID of the project.

    Returns:
        ProjectState with all domain states populated.
    """
    now = datetime.utcnow().isoformat()

    # Run all collectors in parallel
    results = await asyncio.gather(
        _collect_project_info(session, project_id),
        _collect_boq(session, project_id),
        _collect_schedule(session, project_id),
        _collect_takeoff(session, project_id),
        _collect_validation(session, project_id),
        _collect_risk(session, project_id),
        _collect_tendering(session, project_id),
        _collect_documents(session, project_id),
        _collect_reports(session, project_id),
        _collect_cost_model(session, project_id),
        return_exceptions=True,
    )

    # Unpack results, replacing exceptions with defaults
    project_info = results[0] if not isinstance(results[0], Exception) else {}
    boq = results[1] if not isinstance(results[1], Exception) else BOQState()
    schedule = results[2] if not isinstance(results[2], Exception) else ScheduleState()
    takeoff = results[3] if not isinstance(results[3], Exception) else TakeoffState()
    validation = results[4] if not isinstance(results[4], Exception) else ValidationState()
    risk = results[5] if not isinstance(results[5], Exception) else RiskState()
    tendering = results[6] if not isinstance(results[6], Exception) else TenderingState()
    documents = results[7] if not isinstance(results[7], Exception) else DocumentsState()
    reports = results[8] if not isinstance(results[8], Exception) else ReportsState()
    cost_model = results[9] if not isinstance(results[9], Exception) else CostModelState()

    return ProjectState(
        project_id=project_id,
        project_type=project_info.get("project_type", ""),
        project_name=project_info.get("name", ""),
        region=project_info.get("region", ""),
        standard=project_info.get("standard", ""),
        currency=project_info.get("currency", ""),
        created_at=project_info.get("created_at", ""),
        collected_at=now,
        boq=boq,
        schedule=schedule,
        takeoff=takeoff,
        validation=validation,
        risk=risk,
        tendering=tendering,
        documents=documents,
        reports=reports,
        cost_model=cost_model,
    )
