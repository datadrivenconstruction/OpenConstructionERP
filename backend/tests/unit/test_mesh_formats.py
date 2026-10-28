# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the geometry-only mesh classifier used by the BIM upload guards.

Pure, DB-free: exercises ``app.modules.bim_hub.mesh_formats`` in isolation so
the friendly rejection behaviour is pinned without spinning up the app.
"""

from __future__ import annotations

import pytest

from app.modules.bim_hub.mesh_formats import (
    MESH_GEOMETRY_EXTENSIONS,
    is_mesh_geometry_ext,
    mesh_upload_hint,
)


@pytest.mark.parametrize(
    "ext",
    [".obj", ".stl", ".ply", ".dae", ".glb", ".gltf", ".fbx", ".3ds", ".lwo", ".usd", ".usdz"],
)
def test_known_mesh_extensions_recognised(ext: str) -> None:
    assert is_mesh_geometry_ext(ext) is True


def test_extension_matching_is_case_and_dot_insensitive() -> None:
    assert is_mesh_geometry_ext("OBJ") is True
    assert is_mesh_geometry_ext(".GLB") is True
    assert is_mesh_geometry_ext("stl") is True


@pytest.mark.parametrize("ext", [".ifc", ".rvt", ".dwg", ".dgn", ".pdf", ".txt", "", None])
def test_non_mesh_and_cad_extensions_are_not_mesh(ext: str | None) -> None:
    # The convertible CAD/BIM formats must NOT be classified as geometry-only
    # mesh, or the guard would wrongly reject a real IFC/RVT/DWG upload.
    assert is_mesh_geometry_ext(ext or "") is False


def test_hint_names_the_format_and_points_to_bim_hub() -> None:
    msg = mesh_upload_hint(".obj", "tower.obj")
    assert "tower.obj" in msg
    assert ".obj" in msg
    assert "BIM Hub" in msg
    # Honest messaging: geometry only, no server conversion.
    assert "geometry" in msg.lower()
    assert "convert" in msg.lower()


def test_hint_without_filename_is_still_readable() -> None:
    msg = mesh_upload_hint(".stl")
    assert msg.startswith("This file ")
    assert ".stl" in msg


def test_cad_formats_excluded_from_mesh_set() -> None:
    # Guard against future drift: the raw CAD/BIM formats that DO convert must
    # never leak into the mesh set.
    for cad in (".ifc", ".rvt", ".dwg", ".dgn"):
        assert cad not in MESH_GEOMETRY_EXTENSIONS
