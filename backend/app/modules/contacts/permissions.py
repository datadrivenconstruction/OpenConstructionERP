"""Contacts module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_contacts_permissions() -> None:
    """Register permissions for the contacts module."""
    permission_registry.register_module_permissions(
        "contacts",
        {
            "contacts.create": Role.EDITOR,
            "contacts.read": Role.VIEWER,
            "contacts.update": Role.EDITOR,
            "contacts.delete": Role.MANAGER,
        },
    )
