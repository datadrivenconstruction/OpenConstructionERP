# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Geofence and clock-shift arithmetic, DB-free​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Covers the inside/outside verdict for circles and polygons (tolerance counts
as inside), shift pairing, overlaps, missing clock-outs, retention cutoff, and
the three clock validation rules driven through the real rule classes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.field_time import geofence_math as gm

# A site in central Berlin; one degree of latitude is ~111 km.
LAT, LNG = 52.520008, 13.404954
T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


def _circle(radius: float = 100, tolerance: float = 0) -> gm.FenceSpec:
    return gm.FenceSpec("c1", "Gate", gm.SHAPE_CIRCLE, LAT, LNG, radius, (), tolerance)


def _square() -> gm.FenceSpec:
    d = 0.001  # ~111 m north-south
    poly = ((LAT - d, LNG - d), (LAT - d, LNG + d), (LAT + d, LNG + d), (LAT + d, LNG - d))
    return gm.FenceSpec("p1", "Plot", gm.SHAPE_POLYGON, polygon=poly)


def test_haversine_one_millidegree_latitude_is_about_111_m() -> None:
    assert gm.haversine_m(LAT, LNG, LAT + 0.001, LNG) == pytest.approx(111.2, abs=0.5)


def test_circle_inside_and_outside() -> None:
    assert gm.evaluate_fence(LAT + 0.0005, LNG, _circle()).inside is True
    hit = gm.evaluate_fence(LAT + 0.002, LNG, _circle())
    assert hit.inside is False
    assert hit.distance_m == pytest.approx(122.4, abs=1)


def test_tolerance_counts_as_inside_but_distance_stays_honest() -> None:
    hit = gm.evaluate_fence(LAT + 0.0011, LNG, _circle(radius=100, tolerance=30))
    assert hit.inside is True
    assert hit.distance_m > 0


def test_polygon_inside_outside_and_edge_distance() -> None:
    assert gm.evaluate_fence(LAT, LNG, _square()).inside is True
    hit = gm.evaluate_fence(LAT + 0.002, LNG, _square())
    assert hit.inside is False
    assert hit.distance_m == pytest.approx(111.2, abs=2)


def test_best_fence_prefers_a_containing_one_and_none_without_fences() -> None:
    far = gm.FenceSpec("c2", "Yard", gm.SHAPE_CIRCLE, LAT + 1, LNG, 50)
    assert gm.evaluate_fences(LAT, LNG, [far, _circle()]).fence_id == "c1"
    assert gm.evaluate_fences(LAT, LNG, []) is None
    assert gm.approval_for(None) == gm.APPROVAL_NOT_REQUIRED
    assert gm.approval_for(gm.evaluate_fence(LAT + 1, LNG, _circle())) == gm.APPROVAL_PENDING


def test_validate_fence_reports_unusable_geometry() -> None:
    assert gm.validate_fence(_circle()) == []
    assert "radius_positive" in gm.validate_fence(gm.FenceSpec("x", "", gm.SHAPE_CIRCLE, LAT, LNG, 0))
    assert "polygon_min_points" in gm.validate_fence(gm.FenceSpec("x", "", gm.SHAPE_POLYGON, polygon=((1, 1),)))
    assert gm.validate_fence(gm.FenceSpec("x", "", "hexagon")) == ["shape_unknown"]


def _ev(i: str, worker: str, kind: str, at: datetime, status: str = gm.APPROVAL_NOT_REQUIRED) -> dict:
    return {"id": i, "worker": worker, "kind": kind, "occurred_at": at, "approval_status": status}


def test_pair_shifts_and_hours_with_break() -> None:
    shifts = gm.pair_shifts([_ev("1", "w", "in", T0), _ev("2", "w", "out", T0 + timedelta(hours=8, minutes=30))])
    assert len(shifts) == 1
    assert shifts[0].out_event_id == "2"
    assert str(gm.shift_hours(shifts[0], 30)) == "8.00"
    assert gm.effective_break(shifts[0], 1000) == 510


def test_missing_clock_out_when_stale_or_superseded() -> None:
    events = [_ev("1", "w", "in", T0), _ev("2", "w", "in", T0 + timedelta(hours=2))]
    missing = gm.missing_clock_outs(gm.pair_shifts(events), T0 + timedelta(hours=3))
    assert [s.in_event_id for s in missing] == ["1"]
    stale = gm.missing_clock_outs(gm.pair_shifts([_ev("1", "w", "in", T0)]), T0 + timedelta(hours=17))
    assert len(stale) == 1


def test_overlapping_shifts_are_found_per_worker() -> None:
    a = gm.Shift("w", T0, T0 + timedelta(hours=8), "a")
    b = gm.Shift("w", T0 + timedelta(hours=4), T0 + timedelta(hours=10), "b")
    c = gm.Shift("x", T0, T0 + timedelta(hours=8), "c")
    pairs = gm.overlapping_shifts([a, b, c])
    assert [(p.in_event_id, q.in_event_id) for p, q in pairs] == [("a", "b")]


def test_shift_approval_and_unapproved_outside() -> None:
    s = gm.Shift("w", T0, T0, "1", approval_statuses=[gm.APPROVAL_APPROVED, gm.APPROVAL_NOT_REQUIRED])
    assert gm.shift_is_approved(s)
    s.approval_statuses.append(gm.APPROVAL_PENDING)
    assert not gm.shift_is_approved(s)
    rows = [_ev("1", "w", "in", T0, gm.APPROVAL_PENDING), _ev("2", "w", "out", T0, gm.APPROVAL_APPROVED)]
    assert [r["id"] for r in gm.unapproved_outside(rows)] == ["1"]


def test_purge_cutoff_is_clamped() -> None:
    assert gm.purge_cutoff(date(2026, 10, 26), 90) == date(2026, 7, 28)
    assert gm.purge_cutoff(date(2026, 10, 26), 0) == date(2026, 10, 25)


@pytest.mark.asyncio
async def test_clock_rules_fire_on_the_clock_block_only() -> None:
    from app.core.validation.engine import ValidationContext
    from app.core.validation.rules.field_clock import FIELD_CLOCK_RULES

    events = [
        {**_ev("1", "w", "in", T0, gm.APPROVAL_PENDING), "distance_m": 240.0, "worker_name": "Mason"},
        {**_ev("2", "w", "out", T0 + timedelta(hours=8)), "worker_name": "Mason"},
        {**_ev("3", "w", "in", T0 + timedelta(hours=9)), "worker_name": "Mason"},
    ]
    payload = {
        "lines": [],
        "clock_events": [{**e, "occurred_at": e["occurred_at"].isoformat()} for e in events],
        "now": (T0 + timedelta(hours=30)).isoformat(),
    }
    found: dict[str, int] = {}
    for rule in FIELD_CLOCK_RULES:
        results = await rule.validate(ValidationContext(data=payload, metadata={"locale": "en"}))
        found[rule.rule_id] = len(results)
        bare = await rule.validate(ValidationContext(data={"lines": []}, metadata={"locale": "en"}))
        assert bare == []
    assert found == {
        "field_time.clock_outside_unapproved": 1,
        "field_time.clock_overlapping_shifts": 0,
        "field_time.clock_missing_clock_out": 1,
    }
