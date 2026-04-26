"""DDC adapter extras — canonical-format helpers for the EAC engine (RFC 35).

Pure-Python helpers operating on the canonical BIM element dict produced by
the DDC ``cad2data`` pipeline (the ONLY supported BIM ingestion path per
ADR 002 — no IfcOpenShell, no native IFC). The EAC change-detection engine
calls these helpers on every re-conversion to detect what *actually*
changed between two snapshots of the same model.

Three primitives are exposed:

* :func:`geometry_signature` -- stable, rounding-tolerant fingerprint of an
  element's mesh + bounding box + centroid. Used to answer "did the
  geometry change?" without diffing raw vertex lists.
* :func:`property_set_diff` -- structural diff of two property dicts,
  handling both nested ``Pset_*`` shapes and flat key/value shapes.
* :func:`material_signature` -- SHA-256 over a wall-like element's layered
  build-up, or its primary material name for non-layered elements.

Module-level constants
----------------------
* :data:`SIGNATURE_VERSION` -- bumped when the on-the-wire schema of
  :class:`SignatureV1` changes. Callers can use this to detect that a
  cached signature was produced by an older code version.
* :data:`ROUNDING_TOLERANCE_MM` -- vertices are rounded to this many
  millimetres before hashing. Set conservatively at 0.1 mm so jitter from
  re-exporting the same Revit model does not appear as a real change.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

# Bumped when the on-the-wire schema of SignatureV1 changes.
SIGNATURE_VERSION: str = "1.0"

# Vertices are rounded to this many millimetres before hashing.
# 0.1 mm is well below any meaningful BIM dimensioning precision but well
# above the float32 jitter from a re-exported COLLADA mesh.
ROUNDING_TOLERANCE_MM: float = 0.1

# Number of decimal places used when rounding metre-valued vertices.
# 4 decimals = 0.0001 m = 0.1 mm — matches ROUNDING_TOLERANCE_MM.
_VERTEX_DECIMALS: int = 4


@dataclass(frozen=True)
class SignatureV1:
    """Stable geometric fingerprint of one canonical BIM element.

    All numeric fields are in SI units (metres, square metres, cubic metres).
    The ``mesh_sha256`` is computed over the *deduplicated*, *sorted*,
    *rounded* vertex list so it is idempotent across re-conversions.
    """

    mesh_sha256: str
    vertex_count: int
    volume: float
    surface_area: float
    centroid: tuple[float, float, float]
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    version: str = SIGNATURE_VERSION


@dataclass(frozen=True)
class PropertyChange:
    """One row in a property-set diff.

    ``change_type`` is one of ``"added"``, ``"removed"``, ``"modified"``.
    ``left_value`` / ``right_value`` carry the value on each side; for
    ``"added"`` ``left_value`` is ``None``, for ``"removed"`` ``right_value``
    is ``None``.
    """

    pset_name: str
    property_name: str
    change_type: Literal["added", "removed", "modified"]
    left_value: Any | None = None
    right_value: Any | None = None
    # Marker so dataclass.field is referenced and ruff doesn't trim the import.
    _reserved: tuple[()] = field(default=(), repr=False, compare=False)


# ---------------------------------------------------------------------------
# Geometry signature
# ---------------------------------------------------------------------------


def _coerce_xyz(value: Any) -> tuple[float, float, float] | None:
    """Best-effort conversion of an arbitrary point-like value to a 3-tuple.

    Accepts list/tuple of three numbers, dicts with ``x``/``y``/``z`` keys,
    or ``None``. Returns ``None`` if the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        try:
            return (float(value["x"]), float(value["y"]), float(value["z"]))
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None
    return None


def _round_vertex(v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Round a vertex to ``_VERTEX_DECIMALS`` to absorb sub-mm jitter."""
    return (
        round(v[0], _VERTEX_DECIMALS),
        round(v[1], _VERTEX_DECIMALS),
        round(v[2], _VERTEX_DECIMALS),
    )


def _extract_vertices(geometry: dict[str, Any]) -> list[tuple[float, float, float]]:
    """Extract vertex 3-tuples from a canonical-format ``geometry`` dict.

    The canonical format does not mandate raw vertices on every element
    (extrusions encode ``length``/``height``/``thickness`` instead). We
    accept either:

    * an explicit ``vertices`` key (list of [x, y, z] or {x, y, z});
    * a ``mesh.vertices`` key (same shapes, nested under ``mesh``).

    Returns ``[]`` if no vertices are found.
    """
    candidates: list[Any] = []
    if isinstance(geometry.get("vertices"), list):
        candidates = geometry["vertices"]
    elif isinstance(geometry.get("mesh"), dict) and isinstance(
        geometry["mesh"].get("vertices"), list
    ):
        candidates = geometry["mesh"]["vertices"]

    out: list[tuple[float, float, float]] = []
    for c in candidates:
        xyz = _coerce_xyz(c)
        if xyz is not None:
            out.append(xyz)
    return out


def _empty_signature(element_id: str) -> SignatureV1:
    """Build a fallback signature for an element with no geometry block.

    The mesh hash is the SHA-256 of the element id so two different
    geometry-less elements still hash to different signatures.
    """
    fallback_hash = hashlib.sha256(element_id.encode("utf-8")).hexdigest()
    return SignatureV1(
        mesh_sha256=fallback_hash,
        vertex_count=0,
        volume=0.0,
        surface_area=0.0,
        centroid=(0.0, 0.0, 0.0),
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(0.0, 0.0, 0.0),
    )


def _safe_float(value: Any) -> float:
    """Coerce a possibly-stringy numeric to ``float``, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def geometry_signature(element: dict[str, Any]) -> SignatureV1:
    """Compute a stable geometric fingerprint of a canonical BIM element.

    The returned :class:`SignatureV1` is idempotent across re-conversions
    of the same source model: rounding to ``_VERTEX_DECIMALS`` decimals
    absorbs sub-mm vertex jitter, and the vertex list is deduplicated and
    sorted before hashing so re-ordered indices do not appear as a change.

    Args:
        element: A canonical-format BIM element dict. Expected keys:
            ``id``, ``geometry``, ``quantities``. Missing keys fall back
            to neutral values (zeros, empty strings).

    Returns:
        A :class:`SignatureV1` describing the element's mesh, volume,
        surface area, centroid and bounding box.
    """
    element_id = str(element.get("id") or "")
    geometry = element.get("geometry")

    if not isinstance(geometry, dict):
        return _empty_signature(element_id)

    vertices = _extract_vertices(geometry)

    # Round → dedupe → sort. This is the key step for idempotency: two
    # re-exports of the same model with sub-mm float drift produce the
    # same hash.
    rounded = [_round_vertex(v) for v in vertices]
    unique_sorted = sorted(set(rounded))

    if unique_sorted:
        # Hash the textual representation — explicit, deterministic, and
        # avoids float-binary-format surprises across platforms.
        vertex_blob = "\n".join(f"{x:.4f},{y:.4f},{z:.4f}" for x, y, z in unique_sorted)
        mesh_hash = hashlib.sha256(vertex_blob.encode("utf-8")).hexdigest()
    else:
        # No mesh vertices available — anchor the hash on the element id
        # so different geometry-less elements still hash distinctly.
        mesh_hash = hashlib.sha256(element_id.encode("utf-8")).hexdigest()

    quantities = element.get("quantities") or {}
    volume = _safe_float(
        quantities.get("volume") if isinstance(quantities, dict) else None
    ) or _safe_float(geometry.get("volume_m3"))
    surface_area = _safe_float(
        quantities.get("area") if isinstance(quantities, dict) else None
    ) or _safe_float(geometry.get("area_m2"))

    # Bounding box: prefer explicit geometry.bbox, else derive from vertices.
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    bbox = geometry.get("bbox") if isinstance(geometry.get("bbox"), dict) else None
    explicit_min = _coerce_xyz(bbox.get("min")) if bbox else None
    explicit_max = _coerce_xyz(bbox.get("max")) if bbox else None

    if explicit_min is not None and explicit_max is not None:
        bbox_min, bbox_max = explicit_min, explicit_max
    elif unique_sorted:
        xs = [v[0] for v in unique_sorted]
        ys = [v[1] for v in unique_sorted]
        zs = [v[2] for v in unique_sorted]
        bbox_min = (min(xs), min(ys), min(zs))
        bbox_max = (max(xs), max(ys), max(zs))
    else:
        bbox_min = (0.0, 0.0, 0.0)
        bbox_max = (0.0, 0.0, 0.0)

    # Centroid: explicit if provided, else arithmetic mean of unique vertices.
    explicit_centroid = _coerce_xyz(geometry.get("centroid"))
    if explicit_centroid is not None:
        centroid = explicit_centroid
    elif unique_sorted:
        n = len(unique_sorted)
        centroid = (
            sum(v[0] for v in unique_sorted) / n,
            sum(v[1] for v in unique_sorted) / n,
            sum(v[2] for v in unique_sorted) / n,
        )
    else:
        centroid = (0.0, 0.0, 0.0)

    return SignatureV1(
        mesh_sha256=mesh_hash,
        vertex_count=len(unique_sorted),
        volume=volume,
        surface_area=surface_area,
        centroid=centroid,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
    )


# ---------------------------------------------------------------------------
# Property-set diff
# ---------------------------------------------------------------------------


def _normalise_properties(props: dict[str, Any] | None) -> dict[tuple[str, str], Any]:
    """Flatten a properties dict into ``{(pset, prop): value}`` form.

    Handles both shapes seen in DDC output:

    * Nested:  ``{"Pset_WallCommon": {"FireRating": "F90"}}``
    * Flat:    ``{"FireRating": "F90"}``

    Flat keys are bucketed into a synthetic ``""`` pset so callers see a
    stable key shape regardless of source.
    """
    if not props:
        return {}
    out: dict[tuple[str, str], Any] = {}
    for key, value in props.items():
        if isinstance(value, dict):
            # Nested pset: {pset_name: {prop_name: value}}.
            for sub_name, sub_value in value.items():
                out[(str(key), str(sub_name))] = sub_value
        else:
            # Flat property — synthetic pset name.
            out[("", str(key))] = value
    return out


def property_set_diff(
    left: dict[str, Any],
    right: dict[str, Any],
) -> list[PropertyChange]:
    """Diff two canonical-format ``properties`` dicts.

    Both inputs may use either the nested ``{Pset: {Prop: Value}}`` shape
    or a flat ``{Prop: Value}`` shape — they are normalised before
    comparison. A property present on one side and absent on the other
    produces an ``"added"`` or ``"removed"`` change; a property present on
    both sides with different values produces a ``"modified"`` change.

    Args:
        left: The "before" property dict.
        right: The "after" property dict.

    Returns:
        A list of :class:`PropertyChange` rows, sorted by
        ``(pset_name, property_name)`` for stable output.
    """
    left_flat = _normalise_properties(left)
    right_flat = _normalise_properties(right)

    all_keys = set(left_flat) | set(right_flat)
    changes: list[PropertyChange] = []

    for key in all_keys:
        pset_name, prop_name = key
        in_left = key in left_flat
        in_right = key in right_flat

        if in_left and not in_right:
            changes.append(
                PropertyChange(
                    pset_name=pset_name,
                    property_name=prop_name,
                    change_type="removed",
                    left_value=left_flat[key],
                    right_value=None,
                )
            )
        elif in_right and not in_left:
            changes.append(
                PropertyChange(
                    pset_name=pset_name,
                    property_name=prop_name,
                    change_type="added",
                    left_value=None,
                    right_value=right_flat[key],
                )
            )
        else:
            lv = left_flat[key]
            rv = right_flat[key]
            if lv != rv:
                changes.append(
                    PropertyChange(
                        pset_name=pset_name,
                        property_name=prop_name,
                        change_type="modified",
                        left_value=lv,
                        right_value=rv,
                    )
                )

    changes.sort(key=lambda c: (c.pset_name, c.property_name))
    return changes


# ---------------------------------------------------------------------------
# Material signature
# ---------------------------------------------------------------------------


def _extract_material_layers(
    element: dict[str, Any],
) -> list[tuple[str, float]]:
    """Pull ``[(layer_material, thickness_m), ...]`` out of an element.

    The canonical format places layered build-ups under either
    ``properties.material_layers`` (preferred) or ``material_layers`` at
    the element root. Each layer is a dict with ``material``/``thickness``
    keys (or ``name``/``thickness_m`` aliases). Returns ``[]`` if no
    layers are found.
    """
    candidates: Any = None
    properties = element.get("properties")
    if isinstance(properties, dict):
        candidates = properties.get("material_layers")
    if not isinstance(candidates, list):
        candidates = element.get("material_layers")
    if not isinstance(candidates, list):
        return []

    layers: list[tuple[str, float]] = []
    for layer in candidates:
        if not isinstance(layer, dict):
            continue
        material = layer.get("material") or layer.get("name") or ""
        thickness = layer.get("thickness")
        if thickness is None:
            thickness = layer.get("thickness_m")
        layers.append((str(material), _safe_float(thickness)))
    return layers


def _extract_primary_material(element: dict[str, Any]) -> str:
    """Return the primary material name for non-layered elements.

    Looks first at ``element.material``, then ``properties.material``,
    then ``properties.Material`` (capitalised). Empty string if absent.
    """
    direct = element.get("material")
    if isinstance(direct, str) and direct:
        return direct
    properties = element.get("properties")
    if isinstance(properties, dict):
        for key in ("material", "Material"):
            value = properties.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def material_signature(element: dict[str, Any]) -> str:
    """Compute a stable SHA-256 fingerprint over an element's material(s).

    For a layered element (typically a wall, slab, or roof), the hash
    incorporates the ordered layer build-up: ``(name, thickness)`` pairs
    in their declared order. Reordering layers therefore yields a
    different signature — physically, a 24 cm concrete + 12 cm insulation
    wall is *not* the same as 12 cm insulation + 24 cm concrete.

    For a non-layered element (door, window, fixture, ...), the hash is
    simply ``sha256(material_name)``.

    Args:
        element: A canonical-format BIM element dict.

    Returns:
        A lowercase hex SHA-256 digest. Empty / missing materials still
        produce a deterministic digest (the SHA-256 of the empty string).
    """
    layers = _extract_material_layers(element)
    if layers:
        # Format: name|thickness\nname|thickness ... — newline-delimited
        # so adjacent layers cannot collide via concatenation.
        blob_parts = [f"{name}|{thickness:.6f}" for name, thickness in layers]
        # Include the primary/wrapper material name when present so a
        # rename of the assembly without changing layers still flips the
        # signature. Falls back to the empty string.
        primary = _extract_primary_material(element)
        blob = primary + "\n" + "\n".join(blob_parts)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    primary = _extract_primary_material(element)
    return hashlib.sha256(primary.encode("utf-8")).hexdigest()


__all__ = [
    "ROUNDING_TOLERANCE_MM",
    "SIGNATURE_VERSION",
    "PropertyChange",
    "SignatureV1",
    "geometry_signature",
    "material_signature",
    "property_set_diff",
]
