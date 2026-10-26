# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MCP server permission definitions."""

from app.core.permissions import Role, permission_registry


def register_mcp_permissions() -> None:
    """Register RBAC permissions for the MCP module.

    ``mcp.use`` lets a person switch the endpoint on for themselves and manage
    their own tokens. It is a viewer permission on purpose: a token never
    reaches further than its owner, so a viewer's client can only read what
    the viewer can read.
    """
    permission_registry.register_module_permissions(
        "mcp",
        {
            "mcp.use": Role.VIEWER,
        },
    )
