# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture permission definitions."""

from app.core.permissions import Role, permission_registry

QUOTE_CAPTURE_PERMISSIONS: dict[str, Role] = {
    "quote_capture.read": Role.VIEWER,
    "quote_capture.write": Role.EDITOR,
}


def register_quote_capture_permissions() -> None:
    """Register permissions for the quote capture module."""
    permission_registry.register_module_permissions("quote_capture", QUOTE_CAPTURE_PERMISSIONS)
