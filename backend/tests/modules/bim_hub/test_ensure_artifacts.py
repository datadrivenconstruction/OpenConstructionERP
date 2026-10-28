# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service-level tests for ``BIMHubService.ensure_artifacts`` and friends.

These cover the "every BIM import gets viewer + property artifacts" guarantee:

* a DAE-only model (demo seed / CSV+DAE upload) is turned into a plain GLB and
  a baked streaming tileset whose tiled node names still equal the element ids
  (the safety invariant: node name == mesh_ref == stable_id == Parquet ``id``);
* ``ensure_parquet`` synthesises a queryable property sidecar from the Postgres
  ``oe_bim_element`` rows, keyed by ``mesh_ref`` (fallback ``stable_id``), so the
  per-element property panel returns data for non-CAD models;
* the whole thing is idempotent - a second ``ensure_artifacts`` re-uses the GLB,
  tiles and Parquet without rewriting them.

Exercised against the real storage backend + DB session (no HTTP / auth). The
DAE fixtures are built with pycollada (numeric ``<node id>`` per box) so the
bbox-matching DAE->GLB step keeps the node<->element pairing, exactly as a DDC
RvtExporter COLLADA would.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

trimesh = pytest.importorskip("trimesh")
collada = pytest.importorskip("collada")

from app.core.storage import get_storage_backend
from app.database import async_session_factory
from app.modules.bim_hub import dataframe_store
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub.dataframe_store import query_parquet
from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.bim_hub.service import BIMHubService


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _schema_ready():
    """Create just the two BIM tables this module reads/writes."""
    from app.database import engine

    async with engine.begin() as conn:
        await conn.run_sync(BIMModel.__table__.create, checkfirst=True)
        await conn.run_sync(BIMElement.__table__.create, checkfirst=True)
    yield


# ── Fixtures / helpers ──────────────────────────────────────────────────────

# Cube template: 8 vertices + 12 triangles, reused (translated) per element.
_CUBE = np.array(
    [
        [0, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 0, 1],
        [1, 1, 1],
        [0, 1, 1],
    ],
    dtype=float,
)
_TRIS = np.array(
    [
        0,
        1,
        2,
        0,
        2,
        3,
        4,
        5,
        6,
        4,
        6,
        7,
        0,
        1,
        5,
        0,
        5,
        4,
        2,
        3,
        7,
        2,
        7,
        6,
        1,
        2,
        6,
        1,
        6,
        5,
        0,
        3,
        7,
        0,
        7,
        4,
    ]
)


def _build_dae_bytes(n: int, first_id: int = 100000) -> tuple[bytes, list[str]]:
    """Build a COLLADA .dae of ``n`` distinct unit boxes and return its bytes.

    Each box is its own ``<geometry>`` and a ``<node id="NUMERIC">`` carrying
    an ``<instance_geometry>`` - the shape ``_dae_element_bboxes`` parses and
    the shape a DDC RvtExporter COLLADA has. The numeric node id becomes the
    element id preserved through DAE -> GLB -> tile.
    """
    mesh = collada.Collada()
    effect = collada.material.Effect("eff0", [], "phong", diffuse=(0.6, 0.6, 0.6, 1))
    mat = collada.material.Material("mat0", "mat0", effect)
    mesh.effects.append(effect)
    mesh.materials.append(mat)

    nodes = []
    ids: list[str] = []
    for k in range(n):
        # Distinct location per element so every bbox is unique / matchable.
        off = np.array([(k % 20) * 2.0, ((k // 20) % 20) * 2.0, (k // 400) * 2.0])
        verts = (_CUBE + off).flatten()
        eid = str(first_id + k)
        ids.append(eid)
        vsrc = collada.source.FloatSource(f"v{k}", verts, ("X", "Y", "Z"))
        geom = collada.geometry.Geometry(mesh, f"geom{k}", f"geom{k}", [vsrc])
        il = collada.source.InputList()
        il.addInput(0, "VERTEX", f"#v{k}")
        geom.primitives.append(geom.createTriangleSet(_TRIS, il, "mat0"))
        mesh.geometries.append(geom)
        matnode = collada.scene.MaterialNode("mat0", mat, inputs=[])
        node = collada.scene.Node(eid, children=[collada.scene.GeometryNode(geom, [matnode])])
        nodes.append(node)

    scene = collada.scene.Scene("scene0", nodes)
    mesh.scenes.append(scene)
    mesh.scene = scene

    with tempfile.TemporaryDirectory(prefix="oe-test-dae-") as tmp:
        path = Path(tmp) / "geometry.dae"
        mesh.write(str(path))
        return path.read_bytes(), ids


async def _insert_model(project_id: uuid.UUID, model_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        session.add(
            BIMModel(
                id=model_id,
                project_id=project_id,
                name=f"artifacts-test-{model_id}",
                model_format="ifc",
                status="ready",
                element_count=0,
            )
        )
        await session.commit()


async def _insert_elements(model_id: uuid.UUID, rows: list[dict]) -> None:
    async with async_session_factory() as session:
        for r in rows:
            session.add(
                BIMElement(
                    model_id=model_id,
                    stable_id=r["stable_id"],
                    element_type=r.get("element_type"),
                    name=r.get("name"),
                    storey=r.get("storey"),
                    discipline=r.get("discipline"),
                    properties=r.get("properties") or {},
                    quantities=r.get("quantities") or {},
                    mesh_ref=r.get("mesh_ref"),
                )
            )
        await session.commit()


async def _cleanup(project_id: uuid.UUID, model_id: uuid.UUID) -> None:
    await bim_file_storage.delete_model_blobs(project_id, model_id)
    parquet = dataframe_store._existing_parquet_path(str(project_id), str(model_id), None)
    if parquet is not None:
        try:
            parquet.unlink()
        except OSError:
            pass
    async with async_session_factory() as session:
        await session.execute(BIMElement.__table__.delete().where(BIMElement.model_id == model_id))
        obj = await session.get(BIMModel, model_id)
        if obj is not None:
            await session.delete(obj)
        await session.commit()


def _artifact_paths(project_id: uuid.UUID, model_id: uuid.UUID) -> dict[str, Path | None]:
    """Local disk paths for the three artifacts (None when not on local disk)."""
    backend = get_storage_backend()
    glb = bim_file_storage.geometry_key(project_id, model_id, ".glb")
    manifest = bim_file_storage.tiles_manifest_key(project_id, model_id)
    return {
        "glb": backend.local_path(glb),
        "manifest": backend.local_path(manifest),
        "parquet": dataframe_store._existing_parquet_path(str(project_id), str(model_id), None),
    }


# ── (a) DAE-only -> GLB + tileset + node names still equal element ids ───────


@pytest.mark.asyncio
async def test_ensure_artifacts_dae_only_bakes_glb_tileset_preserving_ids() -> None:
    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    n = 450  # above the tiler's MIN_NODES_TO_TILE (400)
    dae_bytes, ids = _build_dae_bytes(n)

    await _insert_model(project_id, model_id)
    # Elements carry mesh_ref == the DAE node id (== glTF node name after bake).
    await _insert_elements(
        model_id,
        [{"stable_id": eid, "mesh_ref": eid, "element_type": "Wall"} for eid in ids],
    )
    # DAE-only: no GLB yet.
    await bim_file_storage.save_geometry(project_id, model_id, ".dae", dae_bytes)

    try:
        found_before = await bim_file_storage.find_geometry_key(project_id, model_id, prefer_ext=".glb")
        assert found_before is not None and found_before[1] == ".dae"  # only the DAE exists

        async with async_session_factory() as session:
            await BIMHubService(session).ensure_artifacts(project_id, model_id)

        # (1) a GLB now exists.
        glb = await bim_file_storage.find_geometry_key(project_id, model_id, prefer_ext=".glb")
        assert glb is not None and glb[1] == ".glb"

        # (2) a real (non-skipped) tileset manifest was baked.
        raw = await bim_file_storage.read_tiles_manifest(project_id, model_id)
        assert raw is not None
        manifest = json.loads(raw)
        assert not manifest.get("skipped")
        assert manifest["tile_count"] >= 1
        assert manifest["tiles"]

        # (3) the safety invariant: tiled node names == element ids (mesh_refs).
        tiled_nodes = [nm for t in manifest["tiles"] for nm in t["nodes"]]
        assert tiled_nodes
        idset = set(ids)
        matched = sum(1 for nm in tiled_nodes if nm in idset)
        assert matched / len(tiled_nodes) >= 0.99, f"only {matched}/{len(tiled_nodes)} names matched"

        # And the property sidecar was synthesised too, keyed by the same ids.
        first_tile_node = tiled_nodes[0]
        rows = query_parquet(
            str(project_id),
            str(model_id),
            filters=[{"column": "id", "op": "=", "value": first_tile_node}],
            limit=1,
        )
        assert len(rows) == 1 and rows[0]["id"] == first_tile_node
    finally:
        await _cleanup(project_id, model_id)


# ── (b) ensure_parquet synthesises a queryable sidecar keyed by mesh_ref ─────


@pytest.mark.asyncio
async def test_ensure_parquet_synthesises_queryable_sidecar_from_postgres() -> None:
    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    await _insert_model(project_id, model_id)
    await _insert_elements(
        model_id,
        [
            {
                "stable_id": "guid-A",
                "mesh_ref": "200001",
                "element_type": "Wall",
                "name": "Basic Wall",
                "storey": "L1",
                "discipline": "architecture",
                "properties": {"Fire Rating": "F90", "Material": "Concrete"},
                "quantities": {"area": 12.5, "volume": 3.0},
            },
            # mesh_ref is null -> id must fall back to stable_id.
            {
                "stable_id": "guid-B",
                "mesh_ref": None,
                "element_type": "Door",
                "properties": {"Fire Rating": "F30"},
                "quantities": {},
            },
        ],
    )

    try:
        async with async_session_factory() as session:
            ok = await BIMHubService(session).ensure_parquet(str(project_id), str(model_id))
        assert ok is True

        # id == mesh_ref returns the row, with flattened properties + quantities.
        rows = query_parquet(
            str(project_id),
            str(model_id),
            filters=[{"column": "id", "op": "=", "value": "200001"}],
            limit=5,
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == "200001"
        assert row["stable_id"] == "guid-A"
        assert row["element_type"] == "Wall"
        assert row["Fire Rating"] == "F90"
        assert row["Material"] == "Concrete"
        # write_dataframe coerces every value to string.
        assert row["area"] == "12.5"

        # mesh_ref null -> id falls back to stable_id, still queryable.
        fallback = query_parquet(
            str(project_id),
            str(model_id),
            filters=[{"column": "id", "op": "=", "value": "guid-B"}],
            limit=5,
        )
        assert len(fallback) == 1
        assert fallback[0]["id"] == "guid-B"
        assert fallback[0]["Fire Rating"] == "F30"
    finally:
        await _cleanup(project_id, model_id)


# ── (c) idempotency: a second ensure_artifacts rewrites nothing ─────────────


@pytest.mark.asyncio
async def test_ensure_artifacts_is_idempotent_and_does_not_rewrite() -> None:
    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    dae_bytes, ids = _build_dae_bytes(450)
    await _insert_model(project_id, model_id)
    await _insert_elements(model_id, [{"stable_id": eid, "mesh_ref": eid} for eid in ids])
    await bim_file_storage.save_geometry(project_id, model_id, ".dae", dae_bytes)

    try:
        async with async_session_factory() as session:
            await BIMHubService(session).ensure_artifacts(project_id, model_id)

        paths = _artifact_paths(project_id, model_id)
        # All three artifacts must be present on local disk to compare mtimes.
        assert paths["glb"] is not None and paths["glb"].is_file()
        assert paths["manifest"] is not None and paths["manifest"].is_file()
        assert paths["parquet"] is not None and paths["parquet"].is_file()
        before = {k: (p.stat().st_mtime_ns, p.stat().st_size) for k, p in paths.items()}

        # Second run: every step sees its artifact already present -> no rewrite.
        async with async_session_factory() as session:
            await BIMHubService(session).ensure_artifacts(project_id, model_id)

        after = {k: (p.stat().st_mtime_ns, p.stat().st_size) for k, p in paths.items()}
        assert after == before, f"artifacts were rewritten: before={before} after={after}"
    finally:
        await _cleanup(project_id, model_id)
