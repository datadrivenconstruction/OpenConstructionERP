# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared building blocks for the money-module rule sets.

Change orders, cost recovery, post-calculation and claims evidence all carry
money, quantities and a status, and all ask the same six questions of a record:
do the totals add up, are the numbers sane, is a currency stated and the same
throughout, are the required references present, did the status move along an
allowed edge, and are the dates in order. This module holds the plain helpers
and the base rule that answers them in the caller's language, so each module's
``validators.py`` only says which fields to look at.

Messages live in the shared bundle under the ``money`` section.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.failure import finding, introduced_errors, raise_rule_failure
from app.core.validation.messages import translate

#: Money is stored to two places; one minor unit of slack absorbs rounding of
#: a sum of rounded lines without hiding a real discrepancy.
MONEY_TOLERANCE = Decimal("0.01")

#: Anything at or above this is a unit slip (cents entered as units, a pasted
#: id), not a price. No construction line item reaches a trillion.
MAX_SANE_AMOUNT = Decimal("1e12")


def to_dec(value: Any) -> Decimal | None:
    """Parse a number or numeric string; ``None`` when absent or not a finite number."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def data_of(context: ValidationContext) -> dict[str, Any]:
    """The context payload as a dict (an empty one for anything else)."""
    return context.data if isinstance(context.data, dict) else {}


def section(context: ValidationContext, key: str) -> dict[str, Any]:
    """One nested record of the payload, or an empty dict."""
    value = data_of(context).get(key)
    return value if isinstance(value, dict) else {}


def rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    """The dict rows of a list in the payload."""
    value = data_of(context).get(key)
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def currency_of(record: Mapping[str, Any]) -> str:
    """The record's currency code, trimmed and upper-cased; blank when unstated."""
    return str(record.get("currency") or "").strip().upper()


def blank(value: Any) -> bool:
    """True for ``None`` and whitespace-only text."""
    return value is None or (isinstance(value, str) and not value.strip())


def locale_of(context: ValidationContext) -> str:
    """The caller's locale from the context metadata, English by default."""
    meta = context.metadata or {}
    return str(meta.get("locale") or "en")


class MoneyRule(ValidationRule):
    """Base for the money-module rules: result building in the caller's locale."""

    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    #: Message section of the rule set. With ``own_message_keys`` set, only those keys read from it and
    #: every other key is the shared ``money`` text; without, every key reads from it.
    message_section = "money"
    own_message_keys: frozenset[str] = frozenset()

    #: When set, every rule of the set shares this suggestion key instead of one per rule.
    suggestion_key: str | None = None

    def _section_of(self, key: str) -> str:
        if not self.own_message_keys or key in self.own_message_keys:
            return self.message_section
        return "money"

    def ok(self, ref: str = "") -> RuleResult:
        """A passing result."""
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message="OK",
            element_ref=ref,
        )

    def fail(
        self,
        context: ValidationContext,
        key: str,
        *,
        ref: str = "",
        severity: Severity | None = None,
        section: str | None = None,
        **params: Any,
    ) -> RuleResult:
        """A failing result whose text is ``<section>.<key>`` in the caller's locale."""
        section = section or self._section_of(key)
        locale = locale_of(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"{section}.{key}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=translate(self.suggestion_key or f"{section}.{key}.suggestion", locale=locale),
            details={k: str(v) for k, v in params.items()},
        )

    def total_mismatch(
        self,
        context: ValidationContext,
        ref: str,
        label: str,
        stated: Decimal,
        expected: Decimal,
        currency: str,
        tolerance: Decimal = MONEY_TOLERANCE,
    ) -> RuleResult | None:
        """A failure when ``stated`` differs from ``expected`` by more than ``tolerance``."""
        from app.core.currency_registry import sentence_amount  # noqa: PLC0415

        if abs(stated - expected) <= tolerance:
            return None
        return self.fail(
            context,
            "total_matches_lines",
            ref=ref,
            label=label,
            stated=sentence_amount(stated, currency),
            expected=sentence_amount(expected, currency),
        )

    def out_of_range(
        self,
        context: ValidationContext,
        ref: str,
        field: str,
        value: Decimal | None,
        low: Decimal,
        high: Decimal,
    ) -> RuleResult | None:
        """A failure when a stated number lies outside ``[low, high]``; ``None`` value is not judged."""
        if value is None or low <= value <= high:
            return None
        return self.fail(context, "value_in_range", ref=ref, field=field, value=value, low=low, high=high)

    def currency_findings(
        self, context: ValidationContext, ref: str, header: str, others: Iterable[str]
    ) -> list[RuleResult]:
        """Currency stated on the header, and the same on every other record."""
        found = {c for c in others if c}
        if not header:
            return [self.fail(context, "currency_present", ref=ref)]
        mixed = found - {header}
        if mixed:
            codes = ", ".join(sorted({header, *mixed}))
            return [self.fail(context, "currency_consistent", ref=ref, currencies=codes)]
        return []

    def status_findings(
        self,
        context: ValidationContext,
        ref: str,
        previous: Any,
        current: Any,
        allowed: Mapping[str, Iterable[str]],
    ) -> list[RuleResult]:
        """A failure when a status moved along an edge the workflow does not have."""
        if blank(previous) or blank(current) or previous == current:
            return []
        known = allowed.get(str(previous))
        if known is not None and str(current) in set(known):
            return []
        return [self.fail(context, "status_transition", ref=ref, from_status=previous, to_status=current)]


async def enforce_money_rules(
    rule_set: str,
    data: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    project_id: str | None = None,
    operation: str = "write",
    before: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a money rule set at a write point; errors block, warnings are returned.

    Raises HTTP 422 with ``error="money_rules_failed"`` and the failed rules when any
    ERROR fires, HTTP 503 when the rule set is not registered. Returns the WARNING
    findings (possibly empty) for the caller to hand to the client. With ``before`` (the
    stored record) only errors the edit introduces block.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from app.core.i18n import get_locale  # noqa: PLC0415
    from app.core.validation.engine import validation_engine  # noqa: PLC0415

    async def run(payload: dict[str, Any]) -> Any:
        return await validation_engine.validate(
            data=payload,
            rule_sets=[rule_set],
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            metadata={"locale": get_locale(), "workflow": operation},
        )

    report = await run(data)
    if rule_set in report.unsupported_rule_sets:
        raise HTTPException(
            status_code=503,
            detail=f"The {rule_set} validation rules are not loaded on this deployment.",
        )

    async def stored() -> Any:
        return await run(before or {})

    blocking = await introduced_errors(report, stored if before is not None else None)
    raise_rule_failure(report, blocking, error="money_rules_failed", rule_set=rule_set, operation=operation)
    return [finding(r) for r in report.warnings]


async def enforce_rule_set(
    data: dict[str, Any],
    *,
    rule_set: str,
    target_type: str,
    target_id: str,
    error_code: str,
) -> list[dict[str, Any]]:
    """Run one rule set at a write point: errors raise a coded 422, warnings are returned.

    The 422 detail has the same shape as the contracts compliance gate
    (``error``, ``message``, ``rule_sets``, ``status``, ``results``).
    """
    from fastapi import HTTPException, status  # noqa: PLC0415

    from app.core.i18n import get_locale  # noqa: PLC0415
    from app.core.validation.engine import validation_engine  # noqa: PLC0415

    report = await validation_engine.validate(
        data=data,
        rule_sets=[rule_set],
        target_type=target_type,
        target_id=target_id,
        metadata={"locale": get_locale()},
    )
    if rule_set in report.unsupported_rule_sets:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The '{rule_set}' validation rules are not loaded on this deployment.",
        )
    raise_rule_failure(report, error=error_code)
    return [finding(r) for r in report.warnings]
