# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync validation rules (rule set ``accounting_sync``).

* ``accounting_sync.unmapped_account`` - ERROR. A document line or its control
  account has a posting category with no account code.
* ``accounting_sync.tax_code_mismatch`` - ERROR. A line's tax rate differs from the
  rate of its tax code in the dated tax seed, or the code has no external tax key.
* ``accounting_sync.closed_period`` - ERROR. The document date is on or before the
  connection's lock date (books closed).
* ``accounting_sync.total_mismatch`` - ERROR. The total the accounting system
  computed after the push differs from the platform total.
* ``accounting_sync.contact_missing_tax_id`` - WARNING. A business counterparty has
  no tax id.

Rules read the plain snapshot of
:meth:`app.modules.accounting_sync.service.AccountingSyncService.validation_snapshot`.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
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

logger = logging.getLogger(__name__)

RULE_SET = "accounting_sync"
TOLERANCE = Decimal("0.01")


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _docs(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    rows = data.get("documents")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _result(rule: ValidationRule, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


class UnmappedAccount(ValidationRule):
    rule_id = "accounting_sync.unmapped_account"
    name = "Every Posting Category Has An Account"
    standard = "accounting"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Each line and control account of a document maps to an account code before it is pushed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for d in _docs(context):
            missing = sorted({c for c in d.get("categories", []) if not (d.get("accounts") or {}).get(c)})
            ref = d.get("number")
            if missing:
                out.append(
                    _result(
                        self,
                        False,
                        f"Document {ref} has no account for: {', '.join(missing)}.",
                        ref,
                        record_id=d.get("record_id"),
                        categories=missing,
                    )
                )
            else:
                out.append(_result(self, True, "OK", ref))
        return out


class TaxCodeMismatch(ValidationRule):
    rule_id = "accounting_sync.tax_code_mismatch"
    name = "Tax Rate Matches Its Tax Code"
    standard = "accounting"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "A line's tax rate equals the rate in force for its tax code, and the code maps to an external tax key."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for d in _docs(context):
            ref = d.get("number")
            problems = []
            for ln in d.get("lines") or []:
                rate, seed = _dec(ln.get("tax_rate")), _dec(ln.get("seed_rate"))
                if seed is not None and rate is not None and abs(rate - seed) > Decimal("0.0001"):
                    problems.append(f"{ln.get('tax_code')} at {rate}% but the code is {seed}%")
                if ln.get("tax_key") is None:
                    problems.append(f"{ln.get('tax_code')} has no external tax key")
            if problems:
                out.append(
                    _result(
                        self,
                        False,
                        f"Document {ref}: " + "; ".join(sorted(set(problems))) + ".",
                        ref,
                        record_id=d.get("record_id"),
                    )
                )
            else:
                out.append(_result(self, True, "OK", ref))
        return out


class ClosedPeriod(ValidationRule):
    rule_id = "accounting_sync.closed_period"
    name = "No Posting Into A Closed Period"
    standard = "accounting"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A document dated on or before the lock date of the books is not posted."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        lock = str(data.get("lock_date") or "")
        out = []
        for d in _docs(context):
            ref = d.get("number")
            day = str(d.get("doc_date") or "")
            if lock and day and day <= lock:
                out.append(
                    _result(
                        self,
                        False,
                        f"Document {ref} is dated {day}; the books are closed through {lock}.",
                        ref,
                        record_id=d.get("record_id"),
                    )
                )
            else:
                out.append(_result(self, True, "OK", ref))
        return out


class TotalMismatch(ValidationRule):
    rule_id = "accounting_sync.total_mismatch"
    name = "Total Matches After Push"
    standard = "accounting"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "The total the accounting system computed equals the platform total, and the lines add up to the document."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for d in _docs(context):
            ref = d.get("number")
            gross, recorded, remote = (
                _dec(d.get("gross_total")),
                _dec(d.get("recorded_total")),
                _dec(d.get("remote_total")),
            )
            if remote is not None and gross is not None and abs(remote - gross) > TOLERANCE:
                out.append(
                    _result(
                        self,
                        False,
                        f"Document {ref}: the accounting system shows {remote}, the platform {gross}.",
                        ref,
                        record_id=d.get("record_id"),
                    )
                )
            elif recorded is not None and gross is not None and abs(recorded - gross) > TOLERANCE:
                out.append(
                    _result(
                        self,
                        False,
                        f"Document {ref}: lines add up to {gross}, the document says {recorded}.",
                        ref,
                        record_id=d.get("record_id"),
                    )
                )
            else:
                out.append(_result(self, True, "OK", ref))
        return out


class ContactMissingTaxId(ValidationRule):
    rule_id = "accounting_sync.contact_missing_tax_id"
    name = "Business Contact Has A Tax Id"
    standard = "accounting"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A company customer or supplier carries its VAT or tax number before it is pushed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        seen: set[str] = set()
        for d in _docs(context):
            c = d.get("contact") or {}
            key = str(c.get("record_id") or "")
            if key in seen:
                continue
            seen.add(key)
            name = c.get("name") or key
            if c.get("is_business", True) and not c.get("tax_id"):
                out.append(_result(self, False, f"Contact {name} has no tax id.", name, contact_id=key))
            else:
                out.append(_result(self, True, "OK", name))
        return out


_RULES: tuple[ValidationRule, ...] = (
    UnmappedAccount(),
    TaxCodeMismatch(),
    ClosedPeriod(),
    TotalMismatch(),
    ContactMissingTaxId(),
)
RULE_IDS = tuple(r.rule_id for r in _RULES)


def register_accounting_sync_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Run the rule set over a snapshot and return the failing results only."""
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[RULE_SET], target_type="accounting_sync", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("accounting_sync validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]


__all__ = ["RULE_IDS", "RULE_SET", "evaluate", "register_accounting_sync_rules"]
