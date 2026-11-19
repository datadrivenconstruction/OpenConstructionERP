# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow permission definitions."""

from app.core.permissions import Role, permission_registry


def register_dataflow_permissions() -> None:
    """Register permissions for the dataflow module."""
    permission_registry.register_module_permissions("dataflow", {"dataflow.read": Role.VIEWER})
