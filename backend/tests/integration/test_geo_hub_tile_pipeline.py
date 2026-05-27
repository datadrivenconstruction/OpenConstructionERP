"""Pure-function tests for the geo_hub tile pipeline.

No DB, no HTTP — exercises the canonical-JSON -> glTF -> 3D Tiles
build stages directly. Each stage is verifiable against the OGC 3D
Tiles 1.1 spec without spinning up the FastAPI app.
"""

from __future__ import annotations

import json
import struct

from app.modules.geo_hub.coord_transforms import (
    ecef_to_enu,
    ecef_to_wgs84,
    enu_to_ecef,
    transform,
    web_mercator_to_wgs84,
    wgs84_to_ecef,
    wgs84_to_web_mercator,
)
from app.modules.geo_hub.tile_pipeline import (
    TileAABB,
    build_gltf_for_tile,
    build_tile_artifacts,
    build_tileset_json,
    compute_aabb,
    partition_by_aabb,
    write_b3dm,
)

# ── Fixtures (pure data) ────────────────────────────────────────────────


def _elements(n: int = 4) -> list[dict]:
    out = []
    for i in range(n):
        out.append(
            {
                "id": f"elem_{i:03d}",
                "category": "wall" if i % 2 == 0 else "slab",
                "classification": {
                    "din276": "330" if i % 2 == 0 else "350",
                    "nrm": f"2.{i}.1",
                    "masterformat": "04 20 00" if i % 2 == 0 else "03 30 00",
                },
                "geometry": {
                    "aabb": [
                        i * 5.0,
                        0.0,
                        0.0,
                        i * 5.0 + 4.5,
                        0.3,
                        3.0,
                    ],
                    "area_m2": 13.5,
                    "volume_m3": 4.0,
                },
                "quantities": {"area_m2": 13.5, "volume_m3": 4.0},
                "validation_status": "passed",
            },
        )
    return out


# ── Stage 2: AABB ───────────────────────────────────────────────────────


class TestComputeAabb:
    def test_empty_input(self):
        aabb = compute_aabb([])
        assert aabb.is_empty()

    def test_single_element(self):
        aabb = compute_aabb(_elements(1))
        assert aabb.min_x == 0.0
        assert aabb.max_x == 4.5
        assert aabb.max_z == 3.0

    def test_union_over_many_elements(self):
        aabb = compute_aabb(_elements(4))
        # 4 walls/slabs side-by-side along x.
        assert aabb.min_x == 0.0
        assert aabb.max_x == 3 * 5.0 + 4.5
        assert aabb.max_z == 3.0

    def test_handles_elements_with_no_geometry(self):
        elems = _elements(2) + [{"id": "no_geom", "category": "annotation"}]
        aabb = compute_aabb(elems)
        # The no-geometry element is silently dropped.
        assert aabb.max_x == 1 * 5.0 + 4.5

    def test_diagonal_metric(self):
        aabb = TileAABB(0, 0, 0, 3, 4, 0)
        assert abs(aabb.diagonal_m - 5.0) < 1e-9


# ── Stage 3: partition ──────────────────────────────────────────────────


class TestPartitionByAabb:
    def test_single_tile_is_identity(self):
        elems = _elements(4)
        groups = partition_by_aabb(elems, target_tile_count=1)
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_two_tiles_splits_along_longest_axis(self):
        elems = _elements(4)
        groups = partition_by_aabb(elems, target_tile_count=2)
        assert len(groups) == 2
        assert sum(len(g) for g in groups) == 4

    def test_partition_is_deterministic(self):
        # Two calls on identical input must produce identical outputs.
        groups_a = partition_by_aabb(_elements(8), target_tile_count=4)
        groups_b = partition_by_aabb(_elements(8), target_tile_count=4)
        a_signature = [sorted(e["id"] for e in g) for g in groups_a]
        b_signature = [sorted(e["id"] for e in g) for g in groups_b]
        assert a_signature == b_signature


# ── Stage 4: glTF ───────────────────────────────────────────────────────


class TestBuildGltf:
    def test_metadata_table_carries_classification(self):
        build = build_gltf_for_tile(_elements(3))
        assert build.feature_count == 3
        rows = build.metadata_table
        assert rows["din276"] == ["330", "350", "330"]
        assert rows["element_id"] == ["elem_000", "elem_001", "elem_002"]

    def test_gltf_declares_extensions(self):
        build = build_gltf_for_tile(_elements(2))
        assert "EXT_mesh_features" in build.gltf["extensionsUsed"]
        assert "EXT_structural_metadata" in build.gltf["extensionsUsed"]

    def test_property_table_count_matches_features(self):
        build = build_gltf_for_tile(_elements(5))
        tbl = build.gltf["extensions"]["EXT_structural_metadata"]["propertyTables"][0]
        assert tbl["count"] == 5
        assert len(tbl["properties"]["din276"]["values"]) == 5

    def test_binary_blob_is_4_byte_aligned(self):
        build = build_gltf_for_tile(_elements(3))
        assert len(build.binary_blob) % 4 == 0


# ── Stage 5: b3dm wrapper ───────────────────────────────────────────────


class TestWriteB3dm:
    def test_b3dm_has_correct_magic(self):
        build = build_gltf_for_tile(_elements(2))
        blob = write_b3dm(
            build.gltf,
            build.binary_blob,
            feature_table={"BATCH_LENGTH": build.feature_count},
        )
        assert blob[:4] == b"b3dm"

    def test_b3dm_header_byte_length_matches_blob(self):
        build = build_gltf_for_tile(_elements(2))
        blob = write_b3dm(
            build.gltf,
            build.binary_blob,
            feature_table={"BATCH_LENGTH": build.feature_count},
        )
        # Header: [4 magic][4 version][4 byteLength]... — uint32 little-endian.
        byte_length = struct.unpack("<I", blob[8:12])[0]
        assert byte_length == len(blob)

    def test_b3dm_payload_starts_8byte_aligned(self):
        build = build_gltf_for_tile(_elements(2))
        blob = write_b3dm(
            build.gltf,
            build.binary_blob,
            feature_table={"BATCH_LENGTH": build.feature_count},
        )
        # Find the embedded glb. It starts with "glTF" magic.
        idx = blob.find(b"glTF")
        assert idx != -1
        assert idx % 8 == 0, f"glb payload starts at byte {idx} which is not 8-byte aligned"


# ── Stage 6: tileset.json ───────────────────────────────────────────────


class TestBuildTilesetJson:
    def test_spec_required_keys_present(self):
        aabb = TileAABB(0, 0, 0, 10, 10, 5)
        out = build_tileset_json(
            aabb,
            content_uri="tile_0.b3dm",
            anchor_lat=52.52,
            anchor_lon=13.40,
        )
        assert out["asset"]["version"] == "1.1"
        assert "geometricError" in out
        assert "root" in out
        assert "boundingVolume" in out["root"]
        assert "content" in out["root"]
        assert out["root"]["content"]["uri"] == "tile_0.b3dm"

    def test_bounding_volume_is_region_in_radians(self):
        aabb = TileAABB(-50, -50, 0, 50, 50, 30)
        out = build_tileset_json(
            aabb,
            content_uri="tile_0.b3dm",
            anchor_lat=51.5,  # London
            anchor_lon=-0.12,
            anchor_alt=10.0,
        )
        region = out["root"]["boundingVolume"]["region"]
        assert len(region) == 6
        west, south, east, north, min_h, max_h = region
        # Region values are in radians per the 3D Tiles spec.
        assert -3.5 < west < 3.5
        assert -1.6 < south < 1.6
        assert east > west
        assert north > south
        assert max_h > min_h

    def test_default_geometric_error_scales_with_diagonal(self):
        aabb_small = TileAABB(0, 0, 0, 5, 5, 5)
        aabb_large = TileAABB(0, 0, 0, 500, 500, 500)
        small = build_tileset_json(
            aabb_small,
            content_uri="x.b3dm",
            anchor_lat=0,
            anchor_lon=0,
        )["geometricError"]
        large = build_tileset_json(
            aabb_large,
            content_uri="x.b3dm",
            anchor_lat=0,
            anchor_lon=0,
        )["geometricError"]
        assert large >= small  # roughly


# ── End-to-end orchestrator ─────────────────────────────────────────────


class TestBuildTileArtifacts:
    def test_round_trip(self):
        elems = _elements(3)
        tileset_json, b3dm_bytes, build = build_tile_artifacts(
            elems,
            anchor_lat=52.52,
            anchor_lon=13.40,
        )
        # The tileset_json + b3dm shapes are spec-correct.
        assert tileset_json["asset"]["version"] == "1.1"
        assert b3dm_bytes[:4] == b"b3dm"
        assert build.feature_count == 3
        # The tileset JSON is round-trippable.
        roundtrip = json.loads(json.dumps(tileset_json))
        assert roundtrip == tileset_json


# ── coord_transforms ────────────────────────────────────────────────────


class TestCoordTransforms:
    def test_wgs84_to_web_mercator_at_equator(self):
        x, y = wgs84_to_web_mercator(0.0, 0.0)
        assert abs(x) < 1e-6
        assert abs(y) < 1e-6

    def test_web_mercator_round_trip(self):
        # Berlin
        x, y = wgs84_to_web_mercator(52.5200, 13.4050)
        lat, lon = web_mercator_to_wgs84(x, y)
        assert abs(lat - 52.5200) < 1e-6
        assert abs(lon - 13.4050) < 1e-6

    def test_wgs84_to_ecef_round_trip(self):
        # New York
        lat0, lon0, alt0 = 40.7128, -74.0060, 100.0
        x, y, z = wgs84_to_ecef(lat0, lon0, alt0)
        lat, lon, alt = ecef_to_wgs84(x, y, z)
        assert abs(lat - lat0) < 1e-6
        assert abs(lon - lon0) < 1e-6
        assert abs(alt - alt0) < 1e-2

    def test_enu_round_trip(self):
        # Local point 10 m east, 5 m north, 2 m up at the Berlin anchor.
        ref_lat, ref_lon = 52.52, 13.40
        x0, y0, z0 = enu_to_ecef(10, 5, 2, ref_lat, ref_lon)
        e, n, u = ecef_to_enu(x0, y0, z0, ref_lat, ref_lon)
        assert abs(e - 10.0) < 1e-3
        assert abs(n - 5.0) < 1e-3
        assert abs(u - 2.0) < 1e-3

    def test_transform_identity_short_circuits(self):
        out = transform(4326, 4326, 52.52, 13.40)
        assert out == (52.52, 13.40, 0.0)


# ── Heading rotation (_rotate_element pivot) ─────────────────────────────


class TestRotateElement:
    """``_rotate_element`` must rotate around the supplied pivot, not the
    local origin — otherwise canonical exports whose origin is hundreds
    of metres from the building footprint get translated *away* from
    their geographic anchor on any non-zero heading.
    """

    def test_180_rotation_around_centroid_preserves_footprint(self):
        from app.modules.geo_hub.service import _rotate_element

        # 1 m x 1 m box positioned 1000 m east of the local origin —
        # this is realistic when the surveyor's benchmark is far from
        # the building.
        element = {
            "id": "wall_001",
            "geometry": {"aabb": [1000.0, 500.0, 0.0, 1001.0, 501.0, 3.0]},
        }
        pivot_x = 1000.5
        pivot_y = 500.5
        rotated = _rotate_element(
            element,
            180.0,
            pivot_x=pivot_x,
            pivot_y=pivot_y,
        )
        new_aabb = rotated["geometry"]["aabb"]
        # After a 180 rotation around the centroid, the box must overlap
        # its original footprint within numerical noise.
        assert abs(new_aabb[0] - 1000.0) < 1e-6
        assert abs(new_aabb[1] - 500.0) < 1e-6
        assert abs(new_aabb[3] - 1001.0) < 1e-6
        assert abs(new_aabb[4] - 501.0) < 1e-6
        assert new_aabb[2] == 0.0
        assert new_aabb[5] == 3.0

    def test_rotation_around_origin_translates_far_off_box(self):
        """Regression: rotating around (0,0) flings a remote box across
        the map — exactly the bug the pivot parameter fixes.
        """
        from app.modules.geo_hub.service import _rotate_element

        element = {
            "id": "wall_001",
            "geometry": {"aabb": [1000.0, 500.0, 0.0, 1001.0, 501.0, 3.0]},
        }
        # Old behaviour (pivot_x=pivot_y=0) — should be visibly displaced.
        rotated = _rotate_element(element, 180.0, pivot_x=0.0, pivot_y=0.0)
        new_aabb = rotated["geometry"]["aabb"]
        # Now the box centre is roughly at (-1000.5, -500.5) — far from
        # the original (1000.5, 500.5).
        assert new_aabb[0] < -500
        assert new_aabb[1] < -250

    def test_zero_heading_is_noop(self):
        from app.modules.geo_hub.service import _rotate_element

        element = {
            "id": "wall_001",
            "geometry": {"aabb": [1.0, 2.0, 0.0, 3.0, 4.0, 5.0]},
        }
        rotated = _rotate_element(element, 0.0, pivot_x=2.0, pivot_y=3.0)
        new_aabb = rotated["geometry"]["aabb"]
        for original, after in zip(element["geometry"]["aabb"], new_aabb, strict=False):
            assert abs(original - after) < 1e-9
