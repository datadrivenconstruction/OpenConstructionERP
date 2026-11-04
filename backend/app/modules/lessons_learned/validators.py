# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned validation rules (rule set ``lessons_learned``).

Rules read ``context.data`` = the lesson as a plain dict. Errors block confirming a lesson; the warning only
advises. The service runs the set on every create, update and confirm.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)

RULE_SET = "lessons_learned"


def _result(rule: ValidationRule, passed: bool, message: str) -> list[RuleResult]:
    return [
        RuleResult(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            passed=passed,
            message="ok" if passed else message,
            element_ref=None,
        )
    ]


def _text(context: ValidationContext, key: str) -> str:
    data = context.data if isinstance(context.data, dict) else {}
    return str(data.get(key) or "").strip()


class TitleRequired(ValidationRule):
    """A lesson needs a short title."""

    rule_id = "lessons_learned.title_required"
    name = "Lesson has a title"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A lesson needs a short title."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return _result(self, bool(_text(context, "title")), "title_missing")


class HasTag(ValidationRule):
    """A lesson needs at least one tag, otherwise no other project can ever match it."""

    rule_id = "lessons_learned.has_tag"
    name = "Lesson has a trade, cost code or risk category"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Without a tag no other project can ever match the lesson."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ok = any(_text(context, k) for k in ("trade", "cost_code", "risk_category"))
        return _result(self, ok, "tag_missing")


class HasContent(ValidationRule):
    """A lesson needs a description or a recommendation."""

    rule_id = "lessons_learned.has_content"
    name = "Lesson says what happened or what to do"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A lesson needs a description or a recommendation."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ok = bool(_text(context, "description") or _text(context, "recommendation"))
        return _result(self, ok, "content_missing")


class ConfirmedHasRecommendation(ValidationRule):
    """A confirmed lesson should say what to do next time."""

    rule_id = "lessons_learned.confirmed_has_recommendation"
    name = "Confirmed lesson has a recommendation"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A lesson that only describes the problem does not help the next estimator."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _text(context, "status") != "confirmed":
            return []
        return _result(self, bool(_text(context, "recommendation")), "recommendation_missing")


_RULES: tuple[ValidationRule, ...] = (TitleRequired(), HasTag(), HasContent(), ConfirmedHasRecommendation())
RULE_IDS = tuple(r.rule_id for r in _RULES)


def register_lessons_learned_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(data: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Run the rule set on one lesson and return the failed results."""
    register_lessons_learned_rules()
    report = await validation_engine.validate(
        data=data, rule_sets=[RULE_SET], target_type="lesson_learned", target_id=target_id
    )
    return [r for r in report.results if not r.is_engine_error and not r.passed]


__all__ = ["RULE_IDS", "RULE_SET", "evaluate", "register_lessons_learned_rules"]
