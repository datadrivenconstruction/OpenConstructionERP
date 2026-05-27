"""PATCH a GeoJSON crop polygon and a corners array; assert round-trip."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_crop_polygon_round_trip(http_client, tenant_a, tiny_png):
    files = {"file": ("img.png", tiny_png, "image/png")}
    create = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-image",
        data={"project_id": tenant_a["project_id"]},
        files=files,
        headers=tenant_a["headers"],
    )
    assert create.status_code == 201, create.text
    overlay_id = create.json()["id"]

    crop = {
        "type": "Polygon",
        "coordinates": [
            [
                [13.4050, 52.5200],
                [13.4060, 52.5210],
                [13.4070, 52.5195],
                [13.4055, 52.5190],
                [13.4050, 52.5200],
            ]
        ],
    }
    new_corners = [
        [13.4040, 52.5215],
        [13.4080, 52.5215],
        [13.4080, 52.5185],
        [13.4040, 52.5185],
    ]
    patch = await http_client.patch(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        json={
            "crop_polygon_geojson": crop,
            "corners_geojson": new_corners,
            "opacity": "0.45",
            "rotation_deg": "12.5",
            "z_order": 7,
            "visible": True,
        },
        headers=tenant_a["headers"],
    )
    assert patch.status_code == 200, patch.text

    fetched = await http_client.get(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        headers=tenant_a["headers"],
    )
    assert fetched.status_code == 200
    obj = fetched.json()
    assert obj["crop_polygon_geojson"] == crop
    assert obj["corners_geojson"] == new_corners
    assert float(obj["opacity"]) == pytest.approx(0.45)
    assert float(obj["rotation_deg"]) == pytest.approx(12.5)
    assert obj["z_order"] == 7
    assert obj["visible"] is True


@pytest.mark.asyncio
async def test_crop_polygon_must_be_valid_geojson(
    http_client,
    tenant_a,
    tiny_png,
):
    files = {"file": ("img2.png", tiny_png, "image/png")}
    create = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-image",
        data={"project_id": tenant_a["project_id"]},
        files=files,
        headers=tenant_a["headers"],
    )
    assert create.status_code == 201
    overlay_id = create.json()["id"]

    # Wrong type at top level.
    bad = await http_client.patch(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        json={
            "crop_polygon_geojson": {
                "type": "Point",
                "coordinates": [13.4, 52.5],
            },
        },
        headers=tenant_a["headers"],
    )
    assert bad.status_code == 422

    # Ring with < 3 points.
    too_few = await http_client.patch(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        json={
            "crop_polygon_geojson": {
                "type": "Polygon",
                "coordinates": [[[1, 1], [2, 2]]],
            },
        },
        headers=tenant_a["headers"],
    )
    assert too_few.status_code == 422

    # Wrong corners count.
    bad_corners = await http_client.patch(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        json={"corners_geojson": [[1, 1], [2, 2]]},
        headers=tenant_a["headers"],
    )
    assert bad_corners.status_code == 422
