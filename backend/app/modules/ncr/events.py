# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""NCR cross-module event subscribers (HSE/QMS/Risk wave).

These handlers wire the standalone NCR module to upstream events without
import-time coupling. Registered idempotently via
:func:`register_subscribers` from ``app.modules.ncr.__init__``.

Subscriptions:

* ``qms.audit.finding_raised`` whose payload requests a corrective action →
  mirror as an NCR in the NCR module so non-conformances detected during a
  QMS audit appear on the project NCR dashboard. Idempotent via the
  ``source_finding_id`` marker stored in ``NCR.metadata_``.

* ``clash.high_severity.detected`` for a CRITICAL (or reviewer-confirmed)
  clash → raise an NCR so the design/coordination non-conformance enters
  the formal NCR workflow (root cause, corrective action, sign-off).
  Idempotent on ``NCR.clash_result_id``.

* ``ncr.closed_with_cost_impact`` → publish ``moc.candidate_from_ncr`` so
  the MoC module (or any subscriber) can auto-propose a Management-of-
  Change entry for scope-affecting NCRs. Cheap fan-out - no DB write here.

All handlers are fail-soft: any exception is swallowed at debug. Cross-
session writes are SQLite-deadlock-gated via :func:`_can_open_isolated_session`.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.ncr.models import NCR

logger = logging.getLogger(__name__)


async def _can_open_isolated_session() -> bool:
    """Return True only when we can safely write from a subscriber.

    Mirrors the QMS/risk gates: SQLite has a single-writer lock, so opening
    a second session inside an event handler while the publisher still
    holds the request transaction deadlocks. We only auto-materialise on
    PostgreSQL.
    """
    try:
        async with async_session_factory() as probe:
            bind = probe.get_bind()
            dialect = getattr(getattr(bind, "dialect", None), "name", "") or ""
        return dialect == "postgresql"
    except Exception:
        return False


# ── qms.audit.finding_raised → standalone-NCR row ───────────────────────


_FINDING_SEVERITY_TO_NCR_SEVERITY = {
    "major_nc": "major",
    "minor_nc": "minor",
    "observation": "observation",
    "opportunity": "observation",
}


async def _on_qms_finding_raised(event: Event) -> None:
    """``qms.audit.finding_raised`` → mirror as an NCR row.

    Only major / minor non-conformances are mirrored - observations and
    improvement opportunities are kept inside QMS to avoid noise on the
    NCR dashboard. Idempotent on ``source_finding_id``.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    finding_id = data.get("finding_id")
    audit_id = data.get("audit_id")
    project_id_raw = data.get("project_id")
    finding_type = (data.get("finding_type") or "").lower()
    if not (finding_id and audit_id and project_id_raw):
        return
    if finding_type not in {"major_nc", "minor_nc"}:
        # Observations / opportunities don't warrant an NCR row.
        return
    try:
        project_id = uuid.UUID(str(project_id_raw))
    except (ValueError, TypeError):
        return

    try:
        async with async_session_factory() as session:
            # Idempotency - check for an existing NCR with this finding marker.
            stmt = select(NCR).where(NCR.project_id == project_id)
            existing = (await session.execute(stmt)).scalars().all()
            finding_id_s = str(finding_id)
            for row in existing:
                md = row.metadata_ if isinstance(row.metadata_, dict) else {}
                if md.get("source_finding_id") == finding_id_s:
                    return

            from app.modules.ncr.repository import NCRRepository

            repo = NCRRepository(session)
            ncr_number = await repo.next_ncr_number(project_id)
            severity = _FINDING_SEVERITY_TO_NCR_SEVERITY.get(finding_type, "minor")
            ncr = NCR(
                project_id=project_id,
                ncr_number=ncr_number,
                title=f"QMS audit finding → NCR ({finding_type})"[:500],
                description=(f"Auto-mirrored from QMS audit {audit_id}, finding {finding_id_s}. Type: {finding_type}.")[
                    :10000
                ],
                ncr_type="documentation",
                severity=severity,
                status="identified",
                metadata_={
                    "source": "qms",
                    "source_event": "qms.audit.finding_raised",
                    "source_finding_id": finding_id_s,
                    "source_audit_id": str(audit_id),
                },
            )
            session.add(ncr)
            await session.commit()
            logger.info(
                "ncr: auto-mirrored QMS finding %s → NCR %s (%s)",
                finding_id_s,
                ncr.id,
                ncr_number,
            )
            event_bus.publish_detached(
                "ncr.mirrored_from_qms_finding",
                {
                    "source_finding_id": finding_id_s,
                    "source_audit_id": str(audit_id),
                    "ncr_id": str(ncr.id),
                    "ncr_number": ncr_number,
                    "project_id": str(project_id),
                    "severity": severity,
                },
                source_module="ncr",
            )
    except Exception:
        logger.debug("ncr: _on_qms_finding_raised failed", exc_info=True)


# ── clash.high_severity.detected → standalone-NCR row ───────────────────


async def _on_clash_high_severity(event: Event) -> None:
    """``clash.high_severity.detected`` → raise an NCR for serious clashes.

    A high-severity clash is a coordination finding; a *critical* one (or a
    reviewer who confirms a clash) is a formal non-conformance that belongs
    in the NCR workflow. We therefore only materialise an NCR when the
    severity is ``critical`` or the trigger is ``confirmed`` - routine high
    clashes stay on the clash board (and become a punch item via the
    punchlist bridge) to avoid NCR-dashboard noise.

    Idempotent on ``NCR.clash_result_id`` so a re-published or re-confirmed
    event for the same clash never raises a second NCR.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    result_id = data.get("result_id")
    project_id_raw = data.get("project_id")
    if not (result_id and project_id_raw):
        return

    severity = str(data.get("severity") or "").lower()
    trigger = str(data.get("trigger") or "").lower()
    if severity != "critical" and trigger != "confirmed":
        return

    try:
        project_id = uuid.UUID(str(project_id_raw))
    except (ValueError, TypeError):
        return

    result_id_s = str(result_id)
    try:
        async with async_session_factory() as session:
            # Idempotency - bail if an NCR already links this clash.
            existing = (
                await session.execute(
                    select(NCR.id).where(
                        NCR.project_id == project_id,
                        NCR.clash_result_id == result_id_s,
                    )
                )
            ).first()
            if existing is not None:
                return

            a_name = str(data.get("a_name") or "").strip()
            b_name = str(data.get("b_name") or "").strip()
            clash_type = str(data.get("clash_type") or "clash").strip() or "clash"
            elements = f"{a_name or '?'} vs {b_name or '?'}"
            title = f"Clash NCR: {elements}"[:500]
            description = (
                f"Auto-raised from a {severity or 'high'}-severity clash "
                f"(trigger: {trigger or 'detected'}).\n"
                f"Elements: {elements}\n"
                f"Clash type: {clash_type}\n"
                f"Clash result: {result_id_s}"
            )[:10000]

            from app.modules.ncr.repository import NCRRepository

            repo = NCRRepository(session)
            ncr_number = await repo.next_ncr_number(project_id)
            ncr = NCR(
                project_id=project_id,
                ncr_number=ncr_number,
                title=title,
                description=description,
                ncr_type="design",
                severity="critical" if severity == "critical" else "major",
                status="identified",
                location_description=elements[:500],
                clash_result_id=result_id_s,
                metadata_={
                    "source": "clash",
                    "source_event": "clash.high_severity.detected",
                    "result_id": result_id_s,
                    "run_id": str(data.get("run_id") or ""),
                    "severity": severity,
                    "trigger": trigger,
                    "clash_type": clash_type,
                },
            )
            session.add(ncr)
            await session.commit()
            logger.info(
                "ncr: auto-raised NCR %s (%s) from clash %s (%s/%s)",
                ncr.id,
                ncr_number,
                result_id_s,
                severity,
                trigger,
            )
            event_bus.publish_detached(
                "ncr.created_from_clash",
                {
                    "ncr_id": str(ncr.id),
                    "ncr_number": ncr_number,
                    "project_id": str(project_id),
                    "result_id": result_id_s,
                    "severity": severity,
                },
                source_module="ncr",
            )
    except Exception:
        logger.debug("ncr: _on_clash_high_severity failed", exc_info=True)


# ── validation.results.errors_found → raise an NCR ──────────────────────


async def _on_validation_errors_found(event: Event) -> None:
    """``validation.results.errors_found`` → raise one NCR per validation run.

    An ERROR-severity validation result blocks the data from being trusted; it
    is a documentation/data non-conformance that belongs in the formal NCR
    workflow (root cause, corrective action, sign-off). We raise a single NCR
    per report summarising the blocking errors rather than one per error, to
    keep the NCR dashboard readable.

    Idempotent on ``metadata_['report_id']`` so re-running the same validation
    (which produces a new report id) raises a fresh NCR, but a re-published
    event for the *same* report never raises a duplicate.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    report_id = data.get("report_id")
    project_id_raw = data.get("project_id")
    errors = data.get("errors") or []
    error_count = int(data.get("error_count") or len(errors) or 0)
    if not (report_id and project_id_raw) or error_count <= 0:
        return

    try:
        project_id = uuid.UUID(str(project_id_raw))
    except (ValueError, TypeError):
        return

    report_id_s = str(report_id)
    try:
        async with async_session_factory() as session:
            # Idempotency - bail if an NCR already links this validation report.
            # Match metadata in Python (as the QMS bridge does) rather than via a
            # JSONB path operator, so the check never depends on column-type quirks.
            existing_rows = (await session.execute(select(NCR).where(NCR.project_id == project_id))).scalars().all()
            for row in existing_rows:
                md = row.metadata_ if isinstance(row.metadata_, dict) else {}
                if md.get("source") == "validation" and md.get("report_id") == report_id_s:
                    return

            rule_set = str(data.get("rule_set") or "").strip()
            target_id = str(data.get("target_id") or "").strip()
            top = errors[:5]
            bullet_lines = "\n".join(
                f"- [{e.get('rule_id') or '?'}] {e.get('message') or ''}"
                + (f" (at {e.get('element_ref')})" if e.get("element_ref") else "")
                for e in top
            )
            more = error_count - len(top)
            if more > 0:
                bullet_lines += f"\n- ... and {more} more"
            title = f"Validation errors in BOQ ({error_count})"[:500]
            description = (
                f"Auto-raised from a validation run that produced {error_count} "
                f"blocking error(s).\n"
                f"Rule set: {rule_set or 'n/a'}\n"
                f"Validation report: {report_id_s}\n\n"
                f"{bullet_lines}"
            )[:10000]

            from app.modules.ncr.repository import NCRRepository

            repo = NCRRepository(session)
            ncr_number = await repo.next_ncr_number(project_id)
            ncr = NCR(
                project_id=project_id,
                ncr_number=ncr_number,
                title=title,
                description=description,
                ncr_type="documentation",
                severity="major",
                status="identified",
                metadata_={
                    "source": "validation",
                    "source_event": "validation.results.errors_found",
                    "report_id": report_id_s,
                    "target_id": target_id,
                    "rule_set": rule_set,
                    "error_count": error_count,
                    "errors": top,
                },
            )
            session.add(ncr)
            await session.commit()
            logger.info(
                "ncr: auto-raised NCR %s (%s) from validation report %s (%d error(s))",
                ncr.id,
                ncr_number,
                report_id_s,
                error_count,
            )
            event_bus.publish_detached(
                "ncr.created_from_validation",
                {
                    "ncr_id": str(ncr.id),
                    "ncr_number": ncr_number,
                    "project_id": str(project_id),
                    "report_id": report_id_s,
                    "error_count": error_count,
                },
                source_module="ncr",
            )
    except Exception:
        logger.debug("ncr: _on_validation_errors_found failed", exc_info=True)


# ── ncr.closed_with_cost_impact → MoC candidate fan-out ─────────────────


async def _on_ncr_closed_with_cost_impact(event: Event) -> None:
    """``ncr.closed_with_cost_impact`` → ``moc.candidate_from_ncr`` fan-out.

    The MoC module decides whether the cost is scope-affecting (its own
    threshold + policy) and whether to auto-create a MoC entry. We only
    re-emit so loose coupling is preserved. Also publishes a BI nudge for
    the COPQ / scope-creep gauges.
    """
    data = event.data or {}
    ncr_id = data.get("ncr_id")
    project_id = data.get("project_id")
    if not (ncr_id and project_id):
        return
    try:
        event_bus.publish_detached(
            "moc.candidate_from_ncr",
            {
                "source_event": "ncr.closed_with_cost_impact",
                "ncr_id": str(ncr_id),
                "ncr_number": data.get("ncr_number") or "",
                "project_id": str(project_id),
                "title": data.get("title") or "",
                "cost_impact": data.get("cost_impact") or "",
                "schedule_impact_days": data.get("schedule_impact_days") or 0,
            },
            source_module="ncr",
        )
    except Exception:
        logger.debug("ncr: moc.candidate_from_ncr emit failed", exc_info=True)

    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "ncr",
                "source_event": "ncr.closed_with_cost_impact",
                "project_id": str(project_id),
                "kpi_codes": ["ncr_closed_count", "scope_creep_value"],
                "reason": "ncr_closed_with_cost",
            },
            source_module="ncr",
        )
    except Exception:
        logger.debug("ncr: kpi_recompute emit failed", exc_info=True)


def register_subscribers() -> None:
    """Idempotently subscribe NCR cross-module handlers."""
    event_bus.subscribe_once("qms.audit.finding_raised", _on_qms_finding_raised)
    event_bus.subscribe_once("clash.high_severity.detected", _on_clash_high_severity)
    event_bus.subscribe_once("validation.results.errors_found", _on_validation_errors_found)
    event_bus.subscribe_once("ncr.closed_with_cost_impact", _on_ncr_closed_with_cost_impact)
    logger.info("NCR: 4 cross-module subscriber(s) registered")
