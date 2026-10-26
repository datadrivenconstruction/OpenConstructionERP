# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report permission definitions."""

from app.core.permissions import Role, permission_registry

# Reading the schedule is viewer-level; closing a period or overriding the forecast needs an editor.
WIP_REPORT_PERMISSIONS: dict[str, Role] = {
    "wip_report.read": Role.VIEWER,
    "wip_report.write": Role.EDITOR,
}


def register_wip_report_permissions() -> None:
    """Register permissions for the WIP report module."""
    permission_registry.register_module_permissions("wip_report", WIP_REPORT_PERMISSIONS)
