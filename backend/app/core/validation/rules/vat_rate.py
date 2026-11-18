# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``vat_rate`` rule set: the bill's tax line carries the country's standard VAT rate.

Neutral. The rate comes from the dated tax seed through
:func:`app.core.vat_construction.default_vat_rate_percent`, for the project's
country on the bill's tax date (today when the bill has none), so no rate lives
here. A country pack switches the set on by listing it.

* ``vat_rate.standard_rate`` (error) - every active tax markup line is at the
  standard rate, unless the bill records its VAT treatment (an exemption or a
  reduced rate somebody chose on purpose), in which case the line passes and
  the finding names the treatment.

A bill without a tax line, or a country the seed has no standard rate for,
gets no finding: the rule cannot know what the rate should be.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, ValidationRule
from app.core.validation.messages import translate
from app.core.validation.rules import _boq_document, _boq_document_metadata, _get_locale, _ok, _uk_answered

VAT_RATE_RULE_SET = "vat_rate"
_TAX_CATEGORY = "tax"


def _percent(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _tax_date(context: ValidationContext) -> date:
    boq = _boq_document(context)
    for key in ("tax_date", "base_date"):
        raw = boq.get(key)
        if raw:
            try:
                return date.fromisoformat(str(raw)[:10])
            except ValueError:
                continue
    return date.today()


def _country(context: ValidationContext) -> str:
    data = context.data
    record = data.get("project_record") if isinstance(data, dict) else None
    return str((record or {}).get("country_code") or "").strip().upper() if isinstance(record, dict) else ""


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f")


class VatStandardRate(ValidationRule):
    rule_id = "vat_rate.standard_rate"
    name = "VAT at the Standard Rate"
    standard = VAT_RATE_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "The bill's tax line carries the country's standard VAT rate unless a treatment is recorded"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from app.core.vat_construction import default_vat_rate_percent

        country = _country(context)
        if not country:
            return []
        on = _tax_date(context)
        rate = default_vat_rate_percent(country, on)
        if rate is None:
            return []
        raw = context.data.get("markups") if isinstance(context.data, dict) else None
        lines = [
            m
            for m in (raw if isinstance(raw, list) else [])
            if isinstance(m, dict)
            and m.get("is_active", True)
            and str(m.get("category") or "").strip().lower() == _TAX_CATEGORY
            and str(m.get("markup_type") or "percentage").lower() == "percentage"
        ]
        treatment = _uk_answered(_boq_document_metadata(context), "vat_treatment", "vat_exemption")
        locale = _get_locale(context)
        results = []
        for markup in lines:
            percent = _percent(markup.get("percentage"))
            if percent is None:
                continue
            passed = percent == rate or treatment is not None
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=_ok(locale)
                    if passed
                    else translate(
                        "vat_rate.standard_rate.fail",
                        locale=locale,
                        markup=markup.get("name") or "VAT",
                        percent=_fmt(percent),
                        rate=_fmt(rate),
                        country=country,
                    ),
                    element_ref=str(markup["id"]) if markup.get("id") is not None else None,
                    details={
                        "percent": str(percent),
                        "rate": str(rate),
                        "country": country,
                        "on": on.isoformat(),
                        "treatment": treatment if isinstance(treatment, str) else None,
                    },
                    suggestion=None if passed else translate("vat_rate.standard_rate.suggestion", locale=locale),
                )
            )
        return results


VAT_RATE_RULES: tuple[type[ValidationRule], ...] = (VatStandardRate,)

__all__ = ["VAT_RATE_RULES", "VAT_RATE_RULE_SET"]
