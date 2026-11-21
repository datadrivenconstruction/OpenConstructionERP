# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan editor without a database: view transform, conventions, code grammar, rules SRV-140..144."""

from __future__ import annotations

import pytest
from pyproj import Transformer

from app.core.validation.engine import Severity, ValidationContext
from app.modules.survey_core import plan_reference as ref
from app.modules.survey_core.plan_service import default_library
from app.modules.survey_core.plan_validators import (
    CodeDuplicateRule,
    CodeUnknownRule,
    RingCrossesRule,
    RingOpenRule,
    StringShortRule,
    ring_crossings,
)
from app.modules.survey_core.plan_view import fit_view, local_view, to_grid, to_view


def _ctx(plan: dict) -> ValidationContext:
    return ValidationContext(data={"plan": plan}, metadata={"locale": "en"})


# -- View transform -------------------------------------------------------------------------------------------


def test_view_transform_is_under_a_millimetre_over_five_km_in_utm_33n() -> None:
    dto = fit_view(32633, 386500.0, 5816500.0, 391500.0, 5821500.0)
    assert dto["kind"] == "polynomial"
    assert dto["residual_mm"] < 1.0
    exact = Transformer.from_crs(32633, 4326, always_xy=True)
    for e, n in [(386500.0, 5816500.0), (389123.4, 5819876.5), (391500.0, 5821500.0)]:
        lon, lat = to_view(dto, e, n)
        tlon, tlat = exact.transform(e, n)
        assert abs(lon - tlon) < 1e-7 and abs(lat - tlat) < 1e-7


def test_view_transform_round_trips_through_the_inverse() -> None:
    dto = fit_view(32633, 389000.0, 5819000.0, 389120.0, 5819080.0)
    e, n = to_grid(dto, *to_view(dto, 389050.0, 5819010.0))
    assert abs(e - 389050.0) < 0.01 and abs(n - 5819010.0) < 0.01


def test_grid_north_is_west_of_true_north_east_of_the_central_meridian_negative() -> None:
    # Riverside lies west of 15 deg E in zone 33N: grid convergence makes grid north point west of true north.
    dto = fit_view(32633, 388000.0, 5818000.0, 390000.0, 5820000.0)
    assert -2.0 < dto["grid_north_bearing"] < 0.0


def test_a_local_grid_is_never_pinned_to_a_place() -> None:
    dto = local_view(1000.0, 2000.0, [990.0, 1990.0, 1010.0, 2010.0])
    assert dto["kind"] == "local" and dto["epsg"] is None
    assert to_grid(dto, *to_view(dto, 1003.25, 1998.5)) == pytest.approx((1003.25, 1998.5), abs=1e-9)


def test_a_geographic_crs_has_no_planar_fit() -> None:
    with pytest.raises(ValueError, match="not a projected"):
        fit_view(4326, 0, 0, 1, 1)


# -- Conventions and libraries --------------------------------------------------------------------------------


def test_conventions_follow_the_country_and_fall_back_to_neutral() -> None:
    de, source = ref.country_conventions("DE")
    assert source == "country" and de["angleUnit"] == "gon" and de["chainage"] == "km"
    us, _ = ref.country_conventions("us")
    assert us["linearUnit"] == "ftUS" and us["directionFormat"] == "quadrant" and us["areaUnit"] == "acre"
    assert us["precision"] == "0.01ft"
    ru, _ = ref.country_conventions("RU")
    assert ru["axis"] == "XY"
    neutral, source = ref.country_conventions(None)
    assert source == "neutral" and neutral["angleUnit"] == "dms" and neutral["axis"] == "EN"


def test_clean_conventions_drops_unknown_keys_and_values() -> None:
    assert ref.clean_conventions({"axis": "YX", "angleUnit": "mil", "colour": "red", "angleDecimals": 2}) == {
        "axis": "YX",
        "angleDecimals": 2,
    }


def test_country_codes_show_only_for_an_active_market() -> None:
    assert default_library("DE", ["DE"]).source == "pack"
    assert any(c["code"] == "BO" for c in default_library("DE", ["DE"]).items)
    assert default_library("DE", ["US"]).source == "neutral"
    assert default_library("DE", ["*"]).source == "neutral"
    assert default_library("FR", ["FR"]).source == "neutral"
    assert set(ref.library_countries()) >= {"US", "DE", "RU"}


@pytest.mark.parametrize(
    ("raw", "base", "string", "control"),
    [("EP1", "EP", "1", None), ("EP2 ST", "EP", "2", "ST"), ("BLD3CL", "BLD", "3", "CL"), ("TR", "TR", "1", None)],
)
def test_parse_code(raw: str, base: str, string: str, control: str | None) -> None:
    entry, b, s, c = ref.parse_code(raw, ref.neutral_codes())
    assert entry is not None and (b, s, c) == (base, string, control)


def test_longest_library_code_wins() -> None:
    lib = [{"code": "B", "line": "open"}, {"code": "BLD", "line": "closed"}]
    assert ref.parse_code("BLD1", lib)[0]["code"] == "BLD"


# -- Rules ----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_srv140_counts_unknown_codes_once_per_code() -> None:
    plan = {"library": ref.neutral_codes(), "codes": ["EP1", "XX", "XX", "EG", ""]}
    results = await CodeUnknownRule().validate(_ctx(plan))
    assert [(r.element_ref, r.severity) for r in results] == [("XX", Severity.INFO)]
    assert "2 points" in results[0].message


@pytest.mark.asyncio
async def test_srv141_flags_single_point_and_short_closed_strings() -> None:
    plan = {"library": ref.neutral_codes(), "codes": ["EP1", "EP1", "EP2", "BLD1", "BLD1", "FN"]}
    refs = {r.element_ref for r in await StringShortRule().validate(_ctx(plan)) if not r.passed}
    assert refs == {"EP2", "BLD1", "FN1"}


@pytest.mark.asyncio
async def test_riverside_codes_raise_no_string_or_code_findings() -> None:
    from pathlib import Path

    demo = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
    codes = [line.split(",")[4] for line in (demo / "existing_ground.csv").read_text().splitlines() if line]
    codes += [line.split(",")[4] for line in (demo / "control.csv").read_text().splitlines() if line]
    plan = {"library": ref.neutral_codes(), "codes": codes}
    assert all(r.passed for r in await CodeUnknownRule().validate(_ctx(plan)))
    assert all(r.passed for r in await StringShortRule().validate(_ctx(plan)))


@pytest.mark.asyncio
async def test_srv142_and_srv143_check_drawn_rings() -> None:
    bow = {"type": "Polygon", "coordinates": [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]]}
    flat = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [0, 0]]]}
    good = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    plan = {
        "sketch": [{"id": "bow", "geometry": bow}, {"id": "flat", "geometry": flat}, {"id": "ok", "geometry": good}]
    }
    crosses = [r for r in await RingCrossesRule().validate(_ctx(plan)) if not r.passed]
    assert [r.element_ref for r in crosses] == ["bow"] and crosses[0].severity == Severity.ERROR
    assert "E 5.000, N 5.000" in crosses[0].message
    assert [r.element_ref for r in await RingOpenRule().validate(_ctx(plan)) if not r.passed] == ["flat"]


def test_ring_crossings_ignores_adjacent_edges() -> None:
    assert ring_crossings([(0, 0), (10, 0), (10, 10), (0, 10)]) == []


@pytest.mark.asyncio
async def test_srv144_names_duplicate_codes() -> None:
    plan = {"library": [{"code": "EP"}, {"code": "ep"}, {"code": "TR"}]}
    assert [r.element_ref for r in await CodeDuplicateRule().validate(_ctx(plan))] == ["EP"]


def test_the_riverside_library_knows_every_code_its_demo_points_use() -> None:
    # The showcase opened with SRV-140 findings for PIT and BASE: the shipped library lacked them.
    import json
    from pathlib import Path

    demo = Path(ref.__file__).resolve().parent / "demo" / "riverside"
    library = json.loads((demo / "codes_riverside.json").read_text(encoding="utf-8"))["items"]
    files = ("control.csv", "existing_ground.csv", "pit_2026-10-01.csv", "pit_2026-10-31.csv")
    files += ("stockpile_A_base.csv", "stockpile_A_2026-10-12.csv")
    codes = []
    for name in files:
        for line in (demo / name).read_text(encoding="utf-8").splitlines():
            cols = line.split(",")
            if len(cols) >= 5 and cols[1].replace(".", "", 1).isdigit():
                codes.append(cols[4].strip())
    assert {"PIT", "BASE"} <= {c.upper() for c in codes}
    assert ref.unknown_codes(codes, library) == {}
    assert all(entry["label"] for entry in library)


def test_chile_has_plan_conventions_and_a_spanish_code_library() -> None:
    conv, source = ref.country_conventions("CL")
    assert source == "country"
    assert (conv["axis"], conv["directionFormat"], conv["linearUnit"]) == ("EN", "azimuth", "m")
    codes = ref.country_codes("CL")
    assert codes and ref.duplicate_codes(codes) == []
    assert {c["code"]: c["label"] for c in codes}["KB"] == "Solera"
    assert "CL" in ref.library_countries()
    # The grids are the ones survey_reference already offers: SIRGAS-Chile 2016 / UTM 18S and 19S.
    epsg = {h["epsg"] for h in ref._reference()["CL"]["horizontal"] if h["role"] == "primary"}
    assert epsg == {9154, 9155}
