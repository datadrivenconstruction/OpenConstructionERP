# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue validation rules (rule set ``project_catalogue``).

Rules run over a plain dict context built by the service::

    {
        "project": {"id", "currency"},
        "items": [{"id", "code", "unit", "rate", "currency", "source_type",
                   "source_rate", "current_source_rate", "source_found"}],
    }

A rule only judges what is present, so an empty catalogue passes.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MAX_SANE_AMOUNT, MoneyRule, currency_of, rows, section, to_dec
from app.modules.project_catalogue.catalogue_math import deviation_percent

PROJECT_CATALOGUE_RULE_SET = "project_catalogue"

#: A local rate more than this far from its source is more often a slipped decimal than a negotiated price.
OVERRIDE_WARN_PERCENT = Decimal("50")


class _CatalogueRule(MoneyRule):
    standard = PROJECT_CATALOGUE_RULE_SET
    message_section = "project_catalogue"
    own_message_keys = frozenset(
        {"unit_present", "duplicate_code", "currency_differs", "override_far", "source_changed"}
    )


def _ref(item: dict) -> str:
    return str(item.get("id") or item.get("code") or "")


def _code(item: dict) -> str:
    return str(item.get("code") or "").strip() or "?"


class RateInRangeRule(_CatalogueRule):
    """A project rate is not negative and not a unit slip."""

    rule_id = "project_catalogue.rate_in_range"
    name = "Project rates are in a sane range"
    description = "Each project rate between 0 and 1e12"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for item in rows(context, "items"):
            bad = self.out_of_range(
                context, _ref(item), _code(item), to_dec(item.get("rate")), Decimal("0"), MAX_SANE_AMOUNT
            )
            if bad:
                out.append(bad)
        return out or [self.ok()]


class UnitPresentRule(_CatalogueRule):
    """A rate says what it is priced per."""

    rule_id = "project_catalogue.unit_present"
    name = "Project rates name their unit"
    category = RuleCategory.COMPLETENESS
    description = "A rate without a unit cannot be applied to a measured quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "unit_present", ref=_ref(item), code=_code(item))
            for item in rows(context, "items")
            if not str(item.get("unit") or "").strip()
        ]
        return out or [self.ok()]


class CurrencyStatedRule(_CatalogueRule):
    """A priced rate names its currency."""

    rule_id = "project_catalogue.currency_stated"
    name = "Project rate currency stated"
    category = RuleCategory.COMPLETENESS
    description = "A rate above zero needs a currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "currency_present", ref=_ref(item))
            for item in rows(context, "items")
            if (to_dec(item.get("rate")) or 0) > 0 and not currency_of(item)
        ]
        return out or [self.ok()]


class DuplicateCodeRule(_CatalogueRule):
    """One code means one rate inside a project."""

    rule_id = "project_catalogue.duplicate_code"
    name = "No code used twice in the project catalogue"
    severity = Severity.WARNING
    description = "Two rates under one code make a bill line ambiguous"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        seen: set[str] = set()
        out: list[RuleResult] = []
        for item in rows(context, "items"):
            code = str(item.get("code") or "").strip()
            norm = code.casefold()
            if not norm:
                continue
            if norm in seen:
                out.append(self.fail(context, "duplicate_code", ref=_ref(item), code=code))
            seen.add(norm)
        return out or [self.ok()]


class CurrencyMatchesProjectRule(_CatalogueRule):
    """A rate is in the currency the project is priced in."""

    rule_id = "project_catalogue.currency_matches_project"
    name = "Project rates are in the project currency"
    severity = Severity.WARNING
    description = "A rate in another currency enters the bill unconverted"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        project_currency = currency_of(section(context, "project"))
        if not project_currency:
            return [self.ok()]
        out = [
            self.fail(
                context,
                "currency_differs",
                ref=_ref(item),
                code=_code(item),
                currency=currency_of(item),
                project_currency=project_currency,
            )
            for item in rows(context, "items")
            if currency_of(item) and currency_of(item) != project_currency
        ]
        return out or [self.ok()]


class OverridePlausibleRule(_CatalogueRule):
    """A local rate does not sit implausibly far from the source it was copied from."""

    rule_id = "project_catalogue.override_plausible"
    name = "Local rates stay near their source"
    severity = Severity.WARNING
    description = "A local rate more than 50 % away from its source rate is flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for item in rows(context, "items"):
            dev = deviation_percent(to_dec(item.get("rate")), to_dec(item.get("source_rate")))
            if dev is not None and abs(dev) > OVERRIDE_WARN_PERCENT:
                out.append(
                    self.fail(
                        context,
                        "override_far",
                        ref=_ref(item),
                        code=_code(item),
                        percent=format(dev.normalize(), "f"),
                        source_rate=item.get("source_rate"),
                    )
                )
        return out or [self.ok()]


class SourceCurrentRule(_CatalogueRule):
    """A moved source price is decided on, not left standing unseen."""

    rule_id = "project_catalogue.source_current"
    name = "Source price changes are decided"
    severity = Severity.INFO
    description = "A source rate that changed since the project copied it is reported"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for item in rows(context, "items"):
            if str(item.get("source_type") or "manual") == "manual" or not item.get("source_found", True):
                continue
            old, new = to_dec(item.get("source_rate")), to_dec(item.get("current_source_rate"))
            if old is not None and new is not None and old.compare(new) != 0:
                out.append(
                    self.fail(
                        context,
                        "source_changed",
                        ref=_ref(item),
                        code=_code(item),
                        old=format(old.normalize(), "f"),
                        new=format(new.normalize(), "f"),
                    )
                )
        return out or [self.ok()]


PROJECT_CATALOGUE_RULES = (
    RateInRangeRule,
    UnitPresentRule,
    CurrencyStatedRule,
    DuplicateCodeRule,
    CurrencyMatchesProjectRule,
    OverridePlausibleRule,
    SourceCurrentRule,
)


def register_project_catalogue_validation_rules() -> None:
    """Register the project catalogue rules with the platform rule registry."""
    for rule_class in PROJECT_CATALOGUE_RULES:
        rule_registry.register(rule_class(), [PROJECT_CATALOGUE_RULE_SET])


__all__ = [
    "PROJECT_CATALOGUE_RULES",
    "PROJECT_CATALOGUE_RULE_SET",
    "register_project_catalogue_validation_rules",
]
