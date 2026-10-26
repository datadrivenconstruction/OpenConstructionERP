# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Field Time event definitions and publishers.

An approved field timesheet is the authoritative record of actual labour and
plant hours for a project-day. When a timesheet is submitted, approved or
reversed this module publishes a single, self-contained event so downstream
consumers can react without re-opening the timesheet inside a foreign session:

* the **payroll** module treats approved timesheets as the preferred source of
  field labour hours (see ``payroll.service``);
* the **cost / EVM** model can roll ``hours x rate`` into labour and plant
  actuals against the budget.

This module owns the canonical event names and typed publishers so every caller
emits an identically shaped payload. The payload carries the hours / cost rollup
inline. Publishing is detached (fire-and-forget) so the request can commit and
release its writer lock before subscribers open a second session - identical
rationale to ``fieldreports/events.py``.

Auto-imported by the module loader when ``oe_field_time`` loads.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.events import event_bus

logger = logging.getLogger(__name__)

# Canonical event names. The verb is the business fact ("a timesheet was
# approved"), matching the payroll / cost vocabulary.
TIMESHEET_SUBMITTED = "field_time.timesheet_submitted"
TIMESHEET_APPROVED = "field_time.timesheet_approved"
TIMESHEET_REVERSED = "field_time.timesheet_reversed"

SOURCE_MODULE = "oe_field_time"


def _publish(name: str, payload: dict[str, Any]) -> None:
    """Detached publish that never lets a bus failure break the transition."""
    try:
        event_bus.publish_detached(name, payload, source_module=SOURCE_MODULE)
    except Exception:  # noqa: BLE001 - a bus hiccup must not fail the request
        logger.debug("Field-time event publish skipped: %s", name)


def publish_timesheet_submitted(
    *,
    timesheet_id: str,
    project_id: str,
    work_date: str,
    labour_hours: str,
    plant_hours: str,
    actor_id: str | None = None,
) -> None:
    """Publish ``field_time.timesheet_submitted`` with the hours rollup inline."""
    _publish(
        TIMESHEET_SUBMITTED,
        {
            "timesheet_id": timesheet_id,
            "project_id": project_id,
            "work_date": work_date,
            "labour_hours": labour_hours,
            "plant_hours": plant_hours,
            "actor_id": actor_id,
        },
    )
    logger.info("Published %s for timesheet=%s", TIMESHEET_SUBMITTED, timesheet_id)


def publish_timesheet_approved(
    *,
    timesheet_id: str,
    project_id: str,
    work_date: str,
    labour_hours: str,
    plant_hours: str,
    labour_cost: str,
    plant_cost: str,
    currency: str,
    actor_id: str | None = None,
) -> None:
    """Publish ``field_time.timesheet_approved`` with the hours + cost rollup.

    Approval is the point at which the hours become authoritative actuals, so the
    payload carries the ``hours x rate`` cost rollup (already in the project base
    currency) alongside the hours.
    """
    _publish(
        TIMESHEET_APPROVED,
        {
            "timesheet_id": timesheet_id,
            "project_id": project_id,
            "work_date": work_date,
            "labour_hours": labour_hours,
            "plant_hours": plant_hours,
            "labour_cost": labour_cost,
            "plant_cost": plant_cost,
            "currency": currency,
            "actor_id": actor_id,
        },
    )
    logger.info("Published %s for timesheet=%s", TIMESHEET_APPROVED, timesheet_id)


def publish_timesheet_reversed(
    *,
    timesheet_id: str,
    reverses_id: str,
    project_id: str,
    work_date: str,
    labour_hours: str,
    plant_hours: str,
    actor_id: str | None = None,
) -> None:
    """Publish ``field_time.timesheet_reversed`` for the reversing timesheet.

    ``timesheet_id`` is the new reversal timesheet; ``reverses_id`` is the
    original it corrects. The hours are the (positive) hours the reversal cancels
    so a consumer can net them against the original.
    """
    _publish(
        TIMESHEET_REVERSED,
        {
            "timesheet_id": timesheet_id,
            "reverses_id": reverses_id,
            "project_id": project_id,
            "work_date": work_date,
            "labour_hours": labour_hours,
            "plant_hours": plant_hours,
            "actor_id": actor_id,
        },
    )
    logger.info(
        "Published %s for timesheet=%s (reverses %s)",
        TIMESHEET_REVERSED,
        timesheet_id,
        reverses_id,
    )


# Time clock facts. Payloads never carry the position: subscribers (daily
# diary headcount, dashboards, notifications) need who, when and whether it
# was inside the fence, not where the worker stood.
CLOCK_IN = "field_time.clock_in"
CLOCK_OUT = "field_time.clock_out"
CLOCK_FLAGGED = "field_time.clock_flagged_outside"
CLOCK_DECIDED = "field_time.clock_decided"
CLOCK_TIMESHEET_BUILT = "field_time.clock_timesheet_built"


def publish_clock_event(name: str, payload: dict[str, Any]) -> None:
    """Publish one of the ``field_time.clock_*`` facts (detached, never raises)."""
    _publish(name, payload)


__all__ = [
    "CLOCK_DECIDED",
    "CLOCK_FLAGGED",
    "CLOCK_IN",
    "CLOCK_OUT",
    "CLOCK_TIMESHEET_BUILT",
    "TIMESHEET_APPROVED",
    "TIMESHEET_REVERSED",
    "TIMESHEET_SUBMITTED",
    "publish_clock_event",
    "publish_timesheet_approved",
    "publish_timesheet_reversed",
    "publish_timesheet_submitted",
]
