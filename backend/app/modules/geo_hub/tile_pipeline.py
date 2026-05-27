# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Canonical-JSON -> glTF -> 3D Tiles 1.1 pipeline.

Pure-Python tile builder. No C++ deps, no Node side-service. The
output complies with the OGC 3D Tiles 1.1 Community Standard (Jan 2025)
and the glTF 2.0 Khronos extensions ``EXT_structural_metadata`` /
``EXT_mesh_features`` so a Cesium 1.x viewer can:

* fetch the root ``tileset.json``
* discover the bounding volume + geometric error
* request the ``content.uri`` (a ``.b3dm`` file containing a glTF blob)
* read per-feature metadata (DIN 276 code, area_m2, classification,
  source_element_id) without a second round-trip

Stages (all unit-testable in isolation):

1. ``load_canonical_elements(elements_or_loader)`` — accept either a
   list of canonical-element dicts, or a coroutine that produces them.
2. ``compute_aabb(elements)`` — axis-aligned bounding box over the
   element geometries.
3. ``partition_by_aabb(elements, target_tile_count)`` — naive
   octree-style split (v1 keeps it to a single tile because the
   spec's hierarchical traversal is overkill for the early customers;
   ``partition_by_aabb`` is exposed and tested so v1.1 can flip on
   multi-tile LoD without touching the public API).
4. ``build_gltf_for_tile(elements, tile_aabb)`` — vertex + index
   buffers, mesh primitives, ``EXT_structural_metadata`` property
   table with one row per element. Returns a glTF dict + a packed
   binary buffer.
5. ``write_b3dm(gltf_bytes, feature_table, batch_table)`` — Cesium's
   binary 3D tile wrapper around a glTF blob.
6. ``build_tileset_json(tile_aabb, content_uri, geometric_error,
   anchor_lat, anchor_lon)`` — root ``tileset.json`` with a region or
   sphere bounding volume positioned at the project anchor.
7. ``upload_to_minio(...)`` — writes ``tileset.json`` + one ``.b3dm``
   into the existing :class:`StorageBackend` under
   ``tilesets/{tileset_id}/``.

Reduce complexity for v1: one tile per source. LoD selection lives in
the spec but is not required for correctness — the viewer treats the
root tile as the only tile and renders it. v1.1 will partition.

All public functions accept and return only Python primitives so the
service layer can drive each stage independently, and so the tests can
verify each stage's output against the spec without spinning up a full
job lifecycle.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Iterable, Sequence

from app.modules.geo_hub.coord_transforms import (
    enu_to_ecef,
)

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────────

# glTF 2.0 component-type enums (matches the spec's WebGL enum table).
_COMPONENT_TYPE_FLOAT = 5126
_COMPONENT_TYPE_UNSIGNED_INT = 5125
_COMPONENT_TYPE_UNSIGNED_SHORT = 5123

# glTF 2.0 buffer-view targets.
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963

# Default geometric error in metres — controls when Cesium swaps in a
# higher-detail child tile. Picked to match Cesium's "wow that's a
# building"-scale threshold without forcing the user to set it.
_DEFAULT_GEOMETRIC_ERROR = 200.0


# ── Datatypes ───────────────────────────────────────────────────────────


@dataclass
class TileAABB:
    """Axis-aligned bounding box in local east-north-up metres."""

    min_x: float = 0.0
    min_y: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    max_z: float = 0.0

    def is_empty(self) -> bool:
        return self.min_x >= self.max_x or self.min_y >= self.max_y or self.min_z >= self.max_z

    def union(self, other: TileAABB) -> TileAABB:
        return TileAABB(
            min(self.min_x, other.min_x),
            min(self.min_y, other.min_y),
            min(self.min_z, other.min_z),
            max(self.max_x, other.max_x),
            max(self.max_y, other.max_y),
            max(self.max_z, other.max_z),
        )

    def expand(self, x: float, y: float, z: float) -> None:
        self.min_x = min(self.min_x, x)
        self.min_y = min(self.min_y, y)
        self.min_z = min(self.min_z, z)
        self.max_x = max(self.max_x, x)
        self.max_y = max(self.max_y, y)
        self.max_z = max(self.max_z, z)

    @property
    def centroid(self) -> tuple[float, float, float]:
        return (
            (self.min_x + self.max_x) / 2.0,
            (self.min_y + self.max_y) / 2.0,
            (self.min_z + self.max_z) / 2.0,
        )

    @property
    def half_size(self) -> tuple[float, float, float]:
        return (
            (self.max_x - self.min_x) / 2.0,
            (self.max_y - self.min_y) / 2.0,
            (self.max_z - self.min_z) / 2.0,
        )

    @property
    def diagonal_m(self) -> float:
        dx = self.max_x - self.min_x
        dy = self.max_y - self.min_y
        dz = self.max_z - self.min_z
        return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass
class GLTFBuild:
    """Output of :func:`build_gltf_for_tile`."""

    gltf: dict[str, Any]
    binary_blob: bytes
    feature_count: int
    triangle_count: int
    aabb: TileAABB
    metadata_table: dict[str, list[Any]] = field(default_factory=dict)


# ── Stage 1: canonical loading ──────────────────────────────────────────


async def load_canonical_elements(
    source: Iterable[dict[str, Any]] | Callable[[], Awaitable[list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Resolve a canonical-elements source into a concrete list.

    Accepts either:

    * an iterable of element dicts (tests, in-process pipelines), or
    * an async ``() -> list[dict]`` callable (service-layer / repo).
    """
    if callable(source):
        result = await source()
        return list(result) if result else []
    return list(source)


# ── Stage 2 + 3: spatial partitioning ───────────────────────────────────


def _element_geometry_aabb(element: dict[str, Any]) -> TileAABB | None:
    """Pull an AABB from a canonical element's ``geometry`` block.

    Canonical format gives us at least one of:

    * ``geometry.aabb`` — six-number list [min_x, min_y, min_z, max_x,
      max_y, max_z] (preferred when the converter wrote it).
    * ``geometry.length_m`` / ``height_m`` / ``thickness_m`` for
      extrusions.
    * ``geometry.area_m2`` / ``geometry.volume_m3`` as a crude fallback
      (we infer a unit cube of equivalent area / volume so the element
      contributes to the tile bounding box even when the converter
      didn't emit per-element geometry — better than dropping it).

    Returns ``None`` only when the element has no usable spatial hint.
    """
    geom = element.get("geometry") or {}
    if not isinstance(geom, dict):
        return None
    aabb = geom.get("aabb")
    if isinstance(aabb, list) and len(aabb) == 6:
        try:
            return TileAABB(*[float(v) for v in aabb])
        except (TypeError, ValueError):
            pass

    # Try a position + extrusion footprint.
    position = geom.get("position") or {}
    if isinstance(position, dict):
        x = float(position.get("x", 0.0) or 0.0)
        y = float(position.get("y", 0.0) or 0.0)
        z = float(position.get("z", 0.0) or 0.0)
    else:
        x = y = z = 0.0
    length = float(geom.get("length_m", 0.0) or 0.0)
    width = float(geom.get("width_m", 0.0) or geom.get("thickness_m", 0.0) or 0.0)
    height = float(geom.get("height_m", 0.0) or 0.0)
    if length <= 0.0 and width <= 0.0 and height <= 0.0:
        # Last resort: area / volume.
        area = float(geom.get("area_m2", 0.0) or 0.0)
        volume = float(geom.get("volume_m3", 0.0) or 0.0)
        if volume > 0:
            side = volume ** (1.0 / 3.0)
            length = width = height = side
        elif area > 0:
            side = math.sqrt(area)
            length = width = side
            height = 1.0
        else:
            return None
    return TileAABB(
        x,
        y,
        z,
        x + max(length, 0.1),
        y + max(width, 0.1),
        z + max(height, 0.1),
    )


def compute_aabb(elements: Sequence[dict[str, Any]]) -> TileAABB:
    """Union the per-element AABBs into a single tile bounding box."""
    out = TileAABB()
    seeded = False
    for elem in elements:
        sub = _element_geometry_aabb(elem)
        if sub is None or sub.is_empty():
            continue
        if not seeded:
            out = sub
            seeded = True
        else:
            out = out.union(sub)
    return out


def partition_by_aabb(
    elements: Sequence[dict[str, Any]],
    target_tile_count: int = 1,
) -> list[list[dict[str, Any]]]:
    """Spatially partition the elements into roughly ``target_tile_count`` groups.

    v1 ships a degenerate single-tile partition (returns the elements
    as a single group) when ``target_tile_count == 1``. For >1 we do
    a simple median-split along the longest axis — recursive doubling
    until we hit the target group count. The recursion is bounded by
    ``ceil(log2(target_tile_count))`` and works in O(n log n).
    """
    if not elements:
        return []
    if target_tile_count <= 1:
        return [list(elements)]

    def _split(group: list[dict[str, Any]], depth: int) -> list[list[dict[str, Any]]]:
        if depth == 0 or len(group) <= 1:
            return [group]
        aabb = compute_aabb(group)
        if aabb.is_empty():
            return [group]
        dx = aabb.max_x - aabb.min_x
        dy = aabb.max_y - aabb.min_y
        dz = aabb.max_z - aabb.min_z
        if dx >= dy and dx >= dz:
            axis = "x"
            mid = (aabb.min_x + aabb.max_x) / 2.0
        elif dy >= dz:
            axis = "y"
            mid = (aabb.min_y + aabb.max_y) / 2.0
        else:
            axis = "z"
            mid = (aabb.min_z + aabb.max_z) / 2.0
        left: list[dict[str, Any]] = []
        right: list[dict[str, Any]] = []
        for elem in group:
            sub = _element_geometry_aabb(elem)
            if sub is None:
                # Drop AABB-less elements into the lighter side to
                # keep groups balanced.
                (left if len(left) <= len(right) else right).append(elem)
                continue
            cx = (sub.min_x + sub.max_x) / 2.0
            cy = (sub.min_y + sub.max_y) / 2.0
            cz = (sub.min_z + sub.max_z) / 2.0
            cval = cx if axis == "x" else (cy if axis == "y" else cz)
            (left if cval < mid else right).append(elem)
        if not left or not right:
            # Split made no progress — stop here.
            return [group]
        return _split(left, depth - 1) + _split(right, depth - 1)

    max_depth = math.ceil(math.log2(target_tile_count))
    return _split(list(elements), max_depth)


# ── Stage 4: glTF construction ──────────────────────────────────────────


def _emit_box_mesh(
    aabb: TileAABB,
    feature_id: int,
    buffer: bytearray,
    vertex_offset: int,
    index_offset: int,
) -> tuple[int, int]:
    """Append an oriented box mesh for one feature into ``buffer``.

    Returns the (new_vertex_offset, new_index_offset) so the caller can
    keep stacking primitives. Each vertex carries a ``_FEATURE_ID_0``
    attribute that ties back to the metadata property table — this is
    what enables ``EXT_mesh_features`` lookups in Cesium.
    """
    # 8 vertices of the AABB (xyz + featureId).
    corners = [
        (aabb.min_x, aabb.min_y, aabb.min_z),
        (aabb.max_x, aabb.min_y, aabb.min_z),
        (aabb.max_x, aabb.max_y, aabb.min_z),
        (aabb.min_x, aabb.max_y, aabb.min_z),
        (aabb.min_x, aabb.min_y, aabb.max_z),
        (aabb.max_x, aabb.min_y, aabb.max_z),
        (aabb.max_x, aabb.max_y, aabb.max_z),
        (aabb.min_x, aabb.max_y, aabb.max_z),
    ]
    base_index = vertex_offset
    for x, y, z in corners:
        buffer.extend(struct.pack("<fff", x, y, z))
    # FeatureId attribute (one unsigned short per vertex).
    feature_buffer_start = len(buffer)
    for _ in corners:
        buffer.extend(struct.pack("<H", feature_id))
    # Pad to 4-byte alignment because the index buffer that follows
    # starts at len(buffer).
    while (len(buffer) - feature_buffer_start) % 4 != 0:
        buffer.append(0)

    # 12 triangles = 36 indices.
    triangles = [
        # bottom
        (0, 1, 2),
        (0, 2, 3),
        # top
        (4, 6, 5),
        (4, 7, 6),
        # sides
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    ]
    for tri in triangles:
        for v in tri:
            buffer.extend(struct.pack("<I", base_index + v))

    new_vertex_offset = vertex_offset + len(corners)
    new_index_offset = index_offset + len(triangles) * 3
    return new_vertex_offset, new_index_offset


def build_gltf_for_tile(
    elements: Sequence[dict[str, Any]],
    tile_aabb: TileAABB | None = None,
    *,
    add_structural_metadata: bool = True,
) -> GLTFBuild:
    """Build a single-tile glTF 2.0 dict + binary blob.

    Each element gets a degenerate box mesh sized to its canonical
    AABB. The intent here is not to ship visually-perfect geometry —
    that's the converter's job — but to produce a *valid* glTF that:

    * places the right number of features at roughly the right place
    * carries the structural metadata so a tile click lights up the
      same DIN 276 / area / classification info that the BOQ shows
    * fits the OGC 3D Tiles 1.1 + glTF 2.0 specs strictly enough for
      Cesium to render without warnings

    The resulting blob is what gets wrapped in a ``.b3dm`` header by
    :func:`write_b3dm`.
    """
    if tile_aabb is None:
        tile_aabb = compute_aabb(elements)

    binary = bytearray()
    vertex_offset = 0
    index_offset = 0

    primitives: list[dict[str, Any]] = []
    metadata_rows: dict[str, list[Any]] = {
        "element_id": [],
        "category": [],
        "din276": [],
        "nrm": [],
        "masterformat": [],
        "area_m2": [],
        "volume_m3": [],
        "validation_status": [],
    }
    triangle_count = 0
    feature_index = 0

    # Buffer-view bookkeeping. We append per-feature primitives so
    # the buffer-view offsets/lengths line up with the binary blob.
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    for element in elements:
        sub = _element_geometry_aabb(element)
        if sub is None or sub.is_empty():
            continue
        vert_start_bytes = len(binary)
        new_vo, new_io = _emit_box_mesh(
            sub,
            feature_index,
            binary,
            vertex_offset,
            index_offset,
        )
        # Indices follow vertices + featureIds + padding. Carve out
        # the offsets after _emit_box_mesh has written them.
        # 8 vertices * 12 bytes (3 floats) = 96 bytes.
        vert_bytes = 96
        feature_bytes = 16  # 8 * uint16
        feature_padding = (4 - (feature_bytes % 4)) % 4
        index_bytes = 36 * 4  # 36 uint32
        # buffer-view: positions
        position_bv_index = len(buffer_views)
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": vert_start_bytes,
                "byteLength": vert_bytes,
                "target": _ARRAY_BUFFER,
            }
        )
        # buffer-view: feature ids
        feature_bv_index = len(buffer_views)
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": vert_start_bytes + vert_bytes,
                "byteLength": feature_bytes,
                "target": _ARRAY_BUFFER,
            }
        )
        # buffer-view: indices
        index_bv_index = len(buffer_views)
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": vert_start_bytes + vert_bytes + feature_bytes + feature_padding,
                "byteLength": index_bytes,
                "target": _ELEMENT_ARRAY_BUFFER,
            }
        )

        position_accessor_index = len(accessors)
        accessors.append(
            {
                "bufferView": position_bv_index,
                "byteOffset": 0,
                "componentType": _COMPONENT_TYPE_FLOAT,
                "count": 8,
                "type": "VEC3",
                "min": [sub.min_x, sub.min_y, sub.min_z],
                "max": [sub.max_x, sub.max_y, sub.max_z],
            }
        )
        feature_accessor_index = len(accessors)
        accessors.append(
            {
                "bufferView": feature_bv_index,
                "byteOffset": 0,
                "componentType": _COMPONENT_TYPE_UNSIGNED_SHORT,
                "count": 8,
                "type": "SCALAR",
            }
        )
        index_accessor_index = len(accessors)
        accessors.append(
            {
                "bufferView": index_bv_index,
                "byteOffset": 0,
                "componentType": _COMPONENT_TYPE_UNSIGNED_INT,
                "count": 36,
                "type": "SCALAR",
            }
        )

        primitive: dict[str, Any] = {
            "attributes": {
                "POSITION": position_accessor_index,
                "_FEATURE_ID_0": feature_accessor_index,
            },
            "indices": index_accessor_index,
            "mode": 4,  # TRIANGLES
        }
        if add_structural_metadata:
            primitive["extensions"] = {
                "EXT_mesh_features": {
                    "featureIds": [
                        {
                            "featureCount": 1,
                            "attribute": 0,
                            "propertyTable": 0,
                        },
                    ],
                },
            }
        primitives.append(primitive)

        # ── Metadata row ──
        classification = element.get("classification") or {}
        if not isinstance(classification, dict):
            classification = {}
        geometry = element.get("geometry") or {}
        quantities = element.get("quantities") or {}
        if not isinstance(quantities, dict):
            quantities = {}

        metadata_rows["element_id"].append(str(element.get("id", "")))
        metadata_rows["category"].append(str(element.get("category", "")))
        metadata_rows["din276"].append(str(classification.get("din276", "")))
        metadata_rows["nrm"].append(str(classification.get("nrm", "")))
        metadata_rows["masterformat"].append(
            str(classification.get("masterformat", "")),
        )
        metadata_rows["area_m2"].append(
            float(geometry.get("area_m2") or quantities.get("area_m2", 0.0) or 0.0),
        )
        metadata_rows["volume_m3"].append(
            float(
                geometry.get("volume_m3") or quantities.get("volume_m3", 0.0) or 0.0,
            ),
        )
        metadata_rows["validation_status"].append(
            str(element.get("validation_status", "")),
        )

        triangle_count += 12
        vertex_offset = new_vo
        index_offset = new_io
        feature_index += 1

    # Pad the binary blob to a multiple of 4 bytes (glTF spec).
    while len(binary) % 4 != 0:
        binary.append(0)

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "openconstructionerp/geo_hub"},
        "extensionsUsed": [],
        "extensionsRequired": [],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [{"primitives": primitives}] if primitives else [],
        "nodes": [{"mesh": 0}] if primitives else [],
        "scenes": [{"nodes": [0]}] if primitives else [{"nodes": []}],
        "scene": 0,
    }

    if add_structural_metadata and feature_index > 0:
        gltf["extensionsUsed"].extend(
            ["EXT_mesh_features", "EXT_structural_metadata"],
        )
        gltf["extensions"] = {
            "EXT_structural_metadata": {
                "schema": {
                    "id": "openconstructionerp.geo_hub.v1",
                    "classes": {
                        "Element": {
                            "name": "Element",
                            "description": (
                                "Canonical BIM / CAD element exported to 3D Tiles by openconstructionerp.geo_hub"
                            ),
                            "properties": {
                                "element_id": {"type": "STRING"},
                                "category": {"type": "STRING"},
                                "din276": {"type": "STRING"},
                                "nrm": {"type": "STRING"},
                                "masterformat": {"type": "STRING"},
                                "area_m2": {
                                    "type": "SCALAR",
                                    "componentType": "FLOAT32",
                                },
                                "volume_m3": {
                                    "type": "SCALAR",
                                    "componentType": "FLOAT32",
                                },
                                "validation_status": {"type": "STRING"},
                            },
                        },
                    },
                },
                "propertyTables": [
                    {
                        "name": "Elements",
                        "class": "Element",
                        "count": feature_index,
                        "properties": {
                            # Property values are inlined into the
                            # tileset.json metadata in v1 (a binary
                            # property table would shave bytes but
                            # adds spec edge-cases — the JSON path is
                            # the spec-compliant fallback and Cesium
                            # reads it natively).
                            k: {"values": v[:feature_index]}
                            for k, v in metadata_rows.items()
                        },
                    },
                ],
            },
        }

    return GLTFBuild(
        gltf=gltf,
        binary_blob=bytes(binary),
        feature_count=feature_index,
        triangle_count=triangle_count,
        aabb=tile_aabb,
        metadata_table=metadata_rows,
    )


# ── Stage 5: b3dm wrapper ───────────────────────────────────────────────


def _pack_glb(gltf: dict[str, Any], binary: bytes) -> bytes:
    """Pack a glTF JSON + binary blob into the GLB binary container."""
    json_text = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    # Pad JSON chunk to 4-byte boundary with ASCII space.
    while len(json_text) % 4 != 0:
        json_text += b" "
    # Pad binary chunk to 4-byte boundary with zeros.
    bin_padded = binary
    while len(bin_padded) % 4 != 0:
        bin_padded += b"\x00"
    total = 12 + 8 + len(json_text) + 8 + len(bin_padded)
    header = struct.pack("<4sII", b"glTF", 2, total)
    json_chunk = (
        struct.pack("<II", len(json_text), 0x4E4F534A) + json_text  # "JSON"
    )
    bin_chunk = (
        struct.pack("<II", len(bin_padded), 0x004E4942) + bin_padded  # "BIN\0"
    )
    return header + json_chunk + bin_chunk


def write_b3dm(
    gltf: dict[str, Any],
    binary: bytes,
    *,
    feature_table: dict[str, Any] | None = None,
    batch_table: dict[str, Any] | None = None,
) -> bytes:
    """Wrap a glTF blob in the 3D Tiles ``.b3dm`` binary format.

    Spec: https://github.com/CesiumGS/3d-tiles/tree/main/specification/TileFormats/Batched3DModel

    Layout::

        [0..4)    magic         "b3dm"
        [4..8)    version       1 (uint32)
        [8..12)   byteLength    total file length (uint32)
        [12..16)  featureTableJSONByteLength (uint32)
        [16..20)  featureTableBinaryByteLength (uint32)
        [20..24)  batchTableJSONByteLength (uint32)
        [24..28)  batchTableBinaryByteLength (uint32)
        [28..)    featureTableJSON  (padded to 8-byte alignment)
                  featureTableBinary (padded to 8-byte alignment)
                  batchTableJSON     (padded to 8-byte alignment)
                  batchTableBinary   (padded to 8-byte alignment)
                  glb payload
    """
    glb = _pack_glb(gltf, binary)

    feature_table_json_obj = feature_table or {"BATCH_LENGTH": 0}
    feature_table_json = json.dumps(
        feature_table_json_obj,
        separators=(",", ":"),
    ).encode("utf-8")
    while (28 + len(feature_table_json)) % 8 != 0:
        feature_table_json += b" "

    feature_table_binary = b""  # No binary feature table in v1.
    batch_table_json = json.dumps(batch_table or {}, separators=(",", ":")).encode("utf-8") if batch_table else b""
    while batch_table_json and (
        (28 + len(feature_table_json) + len(feature_table_binary) + len(batch_table_json)) % 8 != 0
    ):
        batch_table_json += b" "
    batch_table_binary = b""

    payload_offset = (
        28 + len(feature_table_json) + len(feature_table_binary) + len(batch_table_json) + len(batch_table_binary)
    )
    # glb itself must start at an 8-byte boundary inside the file.
    while payload_offset % 8 != 0:
        # Tack any remaining padding onto the batch-table JSON which
        # is the last variable-length section before the glb.
        if batch_table_json:
            batch_table_json += b" "
        else:
            feature_table_json += b" "
        payload_offset = (
            28 + len(feature_table_json) + len(feature_table_binary) + len(batch_table_json) + len(batch_table_binary)
        )

    total = payload_offset + len(glb)
    header = struct.pack(
        "<4sIIIIII",
        b"b3dm",
        1,
        total,
        len(feature_table_json),
        len(feature_table_binary),
        len(batch_table_json),
        len(batch_table_binary),
    )
    return header + feature_table_json + feature_table_binary + batch_table_json + batch_table_binary + glb


# ── Stage 6: tileset.json ───────────────────────────────────────────────


def _bounding_region_for_aabb(
    aabb: TileAABB,
    anchor_lat: float,
    anchor_lon: float,
    anchor_alt: float,
) -> list[float]:
    """Project the AABB corners into WGS84 and return a Cesium region.

    Cesium 3D Tiles region: ``[west, south, east, north, min_h, max_h]``
    where lon / lat are in **radians** (the spec). We do the heavy
    work in ENU -> ECEF -> WGS84 lat/lon (radians) without depending
    on pyproj.
    """
    west = math.inf
    south = math.inf
    east = -math.inf
    north = -math.inf
    min_h = math.inf
    max_h = -math.inf
    corners = [
        (aabb.min_x, aabb.min_y, aabb.min_z),
        (aabb.max_x, aabb.min_y, aabb.min_z),
        (aabb.max_x, aabb.max_y, aabb.min_z),
        (aabb.min_x, aabb.max_y, aabb.min_z),
        (aabb.min_x, aabb.min_y, aabb.max_z),
        (aabb.max_x, aabb.min_y, aabb.max_z),
        (aabb.max_x, aabb.max_y, aabb.max_z),
        (aabb.min_x, aabb.max_y, aabb.max_z),
    ]
    for e, n, u in corners:
        x, y, z = enu_to_ecef(e, n, u, anchor_lat, anchor_lon, anchor_alt)
        # ECEF -> WGS84 (lat/lon in radians).
        lon = math.atan2(y, x)
        p = math.sqrt(x * x + y * y)
        lat = math.atan2(z, p * (1 - 0.006_694_379_990_14))
        # Refine latitude via a 3-step iteration.
        for _ in range(3):
            n_phi = 6_378_137.0 / math.sqrt(
                1 - 0.006_694_379_990_14 * math.sin(lat) ** 2,
            )
            lat = math.atan2(
                z + 0.006_694_379_990_14 * n_phi * math.sin(lat),
                p,
            )
        alt = p / math.cos(lat) - 6_378_137.0
        west = min(west, lon)
        south = min(south, lat)
        east = max(east, lon)
        north = max(north, lat)
        min_h = min(min_h, alt)
        max_h = max(max_h, alt)
    return [west, south, east, north, min_h, max_h]


def build_tileset_json(
    tile_aabb: TileAABB,
    *,
    content_uri: str,
    anchor_lat: float,
    anchor_lon: float,
    anchor_alt: float = 0.0,
    geometric_error: float | None = None,
) -> dict[str, Any]:
    """Assemble a spec-compliant root ``tileset.json``.

    Uses a ``region`` bounding volume because it sits on the earth's
    surface and Cesium handles it transparently without needing an
    external transform matrix per tile.
    """
    if geometric_error is None:
        geometric_error = max(
            _DEFAULT_GEOMETRIC_ERROR,
            tile_aabb.diagonal_m / 4.0,
        )
    region = _bounding_region_for_aabb(
        tile_aabb,
        anchor_lat,
        anchor_lon,
        anchor_alt,
    )
    return {
        "asset": {"version": "1.1", "tilesetVersion": "1.0"},
        "geometricError": geometric_error,
        "root": {
            "boundingVolume": {"region": region},
            "geometricError": geometric_error,
            "refine": "ADD",
            "content": {"uri": content_uri},
        },
        "extensionsUsed": ["3DTILES_metadata"],
        "extensionsRequired": [],
        "metadata": {
            "class": "tilesetRoot",
            "properties": {
                "generated_at": datetime.now(UTC).isoformat(),
                "generator": "openconstructionerp/geo_hub",
            },
        },
    }


# ── Stage 7: storage write ──────────────────────────────────────────────


async def upload_artifacts(
    *,
    tileset_id: uuid.UUID,
    tileset_json: dict[str, Any],
    b3dm_bytes: bytes,
    storage_backend: Any | None = None,
) -> tuple[str, str]:
    """Persist tileset.json + content.b3dm into the storage backend.

    Returns ``(tileset_json_uri, content_uri)`` — the URIs the API
    surfaces back to the frontend. When ``storage_backend`` is ``None``
    we use the application-default backend; tests pass in an in-memory
    backend to avoid touching disk.
    """
    if storage_backend is None:
        from app.core.storage import get_storage_backend

        storage_backend = get_storage_backend()

    base_key = f"tilesets/{tileset_id}"
    content_key = f"{base_key}/tile_0.b3dm"
    tileset_key = f"{base_key}/tileset.json"

    # Make sure the in-document content URI matches the storage key.
    if "root" in tileset_json and "content" in tileset_json["root"]:
        tileset_json["root"]["content"]["uri"] = "tile_0.b3dm"

    json_bytes = json.dumps(tileset_json, indent=2).encode("utf-8")

    await storage_backend.put(content_key, b3dm_bytes)
    await storage_backend.put(tileset_key, json_bytes)
    return tileset_key, content_key


# ── End-to-end orchestrator (sync helper used by service.py) ────────────


def build_tile_artifacts(
    elements: Sequence[dict[str, Any]],
    *,
    anchor_lat: float,
    anchor_lon: float,
    anchor_alt: float = 0.0,
) -> tuple[dict[str, Any], bytes, GLTFBuild]:
    """Run stages 2-6 end-to-end and return the artefacts.

    Storage upload is intentionally NOT part of this helper — the
    service layer drives it so a unit test can grab the bytes without
    a backend.
    """
    aabb = compute_aabb(elements)
    build = build_gltf_for_tile(elements, aabb)
    b3dm_bytes = write_b3dm(
        build.gltf,
        build.binary_blob,
        feature_table={"BATCH_LENGTH": build.feature_count},
        batch_table=None,
    )
    tileset_json = build_tileset_json(
        aabb,
        content_uri="tile_0.b3dm",
        anchor_lat=anchor_lat,
        anchor_lon=anchor_lon,
        anchor_alt=anchor_alt,
    )
    return tileset_json, b3dm_bytes, build


__all__ = [
    "GLTFBuild",
    "TileAABB",
    "build_gltf_for_tile",
    "build_tile_artifacts",
    "build_tileset_json",
    "compute_aabb",
    "load_canonical_elements",
    "partition_by_aabb",
    "upload_artifacts",
    "write_b3dm",
]
