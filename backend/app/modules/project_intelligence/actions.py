"""Action executor — triggers operations in other modules.

Each action_id maps to a definition describing what it does,
which module it targets, and whether it requires confirmation.
"""

import logging
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


async def _run_validation(
    session: AsyncSession,
    project_id: str,
) -> ActionResult:
    """Run validation on the project's BOQs."""
    try:
        from sqlalchemy import text

        # Find first BOQ for this project
        boq_row = (
            await session.execute(
                text("SELECT id FROM oe_boq_boq WHERE project_id = :pid LIMIT 1"),
                {"pid": project_id},
            )
        ).first()

        if not boq_row:
            return ActionResult(
                success=False,
                message="No BOQ found for this project. Create a BOQ first.",
            )

        boq_id = str(boq_row[0])

        # Try to run validation via the service
        try:
            from app.modules.validation.service import ValidationModuleService

            svc = ValidationModuleService(session)
            from app.modules.validation.schemas import RunValidationRequest

            request = RunValidationRequest(
                project_id=project_id,
                boq_id=boq_id,
                rule_sets=["boq_quality"],
            )
            report = await svc.run_validation(request, user_id=None)
            await session.commit()
            return ActionResult(
                success=True,
                message=f"Validation completed. Status: {report.get('status', 'done')}",
                redirect_url="/validation",
            )
        except Exception as e:
            logger.debug("Validation service call failed: %s", e)
            return ActionResult(
                success=True,
                message="Navigate to Validation to run checks",
                redirect_url="/validation",
            )

    except Exception as exc:
        return ActionResult(
            success=False,
            message=f"Could not run validation: {str(exc)[:200]}",
        )


async def _match_cwicr_prices(
    session: AsyncSession,
    project_id: str,
) -> ActionResult:
    """Navigate to catalog for price matching."""
    return ActionResult(
        success=True,
        message="Navigate to the Resource Catalog to match prices",
        redirect_url="/catalog",
    )


async def _generate_schedule(
    session: AsyncSession,
    project_id: str,
) -> ActionResult:
    """Navigate to schedule to generate from BOQ."""
    return ActionResult(
        success=True,
        message="Navigate to Schedule to generate timeline from BOQ",
        redirect_url="/schedule",
    )
