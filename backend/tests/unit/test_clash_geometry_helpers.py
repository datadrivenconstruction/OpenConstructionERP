# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-function tests for the clash geometry helpers (no DB, no GLB).

``app.modules.clash.geometry`` only touches the database / bim_hub
*lazily* (inside method bodies), so its small pure helpers import and run
with no ``DATABASE_URL`` and no trimesh scene - they are exercised here
directly on hand-built numpy arrays:

* :func:`_is_template_node` - the COLLADA ``shapeN-lib`` template filter
  that keeps phantom origin geometry out of the element set.
* :func:`_stable_node_key` - the deterministic node-id sort key (numeric
  ids sort numerically and before non-numeric ids).
* :func:`_obb_from_vertices` - the PCA oriented-bounding-box: it must
  enclose every vertex, return an orthonormal frame, and degrade safely
  on an empty cloud.
* :func:`_assign_storeys` - the deterministic Z-band storey clustering:
  empty / single / too-short inputs collapse to one band, a clearly
  bimodal centroid distribution recovers two storeys (lowest == 0).

A silent regression in any of these would corrupt the element set, the
broad-phase ordering, the narrow-phase OBB-SAT reject or the
Level x Level coordination matrix; pinning them keeps the geometry layer
honest without needing a real GLB asset on disk.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.modules.clash.geometry import (
    _STOREY_MIN_FLOOR_TO_FLOOR_M,
    _assign_storeys,
    _is_template_node,
    _obb_from_vertices,
    _stable_node_key,
)

# ── _is_template_node ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("shape3-lib", True),  # canonical COLLADA template
        ("shape5", True),  # bare shape* prefix
        ("Wall-lib", True),  # any "-lib" suffix
        ("SHAPE7-LIB", True),  # case-insensitive
        ("1030049", False),  # real numeric placed-instance id
        ("-123", False),  # signed numeric id is NOT a template
        ("BeamType:Generic", False),  # a real named element
    ],
)
def test_is_template_node(name: str, expected: bool) -> None:
    assert _is_template_node(name) is expected


# ── _stable_node_key ───────────────────────────────────────────────────────


def test_stable_node_key_numeric_sorts_numerically() -> None:
    assert _stable_node_key("100") == (0, 100)
    assert _stable_node_key("99") == (0, 99)
    # Numeric ordering, not lexicographic: 9 < 20 < 100.
    assert sorted(["100", "9", "20"], key=_stable_node_key) == ["9", "20", "100"]


def test_stable_node_key_signed_numeric() -> None:
    # A leading '-' is stripped for the digit test but int() keeps the sign.
    assert _stable_node_key("-5") == (0, -5)


def test_stable_node_key_non_numeric_sorts_after_numeric() -> None:
    assert _stable_node_key("abc")[0] == 1
    # Non-numeric ids sort lexicographically AFTER every numeric id.
    assert sorted(["zeta", "100", "alpha", "9"], key=_stable_node_key) == ["9", "100", "alpha", "zeta"]


# ── _obb_from_vertices ─────────────────────────────────────────────────────

# Unit cube vertices in local coordinates.
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
    dtype=np.float64,
)


def test_obb_empty_cloud_is_safe() -> None:
    center, axes, half = _obb_from_vertices(np.zeros((0, 3)))
    assert np.allclose(center, 0.0)
    assert np.allclose(axes, np.eye(3))
    assert np.allclose(half, 0.0)


def test_obb_axes_are_orthonormal() -> None:
    _center, axes, _half = _obb_from_vertices(_CUBE)
    # Rows form an orthonormal frame: A @ A.T == I.
    assert np.allclose(axes @ axes.T, np.eye(3), atol=1e-9)


def test_obb_encloses_every_vertex() -> None:
    """The box must contain every input vertex (never under-enclose).

    Project each vertex into the box frame and assert it falls inside
    ``|proj - center_in_frame| <= half`` on all three axes.
    """
    center, axes, half = _obb_from_vertices(_CUBE)
    # Project vertices and the centre into the OBB frame.
    proj = _CUBE @ axes.T
    center_proj = center @ axes.T
    local = np.abs(proj - center_proj)
    assert np.all(local <= half + 1e-9), "OBB does not enclose all vertices"


def test_obb_of_unit_cube_has_half_extents_half_metre() -> None:
    center, _axes, half = _obb_from_vertices(_CUBE)
    assert np.allclose(center, [0.5, 0.5, 0.5])
    # A unit cube is symmetric: half-extents are 0.5 on every axis.
    assert np.allclose(np.sort(half), [0.5, 0.5, 0.5])


def test_obb_is_translation_covariant() -> None:
    shifted = _CUBE + np.array([10.0, -5.0, 3.0])
    center, _axes, half = _obb_from_vertices(shifted)
    assert np.allclose(center, [10.5, -4.5, 3.5])
    assert np.allclose(np.sort(half), [0.5, 0.5, 0.5])


# ── _assign_storeys ────────────────────────────────────────────────────────


def test_assign_storeys_empty_and_single() -> None:
    assert _assign_storeys(np.array([])).tolist() == []
    assert _assign_storeys(np.array([5.0])).tolist() == [0]


def test_assign_storeys_too_short_is_single_floor() -> None:
    # A total Z spread below one floor-to-floor cannot hold two storeys.
    z = np.linspace(0.0, _STOREY_MIN_FLOOR_TO_FLOOR_M - 0.5, 20)
    assert set(_assign_storeys(z).tolist()) == {0}


def test_assign_storeys_recovers_two_floors_from_bimodal_density() -> None:
    """A clear two-storey building: dense bands near z=0 and z=4 with a
    sparse valley between -> exactly two levels, lowest == 0."""
    floor0 = np.linspace(0.0, 0.4, 50)
    floor1 = np.linspace(4.0, 4.4, 50)
    valley = np.array([2.0, 2.1])  # sparse mid-band
    z = np.concatenate([floor0, valley, floor1])
    levels = _assign_storeys(z)
    assert sorted(set(levels.tolist())) == [0, 1]
    # Lowest band is level 0; the upper cluster is the top level.
    assert set(levels[:50].tolist()) == {0}
    assert set(levels[-50:].tolist()) == {1}


def test_assign_storeys_recovers_three_floors() -> None:
    floor0 = np.linspace(0.0, 0.4, 40)
    floor1 = np.linspace(4.0, 4.4, 40)
    floor2 = np.linspace(8.0, 8.4, 40)
    z = np.concatenate([floor0, [2.0], floor1, [6.0], floor2])
    levels = _assign_storeys(z)
    assert sorted(set(levels.tolist())) == [0, 1, 2]


def test_assign_storeys_is_deterministic() -> None:
    rng = np.linspace(0.0, 12.0, 200)
    first = _assign_storeys(rng).tolist()
    for _ in range(3):
        assert _assign_storeys(rng).tolist() == first
