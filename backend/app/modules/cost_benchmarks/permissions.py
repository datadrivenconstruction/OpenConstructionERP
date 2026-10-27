# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks permission definitions."""

from app.core.permissions import Role, permission_registry

COST_BENCHMARKS_PERMISSIONS: dict[str, Role] = {
    "cost_benchmarks.read": Role.VIEWER,
    "cost_benchmarks.write": Role.EDITOR,
}


def register_cost_benchmarks_permissions() -> None:
    """Register permissions for the cost benchmarks module."""
    permission_registry.register_module_permissions("cost_benchmarks", COST_BENCHMARKS_PERMISSIONS)
