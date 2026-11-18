# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project tax profile permissions.

Reading the profile is part of reading the project. Changing it is a manager's
act: the method and the edition decide how every bill and invoice of the
project is taxed, and a method change starts a new lock period.
"""

from app.core.permissions import Role, permission_registry


def register_project_tax_permissions() -> None:
    """Register permissions for the project tax module."""
    permission_registry.register_module_permissions(
        "project_tax",
        {
            "project_tax.read": Role.VIEWER,
            "project_tax.write": Role.MANAGER,
        },
    )
