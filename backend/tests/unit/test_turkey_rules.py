# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Turkish statutory rule set.

``turkey`` is the law of one country, kept apart from ``birimfiyat``, which is
a way of numbering and pricing lines. Its first rule reads the one place a
Turkish bill carries KDV, the tax line of its markup stack, and checks the rate
against the rates in force: 20, 10 and 1 percent since 10 July 2023 under
Cumhurbaşkanı Kararı 7346. The rates it replaced, 18 and 8, are the stale
template the rule exists to catch, because a bill copied from a 2022 job prices
every line two points short and nothing else says so.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import TurkishKDVRateInForce


def bill(*markups: dict[str, Any], locale: str = "en") -> ValidationContext:
    """A context shaped like the one the payload builder hands the engine."""
    return ValidationContext(
        data={
            "positions": [{"id": "p1", "ordinal": "1", "classification": {"birimfiyat": "15.150.1006"}}],
            "boq": {},
            "markups": list(markups),
        },
        metadata={"locale": locale},
    )


def tax(percentage: str, **fields: Any) -> dict[str, Any]:
    line = {"name": "KDV", "category": "tax", "percentage": percentage, "markup_type": "percentage"}
    line.update(fields)
    return line


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", ["20", "20.0", "10", "1", "0"])
async def test_a_rate_in_force_passes(rate: str) -> None:
    """Zero passes too: an exempt supply (istisna) carries a zero tax line on purpose."""
    results = await TurkishKDVRateInForce().validate(bill(tax(rate)))
    assert len(results) == 1
    assert results[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", ["18", "8"])
async def test_the_rates_replaced_in_2023_are_named_as_such(rate: str) -> None:
    results = await TurkishKDVRateInForce().validate(bill(tax(rate)))
    assert len(results) == 1
    assert not results[0].passed
    assert rate in results[0].message
    assert "2023" in results[0].message
    assert results[0].details["declared_rate"] == rate


@pytest.mark.asyncio
async def test_a_rate_the_law_never_had_fails() -> None:
    results = await TurkishKDVRateInForce().validate(bill(tax("19")))
    assert not results[0].passed


@pytest.mark.asyncio
async def test_lines_that_are_not_a_percentage_tax_are_not_judged() -> None:
    """Overhead at 25 percent, a fixed-amount tax line and an inactive stale line
    are all silent: the rule judges a rate a bill actually charges."""
    results = await TurkishKDVRateInForce().validate(
        bill(
            {"name": "Müteahhit kârı ve genel giderler", "category": "overhead", "percentage": "25"},
            tax("5000", markup_type="fixed"),
            tax("18", is_active=False),
        )
    )
    assert results == []


@pytest.mark.asyncio
async def test_a_bill_with_no_tax_line_is_not_asked_for_one() -> None:
    assert await TurkishKDVRateInForce().validate(bill()) == []


@pytest.mark.asyncio
async def test_each_tax_line_is_judged_on_its_own() -> None:
    results = await TurkishKDVRateInForce().validate(bill(tax("20"), tax("18", name="KDV eski")))
    assert [r.passed for r in results] == [True, False]


@pytest.mark.asyncio
async def test_the_message_is_translated() -> None:
    results = await TurkishKDVRateInForce().validate(bill(tax("18"), locale="tr"))
    assert "KDV" in results[0].message
    assert results[0].message != (await TurkishKDVRateInForce().validate(bill(tax("18"))))[0].message


def test_the_rule_is_registered_under_the_turkish_rule_set() -> None:
    from app.core.validation.engine import rule_registry
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    assert "turkey.kdv_rate_in_force" in {rule.rule_id for rule in rule_registry.get_rules_for_sets(["turkey"])}
