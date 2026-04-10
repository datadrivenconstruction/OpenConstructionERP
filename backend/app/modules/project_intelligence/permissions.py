"""Project Intelligence module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_project_intelligence_permissions() -> None:
    """Register permissions for the Project Intelligence module.

    PI exposes project state, scores, and AI recommendations — all
    read-oriented from the user's perspective. Running actions
    (``/actions/{id}``) is write-level and requires EDITOR.
    """
    permission_registry.register_module_permissions(
        "project_intelligence",
        {
            "project_intelligence.read": Role.VIEWER,
            "project_intelligence.create": Role.EDITOR,
        },
    )
