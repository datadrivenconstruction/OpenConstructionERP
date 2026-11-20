# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Country cadastre data: parcel number formats, area tolerance, mark lists and the boundary point register."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.land_parcels import profiles
from app.modules.land_parcels.cadastre import (
    _data,
    boundary_point_register,
    neutral_marks,
    profile_from_entry,
    register_country_profiles,
)


@pytest.fixture
def registered():
    before = dict(profiles._PROFILES)
    register_country_profiles()
    yield
    profiles._PROFILES.clear()
    profiles._PROFILES.update(before)


def test_every_entry_names_its_status_and_valid_marks() -> None:
    neutral = {m.key for m in neutral_marks()}
    for code, entry in _data().items():
        if code.startswith("_"):
            continue
        assert len(code) == 2 and code.isupper()
        assert entry.get("status") in ("to_verify", "verified")
        assert {m["key"] for m in entry.get("marks", [])} <= neutral, code
        if entry.get("area_tolerance"):
            assert entry.get("area_tolerance_source"), f"{code}: a tolerance names its source"


def test_russian_cadastral_number_and_tolerance(registered) -> None:
    ru = profiles.profile_for(["RU"])
    assert ru.id_valid("77:01:0001001:1234") and not ru.id_valid("P-001")
    # 3.5 * 0.10 * sqrt(1600) = 14.00 m2
    assert ru.area_tolerance is not None and ru.area_tolerance(Decimal("1600")) == Decimal("14.00")


def test_a_country_without_an_entry_stays_neutral(registered) -> None:
    fr = profiles.profile_for(["FR"])
    assert fr is profiles.NEUTRAL and fr.id_valid("anything") and fr.area_tolerance is None


def test_another_country_never_leaks_into_a_market(registered) -> None:
    assert profiles.profile_for(["DE"]).id_pattern == ""
    assert profiles.profile_for(["DE"]).area_tolerance is None
    assert "monument" not in {m.key for m in profiles.profile_for(["DE"]).marks}


def test_a_pack_profile_wins_over_country_data() -> None:
    before = dict(profiles._PROFILES)
    try:
        profiles.register_parcel_profile(profiles.ParcelProfile(country="RU", id_pattern=r"X\d+"))
        register_country_profiles()
        assert profiles.profile_for(["RU"]).id_pattern == r"X\d+"
    finally:
        profiles._PROFILES.clear()
        profiles._PROFILES.update(before)


def test_entry_without_marks_gets_the_neutral_list() -> None:
    p = profile_from_entry("XX", {"id_pattern": r"\d+"})
    assert p.marks == neutral_marks()


def test_register_merges_shared_corners_and_flags_conflicts() -> None:
    marks = neutral_marks()
    rows = boundary_point_register(
        [
            {"ref": "A", "points": [{"label": "1", "e": 0, "n": 0, "mark": "pin"}, {"label": "2", "e": 10, "n": 0}]},
            {
                "ref": "B",
                "points": [{"label": "2", "e": 10.002, "n": 0, "mark": "stone"}, {"label": "", "e": 20, "n": 0}],
            },
            {"ref": "C", "points": [{"label": "", "e": 20.001, "n": 0, "mark": "unmarked"}]},
        ],
        marks,
    )
    by_no = {r["point_no"]: r for r in rows}
    assert by_no["1"]["monumented"] is True
    assert by_no["2"]["parcels"] == ["A", "B"] and by_no["2"]["mark"] == "stone"
    assert by_no["2"]["position_spread_m"] == pytest.approx(0.002)
    third = next(r for r in rows if r["parcels"] == ["B", "C"])
    assert third["point_no"] == "#3" and third["monumented"] is False
