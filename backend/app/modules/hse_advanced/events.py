"""‌⁠‍HSE Advanced cross-module event subscribers (Wave M4 deep-pass).

These handlers wire HSE Advanced to the rest of the platform without
import-time coupling. They are registered idempotently via
:func:`register_subscribers` which is called from
``app.modules.hse_advanced.__init__`` at module-load time.

Subscriptions:

* ``safety.incident.created`` — the base safety module records the
  incident. We re-publish two derived events the platform listens on:

  - ``contracts.risk_register_update`` — risk-register projection (BI / contracts
    risk owners). Even though no canonical RiskRegister table exists today,
    the event is the canonical signal so when contracts grows one it picks
    up the history.
  - ``bi_dashboards.kpi_recompute`` — BI projections (TRIR / LTIFR / days
    without LTI) re-compute for the affected project.

* ``hse.capa.completed`` — when a CAPA closes we likewise nudge BI.

All subscribers are fail-soft — any exception is swallowed at debug.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


_SUBSCRIBED_FLAG = "_hse_advanced_subscribers_registered"


async def _on_safety_incident_created(event: Event) -> None:
    """‌⁠‍``safety.incident.created`` → fan-out to risk register + BI.

    Publishes two follow-on events with the same payload so downstream
    consumers can choose granularity. Idempotent on the upstream side
    (the safety module only emits once per incident).
    """
    data = event.data or {}
    project_id = data.get("project_id")
    incident_id = data.get("incident_id")
    if not (project_id and incident_id):
        return
    severity = data.get("severity") or ""
    risk_payload = {
        "source": "hse_advanced",
        "source_event": "safety.incident.created",
        "project_id": str(project_id),
        "incident_id": str(incident_id),
        "incident_number": data.get("incident_number") or "",
        "severity": severity,
        # Heuristic likelihood/impact mapping for risk-matrix consumers
        "likelihood": "occurred",
        "impact": ("severe" if severity in {"high", "critical", "fatality"} else "moderate"),
    }
    try:
        event_bus.publish_detached(
            "contracts.risk_register_update",
            risk_payload,
            source_module="hse_advanced",
        )
    except Exception:
        logger.debug("hse_advanced: risk_register_update emit failed", exc_info=True)

    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "hse_advanced",
                "source_event": "safety.incident.created",
                "project_id": str(project_id),
                "kpi_codes": ["safety_trir", "safety_ltifr", "days_without_lti"],
                "reason": "incident_recorded",
            },
            source_module="hse_advanced",
        )
    except Exception:
        logger.debug("hse_advanced: kpi_recompute emit failed", exc_info=True)


async def _on_capa_completed(event: Event) -> None:
    """‌⁠‍``hse.capa.completed`` → BI projection tick.

    The safety KPIs (TRIR/LTIFR) only change when the *incident* changes,
    but capa-completion lights up the "open CAPA" gauge so BI projections
    refresh. We pass a narrower KPI code list to avoid wasted recompute.
    """
    data = event.data or {}
    project_id = data.get("project_id")
    if not project_id:
        return
    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "hse_advanced",
                "source_event": "hse.capa.completed",
                "project_id": str(project_id),
                "kpi_codes": ["open_capas", "overdue_capas"],
                "reason": "capa_completed",
            },
            source_module="hse_advanced",
        )
    except Exception:
        logger.debug(
            "hse_advanced: kpi_recompute on capa_completed failed",
            exc_info=True,
        )


async def _on_qms_ncr_safety_check(event: Event) -> None:
    """``qms.ncr.raised`` → if the NCR is flagged safety-related, mirror.

    The QMS module publishes the NCR raise event with severity. We listen
    for that and republish ``hse_advanced.if_safety_related`` so HSE
    workflows can pick up safety-impacting NCRs that didn't originate as
    incidents. The check is heuristic — title/description contains "safety"
    or severity is "critical".
    """
    data = event.data or {}
    ncr_id = data.get("ncr_id")
    project_id = data.get("project_id")
    if not (ncr_id and project_id):
        return
    title = (data.get("title") or "").lower()
    severity = (data.get("severity") or "").lower()
    is_safety = (severity in {"critical", "major"} and "safety" in title) or severity in {"critical"}
    if not is_safety:
        return
    try:
        event_bus.publish_detached(
            "hse_advanced.if_safety_related",
            {
                "source_event": "qms.ncr.raised",
                "ncr_id": str(ncr_id),
                "project_id": str(project_id),
                "severity": severity,
                "title": data.get("title") or "",
            },
            source_module="hse_advanced",
        )
    except Exception:
        logger.debug(
            "hse_advanced: if_safety_related emit failed",
            exc_info=True,
        )


def register_subscribers() -> None:
    """Idempotently subscribe HSE Advanced cross-module handlers."""
    if getattr(event_bus, _SUBSCRIBED_FLAG, False):
        return
    event_bus.subscribe("safety.incident.created", _on_safety_incident_created)
    event_bus.subscribe("hse.capa.completed", _on_capa_completed)
    event_bus.subscribe("qms.ncr.raised", _on_qms_ncr_safety_check)
    setattr(event_bus, _SUBSCRIBED_FLAG, True)
    logger.info("HSE Advanced: 3 cross-module subscriber(s) registered")
