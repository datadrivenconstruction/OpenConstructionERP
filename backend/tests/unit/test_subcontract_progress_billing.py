# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress billing against a subcontract's schedule of values.

Worked example (USD, retention 10 percent, agreement value 100,000 of which
5,000 is an approved change order):

=========  =========  ======================================================
Package    Scheduled  Applications
=========  =========  ======================================================
Concrete   60,000     PA-0001 approved 30,000; PA-0002 rejected 50,000
Steel      40,000     PA-0001 approved 10,000; PA-0003 submitted 99,999
=========  =========  ======================================================

PA-0004 (the one printed) bills concrete 15,000 and steel 20,000. Only PA-0001
is earlier and approved, so concrete stands at 45,000 (75 percent) and steel at
30,000 (75 percent): 75,000 completed, 7,500 retention held, 36,000 previously
certified (PA-0001 net: 40,000 less 4,000), and 31,500 due.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.validation.engine import rule_registry, validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules.subcontractors import progress_billing as pb
from app.modules.subcontractors import validators as checks

D = Decimal
CONCRETE = "00000000-0000-0000-0000-0000000000c1"
STEEL = "00000000-0000-0000-0000-0000000000a2"
PACKAGES = [
    {"id": CONCRETE, "name": "Concrete", "planned_value": D("60000")},
    {"id": STEEL, "name": "Steel", "planned_value": D("40000")},
]


def _app(number: str, status: str, concrete: str, steel: str, *, approved: tuple[str, str] | None = None) -> dict:
    gross = D(concrete) + D(steel)
    net = gross - gross * D("0.10")
    lines = [
        {
            "work_package_id": CONCRETE,
            "claimed_amount": D(concrete),
            "approved_amount": D(approved[0] if approved else 0),
        },
        {"work_package_id": STEEL, "claimed_amount": D(steel), "approved_amount": D(approved[1] if approved else 0)},
    ]
    return {
        "id": number,
        "number": number,
        "status": status,
        "gross_amount": gross,
        "net_amount": net,
        "approved_gross_amount": gross if status in pb.COUNTED_STATUSES else None,
        "approved_net_amount": net if status in pb.COUNTED_STATUSES else None,
        "lines": lines,
    }


def _history() -> list[dict]:
    return [
        _app("PA-0001", "finance_approved", "30000", "10000", approved=("30000", "10000")),
        _app("PA-0002", "rejected", "50000", "0"),
        _app("PA-0003", "submitted", "0", "99999"),
        _app("PA-0004", "submitted", "15000", "20000"),
    ]


def _statement(current: str = "PA-0004") -> dict:
    return pb.build_statement(
        contract_sum_to_date=D("100000"),
        change_orders_total=D("5000"),
        retention_percent=D("10"),
        work_packages=PACKAGES,
        applications=_history(),
        current_id=current,
    )


def test_worked_example_lines() -> None:
    concrete, steel = _statement()["lines"]
    assert (concrete["previous"], concrete["this_period"], concrete["total_completed"]) == (
        D("30000"),
        D("15000"),
        D("45000"),
    )
    assert concrete["percent_complete"] == D("75.00")
    assert concrete["retention"] == D("4500.00")
    assert concrete["balance_to_finish"] == D("15000")
    assert (steel["previous"], steel["this_period"], steel["total_completed"]) == (D("10000"), D("20000"), D("30000"))
    assert steel["percent_complete"] == D("75.00")
    assert steel["retention"] == D("3000.00")
    assert steel["balance_to_finish"] == D("10000")


def test_worked_example_summary() -> None:
    summary = _statement()["summary"]
    assert summary["original_contract_sum"] == D("95000")
    assert summary["change_orders"] == D("5000")
    assert summary["contract_sum_to_date"] == D("100000")
    assert summary["completed_to_date"] == D("75000")
    assert summary["retention_held"] == D("7500.00")
    assert summary["previous_certified"] == D("36000.00")
    assert summary["current_due"] == D("31500.00")
    assert summary["balance_to_finish"] == D("25000")
    # The statement ties to the application's own header: gross 35,000 less 10 percent.
    assert summary["current_due"] == _history()[3]["net_amount"]


def test_rejected_and_submitted_applications_never_count_as_previous() -> None:
    steel = _statement()["lines"][1]
    assert steel["previous"] == D("10000")


def test_an_old_statement_does_not_see_later_applications() -> None:
    first = _statement("PA-0001")
    assert [row["previous"] for row in first["lines"]] == [D(0), D(0)]
    assert first["summary"]["previous_certified"] == D(0)
    # An approved application shows what finance approved, not what was claimed.
    assert [row["this_period"] for row in first["lines"]] == [D("30000"), D("10000")]


def test_the_approved_amount_not_the_claim_is_what_later_applications_build_on() -> None:
    history = [
        _app("PA-0001", "finance_approved", "30000", "10000", approved=("25000", "10000")),
        _app("PA-0002", "submitted", "5000", "0"),
    ]
    statement = pb.build_statement(
        contract_sum_to_date=D("100000"),
        change_orders_total=D("0"),
        retention_percent=D("10"),
        work_packages=PACKAGES,
        applications=history,
        current_id="PA-0002",
    )
    assert statement["lines"][0]["previous"] == D("25000")


def test_a_statement_for_an_unsaved_application() -> None:
    statement = pb.build_statement(
        contract_sum_to_date=D("100000"),
        change_orders_total=D("0"),
        retention_percent=D("10"),
        work_packages=PACKAGES,
        applications=_history()[:1],
        current_lines=[{"work_package_id": CONCRETE, "claimed_amount": D("6000"), "approved_amount": D(0)}],
    )
    assert statement["lines"][0]["previous"] == D("30000")
    assert statement["lines"][0]["this_period"] == D("6000")
    assert statement["summary"]["this_gross"] == D("6000")


def test_a_period_percentage_is_an_amount_of_the_scheduled_value() -> None:
    assert pb.amount_from_percent(D("60000"), D("12.5")) == D("7500.00")
    assert pb.percent_of(D("7500"), D("60000")) == D("12.50")
    assert pb.percent_of(D("1"), D("0")) is None


# ── Rules ────────────────────────────────────────────────────────────────


def _payload(**over: object) -> dict:
    statement = _statement()
    base = {
        "id": "PA-0004",
        "application_number": "PA-0004",
        "currency": "USD",
        "as_of": "2026-11-17",
        "contract_sum_to_date": "100000",
        "previous_gross_billed": "40000",
        "this_gross": "35000",
        "override_reason": "",
        "lines": [
            {
                "name": r["name"],
                "scheduled_value": str(r["scheduled_value"]),
                "previous": str(r["previous"]),
                "this_period": str(r["this_period"]),
                "total_completed": str(r["total_completed"]),
            }
            for r in statement["lines"]
        ],
    }
    base.update(over)
    return base


def test_a_clean_statement_raises_nothing() -> None:
    p = _payload()
    assert checks.check_pay_app_line_over_complete(p) == []
    assert checks.check_pay_app_line_negative(p) == []
    assert checks.check_pay_app_within_agreement(p) == []


def test_a_line_over_100_percent_warns_and_a_reason_clears_it() -> None:
    lines = [
        {
            "name": "Steel",
            "scheduled_value": "40000",
            "previous": "35000",
            "this_period": "8000",
            "total_completed": "43000",
        }
    ]
    [finding] = checks.check_pay_app_line_over_complete(_payload(lines=lines))
    assert finding.details == {"scheduled_value": "40000", "total_completed": "43000"}
    assert "107.50" in finding.params["percent"]
    assert (
        checks.check_pay_app_line_over_complete(_payload(lines=lines, override_reason="Quantity overrun, CO pending"))
        == []
    )


def test_exactly_100_percent_is_fine_and_an_untouched_overbilled_line_is_not_blamed_again() -> None:
    exact = [{"name": "A", "scheduled_value": "100", "previous": "0", "this_period": "100", "total_completed": "100"}]
    assert checks.check_pay_app_line_over_complete(_payload(lines=exact)) == []
    stale = [{"name": "A", "scheduled_value": "100", "previous": "120", "this_period": "0", "total_completed": "120"}]
    assert checks.check_pay_app_line_over_complete(_payload(lines=stale)) == []


def test_a_cumulative_below_zero_is_flagged() -> None:
    lines = [{"name": "A", "scheduled_value": "100", "previous": "10", "this_period": "-30", "total_completed": "-20"}]
    [finding] = checks.check_pay_app_line_negative(_payload(lines=lines))
    assert finding.details == {"total_completed": "-20"}


def test_pay_applications_cannot_exceed_the_agreement_plus_approved_variations() -> None:
    [finding] = checks.check_pay_app_within_agreement(_payload(previous_gross_billed="70000", this_gross="35000"))
    assert finding.details == {"billed": "105000", "contract_sum_to_date": "100000"}
    # Exactly the contract sum is allowed, and an agreement with no value judges nothing.
    assert checks.check_pay_app_within_agreement(_payload(previous_gross_billed="65000", this_gross="35000")) == []
    assert checks.check_pay_app_within_agreement(_payload(contract_sum_to_date="0")) == []


@pytest.mark.asyncio
async def test_the_rule_set_reports_warnings_and_errors_with_their_severity() -> None:
    register_builtin_rules()
    registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["subcontract_pay_app"])}
    assert registered == {
        "subcontract.pay_app_over_complete",
        "subcontract.pay_app_line_negative",
        "subcontract.pay_app_within_agreement",
        "subcontract.required_documents",
    }
    lines = [
        {
            "name": "Steel",
            "scheduled_value": "40000",
            "previous": "35000",
            "this_period": "8000",
            "total_completed": "43000",
        }
    ]
    report = await validation_engine.validate(
        data=_payload(lines=lines, previous_gross_billed="70000"),
        rule_sets=["subcontract_pay_app"],
        target_type="subcontract_pay_application",
        target_id="PA-0004",
        metadata={"locale": "en"},
    )
    failed = {r.rule_id: r for r in report.results if not r.passed}
    assert failed["subcontract.pay_app_over_complete"].severity.value == "warning"
    assert failed["subcontract.pay_app_within_agreement"].severity.value == "error"
    assert "107.50" in failed["subcontract.pay_app_over_complete"].message
    assert "105,000" in failed["subcontract.pay_app_within_agreement"].message
