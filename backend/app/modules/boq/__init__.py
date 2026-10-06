# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bill of Quantities module.

Provides BOQ management with hierarchical positions, cost calculations,
and integration with project and validation modules.
"""

import logging


async def on_startup() -> None:
    """Module startup hook - register permissions and the markup rules.

    The validators register themselves at import time too. Both routes are
    kept because the platform has two ways of bringing a module up and a rule
    that only takes one of them is dormant in the other deployment.
    """
    from app.modules.boq import import_jobs
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.boq.validators import register_boq_markup_rules, register_boq_resource_rules

    register_boq_permissions()
    import_jobs.register_boq_import_job_handler()
    # A crash between an upload and the end of its job leaves the file behind.
    try:
        import_jobs.sweep_stale_uploads()
    except Exception:  # noqa: BLE001 - housekeeping never stops the module from starting
        logging.getLogger(__name__).warning("Sweeping stale import uploads failed", exc_info=True)
    register_boq_markup_rules()
    register_boq_resource_rules()
