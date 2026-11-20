# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Alignment by intersection points: tangent points against a hand calc, fit, minimum radius."""

from __future__ import annotations

import json
import math

import pytest

from app.modules.setting_out import alignment_design as ad
from app.modules.setting_out.design_io import alignment_from_json


def test_ninety_degree_left_turn_hand_calc() -> None:
    # IP1 at (100, 0), 90 deg left turn, R 50: T = 50 tan 45 = 50, L = 50 * pi / 2.
    design = ad.design_from_ips([ad.Ip(0, 0), ad.Ip(100, 0, 50.0), ad.Ip(100, 100)])
    [curve] = design.curves
    assert curve.deflection_deg == pytest.approx(90.0)
    assert curve.left
    assert curve.tangent == pytest.approx(50.0)
    assert curve.tc == pytest.approx((50.0, 0.0))
    assert curve.ct == pytest.approx((100.0, 50.0))
    assert curve.centre == pytest.approx((50.0, 50.0))
    assert curve.arc_length == pytest.approx(78.5398, abs=1e-4)
    assert curve.external == pytest.approx(50.0 * (math.sqrt(2) - 1))
    assert curve.tc_chainage == pytest.approx(50.0)
    assert curve.ct_chainage == pytest.approx(128.5398, abs=1e-4)
    assert design.length == pytest.approx(178.5398, abs=1e-4)
    assert design.fits


def test_right_turn_centre_lies_right() -> None:
    design = ad.design_from_ips([ad.Ip(0, 0), ad.Ip(100, 0, 40.0), ad.Ip(100, -100)])
    [curve] = design.curves
    assert not curve.left
    assert curve.centre == pytest.approx((60.0, -40.0))


def test_elements_round_trip_through_the_stored_json() -> None:
    design = ad.design_from_ips([ad.Ip(0, 0), ad.Ip(100, 0, 50.0), ad.Ip(100, 100)], start_chainage=1000.0)
    data = ad.to_json(design, "Road", 50.0)
    al = alignment_from_json(json.loads(json.dumps(data)))
    assert al is not None
    assert al.length == pytest.approx(design.length)
    e, n = al.point_at(1000.0 + 50.0 + 78.5398 / 2)
    # Mid-arc lies on the radius through the IP: centre + R * (1/sqrt2, -1/sqrt2).
    assert (e, n) == pytest.approx((50 + 50 / math.sqrt(2), 50 - 50 / math.sqrt(2)), abs=1e-3)
    assert data["ips"][1]["radius"] == 50.0


def test_curves_that_do_not_fit_between_tangents_overlap() -> None:
    # Leg IP1-IP2 is 100 m; two 90 deg curves with R 60 need 60 + 60 = 120 m.
    design = ad.design_from_ips([ad.Ip(0, 0), ad.Ip(100, 0, 60.0), ad.Ip(100, 100, 60.0), ad.Ip(200, 100)])
    assert not design.fits
    [ov] = design.overlaps
    assert (ov.a, ov.b) == ("IP1", "IP2")
    assert ov.need == pytest.approx(120.0)
    assert ov.have == pytest.approx(100.0)


def test_angle_point_without_radius_has_no_curve() -> None:
    design = ad.design_from_ips([ad.Ip(0, 0), ad.Ip(100, 0), ad.Ip(100, 100)])
    assert design.curves == []
    assert design.length == pytest.approx(200.0)


def test_too_few_ips() -> None:
    with pytest.raises(ValueError, match="two"):
        ad.design_from_ips([ad.Ip(0, 0)])


def test_demo_minimum_radius_table() -> None:
    # Demo values, not a standard: 45 m is below the 60 m given for 50 km/h.
    rmin = ad.min_radius(50.0, [])
    assert rmin is not None
    assert rmin.radius_m == 60.0
    assert rmin.source == "demo"
    assert ad.min_radius(None, []) is None


def test_pack_table_wins_for_its_market_only() -> None:
    ad.register_pack_min_radius("ZZ", {50.0: 80.0, 80.0: 250.0}, "Pack ref 1.2")
    try:
        assert ad.min_radius(50.0, ["ZZ"]).radius_m == 80.0  # type: ignore[union-attr]
        assert ad.min_radius(60.0, ["ZZ"]).radius_m == 250.0  # type: ignore[union-attr]
        assert ad.min_radius(50.0, ["DE"]).radius_m == 60.0  # type: ignore[union-attr]
    finally:
        ad.unregister_pack_min_radius("ZZ")


def test_riverside_access_road_flags_the_45_m_curve() -> None:
    data = json.loads(ad.DEMO_ROAD.read_text(encoding="utf-8"))
    design = ad.design_from_ips([ad.Ip(**ip) for ip in data["ips"]], data["start_chainage"])
    assert [c.radius for c in design.curves] == [120.0, 60.0, 45.0]
    assert design.fits
    rmin = ad.min_radius(data["design_speed_kmh"], [])
    low = [c for c in design.curves if c.radius < rmin.radius_m]  # type: ignore[union-attr]
    assert [c.ref for c in low] == ["IP3"]


def test_ticks_every_20_m_with_labels_every_100() -> None:
    ticks = ad.ticks(0.0, 178.54, 20.0, 100.0)
    assert [t[0] for t in ticks] == [0, 20, 40, 60, 80, 100, 120, 140, 160]
    assert [t[0] for t in ticks if t[1]] == [0, 100]


async def test_preview_findings_without_a_database() -> None:
    from app.modules.setting_out.alignment_router import AlignmentDesignIn, compute

    data = json.loads(ad.DEMO_ROAD.read_text(encoding="utf-8"))
    out = await compute(AlignmentDesignIn(**data), [], "de")
    assert out.fits
    assert [c.below_min for c in out.curves] == [False, False, True]
    [warn] = out.findings
    assert warn.rule_id == "SRV-072"
    assert warn.severity == "warning"
    assert "45" in warn.message
    assert "Mindestradius" in warn.message
    assert out.ticks[0].labelled
    assert out.ticks[1].chainage == 20.0
    assert out.alignment is not None
    assert out.alignment["ips"][3]["radius"] == 45


async def test_overlap_finding_is_an_error() -> None:
    from app.modules.setting_out.alignment_router import AlignmentDesignIn, IpIn, compute

    ips = [IpIn(e=0, n=0), IpIn(e=100, n=0, radius=60), IpIn(e=100, n=100, radius=60), IpIn(e=200, n=100)]
    out = await compute(AlignmentDesignIn(ips=ips), [], "en")
    assert not out.fits
    assert out.alignment is None
    assert [(f.rule_id, f.severity) for f in out.findings] == [("SRV-073", "error")]
    assert "120.00 m of a 100.00 m" in out.findings[0].message
