"""National grids, heights and geoids in core reference data (P0-1): every code is real, every market is covered."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pyproj import CRS

from app.modules.survey_core import crs as crs_lib
from app.modules.survey_core.crs import (
    geoid_name_for,
    legacy_note,
    load_survey_reference,
    national_crs_for,
    register_pack_crs,
    survey_reference,
    transform_points_3d,
    vertical_status,
)

REPO = Path(__file__).resolve().parents[4]
REF = survey_reference()


def _pack_countries() -> set[str]:
    out = set()
    for manifest in (REPO / "packs").glob("*/src/*/manifest.py"):
        m = re.search(r"""["']country["']\s*:\s*["']([A-Z]{2})["']""", manifest.read_text(encoding="utf-8"))
        if m and m.group(1) != "XX":
            out.add(m.group(1))
    return out


def test_every_pack_country_and_the_two_extra_markets_have_an_entry() -> None:
    packs = _pack_countries()
    if not packs:
        pytest.skip("packs are not shipped in this install")
    missing = (packs | {"KZ", "CL"}) - set(REF)
    assert not missing, f"no survey reference for {sorted(missing)}"


@pytest.mark.parametrize("country", sorted(REF))
def test_every_horizontal_code_resolves_and_matches_its_token(country: str) -> None:
    entry = REF[country]
    assert entry["horizontal"], country
    roles = {h["role"] for h in entry["horizontal"]}
    assert roles <= {"primary", "zone", "legacy"}
    assert "primary" in roles, f"{country} has no primary system"
    for h in entry["horizontal"]:
        crs = CRS.from_epsg(h["epsg"])
        assert not crs.is_vertical, (country, h["epsg"])
        assert h["token"].lower() in crs.name.lower(), (country, h["epsg"], crs.name)


@pytest.mark.parametrize("country", sorted(REF))
def test_every_vertical_code_is_a_vertical_system(country: str) -> None:
    for v in REF[country].get("vertical") or []:
        crs = CRS.from_epsg(v["epsg"])
        assert crs.is_vertical, (country, v["epsg"], crs.name)
        assert v["token"].lower() in crs.name.lower(), (country, v["epsg"], crs.name)


def test_units_and_angles_are_declared() -> None:
    for country, entry in REF.items():
        assert entry["linear_unit"] in ("m", "ftUS"), country
        assert entry["angle_unit"] in ("gon", "dms"), country
    assert REF["US"]["linear_unit"] == "ftUS"
    assert REF["DE"]["angle_unit"] == "gon"


def test_the_loader_registers_and_only_adds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crs_lib, "_PACK_CRS", {})
    register_pack_crs("DE", [(31467, "pack note")])
    count = load_survey_reference()
    assert count >= sum(len(e["horizontal"]) for e in REF.values()) - 1
    de = [s for s, _ in national_crs_for(["DE"])]
    assert de[0].epsg == 31467 and de[0].note == "pack note"
    assert len([s for s in de if s.epsg == 31467]) == 1
    assert {25832, 25833} <= {s.epsg for s in de}


def test_national_systems_follow_the_market_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crs_lib, "_PACK_CRS", {})
    load_survey_reference()
    assert national_crs_for(["*"]) == []
    assert national_crs_for([]) == []
    kz = national_crs_for(["kz"])
    assert kz and all(c == "KZ" for _, c in kz)
    cl = {s.epsg for s, _ in national_crs_for(["CL"])}
    assert cl & {32719, 5361, 5362, 9154, 9155}


def test_a_legacy_grid_names_the_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crs_lib, "_PACK_CRS", {})
    load_survey_reference()
    assert legacy_note(31467, ["DE"]) == ("DE", 25832)
    assert legacy_note(25832, ["DE"]) is None
    assert legacy_note(None) is None


def test_geoid_names_come_from_the_reference() -> None:
    assert geoid_name_for(7837) == "GCG2016"
    assert geoid_name_for(None) is None


def test_a_missing_geoid_grid_is_named_and_heights_stay_as_measured() -> None:
    status = vertical_status(4326, None, 25832, 7837)
    assert status.needed
    if status.available:
        pytest.skip("the geoid grid is installed here")
    assert any("gcg2016" in g.lower() for g in status.missing_grids)
    res = transform_points_3d([(9.0, 50.0, 200.0)], 4326, 25832, None, 7837)
    assert not res.heights_converted
    assert res.points[0][2] == 200.0


def test_a_unit_only_vertical_change_converts_heights_without_a_grid() -> None:
    # NAVD88 metres to NAVD88 US survey feet: no geoid involved.
    res = transform_points_3d([(500000.0, 4000000.0, 100.0)], 26910, 26910, 5703, 6360)
    assert res.heights_converted
    assert res.points[0][2] == pytest.approx(328.0833, abs=1e-3)


def test_no_vertical_named_means_no_height_transform() -> None:
    assert not vertical_status(25832, None, 25833, None).needed
