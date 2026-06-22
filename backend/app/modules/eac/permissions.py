# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍EAC v2 module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_eac_permissions() -> None:
    """‌⁠‍Register permissions for the EAC v2 module.

    The EAC engine drives QTO/cost/validation outputs, so its write,
    delete and execute surfaces must be gated by role and not merely by
    "authenticated + same tenant". Reads stay at VIEWER; authoring and
    running rules/rulesets requires at least EDITOR; destructive deletes
    require MANAGER. ``eac.run`` also covers dry-run / validate / compile
    because those feed user-supplied rule definitions/formulas into the
    executor and must not be reachable by a read-only viewer.
    """
    permission_registry.register_module_permissions(
        "eac",
        {
            "eac.read": Role.VIEWER,
            "eac.write": Role.EDITOR,
            "eac.delete": Role.MANAGER,
            "eac.run": Role.EDITOR,
        },
    )
