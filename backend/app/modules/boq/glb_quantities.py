# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quantities measured on the meshes of a converter GLB, per element.

The DDC 2026.10 RVT converter writes geometry (``native_graph.glb``, one node
per element, ``extras.element_id``) and the stored-object graph, but no
calculated quantities: Revit's own Area / Volume / Length are computed values
that are not saved in the file. This module measures them on the mesh, in
metres (glTF is metric and the converter's node matrices carry the feet to
metre scale):

* ``Volume`` (m3): enclosed volume of the element's triangles, only when the
  mesh is closed. An open mesh has no volume, and none is invented.
* ``Area`` (m2): for plate-like elements (walls, floors, roofs, ceilings,
  panels), one face: half the area of the triangles facing the plate's thin
  direction. Openings cut in the mesh are therefore excluded, as in Revit.
* ``Length`` (m): the longest in-plane horizontal extent of a plate, or the
  main extent of a linear element (beams, columns, pipes, ducts).
* ``Height`` (m): vertical extent. ``Thickness`` (m): a plate's thin extent.
* ``Surface Area`` (m2): every triangle.

These are measurements of the exported mesh, not Revit schedule values; curved
or irregular elements can differ from Revit's figures.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

#: Columns this module can add, in display order.
MESH_QUANTITY_COLUMNS: tuple[str, ...] = ("Area", "Volume", "Length", "Height", "Thickness", "Surface Area")

_COMPONENT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_UP = (0.0, 1.0, 0.0)  # glTF is Y-up

#: A plate's thin extent is at most this share of its middle extent.
_PLATE_RATIO = 0.35
#: A linear element's main extent is at least this multiple of its middle extent.
_LINEAR_RATIO = 3.0
#: Share of welded edges that must be shared by exactly two triangles for a volume.
_CLOSED_SHARE = 0.98


def _read_glb(glb_path: Path) -> tuple[dict[str, Any], bytes]:
    data = glb_path.read_bytes()
    if data[:4] != b"glTF" or data[16:20] != b"JSON":
        raise ValueError(f"{glb_path.name} is not a GLB file")
    json_len = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20 : 20 + json_len].decode("utf-8"))
    rest = 20 + json_len
    binary = b""
    if len(data) >= rest + 8 and data[rest + 4 : rest + 8] == b"BIN\x00":
        bin_len = struct.unpack("<I", data[rest : rest + 4])[0]
        binary = data[rest + 8 : rest + 8 + bin_len]
    return doc, binary


def _accessor(doc: dict[str, Any], binary: bytes, index: int) -> Any:
    import numpy as np

    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(_COMPONENT[acc["componentType"]]).newbyteorder("<")
    width = _WIDTH[acc["type"]]
    count = acc["count"]
    offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or dtype.itemsize * width
    if stride == dtype.itemsize * width:
        arr = np.frombuffer(binary, dtype=dtype, count=count * width, offset=offset)
        return arr.reshape(count, width) if width > 1 else arr
    raw = np.frombuffer(binary, dtype=np.uint8, count=stride * (count - 1) + dtype.itemsize * width, offset=offset)
    rows = np.lib.stride_tricks.as_strided(raw, shape=(count, dtype.itemsize * width), strides=(stride, 1))
    return np.ascontiguousarray(rows).view(dtype).reshape(count, width)


def _local_matrix(node: dict[str, Any]) -> Any:
    import numpy as np

    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    m = np.eye(4)
    t = node.get("translation")
    r = node.get("rotation")
    s = node.get("scale")
    if s:
        m = np.diag([s[0], s[1], s[2], 1.0]) @ m
    if r:
        x, y, z, w = r
        rot = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
                [0, 0, 0, 1],
            ]
        )
        m = rot @ m
    if t:
        tm = np.eye(4)
        tm[:3, 3] = t
        m = tm @ m
    return m


def _element_triangles(doc: dict[str, Any], binary: bytes) -> dict[int, list[Any]]:
    """World-space triangles ``(n, 3, 3)`` per element id."""
    import numpy as np

    nodes = doc.get("nodes", [])
    meshes = doc.get("meshes", [])
    out: dict[int, list[Any]] = {}
    roots: list[int] = []
    for scene in doc.get("scenes", []) or []:
        roots.extend(scene.get("nodes", []))
    if not roots:
        children = {c for n in nodes for c in n.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    stack = [(i, np.eye(4), None) for i in roots]
    seen: set[int] = set()
    while stack:
        idx, parent_m, parent_eid = stack.pop()
        if idx in seen or idx >= len(nodes):
            continue
        seen.add(idx)
        node = nodes[idx]
        world = parent_m @ _local_matrix(node)
        eid = (node.get("extras") or {}).get("element_id", parent_eid)
        if isinstance(eid, int) and "mesh" in node:
            for prim in meshes[node["mesh"]].get("primitives", []):
                if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                    continue
                pos = _accessor(doc, binary, prim["attributes"]["POSITION"]).astype(float)
                if "indices" in prim:
                    idxs = _accessor(doc, binary, prim["indices"]).astype(np.int64)
                else:
                    idxs = np.arange(len(pos), dtype=np.int64)
                idxs = idxs[: len(idxs) - len(idxs) % 3].reshape(-1, 3)
                if not len(idxs):
                    continue
                pts = pos @ world[:3, :3].T + world[:3, 3]
                out.setdefault(eid, []).append(pts[idxs])
        for child in node.get("children", []):
            stack.append((child, world, eid if isinstance(eid, int) else None))
    return out


def _is_closed(tris: Any) -> bool:
    import numpy as np

    verts = np.round(tris.reshape(-1, 3), 5)
    _, inverse = np.unique(verts, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1, 3)
    edges = np.concatenate([inverse[:, [0, 1]], inverse[:, [1, 2]], inverse[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    edges = edges[edges[:, 0] != edges[:, 1]]
    if not len(edges):
        return False
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return float(np.mean(counts == 2)) >= _CLOSED_SHARE


def measure_triangles(tris: Any) -> dict[str, float]:
    """Quantities of one element from its world-space triangles ``(n, 3, 3)`` in metres."""
    import numpy as np

    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cross = np.cross(b - a, c - a)
    norms = np.linalg.norm(cross, axis=1)
    keep = norms > 1e-12
    if not keep.any():
        return {}
    tris, cross, norms = tris[keep], cross[keep], norms[keep]
    tri_area = 0.5 * norms
    normals = cross / norms[:, None]
    out: dict[str, float] = {"Surface Area": float(tri_area.sum())}

    pts = tris.reshape(-1, 3)
    up = np.array(_UP)
    heights = pts @ up
    out["Height"] = float(heights.max() - heights.min())

    # Each corner once: a vertex repeated by many triangles would tilt the axes.
    corners = np.unique(np.round(pts, 5), axis=0)
    centred = corners - corners.mean(axis=0)
    _, vecs = np.linalg.eigh(centred.T @ centred)
    axes = vecs.T[::-1]  # largest variance first
    proj = centred @ axes.T
    extents = proj.max(axis=0) - proj.min(axis=0)
    order = np.argsort(-extents)
    axes, extents = axes[order], extents[order]
    e1, e2, e3 = (float(x) for x in extents)

    if e2 > 0 and e3 <= _PLATE_RATIO * e2:
        thin = axes[2]
        facing = np.abs(normals @ thin) > 0.9
        out["Area"] = float(tri_area[facing].sum() / 2.0)
        out["Thickness"] = e3
        # A wall's length is its horizontal in-plane extent; a slab has two, take the longer.
        horizontal = [float(extents[i]) for i in (0, 1) if abs(float(axes[i] @ up)) < 0.5]
        out["Length"] = max(horizontal) if horizontal else e1
    elif e2 > 0 and e1 >= _LINEAR_RATIO * e2 or e2 == 0 and e1 > 0:
        out["Length"] = e1

    if _is_closed(tris):
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        out["Volume"] = abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)
    return {k: round(v, 4) for k, v in out.items() if math.isfinite(v) and v > 0}


def glb_element_quantities(glb_path: Path) -> dict[int, dict[str, float]]:
    """``{element_id: {column: value}}`` for every element with triangles in the GLB."""
    import numpy as np

    doc, binary = _read_glb(glb_path)
    result: dict[int, dict[str, float]] = {}
    for eid, parts in _element_triangles(doc, binary).items():
        tris = parts[0] if len(parts) == 1 else np.concatenate(parts)
        q = measure_triangles(tris)
        if q:
            result[eid] = q
    return result
