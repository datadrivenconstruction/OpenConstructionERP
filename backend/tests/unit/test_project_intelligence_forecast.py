# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-logic unit tests for predictive forecast analytics (TOP-30 #19).

Covers every formula and guard in
``app.modules.project_intelligence.forecast`` with no database:

* ``compute_cost_forecast`` — CPI / SPI / EAC / ETC / VAC / TCPI, plus the
  division-by-zero guards (no AC, no PV, BAC == AC) and the TCPI
  not-achievable sentinel.
* ``project_schedule_slip`` — finish-variance projection (late / ahead /
  on-track), at-risk task counting, and the empty / no-baseline degradations.
* ``score_cost_overrun_risk`` — RAG banding, confidence from present signals,
  schedule nudge, and the always-non-empty rationale.
* ``degraded_cost_forecast`` — graceful "unavailable" payloads.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.project_intelligence.forecast import (
    RAG_AMBER_THRESHOLD,
    RAG_RED_THRESHOLD,
    TCPI_NOT_ACHIEVABLE,
    compute_cost_forecast,
    degraded_cost_forecast,
    project_schedule_slip,
    score_cost_overrun_risk,
    to_decimal,
)


def _d(value: str) -> Decimal:
    return Decimal(value)


# ── compute_cost_forecast: nominal EVM math ─────────────────────────────────


def test_cost_forecast_over_budget_indices_and_eac() -> None:
    """Classic over-budget snapshot: BAC 1.0M, EV 0.6M, AC 0.7M, PV 0.63M."""
    fc = compute_cost_forecast(
        bac=_d("1000000"),
        ev=_d("600000"),
        ac=_d("700000"),
        pv=_d("630000"),
        currency="EUR",
        snapshot_date="2026-06-04",
    )
    assert fc.available is True
    assert fc.currency == "EUR"
    # CPI = 600000 / 700000 = 0.8571
    assert fc.cpi == 0.8571
    # SPI = 600000 / 630000 = 0.9524
    assert fc.spi == 0.9524
    # EAC = BAC / CPI = 1000000 / 0.857142857 = 1166666.67
    assert fc.eac == "1166666.67"
    # ETC = EAC - AC = 1166666.67 - 700000 = 466666.67
    assert fc.etc == "466666.67"
    # VAC = BAC - EAC = 1000000 - 1166666.67 = -166666.67 (over budget)
    assert fc.vac == "-166666.67"
    # TCPI = (BAC - EV) / (BAC - AC) = 400000 / 300000 = 1.3333
    assert fc.tcpi == "1.3333"
    assert fc.eac_over_bac == 1.1667


def test_cost_forecast_on_budget_eac_equals_bac() -> None:
    """CPI exactly 1.0 → EAC == BAC, VAC == 0."""
    fc = compute_cost_forecast(bac=_d("500000"), ev=_d("250000"), ac=_d("250000"), pv=_d("250000"))
    assert fc.cpi == 1.0
    assert fc.eac == "500000.00"
    assert fc.vac == "0.00"
    assert fc.eac_over_bac == 1.0


def test_cost_forecast_under_budget_positive_vac() -> None:
    """CPI > 1.0 (under budget) → positive VAC."""
    fc = compute_cost_forecast(bac=_d("100000"), ev=_d("60000"), ac=_d("50000"), pv=_d("60000"))
    # CPI = 60000/50000 = 1.2 → EAC = 100000/1.2 = 83333.33 → VAC = +16666.67
    assert fc.cpi == 1.2
    assert fc.eac == "83333.33"
    assert fc.vac == "16666.67"


# ── compute_cost_forecast: division-by-zero guards ──────────────────────────


def test_cost_forecast_no_actuals_cpi_none_eac_falls_back_to_bac() -> None:
    """AC == 0 (no actuals): CPI undefined, EAC falls back to BAC."""
    fc = compute_cost_forecast(bac=_d("1000000"), ev=_d("0"), ac=_d("0"), pv=_d("100000"))
    assert fc.cpi is None
    assert fc.eac == "1000000.00"
    assert fc.etc == "1000000.00"  # EAC - AC = 1000000 - 0
    assert fc.vac == "0.00"


def test_cost_forecast_no_planned_value_spi_none() -> None:
    """PV == 0: SPI is None (cannot divide), CPI still computes."""
    fc = compute_cost_forecast(bac=_d("100000"), ev=_d("50000"), ac=_d("40000"), pv=_d("0"))
    assert fc.spi is None
    assert fc.cpi == 1.25


def test_cost_forecast_tcpi_not_achievable_sentinel() -> None:
    """BAC == AC with work remaining → TCPI is the not-achievable sentinel."""
    fc = compute_cost_forecast(bac=_d("100000"), ev=_d("80000"), ac=_d("100000"), pv=_d("90000"))
    assert fc.tcpi == TCPI_NOT_ACHIEVABLE


def test_cost_forecast_tcpi_one_when_complete() -> None:
    """BAC == AC == EV (done, on budget) → TCPI 1.0, not the sentinel."""
    fc = compute_cost_forecast(bac=_d("100000"), ev=_d("100000"), ac=_d("100000"), pv=_d("100000"))
    assert fc.tcpi == "1.0"


def test_degraded_cost_forecast_carries_reason() -> None:
    fc = degraded_cost_forecast("no_evm_snapshot", currency="USD")
    assert fc.available is False
    assert fc.reason == "no_evm_snapshot"
    assert fc.currency == "USD"
    assert fc.eac is None


# ── to_decimal guard ────────────────────────────────────────────────────────


def test_to_decimal_handles_garbage_and_empty() -> None:
    assert to_decimal("not-a-number") == Decimal("0")
    assert to_decimal("") == Decimal("0")
    assert to_decimal(None) == Decimal("0")
    assert to_decimal("12.5") == Decimal("12.5")
    assert to_decimal(None, default=Decimal("7")) == Decimal("7")


# ── project_schedule_slip ───────────────────────────────────────────────────


def test_schedule_slip_empty_activities_unavailable() -> None:
    slip = project_schedule_slip(activities=[], baseline_finish="2026-12-31")
    assert slip.available is False
    assert slip.reason == "no_schedule_activities"


def test_schedule_slip_behind_projects_late_finish() -> None:
    """Activities running behind plan project a finish later than baseline."""
    activities = [
        {"planned_pct": _d("80"), "actual_pct": _d("40"), "end_date": "2026-12-31"},
        {"planned_pct": _d("80"), "actual_pct": _d("40"), "end_date": "2026-12-31"},
    ]
    slip = project_schedule_slip(
        activities=activities,
        baseline_finish="2026-12-31",
        data_date="2026-06-01",
    )
    assert slip.available is True
    assert slip.activities_total == 2
    # actual 40 < planned 80 by 40pp > 10pp threshold, not complete → both at risk
    assert slip.at_risk_task_count == 2
    # SPI_t = 40/80 = 0.5 → remaining span stretched ×2 → late finish.
    assert slip.finish_variance_days is not None
    assert slip.finish_variance_days > 0


def test_schedule_slip_ahead_projects_early_finish() -> None:
    """Running ahead of plan projects an earlier finish (negative variance)."""
    activities = [
        {"planned_pct": _d("50"), "actual_pct": _d("75"), "end_date": "2026-12-31"},
    ]
    slip = project_schedule_slip(
        activities=activities,
        baseline_finish="2026-12-31",
        data_date="2026-06-01",
    )
    # SPI_t = 75/50 = 1.5 → remaining span compressed → earlier finish.
    assert slip.finish_variance_days is not None
    assert slip.finish_variance_days < 0
    assert slip.at_risk_task_count == 0


def test_schedule_slip_on_track_zero_variance() -> None:
    """Actual == planned → SPI_t 1.0 → finish on the baseline date."""
    activities = [
        {"planned_pct": _d("60"), "actual_pct": _d("60"), "end_date": "2026-12-31"},
    ]
    slip = project_schedule_slip(
        activities=activities,
        baseline_finish="2026-12-31",
        data_date="2026-06-01",
    )
    assert slip.finish_variance_days == 0


def test_schedule_slip_no_planned_progress_degrades() -> None:
    """Zero planned progress → cannot project a variance, dates left None."""
    activities = [
        {"planned_pct": _d("0"), "actual_pct": _d("0"), "end_date": "2026-12-31"},
    ]
    slip = project_schedule_slip(
        activities=activities,
        baseline_finish="2026-12-31",
        data_date="2026-06-01",
    )
    assert slip.available is True
    assert slip.finish_variance_days is None
    assert slip.reason == "insufficient_progress_or_no_baseline_finish"


def test_schedule_slip_complete_activity_counted() -> None:
    activities = [
        {"planned_pct": _d("100"), "actual_pct": _d("100"), "end_date": "2026-01-31"},
        {"planned_pct": _d("80"), "actual_pct": _d("30"), "end_date": "2026-12-31"},
    ]
    slip = project_schedule_slip(
        activities=activities,
        baseline_finish="2026-12-31",
        data_date="2026-06-01",
    )
    assert slip.activities_complete == 1
    assert slip.at_risk_task_count == 1  # only the second (behind, not complete)


# ── score_cost_overrun_risk ─────────────────────────────────────────────────


def test_risk_score_healthy_project_green() -> None:
    """On-plan CPI/SPI, no overrun, no risks → green band, low score."""
    risk = score_cost_overrun_risk(
        cpi=1.05,
        spi=1.02,
        vac=_d("50000"),
        bac=_d("1000000"),
        finish_variance_days=0,
        open_high_severity_risks=0,
    )
    assert risk.band == "green"
    assert risk.score < float(RAG_AMBER_THRESHOLD)
    assert risk.rationale  # never empty
    # All four signals present → full confidence.
    assert risk.confidence == 1.0


def test_risk_score_severe_overrun_red() -> None:
    """Deep CPI shortfall + big overrun + many risks + late finish → red."""
    risk = score_cost_overrun_risk(
        cpi=0.55,
        spi=0.6,
        vac=_d("-300000"),
        bac=_d("1000000"),
        finish_variance_days=120,
        open_high_severity_risks=6,
    )
    assert risk.band == "red"
    assert risk.score >= float(RAG_RED_THRESHOLD)
    assert any("CPI" in r for r in risk.rationale)
    assert any("late" in r for r in risk.rationale)


def test_risk_score_moderate_amber() -> None:
    """A mid CPI shortfall with a small overrun lands amber."""
    risk = score_cost_overrun_risk(
        cpi=0.85,
        spi=0.9,
        vac=_d("-90000"),
        bac=_d("1000000"),
        finish_variance_days=10,
        open_high_severity_risks=2,
    )
    assert risk.band == "amber"
    assert float(RAG_AMBER_THRESHOLD) <= risk.score < float(RAG_RED_THRESHOLD)


def test_risk_score_partial_signals_lower_confidence() -> None:
    """Only CPI present (no SPI/VAC) → confidence below 1.0 but score honest."""
    risk = score_cost_overrun_risk(
        cpi=0.7,
        spi=None,
        vac=None,
        bac=None,
        finish_variance_days=None,
        open_high_severity_risks=0,
    )
    # Present weight = CPI(0.35) + risks(0.20) = 0.55 of total 1.0.
    assert risk.confidence == 0.55
    assert risk.score > 0.0


def test_risk_score_rationale_never_empty_even_when_clean() -> None:
    """A perfectly clean project still gets an explanatory rationale line."""
    risk = score_cost_overrun_risk(
        cpi=1.0,
        spi=1.0,
        vac=_d("0"),
        bac=_d("100000"),
        finish_variance_days=0,
        open_high_severity_risks=0,
    )
    assert len(risk.rationale) >= 1


def test_risk_score_no_signals_at_all_floors_safely() -> None:
    """No cost signals, no risks: score 0, green, risks-only confidence."""
    risk = score_cost_overrun_risk(
        cpi=None,
        spi=None,
        vac=None,
        bac=None,
        finish_variance_days=None,
        open_high_severity_risks=0,
    )
    assert risk.score == 0.0
    assert risk.band == "green"
    # Only the always-present risks signal counted → 0.20 / 1.0.
    assert risk.confidence == 0.2
    assert risk.rationale
