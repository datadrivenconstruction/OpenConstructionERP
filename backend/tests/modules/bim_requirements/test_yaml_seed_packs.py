"""Integration check: every seed YAML pack in data/bim_rules/ must
load AND dry-run against a small synthetic element set without raising.

This is the "real-world smoke test" that catches schema drift between
the YAML files and the loader/runtime in code review.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.bim_requirements.rule_runtime import evaluate_rule_pack
from app.modules.bim_requirements.yaml_loader import load_rule_pack

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_DIR = REPO_ROOT / "data" / "bim_rules"


# A representative element set that covers every selector in the seed
# packs at least once. Each element is a plain dict — that is the only
# contract the rule_runtime requires.
SYNTHETIC_ELEMENTS = [
    # Compliant internal wall: has DIN 276 code, FireRating, IsExternal=false.
    {
        "id": "w-int-ok",
        "ifc_class": "IfcWall",
        "classification": {"din276": "330"},
        "properties": {"IsExternal": False, "FireRating": "F90"},
    },
    # Internal wall missing FireRating.
    {
        "id": "w-int-bad",
        "ifc_class": "IfcWall",
        "classification": {"din276": "330"},
        "properties": {"IsExternal": False},
    },
    # External wall — should be ignored by the fire-rating rule.
    {
        "id": "w-ext",
        "ifc_class": "IfcWall",
        "classification": {"din276": "330"},
        "properties": {"IsExternal": True},
    },
    # Element without a DIN 276 code (completeness check should fail).
    {
        "id": "elem-unclassified",
        "ifc_class": "IfcElement",
        "classification": {},
        "properties": {},
    },
    # Corridor with sub-spec width.
    {
        "id": "corr-bad",
        "ifc_class": "IfcSpace",
        "properties": {"SpaceType": "Corridor", "Width": 1.2, "Name": "OR.02.001"},
    },
    # Corridor with compliant width.
    {
        "id": "corr-ok",
        "ifc_class": "IfcSpace",
        "properties": {"SpaceType": "Corridor", "Width": 1.6, "Name": "OR.02.002"},
    },
    # Door on accessible route — sub-spec width.
    {
        "id": "door-bad",
        "ifc_class": "IfcDoor",
        "properties": {"OnAccessibleRoute": True, "ClearWidth": 0.85},
    },
    # Pipe-segment with insufficient clearance to nearby beam.
    {
        "id": "pipe-bad",
        "ifc_class": "IfcPipeSegment",
        "properties": {"ClearanceToStructure": 0.05},
    },
    # The beam the pipe is too close to.
    {
        "id": "beam-1",
        "ifc_class": "IfcBeam",
    },
    # Space with bad name.
    {
        "id": "space-bad-name",
        "ifc_class": "IfcSpace",
        "properties": {"Name": "kitchen"},
    },
    # ── LOD 300 / LOD 400 / COBie fixtures ───────────────────────────────
    # LOD300-compliant wall (all properties + plausible dimensions).
    {
        "id": "wall-lod300-ok",
        "ifc_class": "IfcWall",
        "properties": {
            "Material": "Concrete C30/37",
            "Width": 0.24,
            "Height": 3.0,
            "Length": 5.0,
            "IsExternal": False,
            "IsFireRated": True,
            "FireRating": "F90",
            "BBoxHeight": 3.001,
            "HeightDeltaMM": 1.0,
        },
    },
    # LOD300 wall missing Material.
    {
        "id": "wall-lod300-bad",
        "ifc_class": "IfcWall",
        "properties": {"Width": 0.2, "IsExternal": True, "IsFireRated": False},
    },
    # LOD300/400 door — fully compliant + hosted by wall.
    {
        "id": "door-lod400-ok",
        "ifc_class": "IfcDoor",
        "properties": {
            "Material": "Steel",
            "Width": 1.0,
            "Height": 2.1,
            "OperationType": "SINGLE_SWING_LEFT",
            "HostElementClass": "IfcWall",
        },
    },
    # Door bad: hosted by Slab instead of Wall.
    {
        "id": "door-bad-host",
        "ifc_class": "IfcDoor",
        "properties": {
            "Material": "Steel",
            "Width": 0.9,
            "OperationType": "SINGLE_SWING_LEFT",
            "HostElementClass": "IfcSlab",
        },
    },
    # Window with all LOD300 fields.
    {
        "id": "window-lod300-ok",
        "ifc_class": "IfcWindow",
        "properties": {
            "Material": "Aluminium",
            "Width": 1.5,
            "Height": 1.2,
            "GlazingAreaFraction": 0.75,
            "HostElementClass": "IfcWall",
        },
    },
    # Column with LOD300 fields.
    {
        "id": "column-lod300-ok",
        "ifc_class": "IfcColumn",
        "properties": {
            "Material": "Steel",
            "CrossSectionArea": 0.045,
            "Length": 3.0,
            "CrossSection": "HEB200",
        },
    },
    # Beam with LOD300 fields.
    {
        "id": "beam-lod300-ok",
        "ifc_class": "IfcBeam",
        "properties": {
            "Material": "Steel",
            "Span": 6.5,
            "CrossSection": "IPE300",
        },
    },
    # MEP element flagged as terminal that traces to source.
    {
        "id": "mep-terminal-ok",
        "ifc_class": "IfcDistributionElement",
        "properties": {
            "IsTerminal": True,
            "HasSource": True,
            "MaintenanceFrequency": "P1Y",
        },
    },
    # MEP element where HasSource=false (LOD400 violation).
    {
        "id": "mep-terminal-bad",
        "ifc_class": "IfcDistributionElement",
        "properties": {
            "IsTerminal": True,
            "HasSource": False,
            "MaintenanceFrequency": "P1Y",
        },
    },
    # Type-bearing element fully populated (LOD400 / COBie).
    {
        "id": "type-elem-ok",
        "ifc_class": "IfcElement",
        "properties": {
            "IsTypeBearing": True,
            "ManufacturerName": "ACME Doors GmbH",
            "ProductCode": "AD-9000",
            "ProductionYear": 2024,
            "HasWarranty": True,
            "StartOfWarranty": "2024-09-01",
            "WarrantyDurationYears": 5,
        },
    },
    # Type-bearing element missing manufacturer.
    {
        "id": "type-elem-bad",
        "ifc_class": "IfcElement",
        "properties": {"IsTypeBearing": True},
    },
    # COBie space, fully compliant (4-level spatial structure).
    {
        "id": "cobie-space-ok",
        "ifc_class": "IfcSpace",
        "properties": {
            "SpaceName": "OR.02.001",
            "SpaceLongName": "Operating Room 1",
            "SpaceUsage": "Surgical",
            "OccupancyType": "I-2",
            "NetFloorArea": 42.5,
            "Area": 42.5,
            "Volume": 145.0,
            "SpatialDepth": 4,
            "Name": "OR.02.001",
        },
    },
    # COBie space with bad spatial depth (flat structure).
    {
        "id": "cobie-space-flat",
        "ifc_class": "IfcSpace",
        "properties": {
            "SpaceName": "Lobby",
            "SpatialDepth": 2,
            "NetFloorArea": 80.0,
            "Name": "LB.00.001",
        },
    },
    # COBie type, fully populated.
    {
        "id": "cobie-type-ok",
        "ifc_class": "IfcTypeObject",
        "properties": {
            "Manufacturer": "Otis Elevators",
            "ModelLabel": "Gen2",
            "ProductionYear": 2024,
            "AssetType": "Fixed",
            "WarrantyDuration": 24,
            "ExpectedLife": 25,
        },
    },
    # COBie type missing manufacturer.
    {
        "id": "cobie-type-bad",
        "ifc_class": "IfcTypeObject",
        "properties": {
            "ModelLabel": "MysteryUnit",
            "AssetType": "Movable",
            "ExpectedLife": 10,
        },
    },
    # COBie component, serialised + installed.
    {
        "id": "cobie-comp-ok",
        "ifc_class": "IfcElement",
        "properties": {
            "IsCOBieComponent": True,
            "IsSerialised": True,
            "SerialNumber": "SN-100-200",
            "InstallationDate": "2024-11-15",
            "HasWarranty": True,
            "WarrantyStartDate": "2024-11-15",
        },
    },
    # COBie component missing SerialNumber when serialised.
    {
        "id": "cobie-comp-bad",
        "ifc_class": "IfcElement",
        "properties": {
            "IsCOBieComponent": True,
            "IsSerialised": True,
        },
    },
]


@pytest.mark.parametrize(
    "pack_filename",
    [
        "din_276_kg_completeness.yaml",
        "clearance_corridor_door.yaml",
        "fire_compartment_property.yaml",
        "mep_clearance.yaml",
        "room_naming_convention.yaml",
        "lod300_design_development.yaml",
        "lod400_construction.yaml",
        "cobie_handover.yaml",
    ],
)
def test_seed_pack_loads_and_runs(pack_filename: str) -> None:
    """Each seed pack must parse and produce a valid PackResult."""
    pack = load_rule_pack(SEED_DIR / pack_filename)
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)

    assert result.pack_id == pack.pack.id
    assert result.total_elements == len(SYNTHETIC_ELEMENTS)
    # Every element ends up in exactly one of the three buckets.
    assert result.passed + result.failed + result.not_applicable == len(SYNTHETIC_ELEMENTS)
    # Every result row carries a real element id from the synthetic set.
    ids = {e["id"] for e in SYNTHETIC_ELEMENTS}
    for row in result.results:
        assert row.element_id in ids


def test_din276_pack_flags_unclassified_element() -> None:
    """The DIN 276 completeness pack must mark the unclassified element as failing."""
    pack = load_rule_pack(SEED_DIR / "din_276_kg_completeness.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    failing_ids = {r.element_id for r in result.results if not r.passed}
    assert "elem-unclassified" in failing_ids


def test_corridor_pack_flags_narrow_corridor() -> None:
    """The corridor pack must fail corr-bad and pass corr-ok."""
    pack = load_rule_pack(SEED_DIR / "clearance_corridor_door.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    outcomes = {(r.rule_id, r.element_id): r.passed for r in result.results}
    assert outcomes.get(("corridor_minimum_width", "corr-bad")) is False
    assert outcomes.get(("corridor_minimum_width", "corr-ok")) is True
    # The door rule should have flagged the door with ClearWidth 0.85.
    assert outcomes.get(("door_clear_width", "door-bad")) is False


def test_fire_pack_ignores_external_walls() -> None:
    """The fire-rating pack should treat external walls as not_applicable."""
    pack = load_rule_pack(SEED_DIR / "fire_compartment_property.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    rule_ids_for_ext = {r.rule_id for r in result.results if r.element_id == "w-ext"}
    # The external wall must not appear under the internal-wall fire rules.
    assert "internal_wall_fire_rating_present" not in rule_ids_for_ext
    assert "internal_wall_fire_rating_valid" not in rule_ids_for_ext


def test_mep_pack_flags_pipe_close_to_beam() -> None:
    """The MEP clearance pack must fail pipe-bad when beam-1 is in the set."""
    pack = load_rule_pack(SEED_DIR / "mep_clearance.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    pipe_outcomes = [r for r in result.results if r.element_id == "pipe-bad"]
    assert pipe_outcomes
    assert all(not r.passed for r in pipe_outcomes)


def test_room_naming_pack_flags_lowercase_kitchen() -> None:
    """The room-naming pack must fail 'kitchen' but pass 'OR.02.001'."""
    pack = load_rule_pack(SEED_DIR / "room_naming_convention.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    outcomes = {r.element_id: r.passed for r in result.results}
    assert outcomes.get("space-bad-name") is False
    assert outcomes.get("corr-ok") is True


def test_lod300_pack_distinguishes_compliant_vs_missing_material() -> None:
    """LOD300 pack: wall with full property block passes; wall missing
    Material is flagged."""
    pack = load_rule_pack(SEED_DIR / "lod300_design_development.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    material_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "lod300_wall_material_present"}
    assert material_outcomes.get("wall-lod300-ok") is True
    assert material_outcomes.get("wall-lod300-bad") is False


def test_lod300_pack_validates_door_operation_type_vocabulary() -> None:
    """LOD300 door rule must accept the Pset_DoorCommon enumeration."""
    pack = load_rule_pack(SEED_DIR / "lod300_design_development.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    op_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "lod300_door_pset_common"}
    assert op_outcomes.get("door-lod400-ok") is True


def test_lod400_pack_flags_terminal_without_source() -> None:
    """LOD 400 connectivity rule must fail terminals where HasSource=false."""
    pack = load_rule_pack(SEED_DIR / "lod400_construction.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    source_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "lod400_mep_traces_to_source"}
    assert source_outcomes.get("mep-terminal-ok") is True
    assert source_outcomes.get("mep-terminal-bad") is False


def test_lod400_pack_requires_manufacturer_on_type_bearing_element() -> None:
    """LOD 400 manufacturer rule must fail type-bearing elements with no
    ManufacturerName."""
    pack = load_rule_pack(SEED_DIR / "lod400_construction.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    mfg_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "lod400_manufacturer_name"}
    assert mfg_outcomes.get("type-elem-ok") is True
    assert mfg_outcomes.get("type-elem-bad") is False


def test_lod400_pack_enforces_door_hosting_invariant() -> None:
    """Doors must be hosted by IfcWall — slab-hosted doors must fail."""
    pack = load_rule_pack(SEED_DIR / "lod400_construction.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    host_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "lod400_door_hosted_by_wall"}
    assert host_outcomes.get("door-lod400-ok") is True
    assert host_outcomes.get("door-bad-host") is False


def test_cobie_pack_enforces_four_level_spatial_structure() -> None:
    """COBie pack must fail spaces whose SpatialDepth != 4."""
    pack = load_rule_pack(SEED_DIR / "cobie_handover.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    depth_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "cobie_spatial_depth_is_four"}
    assert depth_outcomes.get("cobie-space-ok") is True
    assert depth_outcomes.get("cobie-space-flat") is False


def test_cobie_pack_requires_manufacturer_on_types() -> None:
    """COBie types must declare Manufacturer; missing → fail."""
    pack = load_rule_pack(SEED_DIR / "cobie_handover.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    mfg_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "cobie_type_manufacturer"}
    assert mfg_outcomes.get("cobie-type-ok") is True
    assert mfg_outcomes.get("cobie-type-bad") is False


def test_cobie_pack_flags_unserialised_components() -> None:
    """COBie SerialNumber rule fails when IsSerialised but no SerialNumber."""
    pack = load_rule_pack(SEED_DIR / "cobie_handover.yaml")
    result = evaluate_rule_pack(pack, SYNTHETIC_ELEMENTS)
    sn_outcomes = {r.element_id: r.passed for r in result.results if r.rule_id == "cobie_component_serial_number"}
    assert sn_outcomes.get("cobie-comp-ok") is True
    assert sn_outcomes.get("cobie-comp-bad") is False
