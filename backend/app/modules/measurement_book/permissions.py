# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book permission definitions."""

from app.core.permissions import Role, permission_registry


def register_measurement_book_permissions() -> None:
    """Register permissions; posting the running bill to progress is a manager action."""
    permission_registry.register_module_permissions(
        "measurement_book",
        {
            "measurement_book.read": Role.VIEWER,
            "measurement_book.write": Role.EDITOR,
            "measurement_book.check": Role.EDITOR,
            "measurement_book.bill": Role.MANAGER,
        },
    )
