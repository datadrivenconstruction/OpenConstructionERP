# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bill of Quantities module.

Provides BOQ management with hierarchical positions, cost calculations,
and integration with project and validation modules.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and the markup rules.

    The validators register themselves at import time too. Both routes are
    kept because the platform has two ways of bringing a module up and a rule
    that only takes one of them is dormant in the other deployment.
    """
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.boq.validators import register_boq_markup_rules, register_boq_resource_rules

    register_boq_permissions()
    register_boq_markup_rules()
    register_boq_resource_rules()
