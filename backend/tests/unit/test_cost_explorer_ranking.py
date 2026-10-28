"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Cost Explorer resource-match ranking engine.

The engine (``app.modules.cost_explorer.ranking``) is pure - stdlib only, no
ORM or app imports - so it is loaded here directly from its file path. That
keeps the test independent of the FastAPI dependency graph (which does not
import cleanly on a bare interpreter) while still exercising the real module,
and it runs identically here and in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

_RANKING_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "cost_explorer" / "ranking.py"
_spec = importlib.util.spec_from_file_location("cost_explorer_ranking", _RANKING_PATH)
assert _spec and _spec.loader
ranking = importlib.util.module_from_spec(_spec)
# Register before exec: dataclasses under ``from __future__ import annotations``
# resolve field types via ``sys.modules[cls.__module__]``, which must exist.
sys.modules["cost_explorer_ranking"] = ranking
_spec.loader.exec_module(ranking)

ResourceLine = ranking.ResourceLine
CandidateItem = ranking.CandidateItem


def _item(rate_code: str, total: str, lines: list[tuple[str, str]]) -> ranking.CandidateItem:
    """Build a candidate: ``lines`` is a list of ``(resource_code, line_cost)``."""
    return CandidateItem(
        cost_item_id=rate_code,
        rate_code=rate_code,
        region="X",
        item_total=Decimal(total),
        lines=[
            ResourceLine(resource_code=c, cost=Decimal(cost), quantity=Decimal("1"), resource_name=c.lower())
            for c, cost in lines
        ],
    )


# ── to_decimal: money/quantity parsing degrades, never raises ───────────────


def test_to_decimal_parses_and_degrades() -> None:
    assert ranking.to_decimal("12.50") == Decimal("12.50")
    assert ranking.to_decimal(3) == Decimal("3")
    assert ranking.to_decimal("") == Decimal(0)
    assert ranking.to_decimal(None) == Decimal(0)
    assert ranking.to_decimal("not-a-number") == Decimal(0)


# ── normalise_weights ───────────────────────────────────────────────────────


def test_normalise_weights_list_is_uniform() -> None:
    assert ranking.normalise_weights(["A", "B"]) == {"A": 1.0, "B": 1.0}


def test_normalise_weights_floors_negative_and_drops_blank() -> None:
    out = ranking.normalise_weights({"A": 3.0, "B": -2.0, "": 5.0, "  ": 1.0})
    assert out == {"A": 3.0, "B": 0.0}


# ── coverage / scoring ──────────────────────────────────────────────────────


def test_full_coverage_beats_partial() -> None:
    req = ["A", "B"]
    full = _item("FULL", "100", [("A", "40"), ("B", "40")])
    partial = _item("PART", "100", [("A", "40"), ("Z", "40")])
    results = ranking.rank(req, [full, partial])
    assert [r.rate_code for r in results] == ["FULL", "PART"]
    assert results[0].coverage == 1.0
    assert results[1].coverage == 0.5


def test_cost_weight_rewards_price_share() -> None:
    # Both fully cover {A,B}; the item where A+B drive more of the rate wins.
    req = ["A", "B"]
    big_share = _item("BIG", "100", [("A", "45"), ("B", "45")])  # 90% of rate
    small_share = _item("SMALL", "100", [("A", "10"), ("B", "10")])  # 20% of rate
    results = ranking.rank(req, [big_share, small_share])
    assert [r.rate_code for r in results] == ["BIG", "SMALL"]
    assert results[0].cost_weight > results[1].cost_weight


def test_unmatched_item_is_excluded() -> None:
    req = ["A"]
    none = _item("NONE", "100", [("Y", "10"), ("Z", "10")])
    assert ranking.rank(req, [none]) == []


def test_missing_codes_reported_sorted() -> None:
    req = ["A", "B", "C"]
    item = _item("ONE", "100", [("A", "10")])
    (m,) = ranking.rank(req, [item])
    assert [x.resource_code for x in m.matched] == ["A"]
    assert m.missing_codes == ["B", "C"]


def test_weighting_shifts_coverage() -> None:
    # A carries 3x the weight of B, so an item with only A covers 0.75.
    weights = {"A": 3.0, "B": 1.0}
    only_a = _item("HASA", "100", [("A", "10")])
    only_b = _item("HASB", "100", [("B", "10")])
    results = ranking.rank(weights, [only_a, only_b])
    by_code = {r.rate_code: r for r in results}
    assert round(by_code["HASA"].coverage, 2) == 0.75
    assert round(by_code["HASB"].coverage, 2) == 0.25
    assert by_code["HASA"].score > by_code["HASB"].score


def test_zero_weighted_only_match_reads_as_no_coverage() -> None:
    # Regression: an item that carries only a resource the caller weighted 0
    # must read as 0 coverage, not a full match via a degenerate fallback.
    weights = {"A": 1.0, "B": 0.0}
    only_b = _item("ONLYB", "100", [("B", "40")])
    (m,) = ranking.rank(weights, [only_b])
    assert m.coverage == 0.0


def test_all_zero_weights_fall_back_to_uniform_coverage() -> None:
    # When every requested weight is 0 (degenerate), fall back to uniform so
    # coverage is measured by count instead of dividing by zero.
    weights = {"A": 0.0, "B": 0.0}
    only_a = _item("HASA", "100", [("A", "10")])
    (m,) = ranking.rank(weights, [only_a])
    assert m.coverage == 0.5  # 1 of 2 requested, uniform


def test_zero_item_total_does_not_crash() -> None:
    req = ["A"]
    item = _item("ZERO", "0", [("A", "10")])
    (m,) = ranking.rank(req, [item])
    assert m.cost_weight == 0.0
    assert m.coverage == 1.0  # coverage still counts; cost share simply unknown


def test_extra_resources_break_ties_towards_focused_match() -> None:
    # Same coverage (1.0) and same matched cost share; the item that drags in
    # many unrequested resources ranks just below the focused one.
    req = ["A"]
    focused = _item("FOCUS", "100", [("A", "50")])
    sprawling = _item("SPRAWL", "100", [("A", "50")] + [(f"X{i}", "0") for i in range(30)])
    results = ranking.rank(req, [focused, sprawling])
    assert [r.rate_code for r in results] == ["FOCUS", "SPRAWL"]
    assert results[0].score >= results[1].score


def test_limit_caps_results() -> None:
    req = ["A"]
    items = [_item(f"I{i}", "100", [("A", str(10 + i))]) for i in range(10)]
    assert len(ranking.rank(req, items, limit=3)) == 3


def test_scores_are_bounded_unit_interval() -> None:
    req = ["A", "B"]
    item = _item("X", "100", [("A", "999999"), ("B", "999999")])  # matched cost >> total
    (m,) = ranking.rank(req, [item])
    assert 0.0 <= m.score <= 1.0
    assert m.cost_weight == 1.0  # capped, not >1


def test_empty_request_returns_nothing() -> None:
    assert ranking.rank([], [_item("X", "100", [("A", "1")])]) == []


if __name__ == "__main__":
    # Standalone runner so the engine can be validated without pytest present.
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} ranking tests passed")
