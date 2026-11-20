# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the one tender model (rule sets ``tender``, ``tender_issue``, ``tender_award``).

Two kinds of rule live here:

* **Merge rules** on a canonical tender (payload from :func:`tender_payload`):
  the copy of an old package reconciles with its source, a free bid line names
  what it prices, the award goes to a bidder of the package, and an old status
  with no canonical equivalent is shown rather than silently mapped.
* **The quote rules under their new ids.** The ``rfq.*`` rules move to
  ``tender.*``; the old ids stay registered and :data:`RULE_ALIASES` maps each
  old id to its new one, so stored results and saved filters keep resolving.

Check functions are pure (payload dict in, findings out); the rule classes wrap
them for the engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

TENDER_RULE_SET = "tender"
TENDER_ISSUE_RULE_SET = "tender_issue"
TENDER_AWARD_RULE_SET = "tender_award"

#: Old rule id -> new rule id. Filled by :func:`register_tender_validation_rules`.
RULE_ALIASES: dict[str, str] = {}


@dataclass(frozen=True)
class Finding:
    """One failed check; ``params`` fill the message."""

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    try:
        out = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def check_copy_reconciled(payload: dict[str, Any]) -> list[Finding]:
    """A copied package carries as many bids, totalling the same, as its source."""
    copy = payload.get("copy") or {}
    if not copy:
        return []
    src_n, dst_n = int(copy.get("bids_source") or 0), int(copy.get("bids_target") or 0)
    src_t, dst_t = _dec(copy.get("total_source")) or Decimal(0), _dec(copy.get("total_target")) or Decimal(0)
    if src_n == dst_n and src_t == dst_t:
        return []
    return [
        Finding(
            str(payload.get("code") or ""),
            {
                "bids_source": str(src_n),
                "bids_target": str(dst_n),
                "total_source": str(src_t),
                "total_target": str(dst_t),
            },
        )
    ]


def check_free_lines_described(payload: dict[str, Any]) -> list[Finding]:
    """A bid line outside the package scope says what it prices and in which unit."""
    out: list[Finding] = []
    for line in payload.get("submission_lines") or []:
        if line.get("line_item_id"):
            continue
        missing = [k for k in ("description", "unit") if not str(line.get(k) or "").strip()]
        if missing:
            out.append(Finding(str(line.get("id") or ""), {"missing": ", ".join(missing)}))
    return out


def check_award_bidder_in_package(payload: dict[str, Any]) -> list[Finding]:
    """The awarded bidder is one of the package's own bidders."""
    award = payload.get("award") or {}
    winner = str(award.get("awarded_bidder_id") or "")
    if not winner:
        return []
    bidders = {str(b.get("id")) for b in payload.get("bidders") or []}
    return [] if winner in bidders else [Finding(str(payload.get("code") or ""), {"bidder": winner})]


#: Old statuses the copy knows; anything else became ``closed`` and is shown.
KNOWN_LEGACY_STATUSES = frozenset(
    {"draft", "issued", "collecting", "evaluating", "awarded", "closed"}
    | {"published", "bids_received", "po_issued", "completed", "cancelled"}
)


def check_legacy_status_mapped(payload: dict[str, Any]) -> list[Finding]:
    """An old status with no canonical equivalent is named, not hidden behind ``closed``."""
    legacy = (payload.get("metadata") or {}).get("legacy") or {}
    status = str(legacy.get("status") or "").strip().lower()
    if not legacy or not status or status in KNOWN_LEGACY_STATUSES:
        return []
    return [Finding(str(payload.get("code") or ""), {"status": status})]


def tender_payload(detail: Any, copy_line: Any = None) -> dict[str, Any]:
    """Payload for the merge rules from a :class:`TenderDetail` and an optional reconcile line."""
    data = detail.model_dump(mode="json") if hasattr(detail, "model_dump") else dict(detail)
    pkg = data.get("package") or {}
    payload = {
        "code": pkg.get("code"),
        "metadata": pkg.get("metadata") or {},
        "bidders": data.get("bidders") or [],
        "submission_lines": data.get("submission_lines") or [],
        "award": data.get("award") or {},
    }
    if copy_line is not None:
        payload["copy"] = {
            "bids_source": copy_line.bids_source,
            "bids_target": copy_line.bids_target,
            "total_source": str(copy_line.total_source),
            "total_target": str(copy_line.total_target),
        }
    return payload


def _result(rule: ValidationRule, passed: bool, message: str, *, ref: str | None = None, **details: Any) -> RuleResult:
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


def _payload(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


class TenderCopyReconciled(ValidationRule):
    """The canonical copy of an old package matches its source."""

    rule_id = "tender.copy_reconciled"
    name = "Tender Copy Reconciled"
    standard = "tender"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a copied tender whose bid count or bid total differs from the package it was copied from."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        findings = check_copy_reconciled(_payload(context))
        if not findings:
            return [_result(self, True, "The copy carries the same bids and total as its source.")]
        f = findings[0]
        return [
            _result(
                self,
                False,
                (
                    f"Tender {f.element_ref}: {f.params['bids_target']} of {f.params['bids_source']} bids copied, "
                    f"total {f.params['total_target']} against {f.params['total_source']}."
                ),
                ref=f.element_ref,
                **f.params,
            )
        ]


class TenderFreeLinesDescribed(ValidationRule):
    """A bid line outside the scope names what it prices."""

    rule_id = "tender.free_line_described"
    name = "Tender Free Line Described"
    standard = "tender"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a priced line with no scope line and no description or unit; nobody can compare it."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        findings = check_free_lines_described(_payload(context))
        if not findings:
            return [_result(self, True, "Every line outside the scope says what it prices.")]
        return [
            _result(self, False, f"A bid line outside the scope has no {f.params['missing']}.", ref=f.element_ref)
            for f in findings
        ]


class TenderAwardBidderInPackage(ValidationRule):
    """The award names a bidder of the same package."""

    rule_id = "tender.award_bidder_in_package"
    name = "Tender Award Bidder In Package"
    standard = "tender"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags an award whose bidder is not one of the package's bidders."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        findings = check_award_bidder_in_package(_payload(context))
        if not findings:
            return [_result(self, True, "The award goes to a bidder of this package.")]
        f = findings[0]
        return [
            _result(self, False, f"Tender {f.element_ref} is awarded to a bidder it never invited.", ref=f.element_ref)
        ]


class TenderLegacyStatusMapped(ValidationRule):
    """An old status with no canonical equivalent is shown."""

    rule_id = "tender.legacy_status_mapped"
    name = "Tender Legacy Status Mapped"
    standard = "tender"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a copied tender whose old status had no equivalent and was read as closed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        findings = check_legacy_status_mapped(_payload(context))
        if not findings:
            return [_result(self, True, "The old status maps to a tender status.")]
        f = findings[0]
        return [
            _result(
                self,
                False,
                f"Tender {f.element_ref} had the status '{f.params['status']}', which is now shown as closed.",
                ref=f.element_ref,
            )
        ]


_MERGE_RULES: tuple[ValidationRule, ...] = (
    TenderCopyReconciled(),
    TenderFreeLinesDescribed(),
    TenderAwardBidderInPackage(),
    TenderLegacyStatusMapped(),
)

#: Old quote rule sets -> their tender equivalents.
_SET_MOVES = {"rfq_issue": TENDER_ISSUE_RULE_SET, "rfq_award": TENDER_AWARD_RULE_SET}


def _renamed(rule: ValidationRule, new_id: str) -> ValidationRule:
    """A copy of ``rule`` registered under ``new_id``; same checks, same messages."""
    cls = type(rule)
    clone_cls = type(f"Tender{cls.__name__}", (cls,), {"rule_id": new_id, "standard": "tender"})
    try:
        return clone_cls()
    except TypeError:
        clone = object.__new__(clone_cls)
        clone.__dict__.update(rule.__dict__)
        return clone


def register_tender_validation_rules() -> None:
    """Register the merge rules and the ``tender.*`` ids of the quote rules. Idempotent.

    The quote rules come from ``rfq_bidding``; their old ids stay registered,
    so a caller that still asks for ``rfq_issue`` / ``rfq_award`` sees no change.
    """
    for rule in _MERGE_RULES:
        rule_registry.register(rule, [TENDER_RULE_SET, TENDER_AWARD_RULE_SET])
    try:
        from app.modules.rfq_bidding.validators import register_rfq_validation_rules  # noqa: PLC0415

        register_rfq_validation_rules()
    except Exception:  # noqa: BLE001 - the merge rules stand without the quote rules
        logger.warning("rfq rules unavailable; tender.* aliases not registered", exc_info=True)
        return
    for old_set, new_set in _SET_MOVES.items():
        for rule in rule_registry.get_rules_for_sets([old_set]):
            if not rule.rule_id.startswith("rfq."):
                continue
            new_id = "tender." + rule.rule_id.removeprefix("rfq.")
            RULE_ALIASES[rule.rule_id] = new_id
            existing = rule_registry.get_rule(new_id)
            rule_registry.register(existing or _renamed(rule, new_id), [new_set, TENDER_RULE_SET])


def resolve_rule_id(rule_id: str) -> str:
    """The current id of a rule, following an old ``rfq.*`` alias."""
    return RULE_ALIASES.get(rule_id, rule_id)
