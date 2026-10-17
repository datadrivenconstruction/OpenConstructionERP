# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closeout cross-module subscribers (freshness).

When closure evidence changes (a punch item closes, an inspection completes,
a CDE document is published / updated) the project's closeout package is
marked stale: its built-ZIP stamp is cleared and ``ready``/``issued`` drops
back to ``in_progress`` so the UI prompts a rebuild. Best-effort and
idempotent - a failure here never blocks the originating workflow.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from app.core.events import event_bus
from app.database import async_session_factory
from app.modules.closeout.repository import CloseoutRepository

if TYPE_CHECKING:
    from app.core.events import Event

logger = logging.getLogger(__name__)


# Events that should mark a project's closeout package stale.
_STALE_EVENTS = (
    "punchlist.item.status_changed",
    "inspection.completed.failed",
    "inspection.completed.passed",
    "documents.document.updated",
)


def _coerce_uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _mark_project_package_stale(event: Event) -> None:
    """Clear the built-package stamp for the event's project, if a package exists."""
    data = event.data or {}
    project_id = _coerce_uuid(data.get("project_id"))
    if project_id is None:
        return
    try:
        async with async_session_factory() as session:
            repo = CloseoutRepository(session)
            package = await repo.get_package_for_project(project_id)
            if package is None:
                return
            # Only act when there is something to invalidate.
            if package.package_key is None and package.last_built_at is None and package.status != "issued":
                return
            package.package_key = None
            package.last_built_at = None
            package.last_built_job_id = None
            if package.status in ("ready", "issued"):
                package.status = "in_progress"
            session.add(package)
            await session.commit()
            logger.debug("closeout: marked package %s stale on event %s", package.id, event.name)
    except Exception:  # noqa: BLE001 - best-effort, never block the source workflow
        logger.debug("closeout: stale-mark failed for event %s", event.name, exc_info=True)


def register_closeout_subscribers() -> None:
    """Subscribe the freshness handler to closure-evidence events (idempotent)."""
    for name in _STALE_EVENTS:
        event_bus.subscribe_once(name, _mark_project_package_stale)
    logger.info("closeout: subscribed to %d freshness event(s)", len(_STALE_EVENTS))
