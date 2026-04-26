"""Unit tests for ``app.modules.bim_hub.ddc_extras`` (RFC 34 W0.2).

The tests exercise the three public helpers — :func:`geometry_signature`,
:func:`property_set_diff`, :func:`material_signature` — using synthetic
canonical-format dicts. No real BIM files are loaded.
"""

from __future__ import annotations

import hashlib

import pytest

from app.modules.bim_hub.ddc_extras import (
    ROUNDING_TOLERANCE_MM,
    SIGNATURE_VERSION,
    PropertyChange,
    SignatureV1,
    geometry_signature,
    material_signature,
    property_set_diff,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _wall_element(vertices: list[list[float]]) -> dict[str, object]:
    """Build a minimal canonical wall element with the given vertex list."""
    return {
        "id": "elem-wall-001",
        "category": "wall",
        "geometry": {
            "type": "mesh",
            "vertices": vertices,
        },
        "quantities": {
            "area": 37.5,
            "volume": 9.0,
            "length": 12.5,
        },
        "properties": {
            "Pset_WallCommon": {
                "FireRating": "F90",
                "IsExternal": True,
            }
        },
    }


# ---------------------------------------------------------------------------
# geometry_signature
# ---------------------------------------------------------------------------


def test_geometry_signature_idempotent() -> None:
    """Same element twice must hash to the same signature."""
    elem = _wall_element(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
    )

    sig_a = geometry_signature(elem)
    sig_b = geometry_signature(elem)

    assert isinstance(sig_a, SignatureV1)
    assert sig_a == sig_b
    assert sig_a.version == SIGNATURE_VERSION


def test_geometry_signature_tolerant_to_micro_rounding() -> None:
    """Sub-tolerance jitter must not change the signature.

    Per ``ROUNDING_TOLERANCE_MM`` (= 0.1 mm = 4 decimal places in metres),
    two vertices that differ only at the 5th decimal place must collapse
    onto the same rounded grid point and therefore produce the same hash.
    """
    assert ROUNDING_TOLERANCE_MM == 0.1

    elem_a = _wall_element([[1.00001, 2.00001, 3.00001]])
    elem_b = _wall_element([[1.00002, 2.00002, 3.00002]])

    sig_a = geometry_signature(elem_a)
    sig_b = geometry_signature(elem_b)

    # Both vertex coordinates round to (1.0000, 2.0000, 3.0000) so the
    # mesh fingerprint must be identical.
    assert sig_a.mesh_sha256 == sig_b.mesh_sha256
    assert sig_a.vertex_count == sig_b.vertex_count == 1


def test_geometry_signature_changes_on_real_change() -> None:
    """Moving a vertex by 1 mm (above tolerance) must change the hash."""
    elem_a = _wall_element([[0.0, 0.0, 0.0]])
    elem_b = _wall_element([[0.0, 0.0, 0.001]])  # 1 mm Z shift

    sig_a = geometry_signature(elem_a)
    sig_b = geometry_signature(elem_b)

    assert sig_a.mesh_sha256 != sig_b.mesh_sha256


def test_geometry_signature_missing_geometry() -> None:
    """An element without a ``geometry`` key falls back to id-based hash."""
    elem = {"id": "elem-no-geom-42", "properties": {}}

    sig = geometry_signature(elem)

    expected_hash = hashlib.sha256(b"elem-no-geom-42").hexdigest()
    assert sig.mesh_sha256 == expected_hash
    assert sig.vertex_count == 0
    assert sig.volume == 0.0
    assert sig.surface_area == 0.0
    assert sig.centroid == (0.0, 0.0, 0.0)
    assert sig.bbox_min == (0.0, 0.0, 0.0)
    assert sig.bbox_max == (0.0, 0.0, 0.0)
    assert sig.version == SIGNATURE_VERSION


# ---------------------------------------------------------------------------
# property_set_diff
# ---------------------------------------------------------------------------


def test_property_set_diff_added_removed_modified() -> None:
    """One added, one removed, one modified -> 3 PropertyChange rows."""
    left = {
        "Pset_WallCommon": {
            "FireRating": "F90",  # modified -> F120
            "IsExternal": True,   # removed
        }
    }
    right = {
        "Pset_WallCommon": {
            "FireRating": "F120",   # modified
            "AcousticRating": "DnT,w 53 dB",  # added
        }
    }

    changes = property_set_diff(left, right)
    by_type = {c.change_type: c for c in changes}

    assert len(changes) == 3
    assert set(by_type) == {"added", "removed", "modified"}

    assert by_type["modified"].property_name == "FireRating"
    assert by_type["modified"].left_value == "F90"
    assert by_type["modified"].right_value == "F120"

    assert by_type["removed"].property_name == "IsExternal"
    assert by_type["removed"].left_value is True
    assert by_type["removed"].right_value is None

    assert by_type["added"].property_name == "AcousticRating"
    assert by_type["added"].left_value is None
    assert by_type["added"].right_value == "DnT,w 53 dB"


def test_property_set_diff_handles_both_nested_and_flat() -> None:
    """Nested ``{Pset: {Prop: V}}`` and flat ``{Prop: V}`` shapes coexist."""
    nested_left = {"Pset_WallCommon": {"FireRating": "F90"}}
    flat_right = {"FireRating": "F90"}

    # The two sides use different containers, but the property *value*
    # is identical, so the diff must surface this as one removed +
    # one added (they live in different psets after normalisation),
    # not as zero changes.
    changes = property_set_diff(nested_left, flat_right)
    types = sorted(c.change_type for c in changes)
    assert types == ["added", "removed"]

    # And in the symmetric case where both are flat with the same value,
    # the diff is empty.
    changes_same = property_set_diff(flat_right, dict(flat_right))
    assert changes_same == []

    # And mixed: nested L = nested R with same content -> empty.
    changes_nested_same = property_set_diff(nested_left, dict(nested_left))
    assert changes_nested_same == []


def test_property_set_diff_stable_ordering() -> None:
    """Same input -> same row order, every time."""
    left = {
        "Pset_Z": {"prop_b": 1, "prop_a": 2},
        "Pset_A": {"prop_z": 3},
    }
    right: dict[str, object] = {}  # everything removed

    out_a = property_set_diff(left, right)
    out_b = property_set_diff(left, right)

    assert out_a == out_b
    keys = [(c.pset_name, c.property_name) for c in out_a]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# material_signature
# ---------------------------------------------------------------------------


def _layered_wall(layers: list[tuple[str, float]]) -> dict[str, object]:
    """Build a wall-like element with the given material build-up."""
    return {
        "id": "elem-wall-layered",
        "category": "wall",
        "properties": {
            "material": "ExteriorWallType_A",
            "material_layers": [
                {"material": name, "thickness": thickness}
                for name, thickness in layers
            ],
        },
    }


def test_material_signature_layered_wall() -> None:
    """Same layers in same order -> same signature; reordered -> different."""
    layers_normal = [
        ("Concrete_C30_37", 0.24),
        ("Insulation_PUR", 0.12),
        ("Plaster_Lime", 0.015),
    ]
    layers_reversed = list(reversed(layers_normal))

    sig_a = material_signature(_layered_wall(layers_normal))
    sig_b = material_signature(_layered_wall(layers_normal))
    sig_c = material_signature(_layered_wall(layers_reversed))

    assert sig_a == sig_b
    assert sig_a != sig_c
    # Lowercase hex of the right length.
    assert len(sig_a) == 64
    assert sig_a == sig_a.lower()


def test_material_signature_simple_element() -> None:
    """A non-layered element hashes its primary material name only."""
    door = {
        "id": "elem-door-001",
        "category": "door",
        "properties": {"material": "Oak_Solid"},
    }

    sig = material_signature(door)
    expected = hashlib.sha256(b"Oak_Solid").hexdigest()

    assert sig == expected


# ---------------------------------------------------------------------------
# Trivial sanity check on dataclass surface area
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change_type", ["added", "removed", "modified"]
)
def test_property_change_dataclass_surface(change_type: str) -> None:
    """PropertyChange instances are frozen dataclasses with the right fields."""
    pc = PropertyChange(
        pset_name="Pset_X",
        property_name="prop",
        change_type=change_type,  # type: ignore[arg-type]
        left_value=1,
        right_value=2,
    )
    assert pc.pset_name == "Pset_X"
    assert pc.property_name == "prop"
    assert pc.change_type == change_type
    with pytest.raises((AttributeError, Exception)):
        pc.pset_name = "mutated"  # type: ignore[misc]
