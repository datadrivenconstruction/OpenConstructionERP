# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart Views preset library — out-of-box, ready-to-install views.

Each preset is a frozen :class:`SmartViewCreate`-compatible dict that the
service layer can hand to :meth:`SmartViewService.install_preset` to
materialise as a real ``oe_smart_view`` row. Presets are *templates*,
not rows: they are NOT stored in the DB until a user installs them.
Re-installing the same preset for the same (project, user) pair is
idempotent — the service returns the existing row instead of creating
a duplicate.

Counter-intuitive design: presets do NOT carry a scope_id; the scope
target is supplied by the caller at install time (so the same preset
can be installed once per project for a user's My-views, and again at
project scope for the team). The ``preset_id`` slug is stable across
releases so analytics ("install_preset_id=walls_by_fire_rating") survive
a preset content tweak.
"""

from __future__ import annotations

from typing import Any

# ── Preset catalogue ────────────────────────────────────────────────────
#
# Each preset is a self-contained dict shaped like ``SmartViewCreate``
# minus the ``scope_type`` / ``scope_id`` (the service fills those in).
# Every selector / action_args dict already conforms to the Pydantic
# schemas in ``schemas.py``; the service revalidates on install.
#
# ``preset_id`` is a stable slug — never rename one once shipped (the
# service uses it for the idempotency lookup).
# ``category`` is a free-form bucket used by the UI to group cards
# ("structure", "mep", "envelope", "doors", "spaces").

BUILTIN_PRESETS: list[dict[str, Any]] = [
    # 1) Walls by fire rating — colour every wall by its FireRating
    #    property. Walls without a FireRating fall through to the
    #    default ``show_all`` action (visible, default tint).
    {
        "preset_id": "walls_by_fire_rating",
        "category": "structure",
        "name": "Walls by fire rating",
        "description": (
            "Colours every IfcWall by its FireRating property value. "
            "Walls without a FireRating remain visible but uncoloured."
        ),
        "default_action": "show_all",
        "rules": [
            {
                "id": "walls-fire-rating",
                "selector": {
                    "ifc_class": "IfcWall",
                    "property": "FireRating",
                    "operator": "exists",
                    "value": None,
                },
                "action": "color",
                "action_args": {"color_by_property": "FireRating"},
                "order": 0,
            }
        ],
    },
    # 2) MEP by discipline — three rules, one per discipline. Order
    #    matters only for overlap (an element is at most one of the
    #    three IFC classes here so the rules never collide).
    {
        "preset_id": "mep_by_discipline",
        "category": "mep",
        "name": "MEP by discipline",
        "description": (
            "Colours flow segments / terminals / controllers by discipline: "
            "HVAC=blue, Electrical=yellow, Plumbing=green."
        ),
        "default_action": "show_all",
        "rules": [
            # HVAC — IfcDuct* + IfcAirTerminal pattern via FlowSegment
            # entity name. Selector relies on `ifc_class` only.
            {
                "id": "mep-flow-segment",
                "selector": {"ifc_class": "IfcFlowSegment"},
                "action": "color",
                "action_args": {"color": "#3b82f6"},
                "order": 0,
            },
            {
                "id": "mep-flow-terminal",
                "selector": {"ifc_class": "IfcFlowTerminal"},
                "action": "color",
                "action_args": {"color": "#eab308"},
                "order": 1,
            },
            {
                "id": "mep-flow-controller",
                "selector": {"ifc_class": "IfcFlowController"},
                "action": "color",
                "action_args": {"color": "#10b981"},
                "order": 2,
            },
        ],
    },
    # 3) Structural concrete C30/37+ — highlight beams / columns / slabs
    #    whose Material property contains "C30" (covers C30/37, C30/37 XC4,
    #    etc.). A regex selector is used because real-world Material
    #    strings are wildly inconsistent across exporters.
    {
        "preset_id": "structural_concrete_c30",
        "category": "structure",
        "name": "Structural concrete C30/37+",
        "description": (
            "Highlights structural members (beam / column / slab) whose "
            "Material property contains C30 or higher (C30/37, C35/45, C40/50)."
        ),
        "default_action": "show_all",
        "rules": [
            {
                "id": "concrete-beam",
                "selector": {
                    "ifc_class": "IfcBeam",
                    "property": "Material",
                    "operator": "regex",
                    "value": r"C(3[0-9]|[4-9][0-9])/",
                },
                "action": "color",
                "action_args": {"color": "#f97316"},
                "order": 0,
            },
            {
                "id": "concrete-column",
                "selector": {
                    "ifc_class": "IfcColumn",
                    "property": "Material",
                    "operator": "regex",
                    "value": r"C(3[0-9]|[4-9][0-9])/",
                },
                "action": "color",
                "action_args": {"color": "#f97316"},
                "order": 1,
            },
            {
                "id": "concrete-slab",
                "selector": {
                    "ifc_class": "IfcSlab",
                    "property": "Material",
                    "operator": "regex",
                    "value": r"C(3[0-9]|[4-9][0-9])/",
                },
                "action": "color",
                "action_args": {"color": "#f97316"},
                "order": 2,
            },
        ],
    },
    # 4) Doors fire-rated — fire-rated doors green, others transparent.
    #    ``hide_all`` would over-hide context; using ``transparent`` keeps
    #    surrounding geometry as a ghost reference.
    {
        "preset_id": "doors_fire_rated",
        "category": "doors",
        "name": "Fire-rated doors",
        "description": (
            "Highlights fire-rated doors in green; doors without a FireRating property fade to a ghost overlay."
        ),
        "default_action": "show_all",
        "rules": [
            {
                "id": "doors-not-fire-rated",
                "selector": {"ifc_class": "IfcDoor"},
                "action": "transparent",
                "action_args": {"opacity": 0.15},
                "order": 0,
            },
            {
                "id": "doors-fire-rated",
                "selector": {
                    "ifc_class": "IfcDoor",
                    "property": "FireRating",
                    "operator": "exists",
                    "value": None,
                },
                "action": "color",
                "action_args": {"color": "#10b981"},
                "order": 1,
            },
        ],
    },
    # 5) Exterior walls — show exterior walls only, hide interior.
    #    Two rules: hide everything that is a wall + IsExternal=false,
    #    show everything that is a wall + IsExternal=true.
    {
        "preset_id": "exterior_walls",
        "category": "envelope",
        "name": "Exterior walls only",
        "description": (
            "Shows walls whose IsExternal property is true; hides walls "
            "marked as interior. Non-wall geometry is unaffected."
        ),
        "default_action": "show_all",
        "rules": [
            {
                "id": "walls-interior-hide",
                "selector": {
                    "ifc_class": "IfcWall",
                    "property": "IsExternal",
                    "operator": "eq",
                    "value": False,
                },
                "action": "hide",
                "action_args": {},
                "order": 0,
            },
            {
                "id": "walls-exterior-color",
                "selector": {
                    "ifc_class": "IfcWall",
                    "property": "IsExternal",
                    "operator": "eq",
                    "value": True,
                },
                "action": "color",
                "action_args": {"color": "#0ea5e9"},
                "order": 1,
            },
        ],
    },
    # 6) Spaces by zone — colour every IfcSpace by its LongName (room
    #    name). Falls back to ObjectType if LongName is absent — but
    #    the evaluator only consults the configured property, so we
    #    pick LongName as the most-populated of the two in practice.
    {
        "preset_id": "spaces_by_zone",
        "category": "spaces",
        "name": "Spaces by zone",
        "description": ("Colours every IfcSpace by its LongName (room name / zone)."),
        "default_action": "show_all",
        "rules": [
            {
                "id": "spaces-color-by-longname",
                "selector": {
                    "ifc_class": "IfcSpace",
                    "property": "LongName",
                    "operator": "exists",
                    "value": None,
                },
                "action": "color",
                "action_args": {"color_by_property": "LongName"},
                "order": 0,
            }
        ],
    },
]


def get_preset(preset_id: str) -> dict[str, Any] | None:
    """Return the preset dict with the given slug, or ``None`` if absent.

    The lookup is linear because the registry is small (6 entries) and
    constant after import; keeping it a flat list makes the source diff-
    friendly when adding new presets.
    """
    for p in BUILTIN_PRESETS:
        if p["preset_id"] == preset_id:
            return p
    return None


def list_preset_ids() -> list[str]:
    """Stable ordering of preset slugs (matches BUILTIN_PRESETS order)."""
    return [p["preset_id"] for p in BUILTIN_PRESETS]
