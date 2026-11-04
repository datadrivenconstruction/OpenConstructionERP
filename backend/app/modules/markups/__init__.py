# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Markups & Annotations module.

Provides drawing markups, scale calibration, and stamp templates
for document annotation workflows in construction projects.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and seed default stamps."""
    from app.modules.markups.permissions import register_markups_permissions

    register_markups_permissions()
    from app.modules.markups.validators import register_markups_validation_rules

    register_markups_validation_rules()
