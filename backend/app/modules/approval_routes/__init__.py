# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval Routes module.

Generic multi-step approval engine. Every other module that needs a
routed sign-off workflow (markup approval, submittal review, change
order, RFI, contract signature, …) starts an :class:`Instance` against
this module's tables instead of inventing its own approve/reject schema.

Schema
~~~~~~

* :class:`Route` - template/definition (project-scoped or tenant-wide)
* :class:`Step` - ordered approver slot inside a route
* :class:`Instance` - running workflow against a concrete target row
* :class:`StepState` - per-step decision (pending → approved/rejected)

The engine deliberately does NOT touch the target tables; consumers
read ``status`` and ``current_step_ordinal`` off the instance row and
render their own UI.
"""

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions and seed presets.

    The preset seed is best-effort: a missing table (schema behind the model)
    or a transient DB error logs a warning but never fails module boot, matching
    the seeding pattern used by the other auto-installed modules.
    """
    from app.modules.approval_routes.permissions import register_approval_route_permissions

    register_approval_route_permissions()

    try:
        from app.database import async_session_factory
        from app.modules.approval_routes.seed import seed_approval_route_presets

        async with async_session_factory() as session:
            await seed_approval_route_presets(session)
            await session.commit()
    except Exception:  # noqa: BLE001 - startup hook must not raise.
        logger.warning("Approval-route preset seed failed at startup", exc_info=True)
