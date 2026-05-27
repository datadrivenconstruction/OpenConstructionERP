"""‌⁠‍Audit-log PII pruning task (Epic H §H8).

GDPR Article 5(1)(e) — storage limitation. The capture-context columns
added in Epic H (``ip_address`` / ``user_agent``) are personal data even
when the actor cannot be re-identified by name (e.g. a leaked IP can be
tied to a household). To stay compliant we MUST scrub those two columns
on rows older than the configured retention window without dropping the
audit row itself — the rest of the row (entity_type, action, from/to
status, …) is operational data the customer needs for FIDIC / SCL
dispute timelines and stays untouched.

The function is exposed as both a plain async coroutine (for unit tests
and ad-hoc CLI invocation) and as a Celery task (for production beat
scheduling once Celery beat is wired up). Both code paths share
:func:`_prune_query`, which is the only place that touches the database.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog

logger = logging.getLogger(__name__)

# 180 days mirrors the SCL Protocol "two-year live history" plus a buffer
# for dispute escalation. Operators can override via env (handled at the
# scheduler layer, not here).
DEFAULT_PII_RETENTION_DAYS = 180


async def prune_audit_pii(
    session: AsyncSession,
    *,
    retention_days: int = DEFAULT_PII_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Null-out IP / UA on activity-log rows older than ``retention_days``.

    Returns the row count that was scrubbed (NULL was written).  Rows
    that already had both columns NULL are not counted — the UPDATE
    skips them via the ``OR``-ed NOT NULL predicate.
    """
    threshold = (now or datetime.now(UTC)) - timedelta(days=retention_days)

    stmt = (
        update(ActivityLog)
        .where(ActivityLog.created_at < threshold)
        .where(
            (ActivityLog.ip_address.isnot(None)) | (ActivityLog.user_agent.isnot(None)),
        )
        .values(ip_address=None, user_agent=None)
        # ``synchronize_session=False`` skips the ORM-side row evaluator,
        # which trips over naive-vs-aware datetime comparisons on SQLite
        # (the dialect strips tzinfo on read). The DB-side comparison is
        # correct on both SQLite and PostgreSQL; the prune task does not
        # rely on in-session object state being refreshed in lockstep.
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    await session.flush()
    affected = int(result.rowcount or 0)
    logger.info(
        "audit_prune: scrubbed IP+UA on %d activity-log rows older than %s",
        affected,
        threshold.isoformat(),
    )
    return affected


# ── Celery task wrapper ───────────────────────────────────────────────


def register_prune_task() -> None:
    """Late-bound Celery registration.

    Importing celery at module-load time would couple every test that
    touches ``audit_log`` to a Redis broker. Registration happens via
    explicit call from the worker bootstrap so the prod celery process
    picks the task up while the test process does not.
    """
    try:
        from app.core.jobs import celery_app  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover — jobs module not wired
        logger.debug("audit_prune: celery app not available, skipping task registration")
        return

    @celery_app.task(name="oe.audit_prune_pii")  # type: ignore[misc]
    def _prune_audit_pii_celery(
        retention_days: int = DEFAULT_PII_RETENTION_DAYS,
    ) -> int:  # pragma: no cover — exercised at worker level
        import asyncio

        from app.database import async_session_factory

        async def _run() -> int:
            async with async_session_factory() as session:
                count = await prune_audit_pii(
                    session,
                    retention_days=retention_days,
                )
                await session.commit()
                return count

        return asyncio.run(_run())
