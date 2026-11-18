# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``norm_base`` and ``public_funding`` rule sets: norm codes, grades, caps and price evidence.

Both sets are neutral. Every value they compare against comes from the pack
that covers the project's country (:mod:`app.core.norm_bases`); with no such
pack the rules return nothing, so switching the sets on elsewhere is harmless.

``norm_base``:

* ``norm_base.code_present`` (warning) - a leaf line cites a norm code.
* ``norm_base.code_shape`` (warning) - the code has the shape the base
  prescribes. A warning, not an error: the shape is documented secondary
  literature, and a company may cite a norm the pattern does not know yet.
* ``norm_base.legacy_prefix`` (warning) - the code uses a retired prefix whose
  current form the pack maps; the finding names the current code.
* ``norm_base.resource_breakdown`` (warning) - a line citing a norm carries
  labour hours with an average grade.
* ``norm_base.grade_range`` (error) - the grade is on the pack's scale.

``public_funding`` (reads the project's ``estimate_pricing`` settings):

* ``public_funding.markup_cap`` (error) - a capped markup stays under the cap
  of the project's funding class.
* ``public_funding.investor_exact`` (warning) - a client's estimate on that
  funding uses exactly the capped percentage.
* ``public_funding.material_price_evidence`` (warning) - each material carries
  the number of supplier offers, or a price analysis, the class requires.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core import norm_bases
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.rules import _get_leaf_positions, _get_locale, _ok, _position_metadata

NORM_BASE_RULE_SET = "norm_base"
PUBLIC_FUNDING_RULE_SET = "public_funding"

_LABOUR_TYPES = frozenset({"labor", "labour"})
_MATERIAL_TYPES = frozenset({"material", "materials"})


def _record(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    record = data.get("project_record") if isinstance(data, dict) else None
    return record if isinstance(record, dict) else {}


def _country(context: ValidationContext) -> str | None:
    return _record(context).get("country_code") or None


def _settings(context: ValidationContext) -> dict[str, Any]:
    settings = _record(context).get("estimate_pricing")
    return settings if isinstance(settings, dict) else {}


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _resources(pos: dict[str, Any], base_key: str) -> list[dict[str, Any]]:
    """Resource rows of a line, namespaced under the base key first, then bare."""
    meta = _position_metadata(pos)
    block = meta.get(base_key)
    raw = block.get("resources") if isinstance(block, dict) and "resources" in block else meta.get("resources")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _kind(row: dict[str, Any]) -> str:
    return str(row.get("type") or "").strip().lower()


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    ref: Any,
    details: dict[str, Any] | None = None,
    suggestion: str | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=str(ref) if ref is not None else None,
        details=details or {},
        suggestion=suggestion,
    )


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f")


# ── norm_base ───────────────────────────────────────────────────────────────


class _NormBaseRule(ValidationRule):
    standard = NORM_BASE_RULE_SET
    category = RuleCategory.COMPLIANCE

    def _bases(self, context: ValidationContext) -> list[norm_bases.NormBase]:
        return norm_bases.norm_bases_for(_country(context))


class NormCodePresent(_NormBaseRule):
    rule_id = "norm_base.code_present"
    name = "Norm Code Present"
    severity = Severity.WARNING
    description = "A norm-based estimate cites a norm code on every line"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bases = self._bases(context)
        if not bases:
            return []
        locale = _get_locale(context)
        base = bases[0]
        results = []
        for pos in _get_leaf_positions(context):
            passed = any(b.code_of(pos) for b in bases)
            results.append(
                _result(
                    self,
                    passed,
                    _ok(locale)
                    if passed
                    else translate(
                        "norm_base.code_present.fail",
                        locale=locale,
                        ordinal=pos.get("ordinal", "?"),
                        base=base.name,
                    ),
                    pos.get("id"),
                    {"base": base.key},
                    None
                    if passed
                    else translate(
                        "norm_base.code_present.suggestion", locale=locale, classification=base.classification_key
                    ),
                )
            )
        return results


class NormCodeShape(_NormBaseRule):
    rule_id = "norm_base.code_shape"
    name = "Norm Code Shape"
    severity = Severity.WARNING
    description = "A cited norm code has the shape its norm base prescribes"
    _status = "shape"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results = []
        for base in self._bases(context):
            for pos in _get_leaf_positions(context):
                code = base.code_of(pos)
                if not code:
                    continue
                check = base.check(code)
                failed = check.status == self._status
                results.append(
                    _result(
                        self,
                        not failed,
                        self._message(base, check, pos, locale) if failed else _ok(locale),
                        pos.get("id"),
                        {"code": check.code, "status": check.status, "suggested": check.suggested},
                    )
                )
        return results

    def _message(self, base: norm_bases.NormBase, check: norm_bases.CodeCheck, pos: dict, locale: str) -> str:
        return translate(
            "norm_base.code_shape.fail",
            locale=locale,
            code=check.code,
            ordinal=pos.get("ordinal", "?"),
            base=base.name,
            example=base.code_example,
        )


class NormLegacyPrefix(NormCodeShape):
    rule_id = "norm_base.legacy_prefix"
    name = "Norm Code Uses a Retired Prefix"
    description = "A code with a retired prefix is rewritten to its current form"
    _status = "legacy"

    def _message(self, base: norm_bases.NormBase, check: norm_bases.CodeCheck, pos: dict, locale: str) -> str:
        return translate(
            "norm_base.legacy_prefix.fail",
            locale=locale,
            code=check.code,
            ordinal=pos.get("ordinal", "?"),
            old=check.old_prefix,
            new=check.suggested,
        )


class NormResourceBreakdown(_NormBaseRule):
    rule_id = "norm_base.resource_breakdown"
    name = "Norm Line Has Graded Labour"
    severity = Severity.WARNING
    description = "A line citing a norm carries labour hours and the norm's average grade"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results = []
        for base in self._bases(context):
            for pos in _get_leaf_positions(context):
                code = base.code_of(pos)
                if not code:
                    continue
                labour = [
                    r
                    for r in _resources(pos, base.key)
                    if _kind(r) in _LABOUR_TYPES or _kind(r) == base.labour_resource_type
                ]
                passed = bool(labour) and all(
                    (_dec(r.get("quantity")) or 0) > 0 and _dec(r.get(base.grade_field)) is not None for r in labour
                )
                results.append(
                    _result(
                        self,
                        passed,
                        _ok(locale)
                        if passed
                        else translate(
                            "norm_base.resource_breakdown.fail",
                            locale=locale,
                            code=code,
                            ordinal=pos.get("ordinal", "?"),
                        ),
                        pos.get("id"),
                        {"code": code, "labour_rows": len(labour)},
                        None if passed else translate("norm_base.resource_breakdown.suggestion", locale=locale),
                    )
                )
        return results


class NormLabourGradeRange(_NormBaseRule):
    rule_id = "norm_base.grade_range"
    name = "Labour Grade on the Scale"
    severity = Severity.ERROR
    description = "An average labour grade lies on the grade scale the pack declares"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pricing = norm_bases.estimate_pricing_for(_country(context))
        grading = pricing.grading if pricing else None
        bases = self._bases(context)
        if grading is None:
            return []
        locale = _get_locale(context)
        grade_field = bases[0].grade_field if bases else "grade"
        base_key = bases[0].key if bases else ""
        results = []
        for pos in _get_leaf_positions(context):
            for row in _resources(pos, base_key):
                if _kind(row) not in _LABOUR_TYPES or row.get(grade_field) in (None, ""):
                    continue
                grade = _dec(row.get(grade_field))
                passed = grade is not None and grading.in_range(grade)
                results.append(
                    _result(
                        self,
                        passed,
                        _ok(locale)
                        if passed
                        else translate(
                            "norm_base.grade_range.fail",
                            locale=locale,
                            grade=row.get(grade_field),
                            ordinal=pos.get("ordinal", "?"),
                            min=_fmt(grading.grade_min),
                            max=_fmt(grading.grade_max),
                            step=_fmt(grading.grade_step),
                        ),
                        pos.get("id"),
                        {"grade": str(row.get(grade_field))},
                    )
                )
        return results


# ── public_funding ──────────────────────────────────────────────────────────


def _funding(
    context: ValidationContext,
) -> tuple[norm_bases.FundingClass | None, dict[str, Any]]:
    settings = _settings(context)
    pricing = norm_bases.estimate_pricing_for(_country(context))
    if pricing is None:
        return None, settings
    return pricing.funding_class(settings.get("funding_class")), settings


def _active_markups(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    raw = data.get("markups") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    return [
        m
        for m in raw
        if isinstance(m, dict)
        and m.get("is_active", True)
        and str(m.get("markup_type") or "percentage").lower() == "percentage"
    ]


def _capped(
    context: ValidationContext, fc: norm_bases.FundingClass
) -> Iterator[tuple[dict[str, Any], norm_bases.MarkupCap, Decimal]]:
    for markup in _active_markups(context):
        cap = next((c for c in fc.markup_caps if c.matches(markup)), None)
        percent = _dec(markup.get("percentage"))
        if cap is not None and percent is not None:
            yield markup, cap, percent


class _FundingRule(ValidationRule):
    standard = PUBLIC_FUNDING_RULE_SET
    category = RuleCategory.COMPLIANCE


class PublicMarkupCap(_FundingRule):
    rule_id = "public_funding.markup_cap"
    name = "Markup Within the Funding Cap"
    severity = Severity.ERROR
    description = "Overhead, administrative and profit markups stay under the cap of the project's funding class"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fc, _ = _funding(context)
        if fc is None or not fc.markup_caps:
            return []
        locale = _get_locale(context)
        results = []
        for markup, cap, percent in _capped(context, fc):
            passed = percent <= cap.cap_percent
            results.append(
                _result(
                    self,
                    passed,
                    _ok(locale)
                    if passed
                    else translate(
                        "public_funding.markup_cap.fail",
                        locale=locale,
                        funding=norm_bases.label_in(fc.label, locale),
                        markup=markup.get("name") or norm_bases.label_in(cap.label, locale),
                        percent=_fmt(percent),
                        cap=_fmt(cap.cap_percent),
                        source=fc.source,
                    ),
                    markup.get("id"),
                    {"cap_key": cap.key, "percent": str(percent), "cap": str(cap.cap_percent)},
                    None if passed else translate("public_funding.markup_cap.suggestion", locale=locale),
                )
            )
        return results


class PublicInvestorExact(_FundingRule):
    rule_id = "public_funding.investor_exact"
    name = "Client Estimate at the Funding Cap"
    severity = Severity.WARNING
    description = "A client's estimate on this funding uses exactly the capped percentages"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fc, settings = _funding(context)
        if fc is None or not fc.investor_estimate_at_cap or settings.get("estimate_role") != "investor":
            return []
        locale = _get_locale(context)
        results = []
        for markup, cap, percent in _capped(context, fc):
            passed = percent == cap.cap_percent
            results.append(
                _result(
                    self,
                    passed,
                    _ok(locale)
                    if passed
                    else translate(
                        "public_funding.investor_exact.fail",
                        locale=locale,
                        funding=norm_bases.label_in(fc.label, locale),
                        markup=markup.get("name") or norm_bases.label_in(cap.label, locale),
                        cap=_fmt(cap.cap_percent),
                        source=fc.source,
                    ),
                    markup.get("id"),
                    {"cap_key": cap.key, "percent": str(percent), "cap": str(cap.cap_percent)},
                )
            )
        return results


class PublicMaterialPriceEvidence(_FundingRule):
    rule_id = "public_funding.material_price_evidence"
    name = "Material Price Evidence"
    severity = Severity.WARNING
    description = "Each material priced on this funding carries supplier offers or a price analysis"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fc, _ = _funding(context)
        if fc is None or not fc.min_quotes:
            return []
        locale = _get_locale(context)
        results = []
        for pos in _get_leaf_positions(context):
            for row in _resources(pos, ""):
                if _kind(row) not in _MATERIAL_TYPES:
                    continue
                evidence = row.get("price_evidence") if isinstance(row.get("price_evidence"), dict) else {}
                quotes = [q for q in evidence.get("quotes") or [] if isinstance(q, dict)]
                passed = len(quotes) >= fc.min_quotes or bool(evidence.get("report_ref"))
                material = row.get("code") or row.get("name") or "?"
                results.append(
                    _result(
                        self,
                        passed,
                        _ok(locale)
                        if passed
                        else translate(
                            "public_funding.material_price_evidence.fail",
                            locale=locale,
                            funding=norm_bases.label_in(fc.label, locale),
                            material=material,
                            ordinal=pos.get("ordinal", "?"),
                            count=len(quotes),
                            required=fc.min_quotes,
                        ),
                        pos.get("id"),
                        {"material": material, "quotes": len(quotes), "required": fc.min_quotes},
                        None
                        if passed
                        else translate("public_funding.material_price_evidence.suggestion", locale=locale),
                    )
                )
        return results


NORM_BASE_RULES: tuple[type[ValidationRule], ...] = (
    NormCodePresent,
    NormCodeShape,
    NormLegacyPrefix,
    NormResourceBreakdown,
    NormLabourGradeRange,
    PublicMarkupCap,
    PublicInvestorExact,
    PublicMaterialPriceEvidence,
)

__all__ = ["NORM_BASE_RULES", "NORM_BASE_RULE_SET", "PUBLIC_FUNDING_RULE_SET"]
