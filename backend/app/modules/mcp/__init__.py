# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MCP server module.

A Model Context Protocol endpoint (streamable HTTP, JSON responses) mounted at
``/api/v1/mcp/``. An external AI client authenticates with a personal token
and then works with exactly what its owner may see: read tools for projects,
bills of quantities, the cost database, schedules, validation, site issues and
document metadata, and ``propose_*`` tools that store a proposal a person
confirms in the app. Nothing a client sends is ever applied directly.
"""


async def on_startup() -> None:
    """Register the module's permissions and validation rules (both idempotent)."""
    from app.modules.mcp.permissions import register_mcp_permissions
    from app.modules.mcp.validators import register_mcp_rules

    register_mcp_permissions()
    register_mcp_rules()
