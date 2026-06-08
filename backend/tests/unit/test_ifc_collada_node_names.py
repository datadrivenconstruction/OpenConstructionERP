"""Regression: COLLADA node ``name`` must equal the element id, not the label.

The Three.js ColladaLoader sets ``Object3D.name`` from a ``<node>``'s
``name`` attribute (it ignores ``id``).  The BIM viewer then matches each
mesh to a :class:`BIMElement` by that name against ``mesh_ref``.  If the
placeholder generator writes the human label (e.g. ``"Basic Wall:Exterior"``)
into ``name`` instead of the stable id, matching collapses to a positional
nearest-bbox fallback and filtering/grouping stops lining up with the
geometry - the IFC "grouping briefly works then shows the whole model"
symptom reported on 2026-06-08.

``_generate_collada_boxes`` feeds both the IFC text-fallback path and the
Revit box-fallback path, so this single guard protects both.  The real-DAE
Revit path is corrected separately by ``_patch_collada_node_names`` and is
not exercised here.
"""

from __future__ import annotations

import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.bim_hub.ifc_processor import _convert_dae_to_glb, _generate_collada_boxes

_NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}


@pytest.fixture
def temp_dir():
    d = Path(tempfile.mkdtemp(prefix="bim_node_name_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _elements() -> list[dict]:
    """Two elements whose stable id (``mesh_ref``) differs from the label.

    The first carries an IFC GlobalId, the second a numeric Revit ElementId,
    so the assertion covers both id flavours the generator can receive.
    """
    return [
        {
            "mesh_ref": "2W3D5d$JGUID0000000001",
            "name": "Basic Wall:Exterior - 200mm",
            "properties": {"ifc_type": "IFCWALL"},
            "quantities": {"Length": "5.0", "Width": "0.2", "Height": "3.0"},
        },
        {
            "mesh_ref": "1229",
            "name": "Floor:Generic 300mm",
            "properties": {"ifc_type": "IFCSLAB"},
            "quantities": {"Length": "4.0", "Width": "4.0", "Height": "0.3"},
        },
    ]


def test_collada_node_name_equals_element_id_not_label(temp_dir):
    """Every ``<node>`` must expose ``name == id == mesh_ref``."""
    elements = _elements()
    dae_path, _bb = _generate_collada_boxes(elements, temp_dir)

    assert dae_path is not None
    assert dae_path.exists()

    tree = ET.parse(dae_path)
    nodes = tree.findall(".//c:visual_scene/c:node", _NS)
    assert len(nodes) == len(elements)

    expected_ids = {"2W3D5d$JGUID0000000001", "1229"}
    labels = {"Basic Wall:Exterior - 200mm", "Floor:Generic 300mm"}

    seen_ids = set()
    for node in nodes:
        node_id = node.get("id")
        node_name = node.get("name")
        # The decisive invariant the viewer relies on.
        assert node_name == node_id, f"node name {node_name!r} must equal id {node_id!r} for mesh matching"
        # And it must be the stable id, never the human label.
        assert node_name not in labels, f"node name leaked the human label: {node_name!r}"
        seen_ids.add(node_id)

    assert seen_ids == expected_ids


def test_collada_geometry_keeps_human_label(temp_dir):
    """The human label is preserved on ``<geometry name=...>`` for display."""
    elements = _elements()
    dae_path, _bb = _generate_collada_boxes(elements, temp_dir)

    tree = ET.parse(dae_path)
    geom_names = {g.get("name") for g in tree.findall(".//c:library_geometries/c:geometry", _NS)}

    assert "Basic Wall:Exterior - 200mm" in geom_names
    assert "Floor:Generic 300mm" in geom_names


def test_collada_node_id_falls_back_when_mesh_ref_missing(temp_dir):
    """With no ``mesh_ref``/``stable_id`` the node still gets matching id==name."""
    elements = [
        {
            "name": "Anonymous Wall",
            "properties": {"ifc_type": "IFCWALL"},
            "quantities": {"Length": "2.0", "Width": "0.2", "Height": "3.0"},
        },
    ]
    dae_path, _bb = _generate_collada_boxes(elements, temp_dir)

    tree = ET.parse(dae_path)
    nodes = tree.findall(".//c:visual_scene/c:node", _NS)
    assert len(nodes) == 1
    node = nodes[0]
    assert node.get("name") == node.get("id")
    assert node.get("name") != "Anonymous Wall"
    # The generator also writes the resolved id back onto the element.
    assert elements[0]["mesh_ref"] == node.get("id")


# ── GLB fallback: never ship scrambled node names ──────────────────────────


def test_glb_conversion_keeps_node_names(temp_dir):
    """Happy path: a box DAE converts to GLB and bbox matching succeeds."""
    pytest.importorskip("trimesh")
    dae_path, _bb = _generate_collada_boxes(_elements(), temp_dir)

    glb = _convert_dae_to_glb(dae_path, temp_dir)

    # trimesh is present and the boxes have distinct bboxes, so matching
    # works and the GLB is produced.
    assert glb is not None
    assert glb.exists()
    assert glb.suffix == ".glb"


def test_glb_dropped_when_name_patch_throws(temp_dir, monkeypatch):
    """If node-name patching throws, drop the GLB so the DAE (correct names) wins.

    An unpatched GLB carries trimesh's reordered node names, which would push
    the viewer into positional fallback - the exact "grouping reverts to the
    whole model" symptom.  The converter must return ``None`` so the caller
    serves the DAE instead.
    """
    pytest.importorskip("trimesh")
    dae_path, _bb = _generate_collada_boxes(_elements(), temp_dir)

    def _boom(_path):
        raise RuntimeError("bbox parse failed")

    monkeypatch.setattr(ifc_processor, "_dae_element_bboxes", _boom)

    glb = _convert_dae_to_glb(dae_path, temp_dir)

    assert glb is None
    assert not (temp_dir / "geometry.glb").exists()
