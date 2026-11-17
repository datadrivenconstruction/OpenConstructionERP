# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed original estimate: frozen, fingerprinted, opened only with a record.

The estimate behind the tendered rates is copied into an append-only seal with
a SHA-256 fingerprint. Internal estimating and management roles may read it,
every read logged; a counterparty sees it only inside a recorded opening.
Changes are priced from the sealed resource lines and markup stack, side by
side with cost plus; a person records which method applies.
"""

import logging

logger = logging.getLogger(__name__)


async def _ensure_seal_guard() -> None:
    """Install the PostgreSQL immutability trigger where the table exists and the trigger does not."""
    from app.database import engine
    from app.modules.estimate_archive.models import EstimateSeal, install_seal_guard

    if engine.dialect.name != "postgresql":
        return
    try:
        async with engine.begin() as conn:
            table = (await conn.exec_driver_sql(f"SELECT to_regclass('{EstimateSeal.__tablename__}')")).scalar()
            present = (
                await conn.exec_driver_sql(
                    "SELECT 1 FROM pg_trigger WHERE tgname = 'oe_estimate_archive_seal_guard' AND NOT tgisinternal"
                )
            ).scalar()
            if table is not None and present is None:
                await conn.run_sync(install_seal_guard)
                logger.info("estimate_archive: immutability trigger installed")
    except Exception:  # noqa: BLE001 - startup must not fail on a guard the ORM also enforces
        logger.warning("estimate_archive: could not install the immutability trigger", exc_info=True)


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.estimate_archive.permissions import register_estimate_archive_permissions
    from app.modules.estimate_archive.validators import register_estimate_archive_rules

    register_estimate_archive_permissions()
    register_estimate_archive_rules()
    await _ensure_seal_guard()
