"""RFI module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_rfi_permissions() -> None:
    """Register permissions for the RFI module."""
    permission_registry.register_module_permissions(
        "rfi",
        {
            "rfi.create": Role.EDITOR,
            "rfi.read": Role.VIEWER,
            "rfi.update": Role.EDITOR,
            "rfi.delete": Role.MANAGER,
        },
    )
