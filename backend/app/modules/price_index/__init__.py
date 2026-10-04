# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Price Index module - base-to-current cost-index adjustment.

Lets an estimator carry costs from a base period and base region to a target
period and region by applying stored construction cost index series and
regional factors. Returns adjusted amounts and the applied factor without
rewriting the source estimate.

Entities:

* :class:`~app.modules.price_index.models.CostIndexSeries` - a named cost
  index (a time series of period factors).
* :class:`~app.modules.price_index.models.CostIndexPoint` - one period/value
  point within a series.
* :class:`~app.modules.price_index.models.LocationFactor` - a regional cost
  factor keyed by region code.
"""

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Module startup hook - register permissions and seed demo reference data.

    Seeding is best-effort and idempotent: a missing table (schema behind the
    module) or a transient DB hiccup logs a warning but never fails boot.
    """
    from app.modules.price_index.permissions import register_price_index_permissions

    register_price_index_permissions()

    try:
        from app.database import async_session_factory
        from app.modules.price_index.seed import seed_price_index_demo, seed_resource_index_samples

        async with async_session_factory() as session:
            await seed_price_index_demo(session)
            await seed_resource_index_samples(session)
            await session.commit()
    except Exception:  # noqa: BLE001 - startup hook must not raise
        logger.warning("Price index demo seed failed at startup", exc_info=True)
