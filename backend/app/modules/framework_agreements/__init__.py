# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreements and call-off orders."""


async def on_startup() -> None:
    """Module startup hook: register permissions and the ``framework_agreement`` rule set."""
    from app.modules.framework_agreements.permissions import register_framework_permissions
    from app.modules.framework_agreements.validators import register_framework_rules

    register_framework_permissions()
    register_framework_rules()
