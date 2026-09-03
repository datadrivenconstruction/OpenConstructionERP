# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests - one intake spine for every department.

A PM who needs a switchboard built raises ONE request: the workshop knows
when, who and how; it moves through the department's own stages (drawings
received → materials → build → wiring → testing → FAT → delivered); hours
are logged against the quote so cost-to-complete and deviation are live;
drafting is handed off as a child request the board waits on; the planner
shows people per board per day for the next five weeks; and every change
rings the right person's bell.

Departments (engineering, drafting, workshop, automation, hazardous area)
are seeded on first start and fully editable - stages, request types and
their extra questions are data, not code.
"""

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Register permissions, plant the default departments, then top a
    live install up with what a later release added (all idempotent).

    The seed only ever fires on a database with NO department, so an
    install that started before a release would never see a new request
    type or the hazardous-area colour. ``reconcile_seeded_departments``
    closes that gap additively: it appends missing seeded types and never
    touches one the owner has edited, reordered or retired.

    Best-effort: a DB hiccup logs a warning but never fails module boot.
    The departments list also self-seeds on first read, so a failed seed
    here costs nothing but a log line.
    """
    from app.modules.work_requests.permissions import register_work_requests_permissions

    register_work_requests_permissions()

    try:
        from app.database import async_session_factory
        from app.modules.work_requests.seeds import reconcile_seeded_departments, seed_departments_if_empty

        async with async_session_factory() as session:
            if not await seed_departments_if_empty(session):
                await reconcile_seeded_departments(session)
            await session.commit()
    except Exception:  # noqa: BLE001 - startup hook must not raise.
        logger.warning("Work request department seed failed at startup", exc_info=True)
