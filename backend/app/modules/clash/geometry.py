# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Real per-element geometry for the clash-detection engine.

This module is the geometry layer the clash engine builds on. It loads
the *actual* triangle meshes that ship on disk as
``data/bim/<project>/<model>/geometry.glb`` (produced by the DDC
cad2data pipeline / IFC processor — never IfcOpenShell, never native
IFC) and turns every real **placed instance node** into an
:class:`ElementGeom`: world-space vertices/faces in metres, an exact
axis-aligned bounding box, a tight oriented bounding box and an honest
storey index.

No synthetic boxes, no placeholders, **no chunking**. One ElementGeom
per real placed element node. If a node carries no real triangles in
world space it is skipped.

Honest identity model
---------------------
Verified against the real showcase GLBs (7 projects × {architecture
IFC, structural RVT}):

* Each ``geometry.glb`` is a *flat* COLLADA-derived scene: a single
  ``world`` root whose direct children are the mesh nodes (graph depth
  1 — there is **no** element-node → fragment-node hierarchy, so there
  is nothing to "group by parent": each placed node already *is* one
  real element).
* Mesh nodes fall into two classes:
  - **numeric** names (e.g. ``"1030049"``) — real DDC *placed
    instance* nodes. Each has its own dedicated geometry (no
    instancing: every node references a distinct geometry key, max
    reuse == 1), a real world transform and real triangles. These are
    the elements.
  - ``shapeN-lib`` names — COLLADA ``library_geometries`` *template*
    nodes. Every one of them sits at the identity transform / origin
    and is never instanced by a numeric node. They are unplaced
    templates and are **excluded** (counting them would double-count
    and place phantom geometry at the origin).
* The 380 legacy ``oe_bim_element`` rows (``source: ifc_parse``,
  ``stable_id`` == IFC ``GlobalId``) have **no** honest link to the
  GLB numeric node ids — there is no shared id, no material, no DDC
  sidecar, and DDC cad2data is unavailable offline to re-derive one.
  They are therefore abandoned: an element here is one real GLB placed
  instance node, keyed by its own stable node id.

The two models of one project are **not co-registered** (the
architecture IFC and structural RVT live in different scales/origins),
so this provider is strictly *single-model*; cross-model clash would
be dishonest and is out of scope.

Discipline
----------
Per-element discipline is not honestly recoverable offline, so
``ElementGeom.discipline`` is the owning ``oe_bim_model.discipline``
("architecture" / "structural" / …) — which truthfully *is* the
discipline of every element in that model. The honest coordination
matrix is therefore Level × Level, driven by :attr:`ElementGeom.storey`
(a deterministic Z-band clustering of element centroids).

Units
-----
``scene.units`` (or per-mesh ``extras.units``) declares the source
scale, but the DDC RVT exporter mis-tags metre-scale geometry as
millimetres. The declared scale is *verified* against the resulting
whole-model extent (a real building's largest dimension sits in the
3 m – 2 km band); if it is implausible the raw coordinates are treated
as metres. Geometry-driven, no per-format hardcode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# A real building's largest single dimension almost always lands in this
# band (a 3 m shed up to a ~2 km infrastructure corridor). Used purely
# to *sanity-check* a declared unit scale, never to fabricate geometry.
_PLAUSIBLE_MODEL_MIN_M = 3.0
_PLAUSIBLE_MODEL_MAX_M = 2_000.0

# Storey detection. A real multi-storey building does NOT separate its
# floors by empty Z-gaps (columns/walls/shafts span storeys and there
# are elements at every height) — floors show up as *density modes*:
# slabs/beams/furniture cluster at each floor elevation with sparser
# bands between. So levels are split at significant *valleys* in a
# smoothed centroid-Z histogram. Deterministic, no RNG, no sklearn.
_STOREY_BIN_M = 0.5  # histogram bin width (≈ slab thickness order)
_STOREY_SMOOTH = 1  # ± bins moving-average smoothing radius
# A histogram valley is a real floor boundary only when the bands on
# both sides are this many× denser than the valley floor AND the two
# peaks are at least this far apart in metres (a plausible storey
# height) — guards against splitting noise within one floor.
_STOREY_VALLEY_RATIO = 1.5
_STOREY_MIN_FLOOR_TO_FLOOR_M = 2.0
_STOREY_MAX_LEVELS = 60

# Sidecar cache written next to the GLB so re-runs are fast and the
# computed geometry is inspectable without a DB round-trip.
_CACHE_FILENAME = "geometry.clash.json"
_CACHE_VERSION = 2


@dataclass
class ElementGeom:
    """Real world-space geometry for one placed BIM element.

    All coordinates are metres in the model's world frame (GLB node
    transforms already applied).

    Attributes:
        element_id: Stable GLB node id (DDC placed-instance id). This is
            the canonical key the engine uses; equals ``stable_id``.
        stable_id: Same stable GLB node id (kept for the engine
            contract; never ``None`` here).
        name: The element's stable node id (no honest human name is
            available offline for these placed instances).
        discipline: The owning ``oe_bim_model.discipline`` — honest, it
            is that model's discipline for every element in it.
        aabb: ``(min_x, min_y, min_z, max_x, max_y, max_z)`` metres.
        vertices: ``(N, 3)`` float64 world coordinates, metres.
        faces: ``(M, 3)`` int64 triangle indices into ``vertices``.
        obb_center: ``(3,)`` float64 oriented-box centre.
        obb_axes: ``(3, 3)`` float64 unit row vectors (box frame).
        obb_half: ``(3,)`` float64 oriented-box half-extents.
        storey: Deterministic level index (0 == lowest band) from
            Z-band clustering of element AABB centroids across the
            model. Drives the Level × Level clash matrix.
    """

    element_id: str
    stable_id: str | None
    name: str
    discipline: str
    aabb: tuple[float, float, float, float, float, float]
    vertices: np.ndarray
    faces: np.ndarray
    obb_center: np.ndarray
    obb_axes: np.ndarray
    obb_half: np.ndarray
    storey: int


def _repo_data_root() -> pathlib.Path:
    """Return ``<repo>/data`` — the local storage root for BIM blobs.

    Mirrors :func:`app.core.storage._default_local_base_dir` so this
    module never invents a second path scheme. This file lives at
    ``backend/app/modules/clash/geometry.py`` → ``parents[4]`` == repo
    root.
    """
    return pathlib.Path(__file__).resolve().parents[4] / "data"


def _is_template_node(node_name: str) -> bool:
    """Return ``True`` for COLLADA ``library_geometries`` template nodes.

    Verified on every showcase GLB: these are named ``shapeN-lib``,
    always sit at the identity transform and are never instanced — they
    are unplaced templates, not real placed elements.
    """
    s = str(node_name).lower()
    return "-lib" in s or s.startswith("shape")


def _stable_node_key(name: str) -> tuple[int, Any]:
    """Order-stable sort key for a GLB node name.

    Numeric DDC placed-instance ids sort numerically; everything else
    sorts lexicographically after the numerics. Deterministic, no RNG.
    """
    s = str(name)
    core = s[1:] if s[:1] == "-" else s
    if core.isdigit():
        return (0, int(s))
    return (1, s)


def _obb_from_vertices(
    vertices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute a tight oriented bounding box via deterministic PCA.

    The box frame is the principal-axis frame of the element's vertex
    cloud (eigenvectors of the covariance, descending variance); the
    extents are the exact min/max of the real vertices projected into
    that frame, so the box is a *true* enclosing box of the geometry,
    not an approximation. This is O(N) per element with no convex hull
    — fast enough to run over every element of a 5 k+ element model and
    fully deterministic (no RNG, stable eigen ordering). For a degree
    of robustness on huge meshes the covariance is estimated from a
    deterministic stride-sampled subset, but min/max extents always use
    **all** vertices so the box never under-encloses.

    Args:
        vertices: ``(N, 3)`` world coordinates.

    Returns:
        ``(center(3,), axes(3,3), half(3,))`` — all float64, ``axes``
        rows are orthonormal vectors of the box frame.
    """
    pts = np.asarray(vertices, dtype=np.float64)
    if pts.shape[0] == 0:
        z3 = np.zeros(3, dtype=np.float64)
        return z3, np.eye(3, dtype=np.float64), z3.copy()

    center_pt = pts.mean(axis=0)
    centred = pts - center_pt

    # Covariance from a deterministic stride sample (caps cost on dense
    # meshes); extents below still use every vertex.
    cov_pts = centred
    cap = 4096
    if centred.shape[0] > cap:
        step = centred.shape[0] // cap
        cov_pts = centred[::step]
    cov = np.cov(cov_pts, rowvar=False)
    if cov.shape != (3, 3) or not np.all(np.isfinite(cov)):
        cov = np.eye(3, dtype=np.float64)
    eigvals, eigvecs = np.linalg.eigh(cov)
    _ = eigvals
    axes = eigvecs.T[::-1].astype(np.float64)  # descending variance
    norms = np.linalg.norm(axes, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    axes = axes / norms

    proj = centred @ axes.T
    lo = proj.min(axis=0)
    hi = proj.max(axis=0)
    half = ((hi - lo) * 0.5).astype(np.float64)
    center = (center_pt + (axes.T @ ((hi + lo) * 0.5))).astype(np.float64)
    return center.astype(np.float64), axes, half


def _resolve_unit_scale(scene: object, raw_extent: np.ndarray) -> float:
    """Return metres-per-unit, verified against the model's real extent.

    The declared scale (``scene.units`` / per-mesh ``extras.units``) is
    trusted only if applying it lands the model's largest dimension in
    the plausible-building band. Otherwise the raw coordinates are
    treated as already-metres (scale ``1.0``).

    Args:
        scene: A loaded :class:`trimesh.Scene`.
        raw_extent: ``(3,)`` largest-minus-smallest of the merged raw
            (pre-scale) world vertices.

    Returns:
        Metres-per-unit multiplier to apply to raw coordinates.
    """
    declared = 1.0
    try:
        import trimesh

        units = getattr(scene, "units", None)
        if not units:
            for geom in getattr(scene, "geometry", {}).values():
                units = (getattr(geom, "metadata", {}) or {}).get("units")
                if units:
                    break
        if units:
            conv = trimesh.units.unit_conversion(str(units), "meters")
            if conv and math.isfinite(conv) and conv > 0.0:
                declared = float(conv)
    except Exception as exc:  # noqa: BLE001 — default to 1.0 (metres)
        logger.debug("Unit resolution fell back to metres: %s", exc)

    biggest_raw = float(np.max(raw_extent)) if raw_extent.size else 0.0
    if biggest_raw <= 0.0:
        return declared

    scaled = biggest_raw * declared
    if _PLAUSIBLE_MODEL_MIN_M <= scaled <= _PLAUSIBLE_MODEL_MAX_M:
        return declared
    if _PLAUSIBLE_MODEL_MIN_M <= biggest_raw <= _PLAUSIBLE_MODEL_MAX_M:
        logger.info(
            "Declared unit scale %.6g would yield a %.1f m model — treating raw coordinates as metres instead",
            declared,
            scaled,
        )
        return 1.0
    return declared


def _assign_storeys(centroid_z: np.ndarray) -> np.ndarray:
    """Split element centroid-Z into deterministic storey bands.

    Floors are recovered from the *density structure* of the centroid-Z
    distribution, not from empty gaps (a real building has none): build
    a fixed-width histogram, smooth it, find significant valleys (a bin
    whose count is a clear local minimum flanked by denser peaks at
    least a plausible floor-to-floor apart) and split at the elevation
    of each such valley. Fully deterministic — no RNG, no sklearn. If
    there is no honest multi-modal structure a single level is
    returned (we never fabricate floors).

    Args:
        centroid_z: ``(N,)`` element AABB-centroid Z in metres.

    Returns:
        ``(N,)`` int64 level index per element (0 == lowest band).
    """
    n = centroid_z.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    if n == 1:
        return np.zeros(1, dtype=np.int64)

    z = centroid_z.astype(np.float64)
    z_min = float(z.min())
    z_max = float(z.max())
    if z_max - z_min < _STOREY_MIN_FLOOR_TO_FLOOR_M:
        return np.zeros(n, dtype=np.int64)  # too short to hold 2 floors

    nbins = max(int(math.ceil((z_max - z_min) / _STOREY_BIN_M)), 2)
    edges = np.linspace(z_min, z_max, nbins + 1)
    hist, _ = np.histogram(z, bins=edges)

    # Smooth with a small moving average so single sparse bins inside a
    # floor don't read as valleys.
    r = _STOREY_SMOOTH
    if r > 0 and hist.size > 2 * r + 1:
        kernel = np.ones(2 * r + 1, dtype=np.float64) / (2 * r + 1)
        smooth = np.convolve(hist.astype(np.float64), kernel, mode="same")
    else:
        smooth = hist.astype(np.float64)

    centers = 0.5 * (edges[:-1] + edges[1:])
    min_bins_apart = max(
        int(round(_STOREY_MIN_FLOOR_TO_FLOOR_M / _STOREY_BIN_M)),
        1,
    )

    # Walk peaks; a valley between two consecutive peaks is a storey
    # boundary when both peaks dominate the valley floor and are far
    # enough apart vertically to be different storeys.
    boundaries: list[float] = []
    last_peak_idx: int | None = None
    last_peak_val = 0.0
    i = 0
    size = smooth.size
    while i < size:
        # Extent of the current local maximum plateau.
        if (i == 0 or smooth[i] >= smooth[i - 1]) and (i == size - 1 or smooth[i] >= smooth[i + 1]):
            peak_val = float(smooth[i])
            if last_peak_idx is not None:
                seg = smooth[last_peak_idx : i + 1]
                valley_val = float(seg.min())
                valley_off = int(np.argmin(seg))
                valley_idx = last_peak_idx + valley_off
                far_enough = (centers[i] - centers[last_peak_idx]) >= _STOREY_MIN_FLOOR_TO_FLOOR_M
                deep_enough = valley_val * _STOREY_VALLEY_RATIO <= min(
                    peak_val,
                    last_peak_val,
                )
                spread_enough = (i - last_peak_idx) >= min_bins_apart
                if far_enough and deep_enough and spread_enough:
                    boundaries.append(float(edges[valley_idx + 1]))
                    last_peak_idx = i
                    last_peak_val = peak_val
                elif peak_val > last_peak_val:
                    last_peak_idx = i
                    last_peak_val = peak_val
            else:
                last_peak_idx = i
                last_peak_val = peak_val
        i += 1

    if not boundaries:
        return np.zeros(n, dtype=np.int64)
    if len(boundaries) > _STOREY_MAX_LEVELS - 1:
        boundaries = boundaries[: _STOREY_MAX_LEVELS - 1]

    return np.searchsorted(
        np.asarray(boundaries, dtype=np.float64),
        z,
        side="right",
    ).astype(np.int64)


def _node_world_vertices_faces(
    scene: object,
    node_name: str,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return ``(vertices, faces)`` for one scene node, transform applied.

    Vertices are float64 world coordinates *before* unit scaling.
    Returns ``None`` when the node carries fewer than one triangle.
    """
    try:
        import trimesh

        transform, geom_name = scene.graph[node_name]  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — node without geometry
        return None
    geom = scene.geometry.get(geom_name)  # type: ignore[attr-defined]
    if geom is None:
        return None
    verts = np.asarray(getattr(geom, "vertices", np.empty((0, 3))), dtype=np.float64)
    faces = np.asarray(getattr(geom, "faces", np.empty((0, 3))), dtype=np.int64)
    if verts.shape[0] < 3 or faces.shape[0] < 1:
        return None
    world = trimesh.transformations.transform_points(
        verts,
        np.asarray(transform, dtype=np.float64),
    )
    return np.asarray(world, dtype=np.float64), faces


class ClashGeometryProvider:
    """Loads real per-instance GLB geometry for one BIM model."""

    def __init__(self, storage_root: pathlib.Path | None = None) -> None:
        """Initialise the provider.

        Args:
            storage_root: Local storage root holding ``bim/...`` blobs.
                Defaults to ``<repo>/data`` (same as
                :class:`app.core.storage.LocalStorageBackend`).
        """
        self.storage_root: pathlib.Path = pathlib.Path(storage_root) if storage_root is not None else _repo_data_root()

    # ── path resolution (reuses the bim_hub storage scheme) ────────────

    def _resolve_glb_path(self, model: object) -> pathlib.Path | None:
        """Resolve a model's geometry GLB on the local filesystem.

        Honours the persisted ``canonical_file_path`` first (the value
        the bim_hub viewer serves), then falls back to the canonical
        ``bim/{project}/{model}/geometry.glb`` key used by
        :func:`app.modules.bim_hub.file_storage.geometry_key`.
        """
        candidates: list[pathlib.Path] = []
        cfp = getattr(model, "canonical_file_path", None)
        if cfp:
            cfp = str(cfp).replace("\\", "/").lstrip("/")
            candidates.append(self.storage_root / pathlib.PurePosixPath(cfp))
            if not cfp.endswith(".glb"):
                stem = pathlib.PurePosixPath(cfp)
                candidates.append(self.storage_root / stem.with_name("geometry.glb"))
        proj = getattr(model, "project_id", None)
        mid = getattr(model, "id", None)
        if proj is not None and mid is not None:
            candidates.append(
                self.storage_root / "bim" / str(proj) / str(mid) / "geometry.glb",
            )
        for path in candidates:
            try:
                if path.is_file():
                    return path
            except OSError:
                continue
        return None

    # ── public API ─────────────────────────────────────────────────────

    async def load(
        self,
        session: AsyncSession,
        model_id: uuid.UUID | str,
    ) -> dict[str, ElementGeom]:
        """Load real per-instance geometry for one model.

        Resolves the model's GLB, loads it with trimesh (scene,
        ``process=False``, node world transforms applied), and produces
        **one** :class:`ElementGeom` per real placed instance node that
        carries real triangles. Template (``shapeN-lib``) nodes are
        excluded. ``discipline`` is the owning model's discipline;
        ``storey`` is a deterministic Z-band level index. Deterministic
        ordering by node id; no chunking, no RNG.

        Args:
            session: Async SQLAlchemy session.
            model_id: ``oe_bim_model.id``.

        Returns:
            ``{node_id: ElementGeom}``. Empty if the GLB is missing or
            holds no usable placed geometry.
        """
        from sqlalchemy import select

        from app.modules.bim_hub.models import BIMModel

        model = (await session.execute(select(BIMModel).where(BIMModel.id == model_id))).scalar_one_or_none()
        if model is None:
            logger.warning("clash.geometry: model %s not found", model_id)
            return {}

        glb_path = self._resolve_glb_path(model)
        if glb_path is None:
            logger.warning(
                "clash.geometry: no geometry.glb for model %s (cfp=%r)",
                model_id,
                getattr(model, "canonical_file_path", None),
            )
            return {}

        discipline = str(getattr(model, "discipline", None) or "Unassigned")

        return await asyncio.to_thread(self._build, str(glb_path), discipline)

    def _build(self, glb_path: str, discipline: str) -> dict[str, ElementGeom]:
        """Synchronous core of :meth:`load` (runs off the event loop)."""
        try:
            import trimesh

            scene = trimesh.load(glb_path, process=False, force="scene")
        except Exception as exc:  # noqa: BLE001 — corrupt/unsupported blob
            logger.warning("clash.geometry: trimesh failed on %s: %s", glb_path, exc)
            return {}

        if not isinstance(scene, trimesh.Scene) or not scene.geometry:
            logger.warning("clash.geometry: %s has no scene geometry", glb_path)
            return {}

        # One node == one real placed element. Exclude unplaced COLLADA
        # library templates. Deterministic order by node id.
        placed_nodes = sorted(
            (n for n in scene.graph.nodes_geometry if not _is_template_node(n)),
            key=_stable_node_key,
        )

        raw: list[tuple[str, np.ndarray, np.ndarray]] = []
        raw_lo = np.full(3, np.inf)
        raw_hi = np.full(3, -np.inf)
        for nm in placed_nodes:
            vf = _node_world_vertices_faces(scene, nm)
            if vf is None:
                continue
            verts, faces = vf
            raw.append((str(nm), verts, faces))
            raw_lo = np.minimum(raw_lo, verts.min(axis=0))
            raw_hi = np.maximum(raw_hi, verts.max(axis=0))
        if not raw:
            logger.warning(
                "clash.geometry: %s yielded 0 placed instance nodes",
                glb_path,
            )
            return {}

        scale = _resolve_unit_scale(scene, raw_hi - raw_lo)

        node_ids: list[str] = []
        aabbs: list[tuple[float, float, float, float, float, float]] = []
        verts_scaled: list[np.ndarray] = []
        faces_all: list[np.ndarray] = []
        centroids_z: list[float] = []
        for nid, verts, faces in raw:
            v = verts * scale
            lo = v.min(axis=0)
            hi = v.max(axis=0)
            if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))):
                continue
            if not np.any(hi > lo):  # degenerate — no extent on any axis
                continue
            node_ids.append(nid)
            aabbs.append(
                (
                    float(lo[0]),
                    float(lo[1]),
                    float(lo[2]),
                    float(hi[0]),
                    float(hi[1]),
                    float(hi[2]),
                ),
            )
            verts_scaled.append(v)
            faces_all.append(faces.astype(np.int64))
            centroids_z.append(float((lo[2] + hi[2]) * 0.5))

        if not node_ids:
            return {}

        levels = _assign_storeys(np.asarray(centroids_z, dtype=np.float64))

        out: dict[str, ElementGeom] = {}
        for i, nid in enumerate(node_ids):
            v = verts_scaled[i]
            center, axes, half = _obb_from_vertices(v)
            out[nid] = ElementGeom(
                element_id=nid,
                stable_id=nid,
                name=nid,
                discipline=discipline,
                aabb=aabbs[i],
                vertices=v.astype(np.float64),
                faces=faces_all[i],
                obb_center=center.astype(np.float64),
                obb_axes=axes.astype(np.float64),
                obb_half=half.astype(np.float64),
                storey=int(levels[i]),
            )

        logger.info(
            "clash.geometry: %s -> %d placed elements, %d storeys (disc=%s)",
            pathlib.Path(glb_path).name,
            len(out),
            len({g.storey for g in out.values()}),
            discipline,
        )
        return out

    # ── persistence (inspectable sidecar — never fabricates DB rows) ───

    def _cache_path(self, glb_path: pathlib.Path) -> pathlib.Path:
        return glb_path.with_name(_CACHE_FILENAME)

    async def backfill_aabbs(
        self,
        session: AsyncSession,
        model_id: uuid.UUID | str,
    ) -> int:
        """Persist the real per-instance AABB + storey to a sidecar.

        The legacy ``oe_bim_element`` rows are disjoint from the GLB
        placed instances, so writing to them would be meaningless.
        Instead this writes the real, GLB-derived geometry into a
        clash-owned JSON cache next to the GLB
        (``geometry.clash.json``) — ``{node_id: {aabb, storey}}`` — so
        re-runs are fast and the data is inspectable. No DB rows are
        fabricated.

        Args:
            session: Async SQLAlchemy session.
            model_id: ``oe_bim_model.id``.

        Returns:
            Number of real placed elements written to the sidecar.
        """
        from sqlalchemy import select

        from app.modules.bim_hub.models import BIMModel

        model = (await session.execute(select(BIMModel).where(BIMModel.id == model_id))).scalar_one_or_none()
        if model is None:
            return 0
        glb_path = self._resolve_glb_path(model)
        if glb_path is None:
            return 0

        geoms = await self.load(session, model_id)
        if not geoms:
            return 0

        payload = {
            "version": _CACHE_VERSION,
            "model_id": str(model_id),
            "discipline": str(getattr(model, "discipline", None) or "Unassigned"),
            "element_count": len(geoms),
            "storeys": sorted({g.storey for g in geoms.values()}),
            "elements": {nid: {"aabb": list(g.aabb), "storey": g.storey} for nid, g in geoms.items()},
        }
        cache_path = self._cache_path(glb_path)

        def _write() -> None:
            cache_path.write_text(
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)
        logger.info(
            "clash.geometry: wrote %d real elements to %s",
            len(geoms),
            cache_path,
        )
        return len(geoms)


async def backfill_all_models(session: AsyncSession) -> dict[str, int]:
    """Backfill real per-instance geometry for every resolvable model.

    Iterates every ``oe_bim_model`` whose ``geometry.glb`` can be
    resolved and calls :meth:`ClashGeometryProvider.backfill_aabbs`.

    Args:
        session: Async SQLAlchemy session.

    Returns:
        ``{model_id: real_element_count}`` for every processed model.
    """
    from sqlalchemy import select

    from app.modules.bim_hub.models import BIMModel

    provider = ClashGeometryProvider()
    models = list((await session.execute(select(BIMModel))).scalars().all())
    result: dict[str, int] = {}
    for model in models:
        if provider._resolve_glb_path(model) is None:  # noqa: SLF001 — same module
            continue
        try:
            result[str(model.id)] = await provider.backfill_aabbs(session, model.id)
        except Exception as exc:  # noqa: BLE001 — one bad model must not abort the sweep
            logger.exception(
                "clash.geometry: backfill failed for %s: %s",
                model.id,
                exc,
            )
            result[str(model.id)] = 0
    return result


def _cli() -> None:
    """Run the backfill against ``backend/openestimate.db`` and prove it.

    Prints a JSON summary: models processed, total real instance
    elements, the % with a non-degenerate real AABB, and the distinct
    storey count per model.
    """
    import os

    backend_dir = pathlib.Path(__file__).resolve().parents[3]
    db_path = backend_dir / "openestimate.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{db_path.as_posix()}")

    async def _run() -> dict[str, Any]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.modules.bim_hub.models import BIMModel

        engine = create_async_engine(os.environ["DATABASE_URL"])
        maker = async_sessionmaker(engine, expire_on_commit=False)
        provider = ClashGeometryProvider()
        per_model: dict[str, Any] = {}
        total = 0
        total_nondeg = 0
        async with maker() as session:
            models = list(
                (await session.execute(select(BIMModel))).scalars().all(),
            )
            for model in models:
                if provider._resolve_glb_path(model) is None:  # noqa: SLF001
                    continue
                geoms = await provider.load(session, model.id)
                await provider.backfill_aabbs(session, model.id)
                count = len(geoms)
                nondeg = sum(
                    1
                    for g in geoms.values()
                    if (g.aabb[3] > g.aabb[0] or g.aabb[4] > g.aabb[1] or g.aabb[5] > g.aabb[2])
                    and all(math.isfinite(x) for x in g.aabb)
                )
                storeys = sorted({g.storey for g in geoms.values()})
                total += count
                total_nondeg += nondeg
                per_model[str(model.id)] = {
                    "format": str(getattr(model, "model_format", "") or ""),
                    "discipline": str(getattr(model, "discipline", "") or ""),
                    "elements": count,
                    "nondegenerate": nondeg,
                    "pct_nondegenerate": round(100.0 * nondeg / max(count, 1), 2),
                    "distinct_storeys": len(storeys),
                }
        await engine.dispose()
        return {
            "db": str(db_path),
            "models": len(per_model),
            "instance_elements_total": total,
            "instance_elements_nondegenerate": total_nondeg,
            "pct_nondegenerate": round(
                100.0 * total_nondeg / max(total, 1),
                2,
            ),
            "per_model": per_model,
        }

    summary = asyncio.run(_run())
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    _cli()
