"""Shared application math keeps currency units before any regional renderer."""

from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from app.modules.contracts.aia import (
    apply_retention_snapshot,
    build_cost_of_work_row,
    build_g702_summary,
    build_g703,
    build_g703_line,
)


@pytest.mark.parametrize(
    "currency,amount,held,expected",
    [
        ("KWD", "100.125", "10.012", "90.113"),
        ("JPY", "101", "10", "91"),
        ("USD", "100.12", "10.01", "90.11"),
    ],
)
def test_cost_row_and_summary_preserve_source_minor_units(currency, amount, held, expected):
    row = build_cost_of_work_row(
        item_number="1",
        description="Work",
        scheduled=D(amount),
        previous=D("0"),
        this_period=D(amount),
        retainage=D(held),
        currency=currency,
    )
    summary = build_g702_summary([row], original_contract_sum=D(amount), currency=currency)
    assert row["total_completed_stored"] == D(amount)
    assert summary["current_payment_due"] == D(expected)
    assert summary["total_completed_stored"] - summary["retainage"] == summary["current_payment_due"]


@pytest.mark.parametrize(
    "currency,values,expected,retention",
    [
        ("KWD", ["100.1255", "100.1255", "-0.001"], "200.250", "20.025"),
        ("JPY", ["100.5", "100.5", "-1"], "200", "20"),
        ("USD", ["100.125", "100.125", "-0.01"], "200.24", "20.02"),
    ],
)
def test_sheet_balances_credit_and_odd_units(currency, values, expected, retention):
    lines = [NS(id=i, code=str(i), description="Work", total_value=D(value)) for i, value in enumerate(values)]
    billed = {
        line.id: NS(period_completed_value=line.total_value, prior_completed_value=D(0), materials_stored_value=D(0))
        for line in lines
    }
    rows = build_g703(lines, billed, retainage_percent=D(10), currency=currency)
    assert sum(row["total_completed_stored"] for row in rows) == D(expected)
    assert sum(row["retainage"] for row in rows) == D(retention)
    for row in rows:
        assert (
            row["previous_value"] + row["this_period_value"] + row["materials_stored"] == row["total_completed_stored"]
        )
        assert row["scheduled_value"] - row["total_completed_stored"] == row["balance_to_finish"]


@pytest.mark.parametrize("currency,held,shares", [("KWD", "0.005", ["0.003", "0.002"]), ("JPY", "5", ["3", "2"])])
def test_snapshot_remainder_is_allocated_in_currency_units(currency, held, shares):
    lines = [NS(id=i, code=str(i), description="Work", total_value=D(100)) for i in range(2)]
    rows = build_g703(lines, {}, retainage_percent=D(0), prior_by_line={0: D(100), 1: D(100)}, currency=currency)
    apply_retention_snapshot(rows, lines, {}, held=D(held), currency=currency)
    assert [row["retainage"] for row in rows] == list(map(D, shares))
    assert sum(row["retainage"] for row in rows) == D(held)


def test_single_line_percentage_keeps_two_decimal_places_in_jpy():
    line = NS(id=1, code="1", description="Work", total_value=D(300))
    claim = NS(period_completed_value=D(100), prior_completed_value=D(0), materials_stored_value=D(0))
    row = build_g703_line(line, claim, line_number=1, retainage_percent=D(0), currency="JPY")
    assert row["percent_complete"] == D("33.33")


def test_zero_decimal_snapshot_components_sum_to_rounded_held():
    lines = [NS(id=i, code=str(i), description="Work", total_value=D(100)) for i in range(2)]
    billed = {
        line.id: NS(
            period_completed_value=D(100),
            prior_completed_value=D(0),
            materials_stored_value=D(0),
            retention_to_date=D("0.60"),
            retention_stored_to_date=D(0),
        )
        for line in lines
    }
    rows = build_g703(lines, billed, retainage_percent=D(0), currency="JPY")
    apply_retention_snapshot(rows, lines, billed, held=D("1.20"), currency="JPY")
    assert sum(row["retainage"] for row in rows) == D(1)
    assert all(row["retainage"] == row["retainage_completed_work"] + row["retainage_stored_materials"] for row in rows)


def test_summary_dependent_cells_use_printed_operands():
    row = build_cost_of_work_row(
        item_number="1",
        description="Work",
        scheduled=D(1),
        previous=D(0),
        this_period=D(1),
        retainage=D(0),
        currency="JPY",
    )
    summary = build_g702_summary(
        [row],
        original_contract_sum=D("0.50"),
        change_orders_net=D("0.50"),
        previous_certificates_total=D("0.50"),
        currency="JPY",
    )
    assert summary["original_contract_sum"] + summary["change_orders_net"] == summary["contract_sum_to_date"] == D(2)
    assert (
        summary["total_earned_less_retainage"] - summary["previous_certificates_total"]
        == summary["current_payment_due"]
        == D(0)
    )


@pytest.mark.asyncio
async def test_cost_only_certification_freeze_matches_rounded_row():
    from unittest.mock import AsyncMock

    from app.modules.contracts.service import ContractsService

    claim = NS(id=1, contract_id=2, currency="JPY", gross_amount=D("0.50"), retention_amount=D("0.50"))
    contract = NS(id=2, currency="JPY")
    prior = NS(gross_amount=D("0.50"), retention_amount=D(0))
    service = NS(
        claim_line_repo=NS(list_for_claim=AsyncMock(return_value=[])),
        claim_repo=NS(prior_claims=AsyncMock(return_value=[prior])),
    )
    completed, held = await ContractsService.claim_completed_and_held(service, claim, contract=contract)
    row = build_cost_of_work_row(
        item_number="1",
        description="Work",
        scheduled=D(10),
        previous=D("0.50"),
        this_period=D("0.50"),
        retainage=D("0.50"),
        currency="JPY",
    )
    assert completed == row["total_completed_stored"] == D(2)
    assert held == row["retainage"] == D(1)
