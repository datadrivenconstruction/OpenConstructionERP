# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash → BOQ Cost Impact module.

Bridges the clash detection module (BIM coordination) with the BOQ module
(construction estimation) to surface a defensible monetary rework
estimate for every clash. Standalone BIM coordination tools cannot
expose this column - they have no BOQ side to anchor the cost against.

The module is read-only against both source modules:
    * Clash rows resolve via ``a_stable_id`` / ``b_stable_id`` (snapshotted
      on every ``ClashResult`` so re-imported models do not break the link).
    * BOQ positions resolve via ``cad_element_ids`` (already the canonical
      BIM-element-id list per position).
    * Project currency comes straight from the ``oe_projects_project`` row.

It owns no ORM tables of its own - the labour-hours bridge between
discipline pairs is a static Python constant (per the spec). This keeps
the module scope tight and avoids a v3 migration just to ship the
killer-feature column.
"""


async def on_startup() -> None:
    """‌⁠‍Module startup hook - register RBAC permissions."""
    from app.modules.clash_cost_impact.permissions import (
        register_clash_cost_impact_permissions,
    )

    register_clash_cost_impact_permissions()
