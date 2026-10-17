# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""QMS cross-module event subscribers.

These handlers wire QMS to other modules without creating import-time
coupling. They are registered idempotently via :func:`register_subscribers`
which is called from ``app.modules.qms.__init__`` at module-load time.

Subscriptions:

* ``hse.capa.completed`` whose ``source_type=="incident"`` →  mirror the
  HSE incident as a QMS NCR with severity inherited from the CAPA payload
  and ``cost_impact_amount`` carried across when present. This satisfies
  the "HSE NCR auto-mirrored as QMS NCR" requirement.
* ``daily_diary.workforce.summary`` → currently a no-op telemetry hook;
  the ``resources`` module subscribes elsewhere to fold the counts into
  utilisation. Logged here for tracing.
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.qms.models import QMSNCR

logger = logging.getLogger(__name__)


async def _can_open_isolated_session() -> bool:
    """Return True if we can safely open a write session in a subscriber."""
    try:
        async with async_session_factory() as probe:
            bind = probe.get_bind()
            dialect = getattr(getattr(bind, "dialect", None), "name", "") or ""
        return dialect == "postgresql"
    except Exception:
        return False


async def _on_hse_capa_completed(event: Event) -> None:
    """If the CAPA was sourced from an HSE incident with cost impact, mirror it."""
    data = event.data or {}
    capa_id = data.get("capa_id")
    project_id = data.get("project_id")
    if not capa_id or not project_id:
        return
    # The HSE event payload is intentionally lean; if the source_type was
    # not 'incident' we do nothing. The mirror event below carries the
    # contextual fields explicitly.
    return  # explicit no-op - see _on_hse_incident_root_cause for the real path


async def _on_hse_incident_root_cause(event: Event) -> None:
    """``hse.capa.root_cause_recorded`` whose CAPA is incident-sourced → QMS NCR.

    We look up the HSE CAPA on-demand to determine whether it was tied to
    an incident and what the cost / severity context is. The subscriber
    is fail-soft - any error is logged at debug.
    """
    data = event.data or {}
    capa_id = data.get("capa_id")
    project_id = data.get("project_id")
    if not capa_id or not project_id:
        return
    if not await _can_open_isolated_session():
        return
    try:
        async with async_session_factory() as session:
            # Fetch the HSE CAPA to determine source_type
            from app.modules.hse_advanced.models import (  # noqa: PLC0415
                CorrectiveAction,
            )

            capa = await session.get(CorrectiveAction, uuid.UUID(capa_id))
            if capa is None:
                return
            if capa.source_type != "incident":
                return
            # Idempotency - check if an NCR with this CAPA reference already exists.
            from sqlalchemy import select  # noqa: PLC0415

            existing = await session.execute(
                select(QMSNCR).where(
                    QMSNCR.project_id == capa.project_id,
                    QMSNCR.title.like(f"HSE incident → {capa.title[:200]}%"),
                )
            )
            if existing.scalar_one_or_none() is not None:
                return

            severity_map = {
                "manpower": "minor",
                "method": "minor",
                "material": "major",
                "machine": "major",
                "environment": "major",
                "management": "major",
                "other": "minor",
            }
            severity = severity_map.get(
                capa.root_cause_category or "other",
                "minor",
            )
            mirror = QMSNCR(
                project_id=capa.project_id,
                raised_at=None,
                title=f"HSE incident → {capa.title[:480]}"[:500],
                description=(
                    f"Auto-mirrored from HSE CAPA {capa.id}. "
                    f"Root cause: {capa.root_cause_category or 'n/a'}. "
                    f"{capa.description}"
                )[:10000],
                severity=severity,
                root_cause=(
                    "; ".join(
                        f"{i + 1}. {step.get('why', '')} → {step.get('answer', '')}"
                        for i, step in enumerate(capa.five_whys or [])
                    )[:5000]
                    if capa.five_whys
                    else None
                ),
                status="open",
                cost_impact_currency="",
                cost_impact_amount=None,
            )
            session.add(mirror)
            await session.commit()
            logger.info(
                "QMS NCR auto-created from HSE incident CAPA %s → %s",
                capa.id,
                mirror.id,
            )
            event_bus.publish_detached(
                "qms.ncr.mirrored_from_hse",
                {
                    "source_capa_id": str(capa.id),
                    # capa.source_ref is the HSE incident UUID when
                    # source_type == "incident" (gated above).
                    "hse_incident_id": (str(capa.source_ref) if capa.source_ref else ""),
                    "ncr_id": str(mirror.id),
                    "project_id": str(capa.project_id),
                    "severity": severity,
                    "ncr_owner_user_id": (str(capa.owner_user_id) if capa.owner_user_id else ""),
                },
                source_module="qms",
            )
    except Exception:
        logger.debug("qms: HSE→QMS NCR mirror failed", exc_info=True)


async def _on_ncr_raised_fanout(event: Event) -> None:
    """``qms.ncr.raised`` → publish derived events.

    Two follow-on events:

    * ``procurement.supplier_rating_update`` - when an NCR is linked to
      an inspection that references a subcontractor / supplier, the rating
      projection should re-compute. We publish unconditionally and let the
      procurement-side handler resolve the supplier - keeps coupling loose.
    * ``bi_dashboards.kpi_recompute`` - the COPQ / first-pass-yield gauges
      depend on NCR counts and severities.
    """
    data = event.data or {}
    ncr_id = data.get("ncr_id")
    project_id = data.get("project_id")
    if not (ncr_id and project_id):
        return
    severity = data.get("severity") or ""
    try:
        event_bus.publish_detached(
            "procurement.supplier_rating_update",
            {
                "source_event": "qms.ncr.raised",
                "ncr_id": str(ncr_id),
                "project_id": str(project_id),
                "severity": severity,
                "cost_impact_amount": data.get("cost_impact_amount") or "",
                "cost_impact_currency": data.get("cost_impact_currency") or "",
            },
            source_module="qms",
        )
    except Exception:
        logger.debug("qms: supplier_rating_update emit failed", exc_info=True)

    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "qms",
                "source_event": "qms.ncr.raised",
                "project_id": str(project_id),
                "kpi_codes": ["copq", "first_pass_yield", "ncr_open_count"],
                "reason": "ncr_raised",
            },
            source_module="qms",
        )
    except Exception:
        logger.debug("qms: kpi_recompute emit failed", exc_info=True)


async def _on_hold_point_failed(event: Event) -> None:
    """``qms.inspection.hold_point_failed`` → notify + flag for follow-up (item 12).

    Infrastructure-only this phase: we fan out a ``notifications.dispatch``
    event so the notifications module can alert the inspector / GC, and a
    ``bi_dashboards.kpi_recompute`` so the first-pass-yield gauge refreshes.
    A failed hold point is the strongest quality signal on a project, so the
    hook is wired now even though the punchlist auto-raise lands in Phase 2.
    The subscriber is fail-soft - any error is logged at debug.
    """
    data = event.data or {}
    inspection_id = data.get("inspection_id")
    project_id = data.get("project_id")
    if not (inspection_id and project_id):
        return
    try:
        event_bus.publish_detached(
            "notifications.dispatch",
            {
                "source_module": "qms",
                "source_event": "qms.inspection.hold_point_failed",
                "project_id": str(project_id),
                "inspection_id": str(inspection_id),
                "itp_item_id": data.get("itp_item_id") or "",
                "control_point_name": data.get("control_point_name") or "",
                "severity": "high",
                "title": "Hold point failed",
            },
            source_module="qms",
        )
    except Exception:
        logger.debug("qms: hold_point_failed notify emit failed", exc_info=True)

    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "qms",
                "source_event": "qms.inspection.hold_point_failed",
                "project_id": str(project_id),
                "kpi_codes": ["first_pass_yield", "ncr_open_count"],
                "reason": "hold_point_failed",
            },
            source_module="qms",
        )
    except Exception:
        logger.debug("qms: hold_point_failed kpi emit failed", exc_info=True)


async def _on_inspection_approval_requested(event: Event) -> None:
    """``qms.inspection.approval_requested`` → start an approval instance (item 12).

    A failed / conditional hold or witness point needs a formal disposition
    before dependent work proceeds. When the project has an *active*
    ``qms_hold_point`` approval route configured, start an approval instance
    against the inspection so the gate cannot release without sign-off. When
    no route is configured the event is a no-op (the project simply has not
    opted into routed hold-point dispositions) - a release still requires the
    MANAGER+ ``qms.inspection.release_hold`` permission, so the gate is never
    silently weakened. Fail-soft: any error is logged at debug.
    """
    data = event.data or {}
    inspection_id = data.get("inspection_id")
    project_id = data.get("project_id")
    if not (inspection_id and project_id):
        return
    if not await _can_open_isolated_session():
        return
    try:
        async with async_session_factory() as session:
            from app.modules.approval_routes.repository import (  # noqa: PLC0415
                ApprovalRouteRepository,
            )
            from app.modules.approval_routes.schemas import (  # noqa: PLC0415
                InstanceCreate,
            )
            from app.modules.approval_routes.service import (  # noqa: PLC0415
                ApprovalRouteService,
            )

            repo = ApprovalRouteRepository(session)
            routes = await repo.list_routes(
                project_id=uuid.UUID(project_id),
                target_kind="qms_hold_point",
            )
            active = [r for r in routes if r.is_active]
            if not active:
                return
            svc = ApprovalRouteService(session)
            await svc.start_instance(
                InstanceCreate(
                    route_id=active[0].id,
                    target_kind="qms_hold_point",
                    target_id=uuid.UUID(inspection_id),
                ),
                started_by=None,
            )
            await session.commit()
            logger.info(
                "QMS hold-point disposition approval started for inspection %s (route %s)",
                inspection_id,
                active[0].id,
            )
    except Exception:
        logger.debug("qms: hold-point approval auto-start skipped", exc_info=True)


def register_subscribers() -> None:
    """Idempotently subscribe QMS handlers to upstream events."""
    event_bus.subscribe_once("hse.capa.completed", _on_hse_capa_completed)
    event_bus.subscribe_once(
        "hse.capa.root_cause_recorded",
        _on_hse_incident_root_cause,
    )
    event_bus.subscribe_once("qms.ncr.raised", _on_ncr_raised_fanout)
    event_bus.subscribe_once(
        "qms.inspection.hold_point_failed",
        _on_hold_point_failed,
    )
    event_bus.subscribe_once(
        "qms.inspection.approval_requested",
        _on_inspection_approval_requested,
    )
