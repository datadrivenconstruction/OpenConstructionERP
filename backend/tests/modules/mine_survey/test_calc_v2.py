# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Material split, drive profiles and blast holes: the worked examples of the v2 spec."""

from __future__ import annotations

from decimal import Decimal

from app.modules.mine_survey import calc


def test_block_splits_into_ore_and_waste_at_their_own_densities() -> None:
    split = calc.material_split(
        [("ore", "Ore", 11200, Decimal("2.85")), ("waste", "Waste", 7200, Decimal("2.60"))], 18400
    )
    ore, waste = split.parts
    assert ore.tonnes == Decimal("31920.00")
    assert waste.tonnes == Decimal("18720.00")
    assert split.tonnes == Decimal("50640.00")
    assert split.coverage_pct == Decimal("100.00")
    assert split.unassigned_m3 == 0


def test_trucks_carry_97_63_percent_of_the_split_tonnes() -> None:
    trucks = calc.parse_truck_loads("loads,payload_t\n412,120\n")
    assert trucks.tonnes == Decimal("49440.00")
    assert calc.truck_ratio_pct(trucks.tonnes, Decimal("50640")) == Decimal("97.63")


def test_polygons_that_miss_part_of_the_unit_leave_it_unassigned() -> None:
    split = calc.material_split([("ore", "Ore", 9200, Decimal("2.85"))], 18400)
    assert split.coverage_pct == Decimal("50.00")
    assert split.unassigned_m3 == Decimal("9200.000")


def test_a_part_without_density_leaves_the_total_tonnes_open() -> None:
    split = calc.material_split([("ore", "Ore", 100, Decimal("2.85")), ("waste", "Waste", 100, None)], 200)
    assert split.parts[1].tonnes is None
    assert split.tonnes is None


def test_face_pickups_give_20_m_of_advance_against_24_m_planned() -> None:
    adv = calc.drive_advance([Decimal("412.6"), Decimal("420.0"), Decimal("432.6")])
    assert adv == Decimal("20.00")
    assert calc.advance_pct(adv, 24) == Decimal("83.33")


def test_drive_profiles_show_10_9_percent_overbreak_56_m3_and_154_t() -> None:
    # Eleven profiles every 2 m over 20 m whose mean is 28.4 m2 against a 25.6 m2 design.
    areas = [Decimal("28.4")] * 11
    r = calc.drive_profiles(Decimal("25.6"), areas, 20, Decimal("2.75"))
    assert r is not None
    assert r.overbreak_pct == Decimal("10.94")
    assert r.overbreak_pct.quantize(Decimal("0.1")) == Decimal("10.9")
    assert r.excess_m3 == Decimal("56.000")
    assert r.excess_t == Decimal("154.00")
    assert r.under_count == 0


def test_underbreak_counts_profiles_smaller_than_design_beyond_tolerance() -> None:
    r = calc.drive_profiles(25.6, [25.0, 24.0, 26.0], 4, None, under_tol_pct=3)
    assert r is not None
    assert r.under_count == 1  # 24.0 is 6.25 % small; 25.0 is 2.34 %, inside 3 %


def test_section_area_of_a_measured_profile() -> None:
    # A 5 m wide, 5.12 m high box is 25.6 m2.
    assert calc.section_area([(0, 0), (5, 0), (5, 5.12), (0, 5.12)]) == Decimal("25.600")


def test_a_collar_0_32_m_off_fails_a_0_30_m_tolerance() -> None:
    r = calc.hole_check(1000, 2000, 12, Decimal("1000.32"), 2000, 12, Decimal("0.30"), Decimal("0.3"))
    assert r.collar_offset_m == Decimal("0.320")
    assert r.collar_ok is False
    assert r.depth_ok is True


def test_a_hole_drilled_11_4_m_against_12_m_fails_plus_minus_0_3() -> None:
    r = calc.hole_check(1000, 2000, Decimal("12.0"), 1000, 2000, Decimal("11.4"), Decimal("0.30"), Decimal("0.3"))
    assert r.depth_diff_m == Decimal("-0.600")
    assert r.depth_ok is False
    assert r.collar_ok is True


def test_no_tolerance_means_no_verdict() -> None:
    r = calc.hole_check(0, 0, 12, 0.5, 0, 11, None, None)
    assert r.collar_ok is None
    assert r.depth_ok is None


def test_hole_file_reports_bad_rows() -> None:
    rows, problems = calc.parse_holes("hole,e,n,z,depth\nH1,100,200,50,12\nH2,,200,50,12\nH3,101,201,,\n")
    assert [r.hole for r in rows] == ["H1", "H3"]
    assert rows[1].depth_m is None
    assert problems == ["line 3"]
