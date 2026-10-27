# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ permission definitions."""

from app.core.permissions import Role, permission_registry


def register_site_sensors_permissions() -> None:
    """Register permissions for the site sensors module."""
    permission_registry.register_module_permissions(
        "site_sensors",
        {
            "site_sensors.read": Role.VIEWER,
            "site_sensors.record": Role.EDITOR,
            "site_sensors.acknowledge": Role.EDITOR,
            "site_sensors.manage": Role.MANAGER,
        },
    )
