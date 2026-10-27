# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views permission definitions.

Every signed-in role may keep personal views; sharing with the team is an
editor action because it changes what colleagues see in their view picker.
"""

from app.core.permissions import Role, permission_registry


def register_list_views_permissions() -> None:
    """Register permissions for the list-views module."""
    permission_registry.register_module_permissions(
        "list_views",
        {
            "list_views.read": Role.VIEWER,
            "list_views.create": Role.VIEWER,
            "list_views.share": Role.EDITOR,
        },
    )
