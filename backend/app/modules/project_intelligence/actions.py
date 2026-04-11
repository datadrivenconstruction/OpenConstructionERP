"""Action executor — triggers operations in other modules.

Each action_id maps to a definition describing what it does,
which module it targets, and whether it requires confirmation.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ActionDefinition:
    """Defines an executable action."""

    id: str
    label: str
    description: str
    icon: str
    requires_confirmation: bool = False
    confirmation_message: str = ""
    target_module: str | None = None
    target_route: str | None = None
    navigate_to: str | None = None
    params_from_project: list[str] | None = None


@dataclass
class ActionResult:
    """Result of executing an action."""

    success: bool
    message: str
    redirect_url: str | None = None
    data: dict[str, Any] | None = None


# ── Action registry ───────────────────────────────────────────────────────

ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "action_create_boq_ai": ActionDefinition(
        id="action_create_boq_ai",
        label="Generate BOQ with AI",
        description="Use AI estimation to create a complete BOQ from project description",
        icon="sparkles",
        requires_confirmation=False,
        target_module="ai",
        target_route="POST /api/v1/ai/estimate/from-description",
        params_from_project=["project_id", "project_type", "region"],
    ),
    "action_run_validation": ActionDefinition(
        id="action_run_validation",
        label="Run Validation Now",
        description="Check validation rules against this project's BOQ",
        icon="shield-check",
        requires_confirmation=False,
        target_module="validation",
    ),
    "action_generate_schedule": ActionDefinition(
        id="action_generate_schedule",
        label="Auto-Generate Schedule from BOQ",
        description="Create Gantt activities from BOQ sections with cost-proportional durations",
        icon="calendar-plus",
        requires_confirmation=True,
        confirmation_message="This will create a new schedule. Existing schedule (if any) will not be changed.",
        target_module="schedule",
    ),
    "action_match_cwicr_prices": ActionDefinition(
        id="action_match_cwicr_prices",
        label="Match Prices from CWICR Database",
        description="Automatically match zero-price items against the CWICR cost database",
        icon="database",
        requires_confirmation=False,
        target_module="catalog",
    ),
    "action_open_validation": ActionDefinition(
        id="action_open_validation",
        label="View Validation Errors",
        description="Open the Validation module to see and fix errors",
        icon="alert-circle",
        requires_confirmation=False,
        navigate_to="/validation",
    ),
    "action_link_schedule_boq": ActionDefinition(
        id="action_link_schedule_boq",
        label="Link Schedule to BOQ",
        description="Connect Gantt activities to BOQ sections for 5D analysis",
        icon="link",
        requires_confirmation=False,
        navigate_to="/schedule",
    ),
    "action_open_boq": ActionDefinition(
        id="action_open_boq",
        label="Open BOQ Editor",
        description="Navigate to the Bill of Quantities editor",
        icon="table",
        requires_confirmation=False,
        navigate_to="/boq",
    ),
    "action_open_risks": ActionDefinition(
        id="action_open_risks",
        label="Open Risk Register",
        description="Navigate to the Risk Register to manage project risks",
        icon="shield-alert",
        requires_confirmation=False,
        navigate_to="/risks",
    ),
}


def get_available_actions(gap_action_ids: list[str]) -> list[dict[str, Any]]:
    """Return action definitions relevant to the given gap action IDs.

    Args:
        gap_action_ids: List of action IDs from detected gaps.

    Returns:
        List of action definition dicts.
    """
    actions = []
    seen = set()
    for action_id in gap_action_ids:
        if action_id and action_id in ACTION_REGISTRY and action_id not in seen:
            seen.add(action_id)
            defn = ACTION_REGISTRY[action_id]
            actions.append({
                "id": defn.id,
                "label": defn.label,
                "description": defn.description,
                "icon": defn.icon,
                "requires_confirmation": defn.requires_confirmation,
                "confirmation_message": defn.confirmation_message,
                "navigate_to": defn.navigate_to,
                "has_backend_action": defn.target_module is not None,
            })
    return actions


async def execute_action(
    session: AsyncSession,
    action_id: str,
    project_id: str,
) -> ActionResult:
    """Execute a registered action.

    Args:
        session: Database session.
        action_id: ID of the action to execute.
        project_id: UUID of the project.

    Returns:
        ActionResult with success status and message.
    """
    defn = ACTION_REGISTRY.get(action_id)
    if not defn:
        return ActionResult(
            success=False,
            message=f"Unknown action: {action_id}",
        )

    # Navigation-only actions
    if defn.navigate_to and not defn.target_module:
        return ActionResult(
            success=True,
            message=f"Navigate to {defn.label}",
            redirect_url=defn.navigate_to,
        )

    # Backend actions
    try:
        if action_id == "action_run_validation":
            return await _run_validation(session, project_id)
        elif action_id == "action_match_cwicr_prices":
            return await _match_cwicr_prices(session, project_id)
        elif action_id == "action_generate_schedule":
            return await _generate_schedule(session, project_id)
        elif action_id == "action_create_boq_ai":
            return ActionResult(
                success=True,
                message="Navigate to AI Estimate to generate BOQ",
                redirect_url="/ai-estimate",
            )
        else:
            return ActionResult(
                success=False,
                message=f"Action '{action_id}' is not yet implemented",
            )
    except Exception as exc:
        logger.exception("Action %s failed for project %s", action_id, project_id)
        return ActionResult(
            success=False,
            message=f"Action failed: {str(exc)[:200]}",
        )


# ── Helpers ────────────────────────────────────────────────────────────────


def _to_uuid(value: str) -> uuid.UUID:
    """Coerce a string into a UUID, raising a clean ValueError."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def _find_project_boq(
    session: AsyncSession,
    project_id: str,
):
    """Return the first (oldest) BOQ for a project, or None.

    Used by every action that operates on "the project's main BOQ". We pick
    the oldest BOQ deterministically so repeated action runs hit the same
    target. Callers must handle the None case.
    """
    from sqlalchemy import select

    from app.modules.boq.models import BOQ

    pid = _to_uuid(project_id)
    stmt = (
        select(BOQ)
        .where(BOQ.project_id == pid)
        .order_by(BOQ.created_at.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ── Backend action implementations ────────────────────────────────────────


async def _run_validation(
    session: AsyncSession,
    project_id: str,
) -> ActionResult:
    """Run the validation engine against the project's main BOQ.

    Calls ``ValidationModuleService.run_validation`` with the standard
    ``din276`` + ``boq_quality`` rule sets. Persists a real report and
    returns its id + pass/warning/error counts. Never falls back to a
    simple redirect — if the service fails, we surface the error.
    """
    try:
        boq = await _find_project_boq(session, project_id)
        if boq is None:
            return ActionResult(
                success=False,
                message="No BOQ found for this project. Create a BOQ first.",
            )

        from app.modules.validation.service import ValidationModuleService

        svc = ValidationModuleService(session)
        report = await svc.run_validation(
            project_id=_to_uuid(project_id),
            boq_id=boq.id,
            rule_sets=["din276", "boq_quality"],
            user_id=None,
        )
        await session.commit()

        error_count = int(report.get("error_count", 0))
        warning_count = int(report.get("warning_count", 0))
        passed_count = int(report.get("passed_count", 0))
        status_str = report.get("status", "done")
        report_id = report.get("report_id")

        return ActionResult(
            success=True,
            message=(
                f"Validation completed ({status_str}): "
                f"{passed_count} passed, {warning_count} warnings, {error_count} errors"
            ),
            redirect_url="/validation",
            data={
                "report_id": report_id,
                "status": status_str,
                "error_count": error_count,
                "warning_count": warning_count,
                "passed_count": passed_count,
                "boq_id": str(boq.id),
            },
        )
    except Exception as exc:
        logger.exception("_run_validation failed for project %s", project_id)
        return ActionResult(
            success=False,
            message=f"Validation failed: {str(exc)[:200]}",
        )


async def _match_cwicr_prices(
    session: AsyncSession,
    project_id: str,
) -> ActionResult:
    """Match zero-priced BOQ positions against the CWICR cost catalogue.

    For every Position in the project's main BOQ whose ``unit_rate`` is
    blank / zero / non-numeric, we call
    ``CostItemService.suggest_for_bim_element`` (which is the closest
    generic ranked matcher the catalogue exposes) using the position's
    description as the search seed. If we get at least one suggestion
    with score > 0 we write its rate back to the position and recompute
    the line total. Positions with no usable match are counted as
    ``skipped``. No redirect fallback.
    """
    try:
        boq = await _find_project_boq(session, project_id)
        if boq is None:
            return ActionResult(
                success=False,
                message="No BOQ found for this project. Create a BOQ first.",
            )

        from decimal import Decimal, InvalidOperation

        from app.modules.costs.service import CostItemService

        cost_svc = CostItemService(session)

        def _is_zero_or_blank(raw: str | None) -> bool:
            if raw is None or str(raw).strip() == "":
                return True
            try:
                return Decimal(str(raw)) == 0
            except (InvalidOperation, ValueError):
                return True

        # `positions` relation is selectin-loaded; iterate the live list.
        count_total = 0
        count_updated = 0
        count_skipped = 0
        updated_ids: list[str] = []

        for pos in list(boq.positions):
            # Only consider leaf positions (rows that actually carry a price).
            # Section headers typically have empty unit/description — skip.
            if not pos.description or (pos.unit or "").strip() == "":
                continue
            if not _is_zero_or_blank(pos.unit_rate):
                continue

            count_total += 1

            suggestions = await cost_svc.suggest_for_bim_element(
                element_type=None,
                name=pos.description,
                discipline=None,
                properties=None,
                quantities=None,
                classification=pos.classification or None,
                limit=1,
                region=None,
            )
            if not suggestions:
                count_skipped += 1
                continue

            top = suggestions[0]
            try:
                rate_dec = Decimal(str(top.unit_rate))
            except (InvalidOperation, ValueError):
                count_skipped += 1
                continue

            try:
                qty_dec = Decimal(str(pos.quantity or "0"))
            except (InvalidOperation, ValueError):
                qty_dec = Decimal("0")

            pos.unit_rate = str(rate_dec)
            pos.total = str(qty_dec * rate_dec)
            meta = dict(pos.metadata_ or {})
            meta["cwicr_matched_code"] = top.code
            meta["cwicr_matched_score"] = top.score
            pos.metadata_ = meta

            count_updated += 1
            updated_ids.append(str(pos.id))

        if count_updated > 0:
            await session.commit()

        # Best-effort event so downstream listeners can react.
        try:
            from app.core.events import event_bus

            await event_bus.publish(
                "boq.prices.matched",
                {
                    "project_id": str(project_id),
                    "boq_id": str(boq.id),
                    "updated_count": count_updated,
                    "skipped_count": count_skipped,
                    "total_candidates": count_total,
                },
                source_module="oe_project_intelligence",
            )
        except Exception:
            logger.debug("boq.prices.matched event publish skipped", exc_info=True)

        return ActionResult(
            success=True,
            message=(
                f"{count_updated} positions priced from CWICR "
                f"({count_skipped} skipped, {count_total} candidates)"
            ),
            redirect_url="/boq",
            data={
                "boq_id": str(boq.id),
                "count_updated": count_updated,
                "count_skipped": count_skipped,
                "count_total": count_total,
                "updated_position_ids": updated_ids[:50],
            },
        )
    except Exception as exc:
        logger.exception("_match_cwicr_prices failed for project %s", project_id)
        return ActionResult(
            success=False,
            message=f"Price matching failed: {str(exc)[:200]}",
        )


async def _generate_schedule(
    session: AsyncSession,
    project_id: str,
) -> ActionResult:
    """Auto-generate a Schedule + Activities from the project's main BOQ.

    Refuses if a schedule already exists for this project (user must edit
    manually). Otherwise creates a fresh draft Schedule and delegates to
    ``ScheduleService.generate_from_boq`` which builds summary/task
    activities from BOQ sections. No redirect fallback.
    """
    try:
        boq = await _find_project_boq(session, project_id)
        if boq is None:
            return ActionResult(
                success=False,
                message="No BOQ found for this project. Create a BOQ first.",
            )

        from datetime import date

        from app.modules.projects.repository import ProjectRepository
        from app.modules.schedule.schemas import ScheduleCreate
        from app.modules.schedule.service import ScheduleService

        pid = _to_uuid(project_id)
        schedule_svc = ScheduleService(session)

        # Refuse if a schedule already exists.
        existing, existing_count = await schedule_svc.list_schedules_for_project(
            pid, limit=1
        )
        if existing_count > 0 or existing:
            existing_id = existing[0].id if existing else None
            return ActionResult(
                success=False,
                message="Schedule already exists; manual edit required.",
                redirect_url="/schedule",
                data={
                    "schedule_id": str(existing_id) if existing_id else None,
                    "existing_count": existing_count,
                },
            )

        # Resolve a sensible start date: project.planned_start_date → today.
        start_iso = date.today().isoformat()
        try:
            project = await ProjectRepository(session).get_by_id(pid)
            if project is not None:
                candidate = (
                    getattr(project, "planned_start_date", None)
                    or getattr(project, "actual_start_date", None)
                )
                if candidate:
                    start_iso = str(candidate)[:10]
        except Exception:
            logger.debug("Could not resolve project start date", exc_info=True)

        new_schedule = await schedule_svc.create_schedule(
            ScheduleCreate(
                project_id=pid,
                name=f"Auto-generated from BOQ ({boq.name})",
                schedule_type="master",
                description="Generated by Project Intelligence action_generate_schedule.",
                start_date=start_iso,
                metadata={"auto_generated": True, "source_boq_id": str(boq.id)},
            )
        )

        activities = await schedule_svc.generate_from_boq(
            schedule_id=new_schedule.id,
            boq_id=boq.id,
        )
        await session.commit()

        return ActionResult(
            success=True,
            message=f"Schedule generated with {len(activities)} activities",
            redirect_url="/schedule",
            data={
                "schedule_id": str(new_schedule.id),
                "activity_count": len(activities),
                "boq_id": str(boq.id),
                "start_date": start_iso,
            },
        )
    except Exception as exc:
        logger.exception("_generate_schedule failed for project %s", project_id)
        return ActionResult(
            success=False,
            message=f"Schedule generation failed: {str(exc)[:200]}",
        )
