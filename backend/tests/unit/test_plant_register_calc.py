# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure rules of the plant register (SPEC section 4), table-driven.

Each case names the rule it guards and would pass if the rule were missing
only by accident: the expected values differ from what the naive formula or
the permissive default would give.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.plant_register import calc
from app.modules.plant_register.fsm import ITEM_FSM, MANUAL_TARGETS, PAPER_FSM, SLOT_FSM, SPARE_FSM
from app.modules.plant_register.ports import OwnerFurnishedRef, PackagePlan, PackageRef

TODAY = date(2026, 10, 11)
B = calc.Buffers(transport_days=14, install_lead_days=21, approval_buffer_days=14, drawing_review_days=28)


def q(
    source="supplier_quote", enq=date(2026, 8, 3), resp=None, lo=52, hi=60, basis="from_order", is_basis=True, sup=False
):
    return calc.QuoteView(uuid.uuid4(), source, enq, resp, lo, hi, basis, is_basis, sup)


# ── rule 5: latest order date ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("need", "weeks", "basis", "review", "expected"),
    [
        # SPEC example, quote B: 44 wk from approved drawings, review 28 d, buffers 14/21/14 = 385 days.
        (date(2027, 11, 15), 44, "from_approved_drawings", None, date(2026, 10, 26)),
        # Same item, linked submittal reviews in 10 days instead of the catalogue's 28.
        (date(2027, 11, 15), 44, "from_approved_drawings", 10, date(2026, 11, 13)),
        # From order: no review period subtracted even when a submittal is linked.
        (date(2027, 11, 15), 44, "from_order", 10, date(2026, 11, 23)),
        (date(2027, 11, 15), 44, "from_down_payment", None, date(2026, 11, 23)),
        # Quote A: 60 wk from order.
        (date(2027, 11, 15), 60, "from_order", None, date(2026, 8, 3)),
        (None, 44, "from_order", None, None),
        (date(2027, 11, 15), None, "from_order", None, None),
    ],
)
def test_latest_order_date_table(need, weeks, basis, review, expected) -> None:
    assert calc.latest_order_date(need, weeks, basis, B, review_period_days=review) == expected


def test_item_buffer_override_wins_over_catalogue_and_ignores_junk() -> None:
    merged = calc.Buffers.merged(B, {"transport_days": 0, "install_lead_days": -3, "approval_buffer_days": True})
    assert merged == calc.Buffers(0, 21, 14, 28)


@pytest.mark.parametrize(
    ("late", "start", "fixed", "expected"),
    [
        ("2027-11-15", "2027-10-01", date(2027, 1, 1), (date(2027, 11, 15), "activity_late_start")),
        (None, "2027-10-01", date(2027, 1, 1), (date(2027, 10, 1), "activity_start")),
        (None, None, date(2027, 1, 1), (date(2027, 1, 1), "fixed")),
        ("not a date", None, None, (None, "none")),
    ],
)
def test_need_date_prefers_late_start_then_start_then_fixed(late, start, fixed, expected) -> None:
    assert calc.need_date(activity_late_start=late, activity_start=start, fixed=fixed) == expected


# ── rule 2: quote needs a dated enquiry ───────────────────────────────────


@pytest.mark.parametrize(
    ("enq", "resp", "lo", "hi", "errors"),
    [
        (None, None, 40, 44, ["lead_time_without_enquiry_date"]),
        (date(2026, 10, 12), None, 40, 44, ["enquiry_date_in_future"]),
        (date(2026, 8, 10), date(2026, 8, 9), 40, 44, ["response_before_enquiry"]),
        (date(2026, 8, 10), None, 50, 44, ["lead_weeks_range_invalid"]),
        (date(2026, 10, 11), date(2026, 10, 11), 44, 44, []),
    ],
)
def test_quote_errors(enq, resp, lo, hi, errors) -> None:
    assert calc.quote_errors(enquiry_date=enq, response_date=resp, lead_min=lo, lead_max=hi, today=TODAY) == errors


# ── rule 4 and effective lead ─────────────────────────────────────────────


def test_effective_lead_uses_basis_max_and_flags_catalogue_default() -> None:
    assert calc.effective_lead(q(hi=60), 84) == (60, "supplier_quote")
    assert calc.effective_lead(None, 84) == (84, calc.NO_MARKET_EVIDENCE)
    assert calc.effective_lead(None, None) == (None, "none")


def test_basis_ignores_superseded_and_needs_exactly_one() -> None:
    old = q(is_basis=False, sup=True)
    new = q(hi=44)
    assert calc.basis_quote([old, new]) is new
    assert calc.basis_count([old, new]) == 1
    # Two live bases is a broken state: no basis is reported rather than picking one.
    assert calc.basis_quote([q(), q()]) is None
    assert calc.basis_count([q(), q()]) == 2


# ── rule 3: stale ─────────────────────────────────────────────────────────


def test_quote_age_runs_from_response_else_enquiry_and_stale_is_strict() -> None:
    assert calc.quote_age_days(q(enq=date(2026, 7, 1), resp=date(2026, 7, 13)), TODAY) == 90
    assert calc.quote_age_days(q(enq=date(2026, 7, 13)), TODAY) == 90
    assert calc.is_stale(90, 90) is False
    assert calc.is_stale(91, 90) is True
    assert calc.is_stale(None, 90) is False


# ── rule 6: market evidence ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("source", "ok"),
    [
        ("supplier_quote", True),
        ("framework_agreement", True),
        (calc.NO_MARKET_EVIDENCE, False),
        ("expert_estimate", False),
    ],
)
def test_market_evidence(source, ok) -> None:
    market = {"supplier_quote", "framework_agreement", "historic_order", "market_sounding", "supplier_catalogue"}
    assert calc.has_market_evidence(source, market) is ok


# ── Decision 2: long-lead derived ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("weeks", "override", "expected"),
    [(12, None, True), (11, None, False), (None, None, False), (40, False, False), (4, True, True)],
)
def test_long_lead_is_derived_from_threshold_with_override(weeks, override, expected) -> None:
    assert calc.is_long_lead(weeks, 12, override) is expected


# ── rule 7: overdue ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("latest", "ordered", "expected"),
    [
        (date(2026, 10, 10), False, "overdue"),
        (date(2026, 10, 10), True, "ok"),
        (date(2026, 10, 11), False, "due_soon"),
        (date(2026, 11, 10), False, "due_soon"),
        (date(2026, 11, 11), False, "ok"),
        (None, False, "ok"),
    ],
)
def test_order_status(latest, ordered, expected) -> None:
    assert calc.order_status(latest, TODAY, ordered, 30) == expected


# ── rule 10: route against the package plan ───────────────────────────────

P_SUP = PackageRef(uuid.uuid4(), "P1", "Electrical", supplies=True, installs=True)
P_INS = PackageRef(uuid.uuid4(), "P2", "Install only", supplies=False, installs=True)
PLAN = PackagePlan("multi_package", (P_SUP, P_INS))
SINGLE = PackagePlan("single_point", (P_SUP, P_INS), single_owner_package_id=P_INS.id)
OFI_P2 = OwnerFurnishedRef(uuid.uuid4(), P_INS.id)
OFI_OWNER = OwnerFurnishedRef(uuid.uuid4(), None)
R = "route_inconsistent_with_package_plan"


@pytest.mark.parametrize(
    ("route", "pkg", "ofi", "plan", "errors"),
    [
        ("contractor_furnished_installed", P_SUP.id, None, PLAN, []),
        ("contractor_furnished_installed", P_INS.id, None, PLAN, [f"{R}:package_does_not_supply"]),
        ("contractor_furnished_installed", None, None, PLAN, [f"{R}:package_required"]),
        ("contractor_furnished_installed", uuid.uuid4(), None, PLAN, [f"{R}:package_not_in_plan"]),
        ("contractor_furnished_installed", P_SUP.id, None, SINGLE, [f"{R}:single_package_form"]),
        ("owner_furnished_contractor_installed", P_INS.id, OFI_P2, PLAN, []),
        ("owner_furnished_contractor_installed", P_SUP.id, OFI_P2, PLAN, [f"{R}:installer_mismatch"]),
        ("owner_furnished_contractor_installed", P_INS.id, None, PLAN, [f"{R}:owner_furnished_item_required"]),
        ("owner_furnished_owner_installed", None, OFI_OWNER, PLAN, []),
        ("owner_furnished_owner_installed", None, OFI_P2, PLAN, [f"{R}:owner_installs"]),
        ("owner_procured_novated", P_SUP.id, OFI_P2, PLAN, []),
        ("owner_procured_novated", None, OFI_P2, PLAN, [f"{R}:package_required"]),
        ("owner_procured_novated", P_SUP.id, None, PLAN, [f"{R}:owner_furnished_item_required"]),
        ("contractor_furnished_installed", P_SUP.id, None, None, ["package_plan_unavailable"]),
        (None, None, None, PLAN, ["route_missing"]),
    ],
)
def test_route_errors(route, pkg, ofi, plan, errors) -> None:
    assert calc.route_errors(route, pkg, ofi, plan) == errors


# ── rules 8, 9, 14, 15, 17 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("policy", "reason", "vendor", "findings"),
    [
        ("bound", "", None, ["vendor_bound_needs_reason"]),
        ("bound", "warranty", uuid.uuid4(), []),
        ("neutral", "", uuid.uuid4(), ["neutral_spec_names_vendor"]),
        ("neutral", "", None, []),
    ],
)
def test_vendor_findings(policy, reason, vendor, findings) -> None:
    assert calc.vendor_findings(policy, reason, vendor) == findings


def test_paper_needs_two_options_unless_sole_source() -> None:
    one = [{"code": "a"}]
    assert calc.paper_errors(one, "") == ["decision_paper_needs_two_options"]
    assert calc.paper_errors(one, "warranty") == ["decision_paper_needs_two_options"]
    assert calc.paper_errors(one, "sole_source") == []
    assert calc.paper_errors([{"code": "a"}, {"code": "b"}], "") == []


def test_weighted_scores_are_decimal_and_reject_floats() -> None:
    crit = [{"code": "lead", "weight": "4"}, {"code": "cost", "weight": "3"}, {"code": "service", "weight": "2"}]
    opts = [
        {"code": "a", "scores": {"lead": "2", "cost": "4", "service": "4"}},
        {"code": "b", "scores": {"lead": "4", "cost": "3", "service": "3"}},
    ]
    scores = calc.weighted_scores(opts, crit)
    assert scores == {"a": Decimal("3.1111"), "b": Decimal("3.4444")}
    with pytest.raises(ValueError):
        calc.weighted_scores([{"code": "a", "scores": {"lead": 2.5}}], crit)


def test_delivery_limit_gaps_in_step_order() -> None:
    assert calc.delivery_limit_gaps(("supply", "offload", "test"), {"offload": "contractor"}) == ["supply", "test"]


def test_strategic_spares_rule_only_for_critical_and_reason_counts() -> None:
    assert calc.strategic_spares_ok(True, ["commissioning_spares"], "") is False
    assert calc.strategic_spares_ok(True, ["strategic_spares"], "") is True
    assert calc.strategic_spares_ok(True, [], "fleet spare held at the regional depot") is True
    assert calc.strategic_spares_ok(False, [], "") is True


@pytest.mark.parametrize(
    ("min_q", "qty", "ok"), [(2, Decimal(1), False), (2, Decimal(2), True), (None, Decimal(1), True)]
)
def test_redundancy_quantity(min_q, qty, ok) -> None:
    assert calc.redundancy_ok(min_q, qty) is ok


# ── FSMs ──────────────────────────────────────────────────────────────────


def test_item_fsm_lifecycle_and_manual_targets() -> None:
    for a, b in zip(calc.ITEM_STATES, calc.ITEM_STATES[1:], strict=False):
        assert ITEM_FSM.has_transition(a, b), (a, b)
    assert not ITEM_FSM.has_transition("identified", "route_set")
    assert not ITEM_FSM.has_transition("handed_over", "cancelled")
    # Rule 11: ordered, delivered, installed, commissioned and handed_over are never set by hand.
    assert MANUAL_TARGETS.isdisjoint({"ordered", "delivered", "installed", "commissioned", "handed_over"})


def test_slot_paper_spare_fsms() -> None:
    assert SLOT_FSM.has_transition("held", "expired")
    assert not SLOT_FSM.has_transition("requested", "expired")
    assert not SLOT_FSM.has_transition("released", "held")
    assert PAPER_FSM.has_transition("submitted", "approved")
    assert not PAPER_FSM.has_transition("draft", "approved")
    assert not PAPER_FSM.has_transition("approved", "draft")
    assert SPARE_FSM.has_transition("delivered", "waived")
    assert not SPARE_FSM.has_transition("handed_over", "waived")
