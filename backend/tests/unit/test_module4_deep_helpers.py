"""Unit tests for the wave-A deep-dive helpers.

Covers the new pure helpers added across 4 modules:

* ``property_dev``: ``compute_deposit_forfeiture`` (10 jurisdictions +
  cooling-off + unknown jurisdiction fallback).
* ``variations``: ``compute_nec4_timers`` + ``is_nec4_overdue`` +
  ``apply_daywork_markup`` + ``compute_disruption_lost_hours``.
* ``schedule_advanced``: ``cpm_forward_backward_pass`` (critical path
  identification) + ``time_impact_analysis`` (delay impact) +
  ``compute_evm`` (PV/EV/AC/SPI/CPI/EAC) +
  ``compute_rnc_pareto_sorted`` + ``constraint_ready_state``.
* ``bid_management``: ``render_invitation_email`` template merge.

All tests are pure-function tests — no DB, no I/O.
"""

from __future__ import annotations

from datetime import date as dt_date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.bid_management.service import BidManagementService
from app.modules.property_dev.service import (
    compute_deposit_forfeiture,
    supported_jurisdictions,
)
from app.modules.schedule_advanced.service import (
    compute_evm,
    compute_rnc_pareto_sorted,
    constraint_ready_state,
    cpm_forward_backward_pass,
    time_impact_analysis,
)
from app.modules.variations.service import (
    apply_daywork_markup,
    compute_disruption_lost_hours,
    compute_nec4_timers,
    default_clause_for_standard,
    is_nec4_overdue,
    supported_contract_standards,
)

# ─────────────────────────────────────────────────────────────────────────
# property_dev: deposit forfeiture per jurisdiction
# ─────────────────────────────────────────────────────────────────────────


class TestDepositForfeiture:
    def test_uk_full_forfeit(self) -> None:
        result = compute_deposit_forfeiture("10000.00", "GB")
        assert result["forfeited_amount"] == Decimal("10000.00")
        assert result["refundable_amount"] == Decimal("0.00")
        assert "PRA" in result["rule_citation"]

    def test_germany_zero_forfeit(self) -> None:
        # DE has zero default forfeiture under BGB.
        result = compute_deposit_forfeiture("10000.00", "DE")
        assert result["forfeited_amount"] == Decimal("0.00")
        assert result["refundable_amount"] == Decimal("10000.00")
        assert "BGB" in result["rule_citation"]

    def test_cooling_off_overrides_jurisdiction(self) -> None:
        # Even GB returns full refund inside cooling-off / pre-exchange window.
        result = compute_deposit_forfeiture(
            "10000.00",
            "GB",
            cancelled_before_contract=True,
        )
        assert result["forfeited_amount"] == Decimal("0")
        assert result["refundable_amount"] == Decimal("10000.00")
        # The rule summary explicitly mentions full refund pre-contract.
        assert "full refund" in result["rule_summary"].lower()

    def test_unknown_jurisdiction_falls_back_to_generic(self) -> None:
        # No "ZZ" rule loaded → generic common-law default.
        result = compute_deposit_forfeiture("5000.00", "ZZ")
        assert result["forfeited_amount"] == Decimal("5000.00")
        assert "Generic" in result["rule_citation"]

    def test_zero_deposit(self) -> None:
        result = compute_deposit_forfeiture("0", "GB")
        assert result["forfeited_amount"] == Decimal("0.00")
        assert result["refundable_amount"] == Decimal("0.00")

    def test_supported_jurisdictions_includes_core_markets(self) -> None:
        codes = supported_jurisdictions()
        for code in ("GB", "DE", "FR", "ES", "US", "AE"):
            assert code in codes


# ─────────────────────────────────────────────────────────────────────────
# variations: NEC4 timers + daywork markup + disruption measured-mile
# ─────────────────────────────────────────────────────────────────────────


class TestNEC4Timers:
    def test_default_timers_3w_4w(self) -> None:
        result = compute_nec4_timers(dt_date(2026, 1, 1))
        # 3 weeks → 2026-01-22, +4 weeks → 2026-02-19
        assert result["quotation_due_at"] == "2026-01-22"
        assert result["assessment_due_at"] == "2026-02-19"

    def test_custom_windows(self) -> None:
        result = compute_nec4_timers(
            dt_date(2026, 1, 1),
            quotation_weeks=2,
            assessment_weeks=2,
        )
        assert result["quotation_due_at"] == "2026-01-15"
        assert result["assessment_due_at"] == "2026-01-29"

    def test_iso_string_input_accepted(self) -> None:
        result = compute_nec4_timers("2026-01-01")
        assert result["quotation_due_at"] == "2026-01-22"

    def test_overdue_quotation(self) -> None:
        request = SimpleNamespace(
            quotation_due_at="2026-01-01",
            assessment_due_at="2026-02-01",
            submitted_at=None,
            decision_at=None,
        )
        result = is_nec4_overdue(request, today=dt_date(2026, 1, 15))
        assert result["quotation_overdue"] is True
        assert result["assessment_overdue"] is False

    def test_overdue_when_submitted_resets_quotation_flag(self) -> None:
        request = SimpleNamespace(
            quotation_due_at="2026-01-01",
            assessment_due_at="2026-02-01",
            submitted_at="2026-01-05",
            decision_at=None,
        )
        result = is_nec4_overdue(request, today=dt_date(2026, 1, 15))
        # Submitted on time → no quotation overdue, but still no decision.
        assert result["quotation_overdue"] is False
        assert result["assessment_overdue"] is False

    def test_assessment_overdue(self) -> None:
        request = SimpleNamespace(
            quotation_due_at="2026-01-01",
            assessment_due_at="2026-02-01",
            submitted_at="2026-01-05",
            decision_at=None,
        )
        result = is_nec4_overdue(request, today=dt_date(2026, 2, 15))
        assert result["assessment_overdue"] is True


class TestContractStandards:
    def test_supported_includes_fidic_jct_nec4(self) -> None:
        std = supported_contract_standards()
        # We model the named-form variants of each standard.
        assert any("FIDIC" in s for s in std)
        assert any("JCT" in s for s in std)
        assert any("NEC4" in s for s in std)

    def test_default_clause_for_fidic_red_book(self) -> None:
        # FIDIC variation clause is 13.
        assert "13" in default_clause_for_standard("FIDIC_RED_2017")

    def test_default_clause_for_jct(self) -> None:
        # JCT SBC 2016 — Clause 5 (Variations / Changes).
        assert "5" in default_clause_for_standard("JCT_SBC_2016")

    def test_default_clause_for_nec4(self) -> None:
        # NEC4 ECC — Compensation Events Clauses 60–65.
        assert "60" in default_clause_for_standard("NEC4_ECC")

    def test_unknown_standard_returns_empty(self) -> None:
        assert default_clause_for_standard("UNKNOWN") == ""


class TestDayworkMarkup:
    def test_zero_markup(self) -> None:
        assert apply_daywork_markup("1000", "0") == Decimal("1000.00")

    def test_standard_markup_20_pct(self) -> None:
        # BS 6079 typical OH&P markup.
        assert apply_daywork_markup("1000", "20") == Decimal("1200.00")

    def test_fractional_markup(self) -> None:
        assert apply_daywork_markup("1000", "12.5") == Decimal("1125.00")

    def test_none_markup_treated_as_zero(self) -> None:
        assert apply_daywork_markup("500", None) == Decimal("500.00")


class TestMeasuredMileDisruption:
    def test_basic_lost_hours(self) -> None:
        # Baseline: 2 units/hour → 0.5 h/unit
        # Impacted: 1 unit/hour → 1.0 h/unit
        # Over 100 units → 100*(1.0 - 0.5) = 50 hours lost.
        result = compute_disruption_lost_hours("2", "1", "100")
        assert result == Decimal("50.00")

    def test_impacted_equals_baseline_yields_zero(self) -> None:
        # No disruption.
        assert compute_disruption_lost_hours("2", "2", "100") == Decimal("0")

    def test_impacted_better_than_baseline_yields_zero(self) -> None:
        # Productivity improved — no claim.
        assert compute_disruption_lost_hours("1", "2", "100") == Decimal("0")

    def test_zero_quantity_yields_zero(self) -> None:
        assert compute_disruption_lost_hours("2", "1", "0") == Decimal("0")

    def test_zero_productivity_yields_zero(self) -> None:
        assert compute_disruption_lost_hours("0", "1", "100") == Decimal("0")
        assert compute_disruption_lost_hours("2", "0", "100") == Decimal("0")


# ─────────────────────────────────────────────────────────────────────────
# schedule_advanced: CPM + TIA + EVM + RNC pareto + constraint readiness
# ─────────────────────────────────────────────────────────────────────────


class TestCPMForwardBackward:
    def test_two_serial_activities(self) -> None:
        activities = [
            {"id": "A", "duration": 5},
            {"id": "B", "duration": 3},
        ]
        deps = [{"predecessor": "A", "successor": "B"}]
        result = cpm_forward_backward_pass(activities, deps)
        # ES_A=0, EF_A=5, ES_B=5, EF_B=8 → project duration 8.
        # Result is a dict keyed by activity id (str).
        assert result["A"]["es"] == 0
        assert result["A"]["ef"] == 5
        assert result["B"]["es"] == 5
        assert result["B"]["ef"] == 8
        assert result["A"]["total_float"] == 0
        assert result["B"]["total_float"] == 0
        assert result["A"]["is_critical"] is True
        assert result["B"]["is_critical"] is True

    def test_parallel_branch_creates_float(self) -> None:
        # A=5 in parallel with B=3, both feed C=2. A is critical, B has float.
        activities = [
            {"id": "A", "duration": 5},
            {"id": "B", "duration": 3},
            {"id": "C", "duration": 2},
        ]
        deps = [
            {"predecessor": "A", "successor": "C"},
            {"predecessor": "B", "successor": "C"},
        ]
        result = cpm_forward_backward_pass(activities, deps)
        # A is critical (longest), B has 2-day float.
        assert result["A"]["is_critical"] is True
        assert result["A"]["total_float"] == 0
        assert result["B"]["total_float"] == 2
        assert result["B"]["is_critical"] is False
        assert result["C"]["is_critical"] is True


class TestTimeImpactAnalysis:
    def test_delay_on_critical_extends_project(self) -> None:
        activities = [
            {"id": "A", "duration": 5},
            {"id": "B", "duration": 3},
        ]
        deps = [{"predecessor": "A", "successor": "B"}]
        result = time_impact_analysis(
            activities,
            deps,
            impacted_activity_id="A",
            delay_days=4,
        )
        # Baseline 8, impacted 12 → extension 4
        assert result["original_finish_workday"] == 8
        assert result["impacted_finish_workday"] == 12
        assert result["delta_days"] == 4

    def test_delay_on_non_critical_consumes_float(self) -> None:
        # Parallel A=5, B=3 → C=2. Delay B by 1 day — still within float.
        activities = [
            {"id": "A", "duration": 5},
            {"id": "B", "duration": 3},
            {"id": "C", "duration": 2},
        ]
        deps = [
            {"predecessor": "A", "successor": "C"},
            {"predecessor": "B", "successor": "C"},
        ]
        result = time_impact_analysis(
            activities,
            deps,
            impacted_activity_id="B",
            delay_days=1,
        )
        # B has 2-day float; 1-day delay is absorbed.
        assert result["delta_days"] == 0


class TestEVM:
    def test_on_track_spi_cpi_one(self) -> None:
        # Single activity, baseline 10 days, today=5, 50% complete, AC=50% BAC.
        activities = [
            {
                "id": "A",
                "planned_start_workday": 0,
                "planned_finish_workday": 10,
                "budget_at_completion": "1000",
                "percent_complete": "50",
                "actual_cost": "500",
            },
        ]
        result = compute_evm(activities, today_workday=5)
        # PV should be 500 (50% planned), EV=500, AC=500 → SPI=1.0, CPI=1.0
        assert result["pv"] == Decimal("500.00")
        assert result["ev"] == Decimal("500.00")
        assert result["ac"] == Decimal("500.00")
        assert result["spi"] == Decimal("1.0000")
        assert result["cpi"] == Decimal("1.0000")

    def test_behind_schedule_overrun_cost(self) -> None:
        # Should be 50% done, actually 25% done, spent 60%.
        activities = [
            {
                "id": "A",
                "planned_start_workday": 0,
                "planned_finish_workday": 10,
                "budget_at_completion": "1000",
                "percent_complete": "25",
                "actual_cost": "600",
            },
        ]
        result = compute_evm(activities, today_workday=5)
        # PV=500, EV=250, AC=600
        # SPI=0.5, CPI≈0.416..., EAC = AC + (BAC-EV)/CPI
        assert result["pv"] == Decimal("500.00")
        assert result["ev"] == Decimal("250.00")
        assert result["ac"] == Decimal("600.00")
        assert result["spi"] == Decimal("0.5000")
        assert result["cpi"] < Decimal("0.5")
        # SV = EV-PV = -250 (behind), CV = EV-AC = -350 (over budget)
        assert result["sv"] == Decimal("-250.00")
        assert result["cv"] == Decimal("-350.00")


class TestRNCParetoSorted:
    def test_sorted_by_count_desc(self) -> None:
        # The pareto helper uses a canonical category set; use ones that
        # are part of _RNC_CATEGORIES (manpower / material / equipment /
        # prerequisite / weather / safety / other are canonical LPS RNCs).
        rncs = [
            SimpleNamespace(category="material"),
            SimpleNamespace(category="weather"),
            SimpleNamespace(category="material"),
            SimpleNamespace(category="material"),
            SimpleNamespace(category="equipment"),
        ]
        result = compute_rnc_pareto_sorted(rncs)
        # material = 3 → should be the top row.
        assert result[0]["category"] == "material"
        assert result[0]["count"] == 3
        # Cumulative percent grows monotonically and ends at 100.
        prev = 0.0
        for row in result:
            assert row["cum_percent"] >= prev
            prev = row["cum_percent"]
        # Final cumulative percent should reach 100 (allowing rounding eps).
        assert result[-1]["cum_percent"] >= 99.99

    def test_empty_input_uses_canonical_set_with_zero_counts(self) -> None:
        # Empty input still emits the canonical category set with zero counts.
        result = compute_rnc_pareto_sorted([])
        assert len(result) > 0
        assert all(r["count"] == 0 for r in result)


class TestConstraintReadiness:
    def test_no_blockers_means_ready(self) -> None:
        result = constraint_ready_state("task-1", [])
        assert result["is_ready"] is True
        assert result["open_count"] == 0

    def test_open_constraint_blocks(self) -> None:
        constraints = [
            SimpleNamespace(
                id="c1",
                task_ref="task-1",
                status="open",
                type="materials",
                description="Awaiting steel delivery",
                target_clear_date="2026-01-15",
                owner_user_id=None,
            ),
        ]
        result = constraint_ready_state("task-1", constraints)
        assert result["is_ready"] is False
        assert result["open_count"] == 1
        assert len(result["blockers"]) == 1

    def test_cleared_constraint_does_not_block(self) -> None:
        constraints = [
            SimpleNamespace(
                id="c1",
                task_ref="task-1",
                status="cleared",
                type="materials",
                description="",
                target_clear_date=None,
                owner_user_id=None,
            ),
        ]
        result = constraint_ready_state("task-1", constraints)
        assert result["is_ready"] is True


# ─────────────────────────────────────────────────────────────────────────
# bid_management: invitation email template rendering
# ─────────────────────────────────────────────────────────────────────────


class TestInvitationEmailRender:
    def test_token_replacement(self) -> None:
        subj_tpl = "Invitation to bid: {package_code}"
        body_tpl = (
            "Dear {invitee_company_name},\n"
            "You are invited to bid on package {package_code} - "
            "{package_title}. Deadline: {deadline}.\n"
            "Link: {action_url}\n"
            "Regards,\n{sender_name}"
        )
        subj, body = BidManagementService.render_invitation_email(
            subj_tpl,
            body_tpl,
            package_code="BP-001",
            package_title="Concrete works",
            invitee_email="bid@example.com",
            invitee_company_name="ACME Construction",
            sender_name="John Doe",
            deadline="2026-02-01",
            action_url="/bid-management/packages/abc",
        )
        assert subj == "Invitation to bid: BP-001"
        assert "ACME Construction" in body
        assert "Concrete works" in body
        assert "2026-02-01" in body
        assert "John Doe" in body
        assert "{" not in body  # No unresolved tokens

    def test_unknown_token_left_literal(self) -> None:
        subj_tpl = "Hi {unknown_field}"
        body_tpl = "Hello {invitee_company_name}"
        subj, body = BidManagementService.render_invitation_email(
            subj_tpl,
            body_tpl,
            package_code="X",
            package_title="X",
            invitee_email="x@x.com",
            invitee_company_name="ACME",
        )
        assert "{unknown_field}" in subj
        assert "ACME" in body


# ─────────────────────────────────────────────────────────────────────────
# Sanity: imports + entry points all reachable
# ─────────────────────────────────────────────────────────────────────────


def test_helpers_are_pure_no_db_imports_needed() -> None:
    # All helpers tested above are pure — this is a meta-test that
    # importing them does not require a database/session.
    assert callable(compute_deposit_forfeiture)
    assert callable(compute_nec4_timers)
    assert callable(apply_daywork_markup)
    assert callable(compute_disruption_lost_hours)
    assert callable(cpm_forward_backward_pass)
    assert callable(time_impact_analysis)
    assert callable(compute_evm)
    assert callable(compute_rnc_pareto_sorted)
    assert callable(constraint_ready_state)
    assert callable(BidManagementService.render_invitation_email)
