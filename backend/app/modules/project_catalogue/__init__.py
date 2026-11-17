# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue module.

A project's own rates and resources, copied from the regional cost database or
the company library, edited per project, with provenance and a decision on
every moved source price. The master data is never written.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.project_catalogue.permissions import register_project_catalogue_permissions
    from app.modules.project_catalogue.validators import register_project_catalogue_validation_rules

    register_project_catalogue_permissions()
    register_project_catalogue_validation_rules()
