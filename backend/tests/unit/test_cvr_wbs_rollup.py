"""CVR rolled up the WBS tree, with worked numbers.

Tree used throughout::

    1  Building                 (no own line)
      1.1 Substructure          budget 100 000, committed 40 000, cost 30 000, value 35 000,
                                forecast cost 100 000, forecast value 120 000
      1.2 Superstructure        own line budget 50 000 ...
        1.2.1 Frame             budget 200 000 ...
    (no WBS)                    an unallocated line, cost 1 000

so 1.2 = its own line + 1.2.1, 1 = 1.1 + 1.2, and the report = 1 + unallocated.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

from app.core.commercial_checks import check_wbs_rollup_reconciles
from app.core.validation.rules.commercial_control import evaluate
from app.modules.cvr.wbs_tree import WbsNodeRef, build_rollup, figures, reconciliation_rows

D = Decimal


def _line(lid, wbs, *, budget=0, committed=0, cost=0, value=0, fcost=0, fvalue=0, positions=0):
    return SimpleNamespace(
        id=lid,
        wbs_id=wbs,
        budget_cost=D(str(budget)),
        committed_cost=D(str(committed)),
        cost_to_date=D(str(cost)),
        value_to_date=D(str(value)),
        forecast_cost=D(str(fcost)),
        forecast_value=D(str(fvalue)),
        metadata_={"source": "cost_spine", "positions": positions},
    )


NODES = [
    WbsNodeRef("n1", None, "1", "Building", 0),
    WbsNodeRef("n12", "n1", "1.2", "Superstructure", 2),
    WbsNodeRef("n11", "n1", "1.1", "Substructure", 1),
    WbsNodeRef("n121", "n12", "1.2.1", "Frame", 0),
]

LINES = [
    _line(
        "L11", "n11", budget=100000, committed=40000, cost=30000, value=35000, fcost=100000, fvalue=120000, positions=3
    ),
    _line("L12", "n12", budget=50000, committed=0, cost=10000, value=9000, fcost=50000, fvalue=55000, positions=1),
    _line(
        "L121",
        "n121",
        budget=200000,
        committed=150000,
        cost=60000,
        value=70000,
        fcost=210000,
        fvalue=230000,
        positions=5,
    ),
    _line("LX", None, cost=1000, fcost=1000),
]


def _by_code(rollup):
    return {n.code: n for n in rollup.walk()}


def test_parent_is_own_lines_plus_children():
    rollup = build_rollup(NODES, LINES)
    nodes = _by_code(rollup)

    sup = nodes["1.2"]
    assert sup.own["budget_cost"] == D("50000")
    assert sup.total["budget_cost"] == D("250000")
    assert sup.total["committed_cost"] == D("150000")
    assert sup.total["forecast_cost"] == D("260000")
    assert sup.line_count == 2 and sup.positions == 6 and sup.line_ids == ["L12"]

    root = nodes["1"]
    assert root.own["cost_to_date"] == 0 and root.line_ids == []
    assert root.total["budget_cost"] == D("350000")
    assert root.total["cost_to_date"] == D("100000")
    assert root.total["value_to_date"] == D("114000")
    # forecast margin = 405 000 - 360 000
    assert root.forecast_margin == D("45000")
    assert root.margin_to_date == D("14000")
    assert root.line_count == 3 and root.positions == 9


def test_order_and_depth_follow_the_wbs():
    rollup = build_rollup(NODES, LINES)
    assert [(n.code, n.depth) for n in rollup.walk()] == [("1", 0), ("1.1", 1), ("1.2", 1), ("1.2.1", 2)]


def test_lines_without_a_known_element_land_unallocated():
    lines = [*LINES, _line("LGONE", "deleted-node", cost=500, fcost=500)]
    rollup = build_rollup(NODES, lines)
    assert rollup.unallocated.line_ids == ["LX", "LGONE"]
    assert rollup.unallocated.total["cost_to_date"] == D("1500")
    assert rollup.totals["cost_to_date"] == D("101500")


def test_a_loop_in_the_tree_still_shows_every_figure():
    looped = [WbsNodeRef("a", "b", "A", "A"), WbsNodeRef("b", "a", "B", "B")]
    rollup = build_rollup(looped, [_line("La", "a", cost=10), _line("Lb", "b", cost=20)])
    assert sum(r.total["cost_to_date"] for r in rollup.roots) == D("30")


def test_figures_margin_percentage():
    out = figures(build_rollup(NODES, LINES).roots[0].total)
    assert out["forecast_margin"] == D("45000.00")
    # 45 000 / 405 000 = 11.11 %
    assert out["forecast_margin_pct"] == D("11.11")


def test_consistent_rollup_has_no_finding():
    rows = reconciliation_rows(build_rollup(NODES, LINES))
    assert [r["id"] for r in rows] == ["n1", "n12", "report"]
    assert check_wbs_rollup_reconciles({"wbs_rollup_nodes": rows}) == []


def test_a_parent_that_does_not_add_up_is_an_error():
    rows = reconciliation_rows(build_rollup(NODES, LINES))
    rows[0]["total"]["budget_cost"] = "349000.00"
    findings = check_wbs_rollup_reconciles({"wbs_rollup_nodes": rows})
    assert len(findings) == 1
    f = findings[0]
    assert f.element_ref == "n1:budget_cost" and f.severity == "error"
    assert f.params["total"] == "349000" and f.params["parts"] == "350000"


def test_cent_rounding_is_not_a_gap():
    row = {"id": "x", "total": {"cost_to_date": "0.02"}, "parts": [{"cost_to_date": "0.01"}, {"cost_to_date": "0.00"}]}
    assert check_wbs_rollup_reconciles({"wbs_rollup_nodes": [row]}) == []


def test_rule_runs_through_the_engine_and_translates():
    rows = reconciliation_rows(build_rollup(NODES, LINES))
    rows[-1]["total"]["cost_to_date"] = "0"
    found = asyncio.run(evaluate({"wbs_rollup_nodes": rows}, target_type="cvr_report"))
    assert [f["rule_id"] for f in found] == ["cvr.wbs_rollup_reconciles"]
    assert found[0]["severity"] == "error"
    assert "101000" in found[0]["message"]
