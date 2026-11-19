# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Central purchasing permission definitions.

``central_purchasing.manage`` is the central buyer: sees every bundle whole, edits it and awards
it. Everyone else reaches a bundle only through a project they may open, and sees that project's
share, budget and own document, never another project's numbers.
"""

from app.core.permissions import Role, permission_registry


def register_central_purchasing_permissions() -> None:
    """Register permissions for the central purchasing module."""
    permission_registry.register_module_permissions(
        "central_purchasing",
        {
            "central_purchasing.read_share": Role.VIEWER,
            "central_purchasing.manage": Role.MANAGER,
            "central_purchasing.award": Role.MANAGER,
        },
    )
