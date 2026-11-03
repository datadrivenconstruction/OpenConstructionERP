# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Agents module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_ai_agents_permissions() -> None:
    """Register permissions for the AI Agents module."""
    permission_registry.register_module_permissions(
        "ai_agents",
        {
            "ai_agents.read": Role.VIEWER,
            "ai_agents.run": Role.EDITOR,
            # Project agent catalogue: enabling, configuring and the kill switch are manager decisions;
            # accepting or rejecting a draft is an editor action.
            "ai_agents.configure": Role.MANAGER,
            "ai_agents.review": Role.EDITOR,
        },
    )
