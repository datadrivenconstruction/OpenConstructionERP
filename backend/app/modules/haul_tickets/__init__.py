# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets module: one ticket per truck load to or from site.

Composes site logistics (expected deliveries, transports), the equipment fleet
(own trucks), procurement (purchase orders) and the bill (positions, cost codes)
through soft links, so each of them can be switched off without breaking tickets.
"""

from app.modules.haul_tickets.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.haul_tickets.permissions import register_haul_tickets_permissions
    from app.modules.haul_tickets.validators import register_haul_tickets_rules

    register_haul_tickets_permissions()
    register_haul_tickets_rules()
