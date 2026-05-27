"""‌⁠‍Risk event handlers — vector indexing for lessons-learned reuse.

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
    """‌⁠‍Re-embed a single RiskItem row after create / update."""
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
            project_id = str(row.project_id) if row.project_id is not None else None
            await vector_index_one(
                risk_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Risk vector index failed for %s", rid_raw, exc_info=True)


async def _delete_risk_vector(event: Event) -> None:
    """‌⁠‍Remove a deleted RiskItem row from the vector store."""
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


# ── HSE → Risk Register projection ───────────────────────────────────────


async def _can_open_isolated_session() -> bool:
    """‌⁠‍Return True only when we can safely write from a subscriber.

    Matches the gate used by notifications/qms subscribers: SQLite (dev)
    has a single-writer lock, so opening a second session inside an event
    handler while the publisher is still holding the request transaction
    would deadlock. We only auto-materialise risk register rows on
    PostgreSQL.
    """
    try:
        async with async_session_factory() as probe:
            bind = probe.get_bind()
            dialect = getattr(getattr(bind, "dialect", None), "name", "") or ""
        return dialect == "postgresql"
    except Exception:
        return False


_HSE_SEVERITY_TO_RISK_TIER: dict[str, str] = {
    "fatality": "extreme",
    "critical": "high",
    "high": "high",
    "major": "high",
    "medium": "medium",
    "moderate": "medium",
    "low": "low",
    "minor": "low",
}


async def _on_contracts_risk_register_update(event: Event) -> None:
    """‌⁠‍``contracts.risk_register_update`` → materialise a RiskItem.

    Published by ``hse_advanced/events.py::_on_safety_incident_created``
    when a safety incident is recorded. The risk register is the
    canonical home for the resulting "this incident is now a tracked
    risk" projection — without this subscriber the publish was orphaned
    and the incident never appeared in the risk dashboard.

    Idempotency: keyed on ``incident_id`` stored in ``risk.metadata_``
    under ``source_incident_id``. Re-firing the event is safe — the
    second invocation will see the existing row and skip.

    Fail-soft: any error is logged at debug; the upstream incident
    creation must never fail because of a downstream projection.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    project_id_raw = data.get("project_id")
    incident_id_raw = data.get("incident_id")
    if not (project_id_raw and incident_id_raw):
        return
    try:
        project_id = uuid.UUID(str(project_id_raw))
    except (ValueError, TypeError):
        return
    severity = (data.get("severity") or "minor").lower()
    incident_number = data.get("incident_number") or ""
    impact = data.get("impact") or "moderate"
    likelihood = data.get("likelihood") or "occurred"

    try:
        async with async_session_factory() as session:
            # Idempotency check — look for any existing RiskItem with
            # matching source_incident_id in metadata.
            stmt = select(RiskItem).where(RiskItem.project_id == project_id)
            existing_rows = (await session.execute(stmt)).scalars().all()
            incident_id_str = str(incident_id_raw)
            for row in existing_rows:
                md = row.metadata_ if isinstance(row.metadata_, dict) else {}
                if md.get("source_incident_id") == incident_id_str:
                    logger.debug(
                        "risk: incident %s already projected → risk %s",
                        incident_id_str,
                        row.id,
                    )
                    return

            tier = _HSE_SEVERITY_TO_RISK_TIER.get(severity, "medium")
            code = (f"HSE-{incident_number}" if incident_number else f"HSE-{incident_id_str[:8].upper()}")[:50]
            title = (
                f"Safety incident → risk projection ({incident_number})"
                if incident_number
                else f"Safety incident → risk projection ({incident_id_str[:8]})"
            )[:255]
            risk = RiskItem(
                project_id=project_id,
                code=code,
                title=title,
                description=(
                    f"Auto-projected from HSE incident {incident_id_str} "
                    f"(severity={severity}, likelihood={likelihood}, "
                    f"impact={impact})."
                ),
                category="safety",
                probability="0.9",  # occurred → near-certain forward likelihood
                impact_cost="0",
                impact_schedule_days=0,
                impact_severity=tier,
                risk_score="0",
                status="identified",
                mitigation_strategy="",
                contingency_plan="",
                owner_name="",
                response_cost="0",
                currency="",
            )
            risk.metadata_ = {
                "source": "hse_advanced",
                "source_event": "contracts.risk_register_update",
                "source_incident_id": incident_id_str,
                "source_incident_number": incident_number,
                "hse_severity": severity,
                "hse_impact": impact,
                "hse_likelihood": likelihood,
            }
            session.add(risk)
            await session.commit()
            logger.info(
                "risk: auto-projected incident %s → RiskItem %s (tier=%s)",
                incident_id_str,
                risk.id,
                tier,
            )
    except Exception:
        logger.debug(
            "risk: _on_contracts_risk_register_update failed",
            exc_info=True,
        )


event_bus.subscribe(
    "contracts.risk_register_update",
    _on_contracts_risk_register_update,
)
