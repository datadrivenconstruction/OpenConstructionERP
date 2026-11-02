# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner bid schedule round trip: import the owner's pay items, price them, write them back.

Neutral layer over the BOQ. Owner formats are declarative profiles (platform,
packs, user wizard); GAEB XML stays on the GAEB exchange path.
"""

from app.modules.owner_schedule.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.owner_schedule.permissions import register_owner_schedule_permissions
    from app.modules.owner_schedule.validators import register_owner_schedule_rules

    register_owner_schedule_permissions()
    register_owner_schedule_rules()
