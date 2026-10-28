# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Formwork module-specific validation rules.

A formwork rate is one of the easiest numbers on a concrete job to get wrong,
and wrong in a direction that is invisible until the panels arrive on site.
These rules make the assumptions behind the rate checkable instead of leaving
them in the estimator's head.

All rules register under the ``formwork`` rule set and self-select by the
``scope`` carried on the validated data, so one set serves two passes:

Assignment scope (``scope == "assignment"``, one assignment plus its system
and its pour cycle):

* ``formwork.rate_present``            - ERROR. A system priced at zero makes
                                         the whole assignment free.
* ``formwork.reuse_within_limit``      - ERROR. Amortising over more uses than
                                         the panels survive under-prices the job.
* ``formwork.reuse_near_limit``        - WARNING. Within 10 percent of the cap
                                         leaves no room for damage or rework.
* ``formwork.reuse_supported_by_schedule`` - WARNING. The pour cycle does not
                                         deliver the turnaround being claimed.
* ``formwork.schedule_area_matches``   - WARNING. Pour areas and the priced area
                                         disagree by more than 5 percent.
* ``formwork.pour_numbers_unique``     - ERROR. Two pours numbered the same.
* ``formwork.strip_time_respected``    - WARNING. Consecutive pours closer than
                                         the striking time - the same set cannot
                                         serve both.
* ``formwork.waste_within_band``       - WARNING. Waste outside the plausible
                                         0 to 15 percent band.
* ``formwork.boq_position_linked``     - INFO. Not linked to a BOQ position, so
                                         it never reaches the bill.

Project scope (``scope == "project"``, every assignment on one project):

* ``formwork.currency_consistent``     - ERROR. Assignments priced in more than
                                         one currency cannot be summed.
* ``formwork.boq_position_unique``     - WARNING. Two assignments charging the
                                         same BOQ position double-count it.

The rules are pure and DB-free: :mod:`app.modules.formwork.service` builds the
plain-dict payloads and calls :func:`evaluate_assignment` /
:func:`evaluate_project`, which run them through the core engine. Quantities
and money arrive as decimal strings and stay decimal - no float appears here.
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

# The amount format the built-in rules already use: the decimals the currency
# genuinely has, thousands separators, and the code. Taken from the core rules
# rather than rewritten here, so two findings on one screen cannot disagree
# about what an amount looks like. Importing it registers nothing.
from app.core.validation.rules import _fmt_money
from app.modules.formwork.schemas import FormworkFinding, FormworkValidationReport

logger = logging.getLogger(__name__)

# The rule set every formwork rule registers under. The service names it on
# every validate call - a registered rule that nobody requests never runs.
FORMWORK_RULE_SET = "formwork"

# Reuse counts within this fraction of the manufacturer cap leave no headroom
# for panel damage, rework or a re-sequenced programme.
_REUSE_HEADROOM = Decimal("0.10")

# Priced area and the sum of the pour areas may drift by this much before the
# cycle is treated as describing a different scope from the one being priced.
_AREA_TOLERANCE = Decimal("0.05")

# Formwork waste above this is either a data-entry slip or an unstated
# allowance for something other than offcuts.
_WASTE_CEILING = Decimal("15")


# ── payload helpers ─────────────────────────────────────────────────────────


def _dec(value: Any, default: str = "0") -> Decimal:
    """Parse a decimal string / number, falling back to ``default``.

    Validation must never crash the read path it augments, so an unparseable
    value degrades to the default and the rule reports on what it can see.
    """
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError):
        return Decimal(default)


def _scope(context: ValidationContext) -> str:
    """The validation scope carried on the data (``assignment`` / ``project``)."""
    data = context.data
    if isinstance(data, dict):
        scope = data.get("scope")
        if isinstance(scope, str):
            return scope
    return ""


def _assignment(context: ValidationContext) -> dict[str, Any]:
    """The single assignment payload in an assignment-scope context."""
    data = context.data
    if isinstance(data, dict):
        assignment = data.get("assignment")
        if isinstance(assignment, dict):
            return assignment
    return {}


def _pours(context: ValidationContext) -> list[dict[str, Any]]:
    """The pour-cycle lines in an assignment-scope context."""
    data = context.data
    if isinstance(data, dict):
        pours = data.get("pours")
        if isinstance(pours, list):
            return [p for p in pours if isinstance(p, dict)]
    return []


def _assignments(context: ValidationContext) -> list[dict[str, Any]]:
    """Every assignment payload in a project-scope context."""
    data = context.data
    if isinstance(data, dict):
        rows = data.get("assignments")
        if isinstance(rows, list):
            return [a for a in rows if isinstance(a, dict)]
    return []


def _label(assignment: dict[str, Any]) -> str:
    """A human-readable handle for one assignment in a message."""
    name = str(assignment.get("system_name") or "").strip()
    notes = str(assignment.get("notes") or "").strip()
    if name and notes:
        return f"{name} ({notes})"
    return name or notes or str(assignment.get("id") or "assignment")


def _result(
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

    Returning an empty list (rather than a passing result) keeps the report
    honest: a project-scope rule must not read as "passed" on an assignment
    pass it never looked at.
    """
    return []


# ── Assignment-scope rules ──────────────────────────────────────────────────


class FormworkRatePresent(ValidationRule):
    """The catalogue system an assignment points at must carry a rate."""

    rule_id = "formwork.rate_present"
    name = "Formwork system is priced"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A formwork system with no unit rate and no erect/strike rate prices the work at zero"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        unit_rate = _dec(a.get("system_unit_rate"))
        labour = _dec(a.get("erect_strike_rate"))
        ref = str(a.get("id") or "") or None
        if unit_rate > 0 or labour > 0:
            return [
                _result(
                    self,
                    True,
                    "OK",
                    element_ref=ref,
                    details={"unit_rate": str(unit_rate), "erect_strike_rate": str(labour)},
                )
            ]
        return [
            _result(
                self,
                False,
                (
                    f"Formwork system '{_label(a)}' has neither a panel rate nor an erect/strike "
                    f"rate, so this assignment prices at zero."
                ),
                element_ref=ref,
                suggestion="Set the system's unit rate (panel cost per m2) and its erect/strike rate in the catalogue.",
                details={"system_name": a.get("system_name"), "system_id": a.get("formwork_system_id")},
            )
        ]


class FormworkReuseWithinLimit(ValidationRule):
    """Reuse count must not exceed the system's manufacturer cap."""

    rule_id = "formwork.reuse_within_limit"
    name = "Reuse count within the system limit"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Amortising panels over more uses than they survive under-prices the formwork"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        reuse = int(a.get("reuse_count") or 1)
        cap = int(a.get("reuses_max") or 0)
        ref = str(a.get("id") or "") or None
        if cap <= 0 or reuse <= cap:
            return [_result(self, True, "OK", element_ref=ref, details={"reuse_count": reuse, "reuses_max": cap})]
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' amortises over {reuse} uses but the system is rated for {cap}. "
                    f"The panels will be replaced before the assumed reuse is reached."
                ),
                element_ref=ref,
                suggestion=f"Lower the reuse count to {cap} or fewer, or price a second set of panels.",
                details={"reuse_count": reuse, "reuses_max": cap},
            )
        ]


class FormworkReuseNearLimit(ValidationRule):
    """Reuse count should leave headroom under the system's cap."""

    rule_id = "formwork.reuse_near_limit"
    name = "Reuse count leaves headroom"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A reuse count at the manufacturer cap leaves nothing for damage, rework or resequencing"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        reuse = int(a.get("reuse_count") or 1)
        cap = int(a.get("reuses_max") or 0)
        ref = str(a.get("id") or "") or None
        if cap <= 0 or reuse > cap:
            # No cap to compare against, or already an error on the rule above.
            return [_result(self, True, "OK", element_ref=ref, details={"reuse_count": reuse, "reuses_max": cap})]
        threshold = Decimal(cap) * (Decimal("1") - _REUSE_HEADROOM)
        if Decimal(reuse) <= threshold:
            return [_result(self, True, "OK", element_ref=ref, details={"reuse_count": reuse, "reuses_max": cap})]
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' is priced at {reuse} of {cap} possible uses. There is no headroom "
                    f"left for damaged panels or a resequenced programme."
                ),
                element_ref=ref,
                suggestion="Hold a few uses in reserve, or confirm the panel condition assumption with the supplier.",
                details={"reuse_count": reuse, "reuses_max": cap, "headroom_pct": str(_REUSE_HEADROOM * 100)},
            )
        ]


class FormworkReuseSupportedBySchedule(ValidationRule):
    """The pour cycle must actually deliver the reuse being claimed."""

    rule_id = "formwork.reuse_supported_by_schedule"
    name = "Reuse count supported by the pour cycle"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The scheduled pours must turn the panel set around as many times as the rate assumes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        pours = _pours(context)
        ref = str(a.get("id") or "") or None
        if not pours:
            # No cycle described: nothing to contradict the typed reuse count.
            return _skip(self)
        reuse = int(a.get("reuse_count") or 1)
        derived = int(a.get("derived_reuse_count") or 0)
        if derived <= 0 or reuse <= derived:
            return [
                _result(
                    self,
                    True,
                    "OK",
                    element_ref=ref,
                    details={"reuse_count": reuse, "derived_reuse_count": derived, "pour_count": len(pours)},
                )
            ]
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' is priced over {reuse} uses, but the {len(pours)} scheduled pours "
                    f"turn the panel set around only {derived} times. The rate is optimistic by "
                    f"{reuse - derived} use(s)."
                ),
                element_ref=ref,
                suggestion="Derive the reuse count from the pour schedule, or add the pours that justify it.",
                details={
                    "reuse_count": reuse,
                    "derived_reuse_count": derived,
                    "pour_count": len(pours),
                },
            )
        ]


class FormworkScheduleAreaMatches(ValidationRule):
    """Scheduled pour areas should add up to the priced area."""

    rule_id = "formwork.schedule_area_matches"
    name = "Pour areas match the priced area"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The sum of the pour areas and the assignment's priced area describe the same scope"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        pours = _pours(context)
        ref = str(a.get("id") or "") or None
        if not pours:
            return _skip(self)
        priced = _dec(a.get("area_m2"))
        scheduled = sum((_dec(p.get("area_m2")) for p in pours), Decimal("0"))
        if priced <= 0:
            return [
                _result(
                    self,
                    False,
                    (
                        f"'{_label(a)}' schedules {scheduled} m2 of pours but is priced against no area, "
                        f"so nothing is charged for it."
                    ),
                    element_ref=ref,
                    suggestion="Set the assignment area, or derive it from the pour schedule.",
                    details={"priced_area_m2": str(priced), "scheduled_area_m2": str(scheduled)},
                )
            ]
        drift = abs(scheduled - priced) / priced
        if drift <= _AREA_TOLERANCE:
            return [
                _result(
                    self,
                    True,
                    "OK",
                    element_ref=ref,
                    details={"priced_area_m2": str(priced), "scheduled_area_m2": str(scheduled)},
                )
            ]
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' is priced against {priced} m2 but its pour cycle adds up to "
                    f"{scheduled} m2. One of the two is describing different work."
                ),
                element_ref=ref,
                suggestion="Reconcile the pour areas with the priced area before the rate goes into the bill.",
                details={
                    "priced_area_m2": str(priced),
                    "scheduled_area_m2": str(scheduled),
                    "drift_pct": str((drift * 100).quantize(Decimal("0.01"))),
                },
            )
        ]


class FormworkPourNumbersUnique(ValidationRule):
    """Each pour in a cycle needs its own number."""

    rule_id = "formwork.pour_numbers_unique"
    name = "Pour numbers are unique"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Two pours sharing a number make the cycle sequence ambiguous"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        pours = _pours(context)
        ref = str(a.get("id") or "") or None
        if not pours:
            return _skip(self)
        seen: dict[int, int] = {}
        for pour in pours:
            no = int(pour.get("pour_no") or 0)
            seen[no] = seen.get(no, 0) + 1
        duplicates = sorted(no for no, count in seen.items() if count > 1)
        if not duplicates:
            return [_result(self, True, "OK", element_ref=ref, details={"pour_count": len(pours)})]
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' has more than one pour numbered "
                    f"{', '.join(str(n) for n in duplicates)}, so the cycle order is ambiguous."
                ),
                element_ref=ref,
                suggestion="Renumber the pours so each lift has its own sequence number.",
                details={"duplicate_pour_numbers": duplicates, "pour_count": len(pours)},
            )
        ]


class FormworkStripTimeRespected(ValidationRule):
    """Consecutive pours must be at least a striking time apart."""

    rule_id = "formwork.strip_time_respected"
    name = "Pour cycle respects the striking time"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The same panel set cannot serve two pours closer together than its striking time"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        ref = str(a.get("id") or "") or None
        conflicts = a.get("cycle_conflicts")
        conflicts = conflicts if isinstance(conflicts, list) else []
        dated = int(a.get("dated_pour_count") or 0)
        if dated < 2:
            # Fewer than two dated pours: no gap exists to check.
            return _skip(self)
        strip_time = int(a.get("strip_time_days") or 0)
        if not conflicts:
            return [
                _result(
                    self,
                    True,
                    "OK",
                    element_ref=ref,
                    details={"strip_time_days": strip_time, "dated_pour_count": dated},
                )
            ]
        first = conflicts[0] if isinstance(conflicts[0], dict) else {}
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' turns the panel set around in {first.get('gap_days')} day(s) between "
                    f"pour {first.get('from_pour_no')} and pour {first.get('to_pour_no')}, but the system "
                    f"needs {strip_time} day(s) before striking. {len(conflicts)} gap(s) are too short."
                ),
                element_ref=ref,
                suggestion="Space the pours out, or price a second set of panels so two lifts can run in parallel.",
                details={
                    "strip_time_days": strip_time,
                    "conflict_count": len(conflicts),
                    "conflicts": conflicts[:8],
                },
            )
        ]


class FormworkWasteWithinBand(ValidationRule):
    """Waste allowance should sit in a plausible band."""

    rule_id = "formwork.waste_within_band"
    name = "Waste allowance is plausible"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Formwork waste outside 0 to 15 percent is usually a slip or an unstated allowance"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        ref = str(a.get("id") or "") or None
        waste = _dec(a.get("waste_pct"))
        if waste <= _WASTE_CEILING:
            return [_result(self, True, "OK", element_ref=ref, details={"waste_pct": str(waste)})]
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' carries a {waste} percent waste allowance on the panel cost. "
                    f"Above {_WASTE_CEILING} percent this is normally covering something other than offcuts."
                ),
                element_ref=ref,
                suggestion="Bring the waste back into the 0 to 15 percent band, or note what the extra covers.",
                details={"waste_pct": str(waste), "ceiling_pct": str(_WASTE_CEILING)},
            )
        ]


class FormworkBoqPositionLinked(ValidationRule):
    """An assignment reaches the bill only through a BOQ position."""

    rule_id = "formwork.boq_position_linked"
    name = "Assignment is linked to a BOQ position"
    standard = "universal"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "An assignment with no BOQ position is priced but never charged to the bill"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "assignment":
            return _skip(self)
        a = _assignment(context)
        ref = str(a.get("id") or "") or None
        linked = bool(a.get("boq_position_id"))
        if linked:
            return [_result(self, True, "OK", element_ref=ref, details={"linked": True})]
        return [
            _result(
                self,
                False,
                (
                    f"'{_label(a)}' is not linked to a BOQ position, so its "
                    # The payload carries money as a decimal string, so the
                    # figure is parsed before it reaches the renderer rather
                    # than handed over as text. The currency is the catalogue
                    # system's own; blank stays blank rather than becoming a
                    # guess.
                    f"{_fmt_money(_dec(a.get('computed_total')), str(a.get('currency') or '').strip())} "
                    "never reaches the bill of quantities."
                ),
                element_ref=ref,
                # Names the action that fixes it. The rule used to say "link
                # it" when nothing in the product could: the assignment carried
                # a BOQ position id no screen ever wrote. "Send to bill" now
                # creates the position and stores the link in one step.
                suggestion=(
                    "Send the assignment to a bill of quantities, or link it to the "
                    "concrete-pour position it belongs to."
                ),
                details={"linked": False, "computed_total": a.get("computed_total")},
            )
        ]


# ── Project-scope rules ─────────────────────────────────────────────────────


class FormworkCurrencyConsistent(ValidationRule):
    """A project's formwork must resolve to one currency to be summable."""

    rule_id = "formwork.currency_consistent"
    name = "Formwork prices in one currency"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Assignments priced off catalogue systems in different currencies cannot be totalled"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project":
            return _skip(self)
        rows = _assignments(context)
        if not rows:
            return _skip(self)
        currencies = sorted({str(r.get("currency") or "").strip().upper() for r in rows if r.get("currency")})
        if len(currencies) <= 1:
            return [_result(self, True, "OK", details={"currencies": currencies})]
        return [
            _result(
                self,
                False,
                (
                    f"This project's formwork is priced in {len(currencies)} currencies "
                    f"({', '.join(currencies)}). The formwork total is a sum of unlike units."
                ),
                suggestion="Reprice the catalogue systems in use onto one currency before reading the total.",
                details={"currencies": currencies, "assignment_count": len(rows)},
            )
        ]


class FormworkBoqPositionUnique(ValidationRule):
    """One BOQ position should carry formwork once."""

    rule_id = "formwork.boq_position_unique"
    name = "One formwork assignment per BOQ position"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Two assignments on the same BOQ position charge that bill line for formwork twice"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project":
            return _skip(self)
        rows = _assignments(context)
        if not rows:
            return _skip(self)
        counts: dict[str, int] = {}
        for row in rows:
            pos = str(row.get("boq_position_id") or "")
            if pos:
                counts[pos] = counts.get(pos, 0) + 1
        duplicates = sorted(pos for pos, count in counts.items() if count > 1)
        if not duplicates:
            return [_result(self, True, "OK", details={"linked_positions": len(counts)})]
        return [
            _result(
                self,
                False,
                (
                    f"{len(duplicates)} BOQ position(s) carry more than one formwork assignment, "
                    f"so that bill line is charged for formwork twice."
                ),
                suggestion="Merge the duplicate assignments, or split the BOQ position so each pour has its own line.",
                details={"duplicate_boq_position_ids": duplicates[:16], "count": len(duplicates)},
            )
        ]


# ── Registration ────────────────────────────────────────────────────────────

_FORMWORK_RULES: tuple[ValidationRule, ...] = (
    FormworkRatePresent(),
    FormworkReuseWithinLimit(),
    FormworkReuseNearLimit(),
    FormworkReuseSupportedBySchedule(),
    FormworkScheduleAreaMatches(),
    FormworkPourNumbersUnique(),
    FormworkStripTimeRespected(),
    FormworkWasteWithinBand(),
    FormworkBoqPositionLinked(),
    FormworkCurrencyConsistent(),
    FormworkBoqPositionUnique(),
)


def register_formwork_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites by rule id, so a re-import or a hot
    reload re-registers cleanly. Called at import time below (the module loader
    imports every module's ``validators``) and again from the module's
    ``on_startup`` hook, because the platform has two registration routes and
    a rule that only takes one of them is dormant in the other deployment.
    """
    for rule in _FORMWORK_RULES:
        rule_registry.register(rule, [FORMWORK_RULE_SET])
    logger.debug("Registered %d formwork validation rules", len(_FORMWORK_RULES))


register_formwork_rules()


# ── Orchestration used by the service ───────────────────────────────────────


def _finding(result: RuleResult) -> FormworkFinding:
    """Render one failing rule result as a UI-ready finding."""
    context: dict[str, Any] = dict(result.details or {})
    return FormworkFinding(
        rule_id=result.rule_id,
        severity=result.severity.value,
        category=result.category.value,
        message=result.message,
        key=f"formwork.validation.{result.rule_id}",
        element_ref=result.element_ref,
        suggestion=result.suggestion,
        context=context,
    )


def _to_report(
    report: ValidationReport,
    *,
    target_type: str,
    target_id: Any,
) -> FormworkValidationReport:
    """Collapse an engine report into the module's response shape."""
    return FormworkValidationReport(
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


def _degraded(target_type: str, target_id: Any) -> FormworkValidationReport:
    """The report returned when the engine itself could not run.

    SKIPPED, not PASSED: nothing was checked, and saying otherwise would turn
    an infrastructure failure into a clean bill of health.
    """
    return FormworkValidationReport(
        target_type=target_type,
        target_id=target_id,
        status=ValidationStatus.SKIPPED.value,
        error_count=0,
        warning_count=0,
        info_count=0,
        passed_count=0,
        findings=[],
        unsupported_rule_sets=[FORMWORK_RULE_SET],
    )


async def evaluate_assignment(
    payload: dict[str, Any],
    *,
    project_id: str | None = None,
    locale: str = "",
) -> FormworkValidationReport:
    """Run the assignment-scope formwork rules over one assignment.

    ``payload`` carries ``assignment`` (the row plus its catalogue facts and
    the derived cycle figures) and ``pours`` (its schedule lines), both as
    plain dicts with decimal-string quantities.
    """
    assignment = payload.get("assignment") or {}
    target_id = assignment.get("id")
    data = {"scope": "assignment", **payload}
    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[FORMWORK_RULE_SET],
            target_type="formwork_assignment",
            target_id=str(target_id or ""),
            project_id=project_id,
            metadata={"locale": locale},
        )
    except Exception:  # noqa: BLE001 - validation augments; never break the caller
        logger.warning("formwork assignment validation failed for %s", target_id, exc_info=True)
        return _degraded("formwork_assignment", target_id)
    return _to_report(report, target_type="formwork_assignment", target_id=target_id)


async def evaluate_project(
    payload: dict[str, Any],
    *,
    project_id: str,
    locale: str = "",
) -> FormworkValidationReport:
    """Run the project-scope formwork rules over every assignment on a project."""
    data = {"scope": "project", **payload}
    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[FORMWORK_RULE_SET],
            target_type="formwork_project",
            target_id=project_id,
            project_id=project_id,
            metadata={"locale": locale},
        )
    except Exception:  # noqa: BLE001 - validation augments; never break the caller
        logger.warning("formwork project validation failed for %s", project_id, exc_info=True)
        return _degraded("formwork_project", project_id)
    return _to_report(report, target_type="formwork_project", target_id=project_id)
