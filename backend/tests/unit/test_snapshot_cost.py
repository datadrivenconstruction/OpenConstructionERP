"""Pure allocation behind GET /schedules/{id}/snapshot-cost (5D cost-at-date)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.core.validation.engine import ValidationContext
from app.modules.schedule.snapshot_cost import TaskCost, build_cost_snapshot, pick_weights, split_amount
from app.modules.schedule.validators import SnapshotCostCoverage

D = Decimal


def _sum_elements(out: dict, key: str = "planned_cost") -> Decimal:
    return sum((r[key] for r in out["elements"].values()), D("0"))


def test_split_is_exact_to_the_cent() -> None:
    parts = split_amount(D("100.00"), [D("1"), D("1"), D("1")], "EUR")
    assert sum(parts) == D("100.00")
    assert sorted(parts) == [D("33.33"), D("33.33"), D("33.34")]


def test_quantity_weights_beat_equal_split() -> None:
    task = TaskCost("in_progress", D("300"), D("150"), element_ids=["a", "b"], weights={"a": D("1"), "b": D("2")})
    out = build_cost_snapshot([task], "EUR")
    assert out["elements"]["a"]["planned_cost"] == D("100.00")
    assert out["elements"]["b"]["planned_cost"] == D("200.00")
    assert out["elements"]["a"]["allocation"] == "quantity"


def test_equal_split_when_no_weights() -> None:
    out = build_cost_snapshot([TaskCost("not_started", D("100"), D("0"), element_ids=["a", "b"])], "EUR")
    assert out["elements"]["a"]["planned_cost"] == D("50.00")
    assert out["elements"]["a"]["allocation"] == "equal"


def test_element_on_two_tasks_counts_each_task_once() -> None:
    t1 = TaskCost("completed", D("100"), D("100"), element_ids=["a", "a"])  # duplicate link on one task
    t2 = TaskCost("delayed", D("40"), D("0"), element_ids=["a"])
    out = build_cost_snapshot([t1, t2], "EUR")
    assert out["elements"]["a"]["planned_cost"] == D("140.00")
    assert out["elements"]["a"]["status"] == "delayed"
    assert out["totals"]["bac"] == D("140.00")
    assert out["unlinked_cost"] == D("0")


def test_reconciles_to_bac_with_unlinked_and_truncation() -> None:
    tasks = [TaskCost("in_progress", D("1000.01"), D("10"), element_ids=[f"e{i}" for i in range(7)])]
    tasks.append(TaskCost("not_started", D("250.50"), D("0")))  # no elements
    out = build_cost_snapshot(tasks, "EUR", cap=3)
    assert len(out["elements"]) == 3 and out["elements_total"] == 7
    assert _sum_elements(out) + out["other_elements_cost"] + out["unlinked_cost"] == out["totals"]["bac"]
    assert out["unlinked_cost"] == D("250.50")
    assert out["coverage_pct"] == round(float(D("1000.01") / D("1250.51") * 100), 2)
    assert sum(b["planned_cost"] for b in out["by_status"].values()) == D("1000.01")


def test_date_before_start_and_after_end() -> None:
    before = build_cost_snapshot([TaskCost("not_started", D("500"), D("0"), pv=D("0"), element_ids=["a"])], "EUR")
    assert before["totals"]["pv"] == before["totals"]["ev"] == D("0.00")
    after = build_cost_snapshot([TaskCost("completed", D("500"), D("500"), pv=D("500"), element_ids=["a"])], "EUR")
    assert after["totals"]["ev"] == after["totals"]["bac"] == D("500.00")


def test_no_cost_data_is_all_zero() -> None:
    out = build_cost_snapshot([TaskCost("not_started", D("0"), D("0"), element_ids=["a"])], "EUR")
    assert out["totals"]["bac"] == D("0.00") and out["coverage_pct"] == 0.0


def test_pick_weights_needs_one_positive_key_on_every_element() -> None:
    els = {"a": {"quantities": {"volume": 2, "area": 5}}, "b": {"quantities": {"volume": 0, "area": 7}}}
    assert pick_weights(els, ["a", "b"]) == {"a": D("5"), "b": D("7")}
    assert pick_weights(els, ["a", "zz"]) is None


def test_coverage_rule_fires_only_with_cost_data_below_threshold() -> None:
    rule = SnapshotCostCoverage()

    def run(block: dict) -> list:
        return asyncio.run(rule.validate(ValidationContext(data={"cost_snapshot": block})))

    assert run({"has_cost_data": True, "coverage_pct": 79.9})[0].passed is False
    assert run({"has_cost_data": True, "coverage_pct": 80}) == []
    assert run({"has_cost_data": False, "coverage_pct": 0}) == []
