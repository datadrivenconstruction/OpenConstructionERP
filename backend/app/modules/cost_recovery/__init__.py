# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost recovery / back-charge module.

Records costs the project intends to recover from the party held responsible for
causing them - rework arising from a subcontractor defect, extra cost from a
supplier delay - and rolls them up into a recovery ledger: how much is
chargeable, how much has been recovered, and what is still outstanding against
whom. The pure :mod:`back_charge` engine does the money math (stdlib only, so it
unit-tests on the local runner without the database or web framework); a thin
service persists the records and feeds them in.

The module loader discovers and mounts the ``router`` submodule at
``/api/v1/cost-recovery`` and calls :func:`on_startup` once at boot; this
``__init__`` does not import the router at top level so the engine stays
independently importable.
"""

__all__ = ["on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the module's permissions."""
    from app.modules.cost_recovery.permissions import (
        register_cost_recovery_permissions,
    )

    register_cost_recovery_permissions()
    from app.modules.cost_recovery.validators import register_cost_recovery_validation_rules

    register_cost_recovery_validation_rules()
