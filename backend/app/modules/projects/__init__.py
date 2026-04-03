"""Projects module.

Provides project management: creation, configuration, archiving.
Each project defines its region, classification standard, and validation rule sets.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.projects.permissions import register_project_permissions

    register_project_permissions()
