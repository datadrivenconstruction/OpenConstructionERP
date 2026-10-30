# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges arithmetic: exact splits, share totals, instalments, year-end balances."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.service_charges.apportion import (
    allocate,
    check_shares,
    period_amount,
    reconcile,
    unit_budget,
    weights,
)

D = Decimal


def test_allocate_adds_up_to_the_cent() -> None:
    parts = allocate(D("100.00"), [("A", D("1")), ("B", D("1")), ("C", D("1"))])
    assert sum(parts.values()) == D("100.00")
    assert sorted(parts.values()) == [D("33.33"), D("33.33"), D("33.34")]


def test_allocate_by_permille() -> None:
    parts = allocate(D("12000"), [("A", D("250")), ("B", D("333.333")), ("C", D("416.667"))])
    assert sum(parts.values()) == D("12000.00")
    assert parts["A"] == D("3000.00")


def test_allocate_negative_and_empty() -> None:
    assert sum(allocate(D("-10.01"), [("A", D("1")), ("B", D("1"))]).values()) == D("-10.01")
    assert allocate(D("5"), []) == {}


@pytest.mark.parametrize(
    ("method", "shares", "ok"),
    [
        ("permille", ["500", "500"], True),
        ("permille", ["500", "499.999"], False),
        ("custom", ["33.33", "33.33", "33.34"], True),
        ("custom", ["33.33", "33.33", "33.33"], False),
        ("area", ["80.5", "120"], True),
        ("area", ["80.5", "0"], False),
        ("equal", ["0", "0"], True),
        ("permille", ["1001", "-1"], False),
        ("permille", [], False),
    ],
)
def test_check_shares(method: str, shares: list[str], ok: bool) -> None:
    assert check_shares(method, [D(s) for s in shares])[0] is ok


def test_equal_ignores_shares() -> None:
    assert weights("equal", [("A", D("7")), ("B", D("0"))]) == [("A", D("1")), ("B", D("1"))]


def test_unit_budget_and_instalments() -> None:
    keys = {"k1": [("A", D("600")), ("B", D("400"))], "k2": [("A", D("1")), ("B", D("1"))]}
    yearly = unit_budget([(D("1000"), "k1"), (D("101"), "k2")], keys)
    assert yearly == {"A": D("650.50"), "B": D("450.50")}
    parts = [period_amount(yearly["A"], 4, i) for i in range(1, 5)]
    assert sum(parts) == D("650.50")


def test_reconcile_is_exact() -> None:
    keys = {"k1": [("A", D("500")), ("B", D("500"))]}
    out = reconcile(
        {"cleaning": D("1000.01"), "lift": D("50")},
        {"cleaning": "k1"},
        None,
        keys,
        {"A": D("400"), "B": D("600")},
    )
    rows = {r["unit_ref"]: r for r in out["units"]}
    for r in rows.values():
        assert r["balance"] == r["demanded"] - r["actual_share"]
    assert rows["A"]["actual_share"] + rows["B"]["actual_share"] == D("1000.01")
    assert out["unallocated"] == {"lift": D("50.00")}


def test_reconcile_default_key_takes_unbudgeted_category() -> None:
    keys = {"k1": [("A", D("1")), ("B", D("3"))]}
    out = reconcile({"insurance": D("400")}, {}, "k1", keys, {})
    rows = {r["unit_ref"]: r for r in out["units"]}
    assert rows["B"]["balance"] == D("-300.00")
    assert out["unallocated"] == {}
