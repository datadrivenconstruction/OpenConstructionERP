# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM Requirements Import/Export module.

Universal parser and exporter for BIM requirement formats:
IDS XML, COBie, generic Excel/CSV, Revit Shared Parameters, BIMQ JSON.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    from app.modules.bim_requirements.permissions import (
        register_bim_requirements_permissions,
    )

    register_bim_requirements_permissions()

    from app.modules.bim_requirements.validators import register_bim_requirements_validation_rules

    register_bim_requirements_validation_rules()
