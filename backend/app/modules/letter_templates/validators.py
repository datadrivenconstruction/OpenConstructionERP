# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for letter texts, rule set ``letter_templates``.

The payload is ``{"template_key": str, "text": {subject, heading, body, closing}}``.
Each rule maps one finding of :func:`app.core.letter_templates.check_text`:

* ``letter_templates.body_required``         - ERROR, the body is empty.
* ``letter_templates.unknown_placeholder``   - ERROR, a ``{name}`` the letter does not offer.
* ``letter_templates.required_placeholder``  - WARNING, a required value such as ``{amount}`` is missing.

The save endpoint calls ``check_text`` directly and refuses errors; these
rules expose the same checks to the validation engine and its reports.
"""

from __future__ import annotations

from app.core.letter_templates import LetterText, check_text, get_template
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)


def _issues(context: ValidationContext, code: str) -> list:
    data = context.data if isinstance(context.data, dict) else {}
    template = get_template(str(data.get("template_key") or ""))
    raw = data.get("text") if isinstance(data.get("text"), dict) else {}
    if template is None:
        return []
    text = LetterText(**{k: str(raw.get(k) or "") for k in ("subject", "heading", "body", "closing")})
    return [i for i in check_text(template, text) if i.code == code]


class _LetterRule(ValidationRule):
    code = ""
    standard = "letter_templates"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        found = _issues(context, self.code)
        if not found:
            return [
                RuleResult(self.rule_id, self.name, self.severity, self.category, passed=True, message="OK"),
            ]
        return [
            RuleResult(
                self.rule_id,
                self.name,
                self.severity,
                self.category,
                passed=False,
                message=f"{issue.field}: {self.description}"
                + (f" {{{issue.placeholder}}}" if issue.placeholder else ""),
                element_ref=issue.field,
                details={"placeholder": issue.placeholder},
            )
            for issue in found
        ]


class LetterBodyRequired(_LetterRule):
    rule_id = "letter_templates.body_required"
    name = "Letter body required"
    code = "empty_body"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The letter body is empty."


class LetterUnknownPlaceholder(_LetterRule):
    rule_id = "letter_templates.unknown_placeholder"
    name = "Unknown placeholder"
    code = "unknown_placeholder"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "This placeholder is not offered by the letter and would print as written:"


class LetterRequiredPlaceholder(_LetterRule):
    rule_id = "letter_templates.required_placeholder"
    name = "Required placeholder missing"
    code = "missing_required"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "The letter does not mention a value it normally states:"


_RULES = (LetterBodyRequired(), LetterUnknownPlaceholder(), LetterRequiredPlaceholder())


def register_letter_template_rules() -> None:
    """Register the rules with the core registry. Idempotent."""
    for rule in _RULES:
        rule_registry.register(rule, ["letter_templates"])
