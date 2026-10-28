# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-function tests for the OGC API - Features layer (no DB, no HTTP).

``app.modules.geo_hub.ogc_features`` keeps every decision a GIS client
depends on in small functions that take plain data: how ``bbox`` and
``datetime`` parse, what a geometry's envelope is, how an overlay row
explodes into features, and when a ``next`` link may be emitted. Those are
exercised here directly, because each of them fails in a way that is
invisible from the outside:

* a ``bbox`` that silently accepts an inverted rectangle returns nothing
  and looks like an empty dataset;
* an antimeridian box read as an ordinary one drops every feature in the
  Pacific;
* a ``next`` link emitted on the last page makes QGIS page forever, and one
  withheld too early makes it stop early - both look like "the data is
  wrong" rather than "the paging is wrong";
* an overlay whose stored properties happen to use the name ``overlay_id``
  would, without the stamping order asserted here, hand back somebody
  else's identity for the feature.

The service class itself needs a session and is covered in
``tests/integration/test_geo_hub_ogc_api.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.geo_hub.ogc_features import (
    COLLECTIONS,
    CONFORMANCE_CLASSES,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    BBox,
    OgcParameterError,
    anchor_feature,
    feature_collection,
    geometry_bounds,
    geometry_matches_bbox,
    get_collection,
    items_links,
    overlay_features,
    parse_bbox,
    parse_datetime,
    parse_feature_id,
    parse_limit,
    viewpoint_feature,
)

# ── bbox parsing ───────────────────────────────────────────────────────────


def test_bbox_parses_four_numbers() -> None:
    box = parse_bbox("13.0,52.3,13.8,52.7")
    assert box == BBox(west=13.0, south=52.3, east=13.8, north=52.7)


def test_bbox_parses_six_numbers_and_discards_elevation() -> None:
    """The 3D form is legal input; nothing we store is filtered by height."""
    box = parse_bbox("13.0,52.3,-10,13.8,52.7,120")
    assert box == BBox(west=13.0, south=52.3, east=13.8, north=52.7)


def test_bbox_absent_is_not_an_error() -> None:
    assert parse_bbox(None) is None
    assert parse_bbox("  ") is None


@pytest.mark.parametrize(
    "raw",
    [
        "1,2,3",
        "1,2,3,4,5",
        "a,b,c,d",
        "13.0,52.7,13.8,52.3",  # south above north
        "13.0,-91,13.8,52.7",  # latitude out of range
    ],
)
def test_bbox_rejects_nonsense(raw: str) -> None:
    with pytest.raises(OgcParameterError):
        parse_bbox(raw)


def test_bbox_west_greater_than_east_is_the_antimeridian_not_an_error() -> None:
    """A box that wraps past 180 is how the standard spells the Pacific."""
    box = parse_bbox("170,-20,-170,20")
    assert box is not None
    assert box.crosses_antimeridian


# ── bbox matching ──────────────────────────────────────────────────────────


def test_bbox_contains_point_on_a_plain_box() -> None:
    box = BBox(west=13.0, south=52.3, east=13.8, north=52.7)
    assert box.contains_point(13.4, 52.5)
    assert not box.contains_point(1.0, 52.5)
    assert not box.contains_point(13.4, 40.0)


def test_bbox_contains_point_across_the_antimeridian() -> None:
    box = BBox(west=170.0, south=-20.0, east=-170.0, north=20.0)
    assert box.contains_point(175.0, 0.0)
    assert box.contains_point(-175.0, 0.0)
    assert not box.contains_point(0.0, 0.0)


def test_bbox_intersects_bounds() -> None:
    box = BBox(west=0.0, south=0.0, east=10.0, north=10.0)
    assert box.intersects_bounds((5.0, 5.0, 15.0, 15.0))
    assert box.intersects_bounds((-5.0, -5.0, 0.0, 0.0))  # touching counts
    assert not box.intersects_bounds((11.0, 5.0, 12.0, 6.0))
    assert not box.intersects_bounds((5.0, 11.0, 6.0, 12.0))


def test_bbox_intersects_bounds_across_the_antimeridian() -> None:
    box = BBox(west=170.0, south=-20.0, east=-170.0, north=20.0)
    assert box.intersects_bounds((178.0, 0.0, 179.0, 1.0))
    assert box.intersects_bounds((-179.0, 0.0, -178.0, 1.0))
    assert not box.intersects_bounds((0.0, 0.0, 1.0, 1.0))


# ── datetime parsing ───────────────────────────────────────────────────────


def test_datetime_absent_is_unbounded() -> None:
    assert parse_datetime(None) == (None, None)
    assert parse_datetime("") == (None, None)


def test_datetime_instant_bounds_both_ends() -> None:
    start, end = parse_datetime("2026-08-21T09:00:00Z")
    assert start == end == datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


def test_datetime_closed_interval() -> None:
    start, end = parse_datetime("2026-01-01T00:00:00Z/2026-12-31T23:59:59Z")
    assert start == datetime(2026, 1, 1, tzinfo=UTC)
    assert end == datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)


@pytest.mark.parametrize("raw", ["2026-01-01T00:00:00Z/..", "2026-01-01T00:00:00Z/"])
def test_datetime_open_ended_interval(raw: str) -> None:
    start, end = parse_datetime(raw)
    assert start == datetime(2026, 1, 1, tzinfo=UTC)
    assert end is None


@pytest.mark.parametrize("raw", ["../2026-01-01T00:00:00Z", "/2026-01-01T00:00:00Z"])
def test_datetime_open_started_interval(raw: str) -> None:
    start, end = parse_datetime(raw)
    assert start is None
    assert end == datetime(2026, 1, 1, tzinfo=UTC)


def test_datetime_naive_input_is_read_as_utc() -> None:
    """A client that forgets the Z must not shift the window by the host's offset."""
    start, _ = parse_datetime("2026-08-21T09:00:00")
    assert start == datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-date",
        "2026-13-01T00:00:00Z",
        "2026-12-31T00:00:00Z/2026-01-01T00:00:00Z",  # runs backwards
    ],
)
def test_datetime_rejects_nonsense(raw: str) -> None:
    with pytest.raises(OgcParameterError):
        parse_datetime(raw)


# ── limit ──────────────────────────────────────────────────────────────────


def test_limit_defaults_and_clamps() -> None:
    assert parse_limit(None) == DEFAULT_LIMIT
    assert parse_limit(25) == 25
    assert parse_limit(MAX_LIMIT * 10) == MAX_LIMIT


def test_limit_rejects_zero_and_negatives() -> None:
    with pytest.raises(OgcParameterError):
        parse_limit(0)
    with pytest.raises(OgcParameterError):
        parse_limit(-5)


# ── geometry envelopes ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("geometry", "expected"),
    [
        ({"type": "Point", "coordinates": [13.4, 52.5]}, (13.4, 52.5, 13.4, 52.5)),
        # A 3D position must not be read as two separate 2D ones.
        ({"type": "Point", "coordinates": [13.4, 52.5, 34.0]}, (13.4, 52.5, 13.4, 52.5)),
        ({"type": "LineString", "coordinates": [[0, 0], [3, 4]]}, (0.0, 0.0, 3.0, 4.0)),
        (
            {"type": "Polygon", "coordinates": [[[1, 2], [3, 4], [5, 1], [1, 2]]]},
            (1.0, 1.0, 5.0, 4.0),
        ),
        (
            {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 1], [0, 1], [0, 0]]]]},
            (0.0, 0.0, 1.0, 1.0),
        ),
    ],
)
def test_geometry_bounds(geometry: dict, expected: tuple) -> None:
    assert geometry_bounds(geometry) == expected


def test_geometry_bounds_of_a_geometry_collection() -> None:
    geometry = {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "Point", "coordinates": [0, 0]},
            {"type": "Point", "coordinates": [10, 20]},
        ],
    }
    assert geometry_bounds(geometry) == (0.0, 0.0, 10.0, 20.0)


@pytest.mark.parametrize("geometry", [None, {}, {"type": "Point", "coordinates": []}, "nonsense"])
def test_geometry_bounds_of_nothing_is_none(geometry: object) -> None:
    assert geometry_bounds(geometry) is None


def test_a_geometryless_feature_survives_no_filter_and_fails_a_bbox() -> None:
    """Null geometry is legal GeoJSON, and has no position to compare."""
    assert geometry_matches_bbox(None, None)
    assert not geometry_matches_bbox(None, BBox(west=0, south=0, east=1, north=1))


# ── anchor features ────────────────────────────────────────────────────────


def _anchor_row(**overrides: object) -> dict:
    row = {
        "project_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "project_name": "Berlin Tower",
        "anchor_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "lat": Decimal("52.5200"),
        "lon": Decimal("13.4050"),
        "alt": Decimal("34.00"),
        "region_code": "DE-BE",
        "address": "Alexanderplatz 1",
        "project_type": "commercial",
        "status": "active",
        "project_address_text": "Alexanderplatz 1, Berlin",
    }
    row.update(overrides)
    return row


def test_anchor_feature_is_lon_lat_and_keeps_altitude_as_an_attribute() -> None:
    feature = anchor_feature(_anchor_row())
    assert feature is not None
    # CRS84 is longitude first. Getting this backwards puts Berlin in Somalia.
    assert feature["geometry"] == {"type": "Point", "coordinates": [13.405, 52.52]}
    assert feature["id"] == "11111111-1111-1111-1111-111111111111"
    assert feature["properties"]["altitude_m"] == 34.0
    assert feature["properties"]["anchored"] is True
    assert feature["properties"]["project_name"] == "Berlin Tower"


def test_anchor_feature_drops_the_null_island_placeholder() -> None:
    """0/0 is the anchor written before anyone said where the project is.

    It is a real coordinate in the Gulf of Guinea, so serving it would put a
    pin there for every project nobody has placed yet.
    """
    assert anchor_feature(_anchor_row(lat=Decimal("0"), lon=Decimal("0"))) is None


def test_anchor_feature_keeps_a_genuine_zero_on_one_axis() -> None:
    """Greenwich is a real longitude; only 0/0 together is the placeholder."""
    feature = anchor_feature(_anchor_row(lon=Decimal("0"), lat=Decimal("51.4778")))
    assert feature is not None


def test_anchor_feature_marks_an_address_derived_pin_as_unanchored() -> None:
    feature = anchor_feature(_anchor_row(anchor_id=None))
    assert feature is not None
    assert feature["properties"]["anchored"] is False
    assert feature["properties"]["anchor_id"] is None


# ── overlay features ───────────────────────────────────────────────────────


def _overlay(geojson: object, **overrides: object) -> SimpleNamespace:
    row = {
        "id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "project_id": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "name": "Site boundary",
        "kind": "boundary",
        "geojson": geojson,
        "source_file": "boundary.kml",
        "source_event_id": None,
        "is_visible": True,
        "created_at": datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    }
    row.update(overrides)
    return SimpleNamespace(**row)


def test_overlay_explodes_a_feature_collection_with_stable_ids() -> None:
    overlay = _overlay(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {"a": 1}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 4]}, "properties": {}},
            ],
        },
    )
    features = overlay_features(overlay)
    assert [f["id"] for f in features] == [
        "33333333-3333-3333-3333-333333333333:0",
        "33333333-3333-3333-3333-333333333333:1",
    ]
    assert features[0]["properties"]["a"] == 1


def test_overlay_accepts_a_bare_feature() -> None:
    overlay = _overlay({"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {}})
    features = overlay_features(overlay)
    assert len(features) == 1
    assert features[0]["id"].endswith(":0")


def test_overlay_accepts_a_bare_geometry() -> None:
    overlay = _overlay({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
    features = overlay_features(overlay)
    assert len(features) == 1
    assert features[0]["geometry"]["type"] == "Polygon"


@pytest.mark.parametrize("geojson", [{}, None, {"type": "FeatureCollection", "features": []}])
def test_overlay_with_nothing_in_it_yields_nothing(geojson: object) -> None:
    assert overlay_features(_overlay(geojson)) == []


def test_overlay_identity_wins_over_imported_property_names() -> None:
    """An imported file that happens to carry ``overlay_id`` must not win.

    The stamped keys are how a client tells which row and which project a
    feature came from; letting arbitrary imported data overwrite them would
    make a feature claim to belong somewhere it does not.
    """
    overlay = _overlay(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [1, 2]},
                    "properties": {"overlay_id": "spoofed", "project_id": "spoofed"},
                },
            ],
        },
    )
    properties = overlay_features(overlay)[0]["properties"]
    assert properties["overlay_id"] == "33333333-3333-3333-3333-333333333333"
    assert properties["project_id"] == "44444444-4444-4444-4444-444444444444"


def test_overlay_timestamps_are_rfc3339_utc() -> None:
    overlay = _overlay({"type": "Feature", "geometry": None, "properties": {}})
    assert overlay_features(overlay)[0]["properties"]["created_at"] == "2026-08-20T12:00:00Z"


# ── viewpoint features ─────────────────────────────────────────────────────


def test_viewpoint_feature() -> None:
    viewpoint = SimpleNamespace(
        id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        project_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
        name="South approach",
        description="Camera for the tender render",
        camera_lat=Decimal("52.5200"),
        camera_lon=Decimal("13.4050"),
        camera_alt=Decimal("250.00"),
        heading=Decimal("180.000"),
        pitch=Decimal("-30.000"),
        roll=Decimal("0.000"),
        created_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )
    feature = viewpoint_feature(viewpoint)
    assert feature is not None
    assert feature["geometry"]["coordinates"] == [13.405, 52.52]
    assert feature["properties"]["camera_altitude_m"] == 250.0
    assert feature["properties"]["heading_deg"] == 180.0
    assert feature["properties"]["pitch_deg"] == -30.0


# ── feature ids ────────────────────────────────────────────────────────────


def test_parse_feature_id_splits_row_and_index() -> None:
    parsed = parse_feature_id("33333333-3333-3333-3333-333333333333:7")
    assert parsed == (uuid.UUID("33333333-3333-3333-3333-333333333333"), 7)


def test_parse_feature_id_defaults_a_bare_uuid_to_index_zero() -> None:
    parsed = parse_feature_id("33333333-3333-3333-3333-333333333333")
    assert parsed == (uuid.UUID("33333333-3333-3333-3333-333333333333"), 0)


@pytest.mark.parametrize("raw", ["", "not-a-uuid:0", "33333333-3333-3333-3333-333333333333:x", "x:-1"])
def test_parse_feature_id_rejects_nonsense(raw: str) -> None:
    """An unparseable id has to become a 404, never a 500."""
    assert parse_feature_id(raw) is None


# ── paging links ───────────────────────────────────────────────────────────


def _links(**overrides: object) -> dict[str, str]:
    kwargs: dict = {
        "items_url": "https://host/api/v1/geo-hub/ogc/collections/geo-overlays/items",
        "collection_url": "https://host/api/v1/geo-hub/ogc/collections/geo-overlays",
        "query": {},
        "offset": 0,
        "limit": 10,
        "number_returned": 10,
        "number_matched": 25,
    }
    kwargs.update(overrides)
    return {item["rel"]: item["href"] for item in items_links(**kwargs)}


def test_first_page_offers_next_and_no_prev() -> None:
    rels = _links()
    assert "next" in rels
    assert "prev" not in rels
    assert "offset=10" in rels["next"]


def test_middle_page_offers_both() -> None:
    rels = _links(offset=10)
    assert "offset=20" in rels["next"]
    assert "offset=0" not in rels["prev"]  # offset 0 is omitted, not written out
    assert rels["prev"].endswith("limit=10")


def test_last_page_withholds_next() -> None:
    """Emitting next on the last page is what makes a client page forever."""
    rels = _links(offset=20, number_returned=5)
    assert "next" not in rels
    assert "prev" in rels


def test_an_unknown_count_offers_next_only_while_pages_come_back_full() -> None:
    assert "next" in _links(number_matched=None, number_returned=10)
    assert "next" not in _links(number_matched=None, number_returned=3)


def test_links_carry_the_filters_forward() -> None:
    """A next link that drops the bbox silently changes the query mid-page."""
    rels = _links(query={"bbox": "1,2,3,4", "project_id": "abc", "datetime": None})
    assert "bbox=1%2C2%2C3%2C4" in rels["next"]
    assert "project_id=abc" in rels["next"]
    assert "datetime" not in rels["next"]


def test_links_always_point_back_at_the_collection() -> None:
    assert _links()["collection"].endswith("/collections/geo-overlays")


# ── envelope ───────────────────────────────────────────────────────────────


def test_feature_collection_reports_what_it_returned() -> None:
    body = feature_collection([{"type": "Feature"}], number_matched=42, links=[])
    assert body["type"] == "FeatureCollection"
    assert body["numberReturned"] == 1
    assert body["numberMatched"] == 42
    assert body["timeStamp"].endswith("Z")


def test_feature_collection_omits_a_count_it_cannot_stand_behind() -> None:
    """Omission is legal; a guess would make a client stop early or loop."""
    body = feature_collection([], number_matched=None, links=[])
    assert "numberMatched" not in body
    assert body["numberReturned"] == 0


# ── catalogue ──────────────────────────────────────────────────────────────


def test_collection_ids_are_unique_and_resolvable() -> None:
    names = [spec.name for spec in COLLECTIONS]
    assert len(names) == len(set(names))
    for name in names:
        assert get_collection(name) is not None
    assert get_collection("no-such-collection") is None


def test_only_collections_with_a_time_advertise_one() -> None:
    """project-anchors has no honest creation time - an address-derived
    location is not an event that happened at a moment."""
    assert get_collection("project-anchors").temporal is False
    assert get_collection("geo-overlays").temporal is True
    assert get_collection("viewpoints").temporal is True


def test_conformance_does_not_claim_html() -> None:
    """This service returns JSON only; claiming html sends clients nowhere."""
    assert not any(uri.endswith("/html") for uri in CONFORMANCE_CLASSES)
    assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core" in CONFORMANCE_CLASSES
    assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson" in CONFORMANCE_CLASSES
