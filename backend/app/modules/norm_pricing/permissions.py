# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Norm pricing permission definitions."""

from app.core.permissions import Role, permission_registry


def register_norm_pricing_permissions() -> None:
    """Reading rates is open to viewers; the wage and funding settings price the estimate."""
    permission_registry.register_module_permissions(
        "norm_pricing",
        {
            "norm_pricing.read": Role.VIEWER,
            "norm_pricing.update": Role.EDITOR,
        },
    )
