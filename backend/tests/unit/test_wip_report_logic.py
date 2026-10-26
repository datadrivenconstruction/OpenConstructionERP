# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ schedule arithmetic and rules, without a database."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest

from app.modules.wip_report import logic
from app.modules.wip_report.logic import WipInputs, compute


def _row(**kw) -> logic.WipFigures:
    base = {
        "contract_value": Decimal("1000000"),
        "estimated_cost": Decimal("800000"),
        "cost_to_date": Decimal("400000"),
        "billed_to_date": Decimal("450000"),
    }
    base.update(kw)
    return compute(WipInputs(**base))


def test_cost_to_cost_over_billing() -> None:
    f = _row()
    assert f.percent_complete == Decimal("50.00")
    assert f.earned_revenue == Decimal("500000.00")
    assert f.under_billing == Decimal("50000.00") and f.over_billing == Decimal("0.00")
    assert f.projected_gross_profit == Decimal("200000.00")
    assert f.backlog == Decimal("500000.00")
    assert f.cost_to_complete == Decimal("400000.00")
    assert f.gross_profit_to_date == Decimal("100000.00")


def test_over_billing_is_billed_less_earned() -> None:
    f = _row(billed_to_date=Decimal("600000.10"))
    assert f.over_billing == Decimal("100000.10") and f.under_billing == Decimal("0.00")


def test_exact_decimals_never_floats() -> None:
    f = _row(contract_value=Decimal("0.30"), estimated_cost=Decimal("0.10"), cost_to_date=Decimal("0.10"))
    assert isinstance(f.earned_revenue, Decimal)
    assert f.earned_revenue == Decimal("0.30")
    assert logic.dec(0.1) == Decimal("0.1")


def test_percent_capped_and_flags() -> None:
    f = _row(estimated_cost=Decimal("300000"), billed_to_date=Decimal("1200000"))
    assert f.percent_complete == Decimal("100.00")
    assert f.percent_complete_raw > Decimal("100")
    assert {"eac_below_cost_to_date", "percent_over_100", "billed_exceeds_contract"} <= set(f.flags)


def test_fade_and_loss() -> None:
    f = _row(estimated_cost=Decimal("1050000"), previous_gross_profit=Decimal("200000"))
    assert f.fade == Decimal("-250000.00")
    assert f.loss_job and "loss_job" in f.flags
    assert logic.is_large_fade(f.fade, f.contract_value, Decimal("2"))
    assert not logic.is_large_fade(Decimal("-10000"), Decimal("1000000"), Decimal("2"))
    assert not logic.is_large_fade(Decimal("50000"), Decimal("1000000"), Decimal("2"))


def test_no_estimate_and_zero_inputs() -> None:
    f = _row(estimated_cost=Decimal("0"))
    assert "no_estimate" in f.flags and f.percent_complete == Decimal("100.00")
    z = compute(WipInputs(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")))
    assert z.percent_complete == Decimal("0.00") and z.fade is None and z.flags == []


def test_totals_per_currency_never_mix() -> None:
    rows = [
        {"currency": "USD", "contract_value": Decimal("100"), "earned_revenue": Decimal("50"), "fade": None},
        {"currency": "USD", "contract_value": Decimal("300"), "earned_revenue": Decimal("100"), "fade": "-5"},
        {"currency": "EUR", "contract_value": Decimal("10"), "earned_revenue": Decimal("1")},
    ]
    totals = {t["currency"]: t for t in logic.totals_by_currency(rows)}
    assert totals["USD"]["contract_value"] == Decimal("400.00") and totals["USD"]["projects"] == 2
    assert totals["USD"]["percent_complete"] == Decimal("37.50")
    assert totals["USD"]["fade"] == Decimal("-5.00")
    assert totals["EUR"]["contract_value"] == Decimal("10.00")


def test_periods() -> None:
    assert logic.month_end("2026-02") == date(2026, 2, 28)
    assert logic.valid_period("2026-12") and not logic.valid_period("2026-13") and not logic.valid_period("26-01")


@pytest.mark.asyncio
async def test_rules_fire_on_a_bad_row() -> None:
    from app.modules.wip_report.validators import RULE_IDS, evaluate, register_wip_report_rules

    register_wip_report_rules()
    f = _row(estimated_cost=Decimal("300000"), billed_to_date=Decimal("1200000"), previous_gross_profit=Decimal("0"))
    row = {"project_id": "p1", "project_name": "Job", "currency": "USD", "previous_period": "2026-09", **f.as_dict()}
    found = {r.rule_id for r in await evaluate({"rows": [row], "fade_threshold_pct": "2"})}
    assert found == {
        "wip_report.billed_exceeds_contract",
        "wip_report.percent_complete_over_100",
        "wip_report.eac_below_cost_to_date",
    }
    bad = _row(estimated_cost=Decimal("1100000"), previous_gross_profit=Decimal("200000"))
    row2 = {"project_id": "p2", "currency": "USD", **bad.as_dict()}
    found2 = {r.rule_id for r in await evaluate({"rows": [row2]})}
    assert found2 == {"wip_report.large_fade", "wip_report.loss_job"}
    assert len(RULE_IDS) == 5
    clean = {"project_id": "p3", "currency": "USD", **_row().as_dict()}
    assert await evaluate({"rows": [clean]}) == []


def test_exports_render() -> None:
    from openpyxl import load_workbook

    from app.modules.wip_report.exports import to_pdf, to_xlsx

    row = {"project_name": "Job", "currency": "USD", **_row().as_dict()}
    data = {"as_of": date(2026, 9, 30), "rows": [row], "totals": logic.totals_by_currency([row])}
    wb = load_workbook(io.BytesIO(to_xlsx(data)))
    ws = wb["WIP schedule"]
    assert ws["A3"].value == "Job"
    assert Decimal(str(ws["G3"].value)) == Decimal("500000")
    assert to_pdf(data).startswith(b"%PDF")
