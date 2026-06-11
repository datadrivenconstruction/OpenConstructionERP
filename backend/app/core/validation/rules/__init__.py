"""‌⁠‍Built-in validation rules.

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
    """‌⁠‍Extract positions list from context data (handles different data shapes)."""
    data = context.data
    if isinstance(data, dict):
        return data.get("positions", [])
    if isinstance(data, list):
        return data
    return []


def _get_leaf_positions(context: ValidationContext) -> list[dict[str, Any]]:
    """Leaf-only positions - sections (parent / header rows) are skipped.

    Why: section rows aggregate children and intentionally lack `unit`,
    `quantity`, and `unit_rate`. Rules that enforce those fields would
    otherwise emit false-positive errors against every header in the
    tree, drowning real findings on a fresh user's first validation run.

    Detection: a row is a section if (a) `metadata.type == "section"`
    (explicit), or (b) any other row in the dataset names this row as
    its parent (implicit - derived from the parent_id graph). The
    implicit branch covers seed/import paths that don't stamp the type
    metadata field.
    """
    positions = _get_positions(context)
    parent_ids: set[str] = {str(p["parent_id"]) for p in positions if p.get("parent_id")}
    return [
        pos
        for pos in positions
        if (pos.get("type") or "position") != "section" and str(pos.get("id") or "") not in parent_ids
    ]


def _get_locale(context: ValidationContext) -> str:
    """‌⁠‍Pull the active locale from the validation context.

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


def _position_currency(pos: dict[str, Any]) -> str:
    """‌⁠‍Resolve one position's currency from whatever shape the loader supplied.

    The per-position currency is authoritative in the BOQ metadata
    (``Position.metadata_['currency']`` - see ``boq.service._position_currency``),
    but different callers flatten the position dict differently: some put
    ``currency`` at the top level, some nest it under ``metadata`` /
    ``metadata_``, and the BOQ validation loaders historically dropped it
    entirely. Inspect every plausible location so this rule actually fires
    whenever currency data is present, instead of silently passing because it
    only ever read a bare top-level ``currency`` key.

    Returns the upper-cased ISO code, or "" when no currency is recorded.
    """
    # Top-level keys (top-level ``currency`` wins, then the legacy aliases).
    for key in ("currency", "position_currency", "project_currency"):
        val = pos.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().upper()
    # Nested metadata blob (``metadata`` from API shapes, ``metadata_`` from ORM).
    for meta_key in ("metadata", "metadata_"):
        meta = pos.get(meta_key)
        if isinstance(meta, dict):
            for key in ("currency", "position_currency", "project_currency"):
                val = meta.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip().upper()
    return ""


def _ok(locale: str) -> str:
    """Shared "OK" string - every rule that emits passing results uses this."""
    return translate("common.ok", locale=locale)


def _fmt_decimal(value: float, places: int = 2) -> str:
    """Format a float to a fixed number of decimals without locale noise."""
    return f"{value:,.{places}f}"


def _fmt_percent(value: float) -> str:
    """Format a ratio (0.0-1.0) as a percentage string."""
    return f"{value:.0%}"


# Sentinel returned by ``_to_number`` when a value cannot be interpreted as a
# number *at all* (vs. ``None``/missing, which the caller may treat as zero).
_NOT_A_NUMBER = object()

# Whitespace that French / fr-CH / many EU locales use as a thousands group
# separator: ASCII space, NBSP (U+00A0), NARROW NBSP (U+202F).
_GROUP_WHITESPACE = "   \t"


def _to_number(value: Any) -> float | object | None:
    """Locale-tolerant numeric coercion shared by every numeric rule.

    The data layer is supposed to store/transport numbers locale-independent
    (the architecture guide: "stored/transported numbers locale-independent and only
    formatted at view"). In practice GAEB/Excel imports and some API callers
    still hand us locale-formatted *strings* (German ``"1.234,56"``, French
    ``"1 234,56"``, plain ``"185184.0"``, with optional trailing units like
    ``"0,24 m"``). Calling ``float()`` on those raises ``ValueError``; the
    engine then turns one formatting issue into a synthetic compliance ERROR
    per crashed rule (E-I18N-004). This helper is the single place that
    understands those formats so a rule never crashes on a legal number.

    Returns:
        * ``None`` if ``value`` is ``None`` (missing - caller decides default).
        * a ``float`` if the value is/became a finite number.
        * :data:`_NOT_A_NUMBER` if the value is present but un-parseable as a
          number (caller must treat this as "not a number", never crash).
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass - reject explicitly
        return _NOT_A_NUMBER
    if isinstance(value, (int, float)):
        f = float(value)
        # Reject NaN/Infinity - they would silently poison comparisons.
        return f if f == f and f not in (float("inf"), float("-inf")) else _NOT_A_NUMBER
    if isinstance(value, Decimal):
        try:
            return float(value) if value.is_finite() else _NOT_A_NUMBER
        except (InvalidOperation, ValueError):
            return _NOT_A_NUMBER
    if not isinstance(value, str):
        return _NOT_A_NUMBER

    text = value.strip()
    if not text:
        return _NOT_A_NUMBER

    # Strip a leading sign, remember it, work on the magnitude.
    sign = 1.0
    if text[0] in "+-":
        if text[0] == "-":
            sign = -1.0
        text = text[1:].strip()

    # Drop a trailing unit / annotation (``"3.0 m"``, ``"0,24 m"``,
    # ``"150,00 EUR"``). Keep only the leading numeric run plus its
    # group/decimal separators.
    m = re.match(r"[0-9][0-9.,   \t]*", text)
    if not m:
        return _NOT_A_NUMBER
    numeric = m.group(0).strip(_GROUP_WHITESPACE)
    # Collapse whitespace thousands separators (fr ``1 234,56``).
    for ws in _GROUP_WHITESPACE:
        numeric = numeric.replace(ws, "")
    if not numeric:
        return _NOT_A_NUMBER

    has_dot = "." in numeric
    has_comma = "," in numeric

    if has_dot and has_comma:
        # Both present → the *last-occurring* separator is the decimal point
        # (de ``1.234,56`` → comma decimal; us ``1,234.56`` → dot decimal).
        if numeric.rfind(",") > numeric.rfind("."):
            numeric = numeric.replace(".", "").replace(",", ".")
        else:
            numeric = numeric.replace(",", "")
    elif has_comma:
        # Only commas. ``1,234,567`` (>1 comma, no decimal) is unambiguous
        # US/UK thousands grouping. A *single* comma is the German/EU decimal
        # separator (``0,24``, ``2,5``, ``150,00``) - US thousands ``1,234``
        # virtually always carries a ``.`` decimal part too, which is the
        # both-present branch above, so a lone comma is safely a decimal.
        if numeric.count(",") > 1:
            numeric = numeric.replace(",", "")  # 1,234,567 → 1234567
        else:
            numeric = numeric.replace(",", ".")  # 1,5 / 12,50 / 0,24 → decimal
    elif has_dot:
        # A *single* dot with no comma is always a canonical decimal point
        # (``3.0``, ``0.24``, ``185184.0``) - never reinterpret it, that is
        # the source-of-truth storage format. Only multi-dot strings
        # (``1.234.567``) are unambiguously German thousands grouping.
        if numeric.count(".") > 1:
            numeric = numeric.replace(".", "")

    try:
        return sign * float(numeric)
    except ValueError:
        return _NOT_A_NUMBER


def _median(values: list[float]) -> float:
    """True statistical median.

    For an even-length list this is the mean of the two central elements
    (``statistics.median`` semantics) - not ``sorted[n // 2]`` which is the
    *upper*-middle element and skews threshold-based anomaly detection on
    small even samples (E-VAL-013).
    """
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _num(value: Any, default: float | None = 0.0) -> float | None:
    """Convenience wrapper: parse ``value`` or fall back to ``default``.

    Used by rules that want "missing or unparseable → treated as
    ``default``" semantics (the historical ``float(x or 0)`` behaviour) but
    locale-aware and crash-free.
    """
    parsed = _to_number(value)
    if parsed is None or parsed is _NOT_A_NUMBER:
        return default
    return parsed  # type: ignore[return-value]


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
        for pos in _get_leaf_positions(context):
            qty = pos.get("quantity", 0)
            qty_num = _to_number(qty)
            passed = (
                qty_num is not None and qty_num is not _NOT_A_NUMBER and qty_num > 0  # type: ignore[operator]
            )
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
        for pos in _get_leaf_positions(context):
            rate = pos.get("unit_rate", 0)
            rate_num = _to_number(rate)
            passed = (
                rate_num is not None and rate_num is not _NOT_A_NUMBER and rate_num > 0  # type: ignore[operator]
            )
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
        rates: list[float] = []
        for p in positions:
            raw = p.get("unit_rate")
            if not raw:
                continue
            parsed = _to_number(raw)
            if parsed is None or parsed is _NOT_A_NUMBER:
                continue
            rates.append(parsed)  # type: ignore[arg-type]
        if len(rates) < 3:
            return []

        median = _median(rates)
        threshold = median * 5  # Flag if >5x median

        results: list[RuleResult] = []
        for pos in positions:
            raw_rate = pos.get("unit_rate")
            rate = _num(raw_rate, default=0.0) or 0.0 if raw_rate else 0.0
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

    # Valid top-level groups (1st digit) - DIN 276:2018-12 defines KG 100-800
    # (800 = Finanzierung).
    VALID_TOP_GROUPS = {"1", "2", "3", "4", "5", "6", "7", "8"}

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
        "Flags leaf positions with no parent_id - GAEB LV hierarchy requires "
        "every Leistungsposition to live under a Leistungsgruppe."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_positions(context)
        if not positions:
            return []

        parent_ids: set[str] = {str(p.get("parent_id")) for p in positions if p.get("parent_id") is not None}

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
    Importing such a position silently is almost always a mistake - the
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
            parsed_rate = _to_number(rate)
            if parsed_rate is None or parsed_rate is _NOT_A_NUMBER:
                # Non-numeric / unparseable rate is a formatting issue, not a
                # GAEB pricing violation - keep signals orthogonal.
                continue
            rate_val: float = parsed_rate  # type: ignore[assignment]
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
    description = "Quantities should be rounded to at most 3 decimal places for GAEB X83 exports."

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
            # Unparseable / non-numeric is a *formatting* issue, not a
            # negative value - treat as 0 so a locale string never masquerades
            # as a compliance ERROR (E-I18N-004).
            qty_val = _num(qty, default=0.0) or 0.0
            rate_val = _num(rate, default=0.0) or 0.0
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
            rate = _num(pos.get("unit_rate"), default=0.0) or 0.0
            total = _num(pos.get("total"), default=0.0) or 0.0
            rate_ok = rate <= self.RATE_THRESHOLD
            total_ok = total <= self.TOTAL_THRESHOLD
            passed = rate_ok and total_ok
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                parts: list[str] = []
                if not rate_ok:
                    parts.append(f"unit_rate {_fmt_decimal(rate)} > {self.RATE_THRESHOLD:,}")
                if not total_ok:
                    parts.append(f"total {_fmt_decimal(total)} > {self.TOTAL_THRESHOLD:,}")
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

    # Absolute floor (one currency minor unit - absorbs IEEE-754 noise like
    # 0.1 * 0.2 == 0.020000000000000004) plus a magnitude-aware relative
    # term so a systematic sub-cent drift on large-value positions is no
    # longer invisible (E-VAL-014).
    ABS_TOLERANCE = 0.01
    REL_TOLERANCE = 1e-6

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
            qty_p = _to_number(qty)
            rate_p = _to_number(rate)
            stored_p = _to_number(stored_total)
            # A formatting issue must not masquerade as a consistency ERROR
            # (E-I18N-004) - skip rather than crash/false-flag.
            if (
                qty_p is None
                or qty_p is _NOT_A_NUMBER
                or rate_p is None
                or rate_p is _NOT_A_NUMBER
                or stored_p is None
                or stored_p is _NOT_A_NUMBER
            ):
                continue
            qty_val: float = qty_p  # type: ignore[assignment]
            rate_val: float = rate_p  # type: ignore[assignment]
            stored_val: float = stored_p  # type: ignore[assignment]
            computed = qty_val * rate_val
            diff = abs(computed - stored_val)
            tolerance = max(
                self.ABS_TOLERANCE,
                abs(stored_val) * self.REL_TOLERANCE,
            )
            passed = diff <= tolerance
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
                        "tolerance": tolerance,
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
        for pos in _get_leaf_positions(context):
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


# ── Wave 24: unit-system consistency (metric vs imperial) ──────────────────
# Units that are definitively metric (SI) - m, m2, m3, kg, etc.
_METRIC_BOQ_UNITS: frozenset[str] = frozenset(
    {
        "m",
        "m2",
        "m3",
        "m²",
        "m³",
        "mm",
        "cm",
        "km",
        "lm",  # "laufende meter" (linear metres, common GAEB)
        "kg",
        "t",
        "tonne",
        "l",
        "litre",
        "liter",
        "ha",  # hectare
    },
)
# Units that are definitively imperial (US/UK) - ft, lb, etc.
_IMPERIAL_BOQ_UNITS: frozenset[str] = frozenset(
    {
        "ft",
        "ft2",
        "ft3",
        "sqft",
        "cuft",
        "in",
        "inch",
        "yd",
        "sqyd",
        "cy",  # cubic yards
        "lb",
        "lbs",
        "oz",
        "ton",  # short ton
        "gal",
        "gallon",
    },
)


class BOQUnitSystemConsistencyRule(ValidationRule):
    """Warn when BOQ position units don't match project_unit_system.

    The rule is a single-result rule (returns one RuleResult, not one
    per position) so the UI can present the BOQ-wide mismatch summary
    in the validation dashboard. ``details["mismatch_count"]`` captures
    how many positions disagree and ``details["mismatches"]`` lists up
    to the first 10 by ordinal+unit for drill-down.

    Skips silently when project_unit_system is absent or unrecognised
    (no "unit_system" project setting means the user hasn't opted in to
    this guard yet).
    """

    rule_id = "boq_quality.unit_system_consistency"
    name = "Unit System Consistency"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Warn when BOQ positions use units from a different measurement system than the project (metric vs imperial)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        data = context.data if isinstance(context.data, dict) else {}
        project_system_raw = data.get("project_unit_system")
        if project_system_raw is None:
            # No project-level unit-system configured → nothing to check.
            # Return [] so an otherwise-empty BOQ stays SKIPPED (E-VAL-008).
            return []
        project_system = str(project_system_raw).strip().lower()
        if project_system not in {"metric", "imperial"}:
            # Unknown unit-system value → skip (don't false-positive).
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
        # The "wrong" set is the OTHER system.
        wrong_set = _IMPERIAL_BOQ_UNITS if project_system == "metric" else _METRIC_BOQ_UNITS
        wrong_label = "imperial" if project_system == "metric" else "metric"

        mismatches: list[dict[str, str]] = []
        positions = _get_positions(context)
        for pos in positions:
            unit = (pos.get("unit") or "").strip().lower()
            if not unit:
                continue
            if unit in wrong_set:
                mismatches.append(
                    {
                        "ordinal": str(pos.get("ordinal", "?")),
                        "unit": unit,
                        "id": str(pos.get("id", "")),
                    },
                )
        mismatch_count = len(mismatches)
        if mismatch_count == 0:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                    details={"project_unit_system": project_system},
                )
            ]
        # WARNING: at least one position uses the wrong system.
        first_ordinal = mismatches[0]["ordinal"]
        first_unit = mismatches[0]["unit"]
        # The message string is built locally so the test can assert that
        # both unit-system names appear, plus either the unit or ordinal.
        message = (
            f"Project unit system is '{project_system}' but {mismatch_count} "
            f"BOQ position(s) use {wrong_label} units (e.g. {first_unit} on "
            f"position {first_ordinal})."
        )
        suggestion = (
            f"Convert {wrong_label} units to {project_system} equivalents "
            f"or update the project's unit_system if {wrong_label} is "
            f"actually intended."
        )
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=message,
                suggestion=suggestion,
                details={
                    "project_unit_system": project_system,
                    "wrong_system": wrong_label,
                    "mismatch_count": mismatch_count,
                    "mismatches": mismatches[:10],
                },
            )
        ]


# ── Wave 27: classification country-mismatch nudge (INFO) ──────────────────
# Preferred classification standard per country. The rule fires an INFO
# nudge when a position has classifications but is missing the standard
# the country normally uses (e.g. a German project with MasterFormat
# only and no DIN 276).
_PREFERRED_STANDARD_BY_COUNTRY: dict[str, str] = {
    # DACH → DIN 276
    "DE": "din276",
    "AT": "din276",
    "CH": "din276",
    # UK → NRM
    "GB": "nrm",
    # US → MasterFormat
    "US": "masterformat",
}

# Fallback when only ``region`` is set (no ``country_code``).
_REGION_TO_DEFAULT_COUNTRY: dict[str, str] = {
    "DACH": "DE",
    "UK": "GB",
    "US": "US",
}

_COUNTRY_TO_DISPLAY_NAME: dict[str, str] = {
    "DE": "Germany",
    "AT": "Austria",
    "CH": "Switzerland",
    "GB": "United Kingdom",
    "US": "United States",
}

# Rough cross-walk between DIN 276 KG groups and MasterFormat divisions.
# Used as ``suggested_*`` hints when a position is missing the preferred
# standard. None means "no mapping available - fire nudge but leave
# suggestion blank".
_MF_DIV_TO_DIN276: dict[str, str | None] = {
    "01": "100",  # General requirements → Grundstück
    "02": "200",  # Existing conditions → Vorbereitende Maßnahmen
    "03": "330",  # Concrete → Außenwände / tragende Bauteile
    "04": "330",  # Masonry → tragende Außenwände
    "05": "330",  # Metals → tragende Konstruktion
    "06": "350",  # Wood & plastics → Decken / Holzbau
    "07": "330",  # Thermal & moisture → Außenwand-Abdichtung
    "08": "334",  # Openings → Fenster & Türen
    "09": "340",  # Finishes → Innenwände (Oberflächen)
    "10": "375",  # Specialties
    "11": "375",  # Equipment
    "12": "370",  # Furnishings → Ausstattung
    "13": "390",  # Special construction
    "14": "440",  # Conveying equipment → Aufzüge
    "21": "410",  # Fire suppression → Sanitär / Brandschutz
    "22": "410",  # Plumbing → Sanitäranlagen
    "23": "420",  # HVAC → Wärmeversorgung / RLT
    "26": "440",  # Electrical → Starkstromanlagen
    "27": "450",  # Communications → Fernmelde-Anlagen
    "28": "450",  # Safety & security → Sicherheitsanlagen
    "31": "210",  # Earthwork → Herrichten
    "32": "500",  # Exterior improvements → Außenanlagen
    "33": "590",  # Utilities → Anlagen ausserhalb
}

_DIN276_KG_TO_MF_DIV: dict[str, str] = {
    "100": "01",
    "200": "02",
    "300": "03",  # Bauwerk-Konstruktion family → Concrete (representative)
    "330": "03",
    "340": "09",
    "350": "06",
    "360": "07",
    "370": "12",
    "400": "26",  # Bauwerk-Technik family → Electrical (representative)
    "410": "22",
    "420": "23",
    "440": "26",
    "450": "27",
    "500": "32",
    "600": "12",
    "700": "01",
}

# NRM elements (RICS) → DIN 276 KG / MasterFormat division.
_NRM_ELEM_TO_DIN276: dict[str, str] = {
    "0": "100",  # Facilitating works → Grundstück
    "1": "320",  # Substructure → Gründung
    "2": "330",  # Superstructure → tragende Außenwände
    "3": "340",  # Internal finishes → Innenwände-Oberflächen
    "4": "370",  # Fittings & furniture → Einbauten
    "5": "410",  # Services → Sanitär / MEP
    "6": "440",  # Prefabricated buildings & units
    "7": "210",  # Work to existing buildings → Vorbereitende Maßnahmen
    "8": "500",  # External works → Außenanlagen
}

_NRM_ELEM_TO_MF_DIV: dict[str, str] = {
    "0": "01",
    "1": "31",
    "2": "03",
    "3": "09",
    "4": "12",
    "5": "22",
    "6": "13",
    "7": "02",
    "8": "32",
}


def _normalize_country_code(
    metadata: dict[str, Any],
    region: str | None,
) -> str | None:
    """Resolve the active country code from metadata or fall back to region."""
    cc = metadata.get("country_code") if isinstance(metadata, dict) else None
    if cc:
        return str(cc).strip().upper()
    if region:
        return _REGION_TO_DEFAULT_COUNTRY.get(str(region).strip().upper())
    return None


class ClassificationCountryMismatchRule(ValidationRule):
    """INFO nudge when classification standards don't match the country.

    Returns one RuleResult that summarises the whole BOQ (passed=True if
    no nudge needed, else passed=False with a suggested standard).

    Quiet behaviours:
      * Skip silently when country/region context is unknown.
      * Skip silently when a position has no classifications at all
        (completeness rules own that case).
      * Pass when the preferred standard is present (even alongside
        other standards).
    """

    rule_id = "classification_nudge.country_mismatch"
    name = "Classification Standard Matches Country"
    standard = "classification_nudge"
    severity = Severity.INFO
    category = RuleCategory.COMPLIANCE
    description = (
        "Nudge when a project's classifications don't include the country's "
        "preferred standard (DIN 276 for DACH, NRM for UK, MasterFormat for US)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        metadata = getattr(context, "metadata", {}) or {}
        region = getattr(context, "region", None)
        country = _normalize_country_code(metadata, region)
        # No country context → cannot judge → nothing to emit.
        # Return [] so an otherwise-empty / unregioned BOQ stays SKIPPED (E-VAL-008).
        if not country or country not in _PREFERRED_STANDARD_BY_COUNTRY:
            return []
        preferred = _PREFERRED_STANDARD_BY_COUNTRY[country]
        country_display = _COUNTRY_TO_DISPLAY_NAME.get(country, country)
        positions = _get_positions(context)

        # Find the first position that triggers a nudge - i.e. classifications
        # present but missing the preferred standard for this country.
        nudge_pos: dict[str, Any] | None = None
        for pos in positions:
            cls = pos.get("classification", {}) or {}
            if not cls:
                continue
            if cls.get(preferred):
                continue  # preferred present → no nudge for this row
            # at least one OTHER standard is set → nudge candidate
            if cls.get("din276") or cls.get("nrm") or cls.get("masterformat"):
                nudge_pos = pos
                break

        if nudge_pos is None:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                    details={"country": country},
                )
            ]

        cls = nudge_pos.get("classification", {}) or {}
        details: dict[str, Any] = {
            "country": country,
            "preferred_standard": preferred,
        }
        suggestion_target_display = {
            "din276": "DIN 276",
            "nrm": "NRM",
            "masterformat": "MasterFormat",
        }[preferred]

        # Compute suggested target classification code(s) from whichever
        # other standard the user already supplied.
        if preferred == "din276":
            details["suggested_din276"] = None
            if cls.get("masterformat"):
                mf = str(cls["masterformat"]).strip().split()[0][:2]
                details["suggested_din276"] = _MF_DIV_TO_DIN276.get(mf)
            elif cls.get("nrm"):
                nrm = str(cls["nrm"]).strip().split(".")[0]
                details["suggested_din276"] = _NRM_ELEM_TO_DIN276.get(nrm)
        elif preferred == "nrm":
            details["suggested_nrm"] = None
            if cls.get("din276"):
                # KG 3xx → NRM 2, 4xx → 5, 5xx → 8 (rough)
                kg = str(cls["din276"]).strip()[:1]
                kg_to_nrm = {"1": "0", "2": "1", "3": "2", "4": "5", "5": "8", "6": "4", "7": "0"}
                details["suggested_nrm"] = kg_to_nrm.get(kg)
            elif cls.get("masterformat"):
                mf = str(cls["masterformat"]).strip().split()[0][:2]
                # Best-effort
                mf_to_nrm = {"03": "2", "22": "5", "26": "5", "32": "8"}
                details["suggested_nrm"] = mf_to_nrm.get(mf)
        elif preferred == "masterformat":
            details["suggested_masterformat"] = None
            if cls.get("din276"):
                kg = str(cls["din276"]).strip()[:3]
                details["suggested_masterformat"] = _DIN276_KG_TO_MF_DIV.get(kg)
            elif cls.get("nrm"):
                nrm = str(cls["nrm"]).strip().split(".")[0]
                details["suggested_masterformat"] = _NRM_ELEM_TO_MF_DIV.get(nrm)

        message = (
            f"Project is in {country_display} but positions use a different "
            f"classification standard. Consider adding {suggestion_target_display} "
            f"alongside the existing classification."
        )
        suggestion = (
            f"In {country_display}, {suggestion_target_display} is the standard "
            f"classification expected by clients, regulators and cost databases. "
            f"Adding it improves report compatibility."
        )
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=message,
                suggestion=suggestion,
                element_ref=nudge_pos.get("id"),
                details=details,
            )
        ]


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
            parsed = _to_number(rate)
            if parsed is None or parsed is _NOT_A_NUMBER:
                continue  # Formatting issue - not a benchmark violation
            rate_val: float = parsed  # type: ignore[assignment]
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
        "Flags BOQs where more than 30% of positions use lump sum (lsum) unit - indicates poor estimation granularity"
    )

    THRESHOLD = 0.30  # 30%

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        # Count over leaf positions only: section/header rows never carry a
        # unit, so including them in the denominator dilutes the lump-sum
        # ratio and under-flags lump-sum-heavy BOQs.
        positions = _get_leaf_positions(context)
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
        "Flags positions that account for more than 40% of total BOQ cost - "
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
                # Fallback: compute from quantity × unit_rate (locale-tolerant;
                # an unparseable value contributes 0 rather than crashing).
                qty = pos.get("quantity")
                rate = pos.get("unit_rate")
                if qty is not None and rate is not None:
                    val = (_num(qty, default=0.0) or 0.0) * (_num(rate, default=0.0) or 0.0)
                else:
                    val = 0.0
            else:
                val = _num(pos_total, default=0.0) or 0.0
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
    # Group names kept in English only - passed through {group_name} into
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

    # NRM 1 (3rd ed.) group elements 0-14: 0 = Facilitating works,
    # 9 = Main contractor's preliminaries ... 14 = Inflation.
    VALID_GROUPS = {str(n) for n in range(15)}
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


# ── NBR 12721 Rules (Brazil - ABNT cost-group hierarchy) ───────────────
#
# ABNT NBR 12721 defines the cost-classification structure used by
# Brazilian construction estimators alongside SINAPI compositions. A
# project that follows the standard tags each BOQ position with one of
# the canonical sections (S1 = serviços preliminares, S2 = infra-estrutura,
# S3 = supra-estrutura, S4 = vedações, S5 = cobertura, S6 = instalações,
# S7 = revestimentos, S8 = pavimentação, S9 = esquadrias, S10 = pintura,
# S11 = serviços complementares). Recognising these as a first-class
# classification scheme (next to DIN 276 / NRM / MasterFormat) gives the
# Brazilian estimator a way to validate scope completeness against ABNT.


class NBR12721ClassificationRequired(ValidationRule):
    rule_id = "nbr.classification_required"
    name = "NBR 12721 Classification Required"
    standard = "nbr"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should carry an ABNT NBR 12721 section code (S1–S11)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("nbr", "")
            passed = bool(code)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "nbr.classification_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "nbr.classification_required.suggestion",
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


class NBR12721ValidSection(ValidationRule):
    rule_id = "nbr.valid_section"
    name = "Valid NBR 12721 Section"
    standard = "nbr"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "NBR 12721 section codes must be one of S1..S11"

    VALID_SECTIONS = {f"S{n}" for n in range(1, 12)}
    _PATTERN = re.compile(r"^S(1[0-1]|[1-9])(\.\d+)*$", re.IGNORECASE)

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("nbr", "")).strip()
            if not code:
                continue
            passed = bool(self._PATTERN.match(code))
            message = (
                _ok(locale)
                if passed
                else translate(
                    "nbr.valid_section.fail",
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
        # Use leaf positions only: section/header rows intentionally carry no
        # unit_rate, so counting them in the denominator understates the
        # pricing-completeness ratio (matches PositionHasUnitRate).
        positions = _get_leaf_positions(context)
        if not positions:
            return []
        priced = sum(1 for p in positions if p.get("unit_rate") and (_num(p["unit_rate"], default=0.0) or 0.0) > 0)
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


# ── BC3 / FIEBDC-3 Rules (Spain + LATAM) ────────────────────────────────


class BC3CodeRequired(ValidationRule):
    """Every BC3 position must have a FIEBDC-3 concept code.

    BC3 ties every partida back to a concept code (``~C`` record); a
    position without one cannot be exported back to FIEBDC-3 without
    losing the original catalogue reference. Rule fires only when the
    project's classification_standard is bc3 or region is ES / LATAM -
    other regions can leave the field blank without penalty.
    """

    rule_id = "bc3.code_required"
    name = "BC3 Concept Code Required"
    standard = "bc3"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a FIEBDC-3 concept code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            # Skip section rows - chapters carry their own code in ordinal.
            if (pos.get("type") or "position") == "section":
                continue
            classification = pos.get("classification") or {}
            code = classification.get("bc3_code") or classification.get("code") or ""
            passed = bool(str(code).strip())
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "bc3.code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "bc3.code_required.suggestion",
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


class BC3ValidCode(ValidationRule):
    """FIEBDC-3 concept codes follow a hierarchical dotted/hash format.

    Valid patterns (per the FIEBDC-3 specification):

    * Chapter:    ``CC#`` / ``CC.CC#`` (trailing ``#`` is the chapter marker)
    * Partida:    ``CCCC.CCCC.CCCC`` (1–4 alphanumeric segments)
    * Resource:   ``%`` prefix (auxiliary; not normally surfaced as a BOQ row)

    Codes can be alphanumeric (e.g. ``E04CM040`` is a valid common code).
    We reject obviously malformed values (spaces, leading dots, control
    chars) - the FIEBDC-3 spec doesn't fix a strict length, so we lean
    on shape rather than length.
    """

    rule_id = "bc3.valid_code"
    name = "Valid FIEBDC-3 Code Format"
    standard = "bc3"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "FIEBDC-3 codes must use the canonical alphanumeric / dotted format"

    _PATTERN = re.compile(r"^[A-Za-z0-9_%][A-Za-z0-9_.#%-]*$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            classification = pos.get("classification") or {}
            code = str(classification.get("bc3_code") or classification.get("code") or "").strip()
            if not code:
                continue
            # Reject whitespace, leading dot, and shapes the spec forbids.
            passed = bool(self._PATTERN.match(code)) and not code.startswith(".")
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "bc3.valid_code.fail",
                    locale=locale,
                    code=code,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate(
                    "bc3.valid_code.suggestion",
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
        if not positions:
            # An empty BOQ has nothing to be consistent about. Emitting a
            # *passing* row here is what made an empty estimate look "100%
            # green" instead of SKIPPED (E-VAL-008) - return nothing so the
            # engine's no-results → SKIPPED branch can fire.
            return []
        currencies: set[str] = set()
        for pos in positions:
            ccy = _position_currency(pos)
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
        if not positions:
            # See CurrencyConsistency - no positions means nothing to check;
            # a passing row here defeats the SKIPPED status (E-VAL-008).
            return []
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


# ── Revision-compare cost-impact review (Item 17) ───────────────────────────


class RevisionCostImpactReview(ValidationRule):
    """Advisory: a priced revision change should become a controlled variation.

    When a drawing / PDF revision compare reports a non-zero
    ``net_cost_impact`` but no variation request has been raised from it
    yet, this rule flags the gap so the cost change is captured in the
    commercial workflow rather than slipping through silently. It is a
    WARNING (advisory, never blocks) per the "AI proposes, human confirms"
    principle - the user creates the draft variation from the compare
    drawer.

    The compare result is supplied to the engine via
    ``ValidationContext.data`` (or ``context.data["compare"]``) with the
    shape returned by ``compare_drawing_versions`` /
    ``compare_documents``: a ``summary`` carrying ``net_cost_impact``.
    ``context.metadata["variation_request_exists"]`` (truthy) marks that a
    variation has already been raised, so re-validating after the handoff
    passes cleanly.
    """

    rule_id = "boq_quality.revision_cost_impact_review"
    name = "Revision cost impact needs a variation"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "A revision change with a non-zero cost impact should be turned "
        "into a controlled variation request rather than left untracked."
    )

    @staticmethod
    def _extract_net_impact(data: Any) -> Decimal | None:
        """Pull ``net_cost_impact`` out of a compare-result-shaped payload."""
        if not isinstance(data, dict):
            return None
        summary = data.get("summary")
        if not isinstance(summary, dict):
            # Allow the summary itself to be passed directly.
            summary = data if "net_cost_impact" in data else {}
        raw = summary.get("net_cost_impact")
        if raw in (None, ""):
            return None
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            return None

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        net_impact = self._extract_net_impact(context.data)
        if net_impact is None:
            # No compare payload / no priced change in this context - nothing
            # to assert (a passing row here would defeat SKIPPED status).
            return []

        meta = getattr(context, "metadata", None) or {}
        variation_exists = bool(meta.get("variation_request_exists")) if isinstance(meta, dict) else False

        if net_impact != 0 and not variation_exists:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "boq_quality.revision_cost_impact_review.fail",
                        locale=locale,
                        amount=_fmt_decimal(float(net_impact)),
                    ),
                    suggestion=translate(
                        "boq_quality.revision_cost_impact_review.suggestion",
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


# ── Pipeline Builder graph-validity rule ────────────────────────────────────


class PipelineSideEffectGated(ValidationRule):
    """Structural "AI proposes, human confirms" gate (design §3.5).

    Fails the graph (ERROR - blocks publish) if any ``side_effecting``
    node can be reached from a trigger/AI node *without* passing through a
    ``gate.validation`` or ``gate.human_approval`` on that path. A failing
    graph stays ``is_published=false`` and cannot be triggered.

    The ``data`` shape is ``{"graph": {"nodes":[...], "edges":[...]}}``.
    ``side_effecting`` is read from the Node Capability Registry so the
    rule never drifts from what a node actually does.
    """

    rule_id = "pipeline.side_effecting_requires_gate"
    name = "Side-effecting node requires a gate"
    standard = "pipeline"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = (
        "Every side-effecting (write) node must have a validation or "
        "human-approval gate on every path from a trigger/AI node to it."
    )

    _GATE_TYPES = frozenset({"gate.validation", "gate.human_approval"})
    _TRIGGER_PREFIXES = ("trigger.", "ai.")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        data = context.data if isinstance(context.data, dict) else {}
        graph = data.get("graph") if isinstance(data, dict) else None
        if not isinstance(graph, dict):
            return []
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        if not nodes:
            return []

        from app.core.pipeline.registry import node_registry

        node_type: dict[str, str] = {str(n.get("id")): str(n.get("type") or "") for n in nodes}
        in_edges: dict[str, list[str]] = {nid: [] for nid in node_type}
        for e in edges:
            src = str(e.get("source") or "")
            dst = str(e.get("target") or "")
            if src in node_type and dst in node_type:
                in_edges.setdefault(dst, []).append(src)

        def is_side_effecting(nid: str) -> bool:
            spec = node_registry.get(node_type.get(nid, ""))
            return bool(spec and spec.side_effecting)

        def is_gate(nid: str) -> bool:
            return node_type.get(nid, "") in self._GATE_TYPES

        def is_origin(nid: str) -> bool:
            t = node_type.get(nid, "")
            return t.startswith(self._TRIGGER_PREFIXES) or not in_edges.get(nid)

        # For every side-effecting node, walk every path backwards to an
        # origin. If ANY such path has no gate, the graph fails. We do a
        # DFS over reversed edges, treating a gate as a "satisfied" wall.
        violations: list[str] = []
        for target, ttype in node_type.items():
            if not is_side_effecting(target):
                continue

            stack: list[tuple[str, bool]] = [(target, False)]
            seen: set[tuple[str, bool]] = set()
            ungated_path = False
            while stack:
                cur, gated = stack.pop()
                if (cur, gated) in seen:
                    continue
                seen.add((cur, gated))
                # A gate anywhere upstream of `target` (not the target
                # itself) satisfies that branch.
                cur_gated = gated or (cur != target and is_gate(cur))
                preds = in_edges.get(cur, [])
                if is_origin(cur) or not preds:
                    if not cur_gated:
                        ungated_path = True
                        break
                    continue
                for p in preds:
                    stack.append((p, cur_gated))
            if ungated_path:
                violations.append(f"{target} ({ttype})")

        if violations:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "pipeline.side_effecting_requires_gate.fail",
                        locale=locale,
                        nodes=", ".join(sorted(violations)),
                    ),
                    details={"ungated_nodes": sorted(violations)},
                    suggestion=translate(
                        "pipeline.side_effecting_requires_gate.suggestion",
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


# ── Property Development rules (task #139) ─────────────────────────────────
#
# Eight DB-backed rules covering escrow / contract / payment-schedule /
# reservation / broker / price-matrix concerns for the ``property_dev``
# module. Unlike the BOQ-shaped rules above these rules pull live rows from
# the ORM via a SQLAlchemy session passed through
# ``ValidationContext.metadata["session"]`` and a ``development_id``
# (UUID or string) passed through ``metadata["development_id"]``.
#
# Pattern (shared by all 8):
#     async def validate(self, context):
#         ctx = _propdev_context(context)
#         if ctx is None:
#             return []        # not enough context - skip cleanly
#         session, dev_id = ctx
#         ...                  # query, compute, build results
#
# Each rule emits one PASS row when nothing is wrong (so the dashboard
# shows a green tile) or one FAIL row per affected entity (so drill-down
# carries a real element_ref). Severity / category are class attributes
# so the registry, UI and tests can introspect without instantiating.


def _propdev_context(context: ValidationContext) -> tuple[Any, Any] | None:
    """Pull session + development_id from a property-dev rule context.

    Returns ``None`` when either is missing so the caller can short-circuit
    with an empty result list (rules MUST NOT raise on missing context -
    that would surface as a phantom DIAGNOSTIC engine-error row).
    """
    meta = getattr(context, "metadata", None) or {}
    if not isinstance(meta, dict):
        return None
    session = meta.get("session")
    dev_id_raw = meta.get("development_id") or context.project_id
    if session is None or dev_id_raw is None:
        return None
    try:
        import uuid as _uuid

        dev_id = dev_id_raw if isinstance(dev_id_raw, _uuid.UUID) else _uuid.UUID(str(dev_id_raw))
    except (ValueError, AttributeError, TypeError):
        return None
    return session, dev_id


# Regulators that mandate a dedicated escrow account before sales can
# open. Used by ``PropDevEscrowAccountRequired`` and surfaced to the UI
# via the dashboard's ``rule_sets`` field.
_PROPDEV_REGULATORS_REQUIRING_ESCROW = {"RERA", "MAHARERA", "214FZ", "CMA"}


# ISO 13616 IBAN length table (country code → expected total length).
# Truncated to the regulators we care about for property_dev. Unknown
# country codes get a length-only sanity check (15-34 chars).
_IBAN_LENGTHS: dict[str, int] = {
    "AE": 23,  # UAE (RERA)
    "AT": 20,
    "BE": 16,
    "CH": 21,
    "DE": 22,
    "ES": 24,
    "FR": 27,
    "GB": 22,
    "IN": 0,  # India does not use IBAN (length=0 → skip length check)
    "IT": 27,
    "NL": 18,
    "PL": 28,
    "PT": 25,
    "RU": 33,
    "SA": 24,  # Saudi Arabia (CMA)
    "TR": 26,
    "UA": 29,
    "US": 0,  # US does not use IBAN
}


def _iban_is_valid(iban: str) -> bool:
    """ISO 13616 structural check: country + length + mod-97 checksum.

    Returns ``False`` for empty strings, too-short strings, non-IBAN
    countries, and any IBAN whose mod-97 remainder is not 1.
    """
    if not isinstance(iban, str):
        return False
    raw = iban.replace(" ", "").upper()
    if len(raw) < 15 or len(raw) > 34:
        return False
    if not raw[:2].isalpha() or not raw[2:4].isdigit():
        return False
    country = raw[:2]
    expected_len = _IBAN_LENGTHS.get(country)
    if expected_len is None:
        # Unknown country - accept range only.
        if not (15 <= len(raw) <= 34):
            return False
    elif expected_len > 0 and len(raw) != expected_len:
        return False
    # Mod-97 checksum (move first 4 chars to end, convert letters to digits).
    rotated = raw[4:] + raw[:4]
    digits = []
    for ch in rotated:
        if ch.isdigit():
            digits.append(ch)
        elif ch.isalpha():
            digits.append(str(ord(ch) - 55))
        else:
            return False
    try:
        return int("".join(digits)) % 97 == 1
    except ValueError:
        return False


class PropDevEscrowAccountRequired(ValidationRule):
    """ERROR: regulator requires an active escrow account but none exists.

    For each Development whose ``metadata.regulator`` (or the legacy
    ``metadata.jurisdiction``-derived inference) is one of
    ``RERA``/``MAHARERA``/``214FZ``/``CMA`` we expect at least one
    :class:`EscrowAccount` row with ``is_active=True``. Replaces the
    pre-R6 ``Development.metadata["escrow_accounts"]`` workaround.
    """

    rule_id = "property_dev.escrow_account_required"
    name = "Escrow account required"
    standard = "property_dev"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "Developments whose jurisdiction mandates regulator-supervised "
        "escrow (RERA/MAHARERA/214FZ/CMA) must have at least one active "
        "EscrowAccount row."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import Development, EscrowAccount

        dev = await session.get(Development, dev_id)
        if dev is None:
            return []
        meta = dev.metadata_ or {}
        regulator = (meta.get("regulator") or "").upper() if isinstance(meta, dict) else ""
        if not regulator:
            # Best-effort inference from jurisdiction.
            jurisdiction = (meta.get("jurisdiction") if isinstance(meta, dict) else "") or ""
            jurisdiction = jurisdiction.upper()
            if jurisdiction.startswith("AE"):
                regulator = "RERA"
            elif jurisdiction.startswith("IN"):
                regulator = "MAHARERA"
            elif jurisdiction.startswith("RU"):
                regulator = "214FZ"
            elif jurisdiction.startswith("SA"):
                regulator = "CMA"
        if regulator not in _PROPDEV_REGULATORS_REQUIRING_ESCROW:
            # Not subject to escrow rules - pass.
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
        stmt = (
            _sql_select(EscrowAccount.id)
            .where(EscrowAccount.development_id == dev_id)
            .where(EscrowAccount.is_active.is_(True))
        )
        active_count = len(list((await session.execute(stmt)).scalars().all()))
        if active_count >= 1:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                    details={"regulator": regulator, "active_accounts": active_count},
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
                    "property_dev.escrow_account_required.fail",
                    locale=locale,
                    regulator=regulator,
                ),
                element_ref=f"property_dev:development:{dev_id}",
                details={"regulator": regulator, "active_accounts": 0},
                suggestion=translate(
                    "property_dev.escrow_account_required.suggestion",
                    locale=locale,
                ),
            )
        ]


class PropDevEscrowIBANValid(ValidationRule):
    """ERROR: every active EscrowAccount.iban must pass ISO 13616 check."""

    rule_id = "property_dev.escrow_iban_valid"
    name = "Escrow IBAN structurally valid"
    standard = "property_dev"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = (
        "All active escrow accounts must declare an IBAN that passes "
        "ISO 13616 structural validation (country code, length, mod-97 "
        "checksum). Non-IBAN countries (IN, US) are exempt."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import EscrowAccount

        stmt = (
            _sql_select(EscrowAccount)
            .where(EscrowAccount.development_id == dev_id)
            .where(EscrowAccount.is_active.is_(True))
        )
        accounts = list((await session.execute(stmt)).scalars().all())
        if not accounts:
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
        results: list[RuleResult] = []
        all_pass = True
        for acc in accounts:
            iban = (acc.iban or "").strip()
            country = iban[:2].upper() if iban else ""
            # Empty IBAN OR India/US (no IBAN regime) → skip silently.
            if not iban or _IBAN_LENGTHS.get(country, -1) == 0:
                continue
            if not _iban_is_valid(iban):
                all_pass = False
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "property_dev.escrow_iban_valid.fail",
                            locale=locale,
                            account=str(acc.id),
                            iban=iban,
                        ),
                        element_ref=f"property_dev:escrow_account:{acc.id}",
                        details={"escrow_account_id": str(acc.id), "iban": iban},
                        suggestion=translate(
                            "property_dev.escrow_iban_valid.suggestion",
                            locale=locale,
                        ),
                    )
                )
        if all_pass:
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
        return results


class PropDevEscrowBalanceReconciled(ValidationRule):
    """WARNING: per-account ledger total drifts from transactions sum.

    Computes ``credit_total - debit_total`` from
    :class:`EscrowTransaction` rows and compares against the implicit
    ``EscrowAccount`` ledger (we treat the txn sum as ground truth and
    flag accounts whose ``metadata.ledger_balance`` declares something
    different). Drift > 0.01 currency unit triggers WARNING (it is a
    soft signal - actual reconciliation lives in the dedicated workflow).
    """

    rule_id = "property_dev.escrow_balance_reconciled"
    name = "Escrow balance reconciled"
    standard = "property_dev"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Sum of EscrowTransaction credit minus debit must equal the "
        "account's declared ledger balance (metadata.ledger_balance), "
        "within ±0.01 currency unit."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from sqlalchemy import func as _sql_func
        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import (
            EscrowAccount,
            EscrowTransaction,
        )

        acc_stmt = (
            _sql_select(EscrowAccount)
            .where(EscrowAccount.development_id == dev_id)
            .where(EscrowAccount.is_active.is_(True))
        )
        accounts = list((await session.execute(acc_stmt)).scalars().all())
        if not accounts:
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
        results: list[RuleResult] = []
        any_drift = False
        for acc in accounts:
            meta = acc.metadata_ or {}
            declared_raw = meta.get("ledger_balance") if isinstance(meta, dict) else None
            if declared_raw is None:
                # No declared ledger - nothing to compare against. Skip.
                continue
            try:
                declared = Decimal(str(declared_raw))
            except (InvalidOperation, ValueError, TypeError):
                continue
            tx_stmt = (
                _sql_select(
                    EscrowTransaction.direction,
                    _sql_func.coalesce(_sql_func.sum(EscrowTransaction.amount), 0),
                    _sql_func.count(),
                )
                .where(EscrowTransaction.escrow_account_id == acc.id)
                .group_by(EscrowTransaction.direction)
            )
            credit = Decimal("0")
            debit = Decimal("0")
            tx_count = 0
            for direction, total, cnt in (await session.execute(tx_stmt)).all():
                if direction == "credit":
                    credit = Decimal(str(total or 0))
                elif direction == "debit":
                    debit = Decimal(str(total or 0))
                tx_count += int(cnt or 0)
            computed = credit - debit
            drift = (computed - declared).copy_abs()
            if drift > Decimal("0.01"):
                any_drift = True
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "property_dev.escrow_balance_reconciled.fail",
                            locale=locale,
                            account=str(acc.id),
                            ledger=str(declared.quantize(Decimal("0.01"))),
                            drift=str(drift.quantize(Decimal("0.01"))),
                            transactions=tx_count,
                        ),
                        element_ref=f"property_dev:escrow_account:{acc.id}",
                        details={
                            "escrow_account_id": str(acc.id),
                            "declared_ledger": str(declared),
                            "computed_from_txns": str(computed),
                            "drift": str(drift),
                            "transaction_count": tx_count,
                        },
                        suggestion=translate(
                            "property_dev.escrow_balance_reconciled.suggestion",
                            locale=locale,
                        ),
                    )
                )
        if not any_drift:
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
        return results


class PropDevSalesContractPartyOwnershipSumsTo100(ValidationRule):
    """ERROR: sum of ContractParty.ownership_pct must equal 100.00 exactly."""

    rule_id = "property_dev.sales_contract_party_ownership_sums_to_100"
    name = "Contract party ownership sums to 100%"
    standard = "property_dev"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "Every SalesContract's parties must collectively own 100.00% - neither over-subscribed nor under-allocated."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import (
            ContractParty,
            Plot,
            SalesContract,
        )

        # SalesContracts indirectly belong to a Development through Plot.
        contract_stmt = (
            _sql_select(SalesContract).join(Plot, Plot.id == SalesContract.plot_id).where(Plot.development_id == dev_id)
        )
        contracts = list((await session.execute(contract_stmt)).scalars().all())
        if not contracts:
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
        results: list[RuleResult] = []
        any_bad = False
        for c in contracts:
            party_stmt = _sql_select(ContractParty).where(ContractParty.sales_contract_id == c.id)
            parties = list((await session.execute(party_stmt)).scalars().all())
            if not parties:
                # Draft contracts with zero parties → out of scope; skip.
                continue
            total = sum(
                (Decimal(str(p.ownership_pct or 0)) for p in parties),
                Decimal("0"),
            )
            if total != Decimal("100.00") and total != Decimal("100"):
                any_bad = True
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "property_dev.sales_contract_party_ownership_sums_to_100.fail",
                            locale=locale,
                            contract=str(c.id),
                            total=str(total.quantize(Decimal("0.01"))),
                        ),
                        element_ref=f"property_dev:sales_contract:{c.id}",
                        details={
                            "sales_contract_id": str(c.id),
                            "contract_number": c.contract_number,
                            "ownership_total": str(total),
                            "party_count": len(parties),
                        },
                        suggestion=translate(
                            "property_dev.sales_contract_party_ownership_sums_to_100.suggestion",
                            locale=locale,
                        ),
                    )
                )
        if not any_bad:
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
        return results


class PropDevPaymentScheduleInstalmentsSumToContractValue(ValidationRule):
    """ERROR: instalment amounts must add up to SalesContract.total_value."""

    rule_id = "property_dev.payment_schedule_instalments_sum_to_contract_value"
    name = "Payment schedule sums to contract value"
    standard = "property_dev"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "Every PaymentSchedule attached to a SalesContract must have its "
        "Instalment amounts sum to the contract's total_value (within "
        "±0.01 currency unit)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import (
            Instalment,
            PaymentSchedule,
            Plot,
            SalesContract,
        )

        contract_stmt = (
            _sql_select(SalesContract).join(Plot, Plot.id == SalesContract.plot_id).where(Plot.development_id == dev_id)
        )
        contracts = list((await session.execute(contract_stmt)).scalars().all())
        if not contracts:
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
        results: list[RuleResult] = []
        any_bad = False
        for c in contracts:
            sched_stmt = _sql_select(PaymentSchedule).where(PaymentSchedule.sales_contract_id == c.id)
            sched = (await session.execute(sched_stmt)).scalar_one_or_none()
            if sched is None:
                # No schedule yet - not the consistency rule's concern.
                continue
            inst_stmt = _sql_select(Instalment).where(Instalment.schedule_id == sched.id)
            instalments = list((await session.execute(inst_stmt)).scalars().all())
            instalment_total = sum(
                (Decimal(str(i.amount or 0)) for i in instalments),
                Decimal("0"),
            )
            contract_value = Decimal(str(c.total_value or 0))
            drift = (instalment_total - contract_value).copy_abs()
            if drift > Decimal("0.01"):
                any_bad = True
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "property_dev.payment_schedule_instalments_sum_to_contract_value.fail",
                            locale=locale,
                            contract=str(c.id),
                            instalments=str(instalment_total.quantize(Decimal("0.01"))),
                            contract_value=str(contract_value.quantize(Decimal("0.01"))),
                            drift=str(drift.quantize(Decimal("0.01"))),
                        ),
                        element_ref=f"property_dev:sales_contract:{c.id}",
                        details={
                            "sales_contract_id": str(c.id),
                            "schedule_id": str(sched.id),
                            "contract_value": str(contract_value),
                            "instalment_total": str(instalment_total),
                            "drift": str(drift),
                        },
                        suggestion=translate(
                            "property_dev.payment_schedule_instalments_sum_to_contract_value.suggestion",
                            locale=locale,
                        ),
                    )
                )
        if not any_bad:
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
        return results


class PropDevReservationExpiryInFuture(ValidationRule):
    """WARNING: active Reservation must have expires_at in the future."""

    rule_id = "property_dev.reservation_expiry_in_future"
    name = "Active reservation expiry in future"
    standard = "property_dev"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Every Reservation in status='active' must have expires_at strictly "
        "in the future. Expired active rows must be transitioned to "
        "'expired'/'cancelled'."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from datetime import UTC as _UTC
        from datetime import datetime as _dt

        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import Plot, Reservation

        stmt = (
            _sql_select(Reservation)
            .join(Plot, Plot.id == Reservation.plot_id)
            .where(Plot.development_id == dev_id)
            .where(Reservation.status == "active")
        )
        reservations = list((await session.execute(stmt)).scalars().all())
        if not reservations:
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
        now_iso = _dt.now(_UTC).date().isoformat()
        results: list[RuleResult] = []
        any_bad = False
        for r in reservations:
            exp = (r.expires_at or "").strip()
            if not exp:
                # Active reservation with no expiry → bad.
                any_bad = True
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "property_dev.reservation_expiry_in_future.fail",
                            locale=locale,
                            reservation=str(r.id),
                            expires="",
                        ),
                        element_ref=f"property_dev:reservation:{r.id}",
                        details={
                            "reservation_id": str(r.id),
                            "reservation_number": r.reservation_number,
                            "expires_at": "",
                        },
                        suggestion=translate(
                            "property_dev.reservation_expiry_in_future.suggestion",
                            locale=locale,
                        ),
                    )
                )
                continue
            # ISO YYYY-MM-DD string comparison works lexicographically.
            if exp <= now_iso:
                any_bad = True
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "property_dev.reservation_expiry_in_future.fail",
                            locale=locale,
                            reservation=str(r.id),
                            expires=exp,
                        ),
                        element_ref=f"property_dev:reservation:{r.id}",
                        details={
                            "reservation_id": str(r.id),
                            "reservation_number": r.reservation_number,
                            "expires_at": exp,
                            "now": now_iso,
                        },
                        suggestion=translate(
                            "property_dev.reservation_expiry_in_future.suggestion",
                            locale=locale,
                        ),
                    )
                )
        if not any_bad:
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
        return results


class PropDevBrokerCommissionRateWithinBounds(ValidationRule):
    """ERROR: discriminated-union shape + bounds check on each agreement.

    - structure_type='percent' → ``structure["pct"]`` between 0.1% and 15%.
    - structure_type='flat'    → ``structure["amount"]`` > 0.
    - structure_type='ladder'  → ``structure["tiers"]`` non-empty list.
    """

    rule_id = "property_dev.broker_commission_rate_within_bounds"
    name = "Broker commission within bounds"
    standard = "property_dev"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = (
        "Each CommissionAgreement must declare a valid structure: percent "
        "agreements need a rate between 0.1% and 15%, flat agreements need "
        "an amount, ladder agreements need at least one tier."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from sqlalchemy import or_ as _sql_or
        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import CommissionAgreement

        stmt = _sql_select(CommissionAgreement).where(
            _sql_or(
                CommissionAgreement.development_id == dev_id,
                CommissionAgreement.development_id.is_(None),
            )
        )
        agreements = list((await session.execute(stmt)).scalars().all())
        if not agreements:
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
        results: list[RuleResult] = []
        any_bad = False
        for a in agreements:
            structure = a.structure or {}
            stype = (a.structure_type or "percent").lower()
            issue: str | None = None
            if stype == "percent":
                pct_raw = structure.get("pct") if isinstance(structure, dict) else None
                try:
                    pct = Decimal(str(pct_raw)) if pct_raw is not None else None
                except (InvalidOperation, ValueError, TypeError):
                    pct = None
                if pct is None:
                    issue = "percent agreement missing 'pct'"
                else:
                    # Heuristic: rate may be expressed as 0.025 (=2.5%) or 2.5.
                    rate = pct / Decimal("100") if pct > Decimal("1") else pct
                    if rate < Decimal("0.001") or rate > Decimal("0.15"):
                        issue = f"percent rate {pct} outside permitted range 0.1%-15%"
            elif stype == "flat":
                amt_raw = structure.get("amount") if isinstance(structure, dict) else None
                try:
                    amt = Decimal(str(amt_raw)) if amt_raw is not None else None
                except (InvalidOperation, ValueError, TypeError):
                    amt = None
                if amt is None or amt <= Decimal("0"):
                    issue = "flat agreement requires positive 'amount'"
            elif stype == "ladder":
                tiers = structure.get("tiers") if isinstance(structure, dict) else None
                if not isinstance(tiers, list) or not tiers:
                    issue = "ladder agreement requires non-empty 'tiers'"
            else:
                issue = f"unknown structure_type '{stype}'"
            if issue is not None:
                any_bad = True
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "property_dev.broker_commission_rate_within_bounds.fail",
                            locale=locale,
                            agreement=str(a.id),
                            issue=issue,
                        ),
                        element_ref=f"property_dev:commission_agreement:{a.id}",
                        details={
                            "agreement_id": str(a.id),
                            "broker_id": str(a.broker_id),
                            "structure_type": stype,
                            "issue": issue,
                        },
                        suggestion=translate(
                            "property_dev.broker_commission_rate_within_bounds.suggestion",
                            locale=locale,
                        ),
                    )
                )
        if not any_bad:
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
        return results


class PropDevPriceMatrixNoNegativeModifier(ValidationRule):
    """WARNING: every PriceMatrix.rules multiplier must be in [-0.50, 2.00].

    Bounds are chosen to keep the final plot price in a sane envelope
    (-50% discount to +200% premium per factor). Modifiers outside this
    range almost always indicate a data-entry mistake.
    """

    rule_id = "property_dev.price_matrix_no_negative_modifier"
    name = "Price matrix modifier in range"
    standard = "property_dev"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "Each PriceMatrix rule's multiplier must lie within [-0.50, 2.00] "
        "(a -50% discount through +200% premium per factor)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        locale = _get_locale(context)

        from sqlalchemy import select as _sql_select

        from app.modules.property_dev.models import PriceMatrix

        stmt = _sql_select(PriceMatrix).where(PriceMatrix.development_id == dev_id)
        matrices = list((await session.execute(stmt)).scalars().all())
        if not matrices:
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
        results: list[RuleResult] = []
        any_bad = False
        for m in matrices:
            rules_blob = m.rules or []
            if not isinstance(rules_blob, list):
                continue
            for r in rules_blob:
                if not isinstance(r, dict):
                    continue
                factor = r.get("factor_type") or r.get("factor") or "?"
                mult_raw = r.get("multiplier")
                if mult_raw is None:
                    mult_raw = r.get("price_modifier")
                if mult_raw is None:
                    continue
                try:
                    mult = Decimal(str(mult_raw))
                except (InvalidOperation, ValueError, TypeError):
                    continue
                if mult < Decimal("-0.50") or mult > Decimal("2.00"):
                    any_bad = True
                    results.append(
                        RuleResult(
                            rule_id=self.rule_id,
                            rule_name=self.name,
                            severity=self.severity,
                            category=self.category,
                            passed=False,
                            message=translate(
                                "property_dev.price_matrix_no_negative_modifier.fail",
                                locale=locale,
                                matrix=str(m.id),
                                factor=str(factor),
                                multiplier=str(mult),
                            ),
                            element_ref=f"property_dev:price_matrix:{m.id}",
                            details={
                                "price_matrix_id": str(m.id),
                                "factor_type": str(factor),
                                "multiplier": str(mult),
                            },
                            suggestion=translate(
                                "property_dev.price_matrix_no_negative_modifier.suggestion",
                                locale=locale,
                            ),
                        )
                    )
        if not any_bad:
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
        return results


# ── Schedule Quality Rules (C1 - DCMA-14-style health checks) ───────────────
#
# A small pack of network-quality checks over a project schedule, modelled
# on the public DCMA 14-point assessment used as an owner / audit gate on
# public work. Each rule inspects the schedule data the platform already
# stores (activities + relationships from the schedule module), so the pack
# is migration-free: no new tables, no new columns.
#
# Expected ValidationContext.data shape (a dict):
#
#   {
#     "activities": [
#       {
#         "id": "a1",
#         "name": "Excavate footings",
#         "duration_days": 5,
#         "activity_type": "task",          # "milestone" rows are exempt where noted
#         "total_float": 3,                 # int | None - from the CPM pass
#         "is_critical": false,
#         "constraint_type": "must_finish_on",  # None for ASAP/ALAP (soft)
#         "dependencies": [...],            # inline links - counted as logic too
#       },
#       ...
#     ],
#     "relationships": [
#       {"predecessor_id": "a1", "successor_id": "a2",
#        "relationship_type": "FS", "lag_days": 0},
#       ...
#     ],
#   }
#
# Field names mirror the schedule ORM (``Activity`` + ``ScheduleRelationship``)
# so a loader can flatten the rows straight into these dicts. Rules return the
# same RuleResult shape as every other rule in this file.

# Constraint types that hard-pin an activity date and therefore override the
# schedule logic (DCMA "hard constraint" check). ASAP / ALAP and the
# soft "no earlier / no later" window constraints are NOT flagged - only the
# constraints that fully fix a date are.
_HARD_CONSTRAINT_TYPES: frozenset[str] = frozenset(
    {
        "must_start_on",
        "must_finish_on",
        "mandatory_start",
        "mandatory_finish",
    },
)

# Activity types that legitimately carry zero duration - missing-duration and
# open-end logic checks skip these.
_ZERO_DURATION_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {
        "milestone",
        "start_milestone",
        "finish_milestone",
        "hammock",
        "wbs",
        "summary",
        "level_of_effort",
    },
)


def _get_activities(context: ValidationContext) -> list[dict[str, Any]]:
    """Extract the activity list from context data (tolerant of shapes).

    Accepts either ``{"activities": [...]}`` or ``{"tasks": [...]}`` or a bare
    list. Returns ``[]`` when no activities are present so a rule stays
    SKIPPED rather than firing false positives on an empty schedule.
    """
    data = context.data
    if isinstance(data, dict):
        acts = data.get("activities")
        if isinstance(acts, list):
            return acts
        tasks = data.get("tasks")
        if isinstance(tasks, list):
            return tasks
        return []
    if isinstance(data, list):
        return data
    return []


def _get_relationships(context: ValidationContext) -> list[dict[str, Any]]:
    """Extract explicit relationship rows from context data.

    Accepts ``relationships`` or the legacy alias ``links``. Returns ``[]``
    when none are present.
    """
    data = context.data
    if isinstance(data, dict):
        for key in ("relationships", "links"):
            rels = data.get(key)
            if isinstance(rels, list):
                return rels
    return []


def _activity_label(act: dict[str, Any]) -> str:
    """Best-effort human label for an activity in a message."""
    for key in ("activity_code", "wbs_code", "name", "id"):
        val = act.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if val is not None and not isinstance(val, str):
            return str(val)
    return "?"


def _is_zero_duration_type(act: dict[str, Any]) -> bool:
    """True when the activity type is one that legitimately has no duration."""
    act_type = str(act.get("activity_type") or "").strip().lower()
    return act_type in _ZERO_DURATION_ACTIVITY_TYPES


def _inline_dependency_count(act: dict[str, Any]) -> int:
    """Count inline dependencies stored on the activity row itself.

    The schedule ``Activity.dependencies`` JSON column can hold links inline
    (separate from the ``ScheduleRelationship`` table). Count them so an
    activity that only uses inline links is not falsely flagged as an open
    end.
    """
    deps = act.get("dependencies")
    if isinstance(deps, list):
        return len(deps)
    return 0


class ScheduleOpenEnds(ValidationRule):
    """Flags activities with no predecessor and/or no successor logic.

    DCMA "logic" check: every activity except the project start and finish
    should have at least one predecessor and one successor so the network
    is fully tied together. Dangling activities (open ends) make the
    critical-path and float numbers unreliable. Milestone / summary rows are
    exempt because a start milestone legitimately has no predecessor and a
    finish milestone legitimately has no successor.
    """

    rule_id = "schedule_quality.open_ends"
    name = "Schedule Open Ends"
    standard = "schedule_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Flags activities missing predecessor and/or successor logic (open "
        "ends / dangling activities) so the critical path stays defensible."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        activities = _get_activities(context)
        if not activities:
            return []
        relationships = _get_relationships(context)
        has_pred: set[str] = set()
        has_succ: set[str] = set()
        for rel in relationships:
            pred = rel.get("predecessor_id")
            succ = rel.get("successor_id")
            if pred is not None and succ is not None:
                has_succ.add(str(pred))
                has_pred.add(str(succ))

        results: list[RuleResult] = []
        for act in activities:
            if _is_zero_duration_type(act):
                continue
            act_id = str(act.get("id") or "")
            inline = _inline_dependency_count(act)
            # An inline dependency means the activity has a predecessor link.
            missing_pred = act_id not in has_pred and inline == 0
            missing_succ = act_id not in has_succ
            passed = not (missing_pred or missing_succ)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                if missing_pred and missing_succ:
                    ends = translate("schedule_quality.open_ends.both", locale=locale)
                elif missing_pred:
                    ends = translate("schedule_quality.open_ends.predecessor", locale=locale)
                else:
                    ends = translate("schedule_quality.open_ends.successor", locale=locale)
                message = translate(
                    "schedule_quality.open_ends.fail",
                    locale=locale,
                    activity=_activity_label(act),
                    ends=ends,
                )
                suggestion = translate("schedule_quality.open_ends.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=act.get("id"),
                    details=(
                        {} if passed else {"missing_predecessor": missing_pred, "missing_successor": missing_succ}
                    ),
                    suggestion=suggestion,
                )
            )
        return results


class ScheduleNegativeLag(ValidationRule):
    """Flags relationships that use negative lag (a lead).

    DCMA "negative lag (leads)" check: a negative lag lets a successor start
    before its predecessor logically allows, which distorts the forward pass
    and hides true sequencing. Leads should be re-modelled as explicit
    activities or SS/FF relationships instead.
    """

    rule_id = "schedule_quality.negative_lag"
    name = "Schedule Negative Lag"
    standard = "schedule_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags relationships with negative lag (leads), which distort the critical path."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        relationships = _get_relationships(context)
        if not relationships:
            return []
        results: list[RuleResult] = []
        for rel in relationships:
            lag = _to_number(rel.get("lag_days", 0))
            if lag is None or lag is _NOT_A_NUMBER:
                continue  # Non-numeric lag is a data issue, not a lead - skip.
            lag_val: float = lag  # type: ignore[assignment]
            passed = lag_val >= 0
            pred = str(rel.get("predecessor_id") or "?")
            succ = str(rel.get("successor_id") or "?")
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "schedule_quality.negative_lag.fail",
                    locale=locale,
                    predecessor=pred,
                    successor=succ,
                    lag=_fmt_decimal(lag_val, places=0),
                )
                suggestion = translate("schedule_quality.negative_lag.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=rel.get("successor_id"),
                    details=({} if passed else {"lag_days": lag_val, "predecessor_id": pred, "successor_id": succ}),
                    suggestion=suggestion,
                )
            )
        return results


class ScheduleExcessiveLag(ValidationRule):
    """Flags relationships with lag above a sensible threshold.

    DCMA "high lag" check: a large positive lag often hides a missing
    activity (procurement, cure time, approval) that should be modelled
    explicitly so it can carry status and be levelled. The threshold can be
    overridden per project via ``metadata["schedule_quality"]["max_lag_days"]``.
    """

    rule_id = "schedule_quality.excessive_lag"
    name = "Schedule Excessive Lag"
    standard = "schedule_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags relationships whose lag exceeds the configured threshold (default 20 working days)."

    DEFAULT_MAX_LAG_DAYS = 20

    def _max_lag(self, context: ValidationContext) -> float:
        meta = getattr(context, "metadata", None) or {}
        cfg = meta.get("schedule_quality") if isinstance(meta, dict) else None
        if isinstance(cfg, dict):
            override = _to_number(cfg.get("max_lag_days"))
            if override is not None and override is not _NOT_A_NUMBER and override > 0:  # type: ignore[operator]
                return override  # type: ignore[return-value]
        return float(self.DEFAULT_MAX_LAG_DAYS)

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        relationships = _get_relationships(context)
        if not relationships:
            return []
        max_lag = self._max_lag(context)
        results: list[RuleResult] = []
        for rel in relationships:
            lag = _to_number(rel.get("lag_days", 0))
            if lag is None or lag is _NOT_A_NUMBER:
                continue
            lag_val: float = lag  # type: ignore[assignment]
            passed = lag_val <= max_lag
            pred = str(rel.get("predecessor_id") or "?")
            succ = str(rel.get("successor_id") or "?")
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "schedule_quality.excessive_lag.fail",
                    locale=locale,
                    predecessor=pred,
                    successor=succ,
                    lag=_fmt_decimal(lag_val, places=0),
                    threshold=_fmt_decimal(max_lag, places=0),
                )
                suggestion = translate("schedule_quality.excessive_lag.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=rel.get("successor_id"),
                    details=({} if passed else {"lag_days": lag_val, "threshold": max_lag}),
                    suggestion=suggestion,
                )
            )
        return results


class ScheduleHardConstraints(ValidationRule):
    """Flags activities pinned by a hard date constraint.

    DCMA "hard constraint" check: must-start-on / must-finish-on constraints
    override the network logic and prevent activities from moving when their
    predecessors slip, which masks delay. They should be used sparingly and
    documented. Soft window constraints (start-no-earlier, ASAP, ALAP) are
    not flagged.
    """

    rule_id = "schedule_quality.hard_constraints"
    name = "Schedule Hard Constraints"
    standard = "schedule_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags activities with a hard date constraint (must-start-on / must-finish-on) that overrides logic."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        activities = _get_activities(context)
        if not activities:
            return []
        results: list[RuleResult] = []
        for act in activities:
            constraint = str(act.get("constraint_type") or "").strip().lower()
            is_hard = constraint in _HARD_CONSTRAINT_TYPES
            passed = not is_hard
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "schedule_quality.hard_constraints.fail",
                    locale=locale,
                    activity=_activity_label(act),
                    constraint=constraint,
                )
                suggestion = translate("schedule_quality.hard_constraints.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=act.get("id"),
                    details=({} if passed else {"constraint_type": constraint}),
                    suggestion=suggestion,
                )
            )
        return results


class ScheduleNegativeFloat(ValidationRule):
    """Flags activities whose total float is negative.

    DCMA "negative float" check: negative total float means the activity is
    already behind the dates the network needs, usually because a hard
    constraint or an external deadline conflicts with the logic. It signals
    the plan is not achievable as drawn and needs re-sequencing or a
    documented recovery plan.
    """

    rule_id = "schedule_quality.negative_float"
    name = "Schedule Negative Float"
    standard = "schedule_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags activities with negative total float - the schedule is not achievable as currently logic-tied."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        activities = _get_activities(context)
        if not activities:
            return []
        results: list[RuleResult] = []
        for act in activities:
            raw_float = act.get("total_float")
            if raw_float is None:
                continue  # No CPM result yet - nothing to judge.
            tf = _to_number(raw_float)
            if tf is None or tf is _NOT_A_NUMBER:
                continue
            tf_val: float = tf  # type: ignore[assignment]
            passed = tf_val >= 0
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "schedule_quality.negative_float.fail",
                    locale=locale,
                    activity=_activity_label(act),
                    float=_fmt_decimal(tf_val, places=0),
                )
                suggestion = translate("schedule_quality.negative_float.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=act.get("id"),
                    details=({} if passed else {"total_float": tf_val}),
                    suggestion=suggestion,
                )
            )
        return results


class ScheduleHighFloat(ValidationRule):
    """Flags activities with an unusually large total float.

    DCMA "high float" check: a very large total float (default over 44
    working days, roughly two months) usually means the activity is missing
    a successor link or is only loosely tied to the network, so its dates are
    not really controlled by the plan. The threshold can be overridden via
    ``metadata["schedule_quality"]["max_total_float_days"]``.
    """

    rule_id = "schedule_quality.high_float"
    name = "Schedule High Float"
    standard = "schedule_quality"
    severity = Severity.INFO
    category = RuleCategory.CONSISTENCY
    description = "Flags activities whose total float exceeds the configured threshold (default 44 working days)."

    DEFAULT_MAX_TOTAL_FLOAT_DAYS = 44

    def _max_float(self, context: ValidationContext) -> float:
        meta = getattr(context, "metadata", None) or {}
        cfg = meta.get("schedule_quality") if isinstance(meta, dict) else None
        if isinstance(cfg, dict):
            override = _to_number(cfg.get("max_total_float_days"))
            if override is not None and override is not _NOT_A_NUMBER and override > 0:  # type: ignore[operator]
                return override  # type: ignore[return-value]
        return float(self.DEFAULT_MAX_TOTAL_FLOAT_DAYS)

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        activities = _get_activities(context)
        if not activities:
            return []
        threshold = self._max_float(context)
        results: list[RuleResult] = []
        for act in activities:
            raw_float = act.get("total_float")
            if raw_float is None:
                continue
            tf = _to_number(raw_float)
            if tf is None or tf is _NOT_A_NUMBER:
                continue
            tf_val: float = tf  # type: ignore[assignment]
            # Negative float is owned by ScheduleNegativeFloat - keep orthogonal.
            if tf_val < 0:
                continue
            passed = tf_val <= threshold
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "schedule_quality.high_float.fail",
                    locale=locale,
                    activity=_activity_label(act),
                    float=_fmt_decimal(tf_val, places=0),
                    threshold=_fmt_decimal(threshold, places=0),
                )
                suggestion = translate("schedule_quality.high_float.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=act.get("id"),
                    details=({} if passed else {"total_float": tf_val, "threshold": threshold}),
                    suggestion=suggestion,
                )
            )
        return results


class ScheduleMissingDuration(ValidationRule):
    """Flags non-milestone activities with a zero or missing duration.

    DCMA "invalid dates / missing duration" family: a task with no duration
    is either an unfinished plan entry or a milestone that has not been typed
    as one. Genuine milestone / summary rows are exempt. A negative duration
    is always invalid regardless of type.
    """

    rule_id = "schedule_quality.missing_duration"
    name = "Schedule Missing Duration"
    standard = "schedule_quality"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags non-milestone activities with a zero, missing, or negative duration."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        activities = _get_activities(context)
        if not activities:
            return []
        results: list[RuleResult] = []
        for act in activities:
            is_zero_type = _is_zero_duration_type(act)
            dur = _to_number(act.get("duration_days"))
            if dur is None or dur is _NOT_A_NUMBER:
                dur_val = 0.0
            else:
                dur_val = dur  # type: ignore[assignment]
            if is_zero_type:
                # Milestones may be 0 but must never be negative.
                passed = dur_val >= 0
            else:
                passed = dur_val > 0
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "schedule_quality.missing_duration.fail",
                    locale=locale,
                    activity=_activity_label(act),
                    duration=_fmt_decimal(dur_val, places=0),
                )
                suggestion = translate("schedule_quality.missing_duration.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=act.get("id"),
                    details=({} if passed else {"duration_days": dur_val}),
                    suggestion=suggestion,
                )
            )
        return results


# ── AI Takeoff (vision-LLM plan reading, issue #194) ────────────────────────
#
# Validation is first-class for the vision path: the model's structured output
# is checked before it can become a trusted suggestion. These three rules fire
# over a plan-read run's proposals (the engine is fed
# ``context.data = {"proposals": [...], "page_width_pt", "page_height_pt"}``).
# They are a review/quality gate, not a hard block - the API layer also blocks
# accept on a self-intersection ERROR verdict.

# The whole page must imply a real-world span inside this belt. Mirrors
# plan_read._MIN_PAGE_SPAN_M / _MAX_PAGE_SPAN_M so the rule and the service
# agree on what counts as an absurd ratio.
_AI_TAKEOFF_MIN_PAGE_SPAN_M = 0.5
_AI_TAKEOFF_MAX_PAGE_SPAN_M = 5000.0
# Proposals at or below this confidence are flagged for human review.
_AI_TAKEOFF_LOW_CONFIDENCE = 0.62


def _get_plan_read_proposals(context: ValidationContext) -> list[dict[str, Any]]:
    """Pull the plan-read proposal list from the validation context."""
    data = context.data
    if isinstance(data, dict):
        proposals = data.get("proposals")
        if isinstance(proposals, list):
            return proposals
    if isinstance(data, list):
        return data
    return []


def _polygon_self_intersects(points: list[tuple[float, float]]) -> bool:
    """Closed-polygon self-intersection test (parity with the TS source).

    Twin of the frontend ``isSelfIntersecting`` and the service-side
    ``plan_read.polygon_self_intersects`` so the dashboard finding matches the
    canvas verdict.
    """
    n = len(points)
    if n < 4:
        return False

    def _ccw(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    def _cross(
        a: tuple[float, float],
        b: tuple[float, float],
        c: tuple[float, float],
        d: tuple[float, float],
    ) -> bool:
        return _ccw(a, c, d) != _ccw(b, c, d) and _ccw(a, b, c) != _ccw(a, b, d)

    edges = [(points[i], points[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i or (i == 0 and j == n - 1) or j == i + 1:
                continue
            if _cross(*edges[i], *edges[j]):
                return True
    return False


def _proposal_points(proposal: dict[str, Any]) -> list[tuple[float, float]]:
    """Read ``[(x, y), ...]`` from a proposal's points, defensively."""
    out: list[tuple[float, float]] = []
    for pt in proposal.get("points") or []:
        try:
            if isinstance(pt, dict):
                out.append((float(pt["x"]), float(pt["y"])))
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                out.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError, KeyError):
            continue
    return out


class TakeoffScaleSanityRule(ValidationRule):
    rule_id = "ai_takeoff.scale_sanity"
    name = "AI Plan-Read Scale Sanity"
    standard = "ai_takeoff"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A detected scale must imply a plausible real-world page span"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        data = context.data if isinstance(context.data, dict) else {}
        ratio = _to_number(data.get("scale_ratio_px_per_unit"))
        page_w = _to_number(data.get("page_width_pt")) or 0.0
        page_h = _to_number(data.get("page_height_pt")) or 0.0
        # Nothing to check when there is no scale (honest "no evidence").
        if ratio is None or ratio is _NOT_A_NUMBER or ratio <= 0:
            return []
        long_edge = max(float(page_w), float(page_h))  # type: ignore[arg-type]
        if long_edge <= 0:
            return []
        span_m = long_edge / float(ratio)  # type: ignore[arg-type]
        passed = _AI_TAKEOFF_MIN_PAGE_SPAN_M <= span_m <= _AI_TAKEOFF_MAX_PAGE_SPAN_M
        message = (
            _ok(locale) if passed else translate("ai_takeoff.scale_sanity.fail", locale=locale, span=round(span_m, 2))
        )
        suggestion = None if passed else translate("ai_takeoff.scale_sanity.suggestion", locale=locale)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                suggestion=suggestion,
            )
        ]


class TakeoffPolygonSelfIntersectionRule(ValidationRule):
    rule_id = "ai_takeoff.polygon_self_intersection"
    name = "AI Plan-Read Polygon Self-Intersection"
    standard = "ai_takeoff"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A proposed room polygon must not self-intersect"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for prop in _get_plan_read_proposals(context):
            if (prop.get("type") or "").lower() != "area":
                continue
            points = _proposal_points(prop)
            bad = _polygon_self_intersects(points)
            message = (
                _ok(locale)
                if not bad
                else translate(
                    "ai_takeoff.polygon_self_intersection.fail",
                    locale=locale,
                    name=prop.get("annotation") or prop.get("id", "?"),
                )
            )
            suggestion = (
                None if not bad else translate("ai_takeoff.polygon_self_intersection.suggestion", locale=locale)
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=not bad,
                    message=message,
                    element_ref=prop.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


class TakeoffLowConfidenceReviewRule(ValidationRule):
    rule_id = "ai_takeoff.low_confidence_review"
    name = "AI Plan-Read Low Confidence Review"
    standard = "ai_takeoff"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Low-confidence AI proposals are flagged for human review before accept"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for prop in _get_plan_read_proposals(context):
            conf = _to_number(prop.get("confidence"))
            if conf is None or conf is _NOT_A_NUMBER:
                continue
            passed = float(conf) > _AI_TAKEOFF_LOW_CONFIDENCE  # type: ignore[arg-type]
            message = (
                _ok(locale)
                if passed
                else translate(
                    "ai_takeoff.low_confidence_review.fail",
                    locale=locale,
                    name=prop.get("annotation") or prop.get("id", "?"),
                    confidence=round(float(conf), 2),  # type: ignore[arg-type]
                )
            )
            suggestion = None if passed else translate("ai_takeoff.low_confidence_review.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=prop.get("id"),
                    suggestion=suggestion,
                )
            )
        return results


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
        (BOQUnitSystemConsistencyRule(), None),
        (ClassificationCountryMismatchRule(), None),
        (RevisionCostImpactReview(), None),
        # DIN 276 (DACH)
        (DIN276CostGroupRequired(), None),
        (DIN276ValidCostGroup(), None),
        (DIN276Hierarchy(), None),
        (DIN276Completeness(), None),
        # GAEB (DACH) - slice D expansion
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
        # NBR 12721 (Brazil - ABNT cost-group hierarchy)
        (NBR12721ClassificationRequired(), None),
        (NBR12721ValidSection(), None),
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
        # BC3 / FIEBDC-3 (Spain + LATAM)
        (BC3CodeRequired(), None),
        (BC3ValidCode(), None),
        # Pipeline Builder - structural graph-validity gate
        (PipelineSideEffectGated(), None),
        # Property Development (task #139)
        (PropDevEscrowAccountRequired(), None),
        (PropDevEscrowIBANValid(), None),
        (PropDevEscrowBalanceReconciled(), None),
        (PropDevSalesContractPartyOwnershipSumsTo100(), None),
        (PropDevPaymentScheduleInstalmentsSumToContractValue(), None),
        (PropDevReservationExpiryInFuture(), None),
        (PropDevBrokerCommissionRateWithinBounds(), None),
        (PropDevPriceMatrixNoNegativeModifier(), None),
        # Schedule Quality (C1 - DCMA-14-style health checks)
        (ScheduleOpenEnds(), None),
        (ScheduleNegativeLag(), None),
        (ScheduleExcessiveLag(), None),
        (ScheduleHardConstraints(), None),
        (ScheduleNegativeFloat(), None),
        (ScheduleHighFloat(), None),
        (ScheduleMissingDuration(), None),
        # AI Takeoff (vision-LLM plan reading, issue #194)
        (TakeoffScaleSanityRule(), None),
        (TakeoffPolygonSelfIntersectionRule(), None),
        (TakeoffLowConfidenceReviewRule(), None),
    ]

    for rule, sets in rules:
        rule_registry.register(rule, sets)

    logger.info(
        "Registered %d built-in validation rules across %d rule sets",
        len(rules),
        len(rule_registry.list_rule_sets()),
    )
