"""Submitted / assessed / certified grid and the cumulative check, with worked numbers."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.core.commercial_checks import check_cumulative_not_decreasing
from app.core.validation.rules.commercial_control import evaluate
from app.core.valuation_grid import GridLine, build_grid


def _line(**kw) -> GridLine:
    base = {
        "id": "l1",
        "label": "Formwork",
        "unit": "m2",
        "submitted_qty": D("100"),
        "assessed_qty": D("90"),
        "certified_qty": D("85"),
        "rate": D("12.50"),
        "rate_source": "contract_line.unit_rate",
        "submitted_amount": D("1250"),
        "submitted_amount_field": "period_completed_value",
    }
    base.update(kw)
    return GridLine(**base)


def test_amounts_are_quantity_times_rate_unless_stored():
    grid = build_grid([_line(prior_certified_qty=D("40"))])
    row = grid["rows"][0]
    sub, ass, cert = (row["stages"][k] for k in ("submitted", "assessed", "certified"))
    # Submitted amount is the stored claim value, not recomputed.
    assert sub["amount"] == {"value": "1250", "source": "stored", "field": "period_completed_value"}
    # 90 x 12.50 = 1125; 85 x 12.50 = 1062.50.
    assert ass["amount"] == {"value": "1125.00", "source": "computed", "field": "contract_line.unit_rate"}
    assert cert["amount"]["value"] == "1062.50"
    assert row["cumulative_certified_qty"] == "125"
    assert grid["totals"] == {"submitted": "1250", "assessed": "1125.00", "certified": "1062.50"}


def test_no_rate_leaves_the_amount_empty_and_says_so():
    row = build_grid([_line(rate=None, rate_source=None, submitted_amount=None)])["rows"][0]
    assert row["stages"]["assessed"]["amount"] == {"value": None, "source": "missing", "field": None}
    assert row["stages"]["submitted"]["amount"]["source"] == "missing"


def test_empty_claim_has_no_rows_and_null_totals():
    assert build_grid([]) == {"rows": [], "totals": {"submitted": None, "assessed": None, "certified": None}}


def test_cumulative_drop_without_note_is_flagged():
    payload = {
        "valuation_lines": [
            {"id": "a", "label": "Rebar", "prior_cumulative": "500", "cumulative": "450", "note": ""},
            {"id": "b", "label": "Formwork", "prior_cumulative": "500", "cumulative": "450", "note": "Remeasured"},
            {"id": "c", "label": "Concrete", "prior_cumulative": "200", "cumulative": "260", "note": ""},
            {"id": "d", "label": "First claim", "prior_cumulative": None, "cumulative": "10", "note": ""},
        ]
    }
    found = check_cumulative_not_decreasing(payload)
    assert [f.element_ref for f in found] == ["a"]
    assert found[0].params == {"line": "Rebar", "prior": "500", "cumulative": "450"}


@pytest.mark.asyncio
async def test_rule_runs_through_the_engine():
    findings = await evaluate(
        {
            "valuation_lines": [
                {"id": "a", "label": "Rebar", "submitted": "1", "prior_cumulative": "5", "cumulative": "4"}
            ]
        },
        target_type="progress_claim",
    )
    rule = [f for f in findings if f["rule_id"] == "valuation.cumulative_not_decreasing"]
    assert len(rule) == 1
    assert rule[0]["severity"] == "warning"
    assert "Rebar" in rule[0]["message"]
