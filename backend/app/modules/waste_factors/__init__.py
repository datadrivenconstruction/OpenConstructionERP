# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Waste Factors module - net-to-gross quantity adjustment library.

A shared library of waste, lap and coverage multipliers per material or work
category. It converts net measured (drawn) quantities into gross procurement
quantities (``gross = net * factor``) so purchase quantities reflect real site
consumption - rebar laps, tile breakage, concrete over-pour - rather than the
drawn quantity alone.

The package does no import-time database work: the pure engine
(:mod:`app.modules.waste_factors.waste_math`) imports on any interpreter, and
permission registration plus the idempotent default-library seed are deferred to
:func:`on_startup` (called by the module loader), mirroring the other business
modules.
"""

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Register permissions and seed the default factor library (idempotent).

    Best-effort: a missing table (schema behind the model) or a transient DB
    error logs a warning but never fails module boot, matching the seeding
    pattern used by the other auto-installed modules.
    """
    from app.modules.waste_factors.permissions import register_waste_factors_permissions

    register_waste_factors_permissions()
    from app.modules.waste_factors.validators import register_waste_factors_validation_rules

    register_waste_factors_validation_rules()

    try:
        from app.database import async_session_factory
        from app.modules.waste_factors.seed import seed_waste_factors

        async with async_session_factory() as session:
            await seed_waste_factors(session)
            await session.commit()
    except Exception:  # noqa: BLE001 - startup hook must not raise.
        logger.warning("Waste-factor default seed failed at startup", exc_info=True)
