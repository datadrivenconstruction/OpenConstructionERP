# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the BIM geometry tiler (``app.modules.bim_hub.tiler``).

Pure geometry - no DB, no storage, no HTTP. We synthesise a monolithic GLB
with trimesh (a grid of named boxes, one per "element"), run it through the
tiler, and assert the properties the streaming viewer relies on:

* small models are left alone (``None`` -> caller serves the monolith);
* a large model is split into several tiles that together cover every mesh
  exactly once;
* the glTF node-name set is preserved byte-for-byte across the split, so the
  viewer's mesh-node -> BIM element matching keeps working on a streamed tile;
* every tile blob is a valid, reloadable GLB;
* content hashes are deterministic, so tiles cache immutably.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")

from app.modules.bim_hub import tiler


def _make_grid_glb(nx: int, ny: int, nz: int) -> tuple[bytes, set[str]]:
    """Build a GLB of ``nx*ny*nz`` unit boxes, each its own named node."""
    scene = trimesh.Scene()
    names: set[str] = set()
    k = 0
    for x in range(nx):
        for y in range(ny):
            for z in range(nz):
                box = trimesh.creation.box(extents=(0.8, 0.8, 0.8))
                box.apply_translation((x * 1.0, y * 1.0, z * 1.0))
                name = f"elem_{k:04d}"
                scene.add_geometry(box, node_name=name, geom_name=name)
                names.add(name)
                k += 1
    return bytes(scene.export(file_type="glb")), names


def _monolith_node_set(glb: bytes) -> set[str]:
    """The node-geometry names trimesh sees in the monolith (frontend's view)."""
    loaded = trimesh.load(io.BytesIO(glb), file_type="glb", process=False)
    return {str(n) for n in loaded.graph.nodes_geometry}


def test_small_model_is_not_tiled() -> None:
    glb, names = _make_grid_glb(8, 8, 2)  # 128 boxes, below MIN_NODES_TO_TILE
    assert len(names) < tiler.MIN_NODES_TO_TILE
    assert tiler.build_tileset(glb) is None


def test_empty_bytes_returns_none() -> None:
    assert tiler.build_tileset(b"") is None


def test_large_model_splits_into_multiple_tiles() -> None:
    glb, _ = _make_grid_glb(16, 16, 2)  # 512 boxes
    result = tiler.build_tileset(glb, max_meshes_per_tile=100)
    assert result is not None
    manifest, tiles = result

    assert manifest["tiler_version"] == tiler.TILER_VERSION
    assert manifest["tile_count"] > 1
    assert manifest["tile_count"] == len(manifest["tiles"])
    # Every referenced tile hash has a blob, and every blob is referenced.
    referenced = {t["hash"] for t in manifest["tiles"]}
    assert referenced == set(tiles.keys())
    assert manifest["total_bytes"] == sum(len(b) for b in tiles.values())


def test_tiles_cover_every_mesh_and_preserve_node_names() -> None:
    glb, _ = _make_grid_glb(16, 16, 2)
    mono_nodes = _monolith_node_set(glb)

    result = tiler.build_tileset(glb, max_meshes_per_tile=100)
    assert result is not None
    manifest, _tiles = result

    tile_nodes: list[str] = []
    for tile in manifest["tiles"]:
        tile_nodes.extend(tile["nodes"])

    # No mesh lost, none duplicated across tiles.
    assert len(tile_nodes) == len(mono_nodes)
    # Exact set equality: the viewer matches meshes to elements by these node
    # names, so a streamed tile must expose the same identities as the monolith.
    assert set(tile_nodes) == mono_nodes
    # node_count is consistent with the nodes list on each tile.
    for tile in manifest["tiles"]:
        assert tile["node_count"] == len(tile["nodes"])


def test_every_tile_is_a_valid_reloadable_glb() -> None:
    glb, _ = _make_grid_glb(16, 16, 2)
    result = tiler.build_tileset(glb, max_meshes_per_tile=100)
    assert result is not None
    _manifest, tiles = result

    for blob in tiles.values():
        # glTF binary magic "glTF".
        assert blob[:4] == b"glTF"
        reloaded = trimesh.load(io.BytesIO(blob), file_type="glb", process=False)
        # Reloads into a scene with at least one geometry.
        assert len(reloaded.geometry) >= 1


def test_content_hashes_are_deterministic() -> None:
    glb, _ = _make_grid_glb(16, 16, 2)
    first = tiler.build_tileset(glb, max_meshes_per_tile=100)
    second = tiler.build_tileset(glb, max_meshes_per_tile=100)
    assert first is not None and second is not None
    hashes_1 = [t["hash"] for t in first[0]["tiles"]]
    hashes_2 = [t["hash"] for t in second[0]["tiles"]]
    assert hashes_1 == hashes_2


def test_leaf_threshold_stays_below_the_tiling_floor() -> None:
    """The smallest model we bother tiling must still split into several tiles.

    The octree hands back a cell whole as soon as it holds at most
    ``max_meshes_per_tile`` meshes. If that threshold reached the tiling floor,
    every model just above the floor would bake to exactly one tile - a tileset
    that delivers the monolithic GLB plus a manifest round trip, with the
    viewer's progressive reveal firing once, at the end. Streaming would be
    silently dead for that whole size band.
    """
    assert tiler.DEFAULT_MAX_MESHES_PER_TILE < tiler.MIN_NODES_TO_TILE


def test_model_just_above_the_floor_splits_into_several_tiles() -> None:
    # 450 boxes: over MIN_NODES_TO_TILE, and the size band that used to
    # collapse into a single tile under the old 1200-mesh leaf threshold.
    glb, names = _make_grid_glb(15, 15, 2)
    assert tiler.MIN_NODES_TO_TILE < len(names) < 1200

    result = tiler.build_tileset(glb)  # defaults, no explicit threshold
    assert result is not None
    manifest, _tiles = result
    assert manifest["tile_count"] > 1, "a tiled model must have something to stream"


def test_tile_count_is_capped_for_a_dense_model() -> None:
    """A finely divisible model must not shatter into an unbounded tile count."""
    glb, names = _make_grid_glb(12, 12, 12)  # 1728 boxes on a dense lattice
    assert len(names) > tiler.MIN_NODES_TO_TILE

    # A threshold of 1 would octree down to one mesh per tile without the cap.
    result = tiler.build_tileset(glb, max_meshes_per_tile=1)
    assert result is not None
    manifest, _tiles = result
    assert manifest["tile_count"] <= tiler.MAX_TILES_PER_MODEL
    # Still genuinely partitioned, not collapsed back to a single tile.
    assert manifest["tile_count"] > 1


def test_capped_repartition_still_covers_every_mesh_exactly_once() -> None:
    glb, _ = _make_grid_glb(12, 12, 12)
    mono_nodes = _monolith_node_set(glb)

    result = tiler.build_tileset(glb, max_meshes_per_tile=1)
    assert result is not None
    manifest, _tiles = result

    tile_nodes: list[str] = []
    for tile in manifest["tiles"]:
        tile_nodes.extend(tile["nodes"])
    # Relaxing the threshold must not lose or duplicate a mesh: element identity
    # travels on these node names.
    assert len(tile_nodes) == len(mono_nodes)
    assert set(tile_nodes) == mono_nodes


def test_manifest_bounds_enclose_the_model() -> None:
    glb, _ = _make_grid_glb(16, 16, 2)
    result = tiler.build_tileset(glb, max_meshes_per_tile=100)
    assert result is not None
    manifest, _tiles = result

    bmin = np.array(manifest["bounds"][:3])
    bmax = np.array(manifest["bounds"][3:])
    # Every tile bbox sits inside the model bounds (small epsilon for rounding).
    for tile in manifest["tiles"]:
        tmin = np.array(tile["bbox"][:3])
        tmax = np.array(tile["bbox"][3:])
        assert np.all(tmin >= bmin - 1e-3)
        assert np.all(tmax <= bmax + 1e-3)
