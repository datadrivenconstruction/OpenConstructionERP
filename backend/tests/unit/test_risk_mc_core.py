"""The shared Monte Carlo cost sampler and the project simulation built on it.

* ``simulate_cost`` is reproducible for a seed and reads the percentile of the weighted total.
* ``RiskService.simulate`` returns what it returned before the sampler was extracted
  (golden recorded from the pre-refactor code with ``random.seed(11)``).
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

from app.modules.risk import mc_core
from app.modules.risk.service import RiskService

GOLDEN = Path(__file__).parent / "data" / "risk_simulate_golden.json"


def _items() -> list[mc_core.CostItem]:
    return [
        mc_core.CostItem(1000.0, 5000.0, 20000.0, 0.5),
        mc_core.CostItem(12000.0, 12000.0, 12000.0, 0.3),
        mc_core.CostItem(0.0, 9000.0, 9000.0, 0.0),
    ]


def test_simulate_cost_is_deterministic_for_a_seed():
    a = mc_core.simulate_cost(_items(), 3000, seed=42)
    b = mc_core.simulate_cost(_items(), 3000, seed=42)
    c = mc_core.simulate_cost(_items(), 3000, seed=43)
    assert a.totals == b.totals
    assert a.totals != c.totals
    assert a.percentile(80) == b.percentile(80)
    assert a.percentile(50) <= a.percentile(80) <= a.percentile(95)


def test_zero_weight_item_adds_nothing_and_a_point_item_adds_its_weighted_amount():
    sim = mc_core.simulate_cost([mc_core.CostItem(100.0, 100.0, 100.0, 0.25)], 200, seed=1)
    assert set(sim.totals) == {25.0}
    assert sim.per_item_sum == [25.0 * 200]
    none = mc_core.simulate_cost([mc_core.CostItem(0.0, 500.0, 900.0, 0.0)], 50, seed=1)
    assert set(none.totals) == {0.0}


def test_iterations_are_capped():
    assert mc_core.simulate_cost(_items(), 10**9, seed=1).iterations == 100_000


def test_pert_triple_is_ordered_and_falls_back_to_a_point():
    assert mc_core.pert_triple_or_point(None, None, None, fallback=7.0) == (7.0, 7.0, 7.0)
    assert mc_core.pert_triple_or_point(900, 100, 10, fallback=0.0) == (10.0, 100.0, 900.0)


def _risk(i: int, p10, p50, p90, prob: str, cost: str, st: str = "identified", ps=None):
    return NS(
        id=uuid.UUID(int=i), code=f"R{i}", status=st, probability=prob, probability_score=ps,
        impact_cost=cost, impact_schedule_days=i * 3, cost_p10=p10, cost_p50=p50, cost_p90=p90,
        schedule_p10=None, schedule_p50=None, schedule_p90=None, currency="EUR",
    )  # fmt: skip


def test_project_simulation_output_is_unchanged_by_the_extraction():
    items = [
        _risk(1, Decimal(1000), Decimal(5000), Decimal(20000), "0.5", "5000"),
        _risk(2, None, None, None, "0.3", "12000"),
        _risk(3, Decimal(200), Decimal(300), Decimal(900), "0.9", "300", ps=4),
        _risk(4, Decimal(1), Decimal(2), Decimal(3), "0.9", "300", st="closed"),
    ]

    class Repo:
        async def all_for_project(self, _pid):
            return items

        async def update_fields(self, *_a, **_k):
            return None

    async def currency(_pid):
        return "EUR"

    async def drawn(_pid):
        return {str(uuid.UUID(int=3))}

    svc = object.__new__(RiskService)
    svc.repo = Repo()
    svc._get_project_currency = currency
    svc._drawn_risk_ids = drawn
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for mode, expected in golden.items():
        random.seed(11)
        got = asyncio.run(svc.simulate(uuid.uuid4(), iterations=2000, mode=mode))
        assert json.loads(json.dumps(got, sort_keys=True)) == expected, mode
