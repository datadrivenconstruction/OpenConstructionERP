# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM geometry tiler - split a monolithic model GLB into streaming tiles.

Why
---
Today the viewer downloads one GLB for the whole building and parses it
synchronously on the main thread. On a large model that is a 50-150 MB
transfer and a 20-40 s UI freeze, and the browser is told ``no-store`` so it
happens again on every visit. On a job-site tablet over cellular that is the
difference between usable and not.

This module bakes that same model into spatially-partitioned tiles once, so
the viewer can stream geometry progressively (nearest-camera / current-storey
first), parse each tile off the main thread, and cache tiles forever because
they are content-addressed and therefore immutable.

Design
------
Pure geometry, no DB or storage coupling: :func:`build_tileset` takes GLB
bytes and returns a manifest dict plus a ``{content_hash: glb_bytes}`` map.
The service layer owns persistence and the HTTP layer owns delivery. The old
monolithic-GLB path is untouched and stays the fallback for models that were
never tiled, are too small to benefit, or are too large to tile safely.

Tiles preserve the original glTF node names, so the viewer's existing
mesh-node -> BIM element matching (by ``stable_id`` / ``mesh_ref`` / name)
works unchanged on a streamed tile - no frontend rework to keep selection,
isolate, and colour-by-property functioning.

The partition is a plain adaptive octree over per-mesh bounding-box centres:
a cell subdivides into its eight octants until it holds at most
``max_meshes_per_tile`` meshes or the depth cap is reached, with a degenerate
guard so a pile of co-located meshes cannot spin the recursion. If the result
overshoots :data:`MAX_TILES_PER_MODEL` the threshold is relaxed and the model
repartitioned, so tile count stays bounded on very large models. World
transforms are baked into each tile mesh so a tile is self-contained in world
space and the frontend just drops it into the scene at the origin.

Tile granularity is a delivery decision, not a cosmetic one: the threshold has
to stay below :data:`MIN_NODES_TO_TILE` or the smallest models we tile come out
as a single tile and stream no better than the monolith. See the comment on
:data:`DEFAULT_MAX_MESHES_PER_TILE`.
"""

from __future__ import annotations

import hashlib
import io
import logging
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Bumping this invalidates every previously baked tileset (the service keys
# stored manifests by version, so old tiles are simply re-baked on demand).
TILER_VERSION = "1.1"

# Below this mesh count the monolithic GLB already loads fast; tiling would
# only add manifest + per-tile request overhead, so we skip it and let the
# caller serve the monolith.
MIN_NODES_TO_TILE = 400

# Loading a multi-hundred-MB GLB into trimesh peaks at several times its size
# in RAM. Above this we refuse to tile to protect the worker; the monolith
# path (streamed from disk with Range support) still serves the model.
MAX_GLB_BYTES = 400 * 1024 * 1024

# An octree cell stops subdividing once it holds at most this many meshes.
#
# INVARIANT: this MUST stay below MIN_NODES_TO_TILE. The octree returns a cell
# whole as soon as it holds at most this many meshes, so if the threshold sits
# at or above the tiling floor then every model in the band just above that
# floor collapses into a single tile - a "tileset" that costs a manifest round
# trip to deliver exactly the monolithic GLB, with the viewer's progressive
# reveal firing once, at the end. That was the case until 1.1 (the threshold
# was 1200 against a floor of 400), which silently disabled streaming for every
# model between 400 and 1200 meshes.
#
# 300 is measured rather than guessed. On a real 719-mesh model it yields 19
# tiles instead of 1, dropping the bytes before the first tile can appear from
# 2 643 KB to 33 KB, and it costs 6.6% in total payload (2.58 MB monolithic ->
# 2.75 MB of tiles) from per-tile glTF headers and duplicated materials.
DEFAULT_MAX_MESHES_PER_TILE = 300

# Hard recursion cap so a pathological centroid distribution cannot spin.
DEFAULT_MAX_DEPTH = 7

# Upper bound on tiles per model. Each tile is a separate HTTP request, so on a
# high-latency site connection a very large model partitioned too finely trades
# a bandwidth win for a round-trip loss. When the partition overshoots we relax
# the per-tile mesh threshold and repartition; the octree runs on centroids
# only and is cheap, and the expensive GLB export happens once, afterwards.
MAX_TILES_PER_MODEL = 256

# One bake at a time per process: a bake peaks at several times the GLB size in
# RAM, so concurrent bakes from the thread pool would multiply that peak on a
# small server (principle 1).
_BAKE_LOCK = threading.Lock()


def build_tileset(
    glb_bytes: bytes,
    *,
    max_meshes_per_tile: int = DEFAULT_MAX_MESHES_PER_TILE,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[dict[str, Any], dict[str, bytes]] | None:
    """Partition a model GLB into streaming tiles.

    Args:
        glb_bytes: The monolithic model GLB (as produced by the DDC
            ``DAE -> GLB`` conversion). Node names are expected to carry the
            element identity; they are preserved into the tiles.
        max_meshes_per_tile: Octree leaf threshold - a cell stops
            subdividing once it holds at most this many meshes.
        max_depth: Hard octree recursion cap.

    Returns:
        ``(manifest, tiles)`` where *manifest* is a JSON-serialisable dict and
        *tiles* maps ``content_hash -> glb_bytes``. Returns ``None`` when the
        model is too small to benefit from tiling or too large to tile safely -
        the caller should serve the monolithic GLB instead.
    """
    with _BAKE_LOCK:
        return _build_tileset(glb_bytes, max_meshes_per_tile, max_depth)


def _build_tileset(
    glb_bytes: bytes, max_meshes_per_tile: int, max_depth: int
) -> tuple[dict[str, Any], dict[str, bytes]] | None:
    if not glb_bytes:
        return None
    if len(glb_bytes) > MAX_GLB_BYTES:
        logger.info(
            "tiler: GLB %d bytes exceeds cap %d - skipping tiling",
            len(glb_bytes),
            MAX_GLB_BYTES,
        )
        return None

    import trimesh  # lazy: keep the heavy import off module load

    try:
        loaded = trimesh.load(io.BytesIO(glb_bytes), file_type="glb", process=False)
    except Exception as exc:  # noqa: BLE001 - any parse failure -> fall back to monolith
        logger.warning("tiler: trimesh failed to load GLB (%s) - skipping tiling", exc)
        return None

    meshes = _flatten_scene(loaded)
    del loaded  # baked copies carry the geometry; free the parsed scene before exporting
    if len(meshes) < MIN_NODES_TO_TILE:
        logger.info(
            "tiler: %d meshes below tiling threshold %d - skipping",
            len(meshes),
            MIN_NODES_TO_TILE,
        )
        return None

    # Per-mesh bbox bounds -> centres (used for the octree) and the model root.
    lows = np.array([m.bounds[0] for _, m in meshes], dtype=np.float64)
    highs = np.array([m.bounds[1] for _, m in meshes], dtype=np.float64)
    centres = (lows + highs) * 0.5
    root_min = lows.min(axis=0)
    root_max = highs.max(axis=0)

    leaves = _partition(len(meshes), centres, root_min, root_max, max_meshes_per_tile, max_depth)

    tiles_bytes: dict[str, bytes] = {}
    tile_entries: list[dict[str, Any]] = []
    for tile_index, leaf in enumerate(leaves):
        if not leaf:
            continue
        data = _export_tile(trimesh, meshes, leaf)
        if data is None:
            continue
        content_hash = hashlib.sha256(data).hexdigest()[:32]
        # Two leaves that export byte-identical geometry share one blob; the
        # manifest still lists both tiles pointing at the same hash.
        tiles_bytes[content_hash] = data

        tmin = lows[leaf].min(axis=0)
        tmax = highs[leaf].max(axis=0)
        centre = (tmin + tmax) * 0.5
        radius = float(np.linalg.norm(tmax - centre))
        tile_entries.append(
            {
                "id": f"t{tile_index}",
                "hash": content_hash,
                "bbox": [*_round3(tmin), *_round3(tmax)],
                "center": _round3(centre),
                "radius": round(radius, 3),
                "node_count": len(leaf),
                "byte_size": len(data),
                # Node names let the viewer stream just the tile(s) that hold a
                # deep-linked / isolated element instead of the whole model.
                "nodes": [meshes[i][0] for i in leaf],
            }
        )

    if not tile_entries:
        return None

    manifest: dict[str, Any] = {
        "tiler_version": TILER_VERSION,
        "generator": "openconstructionerp-bim-tiler",
        # trimesh exports standard glTF (Y-up); identical orientation to the
        # monolithic GLB, so the viewer's existing up-axis handling applies.
        "up_axis": "Y",
        "bounds": [*_round3(root_min), *_round3(root_max)],
        "mesh_count": len(meshes),
        "tile_count": len(tile_entries),
        "total_bytes": sum(t["byte_size"] for t in tile_entries),
        "tiles": tile_entries,
    }
    logger.info(
        "tiler: baked %d meshes into %d tiles (%.1f MB total)",
        len(meshes),
        len(tile_entries),
        manifest["total_bytes"] / (1024 * 1024),
    )
    return manifest, tiles_bytes


# ──────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────


def _flatten_scene(loaded: Any) -> list[tuple[str, Any]]:
    """Return ``[(node_name, world_space_mesh), ...]`` for every real mesh.

    Instances (several graph nodes referencing one geometry with different
    transforms) become distinct baked meshes, each keyed by its node name so
    element identity survives. Empty/degenerate meshes are dropped.
    """
    import trimesh

    out: list[tuple[str, Any]] = []

    if isinstance(loaded, trimesh.Trimesh):
        if len(loaded.faces) and len(loaded.vertices):
            out.append(("mesh_0", loaded))
        return out

    if not isinstance(loaded, trimesh.Scene):
        return out

    graph = loaded.graph
    try:
        node_names = list(graph.nodes_geometry)
    except Exception:  # noqa: BLE001 - malformed graph -> nothing to tile
        return out

    for node_name in node_names:
        try:
            transform, geom_name = graph[node_name]
        except Exception:  # noqa: BLE001 - skip a node the graph cannot resolve
            continue
        geom = loaded.geometry.get(geom_name)
        if geom is None or not hasattr(geom, "faces"):
            continue
        if len(geom.faces) == 0 or len(geom.vertices) == 0:
            continue
        mesh = geom.copy()
        if transform is not None:
            try:
                mesh.apply_transform(transform)
            except Exception:  # noqa: BLE001 - keep untransformed rather than drop
                logger.debug("tiler: transform failed for node %s", node_name)
        out.append((str(node_name), mesh))
    return out


def _partition(
    mesh_count: int,
    centres: np.ndarray,
    root_min: np.ndarray,
    root_max: np.ndarray,
    max_per_tile: int,
    max_depth: int,
) -> list[list[int]]:
    """Octree the meshes, relaxing the leaf threshold if it overshoots the cap.

    Splitting finely is what makes a model appear progressively, but every tile
    costs an HTTP round trip, so a huge model must not shatter into thousands of
    them. We partition, and while the result exceeds
    :data:`MAX_TILES_PER_MODEL` we double the per-tile mesh threshold and try
    again. Doubling terminates: once the threshold reaches ``mesh_count`` the
    octree returns a single leaf.

    Args:
        mesh_count: Total number of meshes being partitioned.
        centres: ``(mesh_count, 3)`` array of per-mesh bounding-box centres.
        root_min: Lower corner of the model's bounding box.
        root_max: Upper corner of the model's bounding box.
        max_per_tile: Starting octree leaf threshold.
        max_depth: Hard octree recursion cap.

    Returns:
        A list of leaf buckets, each a list of mesh indices.
    """
    indices = list(range(mesh_count))
    cap = max(1, max_per_tile)
    while True:
        leaves = _octree(indices, centres, root_min, root_max, cap, 0, max_depth)
        if len(leaves) <= MAX_TILES_PER_MODEL or cap >= mesh_count:
            return leaves
        cap *= 2
        logger.info(
            "tiler: %d tiles exceeds cap %d - repartitioning at %d meshes per tile",
            len(leaves),
            MAX_TILES_PER_MODEL,
            cap,
        )


def _octree(
    indices: list[int],
    centres: np.ndarray,
    box_min: np.ndarray,
    box_max: np.ndarray,
    max_per_tile: int,
    depth: int,
    max_depth: int,
) -> list[list[int]]:
    """Adaptive octree over mesh-centre points; returns a list of leaf buckets.

    A cell subdivides into its eight octants until it holds at most
    ``max_per_tile`` meshes or ``max_depth`` is reached. If every mesh in a
    cell falls into a single octant (co-located geometry), the split is
    abandoned to avoid unbounded recursion and the cell becomes a leaf.
    """
    if len(indices) <= max_per_tile or depth >= max_depth:
        return [indices]

    mid = (box_min + box_max) * 0.5
    buckets: dict[tuple[bool, bool, bool], list[int]] = {}
    for i in indices:
        c = centres[i]
        key = (bool(c[0] >= mid[0]), bool(c[1] >= mid[1]), bool(c[2] >= mid[2]))
        buckets.setdefault(key, []).append(i)

    if len(buckets) <= 1:
        # Degenerate: everything landed in one octant. Stop here.
        return [indices]

    leaves: list[list[int]] = []
    # Sorted keys -> deterministic tile order -> stable content hashes.
    for key in sorted(buckets):
        child_min = np.array([mid[k] if key[k] else box_min[k] for k in range(3)])
        child_max = np.array([box_max[k] if key[k] else mid[k] for k in range(3)])
        leaves.extend(
            _octree(
                buckets[key],
                centres,
                child_min,
                child_max,
                max_per_tile,
                depth + 1,
                max_depth,
            )
        )
    return leaves


def _export_tile(trimesh_mod: Any, meshes: list[tuple[str, Any]], leaf: list[int]) -> bytes | None:
    """Build a sub-scene from ``leaf`` meshes and export it as GLB bytes."""
    scene = trimesh_mod.Scene()
    for i in leaf:
        name, mesh = meshes[i]
        # node_name carries element identity; geom_name kept in step so the
        # exported glTF node names match what the viewer matches against.
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    try:
        data = scene.export(file_type="glb")
    except Exception as exc:  # noqa: BLE001 - one bad tile must not kill the bake
        logger.warning("tiler: failed to export a tile (%s) - dropping it", exc)
        return None
    return bytes(data)


def _round3(vec: np.ndarray) -> list[float]:
    """Round a 3-vector to mm precision for a compact, stable manifest."""
    return [round(float(v), 3) for v in vec]
