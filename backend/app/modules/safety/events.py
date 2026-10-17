# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Safety module event registry and cross-module subscribers.

Events the safety module *publishes* (canonical names, payload shapes):

* ``safety.incident.created`` - emitted on every incident create. Payload:
  ``{project_id, incident_id, incident_number, incident_type, severity,
  description}``. HSE Advanced and BI listen to recompute TRIR/LTIFR.
* ``safety.observation.high_risk`` - emitted when an observation's
  ``risk_score`` exceeds 15 (on create or update). Payload includes
  ``risk_score`` and ``notify_user_ids``.
* ``safety.threshold_alert_triggered`` - emitted by
  :meth:`SafetyService.get_threshold_alert` when the current LTIFR or TRIR
  lands in the yellow/red band. Payload:
  ``{project_id, ltifr, trir, baseline_ltifr, baseline_trir, ltifr_status,
  trir_status}``. This is the early-warning signal for BI dashboards and
  (Phase 2) email/Slack notifications.

Subscribers registered here are fail-soft: any handler exception is swallowed
at debug so a downstream projection can never block the safety request.
Registration is idempotent via :func:`register_subscribers`, called from
``app.modules.safety.__init__.on_startup`` at module-load time.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_threshold_alert(event: Event) -> None:
    """``safety.threshold_alert_triggered`` → BI KPI recompute nudge.

    A non-green LTIFR/TRIR is the signal BI dashboards watch to refresh the
    safety-rate gauges. We forward a narrow KPI code list so the recompute
    stays cheap and scoped to the affected project.
    """
    data = event.data or {}
    project_id = data.get("project_id")
    if not project_id:
        return
    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "safety",
                "source_event": "safety.threshold_alert_triggered",
                "project_id": str(project_id),
                "kpi_codes": ["safety_trir", "safety_ltifr"],
                "reason": "threshold_alert",
                "ltifr_status": data.get("ltifr_status"),
                "trir_status": data.get("trir_status"),
            },
            source_module="safety",
        )
    except Exception:
        logger.debug("safety: kpi_recompute on threshold_alert failed", exc_info=True)


def register_subscribers() -> None:
    """Idempotently subscribe the safety module's cross-module handlers."""
    event_bus.subscribe_once("safety.threshold_alert_triggered", _on_threshold_alert)
    logger.info("Safety: 1 cross-module subscriber(s) registered")
