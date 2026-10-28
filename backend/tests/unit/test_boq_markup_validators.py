# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the four markup-stack validation rules.

Each rule is exercised twice, on a stack that breaks it and on one that does
not, because a rule that fires on everything and a rule that fires on nothing
are both useless and only the pair of assertions can tell them apart.

Two properties are pinned beyond the individual findings:

* Every rule is a WARNING and none of them rejects. The schema still accepts
  the value a rule flagged, which is the difference between telling an
  estimator something and making them route around the product to get their
  own number in.
* Every rule is actually registered under a rule set the BOQ validation
  endpoint requests, and every message key resolves in all four locales the
  validation bundle ships. A rule registered nowhere and a rule whose message
  falls back to its raw key both look fine in a unit test of the logic alone.

Run (CI):
    cd backend
    python -m pytest tests/unit/test_boq_markup_validators.py -v
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.modules.boq.schemas import MarkupCreate
from app.modules.boq.service import DEFAULT_MARKUP_TEMPLATES
from app.modules.boq.validators import (
    _BOQ_MARKUP_RULES,
    BOQ_MARKUP_RULE_SET,
    MarkupContingencyNotOnProfit,
    MarkupCumulativeBaseIsSettled,
    MarkupOrderIsDeclared,
    MarkupPercentageWithinBand,
)


def _row(
    name: str,
    *,
    category: str = "overhead",
    percentage: str = "10",
    apply_to: str = "direct_cost",
    sort_order: int = 0,
    is_active: bool = True,
    markup_type: str = "percentage",
    scope_position_id: str | None = None,
) -> dict[str, Any]:
    """One markup row in the shape the validation endpoint puts on the payload."""
    return {
        "id": f"markup-{name}",
        "name": name,
        "markup_type": markup_type,
        "category": category,
        "percentage": percentage,
        "fixed_amount": "0",
        "apply_to": apply_to,
        "sort_order": sort_order,
        "is_active": is_active,
        "scope_position_id": scope_position_id,
        "overrides_id": None,
    }


def _context(markups: list[dict[str, Any]]) -> ValidationContext:
    return ValidationContext(data={"positions": [], "markups": markups}, metadata={"locale": "en"})


def _from_template(region: str) -> list[dict[str, Any]]:
    """The shipped default markup set for a region, as validation rows."""
    return [
        _row(
            str(entry["name"]),
            category=str(entry.get("category", "overhead")),
            percentage=str(entry.get("percentage", "0")),
            apply_to=str(entry.get("apply_to", "direct_cost")),
            sort_order=int(entry.get("sort_order", 0)),
            markup_type=str(entry.get("markup_type", "percentage")),
        )
        for entry in DEFAULT_MARKUP_TEMPLATES[region]
    ]


def _ids(results: list[RuleResult]) -> list[str]:
    return [r.rule_id for r in results]


# ── Contingency on profit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contingency_after_profit_on_a_cumulative_base_is_flagged() -> None:
    """The finding names the profit line the contingency is being charged on."""
    stack = [
        _row("Overhead", sort_order=1),
        _row("Profit", category="profit", percentage="8", sort_order=2),
        _row("Contingency", category="contingency", percentage="5", apply_to="cumulative", sort_order=3),
    ]

    results = await MarkupContingencyNotOnProfit().validate(_context(stack))

    assert len(results) == 1
    assert results[0].severity is Severity.WARNING
    assert "Profit" in results[0].message
    assert "Contingency" in results[0].message


@pytest.mark.asyncio
async def test_a_contingency_on_the_direct_cost_is_not_flagged() -> None:
    """The fixed shape passes: the contingency sits on the direct cost."""
    stack = [
        _row("Overhead", sort_order=1),
        _row("Profit", category="profit", percentage="8", sort_order=2),
        _row("Contingency", category="contingency", percentage="5", sort_order=3),
    ]

    assert await MarkupContingencyNotOnProfit().validate(_context(stack)) == []


@pytest.mark.asyncio
async def test_a_contingency_before_the_profit_line_is_not_flagged() -> None:
    """Cumulative is fine when there is no profit in the base yet."""
    stack = [
        _row("Overhead", sort_order=1),
        _row("Contingency", category="contingency", percentage="5", apply_to="cumulative", sort_order=2),
        _row("Profit", category="profit", percentage="8", apply_to="cumulative", sort_order=3),
    ]

    assert await MarkupContingencyNotOnProfit().validate(_context(stack)) == []


@pytest.mark.asyncio
async def test_the_shipped_us_default_passes_this_rule_and_the_uk_one_does_not() -> None:
    """The rule agrees with the fix that put the US contingencies on direct cost.

    The UK set compounds risk after main contractor overheads and profit on
    purpose, which is why this is a warning naming the standard and not an
    error. If this ever inverts, one of the two is wrong and the report says
    which.
    """
    rule = MarkupContingencyNotOnProfit()

    assert await rule.validate(_context(_from_template("US"))) == []
    assert await rule.validate(_context(_from_template("DEFAULT"))) == []
    assert await rule.validate(_context(_from_template("UK"))) != []


# ── Order determinacy ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_lines_claiming_one_place_in_the_order_are_both_flagged() -> None:
    stack = [
        _row("Overhead", sort_order=1),
        _row("Site setup", sort_order=1),
        _row("Profit", category="profit", sort_order=2),
    ]

    results = await MarkupOrderIsDeclared().validate(_context(stack))

    assert len(results) == 2
    assert {r.element_ref for r in results} == {"markup-Overhead", "markup-Site setup"}


@pytest.mark.asyncio
async def test_the_same_order_in_two_different_scopes_is_not_a_clash() -> None:
    """A section exception legitimately sits at the same place as the line it replaces."""
    stack = [
        _row("Overhead", sort_order=1),
        _row("Overhead (fit-out)", sort_order=1, scope_position_id="section-1"),
    ]

    assert await MarkupOrderIsDeclared().validate(_context(stack)) == []


@pytest.mark.asyncio
async def test_an_inactive_line_cannot_clash_with_a_live_one() -> None:
    stack = [_row("Overhead", sort_order=1), _row("Old overhead", sort_order=1, is_active=False)]

    assert await MarkupOrderIsDeclared().validate(_context(stack)) == []


# ── Percentage band ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_misplaced_decimal_point_is_reported() -> None:
    """125 % profit is a typo, and the message says what band it left."""
    stack = [_row("Profit", category="profit", percentage="125", sort_order=1)]

    results = await MarkupPercentageWithinBand().validate(_context(stack))

    assert len(results) == 1
    assert results[0].severity is Severity.WARNING
    assert "125" in results[0].message


@pytest.mark.asyncio
async def test_an_aggressive_but_plausible_margin_is_left_alone() -> None:
    """The band is wide on purpose; it is not an opinion about pricing."""
    stack = [_row("Profit", category="profit", percentage="22", sort_order=1)]

    assert await MarkupPercentageWithinBand().validate(_context(stack)) == []


@pytest.mark.asyncio
async def test_every_shipped_template_is_inside_its_own_bands() -> None:
    """A default the platform ships must never trip its own quality rule."""
    rule = MarkupPercentageWithinBand()
    for region in sorted(DEFAULT_MARKUP_TEMPLATES):
        assert await rule.validate(_context(_from_template(region))) == [], region


def test_the_band_rule_flags_without_the_schema_refusing_the_same_value() -> None:
    """This is the rule's whole design: it reports, it does not reject.

    A percentage the band calls implausible is still accepted by the create
    schema, so the estimator's number goes in and the report says why it looks
    wrong. Tightening the schema to enforce the band would turn the finding
    into the thing people work around.
    """
    accepted = MarkupCreate(name="Profit", category="profit", percentage=95.0)

    assert accepted.percentage == 95.0


# ── Cumulative base ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_cumulative_line_with_nothing_in_front_of_it_is_flagged() -> None:
    stack = [
        _row("VAT", category="tax", percentage="19", apply_to="cumulative", sort_order=1),
        _row("Overhead", sort_order=2),
    ]

    results = await MarkupCumulativeBaseIsSettled().validate(_context(stack))

    assert len(results) == 1
    assert results[0].element_ref == "markup-VAT"


@pytest.mark.asyncio
async def test_a_cumulative_line_after_another_line_is_settled() -> None:
    stack = [
        _row("Overhead", sort_order=1),
        _row("VAT", category="tax", percentage="19", apply_to="cumulative", sort_order=2),
    ]

    assert await MarkupCumulativeBaseIsSettled().validate(_context(stack)) == []


@pytest.mark.asyncio
async def test_every_shipped_template_has_a_settled_cumulative_base() -> None:
    rule = MarkupCumulativeBaseIsSettled()
    for region in sorted(DEFAULT_MARKUP_TEMPLATES):
        assert await rule.validate(_context(_from_template(region))) == [], region


# ── Properties of the set as a whole ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_payload_without_markups_passes_every_rule() -> None:
    """Validating something that has no markup stack must not error."""
    context = ValidationContext(data={"positions": []}, metadata={"locale": "en"})

    for rule in _BOQ_MARKUP_RULES:
        assert await rule.validate(context) == []


def test_no_markup_rule_blocks_a_workflow() -> None:
    """None of them is an ERROR. A rule that rejects is a rule people route around."""
    assert {rule.severity for rule in _BOQ_MARKUP_RULES} == {Severity.WARNING}


def test_the_rules_are_registered_where_the_boq_endpoint_looks_for_them() -> None:
    """A rule registered under a set nobody requests never runs.

    ``boq_quality`` is the universal set every project falls back to, so this
    is the one that makes the rules reachable regardless of region or
    classification standard.
    """
    registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([BOQ_MARKUP_RULE_SET])}

    assert {rule.rule_id for rule in _BOQ_MARKUP_RULES} <= registered


def test_the_rule_ids_are_named_not_numbered() -> None:
    """Findings say what they are about. A numbered code says nothing to a reader."""
    for rule in _BOQ_MARKUP_RULES:
        assert rule.rule_id.startswith("boq.markup.")
        assert not rule.rule_id.split(".")[-1].isdigit()


def test_every_message_and_suggestion_resolves_in_every_bundled_locale() -> None:
    """A message that falls back to its raw key is a hardcoded string by another route."""
    keys = [
        "boq_markup.contingency_not_on_profit",
        "boq_markup.order_is_declared",
        "boq_markup.percentage_within_band",
        "boq_markup.cumulative_base_is_settled",
    ]
    missing: list[str] = []
    for locale in available_locales():
        for key in keys:
            for leaf in ("fail", "suggestion"):
                if not is_key_present(f"{key}.{leaf}", locale):
                    missing.append(f"{locale}:{key}.{leaf}")

    assert missing == [], missing
