"""Commercial control: budget at target cost, commitment grid, approval bands,
valuation stages and the CVR rollup by WBS, with worked numbers.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.commercial_checks import (
    check_assessed_within_submitted,
    check_bands_contiguous,
    check_certified_within_assessed,
    check_line_over_committed,
    check_target_rate_basis,
    check_unmapped_cost,
    step_applies,
)
from app.modules.boq.budget_basis import position_budget, sale_value
from app.modules.costmodel.commitment_grid import LineFigures, assemble_grid
from app.modules.cvr.spine_rollup import CostSource, fold

D = Decimal


def _pos(qty, rate, *, target=None, sale=None, wbs=None, cost_line=None, ordinal="01", unit="m3"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        ordinal=ordinal,
        description="Concrete C30/37",
        unit=unit,
        quantity=str(qty),
        unit_rate=str(rate),
        total=str(D(str(qty)) * D(str(rate))),
        target_rate=None if target is None else str(target),
        sale_rate=None if sale is None else str(sale),
        wbs_id=wbs,
        cost_line_id=cost_line,
    )


# ── 1. Budget basis ──────────────────────────────────────────────────────


def test_budget_uses_target_rate_when_set():
    budget = position_budget(_pos(100, 120, target=95))
    assert budget.amount == D("9500")
    assert budget.basis == "target"


def test_budget_falls_back_to_unit_rate():
    budget = position_budget(_pos(50, 40))
    assert budget.amount == D("2000")
    assert budget.basis == "unit_rate"


def test_sale_value_prefers_sale_rate_then_total():
    assert sale_value(_pos(100, 120, sale=130)) == D("13000")
    assert sale_value(_pos(100, 120)) == D("12000")


def test_target_rate_basis_warns_once_with_count():
    findings = check_target_rate_basis(
        {
            "budget_positions": [
                {"id": "a", "ordinal": "01", "basis": "target"},
                {"id": "b", "ordinal": "02", "basis": "unit_rate"},
            ]
        }
    )
    assert len(findings) == 1
    assert findings[0].params == {"missing": "1", "total": "2", "sample": "02"}
    assert check_target_rate_basis({"budget_positions": [{"id": "a", "basis": "target"}]}) == []


# ── 2. Commitment grid ───────────────────────────────────────────────────


def test_grid_partial_award_committed_and_remaining():
    """Budget 100 m3 at target 95; PO 60 at 92 and subcontract 30 at 100; 40 received."""
    cost_line = uuid.uuid4()
    pos = _pos(100, 120, target=95, cost_line=cost_line)
    figures = {
        str(cost_line): LineFigures(
            po_qty=D("60"),
            po_value=D("5520"),
            sub_qty=D("30"),
            sub_value=D("3000"),
            received_qty=D("40"),
            received_value=D("3680"),
        )
    }
    (row,) = assemble_grid([pos], figures)
    assert row.budget_value == D("9500.00")
    assert row.committed_qty == D("90")
    assert row.committed_value == D("8520.00")
    assert row.remaining_qty == D("10")
    assert row.remaining_value == D("980.00")
    assert row.received_value == D("3680.00")
    assert not row.over_committed_qty
    assert not row.over_committed_value


def test_grid_over_commitment_is_flagged():
    cost_line = uuid.uuid4()
    pos = _pos(100, 120, target=95, cost_line=cost_line)
    (row,) = assemble_grid([pos], {str(cost_line): LineFigures(po_qty=D("110"), po_value=D("10120"))})
    assert row.remaining_qty == D("-10")
    assert row.over_committed_qty and row.over_committed_value
    findings = check_line_over_committed(
        {
            "grid_rows": [
                {
                    "id": "p1",
                    "ordinal": "01",
                    "budget_qty": str(row.budget_qty),
                    "committed_qty": str(row.committed_qty),
                    "budget_value": str(row.budget_value),
                    "committed_value": str(row.committed_value),
                }
            ]
        }
    )
    assert len(findings) == 1
    assert findings[0].params["committed_value"] == "10120"


def test_grid_position_off_spine_keeps_budget_and_zeros():
    (row,) = assemble_grid([_pos(10, 50)], {})
    assert row.budget_value == D("500.00")
    assert row.committed_value == D("0.00")
    assert not row.on_cost_spine


def test_grid_skips_section_rows():
    assert assemble_grid([_pos(0, 0, unit="section")], {}) == []


# ── 3. Approval bands ────────────────────────────────────────────────────

PM = {"ordinal": 1, "amount_min": None, "amount_max": None}
DIRECTOR = {"ordinal": 2, "amount_min": "50000", "amount_max": None}


def test_amount_above_band_routes_to_director_below_skips():
    from app.modules.approval_routes.service import applicable_ordinals, next_ordinal_after

    steps = [SimpleNamespace(**PM), SimpleNamespace(**DIRECTOR)]
    assert applicable_ordinals(steps, D("60000")) == [1, 2]
    assert applicable_ordinals(steps, D("20000")) == [1]
    assert next_ordinal_after(steps, D("60000"), 1) == 2
    assert next_ordinal_after(steps, D("20000"), 1) is None
    # No amount: every step applies, more approvers rather than fewer.
    assert applicable_ordinals(steps, None) == [1, 2]


def test_band_edges_are_half_open():
    assert step_applies(D("50000"), "50000", None)
    assert not step_applies(D("49999.99"), "50000", None)
    assert not step_applies(D("10000"), "0", "10000")


def test_escalation_route_is_contiguous():
    assert check_bands_contiguous({"route_steps": [PM, DIRECTOR]}) == []


def test_gap_between_bands_is_an_error():
    findings = check_bands_contiguous(
        {
            "route_steps": [
                {"ordinal": 1, "amount_min": "0", "amount_max": "10000"},
                {"ordinal": 2, "amount_min": "20000", "amount_max": None},
            ]
        }
    )
    assert [(f.params["kind"], f.severity, f.params["low"], f.params["high"]) for f in findings] == [
        ("gap", "error", "10000", "20000")
    ]


def test_overlap_is_a_warning_and_empty_band_an_error():
    findings = check_bands_contiguous(
        {
            "route_steps": [
                {"ordinal": 1, "amount_min": "0", "amount_max": "15000"},
                {"ordinal": 2, "amount_min": "10000", "amount_max": "50000"},
                {"ordinal": 3, "amount_min": "500", "amount_max": "500"},
            ]
        }
    )
    kinds = {(f.params["kind"], f.severity) for f in findings}
    assert kinds == {("overlap", "warning"), ("empty", "error")}


def test_leading_gap_without_an_unbanded_step():
    findings = check_bands_contiguous({"route_steps": [DIRECTOR]})
    assert [(f.params["kind"], f.params["low"], f.params["high"]) for f in findings] == [("gap", "0", "50000")]


def test_route_with_gap_is_refused_on_save():
    from fastapi import HTTPException

    from app.modules.approval_routes.schemas import StepCreate
    from app.modules.approval_routes.service import _validate_bands

    steps = [
        StepCreate(ordinal=1, approver_role="manager", amount_min=D("0"), amount_max=D("10000")),
        StepCreate(ordinal=2, approver_role="admin", amount_min=D("20000")),
    ]
    with pytest.raises(HTTPException) as exc:
        _validate_bands(steps)
    assert exc.value.status_code == 422


# ── 4. Valuation stages ──────────────────────────────────────────────────


def test_valuation_stage_checks():
    payload = {
        "valuation_lines": [
            {"id": "l1", "label": "Formwork", "submitted": "100", "assessed": "90", "certified": "85"},
            {"id": "l2", "label": "Rebar", "submitted": "40", "assessed": "45", "certified": "50"},
        ]
    }
    assessed = check_assessed_within_submitted(payload)
    certified = check_certified_within_assessed(payload)
    assert [f.element_ref for f in assessed] == ["l2"]
    assert assessed[0].params == {"line": "Rebar", "submitted": "40", "assessed": "45"}
    assert [f.element_ref for f in certified] == ["l2"]


# ── 5. CVR rollup by WBS ─────────────────────────────────────────────────


def test_cvr_fold_totals_equal_module_totals():
    """Two WBS elements, one PO on WBS A, one subcontract split 60/40, one invoice without WBS."""
    wbs_a, wbs_b = str(uuid.uuid4()), str(uuid.uuid4())
    positions = [
        _pos(100, 120, target=95, wbs=wbs_a),  # budget 9500, sale 12000
        _pos(50, 40, wbs=wbs_b),  # budget 2000, sale 2000
    ]
    sources = [
        CostSource("po", "po-1", D("5520"), D("3680"), ((wbs_a, D("1")),)),
        CostSource("subcontract", "sc-1", D("3000"), D("1000"), ((wbs_a, D("0.6")), (wbs_b, D("0.4")))),
        CostSource("invoice", "inv-1", D("0"), D("250"), ()),
    ]
    rollup = fold(positions, sources, {str(positions[0].id): D("4000")})

    a, b, unmapped = rollup.by_wbs[wbs_a], rollup.by_wbs[wbs_b], rollup.by_wbs[""]
    assert (a.budget_cost, a.committed_cost, a.cost_to_date) == (D("9500"), D("7320.0000"), D("4280.0000"))
    assert (b.budget_cost, b.committed_cost, b.cost_to_date) == (D("2000"), D("1200.0000"), D("400.0000"))
    assert (unmapped.committed_cost, unmapped.cost_to_date) == (D("0"), D("250"))
    # 4280 spent + 7320 committed already exceeds the 9500 budget: nothing more to buy.
    assert a.forecast_cost == D("11600.0000")
    # 400 + 1200 + (2000 - 1600) = 2000
    assert b.forecast_cost == D("2000.0000")
    assert a.value_to_date == D("4000")

    totals = rollup.totals()
    assert totals["committed_cost"] == D("8520")
    assert totals["cost_to_date"] == D("4930")
    assert totals["budget_cost"] == D("11500")
    assert totals["forecast_value"] == D("14000")

    findings = check_unmapped_cost({"unmapped_sources": rollup.unmapped_sources})
    assert [f.element_ref for f in findings] == ["invoice:inv-1"]
    assert check_target_rate_basis({"budget_positions": rollup.budget_positions})[0].params["missing"] == "1"


# ── Rule set through the validation engine ───────────────────────────────


@pytest.mark.asyncio
async def test_rules_translate_findings():
    from app.core.validation.rules import register_builtin_rules
    from app.core.validation.rules.commercial_control import evaluate

    register_builtin_rules()
    out = await evaluate(
        {"route_steps": [{"ordinal": 1, "amount_min": "0", "amount_max": "10000"}, DIRECTOR]},
        target_type="approval_route",
    )
    assert [r["rule_id"] for r in out] == ["approval_routes.bands_contiguous"]
    assert out[0]["severity"] == "error"
    assert "10000" in out[0]["message"] and "50000" in out[0]["message"]
