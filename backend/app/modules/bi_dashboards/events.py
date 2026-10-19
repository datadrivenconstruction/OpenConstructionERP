# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""BI Dashboards cross-module subscribers (Wave M4 deep-pass).

BI Dashboards is a *read-only* module - it consumes events from every
other module and feeds them into a lightweight projection layer. The
real per-KPI recompute happens lazily on the next dashboard render
(``service.compute_kpi``). What this module does at event time:

1. Touches the affected KPI's ``last_invalidated_at`` watermark so a
   subsequent ``compute_kpi(persist=True)`` knows the cached snapshot
   is stale.
2. Optionally evaluates alert rules whose ``kpi_code`` is in the
   ``kpi_codes`` payload.

All handlers are fail-soft. Subscribers are gated to PostgreSQL when
they need a writeable session - on SQLite the in-memory dev DB collapses
to a single writer and would deadlock.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


# ── KPI freshness watermarks ────────────────────────────────────────────────
# In-process map of project_id -> {invalidated_at, reason, source_event}. An
# upstream data change bumps the watermark for that project (and the global
# ``"*"`` key). The frontend polls a cheap freshness endpoint and, when the
# watermark advances past what it last saw, refetches the (heavy) EVM/KPI data.
# This gives event-driven live refresh without a WebSocket/SSE transport. The
# map is single-process (matching the in-process schedulers) and resets on
# restart, which the API reports via ``server_started_at`` so a client treats
# data as fresh-since-boot when no invalidation has happened yet.
_SERVER_STARTED_AT = datetime.now(UTC).isoformat()
_GLOBAL_KEY = "*"
_KPI_WATERMARKS: dict[str, dict[str, str | None]] = {}


def _bump_watermark(project_id: str | None, reason: str, source_event: str) -> None:
    """Advance the freshness watermark for a project (and the global key)."""
    now = datetime.now(UTC).isoformat()
    entry = {"invalidated_at": now, "reason": reason, "source_event": source_event}
    _KPI_WATERMARKS[_GLOBAL_KEY] = entry
    if project_id:
        _KPI_WATERMARKS[str(project_id)] = entry


def get_kpi_freshness(project_id: str | None = None) -> dict[str, str | None]:
    """Return the current KPI freshness watermark for a project.

    Falls back to the global watermark when the project has no specific entry
    (an upstream event may not have carried a ``project_id``). Always includes
    ``server_started_at`` so the client can distinguish "fresh since boot" from
    "invalidated at T".
    """
    entry = None
    if project_id:
        entry = _KPI_WATERMARKS.get(str(project_id))
    if entry is None:
        entry = _KPI_WATERMARKS.get(_GLOBAL_KEY)
    return {
        "project_id": str(project_id) if project_id else None,
        "invalidated_at": (entry or {}).get("invalidated_at"),
        "reason": (entry or {}).get("reason"),
        "source_event": (entry or {}).get("source_event"),
        "server_started_at": _SERVER_STARTED_AT,
    }


# Source-of-truth event topics that should invalidate BI projections.
# We listen broadly rather than coupling per-module; the payload's
# optional ``kpi_codes`` decides what to refresh. If the payload omits
# them, every KPI's watermark advances (i.e., universal invalidation).
_PROJECTION_INVALIDATING_EVENTS: tuple[str, ...] = (
    # HSE / safety
    "safety.incident.created",
    "hse.capa.completed",
    "hse.audit.completed",
    "hse.permit.closed",
    # QMS
    "qms.ncr.raised",
    "qms.ncr.closed",
    "qms.audit.completed",
    "qms.punch.closed",
    # Daily Diary
    "daily_diary.closed",
    "daily_diary.signed",
    "daily_diary.workforce.summary",
    # Supplier Catalogs
    "supplier_catalogs.material.added",
    "supplier_catalogs.po.received",
    "supplier_catalogs.invoice.matched",
    "supplier_catalogs.vendor.rated",
    "supplier_catalogs.gr.posted",
    # Schedule Advanced
    "schedule_advanced.actuals_update",
    # Schedule (EVM earned-value depends on activity progress)
    "schedule.activity.progress_updated",
    "schedule.activity.created",
    "schedule.activity.deleted",
    # Cost model (EVM PV/AC + budget consumed depend on these)
    "costmodel.budget_line.created",
    "costmodel.budget_line.updated",
    "costmodel.budget_line.deleted",
    "costmodel.budget.generated",
    "costmodel.snapshot.created",
    "costmodel.snapshot.deleted",
    # Finance (EVM actual cost depends on paid invoices)
    "invoice.paid",
    # Contracts
    "contracts.contract.signed",
    "contracts.claim.certified",
    "contracts.claim.paid",
    # Variations / Change Orders. An approved change order writes the budget
    # delta row EVM reads as BAC.
    "variations.contract_sum.updated",
    "changeorder.approved",
    # Bid Management
    "bid_management.package.awarded",
    # CRM
    "crm.opportunity.won",
    # Carbon
    "carbon.boq_position.assigned",
    # Property Dev
    "property_dev.buyer.contracted",
    "property_dev.handover.completed",
)


async def _on_invalidation_event(event: Event) -> None:
    """Generic handler: forward the event into ``bi_dashboards.kpi_recompute``.

    The real persistence work is deferred to the next dashboard render;
    this handler is a thin re-broadcaster that keeps the BI projection
    layer decoupled from every source module's payload shape.
    """
    data = event.data or {}
    # If the source has already published a ``kpi_recompute`` directly
    # (as our other Wave-M4 subscribers do) skip - avoid duplicate fan-out.
    if event.name == "bi_dashboards.kpi_recompute":
        return
    try:
        payload = {
            "source_module": (event.source_module or "").strip(),
            "source_event": event.name,
            "project_id": data.get("project_id"),
            "kpi_codes": data.get("kpi_codes"),
            "reason": "upstream_event",
        }
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            payload,
            source_module="bi_dashboards",
        )
    except Exception:
        logger.debug(
            "bi_dashboards: invalidation fan-out failed for %s",
            event.name,
            exc_info=True,
        )


async def _on_kpi_recompute(event: Event) -> None:
    """``bi_dashboards.kpi_recompute`` → log + (future) snapshot bump.

    Today this is observability-only; the recompute is lazy on render.
    Once a persistent ``KPIValue`` materialised-view exists, this handler
    will write directly. Keeping the subscriber wired now means the wire
    is in place before the persistence work lands.
    """
    data = event.data or {}
    # Advance the freshness watermark so the next freshness poll tells the
    # frontend to refetch live KPI/EVM values for this project.
    _bump_watermark(
        data.get("project_id"),
        reason=str(data.get("reason") or "upstream_event"),
        source_event=str(data.get("source_event") or ""),
    )
    logger.debug(
        "bi_dashboards: kpi_recompute received src=%s reason=%s kpis=%s project=%s",
        data.get("source_module") or "",
        data.get("reason") or "",
        data.get("kpi_codes") or [],
        data.get("project_id") or "",
    )


def register_subscribers() -> None:
    """Idempotently subscribe BI cross-module handlers."""
    for ev_name in _PROJECTION_INVALIDATING_EVENTS:
        event_bus.subscribe_once(ev_name, _on_invalidation_event)
    event_bus.subscribe_once("bi_dashboards.kpi_recompute", _on_kpi_recompute)
    logger.info(
        "BI Dashboards: %d cross-module subscriber(s) registered",
        len(_PROJECTION_INVALIDATING_EVENTS) + 1,
    )
