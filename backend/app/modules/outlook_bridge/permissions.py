# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outlook Bridge permission declarations."""

from app.core.permissions import Role, permission_registry


def register_outlook_bridge_permissions() -> None:
    permission_registry.register_module_permissions(
        "outlook_bridge",
        {
            "outlook_bridge.read": Role.VIEWER,
            # Opening a draft touches the user's desktop Outlook - editor
            # level, same as sending correspondence.
            "outlook_bridge.draft": Role.EDITOR,
        },
    )


register_outlook_bridge_permissions()
