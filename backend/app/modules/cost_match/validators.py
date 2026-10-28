# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost-match module-specific validation rules.

Matching a foreign bill onto a cost base is fast, which is exactly why it is
dangerous: a few hundred rates are adopted in an afternoon and nothing on the
screen distinguishes a good match from a plausible-looking wrong one. These
rules make the specific ways that goes wrong checkable.

They register under the ``cost_match`` rule set and self-select by the
``scope`` carried on the validated data, so one set serves two passes:

Result scope (``scope == "result"``, one line and its ruling):

* ``cost_match.source_description_present`` - ERROR. A blank pasted line
  cannot be matched to anything, and confirming one adopts a rate for scope
  nobody described.
* ``cost_match.unit_dimension_matches``     - ERROR. The chosen item is priced
  in a different physical dimension from the line (an area rate bought against
  a volume). This is the single most expensive mistake in the whole workflow.
* ``cost_match.rate_present``               - ERROR. The chosen item carries no
  usable unit rate, so the line prices at nothing.
* ``cost_match.decision_has_reviewer``      - ERROR. A ruling with no person
  attached is an auto-applied suggestion, which the platform does not permit.
* ``cost_match.confidence_above_floor``     - WARNING. A suggestion accepted as
  it stands although the matcher scored it below its own review floor.
* ``cost_match.tie_resolved_by_reviewer``   - WARNING. Two candidates scored
  identically and the winner was picked by input order, then confirmed. That
  is not a judgement, it is an accident.
* ``cost_match.source_unit_present``        - WARNING. No unit on the line, so
  the dimension check that guards against area-versus-volume could not run.
* ``cost_match.quantity_present``           - INFO. No quantity, so the line
  carries a rate but can never carry a total.

Run scope (``scope == "run"``, the whole batch):

* ``cost_match.currency_consistent``        - ERROR. Accepted matches priced in
  more than one currency cannot be summed into a bill.
* ``cost_match.duplicate_lines_agree``      - WARNING. The same description
  appears twice and was ruled onto two different cost items, so identical
  scope is priced two ways.
* ``cost_match.review_queue_cleared``       - WARNING. Results still awaiting a
  person. The run is not a priced result yet.

The rules are pure and database-free: :mod:`app.modules.cost_match.service`
builds the plain-dict payloads and calls :func:`evaluate_result` /
:func:`evaluate_run`. Money and quantities arrive as decimal strings and stay
decimal - no float appears here. Unit comparison is delegated to the matcher's
:func:`~app.modules.cost_match.matcher.units_compatible`, so the rule and the
score agree on what "compatible" means instead of each having an opinion.
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
    ValidationReport,
    ValidationRule,
    ValidationStatus,
    rule_registry,
    validation_engine,
)
from app.modules.cost_match.matcher import REVIEW_CONFIDENCE, normalize_text, units_compatible
from app.modules.cost_match.models import (
    DECISION_CONFIRMED,
    DECISION_OVERRIDDEN,
    DECISION_PENDING,
    DECISION_REJECTED,
)
from app.modules.cost_match.schemas import CostMatchFinding, CostMatchValidationReport

logger = logging.getLogger(__name__)

# The rule set every cost-match rule registers under. The service names it on
# every validate call - a registered rule nobody requests never runs.
COST_MATCH_RULE_SET = "cost_match"

# Below this the matcher itself says there is no confident match. Accepting a
# suggestion under it as-is is a judgement worth flagging.
_CONFIDENCE_FLOOR = Decimal(str(REVIEW_CONFIDENCE))

# Rulings that adopt a cost item. ``rejected`` adopts nothing, so the rules
# about rates, units and currencies do not apply to it.
_ADOPTING = (DECISION_CONFIRMED, DECISION_OVERRIDDEN)


# ── payload helpers ─────────────────────────────────────────────────────────


def _dec(value: Any, default: str = "0") -> Decimal:
    """Parse a decimal string / number, falling back to ``default``.

    Validation augments a read path and must never crash it, so an unparseable
    value degrades to the default and the rule reports on what it can see.
    """
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError):
        return Decimal(default)


def _opt_dec(value: Any) -> Decimal | None:
    """Parse an optional decimal, returning ``None`` when absent or unusable.

    The difference from :func:`_dec` matters: a missing rate and a rate of
    zero are different findings, and collapsing them would hide the first.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _scope(context: ValidationContext) -> str:
    """The validation scope carried on the data (``result`` / ``run``)."""
    data = context.data
    if isinstance(data, dict):
        scope = data.get("scope")
        if isinstance(scope, str):
            return scope
    return ""


def _result_payload(context: ValidationContext) -> dict[str, Any]:
    """The single result payload in a result-scope context."""
    data = context.data
    if isinstance(data, dict):
        payload = data.get("result")
        if isinstance(payload, dict):
            return payload
    return {}


def _results(context: ValidationContext) -> list[dict[str, Any]]:
    """Every result payload in a run-scope context."""
    data = context.data
    if isinstance(data, dict):
        rows = data.get("results")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _run(context: ValidationContext) -> dict[str, Any]:
    """The run header in a run-scope context."""
    data = context.data
    if isinstance(data, dict):
        run = data.get("run")
        if isinstance(run, dict):
            return run
    return {}


def _label(payload: dict[str, Any]) -> str:
    """A human-readable handle for one line in a message."""
    line_no = payload.get("line_no")
    description = str(payload.get("source_description") or "").strip()
    if description and len(description) > 60:
        description = description[:57] + "..."
    if line_no and description:
        return f"line {line_no} '{description}'"
    if line_no:
        return f"line {line_no}"
    return description or "line"


def _adopted(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The cost item a ruling adopted, or ``None`` when nothing was adopted.

    Reads the ruling first and the suggestion only as its fallback: a
    confirmation adopts the suggestion, an override adopts something else, and
    a rejection adopts nothing at all. Getting this order wrong is how a rule
    ends up checking a rate the reviewer explicitly refused.
    """
    state = str(payload.get("decision_state") or DECISION_PENDING)
    if state not in _ADOPTING:
        return None
    return {
        "cost_item_id": payload.get("decided_cost_item_id"),
        "code": payload.get("decided_code") or "",
        "description": payload.get("decided_description") or "",
        "unit": payload.get("decided_unit") or "",
        "rate": payload.get("decided_rate"),
        "currency": payload.get("decided_currency") or "",
    }


def _rule_result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying this rule's own identity and severity."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


def _skip(rule: ValidationRule) -> list[RuleResult]:
    """A rule that does not apply to this scope contributes nothing.

    An empty list rather than a passing result: a run-scope rule must not read
    as "passed" on a result pass it never looked at.
    """
    return []


# ── Result-scope rules ──────────────────────────────────────────────────────


class CostMatchSourceDescriptionPresent(ValidationRule):
    """Every submitted line needs text to match on."""

    rule_id = "cost_match.source_description_present"
    name = "Source line carries a description"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A blank pasted line has nothing to match, so any rate adopted for it is unexplained"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        ref = str(payload.get("id") or "") or None
        text = str(payload.get("source_description") or "").strip()
        if text:
            return [_rule_result(self, True, "OK", element_ref=ref, details={"length": len(text)})]
        return [
            _rule_result(
                self,
                False,
                (
                    f"Line {payload.get('line_no')} was submitted with no description, so nothing "
                    f"could be matched against the cost base."
                ),
                element_ref=ref,
                suggestion="Remove the empty row from the pasted bill, or type the scope it stands for.",
                details={"line_no": payload.get("line_no"), "source_ref": payload.get("source_ref")},
            )
        ]


class CostMatchSourceUnitPresent(ValidationRule):
    """A line without a unit cannot be dimension-checked."""

    rule_id = "cost_match.source_unit_present"
    name = "Source line carries a unit"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Without a unit on the line, the area-versus-volume guard has nothing to compare"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        ref = str(payload.get("id") or "") or None
        unit = str(payload.get("source_unit") or "").strip()
        if unit:
            return [_rule_result(self, True, "OK", element_ref=ref, details={"source_unit": unit})]
        return [
            _rule_result(
                self,
                False,
                (
                    f"{_label(payload)} carries no unit, so the match could not be checked against "
                    f"the unit of the cost item it was priced from."
                ),
                element_ref=ref,
                suggestion="Add the unit from the subcontractor's bill so the dimension check can run.",
                details={"line_no": payload.get("line_no")},
            )
        ]


class CostMatchUnitDimensionMatches(ValidationRule):
    """An adopted cost item must be priced in the line's own dimension."""

    rule_id = "cost_match.unit_dimension_matches"
    name = "Adopted rate is priced in the line's dimension"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Buying a volume against an area rate (or a count against a length) misprices the line outright"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        adopted = _adopted(payload)
        if adopted is None:
            # Nothing adopted yet: there is no pairing to check.
            return _skip(self)
        ref = str(payload.get("id") or "") or None
        source_unit = str(payload.get("source_unit") or "")
        adopted_unit = str(adopted.get("unit") or "")
        compatible = units_compatible(source_unit, adopted_unit)
        if compatible is not False:
            # True (same dimension) passes; None means one side is a unit the
            # platform does not recognise, which is a gap the
            # ``source_unit_present`` rule and the reviewer handle, not a
            # mismatch we may assert.
            return [
                _rule_result(
                    self,
                    True,
                    "OK",
                    element_ref=ref,
                    details={
                        "source_unit": source_unit,
                        "adopted_unit": adopted_unit,
                        "comparable": compatible is True,
                    },
                )
            ]
        return [
            _rule_result(
                self,
                False,
                (
                    f"{_label(payload)} is measured in '{source_unit}' but was priced from cost item "
                    f"'{adopted.get('code')}' quoted per '{adopted_unit}'. Those are different physical "
                    f"quantities, so the money on this line is wrong by whatever the two units differ by."
                ),
                element_ref=ref,
                suggestion="Override onto an item quoted in the line's own unit, or restate the quantity in the item's unit.",
                details={
                    "source_unit": source_unit,
                    "adopted_unit": adopted_unit,
                    "adopted_code": adopted.get("code"),
                    "decision_state": payload.get("decision_state"),
                },
            )
        ]


class CostMatchRatePresent(ValidationRule):
    """An adopted cost item must carry a usable unit rate."""

    rule_id = "cost_match.rate_present"
    name = "Adopted cost item is priced"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A matched item with no rate prices the line at zero while looking fully resolved"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        adopted = _adopted(payload)
        if adopted is None:
            return _skip(self)
        ref = str(payload.get("id") or "") or None
        rate = _opt_dec(adopted.get("rate"))
        if rate is not None and rate > 0:
            return [
                _rule_result(
                    self,
                    True,
                    "OK",
                    element_ref=ref,
                    details={"rate": str(rate), "currency": adopted.get("currency")},
                )
            ]
        return [
            _rule_result(
                self,
                False,
                (
                    f"{_label(payload)} was priced from cost item '{adopted.get('code')}', which carries "
                    f"{'no unit rate at all' if rate is None else 'a unit rate of zero'}. The line reads as "
                    f"resolved but contributes nothing to the bill."
                ),
                element_ref=ref,
                suggestion="Pick a priced item from the alternatives, or set the rate on the cost item first.",
                details={
                    "adopted_code": adopted.get("code"),
                    "rate": None if rate is None else str(rate),
                    "currency": adopted.get("currency"),
                },
            )
        ]


class CostMatchDecisionHasReviewer(ValidationRule):
    """Every ruling must name the person who made it."""

    rule_id = "cost_match.decision_has_reviewer"
    name = "Ruling is attributed to a person"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A decided result with no reviewer on it is a suggestion that applied itself"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        state = str(payload.get("decision_state") or DECISION_PENDING)
        if state == DECISION_PENDING:
            return _skip(self)
        ref = str(payload.get("id") or "") or None
        reviewer = payload.get("decided_by")
        if reviewer:
            return [
                _rule_result(
                    self,
                    True,
                    "OK",
                    element_ref=ref,
                    details={"decision_state": state, "decided_by": str(reviewer)},
                )
            ]
        return [
            _rule_result(
                self,
                False,
                (
                    f"{_label(payload)} is recorded as '{state}' but carries no reviewer. A machine "
                    f"suggestion that reached that state without a person behind it must not be priced."
                ),
                element_ref=ref,
                suggestion="Re-open the line and let a reviewer rule on it so the decision is attributable.",
                details={"decision_state": state},
            )
        ]


class CostMatchConfidenceAboveFloor(ValidationRule):
    """A weak suggestion should be overridden, not simply confirmed."""

    rule_id = "cost_match.confidence_above_floor"
    name = "Confirmed suggestion scored above the review floor"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Accepting a suggestion the matcher scored below its own floor adopts a rate on almost no evidence"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        state = str(payload.get("decision_state") or DECISION_PENDING)
        if state != DECISION_CONFIRMED:
            # An override is the reviewer's own choice and carries its own
            # evidence; a rejection adopts nothing. Only a straight
            # confirmation leans on the score.
            return _skip(self)
        ref = str(payload.get("id") or "") or None
        confidence = _dec(payload.get("confidence_at_decision", payload.get("confidence")))
        if confidence >= _CONFIDENCE_FLOOR:
            return [_rule_result(self, True, "OK", element_ref=ref, details={"confidence": str(confidence)})]
        return [
            _rule_result(
                self,
                False,
                (
                    f"{_label(payload)} was confirmed as it stands at a confidence of {confidence}, below "
                    f"the {_CONFIDENCE_FLOOR} floor at which the matcher stops claiming a match at all."
                ),
                element_ref=ref,
                suggestion="Search the base for the right item and override, or reject the line so it is not priced.",
                details={"confidence": str(confidence), "floor": str(_CONFIDENCE_FLOOR)},
            )
        ]


class CostMatchTieResolvedByReviewer(ValidationRule):
    """A tied score means the winner was picked by input order."""

    rule_id = "cost_match.tie_resolved_by_reviewer"
    name = "Tied suggestion was chosen deliberately"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "When two candidates score identically the shown winner is an ordering artefact, not a judgement"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        if not bool(payload.get("tie")):
            return _skip(self)
        state = str(payload.get("decision_state") or DECISION_PENDING)
        if state != DECISION_CONFIRMED:
            return _skip(self)
        ref = str(payload.get("id") or "") or None
        return [
            _rule_result(
                self,
                False,
                (
                    f"{_label(payload)} had two cost items scoring identically. The one that was confirmed "
                    f"won on input order alone, so the choice between them has not actually been made."
                ),
                element_ref=ref,
                suggestion="Compare the tied alternatives and override onto the intended one, even if it is the same item.",
                details={
                    "confidence": str(_dec(payload.get("confidence"))),
                    "alternative_count": int(payload.get("alternative_count") or 0),
                    "suggested_code": payload.get("suggested_code"),
                },
            )
        ]


class CostMatchQuantityPresent(ValidationRule):
    """A line with no quantity carries a rate but never a total."""

    rule_id = "cost_match.quantity_present"
    name = "Source line carries a quantity"
    standard = "universal"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "Without a quantity the matched rate can never become money on the bill"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "result":
            return _skip(self)
        payload = _result_payload(context)
        ref = str(payload.get("id") or "") or None
        quantity = _opt_dec(payload.get("source_quantity"))
        if quantity is not None and quantity > 0:
            return [_rule_result(self, True, "OK", element_ref=ref, details={"quantity": str(quantity)})]
        return [
            _rule_result(
                self,
                False,
                (
                    f"{_label(payload)} has no quantity, so whatever rate is adopted for it contributes "
                    f"nothing to the bill total."
                ),
                element_ref=ref,
                suggestion="Carry the quantity across from the subcontractor's bill, or drop the line.",
                details={"quantity": None if quantity is None else str(quantity)},
            )
        ]


# ── Run-scope rules ─────────────────────────────────────────────────────────


class CostMatchCurrencyConsistent(ValidationRule):
    """A run's adopted rates must resolve to one currency to be summable."""

    rule_id = "cost_match.currency_consistent"
    name = "Adopted rates share one currency"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Lines priced from cost items in different currencies cannot be added into one bill"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "run":
            return _skip(self)
        rows = _results(context)
        adopted = [(r, _adopted(r)) for r in rows]
        currencies = sorted(
            {
                str(item.get("currency") or "").strip().upper()
                for _row, item in adopted
                if item is not None and item.get("currency")
            }
        )
        if len(currencies) <= 1:
            return [_rule_result(self, True, "OK", details={"currencies": currencies})]
        return [
            _rule_result(
                self,
                False,
                (
                    f"This run has adopted rates in {len(currencies)} currencies "
                    f"({', '.join(currencies)}). Totalling the matched bill would add unlike units."
                ),
                suggestion="Match the whole bill against one regional base, or convert before the rates reach the bill.",
                details={"currencies": currencies, "decided_count": sum(1 for _r, i in adopted if i is not None)},
            )
        ]


class CostMatchDuplicateLinesAgree(ValidationRule):
    """The same description twice should be priced the same way twice."""

    rule_id = "cost_match.duplicate_lines_agree"
    name = "Repeated descriptions were priced consistently"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "One scope appearing twice and ruled onto two different cost items prices it two ways"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "run":
            return _skip(self)
        rows = _results(context)
        if not rows:
            return _skip(self)
        # Group by the same normalisation the matcher scores on, so a
        # difference in case, accents or spacing does not hide a duplicate.
        by_text: dict[str, set[str]] = {}
        lines_by_text: dict[str, list[Any]] = {}
        for row in rows:
            item = _adopted(row)
            if item is None:
                continue
            key = normalize_text(str(row.get("source_description") or ""))
            if not key:
                continue
            by_text.setdefault(key, set()).add(str(item.get("cost_item_id") or item.get("code") or ""))
            lines_by_text.setdefault(key, []).append(row.get("line_no"))
        conflicts = {text: sorted(items) for text, items in by_text.items() if len(items) > 1}
        if not conflicts:
            return [_rule_result(self, True, "OK", details={"distinct_decided_descriptions": len(by_text)})]
        sample = sorted(conflicts)[:8]
        return [
            _rule_result(
                self,
                False,
                (
                    f"{len(conflicts)} description(s) appear more than once in this run and were priced from "
                    f"different cost items. The same scope is carrying two different rates."
                ),
                suggestion="Open the repeated lines together and settle on one cost item for them.",
                details={
                    "conflict_count": len(conflicts),
                    "examples": [{"description": text, "line_numbers": lines_by_text.get(text, [])} for text in sample],
                },
            )
        ]


class CostMatchReviewQueueCleared(ValidationRule):
    """A run with lines still in the queue is not a priced result."""

    rule_id = "cost_match.review_queue_cleared"
    name = "Review queue has been worked through"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Lines still awaiting a person are neither priced nor knowingly excluded"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "run":
            return _skip(self)
        rows = _results(context)
        if not rows:
            return _skip(self)
        pending = [r for r in rows if str(r.get("decision_state") or DECISION_PENDING) == DECISION_PENDING]
        run = _run(context)
        if not pending:
            return [
                _rule_result(
                    self,
                    True,
                    "OK",
                    element_ref=str(run.get("id") or "") or None,
                    details={"result_count": len(rows)},
                )
            ]
        rejected = sum(1 for r in rows if str(r.get("decision_state") or "") == DECISION_REJECTED)
        return [
            _rule_result(
                self,
                False,
                (
                    f"{len(pending)} of {len(rows)} line(s) in this run are still waiting for a reviewer. "
                    f"Nothing is applied until a person rules on them."
                ),
                element_ref=str(run.get("id") or "") or None,
                suggestion="Work the needs-review queue, then confirm, override or reject each remaining line.",
                details={
                    "pending": len(pending),
                    "total": len(rows),
                    "rejected": rejected,
                    "pending_line_numbers": [r.get("line_no") for r in pending[:16]],
                },
            )
        ]


# ── Registration ────────────────────────────────────────────────────────────

_COST_MATCH_RULES: tuple[ValidationRule, ...] = (
    CostMatchSourceDescriptionPresent(),
    CostMatchSourceUnitPresent(),
    CostMatchUnitDimensionMatches(),
    CostMatchRatePresent(),
    CostMatchDecisionHasReviewer(),
    CostMatchConfidenceAboveFloor(),
    CostMatchTieResolvedByReviewer(),
    CostMatchQuantityPresent(),
    CostMatchCurrencyConsistent(),
    CostMatchDuplicateLinesAgree(),
    CostMatchReviewQueueCleared(),
)


def register_cost_match_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites by rule id, so a re-import or a hot
    reload re-registers cleanly. Called at import time below (the module
    loader imports every module's ``validators``) and again from the module's
    ``on_startup`` hook, because the platform has two registration routes and
    a rule that only takes one of them is dormant in the other deployment.
    """
    for rule in _COST_MATCH_RULES:
        rule_registry.register(rule, [COST_MATCH_RULE_SET])
    logger.debug("Registered %d cost_match validation rules", len(_COST_MATCH_RULES))


register_cost_match_rules()


# ── Orchestration used by the service ───────────────────────────────────────


def _finding(result: RuleResult) -> CostMatchFinding:
    """Render one failing rule result as a UI-ready finding."""
    return CostMatchFinding(
        rule_id=result.rule_id,
        severity=result.severity.value,
        category=result.category.value,
        message=result.message,
        key=f"cost_match.validation.{result.rule_id}",
        element_ref=result.element_ref,
        suggestion=result.suggestion,
        context=dict(result.details or {}),
    )


def _to_report(
    report: ValidationReport,
    *,
    target_type: str,
    target_id: Any,
) -> CostMatchValidationReport:
    """Collapse an engine report into the module's response shape."""
    return CostMatchValidationReport(
        target_type=target_type,
        target_id=target_id,
        status=report.status.value,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        info_count=len(report.infos),
        passed_count=len(report.passed_rules),
        findings=[_finding(r) for r in report.results if not r.passed and not r.is_engine_error],
        unsupported_rule_sets=list(report.unsupported_rule_sets),
    )


def _degraded(target_type: str, target_id: Any) -> CostMatchValidationReport:
    """The report returned when the engine itself could not run.

    SKIPPED, not PASSED: nothing was checked, and saying otherwise would turn
    an infrastructure failure into a clean bill of health on a bill that is
    about to be priced.
    """
    return CostMatchValidationReport(
        target_type=target_type,
        target_id=target_id,
        status=ValidationStatus.SKIPPED.value,
        error_count=0,
        warning_count=0,
        info_count=0,
        passed_count=0,
        findings=[],
        unsupported_rule_sets=[COST_MATCH_RULE_SET],
    )


async def evaluate_result(
    payload: dict[str, Any],
    *,
    project_id: str | None = None,
    locale: str = "",
) -> CostMatchValidationReport:
    """Run the result-scope rules over one matched line.

    Args:
        payload: Carries ``result`` - the row plus the ruling in force on it,
            with decimal-string money and quantities.
        project_id: Project the run belongs to, for report attribution.
        locale: Reader's locale, passed through as report metadata.

    Returns:
        The module's validation report for that one line.
    """
    result = payload.get("result") or {}
    target_id = result.get("id")
    data = {"scope": "result", **payload}
    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[COST_MATCH_RULE_SET],
            target_type="cost_match_result",
            target_id=str(target_id or ""),
            project_id=project_id,
            metadata={"locale": locale},
        )
    except Exception:  # noqa: BLE001 - validation augments; never break the caller
        logger.warning("cost_match result validation failed for %s", target_id, exc_info=True)
        return _degraded("cost_match_result", target_id)
    return _to_report(report, target_type="cost_match_result", target_id=target_id)


async def evaluate_run(
    payload: dict[str, Any],
    *,
    project_id: str | None = None,
    locale: str = "",
) -> CostMatchValidationReport:
    """Run both scopes over a whole run.

    The run-scope rules see the batch as a batch (currency spread, repeated
    descriptions ruled two ways, how much of the queue is left). The
    result-scope rules are applied to every line by the caller and merged in,
    because a bill is only as sound as its worst line.

    Args:
        payload: Carries ``run`` (the header) and ``results`` (every line with
            the ruling in force on it).
        project_id: Project the run belongs to, for report attribution.
        locale: Reader's locale, passed through as report metadata.

    Returns:
        The module's validation report for the run.
    """
    run = payload.get("run") or {}
    target_id = run.get("id")
    data = {"scope": "run", **payload}
    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[COST_MATCH_RULE_SET],
            target_type="cost_match_run",
            target_id=str(target_id or ""),
            project_id=project_id,
            metadata={"locale": locale},
        )
    except Exception:  # noqa: BLE001 - validation augments; never break the caller
        logger.warning("cost_match run validation failed for %s", target_id, exc_info=True)
        return _degraded("cost_match_run", target_id)
    return _to_report(report, target_type="cost_match_run", target_id=target_id)


def merge_reports(
    reports: list[CostMatchValidationReport],
    *,
    target_type: str,
    target_id: Any,
) -> CostMatchValidationReport:
    """Combine several reports into one without losing a single finding.

    Used to fold every line's result-scope report into the run-scope one. The
    status is the worst of the parts: one ERROR anywhere makes the whole run
    ERRORS, because a bill with one wrongly dimensioned line is not "mostly
    fine".
    """
    findings: list[CostMatchFinding] = []
    errors = warnings = infos = passed = 0
    unsupported: list[str] = []
    for report in reports:
        findings.extend(report.findings)
        errors += report.error_count
        warnings += report.warning_count
        infos += report.info_count
        passed += report.passed_count
        for rule_set in report.unsupported_rule_sets:
            if rule_set not in unsupported:
                unsupported.append(rule_set)
    if unsupported and not findings and not passed:
        status = ValidationStatus.SKIPPED.value
    elif errors:
        status = ValidationStatus.ERRORS.value
    elif warnings:
        status = ValidationStatus.WARNINGS.value
    elif infos:
        status = ValidationStatus.INFO.value
    else:
        status = ValidationStatus.PASSED.value
    return CostMatchValidationReport(
        target_type=target_type,
        target_id=target_id,
        status=status,
        error_count=errors,
        warning_count=warnings,
        info_count=infos,
        passed_count=passed,
        findings=findings,
        unsupported_rule_sets=unsupported,
    )
