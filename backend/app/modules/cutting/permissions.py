# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cutting optimisation permission definitions."""

from app.core.permissions import Role, permission_registry

CUTTING_PERMISSIONS: dict[str, Role] = {
    "cutting.read": Role.VIEWER,
    "cutting.write": Role.EDITOR,
    "cutting.apply": Role.EDITOR,
}


def register_cutting_permissions() -> None:
    """Register permissions for the cutting module.

    Reading jobs and plans is a viewer action; editing cut lists and running the
    optimiser is ``write``. Writing a plan's figures into another module (BOQ
    quantity, requisition quantity, inventory offcuts) is ``apply``, kept apart so
    it can be tightened without touching plain editing.
    """
    permission_registry.register_module_permissions("cutting", CUTTING_PERMISSIONS)
