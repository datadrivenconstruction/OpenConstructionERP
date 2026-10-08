# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legal Entities module permission definitions.

ADMIN for writes: the entities are install-wide, like the company profile, and
the country and currency of an entity decide how every document it owns is
numbered and taxed once those pieces read it. Reads need only a signed-in user.
"""

from app.core.permissions import Role, permission_registry


def register_legal_entities_permissions() -> None:
    """Register permissions for the legal entities module."""
    permission_registry.register_module_permissions(
        "legal_entities",
        {
            "legal_entities.read": Role.VIEWER,
            "legal_entities.manage": Role.ADMIN,
        },
    )
