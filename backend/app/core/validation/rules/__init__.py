# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
from app.core.validation.messages import DEFAULT_LOCALE, is_key_present, translate

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


def _get_leaf_positions(context: ValidationContext) -> list[dict[str, Any]]:
    """Leaf-only positions - sections (parent / header rows) are skipped.

    Why: section rows aggregate children and intentionally lack `unit`,
    `quantity`, and `unit_rate`. Rules that enforce those fields would
    otherwise emit false-positive errors against every header in the
    tree, drowning real findings on a fresh user's first validation run.

    Detection: a row is a section if (a) its `type` field says so
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


def _position_currency(pos: dict[str, Any]) -> str:
    """Resolve one position's currency from whatever shape the loader supplied.

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


def _boq_document(context: ValidationContext) -> dict[str, Any]:
    """The bill's own fields, as the shared payload builder supplies them.

    A document-level rule asks a different question from a line-level one: not
    whether a line is measured correctly but whether the estimate says what it
    is. The base date, the standard it was measured to, the contract it is
    priced against - all of that lives on the bill and on none of its lines.
    """
    data = context.data
    block = data.get("boq") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else {}


def _boq_document_metadata(context: ValidationContext) -> dict[str, Any]:
    """What the bill records about itself, the bill first and the run second.

    The run metadata carries the request locale and nothing a person authored,
    so a rule reading only there is asking a question the product has no way
    to answer: it can never pass, and a warning nobody can clear teaches the
    reader to skip the whole rule set. It stays second in the lookup because a
    caller driving one rule directly still hands its fixture in that way.
    """
    meta = _boq_document(context).get("metadata")
    merged = dict(meta) if isinstance(meta, dict) else {}
    if isinstance(context.metadata, dict):
        for key, value in context.metadata.items():
            merged.setdefault(key, value)
    return merged


def _position_metadata(pos: dict[str, Any]) -> dict[str, Any]:
    """Return the position's metadata blob regardless of dict shape.

    API payloads carry ``metadata``; the ORM flattens to ``metadata_``.
    Returns an empty dict when neither is present so callers can chain
    ``.get`` without guarding.
    """
    for meta_key in ("metadata", "metadata_"):
        meta = pos.get(meta_key)
        if isinstance(meta, dict):
            return meta
    return {}


# GAEB Provis (Bedarfsposition / Eventualposition) markers. These are
# legitimately offered without a binding unit price - the bidder is not
# obliged to price optional scope. A zero (or absent) Einheitspreis on such
# a position is correct per GAEB Fachdok 4.5.3 and must never be flagged as
# a hard pricing error (FA-STD-044).
_GAEB_PROVISIONAL_FLAGS: frozenset[str] = frozenset(
    {
        "withtotal",
        "withouttotal",
        "bedarfsposition",
        "bedarfsposition mit gesamtbetrag",
        "bedarfsposition ohne gesamtbetrag",
        "eventualposition",
        "provisional",
    }
)

# Position-type values (top-level ``type`` or ``metadata.position_type``)
# that GAEB treats as optional / not-necessarily-priced scope.
_PROVISIONAL_TYPES: frozenset[str] = frozenset(
    {"provisional", "bedarf", "bedarfsposition", "eventual", "eventualposition", "optional"}
)


def _is_provisional_position(pos: dict[str, Any]) -> bool:
    """True when a position is a GAEB Bedarfs-/Eventualposition (optional scope).

    Detected from any of: the importer's ``metadata['gaeb_provis']`` flag, a
    ``metadata['position_type']``/top-level ``type`` naming an optional kind,
    or a boolean ``is_provisional`` marker. Such positions may carry a zero or
    missing Einheitspreis without it being an error.
    """
    meta = _position_metadata(pos)
    provis = str(meta.get("gaeb_provis") or "").strip().lower()
    if provis and provis in _GAEB_PROVISIONAL_FLAGS:
        return True
    if meta.get("is_provisional") is True or pos.get("is_provisional") is True:
        return True
    for type_key in (pos.get("type"), meta.get("position_type"), meta.get("gaeb_position_type")):
        if str(type_key or "").strip().lower() in _PROVISIONAL_TYPES:
            return True
    return False


# GAEB exchange phases that carry NO bidder prices. In these the unit rate is
# legitimately 0 / absent for every position, so a zero Einheitspreis must not
# be flagged (FA-STD-045). X81 (Leistungsverzeichnis), X82 (Kostenanschlag)
# and X83 (Angebotsaufforderung) are the unpriced request phases.
_UNPRICED_DA_KINDS: frozenset[str] = frozenset({"x80", "x81", "x82", "x83"})


def _is_unpriced_phase(context: ValidationContext, pos: dict[str, Any]) -> bool:
    """True when the BOQ came from an unpriced GAEB phase (X81/X83).

    Reads the DA kind the importer stamped on the result metadata or each
    position (``gaeb_da_kind``). Defaults to ``False`` (treat as priced) when
    no phase is recorded, so manually-built priced BOQs still get the zero
    review nudge.
    """
    kind = ""
    data = context.data
    if isinstance(data, dict):
        data_meta = data.get("metadata")
        if isinstance(data_meta, dict):
            kind = str(data_meta.get("da_kind") or data_meta.get("gaeb_da_kind") or "")
    if not kind:
        kind = str(_position_metadata(pos).get("gaeb_da_kind") or "")
    return kind.strip().lower() in _UNPRICED_DA_KINDS


def _gaeb_oz_mask(context: ValidationContext, pos: dict[str, Any]) -> list[int] | None:
    """Read the GAEB OZ-Maske (per-level digit widths) if the import recorded it.

    The mask comes from the file's ``BoQBkdn`` and is the only authoritative
    source for how many dotted levels an OZ has and how wide each is. It may
    be threaded on the context (``metadata['gaeb_oz_mask']`` or
    ``data['metadata']['gaeb_oz_mask']``) or carried per-position by the
    importer. Returns the ordered list of integer widths, or ``None`` when no
    mask is available (callers then fall back to a structural check).
    """
    candidates: list[Any] = []
    ctx_meta = getattr(context, "metadata", None)
    if isinstance(ctx_meta, dict):
        candidates.append(ctx_meta.get("gaeb_oz_mask"))
    data = context.data
    if isinstance(data, dict):
        data_meta = data.get("metadata")
        if isinstance(data_meta, dict):
            candidates.append(data_meta.get("gaeb_oz_mask"))
    candidates.append(_position_metadata(pos).get("gaeb_oz_mask"))
    for raw in candidates:
        if isinstance(raw, (list, tuple)) and raw:
            widths: list[int] = []
            for part in raw:
                try:
                    widths.append(int(part))
                except (TypeError, ValueError):
                    widths = []
                    break
            if widths:
                return widths
    return None


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
                    # Always point at the first position carrying this ordinal,
                    # including (especially) the failing duplicate case so the
                    # dashboard can drill into the offending position. Previously
                    # the failing result nulled element_ref, breaking drill-down
                    # on the one finding that needs it most.
                    element_ref=ids[0] if ids else None,
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

# DIN 276:2018-12 cost-group (Kostengruppe / KG) reference tree.
#
# The standard is a strict three-level decimal hierarchy:
#   * Level 1 - main group, one significant digit then two zeros (e.g. 300).
#   * Level 2 - group, two significant digits then one zero (e.g. 330).
#   * Level 3 - element, three significant digits (e.g. 331).
#
# Level 3 is not a free 0-9 range under every parent (DIN 276 enumerates a
# specific set of elements per group), but the codebase deliberately keeps a
# structural level-3 check rather than a closed enumeration: the deeper codes
# produced by the CAD classification mapper and the seed/golden fixtures
# (331, 334, 344, 375, 390, 590, ...) must all stay valid, and projects are
# free to use any element code under a recognised level-2 parent. So level 3
# is accepted whenever its level-2 parent (NN0) is a known group.
#
# Each main group maps to the set of level-2 groups DIN 276:2018-12 names
# explicitly. A "9x0" entry (190, 290, 390, ...) is "Sonstiges" / other and
# is part of the standard for every main group. This table is reference data
# (used for labels and completeness reporting): the validity check itself is
# structural, because the standard reserves the full ten-slot second level per
# main group and regional cost frameworks / offices populate the spare slots
# (e.g. KG 630) - enumerating only the named groups would false-negative those
# legitimate codes and regress the platform's own DIN 276 fixtures.
DIN276_LEVEL_2_GROUPS: dict[str, frozenset[str]] = {
    "100": frozenset({"110", "120", "130", "140", "150", "160", "170", "180", "190"}),
    "200": frozenset({"210", "220", "230", "240", "250", "260", "270", "280", "290"}),
    "300": frozenset({"310", "320", "330", "340", "350", "360", "370", "380", "390"}),
    "400": frozenset({"410", "420", "430", "440", "450", "460", "470", "480", "490"}),
    "500": frozenset({"510", "520", "530", "540", "550", "560", "570", "580", "590"}),
    "600": frozenset({"610", "620", "690"}),
    "700": frozenset({"710", "720", "730", "740", "750", "760", "770", "780", "790"}),
    "800": frozenset({"810", "820", "830", "840", "850", "860", "870", "880", "890"}),
}

# Valid level-1 main groups (the eight KG hundreds defined by the standard).
DIN276_LEVEL_1_GROUPS: frozenset[str] = frozenset(DIN276_LEVEL_2_GROUPS)


def _normalize_din276_code(raw: object) -> str:
    """Return the comparable KG digits for a DIN 276 code.

    Accepts the canonical 3-digit forms (``"300"``, ``"330"``, ``"331"``) and
    the deeper dotted forms emitted by the CAD classification mapper
    (``"330.10"`` -> level-2 group ``"330"``). Whitespace is stripped; the
    fractional tail after a dot is dropped because the hierarchy that DIN 276
    standardises stops at the third digit. Non-string input is coerced via
    ``str``. Returns ``""`` when nothing usable remains.
    """
    code = str(raw or "").strip()
    if not code:
        return ""
    # Deeper, project-specific element codes use a dotted suffix
    # (e.g. "330.10"); the standardised hierarchy is the integer head.
    return code.split(".", 1)[0].strip()


def din276_level(code: str) -> int | None:
    """Return the DIN 276 hierarchy level (1/2/3) of a normalized KG code.

    The check is structural over the three-digit decimal hierarchy and is
    anchored on a valid level-1 main group (the eight KG hundreds, 100-800):

    * Level 1 - ``N00`` (e.g. ``300``).
    * Level 2 - ``NN0`` with a non-zero tens digit (e.g. ``330``).
    * Level 3 - ``NNN`` with a non-zero units digit (e.g. ``331``).

    Level 2 and level 3 are accepted under any valid main group because the
    standard reserves the full second/third level per group and projects /
    regional frameworks populate them differently (see
    :data:`DIN276_LEVEL_2_GROUPS`). Returns ``None`` when the code is not a
    three-digit numeric KG code or when its main group is outside 1-8 - so
    KG 0xx, KG 9xx, wrong-length and non-numeric codes still fail.
    """
    if len(code) != 3 or not code.isdigit():
        return None
    main = code[0] + "00"
    if main not in DIN276_LEVEL_1_GROUPS:
        return None
    if code == main:
        return 1
    if code[2] == "0":
        # NN0 with a non-zero tens digit (guaranteed, else it would equal main).
        return 2
    # NNN element code (non-zero units digit).
    return 3


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
        for pos in _get_leaf_positions(context):
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
    description = (
        "DIN 276 cost group code must be a valid KG code at level 1 (N00), "
        "level 2 (NN0) or level 3 (NNN) of the DIN 276:2018-12 hierarchy"
    )

    # Valid top-level main groups (1st digit) - DIN 276:2018-12 defines
    # KG 100-800 (800 = Finanzierung). Kept for callers/tests that still
    # reference the coarse first-digit set; full hierarchy validation runs
    # through ``din276_level`` against ``DIN276_LEVEL_2_GROUPS``.
    VALID_TOP_GROUPS = {"1", "2", "3", "4", "5", "6", "7", "8"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            raw = str((pos.get("classification") or {}).get("din276", ""))
            if not raw:
                continue  # Handled by cost_group_required
            # Normalize the dotted element forms ("330.10") the CAD mapper
            # emits down to the standardised KG head before validating the
            # level-1 / level-2 / level-3 hierarchy.
            code = _normalize_din276_code(raw)
            level = din276_level(code)
            passed = level is not None
            message = (
                _ok(locale)
                if passed
                else translate(
                    "din276.valid_cost_group.fail",
                    locale=locale,
                    code=raw,
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
                    details={"given_code": raw, "kg_code": code, "kg_level": level},
                )
            )
        return results


# ── GAEB Rules (DACH) ─────────────────────────────────────────────────────


class GAEBOrdinalFormat(ValidationRule):
    """Checks that an OZ (Ordnungszahl) is a well-formed GAEB ordinal.

    There is no single hardcoded OZ shape in GAEB. The number of levels and
    the width of each are declared per file by the OZ-Maske (``BoQBkdn``):
    the BVBS Pruefdateien use ``3.3.4`` (``001.001.0010``) with an optional
    one-character index (``001.001.0010.A``), while other files use ``2.2.4``
    (``01.02.0030``). When the importer recorded the mask we validate each
    level against it exactly; otherwise we fall back to a structural check
    that accepts any dotted chain of numeric levels with an optional trailing
    index. The old rule hardcoded ``XX.XX.XXXX`` and so flagged every level-3
    Pruefdatei OZ as non-conform (FA-STD-046).
    """

    rule_id = "gaeb.ordinal_format"
    name = "GAEB Ordinal Number Format"
    standard = "gaeb"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Ordinal numbers should follow the file's GAEB OZ-Maske (e.g. 001.001.0010 or 01.02.0030)"

    # Structural fallback when no OZ-Maske is recorded: one or more numeric
    # levels joined by dots, with an optional trailing index that is either a
    # short run of digits or a single A-Z letter (GAEB RNoIndex).
    _STRUCTURAL = re.compile(r"^\d+(?:\.\d+)*(?:\.(?:\d{1,3}|[A-Za-z]))?$")

    @staticmethod
    def _matches_mask(ordinal: str, mask: list[int]) -> bool:
        """True when ``ordinal`` conforms to the recorded OZ-Maske widths.

        Section/group headers carry a partial OZ (a prefix of the mask - e.g.
        ``001`` at level 1, ``001.001`` at level 2), and leaf items carry the
        full mask plus an optional RNoIndex (``001.001.0010``,
        ``001.001.0010.A``). So the first ``len(parts)`` levels (capped at the
        mask depth) must each be all-digit and exactly the masked width; one
        extra trailing part beyond the mask may be the RNoIndex (digits or a
        single letter).
        """
        parts = ordinal.split(".")
        if not parts or len(parts) > len(mask) + 1:
            return False
        level_count = min(len(parts), len(mask))
        for part, width in zip(parts[:level_count], mask[:level_count], strict=True):
            if not part.isdigit() or len(part) != width:
                return False
        if len(parts) == len(mask) + 1:
            index = parts[-1]
            if not (index.isdigit() or (len(index) == 1 and index.isalpha())):
                return False
        return True

    def _is_valid(self, ordinal: str, mask: list[int] | None) -> bool:
        if mask:
            return self._matches_mask(ordinal, mask)
        return bool(self._STRUCTURAL.match(ordinal))

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            ordinal = pos.get("ordinal", "")
            if not ordinal:
                continue
            mask = _gaeb_oz_mask(context, pos)
            passed = self._is_valid(str(ordinal), mask)
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
            # A GAEB-imported leaf names its enclosing section via the section
            # OZ (classification/metadata ``gaeb_section``) before the persist
            # step assigns numeric parent_ids - that is a valid linkage too, so
            # the rule must not flag a well-formed import as orphaned.
            classification = pos.get("classification") or {}
            section_ref = str(
                classification.get("gaeb_section") or _position_metadata(pos).get("gaeb_section") or ""
            ).strip()
            passed = (parent_id is not None and str(parent_id) != "") or bool(section_ref)
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
    """Sanity-checks the Einheitspreis without rejecting legitimate prices.

    GAEB does not forbid a zero Einheitspreis. An offered 0.00 is a valid
    transferred price (Fachdok 4.6.4), and a Bedarfs-/Eventualposition may be
    left unpriced entirely (Fachdok 4.5.3). The old rule raised a blocking
    ERROR on every 0.00 line, which failed the official BVBS Pruefdatei (it
    contains a legitimate 0.00 line) and masked real money loss behind noise
    (FA-STD-045). The rule now only blocks on a genuinely impossible value - a
    negative Einheitspreis - and merely warns when a normal (non-optional,
    non-lump-sum) position carries 0.00 so a reviewer can confirm intent.
    Optional positions and lump sums are passed through.
    """

    rule_id = "gaeb.einheitspreis_sanity"
    name = "GAEB Einheitspreis Sanity"
    standard = "gaeb"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "Einheitspreis must not be negative. A zero rate is allowed (offered "
        "0.00, optional or lump-sum positions) but flagged for review on "
        "ordinary positions so a missing rate is caught without blocking."
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
            # Lump sums are allowed an arbitrary pricing shape, but the skip
            # is applied AFTER the negative check rather than before it. A
            # negative Einheitspreis is invalid under every unit and in every
            # phase, so it never needed the unit to decide. Skipping first
            # made the block unreachable on X84, the one phase that actually
            # carries bidder prices: its schema forbids QU on an item, so the
            # importer sees no unit, normalises to a lump sum, and this rule
            # stepped over every position in the file.
            is_lump_sum = unit in self.LUMP_SUM_UNITS
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

            if rate_val < 0:
                # The only genuinely invalid case: a negative Einheitspreis
                # cannot be transferred in any GAEB phase. Block it.
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=Severity.ERROR,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "gaeb.einheitspreis_sanity.negative",
                            locale=locale,
                            ordinal=pos.get("ordinal", "?"),
                            rate=_fmt_decimal(rate_val),
                            unit=unit or "-",
                        ),
                        element_ref=pos.get("id"),
                        details={"unit_rate": rate_val, "unit": unit},
                        suggestion=translate("gaeb.einheitspreis_sanity.suggestion", locale=locale),
                    )
                )
                continue

            if is_lump_sum:
                # Past the negative check, a lump sum is left alone exactly as
                # before: a zero or an unusual figure on one carries no meaning
                # this rule can read.
                continue

            if rate_val == 0 and not _is_provisional_position(pos) and not _is_unpriced_phase(context, pos):
                # A zero on an ordinary position is legal but worth a human
                # glance (likely a missing rate). WARNING, never ERROR. In an
                # unpriced phase (X81/X83) a zero is expected, so no finding.
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=Severity.WARNING,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "gaeb.einheitspreis_sanity.zero",
                            locale=locale,
                            ordinal=pos.get("ordinal", "?"),
                            unit=unit or "-",
                        ),
                        element_ref=pos.get("id"),
                        details={"unit_rate": rate_val, "unit": unit},
                        suggestion=translate("gaeb.einheitspreis_sanity.suggestion", locale=locale),
                    )
                )
                continue

            # Positive rate, or a legitimately-zero optional position.
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.WARNING,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                    element_ref=pos.get("id"),
                    details={"unit_rate": rate_val, "unit": unit},
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


class ResourceSplitMismatch(ValidationRule):
    """Per-unit resource subtotal should reconcile with the position unit rate.

    Positions carrying ``metadata.resources`` follow the per-unit norm
    convention: each resource's contribution per 1 unit of the position is
    its ``total`` when present, else ``quantity * unit_rate``, and the sum
    over all resources should equal the position's ``unit_rate``. When the
    two drift apart by more than 5 percent the Material/Labor/Equipment
    split shown in the BOQ grid no longer describes the money actually
    priced - flag it for review (WARNING, never blocks).
    """

    rule_id = "boq_quality.resource_split_mismatch"
    name = "Resource Split Matches Unit Rate"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Per-unit resource subtotal should match the position unit rate within 5%"

    REL_TOLERANCE = 0.05

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            meta = _position_metadata(pos)
            resources = meta.get("resources")
            if not isinstance(resources, list) or not resources:
                continue
            rate_p = _to_number(pos.get("unit_rate"))
            if rate_p is None or rate_p is _NOT_A_NUMBER:
                continue
            rate_val: float = rate_p  # type: ignore[assignment]
            # Zero/negative rates are covered by position_has_unit_rate /
            # negative_values - comparing a ratio against them is noise.
            if rate_val <= 0:
                continue
            subtotal = 0.0
            for res in resources:
                if not isinstance(res, dict):
                    continue
                ttl_p = _to_number(res.get("total")) if res.get("total") is not None else None
                if ttl_p is None or ttl_p is _NOT_A_NUMBER:
                    qty_p = _to_number(res.get("quantity"))
                    rrate_p = _to_number(res.get("unit_rate"))
                    qty_val = qty_p if isinstance(qty_p, float) else 0.0
                    rrate_val = rrate_p if isinstance(rrate_p, float) else 0.0
                    subtotal += qty_val * rrate_val
                else:
                    subtotal += ttl_p  # type: ignore[arg-type]
            diff_ratio = abs(subtotal - rate_val) / rate_val
            passed = diff_ratio <= self.REL_TOLERANCE
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "boq_quality.resource_split_mismatch.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    subtotal=_fmt_decimal(subtotal),
                    rate=_fmt_decimal(rate_val),
                    diff=_fmt_percent(diff_ratio),
                )
                suggestion = translate(
                    "boq_quality.resource_split_mismatch.suggestion",
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
                        "unit_rate": rate_val,
                        "resource_subtotal": subtotal,
                        "difference_ratio": diff_ratio,
                        "tolerance": self.REL_TOLERANCE,
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
        # Cyrillic spellings. russia_pack declares its default_units in this
        # script and units.py preserves non-Latin units verbatim rather than
        # folding them to Latin, so a bill written the way a Russian-market
        # estimator writes it reached this rule as an unrecognised token - and
        # an unrecognised unit is silently ignored, never flagged. That made
        # the metric half of the check blind on exactly the market whose pack
        # declares these. The digit forms sit beside the glyph forms because
        # both are typed in practice (units.py cites "м3" as a real input).
        "м",
        "м2",
        "м²",
        "м3",
        "м³",
        "кг",
        # Chinese spellings, for the same reason and by the same route: a
        # GB/T 50500 bill writes its metric units as words, and units.py keeps
        # them verbatim, so they arrived here unrecognised and were skipped.
        # Both readings of each unit are listed because both are written: the
        # colloquial 公斤 / 公里 sit beside the SI-derived 千克 / 千米, and a
        # bill mixes them freely. Count units are NOT here; see the note below
        # this set for where they live and why they are not a measurement
        # system. The CJK compatibility glyphs "㎡" and "㎥" are also absent on
        # purpose: units.py rejects them before storage (their leading
        # character is category So, which ``_is_safe_unit_shape`` refuses), so
        # a token in this set would be one the write path can never produce.
        # The full-width Latin forms below do store verbatim and do reach
        # here, which is why those are listed and the compatibility glyphs are
        # not.
        "米",
        "平方米",
        "立方米",
        "吨",
        "千克",
        "公斤",
        "毫米",
        "厘米",
        "千米",
        "公里",
        "升",
        "公顷",
        "克",
        "公吨",
        # Linear metre. 线性米 is the platform's own Chinese for it - the zh
        # locale renders the canonical "lm" that way - and 延长米 / 延米 are what
        # a bill writes for a run of skirting, kerb or handrail. The Latin "lm"
        # a few lines up was already here; its Chinese spellings were not, so a
        # linear-metre row written in Chinese was unrecognised.
        "线性米",
        "延长米",
        "延米",
        # Everyday contractions of 平方米 / 立方米. Both are written in bills and
        # in the quota tables rates are quoted from, and both already appear in
        # the cost matcher's own locale table.
        "平米",
        "立米",
        "平方",
        "立方",
        # Traditional / zh-TW and zh-HK spellings of the same four units. The
        # cost matcher already folds these; the rule did not know them, so the
        # two disagreed about the same bill.
        "公尺",
        "平方公尺",
        "立方公尺",
        "公噸",
        # Full-width Latin, produced by a Chinese IME left in full-width mode.
        # ``str.lower()`` folds full-width capitals to full-width lowercase but
        # never to ASCII, and nothing on the write path applies NFKC, so these
        # reach the rule exactly as typed.
        "ｍ",
        "ｍ２",
        "ｍ３",
    },
)
# Count units - "项", "台", "pcs", "Stk" - are deliberately in NEITHER this set
# nor the imperial one. Both sets are only ever read as the *wrong* set (see
# ``BOQUnitSystemConsistencyRule``), and a count of discrete items cannot be
# the wrong measurement system: it has no dimension to be metric or imperial
# about. Putting one here would make every count row on an imperial project
# report as a metric mismatch. The set that does know about counts is
# ``_COUNT_UNITS`` in ``app.modules.bim_hub.service``, which is where the
# Chinese count units were added.
# Units that are definitively imperial (US/UK) - ft, lb, etc.
_IMPERIAL_BOQ_UNITS: frozenset[str] = frozenset(
    {
        "ft",
        "ft2",
        "ft3",
        "sqft",
        "cuft",
        # The everyday US abbreviations, and the area and volume defaults
        # us_pack itself declares. Without them a US bill written in the very
        # units its own pack prescribes read as unrecognised here, so the pack
        # failed its own rule. units.py folds both to ft2 / ft3 on write, which
        # is why only rows that bypass that path (imports, legacy data) carried
        # them - and those are precisely the rows this rule exists to judge.
        "sf",
        "cf",
        "in",
        "inch",
        "yd",
        "sqyd",
        "cy",  # cubic yards
        "lb",
        "lbs",
        "oz",
        "ton",  # short ton
        "ton_us",  # short ton, the canonical boq/units.py emits for "ton"
        "gal",
        "gallon",
        # Imperial units written in Chinese, and the half of the Chinese
        # vocabulary that a Chinese project actually depends on.
        #
        # The rule reads the set for the system the project is NOT in. China is
        # metric, so on a Chinese bill it is this set that gets read and the
        # Chinese metric words above are never consulted - they earn their keep
        # on an imperial project carrying a Chinese row. Adding the metric
        # words alone therefore left the Chinese market exactly as unprotected
        # as before: an imperial row in a Chinese bill is written 英尺, not
        # "ft", and an unrecognised unit is skipped rather than flagged.
        #
        # 英尺, 平方英尺, 立方码 and 线性英尺 are the platform's own spellings -
        # the zh locale renders ft, sqft, cy and lf that way. The rest are the
        # standard Chinese names for the same family, listed because a document
        # that reaches for one reaches for its siblings.
        "英尺",
        "平方英尺",
        "立方英尺",
        "线性英尺",
        "英寸",
        "平方英寸",
        "码",
        "平方码",
        "立方码",
        "英里",
        "磅",
        "盎司",
        "短吨",
        "加仑",
    },
)


class BOQUnitSystemConsistencyRule(ValidationRule):
    """Warn when BOQ position units don't match project_unit_system.

    The rule is a single-result rule (returns one RuleResult, not one
    per position) so the UI can present the BOQ-wide mismatch summary
    in the validation dashboard. ``details["mismatch_count"]`` captures
    how many positions disagree and ``details["mismatches"]`` lists up
    to the first 10 by ordinal+unit for drill-down.

    Three silences, told apart. A bill with no rows is silent outright:
    there is nothing to be inconsistent with, and a passing result would
    hand an empty BOQ the compliance signal E-VAL-008 exists to deny it.
    A ``project_unit_system`` that is
    present and null means the question was asked and no regional pack
    answered, and the rule skips - the behaviour every project in an
    unclaimed country has always had. A key that is absent entirely means
    the payload was not built by
    :func:`app.core.validation.project_context.with_project_context`, and
    the rule says so as an engine error rather than passing for a check it
    never made. An unrecognised value still passes rather than
    false-positives.
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
        positions = _get_positions(context)
        if not positions:
            # No rows, so no unit to be inconsistent with, and nothing to
            # complain about not having been told either. Returning a passing
            # result here would give an empty BOQ a compliance signal and make
            # it read PASSED at score 1.0, which is exactly what E-VAL-008
            # forbids; the check below only speaks when it had work to do.
            return []
        if "project_unit_system" not in data:
            # Nobody asked. The payload did not come from
            # ``app.core.validation.project_context.with_project_context``, so
            # this rule was never handed the one input it reads - and a rule
            # that shrugs in that case is indistinguishable from one that
            # looked and found nothing, which is how it stayed dormant while
            # registered and enabled. Reported as an engine error: surfaced
            # separately, never flips the report to ERRORS and never drags the
            # score (E-VAL-018), so an otherwise-clean bill still reads clean
            # while the gap has a name.
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(
                        "The measurement system was never resolved for this validation run, so unit consistency "
                        "was not checked. The payload is missing 'project_unit_system'; build it with "
                        "app.core.validation.project_context.with_project_context."
                    ),
                    is_engine_error=True,
                    details={"missing_key": "project_unit_system"},
                )
            ]
        project_system_raw = data.get("project_unit_system")
        if project_system_raw is None:
            # Asked, and no regional pack answered: the project's country is
            # claimed by none, or by packs that disagree. Nothing to check, and
            # guessing a system is worse than declining to judge. Return [] so
            # an otherwise-empty BOQ stays SKIPPED (E-VAL-008).
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
# The preferred standard per country and the region-to-country reduction
# both come from :mod:`app.core.classification_registry` now. This file
# used to keep its own five-country copy of the first and its own
# three-region copy of the second, which meant a project in Poland or
# Australia got no nudge at all while the match pipeline happily ranked
# it against a standard.
#
# The nudge itself stays scoped to the standards it can actually
# crosswalk. Suggesting a DIN 276 group for a MasterFormat division is
# something the tables below can do; suggesting a UNTEC or GESN code is
# not, so a country whose standard is outside this set skips silently
# rather than nudging with an empty suggestion.
_CROSSWALKABLE_STANDARDS: frozenset[str] = frozenset({"din276", "nrm", "masterformat"})

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
    """Resolve the active country code from metadata or fall back to region.

    The region branch goes through the classification registry, so a
    city-suffixed region reduces to the same country as the bare code and
    a macro region reduces to the country it stands for.

    Args:
        metadata: Validation context metadata, may carry ``country_code``.
        region: ``project.region``, possibly empty.

    Returns:
        Alpha-2 country code, or ``None`` when neither source names one.
    """
    from app.core.classification_registry import normalise_region

    cc = metadata.get("country_code") if isinstance(metadata, dict) else None
    if cc:
        return str(cc).strip().upper()
    return normalise_region(region)


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
        "Nudge when a project's classifications don't include the standard its "
        "country reads, for the standards this rule can crosswalk (DIN 276, NRM, MasterFormat)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        metadata = getattr(context, "metadata", {}) or {}
        region = getattr(context, "region", None)
        country = _normalize_country_code(metadata, region)
        # No country context → cannot judge → nothing to emit.
        # Return [] so an otherwise-empty / unregioned BOQ stays SKIPPED (E-VAL-008).
        from app.core.classification_registry import standard_for_country

        preferred = standard_for_country(country)
        if not country or preferred not in _CROSSWALKABLE_STANDARDS:
            return []
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
            # Fold dotted CAD codes ("330.10") to their 3-digit head before
            # comparing, so a dotted parent does not produce a wrong prefix
            # (e.g. "330.10".rstrip("0") -> "330.1") and a false hierarchy warning.
            kg_norm = _normalize_din276_code(kg)
            parent_norm = _normalize_din276_code(parent_kg)
            parent_prefix = parent_norm.rstrip("0") or parent_norm[:1]
            passed = kg_norm.startswith(parent_prefix)
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
            # Fold dotted CAD codes ("330.10") to their 3-digit head first so
            # they are still counted toward their top-level group instead of
            # being dropped by the .isdigit() check.
            kg = _normalize_din276_code((pos.get("classification") or {}).get("din276", ""))
            # Require the whole folded head to be numeric, not just its first
            # three chars: "330.10" folds to "330" and counts, but a malformed
            # non-dotted code like "330x" must still be rejected the way the
            # pre-fold full-string isdigit() check rejected it.
            if len(kg) >= 3 and kg.isdigit():
                # Normalize to top-level group: e.g., 331 -> 300, 421 -> 400
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
        for pos in _get_leaf_positions(context):
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


# ── NRM cost-plan rules (UK) ─────────────────────────────────────────────
#
# The three rules above ask whether each line is classified. These ask
# whether the cost plan is a cost plan: whether it says what date its rates
# are current at, which stage it was produced for, and whether the money that
# is never measured - preliminaries, overheads and profit, risk - is in it at
# all. Those are three of the things a UK cost plan is sent back for, and
# none of them is visible line by line.


def _nrm_groups(context: ValidationContext) -> set[str]:
    """The NRM group elements the bill's lines actually carry."""
    groups: set[str] = set()
    for pos in _get_positions(context):
        code = str((pos.get("classification") or {}).get("nrm", "")).strip()
        if code:
            groups.add(code.split(".")[0])
    return groups


def _is_nrm_bill(context: ValidationContext) -> bool:
    """Whether this dataset is measured to NRM at all.

    A document-level rule has nothing to attach itself to on a bill that was
    never classified to NRM, and a finding about a missing base date on a
    German bill reads as the rule set malfunctioning rather than as advice.
    """
    return bool(_nrm_groups(context))


def _markup_categories(context: ValidationContext) -> set[str]:
    """The categories of the bill's active markup lines.

    A UK cost plan carries preliminaries, overheads and profit either as NRM
    group elements or as markup lines on top of the measured work, and both
    are correct. A rule reading only the group elements convicts every
    estimate built the second way, which is most of them.
    """
    data = context.data
    raw = data.get("markups") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return set()
    return {
        str(markup.get("category") or "").strip().lower()
        for markup in raw
        if isinstance(markup, dict) and markup.get("is_active", True)
    }


class NRMBaseDateDeclared(ValidationRule):
    rule_id = "nrm.base_date_declared"
    name = "NRM Cost Plan Base Date Declared"
    standard = "nrm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A cost plan must state the date its rates are current at"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_nrm_bill(context):
            return []
        locale = _get_locale(context)
        document = _boq_document(context)
        meta = _boq_document_metadata(context)
        declared = document.get("base_date") or meta.get("base_date") or meta.get("price_level")
        passed = bool(str(declared or "").strip())
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=(_ok(locale) if passed else translate("nrm.base_date_declared.fail", locale=locale)),
                element_ref=None,
                details={"base_date": str(declared) if declared else None},
                suggestion=(None if passed else translate("nrm.base_date_declared.suggestion", locale=locale)),
            )
        ]


class NRMCostPlanStageDeclared(ValidationRule):
    rule_id = "nrm.cost_plan_stage_declared"
    name = "NRM Cost Plan Stage Declared"
    standard = "nrm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A cost plan must say which design stage it was produced for"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_nrm_bill(context):
            return []
        locale = _get_locale(context)
        meta = _boq_document_metadata(context)
        declared = (
            meta.get("phase")
            or meta.get("riba_stage")
            or meta.get("stage")
            or _boq_document(context).get("estimate_type")
        )
        passed = bool(str(declared or "").strip())
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=(_ok(locale) if passed else translate("nrm.cost_plan_stage_declared.fail", locale=locale)),
                element_ref=None,
                details={"stage": str(declared) if declared else None},
                suggestion=(None if passed else translate("nrm.cost_plan_stage_declared.suggestion", locale=locale)),
            )
        ]


class NRMContractorCostsPresent(ValidationRule):
    rule_id = "nrm.contractor_costs_present"
    name = "NRM Main Contractor's Preliminaries and Overheads and Profit Present"
    standard = "nrm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A cost plan must carry the main contractor's preliminaries and its overheads and profit"

    #: The NRM 1 group element, and the markup category that carries the same
    #: money when the estimate prices it on top of the measured work rather
    #: than as an element of it.
    CARRIERS = (
        ("preliminaries", "9", "overhead"),
        ("overheads_and_profit", "10", "profit"),
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_nrm_bill(context):
            return []
        locale = _get_locale(context)
        groups = _nrm_groups(context)
        categories = _markup_categories(context)
        results: list[RuleResult] = []
        for what, group, markup_category in self.CARRIERS:
            as_element = group in groups
            as_markup = markup_category in categories
            passed = as_element or as_markup
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=(
                        _ok(locale)
                        if passed
                        else translate(f"nrm.contractor_costs_present.{what}", locale=locale, group=group)
                    ),
                    element_ref=None,
                    details={"carried_as_element": as_element, "carried_as_markup": as_markup, "group": group},
                    suggestion=(
                        None if passed else translate("nrm.contractor_costs_present.suggestion", locale=locale)
                    ),
                )
            )
        return results


class NRMRiskAllowancePresent(ValidationRule):
    rule_id = "nrm.risk_allowance_present"
    name = "NRM Risk Allowance Present"
    standard = "nrm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A cost plan must carry a risk allowance"

    RISK_GROUP = "13"
    RISK_CATEGORY = "contingency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_nrm_bill(context):
            return []
        locale = _get_locale(context)
        as_element = self.RISK_GROUP in _nrm_groups(context)
        as_markup = self.RISK_CATEGORY in _markup_categories(context)
        passed = as_element or as_markup
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=(_ok(locale) if passed else translate("nrm.risk_allowance_present.fail", locale=locale)),
                element_ref=None,
                details={"carried_as_element": as_element, "carried_as_markup": as_markup},
                suggestion=(None if passed else translate("nrm.risk_allowance_present.suggestion", locale=locale)),
            )
        ]


# ── UK statutory rules (Construction Act, CDM 2015, Building Safety Act) ──
#
# These read what the estimate records about itself rather than its lines.
# They sit in a rule set of their own because they are the law of one country
# rather than a method of measurement, and a project elsewhere that happens
# to measure to NRM must not be asked about a CDM appointment.
#
# Every one of them checks that a thing is stated, not what it says. The
# percentages, the notice periods and the retention rate are commercial terms
# this platform has no basis to assert. The single exception is the
# higher-risk building test, where the threshold is statute and an estimate
# can be wrong about it in a way that costs a gateway application.


def _uk_answered(meta: dict[str, Any], *keys: str) -> Any:
    """The first of ``keys`` the bill actually answers, or ``None``.

    A blank string, an empty mapping and a mapping whose every value is blank
    all read as unanswered. Accepting one would turn these rules into a check
    that somebody had opened the dialogue, which is the failure where a
    placeholder that passes is worse than one that does not.
    """
    for key in keys:
        value = meta.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and any(entry not in (None, "", {}, []) for entry in value.values()):
            return value
        if isinstance(value, (int, float)):
            return value
    return None


def _uk_finding(
    rule: ValidationRule,
    context: ValidationContext,
    *,
    passed: bool,
    key: str,
    details: dict[str, Any],
    **params: Any,
) -> list[RuleResult]:
    """One document-level finding, in the shape every rule below returns."""
    locale = _get_locale(context)
    return [
        RuleResult(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            passed=passed,
            message=(_ok(locale) if passed else translate(f"{key}.fail", locale=locale, **params)),
            element_ref=None,
            details=details,
            suggestion=(None if passed else translate(f"{key}.suggestion", locale=locale)),
        )
    ]


class UKContractFormDeclared(ValidationRule):
    rule_id = "uk.contract_form_declared"
    name = "UK Contract Form Declared"
    standard = "uk_statutory"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "An estimate must name the contract form it is priced against"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        declared = _uk_answered(_boq_document_metadata(context), "contract_form", "contract", "contract_suite")
        return _uk_finding(
            self,
            context,
            passed=declared is not None,
            key="uk.contract_form_declared",
            details={"contract_form": declared if isinstance(declared, str) else None},
        )


class UKPaymentRegimeDeclared(ValidationRule):
    rule_id = "uk.payment_regime_declared"
    name = "UK Payment Regime Declared"
    standard = "uk_statutory"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "The payment mechanism must fix when a payment becomes due and its final date for payment"

    #: The two dates the Housing Grants, Construction and Regeneration Act
    #: 1996, as amended, requires a construction contract to fix. A contract
    #: that fixes neither is not thereby free of them: the Scheme for
    #: Construction Contracts supplies both, and the parties then find their
    #: payment terms in a statutory instrument rather than in what they signed.
    DUE = ("due_date", "due_date_days", "payment_due")
    FINAL = ("final_date_for_payment", "final_date_for_payment_days", "final_date")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        meta = _boq_document_metadata(context)
        block = _uk_answered(meta, "payment_regime", "payment_terms")
        source = block if isinstance(block, dict) else meta
        due = _uk_answered(source, *self.DUE)
        final = _uk_answered(source, *self.FINAL)
        missing = [name for name, value in (("due date", due), ("final date for payment", final)) if value is None]
        return _uk_finding(
            self,
            context,
            passed=not missing,
            key="uk.payment_regime_declared",
            details={"due_date": due, "final_date_for_payment": final},
            missing=", ".join(missing) or "-",
        )


class UKRetentionDeclared(ValidationRule):
    rule_id = "uk.retention_declared"
    name = "UK Retention Declared"
    standard = "uk_statutory"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "An estimate must say what retention applies, including that none does"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        declared = _uk_answered(_boq_document_metadata(context), "retention", "retention_terms")
        return _uk_finding(
            self,
            context,
            passed=declared is not None,
            key="uk.retention_declared",
            details={"retention": declared if isinstance(declared, (str, dict)) else None},
        )


class UKCDMDutyHoldersDeclared(ValidationRule):
    rule_id = "uk.cdm_duty_holders_declared"
    name = "CDM 2015 Duty Holders Declared"
    standard = "uk_statutory"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A project with more than one contractor must record its principal designer and principal contractor"

    ROLES = ("principal_designer", "principal_contractor")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        meta = _boq_document_metadata(context)
        block = _uk_answered(meta, "cdm_2015", "cdm")
        appointments = block if isinstance(block, dict) else {}
        missing = [role for role in self.ROLES if _uk_answered(appointments, role) is None]
        return _uk_finding(
            self,
            context,
            passed=not missing,
            key="uk.cdm_duty_holders_declared",
            details={role: appointments.get(role) for role in self.ROLES},
            missing=", ".join(role.replace("_", " ") for role in missing) or "-",
        )


class UKHigherRiskBuildingRegime(ValidationRule):
    rule_id = "uk.hrb_regime_declared"
    name = "Building Safety Act Higher-Risk Building Regime"
    standard = "uk_statutory"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "An estimate must say whether the building is higher-risk, and agree with its own dimensions"

    #: The statutory test: height OR storeys, AND an occupancy the regime is
    #: about. The occupancy half is the one that gets dropped, and dropping it
    #: puts a ten-storey speculative office into a gateway regime that has
    #: nothing to do with it. Wrong in either direction costs real money - a
    #: programme nobody needed, or a missed gateway that stops the building
    #: being occupied.
    #:
    #: Two dwellings is the occupancy that carries through both phases. A care
    #: home and a hospital meet it for design and construction and not for
    #: occupation, which is why they are read as flags the estimate sets
    #: rather than folded into the dwelling count: the count is a number the
    #: building has, and these are a question about what the building is for.
    HEIGHT_M = 18.0
    STOREYS = 7
    RESIDENTIAL_UNITS = 2
    OCCUPANCY_FLAGS = ("care_home", "hospital")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        meta = _boq_document_metadata(context)
        block = _uk_answered(meta, "building_safety_act", "bsa_2022")
        declaration = block if isinstance(block, dict) else {}
        declared = declaration.get("higher_risk_building")
        if not isinstance(declared, bool):
            return _uk_finding(
                self,
                context,
                passed=False,
                key="uk.hrb_regime_declared",
                details={"higher_risk_building": None, "derived": None},
                reason=translate("uk.hrb_regime_declared.unanswered", locale=locale),
            )

        height = _to_number(declaration.get("height_m"))
        storeys = _to_number(declaration.get("storeys"))
        units = _to_number(declaration.get("residential_units"))
        flagged = any(bool(declaration.get(flag)) for flag in self.OCCUPANCY_FLAGS)
        if (units is None and not flagged) or (height is None and storeys is None):
            # Declared but not checkable. Reported as passing rather than as
            # a second finding: the estimate answered the question it was
            # asked, and inventing a dimension to disagree with it would be
            # the rule making something up.
            return _uk_finding(
                self,
                context,
                passed=True,
                key="uk.hrb_regime_declared",
                details={"higher_risk_building": declared, "derived": None},
            )

        tall_enough = (height is not None and height >= self.HEIGHT_M) or (
            storeys is not None and storeys >= self.STOREYS
        )
        derived = tall_enough and (flagged or (units is not None and units >= self.RESIDENTIAL_UNITS))
        return _uk_finding(
            self,
            context,
            passed=declared == derived,
            key="uk.hrb_regime_declared",
            details={
                "higher_risk_building": declared,
                "derived": derived,
                "height_m": height,
                "storeys": storeys,
                "residential_units": units,
                "occupancy_flags": [flag for flag in self.OCCUPANCY_FLAGS if declaration.get(flag)],
            },
            reason=translate(
                "uk.hrb_regime_declared.disagrees",
                locale=locale,
                declared=str(declared).lower(),
                derived=str(derived).lower(),
            ),
        )


class UKVATTreatmentDeclared(ValidationRule):
    rule_id = "uk.vat_treatment_declared"
    name = "UK VAT Treatment Declared"
    standard = "uk_statutory"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "An estimate must say how VAT is treated, whether by a rate, a relief or the reverse charge"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        declared = _uk_answered(_boq_document_metadata(context), "vat_treatment", "vat")
        as_markup = "tax" in _markup_categories(context)
        return _uk_finding(
            self,
            context,
            passed=declared is not None or as_markup,
            key="uk.vat_treatment_declared",
            details={"vat_treatment": declared if isinstance(declared, str) else None, "carried_as_markup": as_markup},
        )


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
        for pos in _get_leaf_positions(context):
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
    description = "Core divisions (03, 05, 26) should be present"

    REQUIRED_DIVISIONS = {"03", "05", "26"}
    # Our own scope wording, not the proprietary division titles
    # (licensing denylist) - these feed user-facing rule messages.
    DIV_NAMES = {
        "03": "concrete work",
        "05": "metal work",
        "26": "electrical systems",
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
        for pos in _get_leaf_positions(context):
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
        for pos in _get_leaf_positions(context):
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


# Units a labour resource is measured in. The Russian one is a man-hour and
# is written three ways in the wild (with the dot, without it, and
# transliterated), so the comparison folds all of them rather than picking a
# spelling and calling the other two absent.
_GESN_LABOUR_UNITS = frozenset(
    {
        "чел.-ч",
        "чел-ч",
        "чел.ч",
        "человеко-час",
        "man-hour",
        "man-hours",
        "chel.-ch",
        "chel-ch",
    }
)


def _gesn_code(pos: dict[str, Any]) -> str:
    """The GESN/FER norm code on a position, whitespace stripped."""
    code = (pos.get("classification") or {}).get("gesn", "")
    return re.sub(r"\s+", "", str(code))


def _gesn_resources(pos: dict[str, Any]) -> list[dict[str, Any]]:
    """The resource decomposition an import left on a position.

    Read from ``metadata["gesn"]["resources"]`` first and from a bare
    ``metadata["resources"]`` second, because an import that knows it is
    reading a Russian base namespaces the block and a generic import does not.
    Anything that is not a list of mappings is treated as absent rather than
    as malformed: a rule that distinguishes the two would be reporting on the
    importer, and the reader cannot act on that.
    """
    meta = _position_metadata(pos)
    block = meta.get("gesn")
    raw = block.get("resources") if isinstance(block, dict) else meta.get("resources")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def _gesn_is_russian_estimate(context: ValidationContext) -> bool:
    """Whether this dataset is a Russian estimate at all.

    The document-level rule below has nothing to attach itself to on a bill
    that never came from the Russian base, and firing there would put a
    finding about a price level on an estimate that has no norm codes in it.
    """
    return any(_gesn_code(pos) for pos in _get_positions(context))


class GESNResourceBreakdown(ValidationRule):
    rule_id = "gesn.resource_breakdown"
    name = "GESN Resource Breakdown Present"
    standard = "gesn"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A line citing a norm should carry the labour, plant and material the norm consumes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            code = _gesn_code(pos)
            if not code:
                # Not a line that cites the norm base. A Russian company still
                # imports plenty of bills that do not, and flagging every one
                # of them would train the reader to ignore the rule set.
                continue
            resources = _gesn_resources(pos)
            passed = bool(resources)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gesn.resource_breakdown.fail",
                    locale=locale,
                    code=code,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate("gesn.resource_breakdown.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"code": code, "resource_count": len(resources)},
                    suggestion=suggestion,
                )
            )
        return results


class GESNLabourHoursPresent(ValidationRule):
    rule_id = "gesn.labour_hours_present"
    name = "GESN Labour Hours Present"
    standard = "gesn"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A resource decomposition must include labour hours, the base overhead and profit are normed on"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            resources = _gesn_resources(pos)
            if not resources:
                # Absent decomposition is the rule above. Reporting it twice
                # would double the finding count without adding a finding.
                continue
            passed = any(str(entry.get("unit", "")).strip().lower() in _GESN_LABOUR_UNITS for entry in resources)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "gesn.labour_hours_present.fail",
                    locale=locale,
                    code=_gesn_code(pos) or "?",
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate("gesn.labour_hours_present.suggestion", locale=locale)
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


class GESNPriceLevelDeclared(ValidationRule):
    rule_id = "gesn.price_level_declared"
    name = "GESN Price Level Declared"
    standard = "gesn"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "An estimate against the norm base must say which price level its roubles are in"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _gesn_is_russian_estimate(context):
            return []
        locale = _get_locale(context)
        meta = _boq_document_metadata(context)
        block = meta.get("gesn")
        declared = (
            (block.get("price_level") if isinstance(block, dict) else None)
            or meta.get("price_level")
            # The bill carries a base date in a column of its own, and an
            # estimate that states one has said which roubles it is in. Reading
            # only the metadata blob would have called that estimate silent.
            or _boq_document(context).get("base_date")
        )
        # An empty string is not a declaration. The published base carries the
        # level as a date, and a blank field reads as a level of nothing.
        passed = bool(str(declared or "").strip())
        if passed:
            message = _ok(locale)
            suggestion = None
        else:
            message = translate("gesn.price_level_declared.fail", locale=locale)
            suggestion = translate("gesn.price_level_declared.suggestion", locale=locale)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                element_ref=None,
                details={"price_level": str(declared) if declared else None},
                suggestion=suggestion,
            )
        ]


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
        for pos in _get_leaf_positions(context):
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
#
# One standard, two spellings, and until 2026-08 the two readers of a Chinese
# cost item disagreed about which one to use. The classification registry names
# the standard ``gb50500`` and ``classification_order`` hands that name to the
# section path builder in ``match_elements``; these rules looked the code up
# under ``gbt50500``, which is what the shipped demo bills were keyed with. The
# result was that the rules below worked and the section path never rendered,
# for every line of both Chinese demo projects.
#
# The demo data now carries the registry's spelling. The rule ids, the
# ``standard`` attribute and the ``validation_rule_sets`` entry keep the older
# one, because those live in the rule-set namespace, resolve through a
# different registry, and renaming them would break every manifest that
# declares the set and every message key in four locales for no gain.
#
# The legacy key is still read. An installation that has been storing bills
# since before this change has rows keyed the old way, and a hard switch would
# turn a bill that passed yesterday into one that fails today, which is a worse
# thing to do to a user than carrying one extra lookup.


def _gb50500_code(pos: dict[str, Any]) -> str:
    """The Chinese item code on a position, under either spelling."""
    classification = pos.get("classification") or {}
    if not isinstance(classification, dict):
        return ""
    return str(classification.get("gb50500") or classification.get("gbt50500") or "")


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
        for pos in _get_leaf_positions(context):
            code = _gb50500_code(pos)
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
            code = _gb50500_code(pos)
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
        for pos in _get_leaf_positions(context):
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


# ── Hungarian Rules (magasépítési és infrastruktúra tételrend) ──────────
#
# Hungarian bills of quantities are written against a sectoral item order
# (tételrend) rather than a cost-group hierarchy. Two of them are in use and
# both are represented here, because a Hungarian contractor meets both:
#
#   building       a nine segment code, ``MA`` for building works followed by
#                  a two digit chapter (fejezet) and up to seven further
#                  numeric levels, written with hyphens: ``MA-01-11-01``. The
#                  seventeen chapters are fixed and are listed below.
#   infrastructure a six or seven digit item number (tételszám) drawn from a
#                  per project code dictionary, plus a row number that makes
#                  the pairing unique inside one project.
#
# The other thing that makes a Hungarian bill Hungarian is the split of every
# priced line into anyag (material) and díj (labour and plant fee). They are
# quoted, summed and reported separately all the way up to the cover sheet,
# and the two together are the line's rate. A bill whose split does not
# reconcile with its own totals is not a formatting problem there: the two
# columns are what the client compares between tenderers.
#
# The chapter names are the standard's own, in Hungarian. They are data, not
# prose, and an English gloss sits beside each so a reader outside Hungary can
# follow the tree.
HU_BUILDING_SECTOR = "MA"

HU_BUILDING_CHAPTERS: dict[str, str] = {
    "01": "ÁLTALÁNOS, JÁRULÉKOS KÖLTSÉGEK",  # general and ancillary costs
    "02": "ELŐKÉSZÍTŐ MUNKÁK",  # preparatory works
    "03": "FÖLDMUNKA, ALAPOZÁS",  # earthworks and foundations
    "04": "SZERKEZETÉPÍTÉSI MUNKÁK",  # structural works
    "05": "KÜLSŐ SZAKIPARI MUNKÁK, ÉPÜLET ZÁRÁS",  # envelope and external trades
    "06": "ÉPÍTÉSZETI, SZAKIPARI MUNKÁK",  # architectural and finishing trades
    "07": "BELSŐÉPÍTÉSZETI MUNKÁK",  # interior fit out
    "08": "MŰEMLÉKI, RESTAURÁTORI MUNKÁK",  # heritage and restoration works
    "09": "ÉPÜLETGÉPÉSZET",  # mechanical services
    "10": "TŰZVÉDELMI RENDSZEREK, OLTÓRENDSZER",  # fire protection and suppression
    "11": "ERŐSÁRAMÚ MUNKÁK",  # electrical power
    "12": "GYENGEÁRAMÚ MUNKÁK",  # extra low voltage and communications
    "13": "AUTOMATIKA",  # building automation
    "14": "SPECIÁLIS TECHNOLÓGIA",  # specialist technology
    "15": "FELVONÓK, EMELŐSZERKEZETEK",  # lifts and lifting equipment
    "16": "KÜLSŐ MUNKÁK",  # external works
    "17": "ÁTADÁS",  # handover
}

# ``MA`` plus a chapter, then up to seven further levels. Sub chapter numbers
# run to three digits (a chapter that overflows its two digit range continues
# at 101, 199 and so on), which is why the segment length is a range and not a
# constant.
_HU_BUILDING_CODE_RE = re.compile(r"^MA-(0[1-9]|1[0-7])(?:-\d{2,3}){0,7}$")

# The infrastructure item number is written either closed up or with a single
# space after the third digit, so the space is removed before the shape is
# judged rather than being admitted into the pattern.
#
# The length is a range because the delivered files say so, not because a
# range is safer. Six or seven digits covers 335 of the 350 lines in the file
# this was measured on; the rest are a five digit number, a single digit on
# the top line of the project, and two lines carrying a letter suffix after an
# underscore. A pattern written from the common case alone would have called
# fifteen correct lines invalid.
_HU_INFRA_CODE_RE = re.compile(r"^\d{1,7}(?:_[A-Za-z0-9]{1,4})?$")


def _hu_block(pos: dict[str, Any]) -> dict[str, Any]:
    """The Hungarian payload an import left on a position, or an empty dict.

    Positions that never came from a Hungarian bill carry nothing here, and
    every rule below treats that as "not my row" rather than as a failure.
    A pack switched on for a Hungarian company still sees plenty of BOQs
    imported from elsewhere, and flagging all of them would train the reader
    to ignore the whole rule set.
    """
    block = _position_metadata(pos).get("hu")
    return block if isinstance(block, dict) else {}


def _hu_code(pos: dict[str, Any]) -> str:
    """The Hungarian item code on a position, whitespace normalised."""
    code = (pos.get("classification") or {}).get("tetelrend", "")
    return re.sub(r"\s+", "", str(code)).upper()


class HungarianItemCodeRequired(ValidationRule):
    rule_id = "hungary.item_code_required"
    name = "Hungarian Item Code Required"
    standard = "hungary"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Priced lines must carry an item code from one of the Hungarian sectoral item orders"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            code = _hu_code(pos)
            passed = bool(_HU_BUILDING_CODE_RE.match(code) or _HU_INFRA_CODE_RE.match(code))
            if passed:
                message = _ok(locale)
                suggestion = None
            elif code:
                message = translate(
                    "hungary.item_code_required.invalid",
                    locale=locale,
                    code=code,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate("hungary.item_code_required.suggestion", locale=locale)
            else:
                message = translate(
                    "hungary.item_code_required.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate("hungary.item_code_required.suggestion", locale=locale)
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


class HungarianChapterRecognised(ValidationRule):
    rule_id = "hungary.chapter_recognised"
    name = "Hungarian Chapter Is One of the Seventeen"
    standard = "hungary"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "The chapter segment of a building item code must be one of the seventeen in the sectoral order"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = _hu_code(pos)
            # Only the building order carries chapters. An infrastructure item
            # number is not a failure here, it is a different order.
            if not code.startswith(f"{HU_BUILDING_SECTOR}-"):
                continue
            segments = code.split("-")
            chapter = segments[1] if len(segments) > 1 else ""
            passed = chapter in HU_BUILDING_CHAPTERS
            if passed:
                message = _ok(locale)
            else:
                message = translate(
                    "hungary.chapter_recognised.fail",
                    locale=locale,
                    chapter=chapter or "?",
                    ordinal=pos.get("ordinal", "?"),
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
                    details={"chapter": chapter, "chapter_name": HU_BUILDING_CHAPTERS.get(chapter, "")},
                )
            )
        return results


class HungarianMaterialFeeSplit(ValidationRule):
    """The anyag and díj halves of a line have to add up to the line.

    Deliberately not "every line must carry both halves". Design fees, permit
    charges and site management are quoted as díj alone and carry no material,
    and a supply only line carries no fee; a rule that demanded both would be
    wrong about a large and perfectly correct part of any Hungarian bill.
    What is always true is that the two halves are the rate, which is the
    invariant the summary sheets are built on, and it is the one a bill can
    actually break by editing a rate without editing its split.
    """

    rule_id = "hungary.material_fee_split"
    name = "Material and Fee Add Up to the Rate"
    standard = "hungary"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The anyag and díj unit prices of a position must sum to its unit rate"

    REL_TOLERANCE = 0.01

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            block = _hu_block(pos)
            if "material_unit_rate" not in block and "fee_unit_rate" not in block:
                continue
            material_p = _to_number(block.get("material_unit_rate"))
            fee_p = _to_number(block.get("fee_unit_rate"))
            rate_p = _to_number(pos.get("unit_rate"))
            if rate_p is None or rate_p is _NOT_A_NUMBER:
                continue
            rate_val: float = rate_p  # type: ignore[assignment]
            if rate_val <= 0:
                continue
            material = material_p if isinstance(material_p, float) else 0.0
            fee = fee_p if isinstance(fee_p, float) else 0.0
            split_total = material + fee
            diff_ratio = abs(split_total - rate_val) / rate_val
            passed = diff_ratio <= self.REL_TOLERANCE
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "hungary.material_fee_split.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    material=_fmt_decimal(material),
                    fee=_fmt_decimal(fee),
                    rate=_fmt_decimal(rate_val),
                )
                suggestion = translate("hungary.material_fee_split.suggestion", locale=locale)
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
                        "material_unit_rate": material,
                        "fee_unit_rate": fee,
                        "unit_rate": rate_val,
                        "difference_ratio": diff_ratio,
                        "tolerance": self.REL_TOLERANCE,
                    },
                    suggestion=suggestion,
                )
            )
        return results


class HungarianItemNumberUnique(ValidationRule):
    """The infrastructure order's per project item number has to stay unique.

    The number is the row's identity for the client's monitoring system: it is
    what the progress figures, the payment applications and the programme
    activities are matched on. Two lines sharing one number do not fail any
    arithmetic, they merge silently at the far end, which is why this is an
    error and not a warning.
    """

    rule_id = "hungary.item_number_unique"
    name = "Project Item Numbers Are Unique"
    standard = "hungary"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Each per-project item number may appear on only one position"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        seen: dict[str, int] = {}
        for pos in _get_positions(context):
            number = str(_hu_block(pos).get("item_number", "")).strip()
            if number:
                seen[number] = seen.get(number, 0) + 1

        results: list[RuleResult] = []
        for pos in _get_positions(context):
            number = str(_hu_block(pos).get("item_number", "")).strip()
            if not number:
                continue
            count = seen.get(number, 0)
            passed = count == 1
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "hungary.item_number_unique.fail",
                    locale=locale,
                    number=number,
                    count=count,
                )
                suggestion = translate("hungary.item_number_unique.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"item_number": number, "occurrences": count},
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
        for pos in _get_leaf_positions(context):
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
        for pos in _get_leaf_positions(context):
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
    losing the original catalogue reference.

    The rule does not guard on the project's classification standard or
    region, whatever this docstring used to claim: it checks every leaf
    position it is handed. Scope comes from selecting the ``bc3`` rule
    set and from nowhere else, so a project that runs it outside Spain
    gets an ERROR on every position with no concept code. That was
    harmless while nothing reached the set; the Spanish compliance pack
    now runs it at contract signature, and the next reader has to know
    the rule does not scope itself.
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
        for pos in _get_leaf_positions(context):
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


# ── Mexico Rules (APU, IVA, retenciones, CFDI) ─────────────────────────────
#
# Mexican estimating revolves around the analisis de precios unitarios (APU)
# integrated under the LOPSRM public-works law and its reglamento: a costo
# directo (mano de obra, materiales, maquinaria) plus indirectos, financiamiento,
# utilidad and cargos adicionales, with IVA (16 percent, 8 percent in the border
# region) added to the total. These rules check that a Mexican BOQ carries the
# pieces a real pilot needs: a complete APU breakdown, a valid IVA rate,
# retenciones flagged on subcontract lines, and the CFDI 4.0 issuer identifiers
# (RFC, regimen fiscal, uso CFDI) needed to invoice and export a tender.
# INFONAVIT/FOVISSSTE/CONAVI (social housing), IMSS, SAT, CFDI and LOPSRM are
# government bodies, laws and standards - regulatory facts, not product brands.

# Resource-type tokens that map to each APU costo-directo component. The BOQ
# resource normaliser emits the English tokens; the Spanish aliases let a
# locally authored APU use its own vocabulary.
_MX_LABOR_TYPES: frozenset[str] = frozenset({"labor", "labour", "mano_de_obra", "mano de obra", "mo"})
_MX_MATERIAL_TYPES: frozenset[str] = frozenset({"material", "materials", "materiales"})
_MX_EQUIPMENT_TYPES: frozenset[str] = frozenset(
    {"equipment", "machinery", "maquinaria", "equipo", "herramienta", "tool", "tools"}
)
_MX_SUBCONTRACT_TYPES: frozenset[str] = frozenset(
    {"subcontractor", "subcontract", "subcontrato", "subcontratista", "destajo"}
)
_MX_COMPONENT_LABELS: dict[str, str] = {
    "mano_de_obra": "mano de obra",
    "materiales": "materiales",
    "maquinaria": "maquinaria",
}
# Valid Mexican IVA rates as percentages: 16 standard, 8 border region, 0 zero.
_MX_VALID_IVA_PCT: tuple[Decimal, ...] = (Decimal("0"), Decimal("8"), Decimal("16"))
# CFDI 4.0 issuer fields a tender export needs, with display labels.
_MX_CFDI_FIELDS: dict[str, str] = {
    "rfc": "RFC",
    "regimen_fiscal": "regimen fiscal",
    "uso_cfdi": "uso CFDI",
}


def _mx_resource_kind(res: dict[str, Any]) -> str | None:
    """Classify one APU resource into a costo-directo component, or None.

    Reads the resource's type from the first of ``type`` / ``resource_type`` /
    ``category`` / ``kind`` that is set, and maps it to ``mano_de_obra``,
    ``materiales`` or ``maquinaria``. Returns ``None`` for an unrecognised type.
    """
    raw = ""
    for key in ("type", "resource_type", "category", "kind"):
        val = res.get(key)
        if isinstance(val, str) and val.strip():
            raw = val.strip().lower()
            break
    if raw in _MX_LABOR_TYPES:
        return "mano_de_obra"
    if raw in _MX_MATERIAL_TYPES:
        return "materiales"
    if raw in _MX_EQUIPMENT_TYPES:
        return "maquinaria"
    return None


def _mx_normalize_pct(value: Any) -> Decimal | None:
    """Coerce a declared IVA rate to a percentage Decimal, or None if unparseable.

    Accepts percentage forms (``16``, ``"16"``, ``"16 %"``) and fraction forms
    (``0.16``). A value in ``(0, 1]`` is read as a fraction and scaled by 100, so
    ``0.16`` becomes ``16`` and ``0`` stays ``0``.
    """
    parsed = _to_number(value)
    if parsed is None or parsed is _NOT_A_NUMBER:
        return None
    dec = Decimal(str(parsed))
    if Decimal("0") < dec <= Decimal("1"):
        dec = dec * Decimal("100")
    return dec


def _mx_is_subcontract(meta: dict[str, Any]) -> bool:
    """True when a position's metadata marks it as subcontracted work.

    Detected by an explicit flag (``subcontracted`` / ``is_subcontract`` /
    ``subcontrato``) or by a resource line whose type is a subcontractor type.
    """
    for flag in ("subcontracted", "is_subcontract", "subcontrato", "subcontratado"):
        if meta.get(flag):
            return True
    resources = meta.get("resources")
    if isinstance(resources, list):
        for res in resources:
            if not isinstance(res, dict):
                continue
            for key in ("type", "resource_type", "category", "kind"):
                val = res.get(key)
                if isinstance(val, str) and val.strip().lower() in _MX_SUBCONTRACT_TYPES:
                    return True
    return False


def _mx_cfdi_fields(context: ValidationContext) -> dict[str, Any]:
    """Collect CFDI issuer fields from the context, regardless of shape.

    Looks in ``context.metadata`` (and a nested ``cfdi`` block), then in
    ``context.data`` when it is a dict (top level, a ``cfdi`` block, and the
    ``metadata`` / ``metadata_`` blobs). The first non-empty value per field
    wins. Returns a dict that may carry ``rfc`` / ``regimen_fiscal`` / ``uso_cfdi``.
    """
    sources: list[dict[str, Any]] = []
    meta = getattr(context, "metadata", None)
    if isinstance(meta, dict):
        sources.append(meta)
        if isinstance(meta.get("cfdi"), dict):
            sources.append(meta["cfdi"])
    data = context.data
    if isinstance(data, dict):
        sources.append(data)
        if isinstance(data.get("cfdi"), dict):
            sources.append(data["cfdi"])
        for meta_key in ("metadata", "metadata_"):
            blob = data.get(meta_key)
            if isinstance(blob, dict):
                sources.append(blob)
                if isinstance(blob.get("cfdi"), dict):
                    sources.append(blob["cfdi"])
    found: dict[str, Any] = {}
    for field in _MX_CFDI_FIELDS:
        for src in sources:
            val = src.get(field)
            if isinstance(val, str) and val.strip():
                found[field] = val.strip()
                break
    return found


class APUCompletenessRule(ValidationRule):
    """A Mexican APU should integrate at least mano de obra and materiales.

    For each leaf position that carries a ``metadata.resources`` breakdown (the
    start of an APU), the costo directo should include both mano de obra and
    materiales; maquinaria is optional since not every concept uses it. A
    position explicitly flagged ``metadata.apu_supply_only`` (pure material
    supply) or ``metadata.apu_labor_only`` is skipped so those legitimate
    single-component concepts do not warn. Positions without a resource
    breakdown are not assessed. WARNING, never blocks.
    """

    rule_id = "mexico.apu_completeness"
    name = "APU Cost Components Complete"
    standard = "mexico"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A Mexican APU should integrate mano de obra and materiales in its costo directo"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            meta = _position_metadata(pos)
            resources = meta.get("resources")
            if not isinstance(resources, list) or not resources:
                continue
            if meta.get("apu_supply_only") or meta.get("apu_labor_only"):
                continue
            present: set[str] = set()
            for res in resources:
                if not isinstance(res, dict):
                    continue
                kind = _mx_resource_kind(res)
                if kind:
                    present.add(kind)
            required = {"mano_de_obra", "materiales"}
            missing = required - present
            passed = not missing
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                missing_labels = ", ".join(
                    _MX_COMPONENT_LABELS[k] for k in ("mano_de_obra", "materiales", "maquinaria") if k in missing
                )
                message = translate(
                    "mexico.apu_completeness.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    missing=missing_labels,
                )
                suggestion = translate("mexico.apu_completeness.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"present": sorted(present), "missing": sorted(missing)},
                    suggestion=suggestion,
                )
            )
        return results


class IVARateValidityRule(ValidationRule):
    """A declared IVA rate must be 16 (standard), 8 (border region) or 0.

    Reads a per-position IVA rate from ``iva_rate`` / ``vat_rate`` / ``tax_rate``
    / ``iva`` (top level or metadata), accepting both percentage (``16``) and
    fraction (``0.16``) forms. Positions that declare no rate are skipped; an
    out-of-range or unparseable rate is flagged. WARNING.
    """

    rule_id = "mexico.iva_rate_valid"
    name = "Valid Mexican IVA Rate"
    standard = "mexico"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "IVA must be 16 percent (standard), 8 percent (border region) or 0 percent"

    _KEYS = ("iva_rate", "vat_rate", "tax_rate", "iva")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            meta = _position_metadata(pos)
            raw = None
            for key in self._KEYS:
                if pos.get(key) is not None:
                    raw = pos.get(key)
                    break
                if meta.get(key) is not None:
                    raw = meta.get(key)
                    break
            if raw is None:
                continue
            pct = _mx_normalize_pct(raw)
            passed = pct is not None and any(abs(pct - allowed) <= Decimal("0.01") for allowed in _MX_VALID_IVA_PCT)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                if pct is None:
                    shown = "?"
                else:
                    shown = format(pct, "f")
                    if "." in shown:
                        shown = shown.rstrip("0").rstrip(".")
                message = translate(
                    "mexico.iva_rate_valid.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                    rate=shown,
                )
                suggestion = translate("mexico.iva_rate_valid.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=message,
                    element_ref=pos.get("id"),
                    details={"declared_rate": str(raw)},
                    suggestion=suggestion,
                )
            )
        return results


class SubcontractRetencionRule(ValidationRule):
    """Subcontract lines should flag whether IVA/ISR retenciones apply.

    For positions marked as subcontracted (a ``subcontracted`` flag or a
    subcontractor resource line), check that the metadata records a retencion
    decision (``retenciones`` / ``retencion_iva`` / ``retencion_isr`` and the
    like). Retention applicability depends on the supplier's regime and the
    contract, so this is an INFO nudge, never a block. Non-subcontract lines
    are not assessed.
    """

    rule_id = "mexico.subcontract_retencion"
    name = "Subcontract Retenciones Flagged"
    standard = "mexico"
    severity = Severity.INFO
    category = RuleCategory.COMPLIANCE
    description = "Subcontract lines should record whether IVA/ISR retenciones apply"

    _RET_KEYS = (
        "retenciones",
        "retencion_iva",
        "retencion_isr",
        "retention",
        "iva_retention",
        "isr_retention",
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            meta = _position_metadata(pos)
            if not _mx_is_subcontract(meta):
                continue
            passed = any(meta.get(key) for key in self._RET_KEYS)
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                message = translate(
                    "mexico.subcontract_retencion.fail",
                    locale=locale,
                    ordinal=pos.get("ordinal", "?"),
                )
                suggestion = translate("mexico.subcontract_retencion.suggestion", locale=locale)
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


class CFDIIssuerDataRule(ValidationRule):
    """The CFDI 4.0 issuer identifiers must be present for a tender export.

    A single project-level check: the issuer RFC, regimen fiscal and uso CFDI
    are needed to invoice and to export a tender in Mexico. When the RFC is
    present it must match the CFDI RFC shape (12 characters for a persona moral,
    13 for a persona fisica). WARNING, never blocks.
    """

    rule_id = "mexico.cfdi_rfc_present"
    name = "CFDI Issuer Data Present"
    standard = "mexico"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "CFDI 4.0 issuer RFC, regimen fiscal and uso CFDI should be set for tender export"

    _RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        fields = _mx_cfdi_fields(context)
        rfc = str(fields.get("rfc") or "").strip()
        ref = context.project_id

        if rfc and not self._RFC.match(rfc.upper()):
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate("mexico.cfdi_rfc_present.invalid_rfc", locale=locale, rfc=rfc),
                    element_ref=ref,
                    suggestion=translate("mexico.cfdi_rfc_present.suggestion", locale=locale),
                )
            ]

        missing = [label for key, label in _MX_CFDI_FIELDS.items() if not fields.get(key)]
        passed = not missing
        if passed:
            message = _ok(locale)
            suggestion = None
        else:
            message = translate(
                "mexico.cfdi_rfc_present.missing",
                locale=locale,
                missing=", ".join(missing),
            )
            suggestion = translate("mexico.cfdi_rfc_present.suggestion", locale=locale)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                element_ref=ref,
                details={"missing": missing},
                suggestion=suggestion,
            )
        ]


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

    IMPERIAL_UNITS = {
        "ft",
        "ft2",
        "ft3",
        "yd",
        "yd2",
        "yd3",
        "in",
        "lb",
        "ton",
        "ton_us",
        "gal",
        "sf",
        "sy",
        "cy",
        "lf",
    }
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
# The scale-plausibility, self-intersection and low-confidence rules that used
# to sit here are gone. Each re-implemented a check the takeoff service already
# performs before a proposal is ever written, and each kept its own copy of the
# thresholds, so the two could drift apart while both looked authoritative. The
# belt is plan_read.scale_is_plausible and plan_read.polygon_self_intersects;
# the per-row verdict and confidence they produce are what the canvas renders
# and what the accept endpoint blocks on. What no other layer accounts for is a
# review queue nobody worked, which is the rule below.

#: Metadata key carrying the number of takeoff rows still awaiting review.
#: Exported so the caller that gathers the count and the rule that reads it
#: cannot drift apart on a spelling; a typo here would silence the rule
#: permanently and look exactly like a clean review queue.
UNREVIEWED_PROPOSALS_META_KEY = "unreviewed_takeoff_proposals"


class TakeoffUnreviewedProposalsRule(ValidationRule):
    """Report quantities the detector proposed and nobody has decided on.

    A `proposed` row is a suggestion, not a measurement, so it is deliberately
    excluded from totals, exports and the priced estimate. The correctness of
    that exclusion is not in question here; what is missing without this rule
    is any account of it. A user who ran plan reading, never worked the review
    queue and then priced the project gets a number that is quietly short of
    what the drawing shows, with nothing on screen to explain the difference.

    Severity is WARNING on purpose. The estimator refuses to apply a run whose
    report carries errors, and blocking the estimate would be the wrong answer:
    pricing the confirmed subset is a legitimate thing to want, and the person
    who left the queue unworked may have meant to. The report says what is not
    included; the decision stays with them.

    The count arrives in metadata rather than being queried here, because rules
    receive data, not a database session. Absent the key the rule returns
    nothing at all, which keeps it honest on the paths that do not supply it.
    """

    rule_id = "ai_takeoff.unreviewed_proposals"
    name = "AI Takeoff Unreviewed Proposals"
    standard = "ai_takeoff"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Detector proposals awaiting review are excluded from priced quantities"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        pending = _to_number(context.metadata.get(UNREVIEWED_PROPOSALS_META_KEY))
        # No count supplied is not the same as a count of zero: stay silent
        # rather than certify a project this caller never asked about.
        if pending is None or pending is _NOT_A_NUMBER:
            return []
        count = int(pending)  # type: ignore[arg-type]
        passed = count <= 0
        message = (
            _ok(locale) if passed else translate("ai_takeoff.unreviewed_proposals.fail", locale=locale, count=count)
        )
        suggestion = None if passed else translate("ai_takeoff.unreviewed_proposals.suggestion", locale=locale)
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


# ── Field Time (labour + plant field timesheets) ────────────────────────────
#
# Validate a foreman's field timesheet payload (see app.modules.field_time).
# The logic lives in the pure engine ``field_time_math`` so the rule bodies stay
# thin and the same checks are unit-tested without a database. The engine is
# imported lazily inside ``validate()`` so this core package never hard-depends
# on a business module at import time (a disabled field_time module must not
# break rule loading).


def _ft_payload(context: ValidationContext) -> dict[str, Any]:
    """Return the timesheet payload dict from the context (empty if malformed)."""
    data = context.data
    return data if isinstance(data, dict) else {}


def _ft_lines(context: ValidationContext) -> list[dict[str, Any]]:
    """Return the timesheet's line dicts from the context."""
    lines = _ft_payload(context).get("lines")
    return lines if isinstance(lines, list) else []


def _ft_line_label(index: int, line: dict[str, Any]) -> str:
    """A human line label: the 1-based row number plus its cost code if any."""
    code = str(line.get("cost_code") or "").strip()
    return f"{index + 1} ({code})" if code else str(index + 1)


class FieldTimeHoursPerDayMax(ValidationRule):
    """A single worker cannot book more than 24 hours across a day's lines."""

    rule_id = "field_time.hours_per_day_max"
    name = "Field Time Hours Per Day Maximum"
    standard = "field_time"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a worker whose summed labour hours for the day exceed 24."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        lines = _ft_lines(context)
        if not lines:
            return []
        from app.modules.field_time import field_time_math as ft

        totals = ft.sum_hours_by_worker(lines)
        results: list[RuleResult] = []
        for worker, hours in sorted(totals.items()):
            passed = hours <= ft.MAX_HOURS_PER_DAY
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=(
                        _ok(locale)
                        if passed
                        else translate(
                            "field_time.hours_per_day_max.fail",
                            locale=locale,
                            worker=worker,
                            hours=f"{hours}",
                            max=f"{ft.MAX_HOURS_PER_DAY}",
                        )
                    ),
                    element_ref=worker,
                    suggestion=(
                        None if passed else translate("field_time.hours_per_day_max.suggestion", locale=locale)
                    ),
                )
            )
        return results


class FieldTimeLineComplete(ValidationRule):
    """Each line must be labour XOR plant, have positive hours and a cost code."""

    rule_id = "field_time.line_complete"
    name = "Field Time Line Complete"
    standard = "field_time"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags timesheet lines that are not labour-XOR-plant, or lack hours / a cost code."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        lines = _ft_lines(context)
        if not lines:
            return []
        from app.modules.field_time import field_time_math as ft

        results: list[RuleResult] = []
        for index, line in enumerate(lines):
            outcome = ft.line_completeness(line)
            if outcome.passed:
                message = _ok(locale)
                suggestion = None
            else:
                reason = ", ".join(
                    translate(f"field_time.line_complete.{code}", locale=locale) for code in outcome.reasons
                )
                message = translate(
                    "field_time.line_complete.fail",
                    locale=locale,
                    line=_ft_line_label(index, line),
                    reason=reason,
                )
                suggestion = translate("field_time.line_complete.suggestion", locale=locale)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=outcome.passed,
                    message=message,
                    element_ref=str(line.get("id") or index),
                    suggestion=suggestion,
                )
            )
        return results


class FieldTimeCostCodeResolves(ValidationRule):
    """Each coded line must resolve to a BOQ position (cost code) or WBS code.

    The valid code sets are supplied by the service through
    ``context.metadata['valid_cost_codes']`` / ``['valid_wbs']`` (rules have no
    database session). When neither is supplied the check is skipped, so a
    project with no BOQ never produces spurious cost-code errors.
    """

    rule_id = "field_time.cost_code_resolves"
    name = "Field Time Cost Code Resolves"
    standard = "field_time"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Flags timesheet lines whose cost code / WBS matches no BOQ position in the project."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        lines = _ft_lines(context)
        if not lines:
            return []
        meta = getattr(context, "metadata", None) or {}
        raw_codes = meta.get("valid_cost_codes")
        raw_wbs = meta.get("valid_wbs")
        if raw_codes is None and raw_wbs is None:
            return []
        from app.modules.field_time import field_time_math as ft

        valid_codes = set(raw_codes) if raw_codes is not None else None
        valid_wbs = set(raw_wbs) if raw_wbs is not None else None
        bad = set(ft.cost_code_unresolved_indices(lines, valid_cost_codes=valid_codes, valid_wbs=valid_wbs))
        results: list[RuleResult] = []
        for index, line in enumerate(lines):
            code = str(line.get("cost_code") or "").strip()
            wbs = str(line.get("wbs") or "").strip()
            if not code and not wbs:
                continue  # completeness owns the missing-code case
            passed = index not in bad
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=(
                        _ok(locale)
                        if passed
                        else translate(
                            "field_time.cost_code_resolves.fail",
                            locale=locale,
                            line=_ft_line_label(index, line),
                            code=code or wbs,
                        )
                    ),
                    element_ref=str(line.get("id") or index),
                    suggestion=(
                        None if passed else translate("field_time.cost_code_resolves.suggestion", locale=locale)
                    ),
                )
            )
        return results


class FieldTimeDayworkNeedsVariation(ValidationRule):
    """A daywork line should reference an open variation it was performed under."""

    rule_id = "field_time.daywork_needs_variation"
    name = "Field Time Daywork Needs Variation"
    standard = "field_time"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags daywork lines not linked to an open variation order."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        lines = _ft_lines(context)
        if not lines:
            return []
        from app.modules.field_time import field_time_math as ft

        meta = getattr(context, "metadata", None) or {}
        raw_open = meta.get("open_variation_ids")
        open_ids = set(raw_open) if raw_open is not None else None
        bad = set(ft.daywork_incomplete_indices(lines, open_variation_ids=open_ids))
        results: list[RuleResult] = []
        for index, line in enumerate(lines):
            if not line.get("is_daywork"):
                continue
            passed = index not in bad
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=(
                        _ok(locale)
                        if passed
                        else translate(
                            "field_time.daywork_needs_variation.fail",
                            locale=locale,
                            line=_ft_line_label(index, line),
                        )
                    ),
                    element_ref=str(line.get("id") or index),
                    suggestion=(
                        None if passed else translate("field_time.daywork_needs_variation.suggestion", locale=locale)
                    ),
                )
            )
        return results


class FieldTimePlantNeedsEquipment(ValidationRule):
    """A line declaring plant work should name the equipment item it used."""

    rule_id = "field_time.plant_needs_equipment"
    name = "Field Time Plant Needs Equipment"
    standard = "field_time"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags plant-intent lines that name no equipment item (so plant hours can be costed)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        lines = _ft_lines(context)
        if not lines:
            return []
        from app.modules.field_time import field_time_math as ft

        bad = ft.plant_missing_equipment_indices(lines)
        results: list[RuleResult] = []
        for index in bad:
            line = lines[index]
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "field_time.plant_needs_equipment.fail",
                        locale=locale,
                        line=_ft_line_label(index, line),
                    ),
                    element_ref=str(line.get("id") or index),
                    suggestion=translate("field_time.plant_needs_equipment.suggestion", locale=locale),
                )
            )
        return results


class FieldTimeOfflineClockPlausible(ValidationRule):
    """A day captured offline must not claim to have been written in the future.

    Deliberately a WARNING. Nothing in the platform orders anything by the
    device clock - the replay queue keeps its own sequence and the server stamps
    its own arrival time - so a wrong clock corrupts no data. It does mislead the
    person reading two entries side by side, which is worth saying and is not
    worth refusing a real shift over. An ERROR here would make a day permanently
    unsubmittable because a phone was set to the wrong year.
    """

    rule_id = "field_time.offline_clock_plausible"
    name = "Field Time Offline Clock Plausible"
    standard = "field_time"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags an offline entry whose device clock ran ahead of the server."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        payload = _ft_payload(context)
        from app.modules.field_time import field_time_math as ft

        capture = ft.read_offline_capture(payload.get("metadata"))
        if not capture.recorded:
            return []
        ahead = ft.offline_clock_ahead_minutes(capture)
        if ahead is None or ahead <= ft.OFFLINE_CLOCK_TOLERANCE_MINUTES:
            return []
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(
                    "field_time.offline_clock_plausible.fail",
                    locale=locale,
                    minutes=f"{ahead}",
                ),
                element_ref=capture.device or capture.entry_key,
                suggestion=translate("field_time.offline_clock_plausible.suggestion", locale=locale),
            )
        ]


class FieldTimeOfflineSyncDelay(ValidationRule):
    """A day that reached the office long after it was worked wants a second look.

    Also a WARNING, and for the same reason: the delay is the site's, not the
    foreman's. Hours recorded in a basement and synced a fortnight later are
    still true hours, but they have probably missed a valuation and possibly a
    payroll run, and the approver is the last person who can catch that.
    """

    rule_id = "field_time.offline_sync_delay"
    name = "Field Time Offline Sync Delay"
    standard = "field_time"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags an offline entry that reached the server long after the day it books."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        payload = _ft_payload(context)
        from app.modules.field_time import field_time_math as ft

        capture = ft.read_offline_capture(payload.get("metadata"))
        if not capture.recorded:
            return []
        delay = ft.offline_sync_delay_days(capture, payload.get("date"))
        if delay is None or delay <= ft.OFFLINE_SYNC_DELAY_WARN_DAYS:
            return []
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(
                    "field_time.offline_sync_delay.fail",
                    locale=locale,
                    days=f"{delay}",
                    date=str(payload.get("date") or ""),
                ),
                element_ref=str(payload.get("id") or ""),
                suggestion=translate("field_time.offline_sync_delay.suggestion", locale=locale),
            )
        ]


class FieldTimeApprovedImmutable(ValidationRule):
    """An approved or reversed timesheet cannot be edited - only reversed."""

    rule_id = "field_time.approved_immutable"
    name = "Field Time Approved Immutable"
    standard = "field_time"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags any attempt to mutate an approved or reversed timesheet."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        payload = _ft_payload(context)
        status_value = str(payload.get("status") or "")
        meta = getattr(context, "metadata", None) or {}
        operation = str(meta.get("operation") or "").lower()
        mutating = operation in ("update", "delete", "edit")
        locked = status_value in ("approved", "reversed")
        if not (mutating and locked):
            return []
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(
                    "field_time.approved_immutable.fail",
                    locale=locale,
                    status=status_value,
                ),
                element_ref=str(payload.get("id") or ""),
                suggestion=translate("field_time.approved_immutable.suggestion", locale=locale),
            )
        ]


# ── Estimate Audit rule set (curated cross-checks) ────────────────────────────
#
# A curated ``estimate_audit`` rule set that catches the four classes of
# mistake a reviewer looks for first when auditing someone else's estimate:
#
#   1. wrong unit of measure    - concrete billed per metre, formwork per m³ …
#   2. near-duplicate lines     - the same scope entered twice under two OZ
#   3. missing companion item   - concrete with no formwork / rebar line;
#                                 paint with no primer (driven by the shapes
#                                 of the platform's own Assembly recipes)
#   4. off-band unit rate       - a rate that is a multiple of, or a fraction
#                                 of, the same work's catalogue rate in the
#                                 SAME currency (benchmarked with the existing
#                                 CWICR matcher, not a hardcoded threshold)
#
# The maps below are seed data distilled from two existing sources of truth:
# the unit conventions of the CWICR catalogue (``CostItem.unit``) and the
# component structure of the Assembly library (``AssemblyTemplate.components``
# - e.g. a reinforced-concrete recipe carries concrete + rebar + formwork).
# Keeping them as curated constants means the rules stay pure and DB-free;
# only the rate-benchmark rule reaches for a live matcher, and only when the
# caller supplies one.


def _audit_text(key: str, locale: str, default: str, **params: Any) -> str:
    """Localized estimate-audit message with an English default.

    Routes through the validation message bundle when a translation for
    ``key`` exists, so these strings localize automatically once the keys are
    added to the locale bundles (and by the translation sweep). Until then a
    sensible English ``default`` is rendered instead of a humanised key stub,
    so an estimator always sees a clear message. Mirrors the frontend
    ``t(key, { defaultValue })`` convention.

    Args:
        key: Dot-notation message key (``estimate_audit.<rule>.<state>``).
        locale: Caller locale from ``ValidationContext.metadata['locale']``.
        default: English fallback template with ``str.format`` placeholders.
        **params: Interpolation values applied to whichever template wins.

    Returns:
        The formatted, localized (or English-default) message.
    """
    if is_key_present(key, locale) or is_key_present(key, DEFAULT_LOCALE):
        return translate(key, locale=locale, **params)
    try:
        return default.format(**params)
    except (KeyError, IndexError, ValueError):
        return default


# Unit token → physical dimension. Comparisons are made on the *dimension*
# (length / area / volume / mass / count / time / lump) rather than the exact
# unit string, so "m3" and "m³" and "cbm" all read as volume and a work
# type's expected dimension can be checked without enumerating every spelling.
_UNIT_DIMENSIONS: dict[str, str] = {
    # length
    "m": "length",
    "lm": "length",
    "lfm": "length",
    "lfdm": "length",
    "rm": "length",
    "mm": "length",
    "cm": "length",
    "km": "length",
    "ft": "length",
    "lft": "length",
    "in": "length",
    "inch": "length",
    "yd": "length",
    # area
    "m2": "area",
    "m²": "area",
    "sqm": "area",
    "qm": "area",
    "ft2": "area",
    "sqft": "area",
    "sf": "area",
    "yd2": "area",
    "sqyd": "area",
    "sy": "area",
    "ha": "area",
    # volume
    "m3": "volume",
    "m³": "volume",
    "cbm": "volume",
    "cum": "volume",
    "ft3": "volume",
    "cuft": "volume",
    "cf": "volume",
    "cy": "volume",
    "yd3": "volume",
    "l": "volume",
    "ltr": "volume",
    "litre": "volume",
    "liter": "volume",
    "gal": "volume",
    "gallon": "volume",
    # mass
    "kg": "mass",
    "t": "mass",
    "to": "mass",
    "mt": "mass",
    "tonne": "mass",
    "tonnes": "mass",
    "ton": "mass",
    "ton_us": "mass",
    "lb": "mass",
    "lbs": "mass",
    "g": "mass",
    # count
    "pcs": "count",
    "pc": "count",
    "stk": "count",
    "stck": "count",
    "st": "count",
    "stück": "count",
    "nr": "count",
    "no": "count",
    "ea": "count",
    "each": "count",
    "u": "count",
    "unit": "count",
    "set": "count",
    # time (labour / plant)
    "h": "time",
    "hr": "time",
    "hrs": "time",
    "hour": "time",
    "std": "time",
    "day": "time",
    "wk": "time",
    "week": "time",
    "mo": "time",
    # lump sum / not dimension-bound
    "lsum": "lump",
    "ls": "lump",
    "psch": "lump",
    "pausch": "lump",
    "pauschal": "lump",
    "sum": "lump",
    "item": "lump",
    "lot": "lump",
}

# Representative unit label per dimension (for human-readable messages).
_DIMENSION_LABEL: dict[str, str] = {
    "length": "m",
    "area": "m²",
    "volume": "m³",
    "mass": "kg",
    "count": "pcs",
    "time": "h",
    "lump": "lsum",
}


def _unit_dimension(unit: str) -> str | None:
    """Return the physical dimension of a BOQ unit token, or ``None``.

    Args:
        unit: Raw unit string (``"m3"``, ``"m²"``, ``"kg"``, ``"lsum"`` …).

    Returns:
        One of ``length`` / ``area`` / ``volume`` / ``mass`` / ``count`` /
        ``time`` / ``lump``, or ``None`` when the token is unknown (in which
        case a rule must not judge it, to avoid false positives).
    """
    return _UNIT_DIMENSIONS.get((unit or "").strip().lower())


# Ordered work-type detection. First match wins, so the more specific
# companion trades (formwork, reinforcement, screed …) are listed BEFORE the
# bulk "concrete" so a line like "concrete formwork" is read as formwork, not
# concrete. Keywords are lower-case substrings covering the most common
# EN / DE plus a few ES / FR / RU spellings (CWICR is multilingual). Every
# keyword is distinctive enough to substring-match a description safely.
_WORK_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("reinforcement", ("reinforcement", "rebar", "bewehrung", "betonstahl", "armadura", "ferraillage", "арматур")),
    ("formwork", ("formwork", "shuttering", "schalung", "coffrage", "encofrado", "опалубк")),
    ("structural_steel", ("structural steel", "steelwork", "steel section", "stahlbau", "charpente")),
    ("screed", ("screed", "estrich", "chape", "solado", "стяжк")),
    ("paint", ("paint", "coating", "anstrich", "malerarbeit", "lackier", "peinture", "pintura", "покрас", "окрас")),
    ("tiling", ("tiling", "tile", "fliesen", "carrelage", "alicatado", "плитк")),
    ("plaster", ("plaster", "render", "putz", "enduit", "revoco", "штукатур")),
    ("waterproofing", ("waterproofing", "abdichtung", "impermeabili", "étanchéité", "etancheite", "гидроизоляц")),
    ("insulation", ("insulation", "dämmung", "daemmung", "aislamiento", "isolation", "утеплен", "теплоизоляц")),
    ("flooring", ("flooring", "floor covering", "bodenbelag", "revêtement de sol", "напольн")),
    ("piping", ("piping", "pipe", "rohrleitung", "rohr", "tubería", "tuberia", "tuyau", "трубопровод")),
    ("masonry", ("masonry", "brickwork", "brick", "mauerwerk", "mampostería", "mamposteria", "maçonnerie", "кладка")),
    (
        "excavation",
        ("excavation", "earthwork", "erdarbeit", "aushub", "excavación", "excavacion", "terrassement", "выемка"),
    ),
    ("concrete", ("concrete", "beton", "hormigón", "hormigon", "béton", "calcestruzzo", "бетон")),
)

# Acceptable unit dimension(s) per work type. Deliberately permissive where a
# trade legitimately spans dimensions (rebar bars in kg vs mesh in m², steel
# sections per tonne vs per metre, masonry walls in m² or m³) so the rule only
# fires on a genuine unit/scope mismatch, not on a valid measurement choice.
_WORK_TYPE_EXPECTED_DIMS: dict[str, frozenset[str]] = {
    "concrete": frozenset({"volume"}),
    "formwork": frozenset({"area"}),
    "reinforcement": frozenset({"mass", "area"}),
    "structural_steel": frozenset({"mass", "length"}),
    "masonry": frozenset({"area", "volume"}),
    "plaster": frozenset({"area"}),
    "screed": frozenset({"area"}),
    "paint": frozenset({"area"}),
    "tiling": frozenset({"area"}),
    "waterproofing": frozenset({"area"}),
    "insulation": frozenset({"area", "volume"}),
    "excavation": frozenset({"volume", "area"}),
    "piping": frozenset({"length"}),
    "flooring": frozenset({"area"}),
}

# Extra keywords for companion items that are not themselves primary work
# types above (primer, tile adhesive, grout). Merged with the primary
# keywords into one presence lookup so any companion trade can be searched
# for across the BOQ.
_COMPANION_ONLY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "primer": (
        "primer",
        "grundierung",
        "grundanstrich",
        "voranstrich",
        "imprimación",
        "imprimacion",
        "primaire",
        "грунтов",
    ),
    "adhesive": ("adhesive", "thinset", "tile cement", "kleber", "adhesivo", "colle", "клей"),
    "grout": ("grout", "verfugung", "fugenmörtel", "fugenmoertel", "lechada", "jointoiement", "затирк"),
}
_PRESENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    **{name: kws for name, kws in _WORK_TYPES},
    **_COMPANION_ONLY_KEYWORDS,
}

# Companion completeness, distilled from the Assembly library recipes: a
# reinforced-concrete recipe bundles concrete + rebar + formwork, a tiled
# floor bundles tile + adhesive + grout, a painted / steel surface carries a
# primer coat. When a BOQ prices the primary work as a standalone line it
# usually needs the companions as their own lines too, unless the line is
# assembly-priced (then the recipe already contains them - see the skip).
_COMPANION_MAP: dict[str, tuple[str, ...]] = {
    "concrete": ("formwork", "reinforcement"),
    "paint": ("primer",),
    "structural_steel": ("primer",),
    "tiling": ("adhesive", "grout"),
}

# Human-readable labels for companion trades used in messages.
_COMPANION_LABELS: dict[str, str] = {
    "formwork": "formwork",
    "reinforcement": "reinforcement / rebar",
    "primer": "primer",
    "adhesive": "adhesive",
    "grout": "grout",
}

# Small multilingual stop list so token-overlap on descriptions ignores
# connectors and articles when comparing lines for near-duplication.
_DEDUP_STOPWORDS: frozenset[str] = frozenset(
    {
        "and",
        "or",
        "the",
        "of",
        "for",
        "with",
        "to",
        "in",
        "on",
        "at",
        "per",
        "as",
        "by",
        "der",
        "die",
        "das",
        "und",
        "mit",
        "für",
        "fur",
        "den",
        "dem",
        "im",
        "zur",
        "zum",
        "de",
        "la",
        "le",
        "el",
        "los",
        "las",
        "del",
        "con",
        "y",
        "du",
        "des",
        "et",
    }
)


def _detect_work_type(description: str) -> str | None:
    """Classify a BOQ line's primary work type from its description text.

    Iterates :data:`_WORK_TYPES` in priority order (companion trades first)
    and returns the first work type whose any keyword is a substring of the
    lower-cased description, or ``None`` when nothing matches.
    """
    text = (description or "").lower()
    if not text:
        return None
    for name, keywords in _WORK_TYPES:
        if any(kw in text for kw in keywords):
            return name
    return None


def _desc_has(description_lower: str, keywords: tuple[str, ...]) -> bool:
    """True when any of ``keywords`` occurs in an already-lower-cased text."""
    return any(kw in description_lower for kw in keywords)


def _present_work_types(positions: list[dict[str, Any]]) -> set[str]:
    """Set of work / companion trades that appear anywhere in the BOQ.

    Scans every position description once against :data:`_PRESENCE_KEYWORDS`
    so the companion-completeness rule can ask "does this estimate contain a
    formwork line at all?" cheaply.
    """
    present: set[str] = set()
    for pos in positions:
        text = str(pos.get("description") or "").lower()
        if not text:
            continue
        for name, keywords in _PRESENCE_KEYWORDS.items():
            if name not in present and _desc_has(text, keywords):
                present.add(name)
    return present


def _is_assembly_priced(pos: dict[str, Any]) -> bool:
    """True when a position is priced as an assembly (bundles its companions).

    An assembly-linked line already contains formwork / rebar / primer inside
    its recipe, so the companion-completeness rule must not flag it. Detected
    from an ``assembly_id`` (top-level or in metadata), an embedded component
    list, an ``assembly`` source, or a lump-sum unit (which bundles scope).
    """
    if pos.get("assembly_id") or pos.get("components"):
        return True
    meta = _position_metadata(pos)
    if meta.get("assembly_id") or meta.get("assembly") or meta.get("components"):
        return True
    if str(pos.get("source") or "").strip().lower() == "assembly":
        return True
    return _unit_dimension(str(pos.get("unit") or "")) == "lump"


def _dedup_tokens(description: str) -> tuple[frozenset[str], frozenset[str]]:
    """Split a description into ``(word_tokens, numeric_tokens)`` for dedup.

    Word tokens are alphabetic, length >= 2, not stop words. Numeric tokens
    are any token that carries a digit (``"c30"``, ``"37"``, ``"20cm"``) and
    are compared for *equality* between two lines so that "door 90x210" and
    "door 100x210" are never treated as duplicates - a differing dimension is
    a real difference, not a typo. Unicode-aware, so non-Latin scripts tokenize.
    """
    words: set[str] = set()
    nums: set[str] = set()
    for tok in re.findall(r"\w+", (description or "").lower()):
        if any(ch.isdigit() for ch in tok):
            nums.add(tok)
        elif len(tok) >= 2 and tok not in _DEDUP_STOPWORDS:
            words.add(tok)
    return frozenset(words), frozenset(nums)


def _word_jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard overlap of two word-token sets (0.0 when both empty)."""
    if not a and not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _match_field(match: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` off a match result that may be an object or a dict."""
    if isinstance(match, dict):
        return match.get(name, default)
    return getattr(match, name, default)


# Near-duplicate detection tuning.
_NEAR_DUP_JACCARD = 0.8
"""Word-set overlap at or above which two same-unit, same-number lines are
treated as near-duplicates."""
_NEAR_DUP_BLOCK_CAP = 250
"""Largest (unit, numeric-fingerprint) block compared pairwise. Bigger blocks
are skipped to keep the check linear; exact-ordinal duplicates in such blocks
are still caught by ``boq_quality.no_duplicate_ordinals``."""

# Catalogue rate-benchmark tuning. The band is RELATIVE to the matched
# catalogue rate (a multiple / a fraction) rather than an absolute number, so
# it travels across trades, regions and currencies.
_RATE_MIN_MATCH_SCORE = 0.6
_RATE_OUTLIER_HIGH = 3.0
_RATE_OUTLIER_LOW = 1.0 / 3.0
_BENCH_MAX_POSITIONS = 300


class WrongUnitOfMeasure(ValidationRule):
    """Flags a line whose unit dimension does not fit its work type.

    Concrete measured in metres, formwork in cubic metres, pipework in square
    metres: the unit belongs to a different physical dimension than the work
    normally uses. The check is dimension-based (so ``m³`` / ``m3`` / ``cbm``
    are equivalent) and only fires when both the work type is recognised and
    the unit dimension is known, so unclassified lines and lump sums are left
    untouched.
    """

    rule_id = "estimate_audit.wrong_unit"
    name = "Work-Type Unit Sanity"
    standard = "estimate_audit"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Flags BOQ lines whose unit of measure does not match the physical "
        "dimension the described work is normally measured in (e.g. concrete "
        "should be a volume, formwork an area, pipework a length)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            work_type = _detect_work_type(str(pos.get("description") or ""))
            if work_type is None:
                continue
            unit = str(pos.get("unit") or "").strip()
            if not unit:
                continue  # empty unit is owned by boq_quality.empty_unit
            dim = _unit_dimension(unit)
            if dim is None or dim == "lump":
                continue  # unknown or lump-sum units cannot be judged safely
            expected = _WORK_TYPE_EXPECTED_DIMS.get(work_type, frozenset())
            passed = dim in expected
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                expected_units = " / ".join(_DIMENSION_LABEL.get(d, d) for d in sorted(expected))
                message = _audit_text(
                    "estimate_audit.wrong_unit.fail",
                    locale,
                    "Position {ordinal}: {work_type} work is normally measured "
                    "in {expected} but this line uses '{unit}'",
                    ordinal=pos.get("ordinal", "?"),
                    work_type=work_type.replace("_", " "),
                    expected=expected_units,
                    unit=unit,
                )
                suggestion = _audit_text(
                    "estimate_audit.wrong_unit.suggestion",
                    locale,
                    "Check the unit of measure - it looks like it belongs to a different quantity",
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
                        "work_type": work_type,
                        "unit": unit,
                        "unit_dimension": dim,
                        "expected_dimensions": sorted(expected),
                    },
                    suggestion=suggestion,
                )
            )
        return results


class NearDuplicateLine(ValidationRule):
    """Flags two lines that describe the same scope in the same unit.

    Goes beyond ``boq_quality.no_duplicate_ordinals`` (which only catches an
    identical ordinal): here the ordinals differ but the descriptions are a
    fuzzy match under the same unit and the same set of numeric tokens, which
    is the fingerprint of a line entered twice by mistake. Numeric tokens must
    match exactly, so "door 90x210" and "door 100x210" are never conflated.
    """

    rule_id = "estimate_audit.near_duplicate"
    name = "Near-Duplicate Line"
    standard = "estimate_audit"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Detects near-duplicate BOQ lines - same unit, same numeric detail and "
        "a highly similar description under a different ordinal - which usually "
        "means the same scope was entered twice."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        entries: list[tuple[dict[str, Any], frozenset[str], frozenset[str]]] = []
        for pos in _get_leaf_positions(context):
            desc = str(pos.get("description") or "").strip()
            unit = str(pos.get("unit") or "").strip().lower()
            if len(desc) < 4 or not unit:
                continue
            words, nums = _dedup_tokens(desc)
            if len(words) < 2:
                continue  # too little signal to compare without false positives
            entries.append((pos, words, nums))

        if len(entries) < 2:
            return []

        # Block by (unit, numeric fingerprint): only lines sharing both can be
        # duplicates, which keeps the pairwise comparison local and cheap.
        blocks: dict[tuple[str, frozenset[str]], list[int]] = {}
        for idx, (pos, _words, nums) in enumerate(entries):
            key = (str(pos.get("unit") or "").strip().lower(), nums)
            blocks.setdefault(key, []).append(idx)

        partners: dict[int, set[int]] = {}
        for members in blocks.values():
            if len(members) < 2 or len(members) > _NEAR_DUP_BLOCK_CAP:
                continue
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    ia, ib = members[a], members[b]
                    if _word_jaccard(entries[ia][1], entries[ib][1]) >= _NEAR_DUP_JACCARD:
                        partners.setdefault(ia, set()).add(ib)
                        partners.setdefault(ib, set()).add(ia)

        if not partners:
            # Nothing duplicated - one green summary row keeps the dashboard tile.
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
        for idx in sorted(partners):
            pos = entries[idx][0]
            partner_ordinals = [
                str(entries[p][0].get("ordinal") or entries[p][0].get("id") or "?") for p in sorted(partners[idx])
            ]
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=_audit_text(
                        "estimate_audit.near_duplicate.fail",
                        locale,
                        "Position {ordinal} looks like a duplicate of {partners}",
                        ordinal=pos.get("ordinal", "?"),
                        partners=", ".join(partner_ordinals),
                    ),
                    element_ref=pos.get("id"),
                    details={
                        "duplicate_of_ids": [str(entries[p][0].get("id") or "") for p in sorted(partners[idx])],
                        "duplicate_of_ordinals": partner_ordinals,
                    },
                    suggestion=_audit_text(
                        "estimate_audit.near_duplicate.suggestion",
                        locale,
                        "Confirm these are separate scopes, otherwise remove the duplicate line",
                    ),
                )
            )
        return results


class MissingCompanionItem(ValidationRule):
    """Flags a primary work line missing its usual companion items.

    Driven by the shapes of the Assembly library recipes: concrete lines
    normally need formwork and reinforcement lines, tiling needs adhesive and
    grout, painted / steel surfaces need a primer. When the primary work is
    priced as a standalone line and no companion line exists anywhere in the
    BOQ, the companion scope may have been forgotten. Assembly-priced lines
    (which already bundle the companions inside the recipe) are skipped.
    """

    rule_id = "estimate_audit.missing_companion"
    name = "Companion Item Completeness"
    standard = "estimate_audit"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = (
        "Flags primary work lines (concrete, tiling, painting, structural "
        "steel) that have no matching companion line (formwork, rebar, "
        "adhesive, grout, primer) anywhere in the estimate."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        positions = _get_leaf_positions(context)
        if not positions:
            return []
        present = _present_work_types(positions)

        results: list[RuleResult] = []
        affected = False
        for pos in positions:
            work_type = _detect_work_type(str(pos.get("description") or ""))
            if work_type is None or work_type not in _COMPANION_MAP:
                continue
            if _is_assembly_priced(pos):
                continue  # the recipe already contains the companions
            missing = [c for c in _COMPANION_MAP[work_type] if c not in present]
            if not missing:
                continue
            affected = True
            missing_labels = ", ".join(_COMPANION_LABELS.get(c, c) for c in missing)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=_audit_text(
                        "estimate_audit.missing_companion.fail",
                        locale,
                        "Position {ordinal} prices {work_type} but the estimate "
                        "has no {missing} line - check the companion work is not missing",
                        ordinal=pos.get("ordinal", "?"),
                        work_type=work_type.replace("_", " "),
                        missing=missing_labels,
                    ),
                    element_ref=pos.get("id"),
                    details={"work_type": work_type, "missing_companions": missing},
                    suggestion=_audit_text(
                        "estimate_audit.missing_companion.suggestion",
                        locale,
                        "Add the companion line, or price it inside an assembly on this position",
                    ),
                )
            )

        if not affected:
            # Either no primary lines, or every one had its companions.
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


async def _resolve_cwicr_matcher(context: ValidationContext) -> Any:
    """Resolve an async catalogue matcher from the validation context.

    Two supply routes, so the rule is both wired to production and DB-free
    testable:

    * ``metadata['cwicr_matcher']`` - an injected async callable
      ``(query: str, unit: str | None) -> list[match]`` (used by tests and by
      any caller that already holds matches).
    * ``metadata['session']`` - a live :class:`AsyncSession`; we wrap the
      existing ``costs.matcher.match_cwicr_items`` around it, forwarding the
      region from ``metadata['region']`` / ``context.region``.

    Returns ``None`` when neither is present, so the rule skips cleanly.
    """
    meta = getattr(context, "metadata", None) or {}
    if not isinstance(meta, dict):
        return None
    injected = meta.get("cwicr_matcher")
    if callable(injected):
        return injected
    session = meta.get("session")
    if session is None:
        return None
    region = meta.get("region") or context.region

    async def _call(query: str, unit: str | None) -> list[Any]:
        from app.modules.costs.matcher import match_cwicr_items

        return await match_cwicr_items(session, query, unit=unit, top_k=1, region=region)

    return _call


class CatalogueRateOutlier(ValidationRule):
    """Flags a unit rate far from the same work's catalogue rate.

    Instead of a hardcoded per-unit ceiling, this benchmarks each priced line
    against the existing CWICR matcher: it finds the closest catalogue item
    for the line's description and unit, and - only when the match is
    confident, in the SAME currency and the SAME unit dimension - flags a rate
    that is a large multiple of, or a small fraction of, that catalogue rate.
    The band is relative to the catalogue rate, so it works in any currency
    and region. Skips silently when no matcher is supplied or no match is found.
    """

    rule_id = "estimate_audit.rate_outlier"
    name = "Catalogue Rate Outlier"
    standard = "estimate_audit"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "Benchmarks each unit rate against the closest same-currency catalogue "
        "rate via the CWICR matcher and flags rates that are a large multiple "
        "of, or a small fraction of, the catalogue rate."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        matcher = await _resolve_cwicr_matcher(context)
        if matcher is None:
            return []  # no catalogue access wired in - nothing to benchmark against

        results: list[RuleResult] = []
        checked = 0
        for pos in _get_leaf_positions(context):
            if checked >= _BENCH_MAX_POSITIONS:
                break
            desc = str(pos.get("description") or "").strip()
            if len(desc) < 3:
                continue
            rate = _to_number(pos.get("unit_rate"))
            if rate is None or rate is _NOT_A_NUMBER or rate <= 0:  # type: ignore[operator]
                continue
            unit = str(pos.get("unit") or "").strip()
            unit_dim = _unit_dimension(unit)
            pos_currency = _position_currency(pos)

            try:
                matches = await matcher(desc, unit or None)
            except Exception:  # pragma: no cover - defensive; one bad line must not kill the rule
                logger.debug("estimate_audit.rate_outlier: matcher failed for %r", desc, exc_info=True)
                continue
            checked += 1
            if not matches:
                continue  # skip on no match
            best = matches[0]

            score = _num(_match_field(best, "score", 0.0), default=0.0) or 0.0
            if score < _RATE_MIN_MATCH_SCORE:
                continue
            cat_rate = _num(_match_field(best, "unit_rate", 0.0), default=0.0) or 0.0
            if cat_rate <= 0:
                continue
            # Same currency only: never compare a EUR rate to a USD catalogue.
            cat_currency = str(_match_field(best, "currency", "") or "").strip().upper()
            if pos_currency and cat_currency and pos_currency != cat_currency:
                continue
            # Same dimension only: never compare a per-m³ rate to a per-m² one.
            cat_dim = _unit_dimension(str(_match_field(best, "unit", "") or ""))
            if unit_dim and cat_dim and unit_dim != cat_dim:
                continue

            ratio = rate / cat_rate  # type: ignore[operator]
            passed = _RATE_OUTLIER_LOW <= ratio <= _RATE_OUTLIER_HIGH
            if passed:
                message = _ok(locale)
                suggestion = None
            else:
                key = "estimate_audit.rate_outlier.high" if ratio > 1 else "estimate_audit.rate_outlier.low"
                default = (
                    "Position {ordinal}: rate {rate} is {ratio}x the catalogue rate {benchmark} for similar {unit} work"
                    if ratio > 1
                    else "Position {ordinal}: rate {rate} is only {ratio}x the "
                    "catalogue rate {benchmark} for similar {unit} work"
                )
                message = _audit_text(
                    key,
                    locale,
                    default,
                    ordinal=pos.get("ordinal", "?"),
                    rate=_fmt_decimal(float(rate)),  # type: ignore[arg-type]
                    benchmark=_fmt_decimal(float(cat_rate)),
                    ratio=_fmt_decimal(float(ratio)),
                    unit=unit or "-",
                )
                suggestion = _audit_text(
                    "estimate_audit.rate_outlier.suggestion",
                    locale,
                    "Review this rate against the catalogue benchmark",
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
                        "unit_rate": float(rate),  # type: ignore[arg-type]
                        "catalogue_rate": float(cat_rate),
                        "ratio": round(float(ratio), 4),
                        "catalogue_code": str(_match_field(best, "code", "") or ""),
                        "match_score": round(float(score), 4),
                        "currency": pos_currency or cat_currency,
                    },
                    suggestion=suggestion,
                )
            )
        return results


# ── Sheet completeness (drawing index / issue register reconciliation) ───────
#
# These rules read a pre-computed EXPECTED sheet list and the ACTUAL project
# ``Sheet`` rows off ``context.data`` and diff them (documents.sheet_index
# owns the parse + set-diff). One finding row per gap, plus a single green row
# when a facet is clean, mirroring how the estimate-audit rules read.


def _reconcile_from_context(context: ValidationContext) -> Any:
    """Diff the expected index against the actual sheets on ``context.data``.

    The three sheet-completeness rules share one reconciliation. The engine
    hands each rule the same :class:`ValidationContext`, so the result is
    computed once and cached on ``context.metadata`` for the other two rules.
    ``sheet_index`` is imported lazily so the core validation package keeps no
    import-time dependency on the documents module.
    """
    meta = context.metadata if isinstance(context.metadata, dict) else {}
    cached = meta.get("_sc_result")
    if cached is not None:
        return cached

    from app.modules.documents.sheet_index import ExpectedSheet, normalize_sheet_number, reconcile

    data = context.data if isinstance(context.data, dict) else {}
    expected_raw = data.get("expected") or []
    actual = data.get("actual") or []
    expected = [
        ExpectedSheet(
            sheet_number=str(e.get("sheet_number") or ""),
            sheet_number_norm=str(e.get("sheet_number_norm") or normalize_sheet_number(e.get("sheet_number"))),
            sheet_title=e.get("sheet_title"),
            revision=e.get("revision"),
        )
        for e in expected_raw
        if isinstance(e, dict)
    ]
    result = reconcile(expected, actual)
    if isinstance(context.metadata, dict):
        context.metadata["_sc_result"] = result
    return result


class SheetCompletenessMissing(ValidationRule):
    rule_id = "sheet_completeness.missing"
    name = "Sheet in index is missing from the set"
    standard = "sheet_completeness"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every sheet listed in the drawing index must exist in the uploaded set"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        result = _reconcile_from_context(context)
        out: list[RuleResult] = []
        for num in result.missing:
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate("sheet_completeness.missing.fail", locale=locale, sheet=num),
                    element_ref=num,
                    suggestion=translate("sheet_completeness.missing.suggestion", locale=locale),
                )
            )
        if not out:
            # One green summary row keeps the traffic-light dashboard tile.
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                )
            )
        return out


class SheetCompletenessExtra(ValidationRule):
    rule_id = "sheet_completeness.extra"
    name = "Uploaded sheet is not in the index"
    standard = "sheet_completeness"
    severity = Severity.WARNING  # a stray sheet is a flag, not a block
    category = RuleCategory.COMPLETENESS
    description = "Every uploaded sheet should be listed in the drawing index / issue register"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        result = _reconcile_from_context(context)
        out: list[RuleResult] = []
        for num in result.extra:
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate("sheet_completeness.extra.fail", locale=locale, sheet=num),
                    element_ref=num,
                    suggestion=translate("sheet_completeness.extra.suggestion", locale=locale),
                )
            )
        if not out:
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                )
            )
        return out


class SheetRevisionMismatch(ValidationRule):
    rule_id = "sheet_completeness.revision_mismatch"
    name = "Sheet revision differs from the index"
    standard = "sheet_completeness"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A matched sheet should be at the revision the drawing index expects"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        result = _reconcile_from_context(context)
        out: list[RuleResult] = []
        for row in result.rev_mismatch:
            sheet = row.get("sheet_number", "?")
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "sheet_completeness.revision_mismatch.fail",
                        locale=locale,
                        sheet=sheet,
                        expected_rev=row.get("expected_rev", "?"),
                        actual_rev=row.get("actual_rev", "?"),
                    ),
                    element_ref=sheet,
                    details=dict(row),
                    suggestion=translate("sheet_completeness.revision_mismatch.suggestion", locale=locale),
                )
            )
        if not out:
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=_ok(locale),
                )
            )
        return out


# ── Procurement (purchase-order commitment gate) ────────────────────────────
#
# A purchase order is where an estimate becomes committed money: approval
# publishes ``procurement.po.approved`` and finance commits the amount against
# the project budget. Nothing downstream re-derives that amount, so a PO whose
# own arithmetic disagrees with itself commits one number and displays another.
#
# The deterministic checks live in ``app.modules.procurement.validators`` (pure
# Decimal, no ORM) so they are unit-testable without a database; these classes
# are thin translators from a ``Finding`` to a ``RuleResult``. The module is
# imported lazily inside ``validate()`` so this core package never hard-depends
# on a business module at import time -- a disabled procurement module must not
# break rule loading.


def _po_payload(context: ValidationContext) -> dict[str, Any]:
    """Return the purchase-order payload dict from the context (empty if malformed)."""
    data = context.data
    return data if isinstance(data, dict) else {}


class _ProcurementRule(ValidationRule):
    """Shared body: run one pure check and translate its findings.

    Subclasses supply ``rule_id``/``severity``/``category`` and :attr:`check_name`,
    the name of the function in ``procurement.validators`` to run. Every rule
    emits a single passing row when the check is clean, so a green PO produces one
    explicit "checked, fine" line per rule rather than silence.
    """

    standard = "procurement"

    #: Name of the ``procurement.validators`` function this rule delegates to.
    check_name: str = ""

    def _message_key(self, suffix: str) -> str:
        return f"{self.rule_id}.{suffix}"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        payload = _po_payload(context)
        if not payload:
            return []
        from app.modules.procurement import validators as po_checks

        findings = getattr(po_checks, self.check_name)(payload)
        if not findings:
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
                message=translate(self._message_key("fail"), locale=locale, **finding.params),
                element_ref=finding.element_ref,
                details=dict(finding.details),
                suggestion=translate(self._message_key("suggestion"), locale=locale),
            )
            for finding in findings
        ]


class ProcurementPOHasLines(_ProcurementRule):
    """A purchase order must have at least one line before it is approved."""

    rule_id = "procurement.po_has_lines"
    name = "Purchase Order Has Lines"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags a purchase order approved with no line items."
    check_name = "check_has_lines"


class ProcurementPOLineAmount(_ProcurementRule):
    """Each line amount must equal quantity x unit rate."""

    rule_id = "procurement.po_line_amount"
    name = "Purchase Order Line Amount"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a line whose amount does not equal its quantity times its unit rate."
    check_name = "check_line_amount"


class ProcurementPOSubtotalMatchesLines(_ProcurementRule):
    """The subtotal must equal the sum of the line amounts."""

    rule_id = "procurement.po_subtotal_matches_lines"
    name = "Purchase Order Subtotal Matches Lines"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a purchase order whose subtotal does not equal the sum of its lines."
    check_name = "check_subtotal_matches_lines"


class ProcurementPOTotalMatchesSubtotal(_ProcurementRule):
    """The total must equal subtotal plus tax -- the number finance commits."""

    rule_id = "procurement.po_total_matches_subtotal"
    name = "Purchase Order Total Matches Subtotal Plus Tax"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a purchase order whose total does not equal its subtotal plus tax."
    check_name = "check_total_matches_subtotal_plus_tax"


class ProcurementPONoNegativeLine(_ProcurementRule):
    """Quantities must be positive and unit rates must not be negative."""

    rule_id = "procurement.po_no_negative_line"
    name = "Purchase Order Line Signs"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = "Flags a line with a non-positive quantity or a negative unit rate."
    check_name = "check_no_negative_line"


class ProcurementPOCurrencySet(_ProcurementRule):
    """A committed amount must carry a currency."""

    rule_id = "procurement.po_currency_set"
    name = "Purchase Order Currency Set"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags a purchase order approved without a currency code."
    check_name = "check_currency_set"


class ProcurementPOVendorAssigned(_ProcurementRule):
    """An approved commitment must name the party it is committed to."""

    rule_id = "procurement.po_vendor_assigned"
    name = "Purchase Order Vendor Assigned"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags a purchase order approved without a vendor."
    check_name = "check_vendor_assigned"


class ProcurementPORetentionWithinBounds(_ProcurementRule):
    """Retention must be a plausible percentage, not an amount typed as a rate."""

    rule_id = "procurement.po_retention_within_bounds"
    name = "Purchase Order Retention Within Bounds"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = "Flags a retention percentage that is negative or implausibly large."
    check_name = "check_retention_within_bounds"


class ProcurementPODeliveryAfterIssue(_ProcurementRule):
    """Delivery cannot be scheduled before the order goes out."""

    rule_id = "procurement.po_delivery_after_issue"
    name = "Purchase Order Delivery After Issue"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a delivery date earlier than the issue date."
    check_name = "check_delivery_not_before_issue"


class ProcurementPOLineCostCoded(_ProcurementRule):
    """A line without a cost code lands in the total and nowhere in the breakdown."""

    rule_id = "procurement.po_line_cost_coded"
    name = "Purchase Order Line Cost Coded"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a line with no WBS, cost category or cost-line link."
    check_name = "check_line_cost_coded"


# ── Subcontract agreements (activation gate) ────────────────────────────────
#
# An agreement leaving ``draft`` for ``active`` is the moment a subcontractor
# may start work, claim against the scope and accrue retention. The schedule of
# values divides by its total value and retention multiplies by its percentage,
# so an agreement that goes live incoherent produces reports nobody can
# reconcile weeks later, inside a payment claim.
#
# Deterministic checks live in ``app.modules.subcontractors.validators`` (pure
# Decimal and date, no ORM); these classes translate a ``Finding`` into a
# ``RuleResult``. The module is imported lazily inside ``validate()`` so this
# core package never hard-depends on a business module at import time.


class _SubcontractRule(ValidationRule):
    """Shared body: run one pure check and translate its findings.

    Subclasses supply ``rule_id``/``severity``/``category`` and
    :attr:`check_name`, the name of the function in ``subcontractors.validators``
    to run. A clean check emits one passing row, so a green agreement produces
    an explicit "checked, fine" line per rule rather than silence.
    """

    standard = "subcontract"

    #: Name of the ``subcontractors.validators`` function this rule delegates to.
    check_name: str = ""

    def _message_key(self, suffix: str) -> str:
        return f"{self.rule_id}.{suffix}"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        payload = context.data if isinstance(context.data, dict) else {}
        if not payload:
            return []
        from app.modules.subcontractors import validators as sub_checks

        findings = getattr(sub_checks, self.check_name)(payload)
        if not findings:
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
                message=translate(self._message_key("fail"), locale=locale, **finding.params),
                element_ref=finding.element_ref,
                details=dict(finding.details),
                suggestion=translate(self._message_key("suggestion"), locale=locale),
            )
            for finding in findings
        ]


class SubcontractAgreementHasScope(_SubcontractRule):
    """An agreement going live must break its scope into work packages."""

    rule_id = "subcontract.agreement_has_scope"
    name = "Subcontract Agreement Has Scope"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags an agreement activated with no work packages to claim against."
    check_name = "check_has_scope"


class SubcontractPackageScopeDescribed(_SubcontractRule):
    """Each work package should say what the work actually is."""

    rule_id = "subcontract.package_scope_described"
    name = "Subcontract Work Package Scope Described"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a work package with a name but no scope description."
    check_name = "check_package_scope_described"


class SubcontractAgreementValuePositive(_SubcontractRule):
    """The contract value must be greater than zero."""

    rule_id = "subcontract.agreement_value_positive"
    name = "Subcontract Agreement Value Positive"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = "Flags an agreement activated with a zero or negative contract value."
    check_name = "check_value_positive"


class SubcontractPackagesWithinValue(_SubcontractRule):
    """The work packages must not be worth more than the contract itself."""

    rule_id = "subcontract.packages_within_value"
    name = "Subcontract Packages Within Contract Value"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags work packages whose planned values exceed the agreement total."
    check_name = "check_packages_within_value"


class SubcontractAgreementDatesOrdered(_SubcontractRule):
    """The contract cannot end before it starts."""

    rule_id = "subcontract.agreement_dates_ordered"
    name = "Subcontract Agreement Dates Ordered"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags an agreement whose end date is earlier than its start date."
    check_name = "check_dates_ordered"


class SubcontractAgreementCurrencySet(_SubcontractRule):
    """A live agreement must carry a currency."""

    rule_id = "subcontract.agreement_currency_set"
    name = "Subcontract Agreement Currency Set"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags an agreement activated without a currency."
    check_name = "check_currency_set"


class SubcontractRetentionWithinBounds(_SubcontractRule):
    """Retention must be a plausible percentage, not an amount typed as a rate."""

    rule_id = "subcontract.retention_within_bounds"
    name = "Subcontract Retention Within Bounds"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = "Flags a retention percentage that is negative or implausibly large."
    check_name = "check_retention_within_bounds"


class SubcontractInsuranceValidAtStart(_SubcontractRule):
    """The subcontractor's insurance must still be valid when work starts."""

    rule_id = "subcontract.insurance_valid_at_start"
    name = "Subcontractor Insurance Valid At Start"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Flags an agreement activated for a subcontractor whose insurance has lapsed."
    check_name = "check_insurance_valid_at_start"


# ── Submittals (submission gate) ────────────────────────────────────────────
#
# Submission is where a submittal stops being a draft and starts consuming
# somebody else's review time, and it is the last point at which the person who
# filed it is still looking at it. Everything afterwards is chasing: the
# register sorts by spec section, the overdue view counts against the required
# date, ball-in-court hands the item to the reviewer. Filed without those, the
# submittal is invisible to every mechanism meant to move it.


class _SubmittalRule(ValidationRule):
    """Shared body: run one pure check in ``submittals.validators``."""

    standard = "submittal"

    #: Name of the ``submittals.validators`` function this rule delegates to.
    check_name: str = ""

    def _message_key(self, suffix: str) -> str:
        return f"{self.rule_id}.{suffix}"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        payload = context.data if isinstance(context.data, dict) else {}
        if not payload:
            return []
        from app.modules.submittals import validators as sub_checks

        findings = getattr(sub_checks, self.check_name)(payload)
        if not findings:
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
                message=translate(self._message_key("fail"), locale=locale, **finding.params),
                element_ref=finding.element_ref,
                details=dict(finding.details),
                suggestion=translate(self._message_key("suggestion"), locale=locale),
            )
            for finding in findings
        ]


class SubmittalReviewerAssigned(_SubmittalRule):
    """A submitted submittal must name the reviewer it is waiting on."""

    rule_id = "submittal.reviewer_assigned"
    name = "Submittal Reviewer Assigned"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags a submittal submitted with no reviewer, so it lands in nobody's court."
    check_name = "check_reviewer_assigned"


class SubmittalRequiredDatePresent(_SubmittalRule):
    """A submitted submittal must carry the date the review is needed by."""

    rule_id = "submittal.required_date_present"
    name = "Submittal Required Date Present"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags a submittal with no required date, which can never be reported late."
    check_name = "check_required_date_present"


class SubmittalRequiredDateAfterSubmitted(_SubmittalRule):
    """The review cannot be due before the submittal was filed."""

    rule_id = "submittal.required_date_after_submitted"
    name = "Submittal Required Date After Submitted"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a submittal whose required date precedes its submission date."
    check_name = "check_required_date_after_submitted"


class SubmittalReviewWindowSufficient(_SubmittalRule):
    """The reviewer needs a workable window, not a nominal one."""

    rule_id = "submittal.review_window_sufficient"
    name = "Submittal Review Window Sufficient"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Flags a review window shorter than the customary ten working days."
    check_name = "check_review_window_sufficient"


class SubmittalSpecSectionPresent(_SubmittalRule):
    """A submittal should say which part of the specification it answers."""

    rule_id = "submittal.spec_section_present"
    name = "Submittal Spec Section Present"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a submittal with no spec section, which the register cannot file."
    check_name = "check_spec_section_present"


class SubmittalApproverDistinctFromReviewer(_SubmittalRule):
    """Review and approval should not be the same person."""

    rule_id = "submittal.approver_distinct_from_reviewer"
    name = "Submittal Approver Distinct From Reviewer"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags one person holding both the review and the approval role."
    check_name = "check_approver_distinct_from_reviewer"


class SubmittalLinkedScopePresent(_SubmittalRule):
    """A submittal should point at the scope it belongs to."""

    rule_id = "submittal.linked_scope_present"
    name = "Submittal Linked Scope Present"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a submittal linked to no BOQ item, so it never rolls up to a package."
    check_name = "check_linked_scope_present"


# ── RFQ bidding (publish and award gates) ───────────────────────────────────
#
# Two moments that cannot be taken back, so two rule sets. ``rfq_issue`` asks
# whether a vendor can bid at all, including whether the deadline is still in
# the future. ``rfq_award`` asks whether the comparison that picked a winner
# compared like with like; the deadline-in-the-future check is deliberately
# absent there, because by award time the deadline has passed on purpose.


class _RFQRule(ValidationRule):
    """Shared body: run one pure check in ``rfq_bidding.validators``."""

    standard = "rfq"

    #: Name of the ``rfq_bidding.validators`` function this rule delegates to.
    check_name: str = ""

    def _message_key(self, suffix: str) -> str:
        return f"{self.rule_id}.{suffix}"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        payload = context.data if isinstance(context.data, dict) else {}
        if not payload:
            return []
        from app.modules.rfq_bidding import validators as rfq_checks

        findings = getattr(rfq_checks, self.check_name)(payload)
        if not findings:
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
                message=translate(self._message_key("fail"), locale=locale, **finding.params),
                element_ref=finding.element_ref,
                details=dict(finding.details),
                suggestion=translate(self._message_key("suggestion"), locale=locale),
            )
            for finding in findings
        ]


class RFQScopeDescribed(_RFQRule):
    """An RFQ must say what is being priced."""

    rule_id = "rfq.scope_described"
    name = "RFQ Scope Described"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags an RFQ with no scope of work and no description."
    check_name = "check_scope_described"


class RFQDeadlinePresent(_RFQRule):
    """A published RFQ must state when bids close."""

    rule_id = "rfq.deadline_present"
    name = "RFQ Deadline Present"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags an RFQ published without a submission deadline."
    check_name = "check_deadline_present"


class RFQDeadlineParseable(_RFQRule):
    """The deadline must be a date the system can actually read."""

    rule_id = "rfq.deadline_parseable"
    name = "RFQ Deadline Parseable"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Flags a malformed deadline, which makes every bid submission fail."
    check_name = "check_deadline_parseable"


class RFQDeadlineInFuture(_RFQRule):
    """Bids must still be open at the moment the RFQ goes out."""

    rule_id = "rfq.deadline_in_future"
    name = "RFQ Deadline In Future"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags an RFQ published with a deadline that has already passed."
    check_name = "check_deadline_in_future"


class RFQHasRecipients(_RFQRule):
    """A published RFQ must be addressed to somebody."""

    rule_id = "rfq.has_recipients"
    name = "RFQ Has Recipients"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags an RFQ published to an empty recipient list."
    check_name = "check_has_recipients"


class RFQCurrencySet(_RFQRule):
    """The RFQ must state the currency bids are to be priced in."""

    rule_id = "rfq.currency_set"
    name = "RFQ Currency Set"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags an RFQ with no currency, so bids cannot be ranked against each other."
    check_name = "check_currency_set"


class RFQBidCurrencyMatches(_RFQRule):
    """Every bid must be priced in the RFQ's currency."""

    rule_id = "rfq.bid_currency_matches"
    name = "RFQ Bid Currency Matches"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a bid priced in a currency other than the RFQ's."
    check_name = "check_bid_currency_matches"


class RFQBidAmountsParseable(_RFQRule):
    """Every bid amount must be a number."""

    rule_id = "rfq.bid_amounts_parseable"
    name = "RFQ Bid Amounts Parseable"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Flags a bid whose amount is not a positive number and cannot be ranked."
    check_name = "check_bid_amounts_parseable"


class RFQBidsStillValid(_RFQRule):
    """A bid should still be inside its validity period when it is awarded."""

    rule_id = "rfq.bids_still_valid"
    name = "RFQ Bids Still Valid"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Flags a bid awarded after its own validity period has expired."
    check_name = "check_bids_still_valid"


class RFQAwardHasCompetition(_RFQRule):
    """An award should rest on a field of bids, not on one."""

    rule_id = "rfq.award_has_competition"
    name = "RFQ Award Has Competition"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags an award made against fewer than three bids."
    check_name = "check_award_has_competition"


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
        (ResourceSplitMismatch(), None),
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
        (NRMBaseDateDeclared(), None),
        (NRMCostPlanStageDeclared(), None),
        (NRMContractorCostsPresent(), None),
        (NRMRiskAllowancePresent(), None),
        # UK statutory (Construction Act, CDM 2015, Building Safety Act)
        (UKContractFormDeclared(), None),
        (UKPaymentRegimeDeclared(), None),
        (UKRetentionDeclared(), None),
        (UKCDMDutyHoldersDeclared(), None),
        (UKHigherRiskBuildingRegime(), None),
        (UKVATTreatmentDeclared(), None),
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
        (GESNResourceBreakdown(), None),
        (GESNLabourHoursPresent(), None),
        (GESNPriceLevelDeclared(), None),
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
        # Hungary (magasepitesi and infrastructure item orders)
        (HungarianItemCodeRequired(), None),
        (HungarianChapterRecognised(), None),
        (HungarianMaterialFeeSplit(), None),
        (HungarianItemNumberUnique(), None),
        # Birim Fiyat (Turkey)
        (BirimFiyatCodeRequired(), None),
        (BirimFiyatValidPoz(), None),
        # Sekisan (Japan)
        (SekisanCodeRequired(), None),
        (SekisanMetricUnits(), None),
        # BC3 / FIEBDC-3 (Spain + LATAM)
        (BC3CodeRequired(), None),
        (BC3ValidCode(), None),
        # Mexico (APU, IVA, retenciones, CFDI)
        (APUCompletenessRule(), None),
        (IVARateValidityRule(), None),
        (SubcontractRetencionRule(), None),
        (CFDIIssuerDataRule(), None),
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
        # Registered into ai_estimator as well as its own standard. The
        # ai_takeoff set has no caller anywhere in the backend, so a rule that
        # lives only there never runs; ai_estimator is the path that prices
        # confirmed quantities and therefore the one that owes the user an
        # account of the quantities it left out.
        # Both sets that actually price a project: boq_quality is the universal
        # default every BOQ validation passes, ai_estimator is the estimate run.
        # Filed under its own "ai_takeoff" standard the rule would never run,
        # because no caller validates against that set.
        (TakeoffUnreviewedProposalsRule(), ["boq_quality", "ai_estimator"]),
        # Field Time (cost-coded, signed labour + plant timesheets)
        (FieldTimeHoursPerDayMax(), None),
        (FieldTimeLineComplete(), None),
        (FieldTimeCostCodeResolves(), None),
        (FieldTimeDayworkNeedsVariation(), None),
        (FieldTimePlantNeedsEquipment(), None),
        (FieldTimeApprovedImmutable(), None),
        (FieldTimeOfflineClockPlausible(), None),
        (FieldTimeOfflineSyncDelay(), None),
        # Estimate Audit (curated cross-checks: wrong unit, near-duplicate,
        # missing companion, catalogue-benchmarked rate outlier)
        (WrongUnitOfMeasure(), ["estimate_audit"]),
        (NearDuplicateLine(), ["estimate_audit"]),
        (MissingCompanionItem(), ["estimate_audit"]),
        (CatalogueRateOutlier(), ["estimate_audit"]),
        # Procurement (purchase-order commitment gate)
        # Registered into the "procurement" set, which ProcurementService._validate
        # passes explicitly on approve and on the read-only validate endpoint. A
        # set nobody passes is a set that never runs (the ai_takeoff lesson), so
        # the reachability of this one is pinned by a test, not by convention.
        (ProcurementPOHasLines(), ["procurement"]),
        (ProcurementPOLineAmount(), ["procurement"]),
        (ProcurementPOSubtotalMatchesLines(), ["procurement"]),
        (ProcurementPOTotalMatchesSubtotal(), ["procurement"]),
        (ProcurementPONoNegativeLine(), ["procurement"]),
        (ProcurementPOCurrencySet(), ["procurement"]),
        (ProcurementPOVendorAssigned(), ["procurement"]),
        (ProcurementPORetentionWithinBounds(), ["procurement"]),
        (ProcurementPODeliveryAfterIssue(), ["procurement"]),
        (ProcurementPOLineCostCoded(), ["procurement"]),
        # Subcontract agreements (activation gate)
        # Registered into the "subcontract" set, which
        # SubcontractorService._validate_agreement passes on activation and on
        # the read-only validate endpoint.
        (SubcontractAgreementHasScope(), ["subcontract"]),
        (SubcontractPackageScopeDescribed(), ["subcontract"]),
        (SubcontractAgreementValuePositive(), ["subcontract"]),
        (SubcontractPackagesWithinValue(), ["subcontract"]),
        (SubcontractAgreementDatesOrdered(), ["subcontract"]),
        (SubcontractAgreementCurrencySet(), ["subcontract"]),
        (SubcontractRetentionWithinBounds(), ["subcontract"]),
        (SubcontractInsuranceValidAtStart(), ["subcontract"]),
        # Submittals (submission gate)
        # Registered into the "submittal" set, which
        # SubmittalService._validate_submittal passes on submit and on the
        # read-only validate endpoint.
        (SubmittalReviewerAssigned(), ["submittal"]),
        (SubmittalRequiredDatePresent(), ["submittal"]),
        (SubmittalRequiredDateAfterSubmitted(), ["submittal"]),
        (SubmittalReviewWindowSufficient(), ["submittal"]),
        (SubmittalSpecSectionPresent(), ["submittal"]),
        (SubmittalApproverDistinctFromReviewer(), ["submittal"]),
        (SubmittalLinkedScopePresent(), ["submittal"]),
        # RFQ bidding (publish and award gates)
        # Two sets rather than one set plus an operation flag: the deadline
        # must be in the future when the RFQ is published and must be in the
        # past by the time it is awarded, so one set cannot hold both without a
        # rule that silently no-ops. Both sets are passed by
        # RFQBiddingService, issue_rfq and award_bid respectively.
        (RFQScopeDescribed(), ["rfq_issue", "rfq_award"]),
        (RFQCurrencySet(), ["rfq_issue", "rfq_award"]),
        (RFQDeadlineParseable(), ["rfq_issue", "rfq_award"]),
        (RFQDeadlinePresent(), ["rfq_issue"]),
        (RFQDeadlineInFuture(), ["rfq_issue"]),
        (RFQHasRecipients(), ["rfq_issue"]),
        (RFQBidCurrencyMatches(), ["rfq_award"]),
        (RFQBidAmountsParseable(), ["rfq_award"]),
        (RFQBidsStillValid(), ["rfq_award"]),
        (RFQAwardHasCompetition(), ["rfq_award"]),
        # Sheet completeness (drawing index / issue register reconciliation)
        (SheetCompletenessMissing(), ["sheet_completeness"]),
        (SheetCompletenessExtra(), ["sheet_completeness"]),
        (SheetRevisionMismatch(), ["sheet_completeness"]),
    ]

    for rule, sets in rules:
        rule_registry.register(rule, sets)

    logger.info(
        "Registered %d built-in validation rules across %d rule sets",
        len(rules),
        len(rule_registry.list_rule_sets()),
    )
