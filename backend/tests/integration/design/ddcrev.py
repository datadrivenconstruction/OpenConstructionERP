"""Build real ``.ddcrev`` packages for tests from the contract examples (contract §2–§5)."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import struct
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

EXAMPLES = Path(__file__).resolve().parent / "contract" / "examples"


def example(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def example_rows() -> list[dict[str, Any]]:
    return copy.deepcopy(example("elements.rows.json"))


# ── geometry.glb: one shared box mesh, one node per element (contract §3) ───


def _box() -> tuple[bytes, bytes, bytes, int, int]:
    faces = [  # normal, four corners (counter-clockwise seen from outside)
        ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
        ((-1, 0, 0), [(0, 0, 1), (0, 1, 1), (0, 1, 0), (0, 0, 0)]),
        ((0, 1, 0), [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)]),
        ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
        ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
        ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)]),
    ]
    pos, nor, idx = bytearray(), bytearray(), bytearray()
    for f, (n, quad) in enumerate(faces):
        for v in quad:
            pos += struct.pack("<3f", *v)
            nor += struct.pack("<3f", *n)
        b = f * 4
        idx += struct.pack("<6H", b, b + 1, b + 2, b, b + 2, b + 3)
    return bytes(pos), bytes(nor), bytes(idx), 24, 36


def glb(rows: list[dict[str, Any]]) -> bytes:
    pos, nor, idx, nverts, nidx = _box()
    binary = pos + nor + idx
    binary += b"\0" * (-len(binary) % 4)
    nodes = []
    for r in rows:
        if r["ifc_class"] == "IfcSpace":  # spaces live in Parquet only
            continue
        # GLB space is Y-up; bbox in the rows is already in GLB space.
        lo = [r["bbox_min_x"], r["bbox_min_y"], r["bbox_min_z"]]
        hi = [r["bbox_max_x"], r["bbox_max_y"], r["bbox_max_z"]]
        nodes.append(
            {
                "name": r["element_key"],
                "mesh": 0,
                "translation": lo,
                "scale": [max(b - a, 0.01) for a, b in zip(lo, hi, strict=True)],
                "extras": {"element_key": r["element_key"], "type_key": r["type_key"], "ifc_class": r["ifc_class"]},
            }
        )
    doc = {
        "asset": {"version": "2.0", "generator": "ddc-erp-link tests"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
        "materials": [
            {"pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1], "metallicFactor": 0, "roughnessFactor": 1}}
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos), "byteLength": len(nor), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos) + len(nor), "byteLength": len(idx), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": nverts,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [1, 1, 1],
            },
            {"bufferView": 1, "componentType": 5126, "count": nverts, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": nidx, "type": "SCALAR"},
        ],
    }
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(js), b"JSON")
        + js
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )


# ── elements.parquet with native types (contract §4) ────────────────────────


def parquet(rows: list[dict[str, Any]], compression: str = "zstd") -> bytes:
    from app.modules.design import contract_models as cm

    fields = []
    for name in cm.ALL_COLUMNS:
        if name in cm.QTY_COLUMNS + cm.BBOX_COLUMNS:
            fields.append(pa.field(name, pa.float64()))
        elif name in cm.INT_COLUMNS:
            fields.append(pa.field(name, pa.int64()))
        else:
            fields.append(pa.field(name, pa.string()))
    schema = pa.schema(fields)
    table = pa.Table.from_pylist([{c: r.get(c) for c in cm.ALL_COLUMNS} for r in rows], schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression=compression, row_group_size=50_000)
    return buf.getvalue()


def diff_doc(revision_id: str, parent_id: str, old: list[dict], new: list[dict]) -> dict[str, Any]:
    o = {r["element_key"]: r for r in old}
    n = {r["element_key"]: r for r in new}
    changed = []
    for k in sorted(o.keys() & n.keys()):
        fields = [{"field": c, "old": o[k][c], "new": n[k][c]} for c in n[k] if o[k].get(c) != n[k][c]]
        if fields:
            changed.append(
                {"element_key": k, "geometry": o[k]["geometry_hash"] != n[k]["geometry_hash"], "fields": fields}
            )
    return {
        "schema": "ddc-diff/1",
        "revision_id": revision_id,
        "parent_revision_id": parent_id,
        "added": sorted(n.keys() - o.keys()),
        "removed": sorted(o.keys() - n.keys()),
        "changed": changed,
        "by_type": [],
    }


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(
    project_id: uuid.UUID | str | None,
    rows: list[dict[str, Any]],
    *,
    parent_id: str | None = None,
    parent_rows: list[dict[str, Any]] | None = None,
    revision_id: str | None = None,
    files: dict[str, bytes] | None = None,
    extra_members: dict[str, bytes] | None = None,
    manifest_edit=None,
) -> tuple[bytes, dict[str, Any]]:
    """Return ``(zip bytes, manifest)``; ``files`` replaces or adds package files before hashing,
    ``extra_members`` adds archive members the manifest does not list, ``manifest_edit(m)`` runs last."""
    rid = revision_id or str(uuid.uuid4())
    content: dict[str, bytes] = {
        "model.ddc": b"DDC-SOURCE\n" + json.dumps(rows, sort_keys=True).encode("utf-8"),
        "geometry.glb": glb(rows),
        "elements.parquet": parquet(rows),
    }
    roles = {"model.ddc": "source", "geometry.glb": "geometry", "elements.parquet": "elements"}
    if parent_id is not None:
        content["diff.json"] = json.dumps(diff_doc(rid, parent_id, parent_rows or [], rows)).encode("utf-8")
        roles["diff.json"] = "diff"
    for path, data in (files or {}).items():
        content[path] = data
        roles.setdefault(path, "sheet" if path.startswith("sheets/") else "thumbnail")
    m = copy.deepcopy(example("manifest.json"))
    m["revision_id"] = rid
    m["parent_revision_id"] = parent_id
    m["project_ref"]["erp_project_id"] = str(project_id) if project_id else None
    m["counts"]["elements"] = len(rows)
    m["checks"] = {"errors": 0, "warnings": 0}
    m["files"] = [{"path": p, "role": roles[p], "sha256": sha(d), "bytes": len(d)} for p, d in content.items()]
    if manifest_edit is not None:
        manifest_edit(m)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(m, indent=1))
        for path, data in content.items():
            zf.writestr(path, data)
        for path, data in (extra_members or {}).items():
            zf.writestr(zipfile.ZipInfo(path), data)
    return buf.getvalue(), m
