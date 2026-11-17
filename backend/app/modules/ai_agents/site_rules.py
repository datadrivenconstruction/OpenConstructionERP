# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for the site assistants (rule set ``ai_site_assistants``).

Every request is checked before a run starts. Each rule reads one flat ``data`` dict:

* ``ai_site_assistants.project_in_scope`` - the record named in the request belongs to the project.
* ``ai_site_assistants.diary_date_not_future`` - a diary draft is for today or a past day.
* ``ai_site_assistants.rfi_in_draft`` - an RFI is checked only while it is still a draft.
* ``ai_site_assistants.minutes_min_length`` - minutes shorter than 50 characters carry nothing to extract.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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

AI_SITE_RULE_SET = "ai_site_assistants"
MIN_MINUTES_CHARS = 50


def _locale(context: ValidationContext) -> str:
    return str((context.metadata or {}).get("locale") or "en")


class _SiteRule(ValidationRule):
    standard = AI_SITE_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    def _result(self, context: ValidationContext, passed: bool, **params: Any) -> list[RuleResult]:
        locale = _locale(context)
        key = self.rule_id
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message="OK" if passed else translate(f"{key}.fail", locale, **params),
                suggestion=None if passed else translate(f"{key}.suggestion", locale),
                details=dict(params),
            )
        ]


class ProjectInScope(_SiteRule):
    rule_id = "ai_site_assistants.project_in_scope"
    name = "Record belongs to the project"
    description = "The RFI or meeting named in a request belongs to the project the request is for."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        if "record_project_id" not in data:
            return []
        ok = str(data.get("record_project_id")) == str(data.get("project_id"))
        return self._result(context, ok)


class DiaryDateNotFuture(_SiteRule):
    rule_id = "ai_site_assistants.diary_date_not_future"
    name = "Diary date is not in the future"
    description = "A diary draft is for today or an earlier day (one day of slack for sites ahead of UTC)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        raw = data.get("diary_date")
        if raw is None:
            return []
        try:
            day = date.fromisoformat(str(raw))
        except ValueError:
            return self._result(context, False, diary_date=str(raw))
        today = data.get("today") or datetime.now(UTC).date()
        return self._result(context, day <= today + timedelta(days=1), diary_date=str(raw))


class RfiInDraft(_SiteRule):
    rule_id = "ai_site_assistants.rfi_in_draft"
    name = "RFI is still a draft"
    description = "The completeness check runs before sending, while the RFI is a draft."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        if "rfi_status" not in data:
            return []
        status = str(data.get("rfi_status"))
        return self._result(context, status == "draft", status=status)


class MinutesMinLength(_SiteRule):
    rule_id = "ai_site_assistants.minutes_min_length"
    name = "Minutes are long enough"
    description = f"Minutes shorter than {MIN_MINUTES_CHARS} characters are not worth extracting from."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        if "minutes" not in data:
            return []
        length = len(str(data.get("minutes") or "").strip())
        return self._result(context, length >= MIN_MINUTES_CHARS, length=length, minimum=MIN_MINUTES_CHARS)


_RULES: list[ValidationRule] = [ProjectInScope(), DiaryDateNotFuture(), RfiInDraft(), MinutesMinLength()]


def register_ai_site_rules() -> None:
    """Register the rule set; idempotent."""
    for rule in _RULES:
        rule_registry.register(rule, [AI_SITE_RULE_SET])
