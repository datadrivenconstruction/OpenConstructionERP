"""The cost-type vocabulary and the split of a position total by its resources."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.cost_types import (
    BUDGET_CATEGORIES,
    COST_TYPES,
    is_budget_category,
    normalize_cost_type,
    split_by_cost_type,
    to_cost_type,
)


def test_vocabulary_keeps_every_stored_category_valid() -> None:
    assert COST_TYPES == ("labor", "material", "equipment", "subcontractor", "other")
    for legacy in ("material", "labor", "equipment", "subcontractor", "overhead", "contingency"):
        assert legacy in BUDGET_CATEGORIES
    assert is_budget_category("Other")
    assert not is_budget_category("machinery")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("machinery", "equipment"),
        ("Machine", "equipment"),
        ("plant", "equipment"),
        ("operator", "labor"),
        ("Labour", "labor"),
        ("materials", "material"),
        ("Nachunternehmer", "subcontractor"),
        ("electricity", "other"),
        ("overhead", None),
        ("", None),
        ("rebar", None),
    ],
)
def test_normalize_maps_resource_spellings(raw: str, expected: str | None) -> None:
    assert normalize_cost_type(raw) == expected


def test_unknown_resource_type_falls_back_to_other() -> None:
    assert to_cost_type("rebar") == "other"
    assert to_cost_type(None) == "other"


def test_mobilization_position_splits_into_types_from_its_resources() -> None:
    # 1.01 Mobilization, 1 lump sum at 1000: crew 10 h x 30, operator 2 h x 50,
    # site cabin 1 x 200, crane 2 h x 100, fencing subcontract 1 x 200.
    resources = [
        {"type": "labor", "quantity": 10, "unit_rate": 30},
        {"type": "operator", "quantity": 2, "unit_rate": 50},
        {"type": "material", "quantity": 1, "unit_rate": 200},
        {"type": "machinery", "quantity": 2, "unit_rate": 100},
        {"type": "subcontractor", "quantity": 1, "unit_rate": 200},
    ]
    shares = split_by_cost_type(Decimal("1000"), resources)
    assert [(s.cost_type, s.amount, s.resource_count) for s in shares] == [
        ("labor", Decimal("400.00"), 2),
        ("material", Decimal("200.00"), 1),
        ("equipment", Decimal("200.00"), 1),
        ("subcontractor", Decimal("200"), 1),
    ]
    assert sum(s.amount for s in shares) == Decimal("1000")


def test_split_follows_shares_when_resources_do_not_add_up_to_the_total() -> None:
    # Rate overridden to 100 while the resources cost 30 per unit: the total is
    # cut by the resource shares and the parts still add up to it exactly.
    resources = [{"type": "labor", "total": "10"}, {"type": "material", "total": "20"}]
    shares = split_by_cost_type(Decimal("100.00"), resources)
    assert [(s.cost_type, s.amount) for s in shares] == [("labor", Decimal("33.33")), ("material", Decimal("66.67"))]


def test_position_without_resources_is_not_split() -> None:
    assert split_by_cost_type(Decimal("500"), []) == []
    assert split_by_cost_type(Decimal("500"), None) == []
    assert split_by_cost_type(Decimal("500"), [{"type": "labor", "quantity": 0, "unit_rate": 40}]) == []


def test_rows_in_another_currency_weigh_in_the_position_currency() -> None:
    # Material priced 100 USD at 0.9 EUR per USD weighs 90 against 90 EUR of labour.
    resources = [
        {"type": "labor", "total": "90", "currency": ""},
        {"type": "material", "total": "100", "currency": "USD"},
        {"type": "equipment", "total": "50", "currency": "GBP"},
    ]
    rates = {"": Decimal("1"), "USD": Decimal("0.9")}
    shares = split_by_cost_type(Decimal("180"), resources, fx_factor=rates.get)
    # GBP has no rate, so the crane is left out rather than weighed at a guess.
    assert [(s.cost_type, s.amount) for s in shares] == [("labor", Decimal("90.00")), ("material", Decimal("90.00"))]
