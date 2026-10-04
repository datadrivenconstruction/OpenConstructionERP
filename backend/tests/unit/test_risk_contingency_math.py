# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Pure tests for the risk-based contingency arithmetic (no database).

The figures on the contingency card come from ``app.modules.risk.contingency``.
Each case below is built so that the obvious wrong implementation gives a
different number than the right one: a closed risk still counted, a foreign
currency summed in its own units, a drawdown counted twice, a P80 that is just
the EMV again.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.risk.contingency import (
    ContingencyLine,
    DrawdownRecord,
    RiskMoney,
    allocated_amount,
    build_position,
    clamp_probability,
    convert_to_base,
    default_line,
    emv_percentiles,
    fx_map_from_rates,
    parse_drawdown_record,
    resolve_base_currency,
    risk_weight,
    to_decimal,
)

D = Decimal


def _risk(
    rid: str,
    p: str,
    impact: str,
    *,
    status: str = "identified",
    currency: str = "EUR",
) -> RiskMoney:
    return RiskMoney(
        risk_id=rid,
        code=f"R-{rid}",
        title=f"Risk {rid}",
        status=status,
        probability=D(p),
        impact=D(impact),
        currency=currency,
    )


def _line(bid: str, allocated: str, *, currency: str = "EUR", drawdowns=()) -> ContingencyLine:
    return ContingencyLine(budget_id=bid, wbs_id=None, currency=currency, allocated=D(allocated), drawdowns=drawdowns)


# ── Status rule ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "drawn", "expected"),
    [
        ("identified", False, D("0.4")),
        ("assessed", False, D("0.4")),
        ("open", False, D("0.4")),
        ("mitigating", False, D("0.4")),
        ("mitigated", False, D("0.4")),
        ("monitoring", False, D("0.4")),
        ("", False, D("0.4")),
        (None, False, D("0.4")),
        # Retired: nothing left to carry.
        ("closed", False, D("0")),
        ("CLOSED", False, D("0")),
        # Happened and not yet drawn: certain, not gone.
        ("occurred", False, D("1")),
        (" Occurred ", False, D("1")),
        # A confirmed drawdown takes the cost out whatever the status says.
        ("occurred", True, D("0")),
        ("open", True, D("0")),
    ],
)
def test_risk_weight(status, drawn, expected):
    assert risk_weight(status, "0.4", drawn=drawn) == expected


def test_risk_weight_clamps_the_probability():
    assert risk_weight("open", "1.7") == D("1")
    assert risk_weight("open", "-0.2") == D("0")
    assert risk_weight("open", "junk") == D("0")


# ── Number helpers ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0.5", D("0.5")), ("", D("0")), (None, D("0")), ("abc", D("0")), ("NaN", D("0")), ("1e400", D("1e400"))],
)
def test_to_decimal(raw, expected):
    assert to_decimal(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("-0.2", D("0")), ("1.7", D("1")), ("0.35", D("0.35")), ("x", D("0"))])
def test_clamp_probability(raw, expected):
    assert clamp_probability(raw) == expected


def test_fx_map_skips_malformed_and_non_positive_rates():
    fx = fx_map_from_rates(
        [
            {"code": "usd", "rate": "0.92"},
            {"code": "GBP", "rate": "0"},
            {"code": "", "rate": "2"},
            "junk",
            {"code": "CHF", "rate": "abc"},
        ]
    )
    assert fx == {"USD": D("0.92")}
    assert fx_map_from_rates(None) == {}


def test_convert_to_base_blank_code_is_base_and_missing_rate_is_none():
    fx = {"USD": D("0.9")}
    assert convert_to_base(D("100"), "", base="EUR", fx=fx) == D("100")
    assert convert_to_base(D("100"), "eur", base="EUR", fx=fx) == D("100")
    assert convert_to_base(D("100"), "USD", base="EUR", fx=fx) == D("90.0")
    assert convert_to_base(D("100"), "GBP", base="EUR", fx=fx) is None


def test_resolve_base_currency():
    assert resolve_base_currency("eur", ["USD"]) == "EUR"
    assert resolve_base_currency("", ["USD", "usd", ""]) == "USD"
    assert resolve_base_currency("", ["USD", "EUR"]) == ""
    assert resolve_base_currency(None, []) == ""


def test_allocated_amount_prefers_revised_then_original():
    assert allocated_amount("120", "100") == D("120")
    assert allocated_amount("0", "100") == D("100")
    assert allocated_amount(None, None) == D("0")


def test_parse_drawdown_record_dict_and_legacy_string():
    rec = parse_drawdown_record(
        "risk:abc",
        {"amount": "250.00", "currency": "usd", "risk_code": "R-001", "note": "crane"},
        line_currency="EUR",
    )
    assert rec is not None
    assert rec.amount == D("250.00")
    assert rec.currency == "USD"
    assert rec.risk_id == "abc"
    assert rec.risk_code == "R-001"
    legacy = parse_drawdown_record("risk:xyz", "75", line_currency="eur")
    assert legacy is not None
    assert (legacy.amount, legacy.currency, legacy.risk_id) == (D("75"), "EUR", "xyz")
    assert parse_drawdown_record("risk:bad", {"amount": "-5"}, line_currency="EUR") is None
    assert parse_drawdown_record("risk:bad", "zero", line_currency="EUR") is None


# ── Percentiles ───────────────────────────────────────────────────────────


def test_percentiles_empty_register():
    values, method = emv_percentiles([])
    assert values == {50: D("0"), 80: D("0")}
    assert method == "exact"


def test_percentiles_single_risk_exact_distribution():
    # One risk, 50 % chance of 100: the total is 0 or 100 with equal weight.
    # P50 is 0 (half the mass sits at 0), P80 is 100. EMV would be 50, which is
    # neither, so a "P80 = EMV" shortcut fails here.
    values, method = emv_percentiles([(D("0.5"), D("100"))])
    assert method == "exact"
    assert values[50] == D("0")
    assert values[80] == D("100")


def test_percentiles_two_risks_exact():
    # A: 0.3 x 1000, B: 0.6 x 200. Outcomes: 0 (0.28), 200 (0.42),
    # 1000 (0.12), 1200 (0.18). Cumulative: 0.28, 0.70, 0.82, 1.00.
    values, method = emv_percentiles([(D("0.3"), D("1000")), (D("0.6"), D("200"))])
    assert method == "exact"
    assert values[50] == D("200")
    assert values[80] == D("1000")


def test_percentiles_certain_risk_is_its_impact():
    values, _ = emv_percentiles([(D("1"), D("40"))])
    assert values == {50: D("40"), 80: D("40")}


def test_percentiles_fall_back_to_normal_approximation_for_large_registers():
    # Impacts 2^i make every subset total distinct, so 20 risks would give
    # 2^20 outcomes, past the cap.
    outcomes = [(D("0.5"), D(2**i)) for i in range(20)]
    values, method = emv_percentiles(outcomes)
    assert method == "normal_approximation"
    mean = sum(p * i for p, i in outcomes)
    assert values[50] == mean
    assert mean < values[80] <= sum(i for _, i in outcomes)


# ── The position ──────────────────────────────────────────────────────────


def test_closed_drops_out_and_a_pending_occurred_risk_counts_in_full():
    risks = [
        _risk("a", "0.5", "1000"),
        _risk("b", "0.2", "5000", status="closed"),
        _risk("c", "0.9", "3000", status="occurred"),
        _risk("d", "0.1", "2000", status="mitigated"),
    ]
    pos = build_position(risks, [_line("L1", "1000")], project_currency="EUR", fx={})
    # 0.5 x 1000 + 0.1 x 2000 + 1 x 3000 = 3700. Counting the closed risk
    # would add 1000; dropping the occurred one would say 700; counting it at
    # its old probability would say 3400.
    assert pos["emv"] == D("3700.00")
    assert pos["emv_by_currency"] == {"EUR": D("3700.00")}
    assert pos["active_risk_count"] == 2
    assert pos["excluded_closed_count"] == 1
    assert [p["risk_id"] for p in pos["pending"]] == ["c"]
    assert pos["pending"][0]["proposed_amount"] == D("3000.00")
    assert pos["pending"][0]["proposed_budget_id"] == "L1"
    # The occurred cost is certain, so it shifts both percentiles by 3000.
    assert pos["p50"] >= D("3000.00")
    assert pos["state"] == "shortfall"


def _stage(status: str, *, drawn: str | None = None, allocated: str = "100000") -> dict:
    """One open risk (p 0.5, impact 100 000) at a stage of its life."""
    risks = [_risk("r", "0.5", "100000", status=status)]
    drawdowns = (
        (DrawdownRecord(source="risk:r", risk_id="r", amount=D(drawn), currency="EUR"),) if drawn is not None else ()
    )
    return build_position(risks, [_line("L", allocated, drawdowns=drawdowns)], project_currency="EUR", fx={})


def test_a_risk_occurring_never_improves_the_position():
    """The finding's case, followed through its three stages.

    Allocated 100 000. Open at p 0.5: 50 000 to spare. Occurred and waiting:
    the full 100 000 is about to go, so nothing is to spare (the old rule said
    100 000 to spare). Confirmed at 100 000: drawn, out of EMV, still nothing
    to spare (a rule counting it twice would say 100 000 short).
    """
    open_ = _stage("open")
    assert (open_["emv"], open_["coverage_gap"], open_["state"]) == (D("50000.00"), D("50000.00"), "covered")

    pending = _stage("occurred")
    assert pending["emv"] == D("100000.00")
    assert pending["drawn"] == D("0.00")
    assert pending["remaining"] == D("100000.00")
    assert pending["coverage_gap"] == D("0.00")
    assert pending["coverage_gap"] <= open_["coverage_gap"]

    confirmed = _stage("occurred", drawn="100000")
    assert confirmed["emv"] == D("0.00")
    assert confirmed["drawn"] == D("100000.00")
    assert confirmed["remaining"] == D("0.00")
    assert confirmed["coverage_gap"] == D("0.00")
    assert confirmed["pending"] == []
    assert confirmed["excluded_drawn_count"] == 1


def test_a_pending_occurred_risk_turns_a_thin_cover_into_a_shortfall():
    # Allocated 80 000: covered while open (gap +30 000), short once it occurs
    # (gap -20 000). The old rule showed it covered with 80 000 to spare.
    assert _stage("open", allocated="80000")["state"] == "covered"
    pending = _stage("occurred", allocated="80000")
    assert pending["state"] == "shortfall"
    assert pending["coverage_gap"] == D("-20000.00")
    # Confirming a smaller actual cost than the impact frees the difference.
    settled = _stage("occurred", drawn="60000", allocated="80000")
    assert settled["state"] == "covered"
    assert settled["coverage_gap"] == D("20000.00")


def test_pending_occurred_risk_without_a_rate_is_reported_apart():
    risks = [_risk("g", "0.1", "800", status="occurred", currency="GBP")]
    pos = build_position(risks, [_line("L", "5000")], project_currency="EUR", fx={})
    assert pos["emv"] == D("0.00")
    assert pos["unconverted_emv"] == {"GBP": D("800.00")}
    assert pos["missing_fx_rates"] == ["GBP"]


def test_foreign_currency_converted_not_summed_in_own_units():
    # 1 USD = 0.5 EUR in the project table. A naive sum would give
    # 0.5 x 1000 + 0.5 x 1000 = 1000; converted it is 500 + 250 = 750.
    risks = [_risk("a", "0.5", "1000", currency="EUR"), _risk("b", "0.5", "1000", currency="USD")]
    pos = build_position(risks, [], project_currency="EUR", fx={"USD": D("0.5")})
    assert pos["emv"] == D("750.00")
    assert pos["emv_by_currency"] == {"EUR": D("500.00"), "USD": D("500.00")}
    assert pos["unconverted_emv"] == {}
    assert pos["missing_fx_rates"] == []


def test_currency_without_rate_is_reported_apart():
    risks = [_risk("a", "0.5", "1000", currency="EUR"), _risk("b", "0.5", "800", currency="GBP")]
    pos = build_position(risks, [], project_currency="EUR", fx={})
    assert pos["emv"] == D("500.00")
    assert pos["unconverted_emv"] == {"GBP": D("400.00")}
    assert pos["missing_fx_rates"] == ["GBP"]


def test_zero_decimal_currency_rounds_to_whole_units():
    risks = [_risk("a", "0.33", "1001", currency="JPY")]
    pos = build_position(risks, [_line("L", "500", currency="JPY")], project_currency="JPY", fx={})
    assert pos["emv"] == D("330")
    assert str(pos["emv"]) == "330"


def test_allocated_drawn_remaining_and_state():
    dd = DrawdownRecord(source="risk:x", risk_id="x", amount=D("300"), currency="EUR", risk_code="R-9")
    lines = [_line("L1", "1000", drawdowns=(dd,)), _line("L2", "500")]
    risks = [_risk("a", "0.5", "1000"), _risk("x", "0.9", "300", status="occurred")]
    pos = build_position(risks, lines, project_currency="EUR", fx={})
    assert pos["allocated"] == D("1500.00")
    assert pos["drawn"] == D("300.00")
    assert pos["remaining"] == D("1200.00")
    assert pos["emv"] == D("500.00")
    assert pos["coverage_gap"] == D("700.00")
    assert pos["state"] == "covered"
    # A drawn risk is neither pending nor in EMV.
    assert pos["pending"] == []
    assert pos["excluded_drawn_count"] == 1
    # Per-line figures: the untouched line stays exactly as allocated.
    by_id = {ln["budget_id"]: ln for ln in pos["lines"]}
    assert by_id["L1"]["drawn"] == D("300.00")
    assert by_id["L1"]["remaining"] == D("700.00")
    assert by_id["L2"]["drawn"] == D("0.00")
    assert by_id["L2"]["remaining"] == D("500.00")
    # Line deltas sum to the total drawn.
    assert sum(ln["drawn"] for ln in pos["lines"]) == pos["drawn"]


def test_drawn_risk_reopened_is_not_counted_again():
    dd = DrawdownRecord(source="risk:x", risk_id="x", amount=D("300"), currency="EUR")
    risks = [_risk("x", "0.9", "300", status="open")]
    pos = build_position(risks, [_line("L1", "1000", drawdowns=(dd,))], project_currency="EUR", fx={})
    assert pos["emv"] == D("0.00")
    assert pos["drawn"] == D("300.00")


def test_drawdown_of_a_deleted_risk_still_counts():
    dd = DrawdownRecord(source="risk:gone", risk_id="gone", amount=D("200"), currency="EUR", risk_code="R-004")
    pos = build_position([], [_line("L1", "1000", drawdowns=(dd,))], project_currency="EUR", fx={})
    assert pos["drawn"] == D("200.00")
    assert pos["remaining"] == D("800.00")
    assert pos["drawdowns"][0]["risk_code"] == "R-004"


def test_states_shortfall_overdrawn_and_no_allocation():
    risks = [_risk("a", "0.5", "1000")]
    assert build_position(risks, [], project_currency="EUR", fx={})["state"] == "no_allocation"
    assert build_position(risks, [_line("L", "400")], project_currency="EUR", fx={})["state"] == "shortfall"
    dd = DrawdownRecord(source="risk:z", risk_id="z", amount=D("600"), currency="EUR")
    over = build_position(risks, [_line("L", "400", drawdowns=(dd,))], project_currency="EUR", fx={})
    assert over["state"] == "overdrawn"
    assert over["remaining"] == D("-200.00")


def test_line_in_foreign_currency_converts_into_totals():
    lines = [_line("L1", "1000", currency="EUR"), _line("L2", "1000", currency="USD")]
    pos = build_position([], lines, project_currency="EUR", fx={"USD": D("0.5")})
    # Naive sum 2000, converted 1500.
    assert pos["allocated"] == D("1500.00")
    pos_missing = build_position([], lines, project_currency="EUR", fx={})
    assert pos_missing["allocated"] == D("1000.00")
    assert pos_missing["missing_fx_rates"] == ["USD"]
    assert {ln["budget_id"]: ln["converted"] for ln in pos_missing["lines"]} == {"L1": True, "L2": False}


def test_pending_proposal_converts_into_line_currency():
    # Risk in USD, the only line in EUR, 1 USD = 0.5 EUR: propose 500 EUR.
    risks = [_risk("r", "1", "1000", status="occurred", currency="USD")]
    pos = build_position(risks, [_line("L", "5000")], project_currency="EUR", fx={"USD": D("0.5")})
    assert pos["pending"][0]["proposed_amount"] == D("500.00")
    assert pos["pending"][0]["proposed_currency"] == "EUR"


def test_pending_without_any_line_has_no_proposal():
    risks = [_risk("r", "1", "1000", status="occurred")]
    pos = build_position(risks, [], project_currency="EUR", fx={})
    assert pos["pending"][0]["proposed_amount"] is None
    assert pos["pending"][0]["proposed_budget_id"] is None


def test_default_line():
    a = _line("A", "1", currency="EUR")
    b = _line("B", "1", currency="USD")
    c = _line("C", "1", currency="EUR")
    assert default_line([a], "EUR") is a
    assert default_line([a, b], "EUR") is a
    assert default_line([a, b, c], "EUR") is None
    assert default_line([], "EUR") is None
