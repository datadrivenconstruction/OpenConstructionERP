# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordinate reference systems through pyproj, checked on known EPSG reference points."""

from __future__ import annotations

import pytest

from app.modules.survey_core.crs import describe, search, transform_points, utm_epsg_for


def test_utm_32633_is_projected_in_metres() -> None:
    info = describe(32633)
    assert info.name == "WGS 84 / UTM zone 33N"
    assert info.kind == "projected"
    assert info.unit == "metre"
    assert not info.is_geographic


def test_4326_is_geographic_and_says_so() -> None:
    info = describe(4326)
    assert info.is_geographic
    assert info.kind == "geographic"


def test_unknown_code_is_refused() -> None:
    with pytest.raises(ValueError):
        describe(999999)


def test_search_by_code_puts_the_exact_code_first() -> None:
    hits = search("32633")
    assert hits[0].epsg == 32633


def test_search_by_name_finds_the_zone() -> None:
    assert any(h.epsg == 32633 for h in search("UTM zone 33N"))


def test_short_search_returns_nothing() -> None:
    assert search("3") == []


@pytest.mark.parametrize(
    ("lat", "lon", "epsg"),
    [(52.51, 13.38, 32633), (-33.87, 151.21, 32756), (40.71, -74.0, 32618), (0.0, 0.0, 32631)],
)
def test_utm_zone_follows_the_pin(lat: float, lon: float, epsg: int) -> None:
    assert utm_epsg_for(lat, lon) == epsg


def test_utm_zone_refuses_an_impossible_pin() -> None:
    assert utm_epsg_for(95.0, 13.0) is None


def test_central_meridian_maps_to_false_easting() -> None:
    # On the central meridian of zone 33 (15 E) easting is exactly 500 000 m, on the equator northing is 0.
    [(e, n, _z)] = transform_points([(15.0, 0.0, None)], 4326, 32633)
    assert e == pytest.approx(500000.0, abs=1e-6)
    assert n == pytest.approx(0.0, abs=1e-6)


def test_web_mercator_reference_point() -> None:
    [(x, y, _z)] = transform_points([(180.0, 0.0, None)], 4326, 3857)
    assert x == pytest.approx(20037508.342789244, abs=1e-6)
    assert y == pytest.approx(0.0, abs=1e-6)


def test_riverside_origin_round_trips_within_a_millimetre() -> None:
    [(lon, lat, _)] = transform_points([(389000.0, 5819000.0, 34.0)], 32633, 4326)
    assert 13.3 < lon < 13.5
    assert 52.4 < lat < 52.6
    [(e, n, z)] = transform_points([(lon, lat, 34.0)], 4326, 32633)
    assert e == pytest.approx(389000.0, abs=1e-3)
    assert n == pytest.approx(5819000.0, abs=1e-3)
    assert z == 34.0


def test_same_system_is_returned_untouched() -> None:
    pts = [(389000.0, 5819000.0, 34.0)]
    assert transform_points(pts, 32633, 32633) == pts
