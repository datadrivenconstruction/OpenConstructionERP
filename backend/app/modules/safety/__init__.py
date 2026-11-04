# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Safety module.

Safety incident reporting and observation tracking - injuries, near misses,
property damage, environmental incidents, and proactive safety observations.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and event subscribers."""
    from app.modules.safety.events import register_subscribers
    from app.modules.safety.permissions import register_safety_permissions

    register_safety_permissions()
    register_subscribers()

    from app.modules.safety.validators import register_safety_validation_rules

    register_safety_validation_rules()
