"""‌⁠‍Subcontractors event subscribers — feed cross-module facts into the rating.

When the NCR / HSE / Quality modules publish an event whose payload names a
``subcontractor_id``, this module bumps the corresponding sub's rating
counters for the *current* period and recomputes the weighted overall score.

The subscriber list is intentionally small (NCR, HSE incidents, schedule
slippage). Each handler opens its own short-lived session via
``async_session_factory()`` so a rating-write failure can never roll back the
upstream module's transaction.

Subscribers wired:
    ``ncr.created``                  → ``bump_rating_from_event(kind="ncr")``
    ``safety.incident.created``      → ``bump_rating_from_event(kind="hse")``
    ``schedule.activity.slipped``    → ``bump_rating_from_event(kind="schedule")``
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.subcontractors.service import SubcontractorService

logger = logging.getLogger(__name__)


def _resolve_sub_id(data: dict[str, object]) -> uuid.UUID | None:
    """‌⁠‍Pull a subcontractor_id out of an event payload (string or UUID).

    Looks at the top-level ``subcontractor_id`` / ``sub_id`` keys first, then
    falls back to a nested ``metadata`` dict. The previous one-liner had an
    operator-precedence bug — the ``if isinstance(...) else None`` ternary
    bound the *entire* ``or`` chain, so every payload without a dict
    ``metadata`` key resolved to ``None`` and the rating bump was silently
    dropped.
    """
    candidate: object | None = data.get("subcontractor_id") or data.get("sub_id")
    if candidate is None:
        meta = data.get("metadata")
        if isinstance(meta, dict):
            candidate = meta.get("subcontractor_id")
    if candidate is None:
        return None
    if isinstance(candidate, uuid.UUID):
        return candidate
    try:
        return uuid.UUID(str(candidate))
    except (ValueError, TypeError):
        return None


async def _bump(kind: str, event: Event) -> None:
    """‌⁠‍Common path: open a session, derive sub_id, bump rating."""
    data = event.data or {}
    sub_id = _resolve_sub_id(data)
    if sub_id is None:
        return
    try:
        async with async_session_factory() as session:
            svc = SubcontractorService(session)
            await svc.bump_rating_from_event(sub_id, kind=kind)
            await session.commit()
    except Exception:
        logger.debug(
            "subcontractors: rating bump for %s/%s failed",
            kind,
            sub_id,
            exc_info=True,
        )


async def _on_ncr_created(event: Event) -> None:
    """``ncr.created`` → +1 NCR for the current month."""
    await _bump("ncr", event)


async def _on_safety_incident_created(event: Event) -> None:
    """``safety.incident.created`` → +1 HSE for the current month."""
    await _bump("hse", event)


async def _on_schedule_slipped(event: Event) -> None:
    """``schedule.activity.slipped`` → +1 schedule-deviation day."""
    await _bump("schedule", event)


_SUBSCRIPTIONS: list[tuple[str, object]] = [
    ("ncr.created", _on_ncr_created),
    ("safety.incident.created", _on_safety_incident_created),
    ("schedule.activity.slipped", _on_schedule_slipped),
]


def register_subcontractor_rating_subscribers() -> None:
    """Wire NCR/HSE/Schedule events into the rating engine.

    Idempotent — :class:`EventBus` deduplicates handlers by identity.
    """
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)  # type: ignore[arg-type]
    logger.info(
        "Subcontractors: subscribed to %d rating-driving event(s)",
        len(_SUBSCRIPTIONS),
    )


# Eagerly register on import — module_loader picks this up when the
# subcontractors module is loaded (same pattern as procurement.events).
register_subcontractor_rating_subscribers()
