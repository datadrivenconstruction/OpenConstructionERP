# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accommodation module - worker camps, rental apartments, hotels.

A unified module covering three accommodation use-cases via one entity
model. The ``kind`` discriminator on :class:`Accommodation` selects:

* ``worker_camp`` - free, employer-owned housing for project crews
* ``rental``      - paid, third-party tenants (apartments, long stays)
* ``hotel``       - short-stay, daily-rate guest housing

The downstream entities (Room / Booking / Charge) are shared across all
three kinds - differences are configuration on the parent Accommodation,
not different tables.

Cross-module integrations are optional (BIM model link, PropDev block
bootstrap) and guarded in code so the module continues to work when those
modules are disabled.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.accommodation.permissions import (
        register_accommodation_permissions,
    )

    register_accommodation_permissions()
    from app.modules.accommodation.validators import register_accommodation_validation_rules

    register_accommodation_validation_rules()
