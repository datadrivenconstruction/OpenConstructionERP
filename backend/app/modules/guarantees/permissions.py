# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register permission definitions."""

from app.core.permissions import Role, permission_registry

# Reading the register and the exposure is viewer-level; issuing, reducing,
# releasing or calling a guarantee and editing bank credit lines needs an editor.
GUARANTEES_PERMISSIONS: dict[str, Role] = {
    "guarantees.read": Role.VIEWER,
    "guarantees.write": Role.EDITOR,
}


def register_guarantees_permissions() -> None:
    """Register permissions for the guarantees module."""
    permission_registry.register_module_permissions("guarantees", GUARANTEES_PERMISSIONS)
