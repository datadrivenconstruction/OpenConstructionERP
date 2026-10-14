# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design management permission definitions.

``design.approve`` is the floor, not the grant: whoever decides an approval
point is named by its approval route, and the decision is taken in the
approval screen (rule 22). ``design.release`` issues releases as transmittals;
under ``four_eyes_release`` the person who prepared a release cannot issue it.
That second-person rule, not the role, carries the control, which is why issuing
stays at editor level while the other approvals sit at manager level.
"""

from app.core.permissions import Role, permission_registry


def register_design_permissions() -> None:
    """Register permissions for the design management module."""
    permission_registry.register_module_permissions(
        "design_management",
        {
            "design.read": Role.VIEWER,
            "design.edit": Role.EDITOR,
            "design.release": Role.EDITOR,
            # Pinning a scheme or catalogue, renumbering, the distribution matrix.
            "design.manage": Role.MANAGER,
            "design.approve": Role.MANAGER,
        },
    )
