"""Full EVM module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_full_evm_permissions() -> None:
    """Register permissions for the Full EVM module.

    EVM forecasts are read-heavy and tied to project finances; anyone
    with VIEWER on the project can read, EDITOR can recompute forecasts.
    """
    permission_registry.register_module_permissions(
        "full_evm",
        {
            "full_evm.read": Role.VIEWER,
            "full_evm.create": Role.EDITOR,
        },
    )
