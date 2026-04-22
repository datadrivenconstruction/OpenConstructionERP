"""Built-in validation rules.

Registers all standard rule sets that ship with OpenEstimate.
Modules can register additional rules via the rule_registry.

Every user-facing ``message`` and ``suggestion`` is resolved through
:mod:`app.core.validation.messages` so that the 20 built-in locales (and
any third-party translations) can render validation feedback without
a single hardcoded string leaking through.

The translator reads the caller's locale from
``ValidationContext.metadata["locale"]`` (defaulting to English). Callers
that don't supply a locale behave identically to the pre-i18n code path.
"""

from __future__ import annotations

import logging
import re
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
from app.core.validation.messages import DEFAULT_LOCALE, translate

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_positions(context: ValidationContext) -> list[dict[str, Any]]:
    """Extract positions list from context data (handles different data shapes)."""
    data = context.data
    if isinstance(data, dict):
        return data.get("positions", [])
    if isinstance(data, list):
        return data
    return []


def _get_locale(context: ValidationContext) -> str:
    """Pull the active locale from the validation context.

    The engine passes caller-supplied ``metadata`` straight into
    :class:`ValidationContext`; rules look up ``metadata["locale"]`` so
    that i18n threading is a single-line change at the call site
    (``engine.validate(..., metadata={"locale": "de"})``).
    """
    meta = getattr(context, "metadata", None) or {}
    locale = meta.get("locale") if isinstance(meta, dict) else None
    if isinstance(locale, str) and locale:
        return locale
    return DEFAULT_LOCALE


def _ok(locale: str) -> str:
    """Shared "OK" string — every rule that emits passing results uses this."""
    return translate("common.ok", locale=locale)


def _fmt_decimal(value: float, places: int = 2) -> str:
    """Format a float to a fixed number of decimals without locale noise."""
    return f"{value:,.{places}f}"


def _fmt_percent(value: float) -> str:
    """Format a ratio (0.0-1.0) as a percentage string."""
    return f"{value:.0%}"


# ── BOQ Quality Rules (Universal) ──────────────────────────────────────────


class PositionHasQuantity(ValidationRule):
    rule_id = "boq_quality.position_has_quantity"
    name = "Position Has Quantity"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position must have a non-zero quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            qty = pos.get("quantity", 0)
            passed = qty is not None and float(qty) > 0
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.position_has_quantity.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "boq_quality.position_has_quantity.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class PositionHasUnitRate(ValidationRule):
    rule_id = "boq_quality.position_has_unit_rate"
    name = "Position Has Unit Rate"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position should have a unit rate assigned"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            rate = pos.get("unit_rate", 0)
            passed = rate is not None and float(rate) > 0
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.position_has_unit_rate.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "boq_quality.position_has_unit_rate.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class PositionHasDescription(ValidationRule):
    rule_id = "boq_quality.position_has_description"
    name = "Position Has Description"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position must have a description"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            desc = (pos.get("description") or "").strip()
            passed = len(desc) >= 3
            message = (
                _ok(locale)
                if passed
                else translate(
                    "boq_quality.position_has_description.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                )
            )
        return results


class NoDuplicateOrdinals(ValidationRule):
    rule_id = "boq_quality.no_duplicate_ordinals"
    name = "No Duplicate Ordinals"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "BOQ positions must have unique ordinal numbers"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        ordinals: dict[str, list[str]] = {}
        for pos in positions:
            ord_val = pos.get("ordinal", "")
            if ord_val:
                ordinals.setdefault(ord_val, []).append(pos.get("id", "?"))

        results: list[RuleResult] = []
        for ordinal, ids in ordinals.items():
            passed = len(ids) == 1
            message = (
                _ok(locale)
                if passed
                else translate(
                    "boq_quality.no_duplicate_ordinals.fail",
                    locale=locale,
                    ordinal=ordinal,
                    count=len(ids),
                )
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=ids[0] if len(ids) == 1 else None,
                    details={"duplicate_ids": ids} if not passed else {},
                )
            )
        return results


class UnitRateInRange(ValidationRule):
    rule_id = "boq_quality.unit_rate_in_range"
    name = "Unit Rate Anomaly Detection"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Flags unit rates that deviate significantly from median"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        rates = [float(p.get("unit_rate", 0)) for p in positions if p.get("unit_rate")]
        if len(rates) < 3:
            return []

        rates_sorted = sorted(rates)
        median = rates_sorted[len(rates_sorted) // 2]
        threshold = median * 5  # Flag if >5x median

        results: list[RuleResult] = []
        for pos in positions:
            rate = float(pos.get("unit_rate", 0)) if pos.get("unit_rate") else 0
            if rate <= 0:
                continue
            passed = rate <= threshold
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.unit_rate_in_range.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    rate=_fmt_decimal(rate),
                    threshold=_fmt_decimal(threshold),
                )
                suggestion = translate(
                    "boq_quality.unit_rate_in_range.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"rate": rate, "median": median, "threshold": threshold},
                    suggestion=suggestion,
                )
            )
        return results


# ── DIN 276 Rules (DACH) ──────────────────────────────────────────────────


class DIN276CostGroupRequired(ValidationRule):
    rule_id = "din276.cost_group_required"
    name = "DIN 276 Cost Group Required"
    standard = "din276"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every BOQ position must have a DIN 276 cost group (Kostengruppe)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            kg = (pos.get("classification") or {}).get("din276", "")
            passed = bool(kg) and len(str(kg)) >= 3
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "din276.cost_group_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "din276.cost_group_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class DIN276ValidCostGroup(ValidationRule):
    rule_id = "din276.valid_cost_group"
    name = "Valid DIN 276 Cost Group"
    standard = "din276"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "DIN 276 cost group code must be a valid 3-digit code"

    # Valid top-level groups (1st digit)
    VALID_TOP_GROUPS = {"1", "2", "3", "4", "5", "6", "7"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            kg = str((pos.get("classification") or {}).get("din276", ""))
            if not kg:
                continue  # Handled by cost_group_required
            passed = len(kg) == 3 and kg.isdigit() and kg[0] in self.VALID_TOP_GROUPS
            message = (
                _ok(locale)
                if passed
                else translate(
                    "din276.valid_cost_group.fail",
                    locale=locale,
                    code=kg,
                    ordinal=pos.get("ordinal", "?"),
                )
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"given_code": kg},
                )
            )
        return results


# ── GAEB Rules (DACH) ─────────────────────────────────────────────────────


class GAEBOrdinalFormat(ValidationRule):
    rule_id = "gaeb.ordinal_format"
    name = "GAEB Ordinal Number Format"
    standard = "gaeb"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Ordinal numbers should follow GAEB LV structure (e.g., 01.02.0030)"

    _PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")  # XX.XX.XXXX

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            ordinal = pos.get("ordinal", "")
            if not ordinal:
                continue
            passed = bool(self._PATTERN.match(ordinal))
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gaeb.ordinal_format.fail",
                    locale=locale,
                    ordinal=ordinal,
                )
                suggestion = translate(
                    "gaeb.ordinal_format.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class GAEBLVStructure(ValidationRule):
    """Flags leaf positions missing a ``parent_id``.

    GAEB Leistungsverzeichnis (LV) files are strictly hierarchical:

        OZ-Stamm (trade) → Leistungsgruppe → Leistungsposition

    A leaf position without a parent is almost always the sign of a
    broken import or an incomplete manually-built LV. The rule skips
    positions that are themselves sections (they are allowed to sit at
    the top of the tree) and positions whose own id appears as a parent
    elsewhere in the LV (i.e. intermediate-level sections).
    """

    rule_id = "gaeb.lv_structure"
    name = "GAEB LV Structure"
    standard = "gaeb"
    severity = Severity.WARNING
    category = RuleCategory.STRUCTURE
    description = (
        "Flags leaf positions with no parent_id — GAEB LV hierarchy requires "
        "every Leistungsposition to live under a Leistungsgruppe."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        if not positions:
            return []

        parent_ids: set[str] = {
            str(p.get("parent_id")) for p in positions if p.get("parent_id") is not None
        }

        results: list[RuleResult] = []
        for pos in positions:
            pos_type = str(pos.get("type") or "").lower()
            if pos_type == "section":
                continue  # Top-level sections legitimately have no parent
            pos_id = str(pos.get("id") or "")
            # Intermediate nodes (those that parent something) are also fine
            if pos_id and pos_id in parent_ids:
                continue
            parent_id = pos.get("parent_id")
            passed = parent_id is not None and str(parent_id) != ""
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gaeb.lv_structure.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "gaeb.lv_structure.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class GAEBEinheitspreisSanity(ValidationRule):
    """Flags zero/negative Einheitspreis on non-lump-sum positions.

    GAEB X83 treats an Einheitspreis of 0 as a bid-withdrawal signal.
    Importing such a position silently is almost always a mistake — the
    rule forces reviewers to confirm whether they meant a zero-priced
    lump sum (valid) or a missing rate (invalid).
    """

    rule_id = "gaeb.einheitspreis_sanity"
    name = "GAEB Einheitspreis Sanity"
    standard = "gaeb"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = (
        "Einheitspreis must be > 0 for every non-lump-sum position. "
        "Zero or negative values would break GAEB X83 Angebotsabgabe."
    )

    LUMP_SUM_UNITS = {"lsum", "ls", "psch", "pausch", "pauschal"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            pos_type = str(pos.get("type") or "").lower()
            if pos_type == "section":
                continue
            unit = str(pos.get("unit") or "").strip().lower()
            if unit in self.LUMP_SUM_UNITS:
                continue  # Lump-sum positions are allowed to have arbitrary pricing shape
            rate = pos.get("unit_rate")
            if rate is None:
                # Missing rate is covered by PositionHasUnitRate; skip to keep signals orthogonal
                continue
            try:
                rate_val = float(rate)
            except (TypeError, ValueError):
                continue
            passed = rate_val > 0
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gaeb.einheitspreis_sanity.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    rate=_fmt_decimal(rate_val),
                    unit=unit or "-",
                )
                suggestion = translate(
                    "gaeb.einheitspreis_sanity.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"unit_rate": rate_val, "unit": unit},
                    suggestion=suggestion,
                )
            )
        return results


class GAEBTradeSectionCode(ValidationRule):
    """Flags top-level sections missing a GAEB Leistungsbereich (trade) code.

    A well-formed GAEB LV organises work into Leistungsbereiche, each
    identified by a 3-digit code (e.g. ``012`` Erdarbeiten, ``013``
    Mauerarbeiten per StLB-Bau). The rule accepts the code either on
    ``classification.gaeb_lb`` or as the leading digits of the section's
    ordinal (``012.xx...``).
    """

    rule_id = "gaeb.trade_section_code"
    name = "GAEB Trade Section Code"
    standard = "gaeb"
    severity = Severity.WARNING
    category = RuleCategory.STRUCTURE
    description = (
        "Top-level sections should carry a 3-digit GAEB Leistungsbereich "
        "code so imports/exports preserve the trade breakdown."
    )

    _LB_PATTERN = re.compile(r"^\d{3}(\..*)?$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        results: list[RuleResult] = []
        for pos in positions:
            pos_type = str(pos.get("type") or "").lower()
            if pos_type != "section":
                continue
            if pos.get("parent_id"):
                # Only top-level sections need the trade code.
                continue
            classification = pos.get("classification") or {}
            lb_code = str(classification.get("gaeb_lb") or "").strip()
            ordinal = str(pos.get("ordinal") or "").strip()
            has_valid_lb = bool(lb_code) and bool(re.fullmatch(r"\d{3}", lb_code))
            has_valid_ordinal = bool(self._LB_PATTERN.match(ordinal))
            passed = has_valid_lb or has_valid_ordinal
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gaeb.trade_section_code.fail",
                    locale=locale,
                    ordinal=ordinal or "?",
                )
                suggestion = translate(
                    "gaeb.trade_section_code.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"gaeb_lb": lb_code, "ordinal": ordinal},
                    suggestion=suggestion,
                )
            )
        return results


class GAEBQuantityDecimals(ValidationRule):
    """Flags quantities with more than 3 decimal places (GAEB X83 convention).

    GAEB X83 specifies that quantity values are transported with up to
    three decimals. More precision than that either gets silently
    truncated by downstream tools or triggers schema validation errors.
    The rule warns so users round explicitly instead of relying on
    implementation-specific truncation.
    """

    rule_id = "gaeb.quantity_decimals"
    name = "GAEB Quantity Decimals"
    standard = "gaeb"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        "Quantities should be rounded to at most 3 decimal places for GAEB X83 exports."
    )

    MAX_DECIMALS = 3

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            qty = pos.get("quantity")
            if qty is None:
                continue
            decimals = _count_decimal_places(qty)
            if decimals is None:
                continue  # Non-numeric payload; skip rather than falsely flag
            passed = decimals <= self.MAX_DECIMALS
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gaeb.quantity_decimals.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    quantity=qty,
                    decimals=decimals,
                )
                suggestion = translate(
                    "gaeb.quantity_decimals.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"quantity": str(qty), "decimals": decimals},
                    suggestion=suggestion,
                )
            )
        return results


def _count_decimal_places(value: Any) -> int | None:
    """Count trailing decimal places in ``value``.

    Uses :class:`Decimal` for an exact answer when possible so that
    float artefacts like ``0.1 + 0.2 == 0.30000000000000004`` don't
    trigger false positives: we round-trip via ``str(Decimal(...))`` on
    floats to remove IEEE-754 noise.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return 0
    try:
        if isinstance(value, float):
            dec = Decimal(str(value))
        elif isinstance(value, Decimal):
            dec = value
        elif isinstance(value, str):
            dec = Decimal(value.strip())
        else:
            dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    normalized = dec.normalize()
    # `normalize` may yield an exponent like 1E+2 for large integers; treat those as 0 decimals
    exponent = normalized.as_tuple().exponent
    if not isinstance(exponent, int) or exponent >= 0:
        return 0
    return -exponent


# ── Additional BOQ Quality Rules ──────────────────────────────────────────


class NegativeValues(ValidationRule):
    rule_id = "boq_quality.negative_values"
    name = "No Negative Values"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = "Positions must not have negative quantity or unit_rate"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            qty = pos.get("quantity")
            rate = pos.get("unit_rate")
            qty_val = float(qty) if qty is not None else 0
            rate_val = float(rate) if rate is not None else 0
            passed = qty_val >= 0 and rate_val >= 0
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                parts: list[str] = []
                if qty_val < 0:
                    parts.append(f"quantity={qty_val}")
                if rate_val < 0:
                    parts.append(f"unit_rate={rate_val}")
                message = translate(
                    "boq_quality.negative_values.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    details=", ".join(parts),
                )
                suggestion = translate(
                    "boq_quality.negative_values.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class UnrealisticRate(ValidationRule):
    rule_id = "boq_quality.unrealistic_rate"
    name = "Unrealistic Rate Detection"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Flags positions with unit rate > 100,000 or total > 10,000,000"

    RATE_THRESHOLD = 100_000
    TOTAL_THRESHOLD = 10_000_000

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            rate = float(pos.get("unit_rate", 0)) if pos.get("unit_rate") is not None else 0
            total = float(pos.get("total", 0)) if pos.get("total") is not None else 0
            rate_ok = rate <= self.RATE_THRESHOLD
            total_ok = total <= self.TOTAL_THRESHOLD
            passed = rate_ok and total_ok
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                parts: list[str] = []
                if not rate_ok:
                    parts.append(
                        f"unit_rate {_fmt_decimal(rate)} > {self.RATE_THRESHOLD:,}"
                    )
                if not total_ok:
                    parts.append(
                        f"total {_fmt_decimal(total)} > {self.TOTAL_THRESHOLD:,}"
                    )
                message = translate(
                    "boq_quality.unrealistic_rate.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    details="; ".join(parts),
                )
                suggestion = translate(
                    "boq_quality.unrealistic_rate.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"unit_rate": rate, "total": total},
                    suggestion=suggestion,
                )
            )
        return results


class TotalMismatch(ValidationRule):
    rule_id = "boq_quality.total_mismatch"
    name = "Total Matches Quantity × Rate"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Computed total (quantity × unit_rate) must match stored total within tolerance"

    TOLERANCE = 0.01

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            qty = pos.get("quantity")
            rate = pos.get("unit_rate")
            stored_total = pos.get("total")
            # Skip positions where any of the three values is missing
            if qty is None or rate is None or stored_total is None:
                continue
            qty_val = float(qty)
            rate_val = float(rate)
            stored_val = float(stored_total)
            computed = qty_val * rate_val
            diff = abs(computed - stored_val)
            passed = diff <= self.TOLERANCE
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.total_mismatch.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    computed=_fmt_decimal(computed),
                    stored=_fmt_decimal(stored_val),
                    diff=_fmt_decimal(diff),
                )
                suggestion = translate(
                    "boq_quality.total_mismatch.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={
                        "quantity": qty_val,
                        "unit_rate": rate_val,
                        "computed_total": computed,
                        "stored_total": stored_val,
                        "difference": diff,
                    },
                    suggestion=suggestion,
                )
            )
        return results


class EmptyUnit(ValidationRule):
    rule_id = "boq_quality.empty_unit"
    name = "Position Has Unit"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position must have a unit field (e.g., m, m2, m3, kg, pcs)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            unit = (pos.get("unit") or "").strip()
            passed = len(unit) > 0
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.empty_unit.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "boq_quality.empty_unit.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class SectionWithoutItems(ValidationRule):
    rule_id = "boq_quality.section_without_items"
    name = "Section Has Child Items"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Section-type positions should contain at least one child position"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        # Build a set of all parent IDs
        parent_ids: set[str] = set()
        for pos in positions:
            pid = pos.get("parent_id")
            if pid:
                parent_ids.add(pid)

        results: list[RuleResult] = []
        for pos in positions:
            pos_type = (pos.get("type") or "").lower()
            if pos_type != "section":
                continue
            pos_id = pos.get("id", "")
            has_children = pos_id in parent_ids
            if has_children:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.section_without_items.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    title=pos.get("description", "untitled"),
                )
                suggestion = translate(
                    "boq_quality.section_without_items.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=has_children,
                    message=message,
                    element_ref=pos_id,
                    suggestion=suggestion,
                )
            )
        return results


# ── Benchmark & Coverage Rules ────────────────────────────────────────────


class RateVsBenchmark(ValidationRule):
    rule_id = "boq_quality.rate_vs_benchmark"
    name = "Rate vs Benchmark"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "Compares unit rates against typical benchmark thresholds per unit type. "
        "Flags rates that are potentially unrealistic compared to industry medians."
    )

    # Simple heuristic thresholds per unit (upper bound for typical rates)
    UNIT_THRESHOLDS: dict[str, float] = {
        "m2": 10_000,  # > 10,000 per m2 is suspicious
        "m3": 50_000,  # > 50,000 per m3 is suspicious
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            rate = pos.get("unit_rate")
            if rate is None:
                continue
            rate_val = float(rate)
            if rate_val <= 0:
                continue
            unit = (pos.get("unit") or "").strip().lower()
            threshold = self.UNIT_THRESHOLDS.get(unit)
            if threshold is None:
                continue
            passed = rate_val <= threshold
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.rate_vs_benchmark.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    rate=_fmt_decimal(rate_val),
                    unit=unit,
                    threshold=_fmt_decimal(threshold),
                )
                suggestion = translate(
                    "boq_quality.rate_vs_benchmark.suggestion",
                    locale=locale,
                    unit=unit,
                    threshold=_fmt_decimal(threshold),
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={
                        "unit_rate": rate_val,
                        "unit": unit,
                        "benchmark_threshold": threshold,
                    },
                    suggestion=suggestion,
                )
            )
        return results


class LumpSumRatio(ValidationRule):
    rule_id = "boq_quality.lump_sum_ratio"
    name = "Lump Sum Ratio"
    standard = "boq_quality"
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = (
        "Flags BOQs where more than 30% of positions use lump sum (lsum) unit — indicates poor estimation granularity"
    )

    THRESHOLD = 0.30  # 30%

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        if not positions:
            return []

        total_count = len(positions)
        lsum_count = sum(1 for pos in positions if (pos.get("unit") or "").strip().lower() == "lsum")
        ratio = lsum_count / total_count
        passed = ratio <= self.THRESHOLD

        if passed:
            message = _ok(locale)
            suggestion = None
        else:
            message = translate(
                "boq_quality.lump_sum_ratio.fail",
                locale=locale,
                lsum_count=lsum_count,
                total_count=total_count,
                percent=_fmt_percent(ratio),
                threshold=_fmt_percent(self.THRESHOLD),
            )
            suggestion = translate(
                "boq_quality.lump_sum_ratio.suggestion",
                locale=locale,
            )

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                details={
                    "lsum_count": lsum_count,
                    "total_count": total_count,
                    "ratio": round(ratio, 3),
                    "threshold": self.THRESHOLD,
                },
                suggestion=suggestion,
            )
        ]


class CostConcentration(ValidationRule):
    rule_id = "boq_quality.cost_concentration"
    name = "Cost Concentration"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Flags positions that account for more than 40% of total BOQ cost — "
        "indicates potential scope error or missing breakdown"
    )

    THRESHOLD = 0.40  # 40%

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        if not positions:
            return []

        # Compute total from each position
        totals: list[tuple[dict[str, Any], float]] = []
        grand_total = 0.0
        for pos in positions:
            pos_total = pos.get("total")
            if pos_total is None:
                # Fallback: compute from quantity × unit_rate
                qty = pos.get("quantity")
                rate = pos.get("unit_rate")
                if qty is not None and rate is not None:
                    val = float(qty) * float(rate)
                else:
                    val = 0.0
            else:
                val = float(pos_total)
            totals.append((pos, val))
            grand_total += val

        if grand_total <= 0:
            return []

        results: list[RuleResult] = []
        for pos, val in totals:
            if val <= 0:
                continue
            share = val / grand_total
            if share > self.THRESHOLD:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "boq_quality.cost_concentration.fail",
                            locale=locale,
                            ordinal=pos.get("ordinal", "?"),
                            share=_fmt_percent(share),
                            value=_fmt_decimal(val),
                            grand_total=_fmt_decimal(grand_total),
                            threshold=_fmt_percent(self.THRESHOLD),
                        ),
                        element_ref=pos.get("id"),
                        details={
                            "position_total": val,
                            "grand_total": grand_total,
                            "share": round(share, 3),
                            "threshold": self.THRESHOLD,
                        },
                        suggestion=translate(
                            "boq_quality.cost_concentration.suggestion",
                            locale=locale,
                        ),
                    )
                )

        # If no positions exceeded the threshold, emit a single passing result
        if not results:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                    details={"grand_total": grand_total, "threshold": self.THRESHOLD},
                )
            )

        return results


# ── Additional DIN 276 Rules ─────────────────────────────────────────────


class DIN276Hierarchy(ValidationRule):
    rule_id = "din276.hierarchy"
    name = "DIN 276 Cost Group Hierarchy"
    standard = "din276"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Child KG code should be nested under the correct parent (e.g., 331 under 330 under 300)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        # Build a map from position id to its DIN 276 KG code
        id_to_kg: dict[str, str] = {}
        id_to_pos: dict[str, dict[str, Any]] = {}
        for pos in positions:
            pos_id = pos.get("id", "")
            kg = str((pos.get("classification") or {}).get("din276", ""))
            if pos_id and kg:
                id_to_kg[pos_id] = kg
                id_to_pos[pos_id] = pos

        results: list[RuleResult] = []
        for pos in positions:
            kg = str((pos.get("classification") or {}).get("din276", ""))
            parent_id = pos.get("parent_id")
            if not kg or not parent_id or parent_id not in id_to_kg:
                continue
            parent_kg = id_to_kg[parent_id]
            # A valid hierarchy means the child KG starts with the parent KG prefix.
            # The parent KG prefix (ignoring trailing zeros) should match.
            # parent=300 (3 chars) → child should start with "3"
            # parent=330 (3 chars) → child should start with "33"
            parent_prefix = parent_kg.rstrip("0") or parent_kg[0]
            passed = kg.startswith(parent_prefix)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "din276.hierarchy.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    child=kg,
                    parent=parent_kg,
                    prefix=parent_prefix,
                )
                suggestion = translate(
                    "din276.hierarchy.suggestion",
                    locale=locale,
                    prefix=parent_prefix,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"child_kg": kg, "parent_kg": parent_kg},
                    suggestion=suggestion,
                )
            )
        return results


class DIN276Completeness(ValidationRule):
    rule_id = "din276.completeness"
    name = "DIN 276 Major Groups Present"
    standard = "din276"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Major KG groups 300 (Building Construction) and 400 (Technical Systems) should be present"

    REQUIRED_GROUPS = {"300", "400"}
    # Group names kept in English only — passed through {group_name} into
    # the i18n template so de/ru translations embed the canonical German
    # term in parentheses.
    GROUP_NAMES = {
        "300": "Building Construction (Baukonstruktionen)",
        "400": "Technical Systems (Technische Anlagen)",
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        # Collect all top-level KG groups (first digit × 100) present in the BOQ
        present_groups: set[str] = set()
        for pos in positions:
            kg = str((pos.get("classification") or {}).get("din276", ""))
            if kg and len(kg) >= 3 and kg.isdigit():
                # Normalize to top-level group: e.g., 331 → 300, 421 → 400
                top_group = kg[0] + "00"
                present_groups.add(top_group)

        results: list[RuleResult] = []
        for group in sorted(self.REQUIRED_GROUPS):
            passed = group in present_groups
            group_name = self.GROUP_NAMES.get(group, "")
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "din276.completeness.fail",
                    locale=locale,
                    group=group,
                    group_name=group_name,
                )
                suggestion = translate(
                    "din276.completeness.suggestion",
                    locale=locale,
                    group=group,
                    group_name=group_name,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    details={
                        "required_group": group,
                        "present_groups": sorted(present_groups),
                    },
                    suggestion=suggestion,
                )
            )
        return results


# ── NRM Rules (UK) ───────────────────────────────────────────────────────


class NRMClassificationRequired(ValidationRule):
    rule_id = "nrm.classification_required"
    name = "NRM Classification Required"
    standard = "nrm"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every BOQ position must have an NRM element code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            nrm = (pos.get("classification") or {}).get("nrm", "")
            passed = bool(nrm) and len(str(nrm)) >= 3
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "nrm.classification_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "nrm.classification_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class NRMValidElement(ValidationRule):
    rule_id = "nrm.valid_element"
    name = "Valid NRM Element Code"
    standard = "nrm"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "NRM element code must match NRM 1/2 structure (e.g., 1.1, 2.6.1)"

    VALID_GROUPS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"}
    _PATTERN = re.compile(r"^\d{1,2}(\.\d{1,2}){0,3}$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            nrm = str((pos.get("classification") or {}).get("nrm", ""))
            if not nrm:
                continue
            top = nrm.split(".")[0]
            passed = bool(self._PATTERN.match(nrm)) and top in self.VALID_GROUPS
            message = (
                _ok(locale)
                if passed
                else translate(
                    "nrm.valid_element.fail",
                    locale=locale,
                    code=nrm,
                    ordinal=pos.get("ordinal", "?"),
                )
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"given_code": nrm},
                )
            )
        return results


class NRMCompleteness(ValidationRule):
    rule_id = "nrm.completeness"
    name = "NRM Major Groups Present"
    standard = "nrm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Major NRM groups (Substructure, Superstructure, Services) should be present"

    REQUIRED_GROUPS = {"1", "2", "5"}  # 1=Substructure, 2=Superstructure, 5=Services
    GROUP_NAMES = {
        "1": "Substructure",
        "2": "Superstructure",
        "5": "Services",
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        present_groups: set[str] = set()
        for pos in positions:
            nrm = str((pos.get("classification") or {}).get("nrm", ""))
            if nrm:
                present_groups.add(nrm.split(".")[0])

        results: list[RuleResult] = []
        for group in sorted(self.REQUIRED_GROUPS):
            passed = group in present_groups
            group_name = self.GROUP_NAMES.get(group, "")
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "nrm.completeness.fail",
                    locale=locale,
                    group=group,
                    group_name=group_name,
                )
                suggestion = translate(
                    "nrm.completeness.suggestion",
                    locale=locale,
                    group=group,
                    group_name=group_name,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    details={"required_group": group, "present_groups": sorted(present_groups)},
                    suggestion=suggestion,
                )
            )
        return results


# ── MasterFormat Rules (US) ──────────────────────────────────────────────


class MasterFormatClassificationRequired(ValidationRule):
    rule_id = "masterformat.classification_required"
    name = "MasterFormat Classification Required"
    standard = "masterformat"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every BOQ position must have a CSI MasterFormat division code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            mf = (pos.get("classification") or {}).get("masterformat", "")
            passed = bool(mf) and len(str(mf).replace(" ", "")) >= 4
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "masterformat.classification_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "masterformat.classification_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class MasterFormatValidDivision(ValidationRule):
    rule_id = "masterformat.valid_division"
    name = "Valid MasterFormat Division"
    standard = "masterformat"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "MasterFormat code must be a valid division (00-49)"

    _PATTERN = re.compile(r"^\d{2}(\s?\d{2}){0,2}(\.\d{2})?$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            mf = str((pos.get("classification") or {}).get("masterformat", ""))
            if not mf:
                continue
            div = mf[:2]
            valid_div = div.isdigit() and 0 <= int(div) <= 49
            passed = bool(self._PATTERN.match(mf)) and valid_div
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "masterformat.valid_division.fail",
                    locale=locale,
                    code=mf,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "masterformat.valid_division.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"given_code": mf},
                    suggestion=suggestion,
                )
            )
        return results


class MasterFormatCompleteness(ValidationRule):
    rule_id = "masterformat.completeness"
    name = "MasterFormat Core Divisions Present"
    standard = "masterformat"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Core divisions (03 Concrete, 05 Metals, 26 Electrical) should be present"

    REQUIRED_DIVISIONS = {"03", "05", "26"}
    DIV_NAMES = {
        "03": "Concrete",
        "05": "Metals",
        "26": "Electrical",
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        present_divs: set[str] = set()
        for pos in positions:
            mf = str((pos.get("classification") or {}).get("masterformat", ""))
            if mf and len(mf) >= 2:
                present_divs.add(mf[:2])

        results: list[RuleResult] = []
        for div in sorted(self.REQUIRED_DIVISIONS):
            passed = div in present_divs
            div_name = self.DIV_NAMES.get(div, "")
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "masterformat.completeness.fail",
                    locale=locale,
                    division=div,
                    division_name=div_name,
                )
                suggestion = translate(
                    "masterformat.completeness.suggestion",
                    locale=locale,
                    division=div,
                    division_name=div_name,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    details={"required_div": div, "present_divs": sorted(present_divs)},
                    suggestion=suggestion,
                )
            )
        return results


# ── SINAPI Rules (Brazil) ───────────────────────────────────────────────


class SINAPICodeRequired(ValidationRule):
    rule_id = "sinapi.code_required"
    name = "SINAPI Code Required"
    standard = "sinapi"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a SINAPI composition code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("sinapi", "")
            passed = bool(code) and len(str(code)) >= 4
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "sinapi.code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "sinapi.code_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class SINAPIValidCode(ValidationRule):
    rule_id = "sinapi.valid_code"
    name = "Valid SINAPI Code Format"
    standard = "sinapi"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "SINAPI codes should be 5-digit numeric codes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("sinapi", ""))
            if not code:
                continue
            passed = code.isdigit() and 4 <= len(code) <= 6
            message = (
                _ok(locale)
                if passed
                else translate(
                    "sinapi.valid_code.fail",
                    locale=locale,
                    code=code,
                    ordinal=pos.get("ordinal", "?"),
                )
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                )
            )
        return results


# ── GESN Rules (Russia/CIS) ─────────────────────────────────────────────


class GESNCodeRequired(ValidationRule):
    rule_id = "gesn.code_required"
    name = "GESN/FER Code Required"
    standard = "gesn"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a ГЭСН/ФЕР code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("gesn", "")
            passed = bool(code) and len(str(code)) >= 5
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gesn.code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "gesn.code_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class GESNValidCode(ValidationRule):
    rule_id = "gesn.valid_code"
    name = "Valid GESN Code Format"
    standard = "gesn"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "ГЭСН codes should follow XX-XX-XXX-XX format"

    _PATTERN = re.compile(r"^\d{2}-\d{2}-\d{3}-\d{2}$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("gesn", ""))
            if not code:
                continue
            passed = bool(self._PATTERN.match(code))
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gesn.valid_code.fail",
                    locale=locale,
                    code=code,
                )
                suggestion = translate(
                    "gesn.valid_code.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                    suggestion=suggestion,
                )
            )
        return results


# ── DPGF Rules (France) ─────────────────────────────────────────────────


class DPGFLotRequired(ValidationRule):
    rule_id = "dpgf.lot_required"
    name = "DPGF Lot Technique Required"
    standard = "dpgf"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions must be assigned to a Lot technique (trade package)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            lot = (pos.get("classification") or {}).get("dpgf", "") or pos.get("section", "")
            passed = bool(lot)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "dpgf.lot_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "dpgf.lot_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class DPGFPricingComplete(ValidationRule):
    rule_id = "dpgf.pricing_complete"
    name = "DPGF Pricing Complete"
    standard = "dpgf"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "All DPGF positions should have complete pricing (unit rate or lump sum)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        if not positions:
            return []
        priced = sum(1 for p in positions if p.get("unit_rate") and float(p["unit_rate"]) > 0)
        total = len(positions)
        ratio = priced / total if total > 0 else 0
        passed = ratio >= 0.80
        if passed:
            message = _ok(locale)
            suggestion = None
        else:
            message = translate(
                "dpgf.pricing_complete.fail",
                locale=locale,
                priced=priced,
                total=total,
                percent=_fmt_percent(ratio),
            )
            suggestion = translate(
                "dpgf.pricing_complete.suggestion",
                locale=locale,
            )
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                details={"priced": priced, "total": total, "ratio": round(ratio, 3)},
                suggestion=suggestion,
            )
        ]


# ── ÖNORM Rules (Austria) ───────────────────────────────────────────────


class ONORMPositionFormat(ValidationRule):
    rule_id = "onorm.position_format"
    name = "ÖNORM B 2063 Position Format"
    standard = "onorm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Position ordinals should follow ÖNORM B 2063 LV structure"

    _PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}[A-Z]?$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            ordinal = pos.get("ordinal", "")
            if not ordinal:
                continue
            passed = bool(self._PATTERN.match(ordinal))
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "onorm.position_format.fail",
                    locale=locale,
                    ordinal=ordinal,
                )
                suggestion = translate(
                    "onorm.position_format.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class ONORMDescriptionLength(ValidationRule):
    rule_id = "onorm.description_length"
    name = "ÖNORM Description Length"
    standard = "onorm"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "ÖNORM positions should have descriptions with sufficient detail (min 20 chars)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            desc = (pos.get("description") or "").strip()
            passed = len(desc) >= 20
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "onorm.description_length.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    length=len(desc),
                )
                suggestion = translate(
                    "onorm.description_length.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


# ── GB/T 50500 Rules (China) ────────────────────────────────────────────


class GBT50500CodeRequired(ValidationRule):
    rule_id = "gbt50500.code_required"
    name = "GB/T 50500 Code Required"
    standard = "gbt50500"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions must have a GB/T 50500 item code (工程量清单编码)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("gbt50500", "")
            passed = bool(code) and len(str(code)) >= 6
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gbt50500.code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "gbt50500.code_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class GBT50500ValidCode(ValidationRule):
    rule_id = "gbt50500.valid_code"
    name = "Valid GB/T 50500 Code"
    standard = "gbt50500"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "GB/T 50500 codes should be 9-digit or 12-digit numeric codes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("gbt50500", ""))
            if not code:
                continue
            passed = code.isdigit() and len(code) in (9, 12)
            message = (
                _ok(locale)
                if passed
                else translate(
                    "gbt50500.valid_code.fail",
                    locale=locale,
                    code=code,
                )
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                )
            )
        return results


# ── CPWD Rules (India) ──────────────────────────────────────────────────


class CPWDCodeRequired(ValidationRule):
    rule_id = "cpwd.code_required"
    name = "CPWD/DSR Code Required"
    standard = "cpwd"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a CPWD/DSR item reference"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("cpwd", "")
            passed = bool(code) and len(str(code)) >= 3
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "cpwd.code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "cpwd.code_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class CPWDMeasurementUnits(ValidationRule):
    rule_id = "cpwd.measurement_units"
    name = "CPWD IS 1200 Measurement Units"
    standard = "cpwd"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Units must follow IS 1200 measurement standards (metric only)"

    VALID_UNITS = {
        "m",
        "m2",
        "m3",
        "kg",
        "t",
        "nos",
        "pcs",
        "rm",
        "rmt",
        "sqm",
        "cum",
        "each",
        "lsum",
        "ls",
        "set",
        "pair",
        "litre",
        "kl",
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            unit = (pos.get("unit") or "").strip().lower()
            if not unit:
                continue
            passed = unit in self.VALID_UNITS
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "cpwd.measurement_units.fail",
                    locale=locale,
                    unit=unit,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "cpwd.measurement_units.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


# ── Birim Fiyat Rules (Turkey) ──────────────────────────────────────────


class BirimFiyatCodeRequired(ValidationRule):
    rule_id = "birimfiyat.code_required"
    name = "Birim Fiyat Poz Required"
    standard = "birimfiyat"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions must have a Bayındırlık birim fiyat poz number"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("birimfiyat", "")
            passed = bool(code) and len(str(code)) >= 4
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "birimfiyat.code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "birimfiyat.code_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class BirimFiyatValidPoz(ValidationRule):
    rule_id = "birimfiyat.valid_poz"
    name = "Valid Birim Fiyat Poz Format"
    standard = "birimfiyat"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Poz numbers should follow Bayındırlık format (XX.XXX/X)"

    _PATTERN = re.compile(r"^\d{2}\.\d{3}(/\d{1,2})?$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("birimfiyat", ""))
            if not code:
                continue
            passed = bool(self._PATTERN.match(code))
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "birimfiyat.valid_poz.fail",
                    locale=locale,
                    code=code,
                )
                suggestion = translate(
                    "birimfiyat.valid_poz.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                    suggestion=suggestion,
                )
            )
        return results


# ── Sekisan Rules (Japan) ───────────────────────────────────────────────


class SekisanCodeRequired(ValidationRule):
    rule_id = "sekisan.code_required"
    name = "Sekisan Code Required"
    standard = "sekisan"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a 積算基準 item code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("sekisan", "")
            passed = bool(code) and len(str(code)) >= 3
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "sekisan.code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "sekisan.code_required.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class SekisanMetricUnits(ValidationRule):
    rule_id = "sekisan.metric_units"
    name = "Sekisan Metric Units"
    standard = "sekisan"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Units must be metric per Japanese construction standards"

    VALID_UNITS = {
        "m",
        "m2",
        "m3",
        "kg",
        "t",
        "本",
        "枚",
        "箇所",
        "式",
        "台",
        "セット",
        "個",
        "組",
        "m2/回",
        "pcs",
        "set",
        "lsum",
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            unit = (pos.get("unit") or "").strip().lower()
            if not unit:
                continue
            passed = unit in self.VALID_UNITS or unit in {u.lower() for u in self.VALID_UNITS}
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "sekisan.metric_units.fail",
                    locale=locale,
                    unit=unit,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "sekisan.metric_units.suggestion",
                    locale=locale,
                )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


# ── Universal Additional Rules ──────────────────────────────────────────


class CurrencyConsistency(ValidationRule):
    rule_id = "boq_quality.currency_consistency"
    name = "Currency Consistency"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "All positions in a BOQ should use the same currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        currencies: set[str] = set()
        for pos in positions:
            ccy = (pos.get("currency") or "").strip().upper()
            if ccy:
                currencies.add(ccy)
        if len(currencies) <= 1:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(
                    "boq_quality.currency_consistency.fail",
                    locale=locale,
                    currencies=", ".join(sorted(currencies)),
                ),
                details={"currencies": sorted(currencies)},
                suggestion=translate(
                    "boq_quality.currency_consistency.suggestion",
                    locale=locale,
                ),
            )
        ]


class MeasurementConsistency(ValidationRule):
    rule_id = "boq_quality.measurement_consistency"
    name = "Measurement Unit Consistency"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags mixing of metric and imperial units in the same BOQ"

    IMPERIAL_UNITS = {"ft", "ft2", "ft3", "yd", "yd2", "yd3", "in", "lb", "ton", "gal", "sf", "sy", "cy", "lf"}
    METRIC_UNITS = {"m", "m2", "m3", "mm", "cm", "km", "kg", "t", "l", "kl", "ml"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        has_metric = False
        has_imperial = False
        for pos in positions:
            unit = (pos.get("unit") or "").strip().lower()
            if unit in self.IMPERIAL_UNITS:
                has_imperial = True
            if unit in self.METRIC_UNITS:
                has_metric = True
        if has_metric and has_imperial:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "boq_quality.measurement_consistency.fail",
                        locale=locale,
                    ),
                    suggestion=translate(
                        "boq_quality.measurement_consistency.suggestion",
                        locale=locale,
                    ),
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message=_ok(locale),
            )
        ]


# ── Registration ────────────────────────────────────────────────────────────


def register_builtin_rules() -> None:
    """Register all built-in validation rules."""
    rules: list[tuple[ValidationRule, list[str] | None]] = [
        # BOQ Quality (universal)
        (PositionHasQuantity(), None),
        (PositionHasUnitRate(), None),
        (PositionHasDescription(), None),
        (NoDuplicateOrdinals(), None),
        (UnitRateInRange(), None),
        (NegativeValues(), None),
        (UnrealisticRate(), None),
        (TotalMismatch(), None),
        (EmptyUnit(), None),
        (SectionWithoutItems(), None),
        (RateVsBenchmark(), None),
        (LumpSumRatio(), None),
        (CostConcentration(), None),
        (CurrencyConsistency(), None),
        (MeasurementConsistency(), None),
        # DIN 276 (DACH)
        (DIN276CostGroupRequired(), None),
        (DIN276ValidCostGroup(), None),
        (DIN276Hierarchy(), None),
        (DIN276Completeness(), None),
        # GAEB (DACH) — slice D expansion
        (GAEBOrdinalFormat(), None),
        (GAEBLVStructure(), None),
        (GAEBEinheitspreisSanity(), None),
        (GAEBTradeSectionCode(), None),
        (GAEBQuantityDecimals(), None),
        # NRM (UK)
        (NRMClassificationRequired(), None),
        (NRMValidElement(), None),
        (NRMCompleteness(), None),
        # MasterFormat (US)
        (MasterFormatClassificationRequired(), None),
        (MasterFormatValidDivision(), None),
        (MasterFormatCompleteness(), None),
        # SINAPI (Brazil)
        (SINAPICodeRequired(), None),
        (SINAPIValidCode(), None),
        # GESN (Russia/CIS)
        (GESNCodeRequired(), None),
        (GESNValidCode(), None),
        # DPGF (France)
        (DPGFLotRequired(), None),
        (DPGFPricingComplete(), None),
        # ÖNORM (Austria)
        (ONORMPositionFormat(), None),
        (ONORMDescriptionLength(), None),
        # GB/T 50500 (China)
        (GBT50500CodeRequired(), None),
        (GBT50500ValidCode(), None),
        # CPWD (India)
        (CPWDCodeRequired(), None),
        (CPWDMeasurementUnits(), None),
        # Birim Fiyat (Turkey)
        (BirimFiyatCodeRequired(), None),
        (BirimFiyatValidPoz(), None),
        # Sekisan (Japan)
        (SekisanCodeRequired(), None),
        (SekisanMetricUnits(), None),
    ]

    for rule, sets in rules:
        rule_registry.register(rule, sets)

    logger.info(
        "Registered %d built-in validation rules across %d rule sets",
        len(rules),
        len(rule_registry.list_rule_sets()),
    )
