# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for the markup stack of a bill.

The markup stack is where a bill stops being a list of quantities and becomes
a price. Until now nothing checked it: an estimator could put contingency on
top of profit, leave two lines fighting over the same place in the order, or
type 300 into a percentage box, and the bill would price all of it silently and
export it to a client. These rules make those checkable.

Every rule here is a WARNING, deliberately, and none of them rejects anything.
A rule that rejects is a rule people route around, and the routes around a
markup check are worse than the check: a percentage typed into the wrong box,
a line deactivated to get past a gate and never turned back on. The estimator
is told, in the language they read, on the screen where the number lives, and
they decide. That is the platform's AI-augmented, human-confirmed principle
applied to arithmetic rather than to a model.

The rules:

* ``boq.markup.contingency_not_on_profit`` - a contingency computed on a base
  that already carries the general contractor's profit. The contractor is then
  paid a margin on money set aside for risk that has not happened, which
  inflates every bid by the product of the two rates. Some markets do this on
  purpose (NRM1 places risk allowances after main contractor overheads and
  profit; the Russian summary estimate takes unforeseen costs on the total of
  the preceding chapters) so this is a flag naming the standard, never a
  refusal.
* ``boq.markup.order_is_declared`` - two lines claiming the same place in the
  order. ``sort_order`` decides what compounds onto what, so a tie makes the
  base of every cumulative line after it a matter of which row the database
  returned first.
* ``boq.markup.percentage_within_band`` - a rate far outside what its category
  is ever plausibly worth. Bands are wide on purpose: this catches a decimal
  point in the wrong place, not an aggressive margin.
* ``boq.markup.cumulative_base_is_settled`` - a line that declares it compounds
  on preceding markups while no markup precedes it. It computes on the direct
  cost, which is correct arithmetic under a label that says otherwise, and the
  next person to reorder the stack changes its base without touching it.

There is no forward-reference rule here, and that absence is deliberate. In
this model ``cumulative`` means "every line before me in the order" and names
nothing, so a line cannot reference a later one and a rule saying it must not
would pass on every bill that can exist. The engine that does have referenced
steps, :mod:`app.modules.methodology.cascade`, already refuses forward
references outright with ``CascadeError``. The checkable failure here is the
one above: a base that is not settled.

The rules are pure and database-free. They read plain dicts out of
:class:`~app.core.validation.engine.ValidationContext` under the ``markups``
key, which the BOQ validation endpoints put there, and every user-facing string
resolves through :mod:`app.core.validation.messages`.
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
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, translate
from app.modules.boq.resource_norms import REVIEW_CATEGORIES, UNIT_RATE_KEPT_KEY, untrusted_buildup_reason

logger = logging.getLogger(__name__)

#: The rule set these register under. ``boq_quality`` is the universal set
#: every project falls back to, so a markup check runs whatever standard or
#: region the project declares. A rule registered under a set nobody requests
#: never runs, and a markup stack is not a regional concern.
BOQ_MARKUP_RULE_SET = "boq_quality"

#: Plausible ceilings per markup category, as a share of that line's own base.
#: Wide on purpose - the target is a misplaced decimal point, not a bold bid.
#: A tax line has no ceiling worth guessing (rates are set by law and some
#: jurisdictions run high), so it is checked only for being negative or absurd.
_PERCENTAGE_CEILING: dict[str, Decimal] = {
    "overhead": Decimal("40"),
    "profit": Decimal("30"),
    "contingency": Decimal("30"),
    "insurance": Decimal("15"),
    "bond": Decimal("15"),
    "tax": Decimal("50"),
    "other": Decimal("50"),
}

#: The ceiling for a category nobody listed above.
_DEFAULT_CEILING = Decimal("50")

_CUMULATIVE = ("cumulative", "subtotal")


def _get_markups(context: ValidationContext) -> list[dict[str, Any]]:
    """Pull the markup rows out of the validated payload.

    Returns an empty list when the caller validated something that has no
    markup stack, so every rule below passes vacuously rather than erroring on
    a payload that was never about markups.
    """
    data = context.data
    if isinstance(data, dict):
        markups = data.get("markups")
        if isinstance(markups, list):
            return [m for m in markups if isinstance(m, dict)]
    return []


def _active(markups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Active lines in evaluation order, ties broken the way the engine breaks them."""
    live = [m for m in markups if m.get("is_active", True)]
    return sorted(live, key=lambda m: (_int(m.get("sort_order")), str(m.get("name") or "")))


def _int(value: object) -> int:
    """Coerce a sort order to int; anything unreadable sorts first, like a zero."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _percentage(markup: dict[str, Any]) -> Decimal | None:
    """Read a line's percentage as a Decimal, or None when it is not a number."""
    try:
        return Decimal(str(markup.get("percentage", "0") or "0"))
    except (InvalidOperation, ValueError):
        return None


def _locale(context: ValidationContext) -> str:
    """The caller's locale, defaulting to English exactly like the core rules."""
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        locale = metadata.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return DEFAULT_LOCALE


def _scope(markup: dict[str, Any]) -> str:
    """The scope key of a line: its position id, or empty for bill-wide."""
    return str(markup.get("scope_position_id") or "")


def _ref(markup: dict[str, Any]) -> str | None:
    """Element reference for a finding: the markup id when there is one."""
    value = markup.get("id")
    return str(value) if value else None


# ── Rules ───────────────────────────────────────────────────────────────────


class MarkupContingencyNotOnProfit(ValidationRule):
    """Contingency must not be computed on a base that already carries profit."""

    rule_id = "boq.markup.contingency_not_on_profit"
    name = "Contingency is not charged a profit margin"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        "A cumulative contingency placed after the profit line pays the contractor "
        "a margin on money reserved for risk that has not happened."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Flag each contingency line whose base contains a preceding profit line."""
        locale = _locale(context)
        results: list[RuleResult] = []

        for scope in {_scope(m) for m in _get_markups(context)}:
            ordered = [m for m in _active(_get_markups(context)) if _scope(m) == scope]
            profit_before: list[str] = []
            for markup in ordered:
                cat = str(markup.get("category") or "").lower()
                applies_to = str(markup.get("apply_to") or "direct_cost").lower()
                if cat == "contingency" and applies_to in _CUMULATIVE and profit_before:
                    results.append(
                        RuleResult(
                            rule_id=self.rule_id,
                            rule_name=self.name,
                            severity=self.severity,
                            category=self.category,
                            passed=False,
                            message=translate(
                                "boq_markup.contingency_not_on_profit.fail",
                                locale,
                                markup=str(markup.get("name") or ""),
                                profit=profit_before[-1],
                            ),
                            element_ref=_ref(markup),
                            suggestion=translate("boq_markup.contingency_not_on_profit.suggestion", locale),
                            details={"apply_to": applies_to, "profit_lines": profit_before},
                        )
                    )
                if cat == "profit":
                    profit_before.append(str(markup.get("name") or ""))

        return results


class MarkupOrderIsDeclared(ValidationRule):
    """Every markup line must claim a place in the order that no other claims."""

    rule_id = "boq.markup.order_is_declared"
    name = "Every markup declares its own place in the order"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.STRUCTURE
    description = (
        "Two markup lines sharing a sort_order leave the compounding order to "
        "whichever row the database happened to return first."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Flag every line that shares its sort order with another in the same scope."""
        locale = _locale(context)
        results: list[RuleResult] = []
        seen: dict[tuple[str, int], list[dict[str, Any]]] = {}

        for markup in _active(_get_markups(context)):
            seen.setdefault((_scope(markup), _int(markup.get("sort_order"))), []).append(markup)

        for (_scope_key, order), group in seen.items():
            if len(group) < 2:
                continue
            names = ", ".join(str(m.get("name") or "") for m in group)
            for markup in group:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=translate(
                            "boq_markup.order_is_declared.fail",
                            locale,
                            order=order,
                            markups=names,
                        ),
                        element_ref=_ref(markup),
                        suggestion=translate("boq_markup.order_is_declared.suggestion", locale),
                        details={"sort_order": order, "markups": names},
                    )
                )

        return results


class MarkupPercentageWithinBand(ValidationRule):
    """A percentage far outside its category's plausible band is flagged, not refused."""

    rule_id = "boq.markup.percentage_within_band"
    name = "Markup percentage is inside a plausible band"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "A rate well outside what its category is ever worth is usually a decimal "
        "point in the wrong place. It is reported and never rejected."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Flag each percentage line outside the ceiling for its category."""
        locale = _locale(context)
        results: list[RuleResult] = []

        for markup in _active(_get_markups(context)):
            if str(markup.get("markup_type") or "percentage").lower() != "percentage":
                continue
            pct = _percentage(markup)
            if pct is None:
                continue
            cat = str(markup.get("category") or "other").lower()
            ceiling = _PERCENTAGE_CEILING.get(cat, _DEFAULT_CEILING)
            if 0 <= pct <= ceiling:
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "boq_markup.percentage_within_band.fail",
                        locale,
                        markup=str(markup.get("name") or ""),
                        percentage=f"{pct}",
                        category=cat,
                        ceiling=f"{ceiling}",
                    ),
                    element_ref=_ref(markup),
                    suggestion=translate("boq_markup.percentage_within_band.suggestion", locale),
                    details={"percentage": str(pct), "category": cat, "ceiling": str(ceiling)},
                )
            )

        return results


class MarkupCumulativeBaseIsSettled(ValidationRule):
    """A cumulative line must have something in front of it to compound onto."""

    rule_id = "boq.markup.cumulative_base_is_settled"
    name = "A cumulative markup has a base to compound onto"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "A line declaring it applies to the direct cost plus preceding markups, "
        "with no markup preceding it, computes on the direct cost under a label "
        "that says otherwise."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Flag each cumulative line that is first in its own scope."""
        locale = _locale(context)
        results: list[RuleResult] = []

        for scope in {_scope(m) for m in _get_markups(context)}:
            ordered = [m for m in _active(_get_markups(context)) if _scope(m) == scope]
            for index, markup in enumerate(ordered):
                applies_to = str(markup.get("apply_to") or "direct_cost").lower()
                if applies_to in _CUMULATIVE and index == 0:
                    results.append(
                        RuleResult(
                            rule_id=self.rule_id,
                            rule_name=self.name,
                            severity=self.severity,
                            category=self.category,
                            passed=False,
                            message=translate(
                                "boq_markup.cumulative_base_is_settled.fail",
                                locale,
                                markup=str(markup.get("name") or ""),
                                apply_to=applies_to,
                            ),
                            element_ref=_ref(markup),
                            suggestion=translate("boq_markup.cumulative_base_is_settled.suggestion", locale),
                            details={"apply_to": applies_to},
                        )
                    )

        return results


# ── Resource buildup rules ──────────────────────────────────────────────────


def _leaf_positions(context: ValidationContext) -> list[dict[str, Any]]:
    """Leaf positions out of the payload, sections skipped, like the core rules.

    A row is a section when its ``type`` says so or when another row names it
    as parent. Sections carry no buildup, so a resource rule has nothing to say
    about them and must not error on their empty fields.
    """
    data = context.data
    positions: list[Any] = []
    if isinstance(data, dict):
        positions = data.get("positions") or []
    elif isinstance(data, list):
        positions = data
    rows = [p for p in positions if isinstance(p, dict)]
    parent_ids = {str(p["parent_id"]) for p in rows if p.get("parent_id")}
    return [p for p in rows if (p.get("type") or "position") != "section" and str(p.get("id") or "") not in parent_ids]


def _position_metadata(position: dict[str, Any]) -> dict[str, Any]:
    for key in ("metadata", "metadata_"):
        meta = position.get(key)
        if isinstance(meta, dict):
            return meta
    return {}


class UnitRateNotRederivedFromUntrustedBuildup(ValidationRule):
    """The resource rows cannot price the line, so an edit will not re-derive the rate.

    Fires in two situations, both of which a person has to look at:

    * An edit touched the resources and the BOQ service kept the stored rate
      instead of re-deriving it. The service stamps the position when it does
      that; this is the finding that carries the stamp into the report, with
      the rate it kept.
    * The stored rows would make the service do the same on the next edit.
      That is the same predicate the service uses, so the report and the
      guard never disagree about a position: rows holding whole-position
      quantities, an allowance split holding the position quantity, or a norm
      the catalogue never stated and the estimator assumed.

    The resource split check flags most of these positions too, on the
    arithmetic alone. This finding names the cause and points at the review
    path, which is what the split check cannot do.
    """

    rule_id = "boq.resources.unit_rate_not_rederived"
    name = "Unit rate was not re-derived from an untrusted resource buildup"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "The resource rows of this position cannot price the line, so the stored unit "
        "rate stands and the buildup needs a human look."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """One finding per leaf position whose buildup is stamped or flagged."""
        locale = _locale(context)
        results: list[RuleResult] = []
        for position in _leaf_positions(context):
            meta = _position_metadata(position)
            stamp = meta.get(UNIT_RATE_KEPT_KEY)
            reason: str | None = None
            kept_rate: str | None = None
            if isinstance(stamp, dict):
                reason = str(stamp.get("reason") or "") or None
                kept_rate = str(stamp.get("kept_unit_rate") or "") or None
            if reason is None:
                reason = untrusted_buildup_reason(
                    source=position.get("source"),
                    metadata=meta,
                    quantity=position.get("quantity"),
                    resources=meta.get("resources"),
                )
            if reason is None:
                continue
            ordinal = str(position.get("ordinal") or "?")
            # One message per reason, so each locale can say what the rows are
            # instead of interpolating an English phrase into a translation.
            key = f"boq_resources.unit_rate_not_rederived.{reason}" if reason in REVIEW_CATEGORIES else None
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(key or "boq_resources.unit_rate_not_rederived.fail", locale, ordinal=ordinal),
                    element_ref=str(position.get("id")) if position.get("id") else None,
                    suggestion=translate("boq_resources.unit_rate_not_rederived.suggestion", locale),
                    details={
                        "reason": reason,
                        "kept_unit_rate": kept_rate,
                        "stamped_by_edit": isinstance(stamp, dict),
                    },
                )
            )
        return results


# ── Registration ────────────────────────────────────────────────────────────

_BOQ_MARKUP_RULES: tuple[ValidationRule, ...] = (
    MarkupContingencyNotOnProfit(),
    MarkupOrderIsDeclared(),
    MarkupPercentageWithinBand(),
    MarkupCumulativeBaseIsSettled(),
)

_BOQ_RESOURCE_RULES: tuple[ValidationRule, ...] = (UnitRateNotRederivedFromUntrustedBuildup(),)


def register_boq_markup_rules() -> None:
    """Register the markup rules with the core rule registry.

    Idempotent - the registry overwrites by rule id, so a re-import or a hot
    reload re-registers cleanly. Called at import time below and again from the
    module's ``on_startup`` hook, because the platform has two registration
    routes and a rule that only takes one of them is dormant in the other
    deployment.
    """
    for rule in _BOQ_MARKUP_RULES:
        rule_registry.register(rule, [BOQ_MARKUP_RULE_SET])
    logger.debug("Registered %d boq markup validation rules", len(_BOQ_MARKUP_RULES))


def register_boq_resource_rules() -> None:
    """Register the resource buildup rules under the same universal set."""
    for rule in _BOQ_RESOURCE_RULES:
        rule_registry.register(rule, [BOQ_MARKUP_RULE_SET])
    logger.debug("Registered %d boq resource validation rules", len(_BOQ_RESOURCE_RULES))


register_boq_markup_rules()
register_boq_resource_rules()
