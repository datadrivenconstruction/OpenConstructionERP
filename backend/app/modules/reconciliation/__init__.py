# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Event reconciliation module.

A project's record of an event scatters across modules and channels: one site
instruction surfaces as correspondence, a change order, a variation and a
management-of-change entry, each in its own table with its own identifier. This
module answers which of those heterogeneous records are really about the *same*
event so the trail can be stitched back together for a claim, an audit, or a
coordination view. The pure :mod:`correlate` engine does the scoring (stdlib
only, so it unit-tests on the local runner without the database or web
framework); a thin service gathers the source rows, projects them onto the
engine's uniform shape, and persists a reviewer's confirm / reject decisions.

The module loader discovers and mounts the ``router`` submodule at
``/api/v1/reconciliation`` and calls :func:`on_startup` once at boot; this
``__init__`` does not import the router at top level so the engine stays
independently importable.
"""

__all__ = ["on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the module's permissions."""
    from app.modules.reconciliation.permissions import (
        register_reconciliation_permissions,
    )

    register_reconciliation_permissions()
    from app.modules.reconciliation.validators import register_reconciliation_validation_rules

    register_reconciliation_validation_rules()
