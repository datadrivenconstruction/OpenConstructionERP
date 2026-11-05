# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Projects module.

Provides project management: creation, configuration, archiving.
Each project defines its region, classification standard, and validation rule sets.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.projects.permissions import register_project_permissions

    register_project_permissions()

    from app.modules.projects.validators import register_projects_validation_rules

    register_projects_validation_rules()
