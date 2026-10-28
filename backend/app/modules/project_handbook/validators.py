# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``project_handbook``.

The rules read one payload, built by ``ProjectHandbookService.validation_payload``::

    {"chapters": [{"code", "status", "content", "owner_id", "required", "sources", "linked_rows",
                   "approved_version", "submitted_at"}, ...]}

Every rule calls the same pure function the service uses (``rules.py``) and keeps the findings of its
own codes, so a check has one implementation.
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
)
from app.modules.project_handbook import rules
from app.modules.project_handbook.messages import translate

HANDBOOK_RULE_SET = "project_handbook"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _locale(context: ValidationContext) -> str:
    return str((getattr(context, "metadata", None) or {}).get("locale") or "en")


class _HandbookRule(ValidationRule):
    standard = "project_handbook"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    key = ""
    codes: tuple[str, ...] = ()

    @property
    def _base(self) -> str:
        return f"project_handbook.rules.{self.key}"

    def _result(self, locale: str, passed: bool, ref: str, severity: Severity | None = None) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=passed,
            message=translate("project_handbook.rules.ok", locale=locale)
            if passed
            else translate(f"{self._base}.fail", locale=locale, ref=ref),
            element_ref=ref,
            suggestion=None if passed else translate(f"{self._base}.suggestion", locale=locale),
        )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        found = [f for f in rules.handbook_findings(_data(context).get("chapters") or []) if f.code in self.codes]
        if not found:
            return [self._result(loc, True, "handbook")]
        return [
            self._result(loc, False, f.ref, Severity.WARNING if f.severity == rules.WARNING else Severity.ERROR)
            for f in found
        ]


class ChaptersPresent(_HandbookRule):
    key = "chapters_present"
    rule_id = "project_handbook.chapters_present"
    name = "Chapters Present"
    description = "The handbook has the chapters its catalogue asks for."
    codes = ("no_chapters",)


class ChaptersOwned(_HandbookRule):
    key = "chapters_owned"
    rule_id = "project_handbook.chapters_owned"
    name = "Chapters Owned"
    description = "Every chapter names an owner."
    codes = ("chapter_owner_missing",)


class ChaptersWritten(_HandbookRule):
    key = "chapters_written"
    rule_id = "project_handbook.chapters_written"
    name = "Chapters Written"
    description = "A chapter carries text; a required chapter must."
    codes = ("chapter_empty",)


class RequiredChaptersApproved(_HandbookRule):
    key = "required_chapters_approved"
    rule_id = "project_handbook.required_chapters_approved"
    name = "Required Chapters Approved"
    severity = Severity.WARNING
    description = "A required chapter has an approved version."
    codes = ("required_chapter_open",)


class LinkedSourcesFilled(_HandbookRule):
    key = "linked_sources_filled"
    rule_id = "project_handbook.linked_sources_filled"
    name = "Linked Sources Filled"
    severity = Severity.WARNING
    description = "A chapter that reads records of other modules finds at least one."
    codes = ("linked_source_empty",)


class ReviewNotOverdue(_HandbookRule):
    key = "review_not_overdue"
    rule_id = "project_handbook.review_not_overdue"
    name = "Review Not Overdue"
    severity = Severity.WARNING
    description = "A chapter does not wait in review for more than two weeks."
    codes = ("review_overdue",)


HANDBOOK_RULES: tuple[type[ValidationRule], ...] = (
    ChaptersPresent,
    ChaptersOwned,
    ChaptersWritten,
    RequiredChaptersApproved,
    LinkedSourcesFilled,
    ReviewNotOverdue,
)


def register_project_handbook_rules() -> None:
    """Idempotently register the project handbook rules."""
    for rule in HANDBOOK_RULES:
        rule_registry.register(rule(), rule_sets=[HANDBOOK_RULE_SET])


# Registered on import as well, like the platform rule modules. Registration is idempotent.
register_project_handbook_rules()
