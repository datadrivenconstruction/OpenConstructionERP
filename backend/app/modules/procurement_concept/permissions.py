# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement concept permission definitions.

``procurement_concept.edit`` is the floor, not the grant: the service narrows
plan edits and approval to a project manager or the owner (or deputy) of the
procurement area in governance (SPEC section 5).
"""

from app.core.permissions import Role, permission_registry


def register_procurement_concept_permissions() -> None:
    """Register permissions for the procurement concept module."""
    permission_registry.register_module_permissions(
        "procurement_concept",
        {
            "procurement_concept.read": Role.VIEWER,
            "procurement_concept.edit": Role.EDITOR,
            # Steering the concept without owning the procurement area, and the fields the gate reads.
            "procurement_concept.manage": Role.MANAGER,
            # Company framework agreements outlive projects.
            "procurement_concept.frameworks.manage": Role.MANAGER,
            # Confirming a legal value of a procurement profile for the whole company.
            "procurement_concept.profiles.confirm": Role.MANAGER,
        },
    )
