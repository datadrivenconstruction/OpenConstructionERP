# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for drafts produced by project catalogue agents.

Rule set ``ai_agent_drafts``:

* ``ai_agent_drafts.review_overdue`` - INFO. A draft an agent created and
  nobody reviewed within the agent's ``review_after_days`` (default 7) is
  either forgotten work or noise; both are worth a nudge, neither blocks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import translate

AI_AGENT_DRAFTS_RULE_SET = "ai_agent_drafts"
DEFAULT_REVIEW_AFTER_DAYS = 7


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class DraftReviewOverdue(ValidationRule):
    """An agent draft still pending after its review window."""

    rule_id = "ai_agent_drafts.review_overdue"
    name = "Agent draft reviewed in time"
    standard = AI_AGENT_DRAFTS_RULE_SET
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "A draft created by an agent and not reviewed after N days."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        now = _as_dt(data.get("as_of")) or datetime.now(UTC)
        locale = str((context.metadata or {}).get("locale") or "en")
        results: list[RuleResult] = []
        for draft in data.get("drafts") or []:
            if draft.get("status") != "pending":
                continue
            created = _as_dt(draft.get("created_at"))
            if created is None:
                continue
            limit = int(draft.get("review_after_days") or DEFAULT_REVIEW_AFTER_DAYS)
            age = (now - created).days
            overdue = age >= limit
            message = (
                translate(
                    "ai_agent_drafts.review_overdue.fail",
                    locale,
                    title=str(draft.get("title") or ""),
                    days=age,
                    limit=limit,
                )
                if overdue
                else "OK"
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=not overdue,
                    message=message,
                    element_ref=str(draft.get("id") or "") or None,
                    suggestion=translate("ai_agent_drafts.review_overdue.suggestion", locale) if overdue else None,
                    details={"age_days": age, "review_after_days": limit, "agent": draft.get("agent_name")},
                )
            )
        return results


_RULES: list[ValidationRule] = [DraftReviewOverdue()]


def register_ai_agent_rules() -> None:
    """Register the rule set; idempotent."""
    for rule in _RULES:
        rule_registry.register(rule, [AI_AGENT_DRAFTS_RULE_SET])
