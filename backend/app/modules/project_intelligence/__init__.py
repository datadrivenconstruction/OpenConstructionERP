"""Project Intelligence module.

AI-powered project completion analysis, scoring, gap detection,
and guided recommendations for OpenConstructionERP.
"""

MODULE_METADATA = {
    "id": "project_intelligence",
    "name": "Project Intelligence",
    "description": "AI-powered project completion analysis and guided recommendations",
    "version": "1.0.0",
    "category": "intelligence",
    "icon": "brain-circuit",
    "route_prefix": "/api/v1/project-intelligence",
    "requires": ["boq", "schedule", "validation"],
    "feature_flags": ["ai_advisor"],
}


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.project_intelligence.permissions import (
        register_project_intelligence_permissions,
    )

    register_project_intelligence_permissions()
