# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for document templates, rule set ``doc_templates``.

The payload is ``{"kind": str, "blocks": {block: text}}``, optionally with
``"countries"`` and ``"values"`` for the pack legal check. Each rule maps one
finding of :func:`app.core.doc_templates.rules.check_blocks` or
:func:`app.core.doc_templates.legal.legal_notes`:

* ``doctpl.unknown_merge_field`` - ERROR, ``{{x}}`` is not a field of this document.
* ``doctpl.email_subject_empty`` - ERROR, email subject is empty.
* ``doctpl.unsafe_link``         - ERROR, a link that is not https:// or mailto:.
* ``doctpl.raw_html``            - ERROR, HTML typed into a block.
* ``doctpl.legal_data_missing``  - ERROR (WARNING when the pack says so), a pack-mandatory value is empty.

A document layout is checked with ``{"layout": key, "template": {...}}`` and
optionally ``"countries"`` for pack locks; it shares the merge field and HTML
rules above and adds:

* ``doctpl.required_section_hidden`` - ERROR, a locked section is hidden or deleted.
* ``doctpl.required_column_hidden``  - ERROR, a locked table column is hidden or removed.
* ``doctpl.required_field_removed``  - ERROR, a locked field is hidden or removed.
* ``doctpl.invalid_expression``      - ERROR, a computed value or condition does not parse.
* ``doctpl.custom_block_limit``      - ERROR, more blocks than a document may hold.

Publishing calls the same checks directly and refuses errors.
"""

from __future__ import annotations

from app.core.doc_templates.legal import legal_notes
from app.core.doc_templates.registry import get_kind
from app.core.doc_templates.rules import Issue, check_blocks
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)


def _issues(context: ValidationContext, rule_id: str) -> list[Issue]:
    data = context.data if isinstance(context.data, dict) else {}
    if data.get("layout"):
        return _layout_issues(data, rule_id)
    kind = get_kind(str(data.get("kind") or ""))
    if kind is None:
        return []
    if rule_id == "doctpl.legal_data_missing":
        values = data.get("values") if isinstance(data.get("values"), dict) else {}
        _notes, issues = legal_notes(kind.key, list(data.get("countries") or []), values, "en")
        return issues
    raw = data.get("blocks") if isinstance(data.get("blocks"), dict) else {}
    blocks = {k: str(v or "") for k, v in raw.items()}
    return [i for i in check_blocks(kind, blocks) if i.rule_id == rule_id]


def _layout_issues(data: dict, rule_id: str) -> list[Issue]:
    from app.core.doc_templates.layout.spec import get_layout
    from app.core.doc_templates.layout.template import check, locks_for, normalise

    spec = get_layout(str(data.get("layout") or ""))
    if spec is None:
        return []
    template = normalise(data.get("template") or {})
    locks = locks_for(spec, [str(c) for c in data.get("countries") or []])
    return [i for i in check(template, spec, locks) if i.rule_id == rule_id]


class _DocRule(ValidationRule):
    standard = "doc_templates"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        found = _issues(context, self.rule_id)
        if not found:
            return [RuleResult(self.rule_id, self.name, self.severity, self.category, passed=True, message="OK")]
        return [
            RuleResult(
                self.rule_id,
                self.name,
                self.severity,
                self.category,
                passed=False,
                message=self.description,
                element_ref=issue.block,
                details=dict(issue.params or {}),
            )
            for issue in found
        ]


class UnknownMergeField(_DocRule):
    rule_id = "doctpl.unknown_merge_field"
    name = "Unknown merge field"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "This field is not a field of this document. Pick one from the list."


class EmailSubjectEmpty(_DocRule):
    rule_id = "doctpl.email_subject_empty"
    name = "Email subject empty"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Email subject is empty."


class UnsafeLink(_DocRule):
    rule_id = "doctpl.unsafe_link"
    name = "Unsafe link"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Links must start with https:// or mailto:."


class RawHtml(_DocRule):
    rule_id = "doctpl.raw_html"
    name = "HTML in text"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Use the text format, not HTML tags."


class LegalDataMissing(_DocRule):
    rule_id = "doctpl.legal_data_missing"
    name = "Legal data missing"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A value the country requires on this document is empty."


class RequiredSectionHidden(_DocRule):
    rule_id = "doctpl.required_section_hidden"
    name = "Required section hidden"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "This section is required on this document and cannot be hidden."


class RequiredColumnHidden(_DocRule):
    rule_id = "doctpl.required_column_hidden"
    name = "Required column hidden"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "This column is required on this document and cannot be hidden."


class RequiredFieldRemoved(_DocRule):
    rule_id = "doctpl.required_field_removed"
    name = "Required field removed"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "This field is required on this document and cannot be removed."


class InvalidExpression(_DocRule):
    rule_id = "doctpl.invalid_expression"
    name = "Invalid formula"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "This formula or condition cannot be read. Use fields, numbers and + - * / only."


class CustomBlockLimit(_DocRule):
    rule_id = "doctpl.custom_block_limit"
    name = "Too many blocks"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = "This document holds more blocks than a document may have."


_RULES = (
    UnknownMergeField(),
    EmailSubjectEmpty(),
    UnsafeLink(),
    RawHtml(),
    LegalDataMissing(),
    RequiredSectionHidden(),
    RequiredColumnHidden(),
    RequiredFieldRemoved(),
    InvalidExpression(),
    CustomBlockLimit(),
)


def register_doc_template_rules() -> None:
    """Register the rules with the core registry. Idempotent."""
    for rule in _RULES:
        rule_registry.register(rule, ["doc_templates"])
