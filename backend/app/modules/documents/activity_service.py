"""‌⁠‍Document activity log — write helpers and read helpers.

The audit log itself is intentionally trivial — there is one writer
(``record_activity``) and one reader (``list_activity``). All callers go
through the helper so the dedupe rule (skip if the same
``(document_id, user_id, action)`` triple fired within the last second)
applies uniformly — duplicate handler invocations on retry must NOT
produce two rows in the timeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.activity_models import DocumentActivity

logger = logging.getLogger(__name__)

# Dedupe window: identical (doc, user, action) events within this many
# seconds collapse to a single row. Mirrors the spec's "skip if last
# entry within 1s with same action+user" hint and keeps double-fired
# event-bus handlers from cluttering the timeline.
_DEDUPE_WINDOW = timedelta(seconds=1)


async def record_activity(
    session: AsyncSession,
    document_id: uuid.UUID,
    user_id: str | None,
    action: str,
    meta: dict[str, Any] | None = None,
) -> DocumentActivity | None:
    """‌⁠‍Append an audit event to ``oe_documents_activity``.

    Returns the new row, or ``None`` when the event was deduped (the
    same ``(document_id, user_id, action)`` triple has been written
    inside the last :data:`_DEDUPE_WINDOW`).

    The helper flushes — but does NOT commit — so the caller can decide
    whether the surrounding transaction should fold the audit row in or
    roll the whole thing back together with the originating mutation.
    Existing service methods follow ``await session.flush()`` +
    ``await session.commit()`` outside the helper.

    Failures are logged and swallowed — audit logging must NEVER break
    the user's primary action.
    """
    try:
        # Dedupe: pull the most-recent row for this (doc, action) pair and
        # compare timestamps in Python. We can't compare ``created_at``
        # against a Python cutoff in SQL because the Base table populates
        # ``created_at`` via ``server_default=CURRENT_TIMESTAMP`` — that's
        # UTC on SQLite and TZ-naive on PostgreSQL, but ``datetime.now()``
        # in this process is local time, so any SQL-side ``>=`` comparison
        # is wrong by the host's UTC offset.  Pulling one row and doing
        # the diff client-side sidesteps that bug entirely.
        stmt = (
            select(DocumentActivity)
            .where(
                DocumentActivity.document_id == document_id,
                DocumentActivity.action == action,
            )
            .order_by(desc(DocumentActivity.created_at))
            .limit(1)
        )
        latest = (await session.execute(stmt)).scalar_one_or_none()
        if latest is not None and latest.user_id == user_id and latest.created_at is not None:
            # Compute the age of the most recent matching row in seconds.
            # ``created_at`` from SQLite is naive-UTC; treating both sides
            # as naive-UTC for the subtraction keeps the maths consistent
            # even on hosts whose local timezone isn't UTC. We normalise
            # tz-aware values (PostgreSQL ``DateTime(timezone=True)``) by
            # stripping the offset before subtracting.
            now_utc = datetime.utcnow()  # noqa: DTZ003 — Base.created_at is naive UTC
            latest_ts = latest.created_at
            if latest_ts.tzinfo is not None:
                latest_ts = latest_ts.replace(tzinfo=None)
            age = now_utc - latest_ts
            if timedelta(0) <= age <= _DEDUPE_WINDOW:
                logger.debug(
                    "Skipping duplicate activity %s for doc %s (user=%s, within %s)",
                    action,
                    document_id,
                    user_id,
                    _DEDUPE_WINDOW,
                )
                return None

        row = DocumentActivity(
            document_id=document_id,
            user_id=str(user_id) if user_id else None,
            action=action,
            meta=meta or {},
        )
        session.add(row)
        await session.flush()
        return row
    except Exception:
        logger.exception(
            "Failed to record document activity (doc=%s action=%s)",
            document_id,
            action,
        )
        return None


async def list_activity(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    limit: int = 20,
) -> list[DocumentActivity]:
    """‌⁠‍Return the newest-first activity rows for a document.

    The endpoint caps ``limit`` at 100 so an attacker can't pull the
    entire audit table through a single query string.
    """
    stmt = (
        select(DocumentActivity)
        .where(DocumentActivity.document_id == document_id)
        .order_by(desc(DocumentActivity.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
