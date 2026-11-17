# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordinate transforms against published reference values, and the picker's edges."""

from __future__ import annotations

import math

import pytest

from app.modules.survey_core import crs as crs_lib
from app.modules.survey_core.crs import (
    describe,
    pack_crs_for,
    register_pack_crs,
    search,
    transform_points,
    utm_epsg_for,
)


def _one(lon: float, lat: float, source: int, target: int) -> tuple[float, float]:
    [(x, y, _z)] = transform_points([(lon, lat, None)], source, target)
    return x, y


def test_proj_never_reaches_for_the_network() -> None:
    from pyproj.network import is_network_enabled

    assert not is_network_enabled()


# -- published worked examples (EPSG Guidance Note 7-2) ------------------------------------------------------------


def test_transverse_mercator_british_national_grid_worked_example() -> None:
    # Airy 1830 (OSGB36) 50 30 00 N, 00 30 00 E -> E 577 274.99 m, N 69 740.50 m.
    e, n = _one(0.5, 50.5, 4277, 27700)
    assert e == pytest.approx(577274.99, abs=0.01)
    assert n == pytest.approx(69740.50, abs=0.01)


def test_lambert_conic_texas_south_central_worked_example_in_us_survey_feet() -> None:
    # Clarke 1866 (NAD27) 28 30 00 N, 96 00 00 W -> E 2 963 503.91 ftUS, N 254 759.80 ftUS.
    assert describe(32040).unit == "US survey foot"
    e, n = _one(-96.0, 28.5, 4267, 32040)
    assert e == pytest.approx(2963503.91, abs=0.01)
    assert n == pytest.approx(254759.80, abs=0.01)


def test_utm_north_of_the_equator_on_the_central_meridian() -> None:
    # Meridian arc to 45 N on WGS 84 is 4 984 944.38 m; UTM scale on the central meridian is 0.9996.
    e, n = _one(15.0, 45.0, 4326, 32633)
    assert e == pytest.approx(500000.0, abs=1e-6)
    assert n == pytest.approx(4984944.378 * 0.9996, abs=0.02)


def test_utm_southern_hemisphere_adds_the_false_northing() -> None:
    e, n = _one(15.0, 0.0, 4326, 32733)
    assert (round(e, 6), round(n, 6)) == (500000.0, 10000000.0)


def test_web_mercator_top_of_the_square() -> None:
    e, n = _one(180.0, 85.0511287798066, 4326, 3857)
    assert e == pytest.approx(20037508.342789244, abs=1e-5)
    assert n == pytest.approx(20037508.342789244, abs=1e-3)


def test_lon_lat_order_not_lat_lon_is_what_the_register_takes() -> None:
    e, n = _one(13.4, 52.5, 4326, 32633)
    assert 380_000 < e < 400_000
    assert 5_800_000 < n < 5_840_000
    swapped = _one(52.5, 13.4, 4326, 32633)
    assert abs(swapped[0] - e) > 1_000_000


# -- consistency -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("zone_epsg", [32631, 32632, 32633, 32634])
def test_round_trip_through_neighbouring_zones_is_within_a_millimetre(zone_epsg: int) -> None:
    e, n = _one(12.0, 52.0, 4326, zone_epsg)
    lon, lat = _one(e, n, zone_epsg, 4326)
    assert lon == pytest.approx(12.0, abs=1e-9)
    assert lat == pytest.approx(52.0, abs=1e-9)


def test_a_point_on_a_zone_boundary_agrees_between_the_two_zones() -> None:
    # 12 E is the line between zones 32 and 33; the same ground point must come back from either.
    e32, n32 = _one(12.0, 52.0, 4326, 32632)
    back = _one(e32, n32, 32632, 32633)
    direct = _one(12.0, 52.0, 4326, 32633)
    assert back[0] == pytest.approx(direct[0], abs=1e-3)
    assert back[1] == pytest.approx(direct[1], abs=1e-3)


def test_etrs89_and_wgs84_utm_agree_to_the_ballpark_without_grids() -> None:
    wgs = _one(13.4, 52.5, 4326, 32633)
    etrs = _one(13.4, 52.5, 4326, 25833)
    assert math.dist(wgs, etrs) < 2.5


def test_heights_pass_through_untouched_even_when_zero_or_negative() -> None:
    out = transform_points([(13.4, 52.5, 0.0), (13.4, 52.5, -12.345), (13.4, 52.5, None)], 4326, 32633)
    assert [z for _, _, z in out] == [0.0, -12.345, None]


def test_an_empty_list_transforms_to_an_empty_list() -> None:
    assert transform_points([], 4326, 32633) == []


def test_ten_thousand_points_in_one_call() -> None:
    pts = [(13.0 + i * 1e-4, 52.0 + i * 1e-4, None) for i in range(10_000)]
    out = transform_points(pts, 4326, 32633)
    assert len(out) == 10_000
    assert out[0][0] < out[-1][0]


def test_unknown_codes_are_refused_on_either_side() -> None:
    with pytest.raises(ValueError):
        transform_points([(1.0, 2.0, None)], 999999, 32633)
    with pytest.raises(ValueError):
        transform_points([(1.0, 2.0, None)], 4326, 999999)


def test_a_point_that_cannot_be_projected_is_an_error_not_infinity() -> None:
    # 90 degrees from the central meridian of zone 33 the Transverse Mercator series has no answer.
    with pytest.raises(ValueError):
        transform_points([(105.0, 0.0, None)], 4326, 32633)


# -- the picker --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["EPSG:32633", "epsg 32633", "EPSG::32633", "  32633  "])
def test_a_typed_code_in_any_common_spelling_finds_it_first(query: str) -> None:
    assert search(query)[0].epsg == 32633


def test_a_code_prefix_lists_the_codes_that_start_with_it_in_order() -> None:
    hits = [h.epsg for h in search("3263", limit=50)]
    assert 32633 in hits
    rest = [e for e in hits if e != 3263]
    assert rest == sorted(rest)
    assert all(str(e).startswith("3263") for e in hits)


@pytest.mark.parametrize(
    "query", ["", " ", "x", "%", "'; DROP TABLE oe_survey_point; --", "Берлин", "برلين", "ZZZZZZZZ"]
)
def test_odd_queries_return_a_list_never_an_error(query: str) -> None:
    assert isinstance(search(query), list)


def test_the_limit_is_honoured() -> None:
    assert len(search("UTM", limit=5)) == 5


def test_search_by_name_is_case_insensitive_and_word_order_free() -> None:
    assert any(h.epsg == 32633 for h in search("utm 33n wgs"))


def test_wgs84_geographic_is_what_a_plain_wgs_query_finds_first() -> None:
    assert search("WGS 84")[0].epsg == 4326


@pytest.mark.parametrize(
    ("epsg", "kind", "unit"),
    [
        (4326, "geographic", "degree"),
        (32633, "projected", "metre"),
        (5778, "vertical", "metre"),
        (7405, "compound", "metre"),
    ],
)
def test_describe_kinds_and_units(epsg: int, kind: str, unit: str) -> None:
    info = describe(epsg)
    assert (info.kind, info.unit) == (kind, unit)


@pytest.mark.parametrize("bad", [0, -1, 1, 10**9])
def test_describe_refuses_codes_that_are_not_systems(bad: int) -> None:
    with pytest.raises(ValueError):
        describe(bad)


@pytest.mark.parametrize(
    ("lat", "lon", "epsg"),
    [
        (0.0, 180.0, 32660),
        (0.0, -180.0, 32601),
        (0.0, 6.0, 32632),
        (84.0, 0.0, 32631),
        (-80.0, 0.0, 32731),
        (-0.0001, 15.0, 32733),
    ],
)
def test_utm_zone_edges(lat: float, lon: float, epsg: int) -> None:
    assert utm_epsg_for(lat, lon) == epsg


@pytest.mark.parametrize(("lat", "lon"), [(84.1, 0.0), (-80.1, 0.0), (0.0, 180.1), (0.0, -181.0)])
def test_utm_has_no_zone_beyond_its_limits(lat: float, lon: float) -> None:
    assert utm_epsg_for(lat, lon) is None


# -- packs -------------------------------------------------------------------------------------------------------


def test_pack_systems_reach_only_the_markets_of_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crs_lib, "_PACK_CRS", {})
    register_pack_crs("de", [(25833, "ETRS89 / UTM 33N")])
    register_pack_crs("PL", [(2180, "PL-1992")])
    assert pack_crs_for(["DE"]) == [(25833, "ETRS89 / UTM 33N", "DE")]
    assert [e for e, _, _ in pack_crs_for([" de ", "pl"])] == [25833, 2180]
    assert pack_crs_for(["US"]) == []
    assert pack_crs_for([]) == []
    assert pack_crs_for(["*"]) == []
