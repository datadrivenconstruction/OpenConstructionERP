# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design Options module-specific validation rules.

First-class validation for the option comparison. A design-option set is a set
of alternative designs for one project, each paired with its OWN priced bill of
quantities. Comparing them on cost is only fair when every option is a real,
fully priced, same-currency, same-programme estimate. These rules make that
fairness explicit instead of leaving it to the reader.

The rules live in one rule set, ``design_options``, and self-select by the scope
of the data they are handed so they run cleanly in two passes:

Per-option rules (the data carries ``scope == "option"`` plus one option and its
positions):

* ``design_options.gfa_present``    - ERROR. A priced option needs a gross floor
                                      area (its own or the project's) so its cost
                                      per m2 can be shown and compared.
* ``design_options.priced_complete``- WARNING. Every option position should carry
                                      a positive quantity and unit rate; a wholly
                                      unpriced option is flagged too, so an empty
                                      bill is never read as a clean pass.

Set-level rules (the data carries ``scope == "set"`` plus every option summary):

* ``design_options.gfa_consistent``   - WARNING. Options compared on cost per m2
                                        should have gross floor areas within 10
                                        percent of each other.
* ``design_options.scope_coverage``   - WARNING. A trade priced in other options
                                        but absent from an option may be dropped
                                        scope, not a real saving.
* ``design_options.unit_consistency`` - ERROR. One trade must use one unit of
                                        measure across options or its per-trade
                                        quantity delta is meaningless.
* ``design_options.currency_consistent`` - ERROR. Every option must resolve to
                                        the one comparison currency; an option
                                        whose own bill mixes currencies cannot.

The comparison aggregator runs each option through the core engine with the
``design_options`` and ``boq_quality`` rule sets (which drives that option's
traffic-light status), then runs the cross-option ``design_options`` rules once
over the whole set (which feeds the fairness banner). ``evaluate_design_option_set``
is the single orchestration entry point the comparison hook calls; it returns the
per-option statuses and the set-level findings as fairness notices. Money,
quantity and ratio values are Decimal-as-strings throughout; no float appears.
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
    ValidationReport,
    ValidationRule,
    ValidationStatus,
    rule_registry,
    validation_engine,
)
from app.core.validation.project_context import with_project_context
from app.modules.boq.service import _is_section, _position_currency
from app.modules.design_options.schemas import DesignOptionFairnessWarning

logger = logging.getLogger(__name__)

# The rule set every design-option rule registers under. Requested alongside
# ``boq_quality`` for the per-option pass and on its own for the set-level pass.
DESIGN_OPTIONS_RULE_SET = "design_options"

# Gross-floor-area spread beyond which a set's options are no longer directly
# comparable on cost per m2 (10 percent).
_GFA_DIVERGENCE_THRESHOLD = Decimal("0.10")


# ── Context + value helpers ──────────────────────────────────────────────────


def _scope(context: ValidationContext) -> str:
    """The validation scope carried on the data (``"option"`` / ``"set"``)."""
    data = context.data
    if isinstance(data, dict):
        scope = data.get("scope")
        if isinstance(scope, str):
            return scope
    return ""


def _option(context: ValidationContext) -> dict[str, Any]:
    """The single option summary in a per-option context (or an empty dict)."""
    data = context.data
    if isinstance(data, dict):
        option = data.get("option")
        if isinstance(option, dict):
            return option
    return {}


def _options(context: ValidationContext) -> list[dict[str, Any]]:
    """Every option summary in a set-level context (or an empty list)."""
    data = context.data
    if isinstance(data, dict):
        options = data.get("options")
        if isinstance(options, list):
            return [o for o in options if isinstance(o, dict)]
    return []


def _leaf_positions(context: ValidationContext) -> list[dict[str, Any]]:
    """Leaf position dicts on a per-option context (section headers skipped)."""
    data = context.data
    positions = data.get("positions") if isinstance(data, dict) else None
    if not isinstance(positions, list):
        return []
    return [pos for pos in positions if isinstance(pos, dict) and (pos.get("type") or "position") != "section"]


def _trades(option: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-trade bucket summaries carried on an option summary."""
    trades = option.get("trades")
    if isinstance(trades, list):
        return [t for t in trades if isinstance(t, dict)]
    return []


def _dec(value: Any) -> Decimal:
    """Parse an arbitrary value into a finite Decimal, never raising."""
    try:
        if value is None or value == "":
            return Decimal("0")
        parsed = Decimal(str(value).strip())
        return parsed if parsed.is_finite() else Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _num(value: Decimal) -> str:
    """Render a Decimal as a plain decimal string (Decimal-as-string contract)."""
    return format(value, "f") if value.is_finite() else "0"


def _pct_str(ratio: Decimal) -> str:
    """Render a 0..1 ratio as a percentage string with one decimal place."""
    return _num((ratio * Decimal("100")).quantize(Decimal("0.1")))


def _raw(value: Any) -> str:
    """Pass a stored money/quantity string through untouched (0 for empty).

    The stored values are already Decimal-as-strings; they are NOT re-parsed
    here so a locale-formatted figure still reaches the ``boq_quality`` rules'
    locale-aware number parser intact instead of being flattened to zero.
    """
    if value is None or value == "":
        return "0"
    return str(value)


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
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


# ── Per-option rules ─────────────────────────────────────────────────────────


class DesignOptionsGfaPresent(ValidationRule):
    rule_id = "design_options.gfa_present"
    name = "Design Option Gross Floor Area Present"
    standard = "design_options"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A priced option needs a gross floor area so its cost per m2 can be shown and compared."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "option":
            return []
        option = _option(context)
        if not option:
            return []
        ref = option.get("id")
        # An unpriced draft is covered by priced_complete; cost per m2 only
        # matters once the option carries a cost, so do not hard-error here.
        if not bool(option.get("priced")):
            return [_result(self, True, "OK", element_ref=ref)]
        passed = _dec(option.get("gfa")) > 0
        name = option.get("name") or ref
        message = (
            "OK"
            if passed
            else f"Option '{name}' has no gross floor area, so its cost per m2 cannot be shown or compared."
        )
        suggestion = (
            None if passed else "Set a gross floor area on the option or the project so cost per m2 is comparable."
        )
        return [_result(self, passed, message, element_ref=ref, suggestion=suggestion)]


class DesignOptionsPricedComplete(ValidationRule):
    rule_id = "design_options.priced_complete"
    name = "Design Option Fully Priced"
    standard = "design_options"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every option position should carry a positive quantity and unit rate for a complete option total."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "option":
            return []
        option = _option(context)
        if not option:
            return []
        ref = option.get("id")
        name = option.get("name") or ref
        leaves = _leaf_positions(context)
        # A wholly unpriced or empty option carries no boq_quality findings (there
        # are no positions to check), so flag it here or an empty bill would read
        # as a clean pass and look like a free option.
        if not bool(option.get("priced")) or not leaves:
            return [
                _result(
                    self,
                    False,
                    f"Option '{name}' is not priced yet, so it cannot be fairly compared on cost.",
                    element_ref=ref,
                    suggestion="Generate and price this option before comparing the set.",
                    details={"priced": bool(option.get("priced")), "position_count": len(leaves)},
                )
            ]
        incomplete = [pos for pos in leaves if _dec(pos.get("quantity")) <= 0 or _dec(pos.get("unit_rate")) <= 0]
        passed = not incomplete
        message = (
            "OK"
            if passed
            else (
                f"Option '{name}' has {len(incomplete)} position(s) with a zero quantity or zero rate, "
                "so the option total understates the real cost."
            )
        )
        suggestion = None if passed else "Fill in the missing quantities and rates so the option total is complete."
        return [
            _result(
                self,
                passed,
                message,
                element_ref=ref,
                suggestion=suggestion,
                details={"incomplete_count": len(incomplete), "position_count": len(leaves)},
            )
        ]


# ── Set-level rules ──────────────────────────────────────────────────────────


class DesignOptionsGfaConsistent(ValidationRule):
    rule_id = "design_options.gfa_consistent"
    name = "Design Options Comparable Floor Areas"
    standard = "design_options"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Options compared on cost per m2 should have gross floor areas within 10 percent of each other."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "set":
            return []
        areas = [area for area in (_dec(o.get("gfa")) for o in _options(context) if bool(o.get("priced"))) if area > 0]
        if len(areas) < 2:
            return [_result(self, True, "OK")]
        low, high = min(areas), max(areas)
        divergence = (high - low) / low if low > 0 else Decimal("0")
        passed = divergence <= _GFA_DIVERGENCE_THRESHOLD
        pct = _pct_str(divergence)
        message = (
            "OK"
            if passed
            else (
                f"Option gross floor areas diverge by {pct} percent "
                f"(from {_num(low)} to {_num(high)}), so cost per m2 is not directly comparable."
            )
        )
        suggestion = (
            None if passed else "Confirm the options cover the same building programme before comparing cost per m2."
        )
        return [
            _result(
                self,
                passed,
                message,
                suggestion=suggestion,
                details={"min_gfa": _num(low), "max_gfa": _num(high), "divergence_pct": pct},
            )
        ]


class DesignOptionsScopeCoverage(ValidationRule):
    rule_id = "design_options.scope_coverage"
    name = "Design Options Scope Coverage"
    standard = "design_options"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A trade priced in other options but absent from an option may be dropped scope, not a real saving."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "set":
            return []
        priced = [o for o in _options(context) if bool(o.get("priced"))]
        if len(priced) < 2:
            return []
        # trade key -> the option ids that actually price that trade.
        present: dict[str, set[str]] = {}
        labels: dict[str, str] = {}
        for option in priced:
            oid = str(option.get("id"))
            for trade in _trades(option):
                key = trade.get("key")
                if not key:
                    continue
                labels.setdefault(key, trade.get("label") or key)
                if _dec(trade.get("cost")) > 0:
                    present.setdefault(key, set()).add(oid)
        results: list[RuleResult] = []
        for option in priced:
            oid = str(option.get("id"))
            name = option.get("name") or oid
            # A trade is "missing here" when at least one OTHER option prices it
            # and this one does not (present[key] never contains this option).
            missing = sorted(key for key, ids in present.items() if oid not in ids)
            if not missing:
                results.append(_result(self, True, "OK", element_ref=oid))
                continue
            missing_labels = [labels.get(key, key) for key in missing]
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"Option '{name}' prices nothing for {len(missing)} trade(s) that other options do "
                        f"({', '.join(missing_labels[:8])}); confirm this is a real saving, not dropped scope."
                    ),
                    element_ref=oid,
                    suggestion="Check whether these trades are genuinely out of this option's scope or just unpriced.",
                    details={"missing_trades": missing, "missing_labels": missing_labels},
                )
            )
        return results


class DesignOptionsUnitConsistency(ValidationRule):
    rule_id = "design_options.unit_consistency"
    name = "Design Options Consistent Trade Units"
    standard = "design_options"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "One trade must use one unit of measure across options or its per-trade quantity delta is meaningless."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "set":
            return []
        priced = [o for o in _options(context) if bool(o.get("priced"))]
        # trade key -> {unit -> [option names that measure the trade in that unit]}
        units_by_trade: dict[str, dict[str, list[str]]] = {}
        labels: dict[str, str] = {}
        for option in priced:
            name = option.get("name") or str(option.get("id"))
            for trade in _trades(option):
                key = trade.get("key")
                unit = (trade.get("unit") or "").strip()
                if not key or not unit:
                    continue
                labels.setdefault(key, trade.get("label") or key)
                units_by_trade.setdefault(key, {}).setdefault(unit, []).append(name)
        results: list[RuleResult] = []
        for key, units in units_by_trade.items():
            if len(units) <= 1:
                continue
            label = labels.get(key, key)
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"Trade '{label}' is measured in different units across options "
                        f"({', '.join(sorted(units))}), so its per-trade quantity comparison is not valid."
                    ),
                    element_ref=key,
                    suggestion="Align the unit of measure for this trade across the options before comparing quantities.",
                    details={"trade": key, "units": {unit: names for unit, names in units.items()}},
                )
            )
        if not results:
            results.append(_result(self, True, "OK"))
        return results


class DesignOptionsCurrencyConsistent(ValidationRule):
    rule_id = "design_options.currency_consistent"
    name = "Design Options Single Comparison Currency"
    standard = "design_options"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "Every option must resolve to one comparison currency; an option whose own bill mixes currencies cannot."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "set":
            return []
        data = context.data
        comparison_currency = str(data.get("comparison_currency") or "") if isinstance(data, dict) else ""
        # The aggregator rebases every option to one comparison currency, so the
        # only way an option fails to resolve to it cleanly is a bill that blended
        # currencies internally before the uniform factor was applied.
        mixed = [o for o in _options(context) if bool(o.get("priced")) and bool(o.get("is_mixed"))]
        if not mixed:
            return [_result(self, True, "OK", details={"comparison_currency": comparison_currency})]
        names = [o.get("name") or str(o.get("id")) for o in mixed]
        return [
            _result(
                self,
                False,
                (
                    f"{len(mixed)} option(s) have a bill that mixes currencies ({', '.join(names[:8])}), "
                    f"so they cannot be compared cleanly in {comparison_currency or 'one currency'}."
                ),
                suggestion="Reprice these options in a single currency so every option resolves to the comparison currency.",
                details={"comparison_currency": comparison_currency, "mixed_options": names, "count": len(mixed)},
            )
        ]


# Rules registered under the ``design_options`` rule set. The per-option pass
# requests this set alongside ``boq_quality``; the set-level pass requests it
# alone. Every rule self-selects by ``scope`` so both passes stay clean.
_DESIGN_OPTIONS_RULES: tuple[ValidationRule, ...] = (
    DesignOptionsGfaPresent(),
    DesignOptionsPricedComplete(),
    DesignOptionsGfaConsistent(),
    DesignOptionsScopeCoverage(),
    DesignOptionsUnitConsistency(),
    DesignOptionsCurrencyConsistent(),
)


def register_design_options_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import / hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook.
    """
    for rule in _DESIGN_OPTIONS_RULES:
        rule_registry.register(rule, [DESIGN_OPTIONS_RULE_SET])
    logger.debug("Registered %d design_options validation rules", len(_DESIGN_OPTIONS_RULES))


# ── Orchestration used by the comparison hook ────────────────────────────────


@dataclass
class DesignOptionValidationOutcome:
    """The comparison-facing result of validating a design-option set.

    ``per_option_status`` maps ``str(option_id)`` to a traffic-light status
    (``passed`` / ``warnings`` / ``errors`` / ``info`` / ``pending``) for that
    option's column. ``fairness`` is the set-level rule findings rendered as
    fairness notices for the comparison banner.
    """

    per_option_status: dict[str, str] = field(default_factory=dict)
    fairness: list[DesignOptionFairnessWarning] = field(default_factory=list)


def to_validation_position(pos: object) -> dict[str, Any]:
    """Adapt a BOQ Position ORM row to the dict shape the leaf rules read.

    Mirrors the shape the BOQ validate endpoint feeds the engine so the
    ``boq_quality`` leaf rules read unit / quantity / rate / total / parent_id /
    type correctly instead of false-positive erroring on every row. Money and
    quantity are passed through as their stored decimal strings, never floats.
    """
    metadata = getattr(pos, "metadata_", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    parent_id = getattr(pos, "parent_id", None)
    return {
        "id": str(getattr(pos, "id", "") or ""),
        "parent_id": str(parent_id) if parent_id else None,
        "ordinal": getattr(pos, "ordinal", "") or "",
        "description": getattr(pos, "description", "") or "",
        "unit": getattr(pos, "unit", "") or "",
        "quantity": _raw(getattr(pos, "quantity", "0")),
        "unit_rate": _raw(getattr(pos, "unit_rate", "0")),
        "total": _raw(getattr(pos, "total", "0")),
        "classification": getattr(pos, "classification", None) or {},
        "source": getattr(pos, "source", None),
        "type": "section" if _is_section(pos) else "position",
        "currency": _position_currency(pos),
        "metadata": metadata,
    }


def _report_to_light(report: ValidationReport) -> str:
    """Collapse an engine report status into a per-option traffic-light value."""
    status = report.status
    if status == ValidationStatus.ERRORS:
        return "errors"
    if status == ValidationStatus.WARNINGS:
        return "warnings"
    if status == ValidationStatus.PASSED:
        return "passed"
    if status == ValidationStatus.INFO:
        return "info"
    # SKIPPED / UNSUPPORTED: nothing actually ran, so keep it honest.
    return "pending"


def _result_to_fairness(result: RuleResult) -> DesignOptionFairnessWarning:
    """Render one failing set-level rule result as a fairness banner notice."""
    context: dict[str, Any] = dict(result.details or {})
    context["message"] = result.message
    if result.element_ref:
        context["ref"] = result.element_ref
    if result.suggestion:
        context["suggestion"] = result.suggestion
    return DesignOptionFairnessWarning(
        key=f"designOptions.validation.{result.rule_id}",
        severity=result.severity.value,
        context=context,
    )


async def evaluate_design_option_set(
    option_payloads: list[dict[str, Any]],
    set_meta: dict[str, Any],
    *,
    session: Any = None,
) -> DesignOptionValidationOutcome:
    """Validate a design-option set and return per-option status + fairness.

    Runs two passes through the core engine:

    1. Per option, the ``design_options`` and ``boq_quality`` rule sets over that
       option's own bill, whose report status becomes the option's traffic light.
    2. Once for the whole set, the cross-option ``design_options`` rules, whose
       failing results become set-level fairness notices.

    Each ``option_payloads`` entry carries ``id``, ``name``, ``gfa`` (effective,
    decimal string), ``priced``, ``is_mixed``, ``grand_total``, ``positions`` (leaf
    dicts from :func:`to_validation_position`) and ``trades`` (per-trade bucket
    summaries). ``set_meta`` carries ``set_id``, ``project_id``,
    ``comparison_currency``, ``currency_unavailable`` and ``locale``.

    ``session`` is the caller's live session, used only to resolve the
    project-derived half of the per-option payload. Without one the run still
    produces a well-formed payload; the keys are simply null, and the rules
    that read them skip instead of reporting that nobody built it.

    Every pass is guarded so a validation failure degrades to a ``pending`` status
    and an empty fairness list rather than breaking the read-only comparison.
    """
    outcome = DesignOptionValidationOutcome()
    locale = set_meta.get("locale") or ""
    project_id = set_meta.get("project_id")
    comparison_currency = str(set_meta.get("comparison_currency") or "")

    # ── Pass 1: per-option (design_options per-option rules + boq_quality) ──
    for payload in option_payloads:
        oid = str(payload.get("id") or "")
        option_data = {
            "scope": "option",
            "positions": payload.get("positions") or [],
            "option": {
                "id": oid,
                "name": payload.get("name") or "",
                "gfa": payload.get("gfa") or "0",
                "priced": bool(payload.get("priced")),
                "is_mixed": bool(payload.get("is_mixed")),
                "grand_total": payload.get("grand_total") or "0",
            },
        }
        try:
            report = await validation_engine.validate(
                data=await with_project_context(session, project_id, option_data),
                rule_sets=[DESIGN_OPTIONS_RULE_SET, "boq_quality"],
                target_type="design_option",
                target_id=oid,
                project_id=project_id,
                metadata={"locale": locale, "base_currency": comparison_currency},
            )
            outcome.per_option_status[oid] = _report_to_light(report)
        except Exception:  # noqa: BLE001 - validation augments; never break the caller
            logger.warning("design_options per-option validation failed for option %s", oid, exc_info=True)
            outcome.per_option_status[oid] = "pending"

    # ── Pass 2: set-level cross-option rules -> fairness notices ──
    set_data = {
        "scope": "set",
        "comparison_currency": comparison_currency,
        "currency_unavailable": bool(set_meta.get("currency_unavailable")),
        "options": [
            {
                "id": str(payload.get("id") or ""),
                "name": payload.get("name") or "",
                "gfa": payload.get("gfa") or "0",
                "priced": bool(payload.get("priced")),
                "is_mixed": bool(payload.get("is_mixed")),
                "trades": payload.get("trades") or [],
            }
            for payload in option_payloads
        ],
    }
    try:
        set_report = await validation_engine.validate(
            data=set_data,
            rule_sets=[DESIGN_OPTIONS_RULE_SET],
            target_type="design_option_set",
            target_id=str(set_meta.get("set_id") or ""),
            project_id=project_id,
            metadata={"locale": locale, "comparison_currency": comparison_currency},
        )
        outcome.fairness = [
            _result_to_fairness(result)
            for result in set_report.results
            if not result.passed and not result.is_engine_error
        ]
    except Exception:  # noqa: BLE001 - validation augments; never break the caller
        logger.warning("design_options set-level validation failed", exc_info=True)

    return outcome
