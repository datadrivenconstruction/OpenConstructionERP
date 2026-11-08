# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``site_sensor_links``: cross-module links point at real records.

Site sensor alerts and formwork strips hold plain GUIDs to a schedule
activity, a diary, an inspection and a punch item. A link is sound when the
target exists and sits in the same project as the alert or strip.

Payload built by :func:`build_sensor_link_payload`::

    {"links": [{"source", "source_id", "field", "target_id", "exists", "same_project"}]}
"""

from __future__ import annotations

import importlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

LINK_RULE_SET = "site_sensor_links"

# field -> (module path, model name); the target's project is read from ``project_id``.
_TARGETS: dict[str, tuple[str, str]] = {
    "diary_id": ("app.modules.daily_diary.models", "DailyDiary"),
    "inspection_id": ("app.modules.inspections.models", "QualityInspection"),
    "punch_item_id": ("app.modules.punchlist.models", "PunchItem"),
}


async def _target_project(session: AsyncSession, field: str, target_id: uuid.UUID) -> tuple[bool, uuid.UUID | None]:
    if field == "schedule_activity_id":
        from app.modules.schedule.models import Activity, Schedule

        row = (
            await session.execute(
                select(Schedule.project_id)
                .join(Activity, Activity.schedule_id == Schedule.id)
                .where(Activity.id == target_id)
            )
        ).first()
        return (row is not None, row[0] if row else None)
    module_path, name = _TARGETS[field]
    try:
        model = getattr(importlib.import_module(module_path), name)
    except (ImportError, AttributeError):
        return False, None
    target = await session.get(model, target_id)
    return (target is not None, getattr(target, "project_id", None) if target else None)


async def build_sensor_link_payload(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Every link set on the project's alerts and strips, resolved."""
    from app.modules.site_sensors.models import FormworkStrip, SensorAlert

    links: list[dict[str, Any]] = []
    sources: list[tuple[str, Any, tuple[str, ...]]] = [
        ("alert", SensorAlert, ("diary_id", "inspection_id", "punch_item_id")),
        ("strip", FormworkStrip, ("schedule_activity_id",)),
    ]
    for source, model, fields in sources:
        for row in (await session.execute(select(model).where(model.project_id == project_id))).scalars():
            for field in fields:
                target_id = getattr(row, field, None)
                if target_id is None:
                    continue
                exists, target_project = await _target_project(session, field, target_id)
                links.append(
                    {
                        "source": source,
                        "source_id": str(row.id),
                        "field": field,
                        "target_id": str(target_id),
                        "exists": exists,
                        "same_project": exists and target_project == project_id,
                    }
                )
    return {"links": links}


class SensorLinkInProject(ValidationRule):
    """A sensor alert or strip links only to an existing record of its own project."""

    rule_id = "site_sensors.link_target_in_project"
    name = "Sensor Link Target In Project"
    description = "Alert and strip links point at an existing record in the same project."
    standard = "site_sensors"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        out: list[RuleResult] = []
        for link in data.get("links") or []:
            if not isinstance(link, dict):
                continue
            passed = bool(link.get("exists")) and bool(link.get("same_project"))
            reason = "ok" if passed else ("missing" if not link.get("exists") else "other_project")
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"{link.get('source')} {link.get('field')} -> {link.get('target_id')}: {reason}",
                    element_ref=str(link.get("source_id") or ""),
                    details={
                        "message_key": f"siteSensors.rules.link_{reason}",
                        "field": str(link.get("field")),
                        "target_id": str(link.get("target_id")),
                    },
                )
            )
        return out


def register_link_rules() -> None:
    rule_registry.register(SensorLinkInProject(), rule_sets=[LINK_RULE_SET, "site_sensors"])


register_link_rules()
