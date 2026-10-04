# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Post-calculation (Nachkalkulation) module.

Reconciles a project's estimate against its site actuals - approved field
timesheets (labour and plant hours) and progress readings (installed quantity) -
into planned-vs-actual labour productivity per BoQ line and per resource category,
a project rollup, and a ranked list of productivity factors to feed back into
estimating. A stateless read/analyse layer: it adds no table, so there is no
migration. The one write is the quantity check's baseline pointer, kept in the
bill's own metadata (see ``app.modules.boq.quantity_baseline``).
"""


async def on_startup() -> None:
    """Module startup hook - register the read permission."""
    from app.modules.postcalc.permissions import register_postcalc_permissions

    register_postcalc_permissions()
