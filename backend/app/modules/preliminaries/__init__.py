# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Preliminaries (general conditions) module.

Estimates the project preliminaries / general conditions that sit alongside the
measured work: site establishment, site staff, temporary works, standing plant
and welfare. Each item is either *time-related* (a rate per period multiplied by
the number of periods the item stands on site) or a *fixed* one-off amount. The
module rolls the items up per category and into a single preliminaries total that
adds to the estimate.

The package does no import-time database work: the pure engine
(:mod:`app.modules.preliminaries.prelim_math`) is importable on any interpreter,
and permission registration is deferred to :func:`on_startup` (called by the
module loader), mirroring every other module.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    from app.modules.preliminaries.permissions import register_preliminaries_permissions

    register_preliminaries_permissions()
    from app.modules.preliminaries.validators import register_preliminaries_validation_rules

    register_preliminaries_validation_rules()
