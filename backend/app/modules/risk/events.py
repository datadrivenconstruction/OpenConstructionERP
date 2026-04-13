"""Risk event handlers — vector indexing for lessons-learned reuse.

Subscribes to ``risk.risk.*`` events and keeps the ``oe_risks`` vector
collection in sync with the underlying :class:`RiskItem` rows.  Risks
have the **highest cross-project semantic-search value** of any module —
an estimator on a new project wants to instantly pull up "similar risks
we already faced" across the entire tenant history so they can reuse the
mitigation strategy, contingency plan and budget reserve.

This module is auto-imported by the module loader when the ``oe_risk``
module is loaded (see ``module_loader._load_module`` → ``events.py``).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.risk.models import RiskItem
from app.modules.risk.vector_adapter import risk_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Each handler opens its own short-lived session, loads the risk row and
# forwards it to the adapter.  Failures are logged and swallowed —
# vector indexing is best-effort and must never break a normal CRUD
# path.  This mirrors the BOQ implementation exactly.


async def _index_risk(event: Event) -> None:
    """Re-embed a single RiskItem row after create / update."""
    rid_raw = (event.data or {}).get("risk_id")
    if not rid_raw:
        return
    try:
        risk_id = uuid.UUID(str(rid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = select(RiskItem).where(RiskItem.id == risk_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(risk_vector_adapter, str(risk_id))
                return
            project_id = (
                str(row.project_id) if row.project_id is not None else None
            )
            await vector_index_one(
                risk_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Risk vector index failed for %s", rid_raw, exc_info=True)


async def _delete_risk_vector(event: Event) -> None:
    """Remove a deleted RiskItem row from the vector store."""
    rid_raw = (event.data or {}).get("risk_id")
    if not rid_raw:
        return
    try:
        await vector_delete_one(risk_vector_adapter, str(rid_raw))
    except Exception:
        logger.debug("Risk vector delete failed for %s", rid_raw, exc_info=True)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_risk_created(event: Event) -> None:
    await _index_risk(event)


async def _on_risk_updated(event: Event) -> None:
    await _index_risk(event)


async def _on_risk_deleted(event: Event) -> None:
    await _delete_risk_vector(event)


event_bus.subscribe("risk.risk.created", _on_risk_created)
event_bus.subscribe("risk.risk.updated", _on_risk_updated)
event_bus.subscribe("risk.risk.deleted", _on_risk_deleted)
