# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan arithmetic: phasing, summary, greedy funding, compare."""

from __future__ import annotations

from decimal import Decimal

from app.modules.capital_plan import logic

PLAN = {"currency": "EUR", "start_year": 2030, "horizon_years": 3}


def _item(i: str, **kw) -> dict:
    base = {
        "id": i,
        "project_id": None,
        "title": f"item {i}",
        "priority": 3,
        "start_year": 2030,
        "duration_years": 1,
        "total_cost": "100",
        "phasing": [],
        "status": "proposed",
        "score": None,
    }
    base.update(kw)
    return base


def _env(*amounts: int) -> list[dict]:
    return [{"year": 2030 + n, "amount": a, "label": ""} for n, a in enumerate(amounts)]


def test_phasing_remainder_goes_to_the_last_year() -> None:
    parts = logic.phase_spend("100.00", logic.even_phasing(3))
    assert parts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(parts) == Decimal("100.00")


def test_phasing_follows_explicit_fractions() -> None:
    assert logic.phase_spend("1000", ["0.2", "0.3", "0.5"]) == [Decimal("200.00"), Decimal("300.00"), Decimal("500.00")]


def test_item_spend_lands_on_calendar_years() -> None:
    spend = logic.item_spend_by_year(_item("a", start_year=2031, duration_years=2, total_cost="10"))
    assert spend == {2031: Decimal("5.00"), 2032: Decimal("5.00")}


def test_summary_gap_and_cumulative_gap() -> None:
    items = [_item("a", total_cost="150"), _item("b", start_year=2031, total_cost="50")]
    out = logic.summarise(PLAN, _env(100, 100, 0), items)
    rows = {r["year"]: r for r in out["rows"]}
    assert rows[2030]["gap"] == "-50.00"
    assert rows[2031]["gap"] == "50.00"
    assert rows[2031]["cumulative_gap"] == "0.00"
    assert out["totals"]["demand"] == "200.00"


def test_deferred_items_cost_nothing() -> None:
    out = logic.summarise(PLAN, _env(100), [_item("a", status="deferred")])
    assert out["rows"][0]["demand"] == "0.00"


def test_spend_outside_the_horizon_is_reported_not_counted() -> None:
    out = logic.summarise(PLAN, _env(100), [_item("a", start_year=2034)])
    assert out["totals"]["demand"] == "0.00"
    assert out["totals"]["beyond_horizon"] == "100.00"
    assert out["items"][0]["outside_horizon"] == "100.00"


def test_envelope_sources_add_up() -> None:
    env = [{"year": 2030, "amount": 60, "label": "Bond"}, {"year": 2030, "amount": 40, "label": "Grant"}]
    assert logic.envelope_by_year(env) == {2030: Decimal("100.00")}


def test_autofund_orders_by_priority_then_score_then_cost() -> None:
    items = [
        _item("low", priority=2, total_cost="10"),
        _item("hi_cheap", priority=1, total_cost="10", score=50),
        _item("hi_scored", priority=1, total_cost="30", score=90),
        _item("hi_cheap_same", priority=1, total_cost="5", score=50),
    ]
    order = [s["id"] for s in logic.autofund(_env(1000), items)]
    assert order == ["hi_scored", "hi_cheap_same", "hi_cheap", "low"]


def test_autofund_unscored_sorts_after_scored() -> None:
    items = [_item("none", total_cost="1"), _item("zero", total_cost="5", score=0)]
    assert [s["id"] for s in logic.autofund(_env(1000), items)] == ["zero", "none"]


def test_autofund_skips_what_does_not_fit_and_says_which_year() -> None:
    items = [_item("big", priority=1, total_cost="90"), _item("next", priority=2, total_cost="50")]
    out = {s["id"]: s for s in logic.autofund(_env(100), items)}
    assert out["big"]["status"] == "funded"
    assert out["next"]["status"] == "proposed"
    assert out["next"]["reason"] == "exceeds envelope in 2030"
    assert 0 < out["next"]["confidence"] <= 1


def test_autofund_lets_a_cheaper_later_item_use_the_leftover() -> None:
    items = [
        _item("big", priority=1, total_cost="90"),
        _item("too_big", priority=2, total_cost="50"),
        _item("small", priority=3, total_cost="10"),
    ]
    out = {s["id"]: s["status"] for s in logic.autofund(_env(100), items)}
    assert out == {"big": "funded", "too_big": "proposed", "small": "funded"}


def test_autofund_checks_every_phased_year_and_leaves_deferred_alone() -> None:
    items = [
        _item("long", priority=1, start_year=2030, duration_years=2, total_cost="200"),
        _item("parked", priority=1, status="deferred"),
    ]
    out = logic.autofund(_env(150, 50), items)
    assert [s["id"] for s in out] == ["long"]
    assert out[0]["reason"] == "exceeds envelope in 2031"


def test_autofund_reports_whether_the_status_changes() -> None:
    out = logic.autofund(_env(100), [_item("a", status="funded", total_cost="10"), _item("b", total_cost="10")])
    assert {s["id"]: s["changed"] for s in out} == {"a": False, "b": True}


def test_compare_reports_deltas_and_changed_items() -> None:
    a = [_item("a", project_id="p1", title="Road", start_year=2030), _item("b", title="Hall")]
    b = [_item("a2", project_id="p1", title="Road", start_year=2031), _item("b2", title="Hall")]
    out = logic.compare(PLAN, _env(100, 100, 100), a, b)
    years = {y["year"]: y for y in out["years"]}
    assert years[2030]["delta_demand"] == "-100.00"
    assert out["totals"]["delta_demand"] == "0.00"
    assert out["changed_items"] == [
        {
            "title": "Road",
            "change": "changed",
            "status_a": "proposed",
            "status_b": "proposed",
            "start_year_a": 2030,
            "start_year_b": 2031,
        }
    ]


def test_compare_delay_moves_demand_between_years() -> None:
    a = [_item("a", total_cost="100", start_year=2030)]
    b = [_item("a", total_cost="100", start_year=2031)]
    years = {y["year"]: y for y in logic.compare(PLAN, _env(100, 100, 100), a, b)["years"]}
    assert years[2030]["delta_demand"] == "-100.00"
    assert years[2031]["delta_demand"] == "100.00"
    assert years[2030]["delta_gap"] == "100.00"


def test_compare_lists_added_and_removed_items() -> None:
    a = [_item("a", title="Only in A")]
    b = [_item("b", title="Only in B")]
    out = logic.compare(PLAN, _env(100), a, b)
    assert {(c["title"], c["change"]) for c in out["changed_items"]} == {
        ("Only in A", "removed"),
        ("Only in B", "added"),
    }
