# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Change order rule set: each rule has a passing and a failing payload."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.changeorders.validators import (
    CHANGEORDERS_RULE_SET,
    ChangeOrderCurrencyRule,
    ChangeOrderRangesRule,
    ChangeOrderReferencesRule,
    ChangeOrderStatusTransitionRule,
    ChangeOrderTotalMatchesItemsRule,
    register_changeorders_validation_rules,
)


def _co(**kw: object) -> dict:
    base = {
        "id": "co1",
        "project_id": "p1",
        "code": "CO-001",
        "status": "draft",
        "cost_impact": "300.00",
        "currency": "EUR",
        "schedule_impact_days": 5,
    }
    base.update(kw)
    return base


def _item(**kw: object) -> dict:
    base = {
        "id": "i1",
        "original_quantity": "10",
        "new_quantity": "20",
        "original_rate": "10",
        "new_rate": "10",
        "cost_delta": "100",
        "currency": "EUR",
    }
    base.update(kw)
    return base


def _data(co: dict | None = None, items: list[dict] | None = None) -> dict:
    return {
        "change_order": co or _co(),
        "items": items if items is not None else [_item(), _item(id="i2", cost_delta="200", new_quantity="30")],
    }


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (ChangeOrderTotalMatchesItemsRule, _data(), _data(_co(cost_impact="999.00"))),
    (ChangeOrderRangesRule, _data(), _data(items=[_item(new_rate="-1")])),
    (ChangeOrderCurrencyRule, _data(), _data(_co(currency=""))),
    (ChangeOrderReferencesRule, _data(), _data(_co(project_id=""))),
    (
        ChangeOrderStatusTransitionRule,
        _data(_co(previous_status="draft", status="submitted")),
        _data(_co(previous_status="draft", status="approved")),
    ),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "money." not in failed[0].message  # translated, not a raw key


async def test_item_delta_must_follow_its_numbers() -> None:
    results = await _run(ChangeOrderTotalMatchesItemsRule(), _data(_co(cost_impact="50"), [_item(cost_delta="50")]))
    assert [r.element_ref for r in results if not r.passed] == ["i1"]


async def test_mixed_item_currency_fails() -> None:
    results = await _run(ChangeOrderCurrencyRule(), _data(items=[_item(currency="USD")]))
    assert not results[0].passed
    assert "EUR" in results[0].message


async def test_zero_money_change_order_needs_no_currency() -> None:
    data = _data(_co(currency="", cost_impact="0"), [_item(cost_delta="0")])
    assert (await _run(ChangeOrderCurrencyRule(), data))[0].passed


async def test_executed_is_terminal_and_rejected_reopens() -> None:
    rule = ChangeOrderStatusTransitionRule()
    assert not (await _run(rule, _data(_co(previous_status="executed", status="draft"))))[0].passed
    assert (await _run(rule, _data(_co(previous_status="rejected", status="draft"))))[0].passed


async def test_message_follows_locale() -> None:
    de = await _run(ChangeOrderReferencesRule(), _data(_co(code="")), locale="de")
    assert "Bezug" in de[0].message


def test_registered_under_rule_set() -> None:
    register_changeorders_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([CHANGEORDERS_RULE_SET])}
    assert "changeorders.status_transition" in ids
    assert len(ids) == 5
