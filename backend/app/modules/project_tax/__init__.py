# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project tax profile: method, election lock, bill standard edition, place of supply."""


async def on_startup() -> None:
    """Register permissions and the ``project_tax`` rule set. Idempotent."""
    from app.modules.project_tax.permissions import register_project_tax_permissions
    from app.modules.project_tax.validators import register_project_tax_rules

    register_project_tax_permissions()
    register_project_tax_rules()
