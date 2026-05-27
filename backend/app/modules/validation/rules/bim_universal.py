"""‌⁠‍Universal per-element BIM validation rules.

This module declares a small library of :class:`BIMElementRule` instances
that apply to any BIM/IFC model regardless of jurisdiction. They are the
"boq_quality" equivalent for BIM element data.

Rules declared here:

* ``bim.wall.has_thickness`` — every Wall must have a thickness > 0
* ``bim.structural.has_material`` — every Structural* element must declare
  a ``material`` property
* ``bim.wall.has_fire_rating`` — every Wall should have ``fire_rating``
  (warning, not error)
* ``bim.door.has_dimensions`` — every Door must have both width and height
* ``bim.window.has_dimensions`` — every Window must have both width and
  height
* ``bim.mep.has_system`` — MEP elements must declare ``system`` or
  ``system_type``
* ``bim.element.has_storey`` — every element should have ``storey``
  populated (warning)
* ``bim.element.name_not_none`` — every element must have a meaningful
  name (warning)

Usage::

    from app.modules.validation.rules.bim_universal import BIM_UNIVERSAL_RULES

    for rule in BIM_UNIVERSAL_RULES:
        ...

The list is considered immutable at import time — do NOT mutate it from
callers. Instead, filter it:
``[r for r in BIM_UNIVERSAL_RULES if r.rule_id in requested]``.
"""

from __future__ import annotations

from app.modules.validation.rules.bim_element_rule import BIMElementRule

# ── Rule definitions ─────────────────────────────────────────────────────────

WALL_HAS_THICKNESS = BIMElementRule(
    rule_id="bim.wall.has_thickness",
    name="Wall elements must have thickness > 0",
    severity="error",
    description=(
        "Every wall element must expose a positive thickness in its "
        "quantities (thickness_m or thickness). Walls without thickness "
        "cannot be used for takeoff or costing."
    ),
    element_filter={"element_type_startswith": ["wall", "ifcwall"]},
    # MUST be a number > 0 — a presence-only check let thickness_m=0 (or the
    # non-numeric string "0,24") pass and defeated the takeoff/costing
    # guarantee the rule name makes (E-BIM-010).
    require_any_positive_quantity=["thickness_m", "thickness", "width_m", "width"],
)

STRUCTURAL_HAS_MATERIAL = BIMElementRule(
    rule_id="bim.structural.has_material",
    name="Structural elements must declare a material",
    severity="error",
    description=(
        "Every element whose type starts with 'Structural' (or the IFC "
        "equivalent) must carry a 'material' property so material "
        "takeoffs and LCA reports can be produced."
    ),
    element_filter={
        "element_type_startswith": [
            "structural",
            "ifcbeam",
            "ifccolumn",
            "ifcfooting",
            "ifcslab",
            "ifcmember",
            "ifcpile",
        ],
    },
    property_checks=[{"property": "material", "must_exist": True}],
)

WALL_HAS_FIRE_RATING = BIMElementRule(
    rule_id="bim.wall.has_fire_rating",
    name="Wall elements should have a fire_rating property",
    severity="warning",
    description=(
        "Walls without a 'fire_rating' property cannot be validated "
        "against fire-compartment design requirements. Treated as a "
        "warning — many temporary or non-compartmenting walls are exempt."
    ),
    element_filter={"element_type_startswith": ["wall", "ifcwall"]},
    property_checks=[{"property": "fire_rating", "must_exist": True}],
)

DOOR_HAS_DIMENSIONS = BIMElementRule(
    rule_id="bim.door.has_dimensions",
    name="Door elements must have width and height",
    severity="error",
    description=("Every door must declare both width and height in either its properties or its quantities dict."),
    element_filter={"element_type_startswith": ["door", "ifcdoor"]},
    require_any_of_properties=["width", "width_m", "overall_width"],
    # Dimensions must be positive numbers, not merely present (E-BIM-010).
    require_any_positive_quantity=["width", "width_m", "height", "height_m"],
)

WINDOW_HAS_DIMENSIONS = BIMElementRule(
    rule_id="bim.window.has_dimensions",
    name="Window elements must have width and height",
    severity="error",
    description=("Every window must declare both width and height in either its properties or its quantities dict."),
    element_filter={"element_type_startswith": ["window", "ifcwindow"]},
    require_any_of_properties=["width", "width_m", "overall_width"],
    # Dimensions must be positive numbers, not merely present (E-BIM-010).
    require_any_positive_quantity=["width", "width_m", "height", "height_m"],
)

MEP_HAS_SYSTEM = BIMElementRule(
    rule_id="bim.mep.has_system",
    name="MEP elements must declare a system or system_type",
    severity="error",
    description=(
        "Mechanical/electrical/plumbing elements must expose either a "
        "'system' or 'system_type' property so they can be grouped by "
        "distribution system."
    ),
    element_filter={
        "element_type_startswith": [
            "duct",
            "pipe",
            "cabletray",
            "conduit",
            "mechanicalequipment",
            "electricalequipment",
            "plumbingfixture",
            "ifcduct",
            "ifcpipe",
            "ifccabletray",
            "ifcflowfitting",
            "ifcflowsegment",
            "ifcflowterminal",
        ],
    },
    require_any_of_properties=["system", "system_type", "system_name", "mep_system"],
)

ELEMENT_HAS_STOREY = BIMElementRule(
    rule_id="bim.element.has_storey",
    name="Elements should have a storey assignment",
    severity="warning",
    description=(
        "Elements not assigned to a storey cannot be included in "
        "storey-based reports or takeoff breakdowns. Warning only — "
        "site-wide elements like terrain or foundations are legitimately "
        "storey-less."
    ),
    require_storey=True,
)

ELEMENT_NAME_NOT_NONE = BIMElementRule(
    rule_id="bim.element.name_not_none",
    name="Elements must have a meaningful name",
    severity="warning",
    description=(
        "Elements with name == '' or 'None' indicate a broken export or "
        "an unnamed family instance. Warning severity — the rest of the "
        "data may still be usable."
    ),
    require_name=True,
)


# ── Registry ─────────────────────────────────────────────────────────────────

BIM_UNIVERSAL_RULES: list[BIMElementRule] = [
    WALL_HAS_THICKNESS,
    STRUCTURAL_HAS_MATERIAL,
    WALL_HAS_FIRE_RATING,
    DOOR_HAS_DIMENSIONS,
    WINDOW_HAS_DIMENSIONS,
    MEP_HAS_SYSTEM,
    ELEMENT_HAS_STOREY,
    ELEMENT_NAME_NOT_NONE,
]
"""‌⁠‍Ordered list of enabled universal BIM element rules."""


def get_rules_by_ids(rule_ids: list[str] | None) -> list[BIMElementRule]:
    """‌⁠‍Return the subset of ``BIM_UNIVERSAL_RULES`` matching ``rule_ids``.

    If ``rule_ids`` is ``None`` or empty, the full enabled set is returned.
    Unknown ids are silently skipped — callers can verify by comparing
    lengths if strict behaviour is needed.
    """
    if not rule_ids:
        return [r for r in BIM_UNIVERSAL_RULES if r.enabled]
    wanted = set(rule_ids)
    return [r for r in BIM_UNIVERSAL_RULES if r.enabled and r.rule_id in wanted]
