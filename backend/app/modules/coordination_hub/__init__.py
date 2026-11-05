# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Coordination Hub module.

A *thin, read-only* aggregator that surfaces every coordination signal
already produced by the sibling BIM modules (federations, clashes, smart
views, rule packs, BCF activity) on a single project-level dashboard.
It owns NO new tables - every count, delta and event-stream entry is
sourced live from the upstream module's own ORM.

Industry term for the surface this module renders is **"Model
Coordination"**. Comparable dedicated tools focus on BCF coordination
Cloud; the unique-to-OCERP twist is the ``open_cost_impact_total`` KPI
that ties coordination debt to live BOQ money via the
``oe_clash_cost_impact`` module.

The aggregator is defensive: each upstream module may or may not be
loaded on a given deployment (the new modules ship in v4.2). If a count
fails because its table is missing - or any other unexpected SELECT
error - the dashboard logs a warning and returns ``0`` for that field
rather than failing the whole response. Honest empty state > 500.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    # Side-effect import so ``CoordinationThreshold`` registers with the
    # shared ``Base.metadata`` before ``create_all`` runs on a fresh
    # SQLite (the table never appears in any other module's import path).
    from app.modules.coordination_hub import models  # noqa: F401
    from app.modules.coordination_hub.permissions import (
        register_coordination_hub_permissions,
    )

    register_coordination_hub_permissions()

    from app.modules.coordination_hub.validators import register_coordination_hub_validation_rules

    register_coordination_hub_validation_rules()
