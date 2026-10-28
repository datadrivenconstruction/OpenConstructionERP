"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration check for the Revit-flavoured seed packs in data/bim_rules/.

Each Revit template must load through the real ``load_rule_pack`` loader
(the same code path the frontend preview endpoint uses) AND dry-run against
a small set of synthetic Revit-shaped elements with the expected pass/fail
outcomes.

Revit elements arrive with their category in ``element_type`` (the field the
``preview-yaml`` router maps from the BIM hub) and their parameters in
``properties``; the runtime matches ``selector.ifc_class`` against either
``ifc_class`` or ``element_type`` case-insensitively.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.bim_requirements.rule_runtime import evaluate_rule_pack
from app.modules.bim_requirements.yaml_loader import load_rule_pack

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_DIR = REPO_ROOT / "data" / "bim_rules"

REVIT_PACK_FILES = [
    "revit_cost_classification.yaml",
    "revit_corridor_door_clearance.yaml",
    "revit_fire_rating.yaml",
    "revit_mep_clearance.yaml",
    "revit_room_naming.yaml",
]


# Synthetic Revit elements (element_type = Revit category, properties =
# Revit parameters). Covers every selector across the five packs.
REVIT_ELEMENTS = [
    # Walls
    {
        "id": "wall-ok",
        "element_type": "Walls",
        "properties": {"Function": "Interior", "Fire Rating": "F90", "DIN_276_Code": "340"},
    },
    {
        "id": "wall-no-din",
        "element_type": "Walls",
        "properties": {"Function": "Interior", "Fire Rating": "F30"},
    },
    {
        "id": "wall-bad-din",
        "element_type": "Walls",
        "properties": {"Function": "Interior", "Fire Rating": "F30", "DIN_276_Code": "120"},
    },
    {
        "id": "wall-no-fire",
        "element_type": "Walls",
        "properties": {"Function": "Interior", "DIN_276_Code": "340"},
    },
    {
        "id": "wall-bad-fire",
        "element_type": "Walls",
        "properties": {"Function": "Interior", "Fire Rating": "F45", "DIN_276_Code": "340"},
    },
    {
        # EN 13501-2 REI class is accepted alongside the DIN 4102 F-classes.
        "id": "wall-rei",
        "element_type": "Walls",
        "properties": {"Function": "Interior", "Fire Rating": "REI 90", "DIN_276_Code": "330"},
    },
    {
        "id": "wall-exterior",
        "element_type": "Walls",
        "properties": {"Function": "Exterior", "DIN_276_Code": "330"},
    },
    # Rooms
    {
        "id": "room-corr-ok",
        "element_type": "Rooms",
        "properties": {"Occupancy": "Corridor", "Number": "CO.02.001", "Clear Width": 1.8},
    },
    {
        "id": "room-corr-narrow",
        "element_type": "Rooms",
        "properties": {"Occupancy": "Corridor", "Number": "CO.02.002", "Clear Width": 1.2},
    },
    {
        "id": "room-bad-number",
        "element_type": "Rooms",
        "properties": {"Occupancy": "Office", "Number": "room-7"},
    },
    # Doors
    {
        "id": "door-ok",
        "element_type": "Doors",
        "properties": {"Accessible Route": True, "Mark": "D-101", "Width": 1.0},
    },
    {
        "id": "door-narrow",
        "element_type": "Doors",
        "properties": {"Accessible Route": True, "Mark": "D-102", "Width": 0.8},
    },
    {
        "id": "door-not-accessible",
        "element_type": "Doors",
        "properties": {"Accessible Route": False, "Mark": "D-103", "Width": 0.7},
    },
    # Pipes / structural framing
    {
        "id": "pipe-ok",
        "element_type": "Pipes",
        "properties": {"Clearance To Structure": 0.15},
    },
    {
        "id": "pipe-bad",
        "element_type": "Pipes",
        "properties": {"Clearance To Structure": 0.05},
    },
    {"id": "beam-1", "element_type": "Structural Framing", "properties": {}},
]


def _outcomes(pack_filename: str) -> dict[tuple[str, str], bool]:
    """Return a {(rule_id, element_id): passed} map for a Revit pack."""
    pack = load_rule_pack(SEED_DIR / pack_filename)
    result = evaluate_rule_pack(pack, REVIT_ELEMENTS)
    return {(r.rule_id, r.element_id): r.passed for r in result.results}


@pytest.mark.parametrize("pack_filename", REVIT_PACK_FILES)
def test_revit_pack_loads_and_runs(pack_filename: str) -> None:
    """Each Revit pack must parse and produce a well-formed PackResult."""
    pack = load_rule_pack(SEED_DIR / pack_filename)
    result = evaluate_rule_pack(pack, REVIT_ELEMENTS)

    assert result.pack_id == pack.pack.id
    assert pack.pack.id.startswith("revit_")
    assert result.total_elements == len(REVIT_ELEMENTS)
    assert result.passed + result.failed + result.not_applicable == len(REVIT_ELEMENTS)
    ids = {e["id"] for e in REVIT_ELEMENTS}
    for row in result.results:
        assert row.element_id in ids


def test_cost_classification_flags_missing_and_out_of_range() -> None:
    o = _outcomes("revit_cost_classification.yaml")
    # Missing DIN_276_Code shared parameter fails the presence rule.
    assert o[("revit_din276_code_present", "wall-no-din")] is False
    assert o[("revit_din276_code_present", "wall-ok")] is True
    # A code outside 300/400/500 fails the range rule (but passes presence).
    assert o[("revit_din276_code_present", "wall-bad-din")] is True
    assert o[("revit_din276_code_in_building_range", "wall-bad-din")] is False
    assert o[("revit_din276_code_in_building_range", "wall-ok")] is True


def test_corridor_and_door_clearance() -> None:
    o = _outcomes("revit_corridor_door_clearance.yaml")
    assert o[("revit_corridor_minimum_width", "room-corr-narrow")] is False
    assert o[("revit_corridor_minimum_width", "room-corr-ok")] is True
    assert o[("revit_door_clear_width", "door-narrow")] is False
    assert o[("revit_door_clear_width", "door-ok")] is True
    # A door not on an accessible route is out of scope for the door rule.
    assert ("revit_door_clear_width", "door-not-accessible") not in o


def test_fire_rating_presence_and_vocabulary() -> None:
    o = _outcomes("revit_fire_rating.yaml")
    assert o[("revit_interior_wall_fire_rating_present", "wall-no-fire")] is False
    assert o[("revit_interior_wall_fire_rating_valid", "wall-bad-fire")] is False
    assert o[("revit_interior_wall_fire_rating_present", "wall-ok")] is True
    # EN 13501-2 REI classes are accepted by the vocabulary rule.
    assert o[("revit_interior_wall_fire_rating_valid", "wall-rei")] is True
    # Exterior walls (Function != Interior) are not applicable.
    assert ("revit_interior_wall_fire_rating_present", "wall-exterior") not in o


def test_mep_clearance_pipe_vs_framing() -> None:
    o = _outcomes("revit_mep_clearance.yaml")
    assert o[("revit_pipe_to_framing_clearance_100mm", "pipe-bad")] is False
    assert o[("revit_pipe_to_framing_clearance_100mm", "pipe-ok")] is True


def test_room_number_naming_pattern() -> None:
    o = _outcomes("revit_room_naming.yaml")
    assert o[("revit_room_number_matches_code_pattern", "room-bad-number")] is False
    assert o[("revit_room_number_matches_code_pattern", "room-corr-ok")] is True


def test_failure_messages_render_without_missing_placeholder() -> None:
    """Spaceless placeholders must interpolate; nothing should render the
    literal '<missing>' sentinel for elements that do carry the value.

    This guards the deliberate design choice to keep Revit ``{{...}}``
    placeholders spaceless (the template regex rejects spaces), e.g. the
    door message interpolates ``{{Mark}}`` and ``{{Width}}``.
    """
    pack = load_rule_pack(SEED_DIR / "revit_corridor_door_clearance.yaml")
    result = evaluate_rule_pack(pack, REVIT_ELEMENTS)
    door_msg = next(
        r.message for r in result.results if r.rule_id == "revit_door_clear_width" and r.element_id == "door-narrow"
    )
    assert door_msg is not None
    assert "D-102" in door_msg  # {{Mark}} interpolated
    assert "0.8" in door_msg  # {{Width}} interpolated
    assert "<missing>" not in door_msg
