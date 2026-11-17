# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcel files: the Riverside GeoJSON, a Shapefile round trip and the DXF export."""

from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.land_parcels.geometry import shoelace_area
from app.modules.land_parcels.parcel_io import (
    parse_geojson,
    parse_shapefile_zip,
    to_dxf,
    to_geojson,
    to_shapefile_zip,
)

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "land_parcels" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["land_parcels"]


def _area(ring: list[tuple[float, float]]) -> Decimal:
    return shoelace_area([(Decimal(str(round(x, 4))), Decimal(str(round(y, 4)))) for x, y in ring]).quantize(
        Decimal("0.01")
    )


def test_riverside_geojson_reads_three_parcels_and_the_lesson_total() -> None:
    parsed = parse_geojson((DEMO / "parcels.geojson").read_text(encoding="utf-8"))
    assert parsed.epsg == 32633
    assert not parsed.problems
    assert [f.ref for f in parsed.features] == ["P-001", "P-002", "P-003"]
    assert all(f.closed for f in parsed.features)
    assert sum(_area(f.ring) for f in parsed.features) == Decimal(EXPECTED["lesson_1"]["total_area_m2"])
    p1 = parsed.features[0]
    assert _area(p1.ring) == Decimal(EXPECTED["lesson_2"]["computed_area_m2"])
    assert p1.legal_area == Decimal("1203")
    assert [f.status for f in parsed.features] == ["acquired", "acquired", "negotiating"]


def test_geojson_problems_are_reported_not_raised() -> None:
    doc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"parcel_id": "A"}, "geometry": {"type": "Point", "coordinates": [1, 2]}},
            {
                "type": "Feature",
                "properties": {"parcel_id": "B"},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10]]]},
            },
        ],
    }
    parsed = parse_geojson(json.dumps(doc))
    assert [p["code"] for p in parsed.problems] == ["no_polygon"]
    assert parsed.features[0].ref == "B"
    assert parsed.features[0].closed is False
    assert parsed.epsg is None


def test_geojson_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="Not a JSON file"):
        parse_geojson("not json")


def test_shapefile_round_trip_keeps_ids_areas_and_crs() -> None:
    parsed = parse_geojson((DEMO / "parcels.geojson").read_text(encoding="utf-8"))
    rows = [
        {
            "ref": f.ref,
            "name": f.name,
            "status": f.status,
            "legal_area": f.legal_area,
            "computed_area": _area(f.ring),
            "ring": f.ring,
        }
        for f in parsed.features
    ]
    data = to_shapefile_zip(rows, 32633)
    names = sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert names == ["parcels.cpg", "parcels.dbf", "parcels.prj", "parcels.shp", "parcels.shx"]
    back = parse_shapefile_zip(data)
    assert back.epsg == 32633
    assert len(back.features) == EXPECTED["lesson_5"]["zip_features"]
    assert [f.ref for f in back.features] == ["P-001", "P-002", "P-003"]
    assert [_area(f.ring) for f in back.features] == [_area(f.ring) for f in parsed.features]
    assert back.features[0].legal_area == Decimal("1203.00")
    assert back.features[2].status == "negotiating"


def test_shipped_demo_shapefile_matches_the_geojson() -> None:
    back = parse_shapefile_zip((DEMO / "parcels_shp.zip").read_bytes())
    assert [f.ref for f in back.features] == ["P-001", "P-002", "P-003"]
    assert sum(_area(f.ring) for f in back.features) == Decimal(EXPECTED["lesson_1"]["total_area_m2"])


def test_shapefile_zip_without_dbf_is_refused() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.shp", b"")
    with pytest.raises(ValueError, match=r"\.dbf"):
        parse_shapefile_zip(buf.getvalue())


def test_geojson_export_round_trip() -> None:
    ring = [(389000.0, 5819000.0), (389010.0, 5819000.0), (389010.0, 5819010.0), (389000.0, 5819010.0)]
    data = to_geojson(
        [{"ref": "X-1", "ring": ring, "legal_area": Decimal("100"), "computed_area": Decimal("100.00")}], 32633
    )
    back = parse_geojson(data.decode("utf-8"))
    assert back.epsg == 32633
    assert back.features[0].ref == "X-1"
    assert back.features[0].closed
    assert _area(back.features[0].ring) == Decimal("100.00")


def test_dxf_export_has_closed_boundaries_and_ids() -> None:
    import ezdxf

    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    points = [{"label": f"B{i}", "e": x, "n": y} for i, (x, y) in enumerate(ring, 1)]
    data = to_dxf([{"ref": "X-1", "ring": ring, "points": points}])
    doc = ezdxf.read(io.StringIO(data.decode("utf-8")))
    msp = doc.modelspace()
    polys = msp.query("LWPOLYLINE")
    assert len(polys) == 1
    assert polys[0].closed
    assert {t.dxf.text for t in msp.query("TEXT")} >= {"X-1", "B1"}
    assert len(msp.query("POINT")) == 4
