# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Basis-of-estimate module.

Auto-drafts the inclusions, exclusions and assumptions that qualify an estimate,
derived from which trades are present, absent or flagged by the coverage check
over the finished BOQ. The drafted lines are editable and export with a proposal.

The reasoning engine (:mod:`app.modules.estimate_basis.derivation`) is
stdlib-only, so it can be unit tested on a bare interpreter without a database or
the app graph. Permission registration is deferred to :func:`on_startup`, called
by the module loader after the router is mounted.
"""


async def on_startup() -> None:
    """Module startup hook - register the module permissions (idempotent)."""
    from app.modules.estimate_basis.permissions import register_estimate_basis_permissions

    register_estimate_basis_permissions()
    from app.modules.estimate_basis.validators import register_estimate_basis_validation_rules

    register_estimate_basis_validation_rules()
