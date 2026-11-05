# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Off-site / Prefab / DfMA module.

Tracks off-site manufactured units through an ordered production lifecycle
(design -> approved_for_production -> in_production -> qa -> dispatched ->
delivered -> installed) with a first-class quality gate: a unit can never be
dispatched, delivered or installed until it has passed QA. Every stage change
is captured as an immutable ``ProductionEvent`` audit row.

The pure stage machine (:mod:`app.modules.prefab.guard`) does no import-time
database work, so it can be unit tested on any interpreter. Permission
registration is deferred to :func:`on_startup`, called by the module loader.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.prefab.permissions import register_prefab_permissions

    register_prefab_permissions()
    from app.modules.prefab.validators import register_prefab_validation_rules

    register_prefab_validation_rules()
