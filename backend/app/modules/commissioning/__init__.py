# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Commissioning (Cx) module.

Systems commissioning for construction handover: group work into commissionable
systems (HVAC, electrical, fire, plumbing ...), run prefunctional and functional
checklists, log deficiencies, score each system's readiness, and commission a
system only once every functional check has passed and no critical issue is
open.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.commissioning.permissions import (
        register_commissioning_permissions,
    )

    register_commissioning_permissions()
    from app.modules.commissioning.validators import register_commissioning_validation_rules

    register_commissioning_validation_rules()
