# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assemblies & Calculations module.

Provides composite cost items (assemblies / calculations) built from
cost database entries with factors. Supports templates, regional factors,
cloning, and integration with the BOQ module.
"""

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Module startup hook - register permissions, subscribers, and seed
    the platform-wide Assembly Library templates (idempotent)."""
    from app.modules.assemblies.events import register_assemblies_subscribers
    from app.modules.assemblies.permissions import register_assemblies_permissions

    register_assemblies_permissions()
    register_assemblies_subscribers()
    from app.modules.assemblies.validators import register_assemblies_validation_rules

    register_assemblies_validation_rules()

    # Seed the canonical Assembly Library on startup. Best-effort: a
    # missing table (alembic head behind v40) or a DB hiccup logs a
    # warning but never fails module boot.
    try:
        from app.database import async_session_factory
        from app.modules.assemblies.repository import seed_assembly_templates

        async with async_session_factory() as session:
            await seed_assembly_templates(session)
    except Exception:  # noqa: BLE001 - startup hook must not raise.
        logger.warning("Assembly templates seed failed at startup", exc_info=True)
