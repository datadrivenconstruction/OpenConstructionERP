# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Unit tests for the post-calculation (Nachkalkulation) compute (pure, DB-free).

The compute layer takes plain dicts and returns Decimal-exact dataclasses, so every
case here is asserted from plain values without a database - normal productivity,
the div-by-zero guards (no labour norm, no installed quantity), under- and
over-productive lines, missing actuals, the project rollup, the per-resource
rollup, and the estimating feedback factors.
"""

from decimal import Decimal

from app.modules.postcalc.model import (
    STATUS_NO_ACTUALS,
    STATUS_NO_BASELINE,
    STATUS_NO_PROGRESS,
    STATUS_ON_PLAN,
    STATUS_OVER_PRODUCTIVE,
    STATUS_UNDER_PRODUCTIVE,
    LineProductivity,
    ProjectPostCalc,
    render_markdown,
)
from app.modules.postcalc.service import (
    aggregate_resources,
    build_feedback_factors,
    compute_line_productivity,
    compute_project_postcalc,
)
from app.modules.price_breakdown import ResourceKind

# ── Builders ─────────────────────────────────────────────────────────────────


def _labour(qty, rate="45"):
    return {"type": "labor", "name": "Crew", "unit": "h", "quantity": qty, "unit_rate": rate}


def _machinery(qty, rate="80"):
    return {"type": "machinery", "name": "Pump", "unit": "h", "quantity": qty, "unit_rate": rate}


def _material(qty, rate="110"):
    return {"type": "material", "name": "Concrete C30/37", "unit": "m3", "quantity": qty, "unit_rate": rate}


def _line(
    *,
    ref="P1",
    description="RC wall",
    unit="m3",
    planned_quantity="100",
    resources=None,
    actual_quantity="0",
    actual_labour_hours="0",
    actual_plant_hours="0",
    actual_labour_cost=None,
    actual_plant_cost=None,
    planned_cost="0",
    currency="EUR",
):
    return {
        "ref": ref,
        "description": description,
        "unit": unit,
        "currency": currency,
        "planned_quantity": planned_quantity,
        "planned_cost": planned_cost,
        "resources": resources if resources is not None else [_labour("2.5")],
        "actual_quantity": actual_quantity,
        "actual_labour_hours": actual_labour_hours,
        "actual_plant_hours": actual_plant_hours,
        "actual_labour_cost": actual_labour_cost,
        "actual_plant_cost": actual_plant_cost,
    }


# ── Normal case ──────────────────────────────────────────────────────────────


def test_normal_case_computes_factor_and_hours():
    # 2.5 planned h/unit, 100 units planned and installed, 300 h actually booked.
    line = _line(
        planned_quantity="100", resources=[_labour("2.5", "45")], actual_quantity="100", actual_labour_hours="300"
    )
    lp = compute_line_productivity(line)

    assert lp.planned_hours == Decimal("250")
    assert lp.actual_hours == Decimal("300")
    assert lp.planned_hours_per_unit == Decimal("2.5")
    assert lp.actual_hours_per_unit == Decimal("3")
    assert lp.earned_hours == Decimal("250")
    assert lp.hours_variance == Decimal("50")
    assert lp.productivity_factor == Decimal("1.2")
    assert lp.variance_pct == Decimal("20")
    assert lp.status == STATUS_UNDER_PRODUCTIVE
    assert lp.is_under_productive is True
    # Planned labour cost = 2.5 h * 45 /unit * 100 units.
    assert lp.planned_labour_cost == Decimal("11250")


def test_progress_below_full_still_compares_on_earned_hours():
    # Only half installed: earned hours track the installed quantity, not the plan.
    line = _line(planned_quantity="100", resources=[_labour("2")], actual_quantity="50", actual_labour_hours="100")
    lp = compute_line_productivity(line)

    assert lp.planned_hours == Decimal("200")
    assert lp.earned_hours == Decimal("100")  # 2 h/unit * 50 installed
    assert lp.productivity_factor == Decimal("1")  # 100 booked / 100 earned
    assert lp.status == STATUS_ON_PLAN
    assert lp.progress_pct == Decimal("50")


# ── Div-by-zero guards ───────────────────────────────────────────────────────


def test_zero_planned_quantity_is_no_baseline_not_crash():
    line = _line(planned_quantity="0", resources=[_labour("2.5")], actual_quantity="10", actual_labour_hours="30")
    lp = compute_line_productivity(line)

    assert lp.status == STATUS_NO_BASELINE
    assert lp.planned_hours == Decimal("0")
    assert lp.planned_hours_per_unit is None
    assert lp.earned_hours is None
    assert lp.productivity_factor is None
    assert lp.variance_pct is None


def test_no_labour_resource_is_no_baseline():
    # A material-only line has no labour norm to judge productivity against.
    line = _line(planned_quantity="100", resources=[_material("1.02")], actual_quantity="100", actual_labour_hours="0")
    lp = compute_line_productivity(line)

    assert lp.planned_hours == Decimal("0")
    assert lp.status == STATUS_NO_BASELINE
    assert lp.productivity_factor is None


def test_hours_booked_but_nothing_installed_is_no_progress():
    line = _line(planned_quantity="100", resources=[_labour("2.5")], actual_quantity="0", actual_labour_hours="40")
    lp = compute_line_productivity(line)

    assert lp.status == STATUS_NO_PROGRESS
    assert lp.actual_hours == Decimal("40")
    assert lp.actual_hours_per_unit is None  # guarded: no installed quantity to divide by
    assert lp.productivity_factor is None


# ── Under / over productive ──────────────────────────────────────────────────


def test_actual_above_planned_is_under_productive():
    line = _line(planned_quantity="80", resources=[_labour("3")], actual_quantity="80", actual_labour_hours="300")
    lp = compute_line_productivity(line)

    # 240 earned vs 300 booked -> factor 1.25, 25% over the norm.
    assert lp.earned_hours == Decimal("240")
    assert lp.productivity_factor == Decimal("1.25")
    assert lp.variance_pct == Decimal("25")
    assert lp.status == STATUS_UNDER_PRODUCTIVE


def test_actual_below_planned_is_over_productive():
    line = _line(planned_quantity="50", resources=[_labour("4")], actual_quantity="50", actual_labour_hours="150")
    lp = compute_line_productivity(line)

    # 200 earned vs 150 booked -> factor 0.75, 25% under the norm.
    assert lp.earned_hours == Decimal("200")
    assert lp.productivity_factor == Decimal("0.75")
    assert lp.variance_pct == Decimal("-25")
    assert lp.status == STATUS_OVER_PRODUCTIVE
    assert lp.is_over_productive is True


# ── Missing actuals ──────────────────────────────────────────────────────────


def test_missing_actuals_is_no_actuals():
    line = _line(planned_quantity="100", resources=[_labour("2.5")], actual_quantity="0", actual_labour_hours="0")
    lp = compute_line_productivity(line)

    assert lp.status == STATUS_NO_ACTUALS
    assert lp.actual_hours == Decimal("0")
    assert lp.earned_hours is None
    assert lp.productivity_factor is None


def test_installed_but_no_hours_booked_is_no_actuals():
    line = _line(planned_quantity="100", resources=[_labour("2.5")], actual_quantity="100", actual_labour_hours="0")
    lp = compute_line_productivity(line)

    assert lp.status == STATUS_NO_ACTUALS
    assert lp.productivity_factor is None


# ── Tolerance band ───────────────────────────────────────────────────────────


def test_tolerance_band_holds_small_deviation_on_plan():
    # 255 booked vs 250 earned -> factor 1.02, inside the default 5% band.
    line = _line(planned_quantity="100", resources=[_labour("2.5")], actual_quantity="100", actual_labour_hours="255")
    assert compute_line_productivity(line).status == STATUS_ON_PLAN
    # A 1% band flags the same 2% deviation as under-productive.
    assert compute_line_productivity(line, tolerance=Decimal("0.01")).status == STATUS_UNDER_PRODUCTIVE


# ── Project rollup ───────────────────────────────────────────────────────────


def _rollup_lines():
    under = _line(
        ref="A",
        planned_quantity="100",
        resources=[_labour("2.5", "45")],
        actual_quantity="100",
        actual_labour_hours="300",
    )
    over = _line(
        ref="B",
        planned_quantity="50",
        resources=[_labour("4", "50")],
        actual_quantity="50",
        actual_labour_hours="150",
    )
    idle = _line(
        ref="C",
        planned_quantity="20",
        resources=[_labour("3", "40")],
        actual_quantity="0",
        actual_labour_hours="0",
    )
    return [under, over, idle]


def test_project_rollup_totals_and_counts():
    report = compute_project_postcalc(_rollup_lines(), currency="EUR")

    assert isinstance(report, ProjectPostCalc)
    assert report.line_count == 3
    assert report.compared_line_count == 2  # idle line has no actuals
    assert report.total_planned_hours == Decimal("510")  # 250 + 200 + 60
    assert report.total_actual_hours == Decimal("450")  # 300 + 150 + 0
    assert report.total_earned_hours == Decimal("450")  # 250 + 200 (comparable only)
    # 450 booked / 450 earned over the comparable lines -> exactly on plan.
    assert report.overall_productivity_factor == Decimal("1")
    assert report.overall_variance_pct == Decimal("0")
    assert report.status_counts == {
        STATUS_UNDER_PRODUCTIVE: 1,
        STATUS_OVER_PRODUCTIVE: 1,
        STATUS_NO_ACTUALS: 1,
    }
    assert report.currency == "EUR"


def test_unbaselined_line_never_skews_overall_factor():
    good = _line(
        ref="A", planned_quantity="100", resources=[_labour("2")], actual_quantity="100", actual_labour_hours="240"
    )
    noisy = _line(
        ref="B",
        planned_quantity="10",
        resources=[_material("1")],  # no labour norm
        actual_quantity="10",
        actual_labour_hours="9999",  # huge stray hours on a line with no baseline
    )
    report = compute_project_postcalc([good, noisy])

    # The stray hours are still counted in the headline total booked hours...
    assert report.total_actual_hours == Decimal("10239")
    # ...but only the baselined line drives the productivity factor (240/200).
    assert report.total_earned_hours == Decimal("200")
    assert report.overall_productivity_factor == Decimal("1.2")
    assert report.compared_line_count == 1


def test_currency_falls_back_to_first_line_when_unset():
    report = compute_project_postcalc([_line(currency="GBP")], currency="")
    assert report.currency == "GBP"


# ── Resource rollup ──────────────────────────────────────────────────────────


def test_resource_rollup_by_kind():
    line = _line(
        planned_quantity="100",
        resources=[_labour("2.5", "45"), _machinery("0.5", "80"), _material("1.02", "110")],
        actual_quantity="100",
        actual_labour_hours="300",
        actual_plant_hours="40",
    )
    resources = aggregate_resources([line])

    by_kind = {r.kind: r for r in resources}
    # Labour and machinery carry a real hours factor; material is cost-only.
    assert by_kind[ResourceKind.LABOUR].planned_hours == Decimal("250")
    assert by_kind[ResourceKind.LABOUR].earned_hours == Decimal("250")
    assert by_kind[ResourceKind.LABOUR].actual_hours == Decimal("300")
    assert by_kind[ResourceKind.LABOUR].productivity_factor == Decimal("1.2")

    assert by_kind[ResourceKind.MACHINERY].planned_hours == Decimal("50")
    assert by_kind[ResourceKind.MACHINERY].actual_hours == Decimal("40")
    assert by_kind[ResourceKind.MACHINERY].productivity_factor == Decimal("0.8")

    material = by_kind[ResourceKind.MATERIAL]
    assert material.productivity_factor is None
    assert material.planned_cost == Decimal("11220")  # 1.02 * 110 * 100
    assert material.actual_cost is None

    # Order follows KIND_ORDER: labour, then machinery, then material.
    assert [r.kind for r in resources] == [
        ResourceKind.LABOUR,
        ResourceKind.MACHINERY,
        ResourceKind.MATERIAL,
    ]


def test_resource_actual_cost_only_when_priced():
    line = _line(
        planned_quantity="100",
        resources=[_labour("2.5", "45")],
        actual_quantity="100",
        actual_labour_hours="300",
        actual_labour_cost="14000",
    )
    labour = next(r for r in aggregate_resources([line]) if r.kind is ResourceKind.LABOUR)
    assert labour.actual_cost == Decimal("14000")
    assert labour.cost_variance == Decimal("2750")  # 14000 - 11250 planned


# ── Feedback factors ─────────────────────────────────────────────────────────


def test_feedback_factors_suggest_observed_norm():
    report = compute_project_postcalc(_rollup_lines())
    factors = report.feedback_factors

    # Both deviating lines are fully installed (coverage 1.0), the idle line is not.
    assert {f.ref for f in factors} == {"A", "B"}
    a = next(f for f in factors if f.ref == "A")
    assert a.current_hours_per_unit == Decimal("2.5")
    assert a.observed_hours_per_unit == Decimal("3")
    assert a.suggested_hours_per_unit == Decimal("3")
    assert a.confidence == Decimal("1")
    assert "raising" in a.recommendation.lower() or "%" in a.recommendation


def test_feedback_factor_min_confidence_filters_thin_evidence():
    # Only 2% installed: a real deviation but too little evidence by default.
    thin = _line(
        planned_quantity="100",
        resources=[_labour("2.5")],
        actual_quantity="2",
        actual_labour_hours="20",
    )
    lp = [compute_line_productivity(thin)]
    assert lp[0].status == STATUS_UNDER_PRODUCTIVE  # 20 booked vs 5 earned

    assert build_feedback_factors(lp) == []  # default 0.10 floor filters it
    loosened = build_feedback_factors(lp, min_confidence=Decimal("0"))
    assert len(loosened) == 1
    assert loosened[0].confidence == Decimal("0.02")


def test_feedback_factors_sorted_by_hour_impact():
    small = _line(
        ref="small", planned_quantity="10", resources=[_labour("2")], actual_quantity="10", actual_labour_hours="30"
    )
    big = _line(
        ref="big", planned_quantity="500", resources=[_labour("2")], actual_quantity="500", actual_labour_hours="1500"
    )
    factors = build_feedback_factors([compute_line_productivity(small), compute_line_productivity(big)])
    # big moves far more hours (500 * 1 h/unit) than small (10 * 1 h/unit).
    assert [f.ref for f in factors] == ["big", "small"]


# ── Serialization + rendering ────────────────────────────────────────────────


def test_to_dict_quantizes_and_passes_none_through():
    line = _line(planned_quantity="100", resources=[_labour("2.5")], actual_quantity="100", actual_labour_hours="300")
    d = compute_line_productivity(line).to_dict()

    assert d["productivity_factor"] == "1.2000"
    assert d["planned_hours"] == "250.00"
    assert d["variance_pct"] == "20.00"
    assert d["status"] == STATUS_UNDER_PRODUCTIVE

    # A no-baseline line serialises the undefined figures as JSON null.
    nb = compute_line_productivity(_line(planned_quantity="0")).to_dict()
    assert nb["productivity_factor"] is None
    assert nb["earned_hours"] is None


def test_project_to_dict_shape():
    d = compute_project_postcalc(_rollup_lines(), currency="EUR").to_dict()
    assert set(d) >= {
        "currency",
        "total_planned_hours",
        "total_actual_hours",
        "overall_productivity_factor",
        "line_count",
        "status_counts",
        "lines",
        "resources",
        "feedback_factors",
    }
    assert len(d["lines"]) == 3
    assert d["overall_productivity_factor"] == "1.0000"
    assert all(isinstance(line["ref"], str) for line in d["lines"])


def test_render_markdown_is_auditable():
    md = render_markdown(compute_project_postcalc(_rollup_lines(), currency="EUR"))

    assert "# Post-calculation" in md
    assert "## Productivity by line" in md
    assert "## Productivity by resource" in md
    assert "## Factors to feed back to estimating" in md
    # The per-line factor and a ref are present so the report is traceable.
    assert "1.2000" in md
    assert "| A |" in md


def test_render_markdown_handles_empty_project():
    md = render_markdown(compute_project_postcalc([]))
    assert "# Post-calculation" in md
    assert "No lines have enough booked hours" in md


def test_line_productivity_is_a_dataclass_instance():
    lp = compute_line_productivity(_line())
    assert isinstance(lp, LineProductivity)
    # Money / hours are Decimal, never float.
    assert isinstance(lp.planned_hours, Decimal)
    assert isinstance(lp.planned_labour_cost, Decimal)


def test_feedback_factor_names_the_position_so_its_history_can_be_fetched():
    line = _line(ref="W1", actual_quantity="100", actual_labour_hours="300")
    line["position_id"] = "8a1d4a9e-0000-4000-8000-000000000001"
    (factor,) = build_feedback_factors([compute_line_productivity(line)])
    assert factor.position_id == "8a1d4a9e-0000-4000-8000-000000000001"
    assert factor.to_dict()["position_id"] == "8a1d4a9e-0000-4000-8000-000000000001"
    # A line handed in without one (an upload, a test) reads None, not an empty string.
    (bare,) = build_feedback_factors(
        [compute_line_productivity(_line(actual_quantity="100", actual_labour_hours="300"))]
    )
    assert bare.position_id is None
