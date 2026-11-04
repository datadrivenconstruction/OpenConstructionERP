# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE Advanced module - sister to safety.

Extends Safety with: JSA, Permit-to-Work, Toolbox Talks, PPE tracking,
Audits, CAPA (corrective actions), KPI calculator (TRIR/LTIFR),
and safety certifications. Does NOT modify the base safety module.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions + event subscribers."""
    from app.modules.hse_advanced.events import register_subscribers
    from app.modules.hse_advanced.permissions import register_hse_advanced_permissions

    register_hse_advanced_permissions()
    register_subscribers()

    from app.modules.hse_advanced.validators import register_hse_validation_rules

    register_hse_validation_rules()
