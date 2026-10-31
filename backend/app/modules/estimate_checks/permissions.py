# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check permission definitions."""

from app.core.permissions import Role, permission_registry

# Anyone who can read an estimate sees its check; estimators accept findings;
# thresholds apply to the whole workspace, so only managers edit them.
ESTIMATE_CHECK_PERMISSIONS: dict[str, Role] = {
    "estimate_checks.read": Role.VIEWER,
    "estimate_checks.accept": Role.EDITOR,
    "estimate_checks.admin": Role.MANAGER,
}


def register_estimate_check_permissions() -> None:
    """Register permissions for the estimate check module."""
    permission_registry.register_module_permissions("estimate_checks", ESTIMATE_CHECK_PERMISSIONS)
