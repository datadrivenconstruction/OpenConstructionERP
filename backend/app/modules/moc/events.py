# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MoC cross-module event subscribers (HSE/QMS/Risk wave).

Wires Management-of-Change to upstream events without import-time coupling.
Registered idempotently via :func:`register_subscribers`, invoked from
``app.modules.moc.__init__.on_startup``.

Subscriptions:

* ``moc.candidate_from_ncr`` - emitted by ``ncr.events`` when an NCR with
  cost impact closes. If the cost crosses a configurable threshold we
  auto-create a draft (``proposed``) MoCEntry so scope-affecting NCRs
  appear on the MoC dashboard ready for review. Idempotent on the
  ``source_ncr_id`` marker.

* ``moc.entry.accepted`` - emitted by ``moc.service.transition`` when a
  MoC is approved. We fan out ``changeorders.candidate_from_moc`` so the
  changeorders module can pre-fill a CO from the approved scope change.
  Loose coupling: we do NOT import changeorders here.

* ``moc.entry.implemented`` → BI nudge for the change-velocity KPI.

All handlers are fail-soft: any exception is swallowed at debug. Cross-
session writes are SQLite-deadlock-gated via :func:`_can_open_isolated_session`.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.moc.models import MoCEntry

logger = logging.getLogger(__name__)


# Cost threshold above which an NCR-closure auto-spawns a draft MoC entry.
# Below this the NCR is closed silently - minor reworks should not flood
# the MoC dashboard. Tunable per-tenant in a future config pass.
_NCR_MOC_AUTO_THRESHOLD = Decimal("1000")


async def _can_open_isolated_session() -> bool:
    """Return True only when a subscriber can safely open a write session."""
    try:
        async with async_session_factory() as probe:
            bind = probe.get_bind()
            dialect = getattr(getattr(bind, "dialect", None), "name", "") or ""
        return dialect == "postgresql"
    except Exception:
        return False


def _parse_money(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


# ── moc.candidate_from_ncr → draft MoCEntry ──────────────────────────────


async def _on_moc_candidate_from_ncr(event: Event) -> None:
    """``moc.candidate_from_ncr`` → auto-create a draft MoC entry.

    Triggered for NCRs that closed with a non-trivial cost impact (≥
    threshold). Idempotent on ``source_ncr_id`` stored in
    ``MoCEntry.metadata_``.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    ncr_id = data.get("ncr_id")
    project_id_raw = data.get("project_id")
    if not (ncr_id and project_id_raw):
        return
    cost_impact = _parse_money(data.get("cost_impact"))
    if cost_impact < _NCR_MOC_AUTO_THRESHOLD:
        logger.debug(
            "moc: NCR %s cost_impact %s below threshold %s, skipping",
            ncr_id,
            cost_impact,
            _NCR_MOC_AUTO_THRESHOLD,
        )
        return
    try:
        project_id = uuid.UUID(str(project_id_raw))
    except (ValueError, TypeError):
        return
    schedule_delta_days = int(data.get("schedule_impact_days") or 0)

    try:
        async with async_session_factory() as session:
            # Idempotency - check for an existing MoC keyed on this NCR.
            stmt = select(MoCEntry).where(MoCEntry.project_id == project_id)
            existing = (await session.execute(stmt)).scalars().all()
            ncr_id_s = str(ncr_id)
            for row in existing:
                md = row.metadata_ if isinstance(row.metadata_, dict) else {}
                if md.get("source_ncr_id") == ncr_id_s:
                    logger.debug(
                        "moc: NCR %s already projected → MoC %s",
                        ncr_id_s,
                        row.id,
                    )
                    return

            from app.modules.moc.repository import MoCRepository

            repo = MoCRepository(session)
            code = await repo.next_code(project_id)
            title = (data.get("title") or f"Scope change from NCR {data.get('ncr_number', '')}")[:500]
            risk_level = "high" if cost_impact >= Decimal("10000") else "medium"
            entry = MoCEntry(
                project_id=project_id,
                code=code,
                title=f"NCR → MoC: {title}"[:500],
                description=(
                    f"Auto-proposed from NCR {data.get('ncr_number') or ncr_id_s}. "
                    f"Cost impact: {cost_impact}. "
                    f"Schedule delta: {schedule_delta_days} days. "
                    "Review and decide whether this rework is scope-affecting "
                    "and should proceed via formal Management of Change."
                ),
                change_category="engineering",
                risk_level=risk_level,
                cost_impact=cost_impact,
                schedule_delta_days=schedule_delta_days,
                currency="",
                proposed_by=None,
                proposed_at=None,
                status="proposed",
            )
            entry.metadata_ = {
                "source": "ncr",
                "source_event": "moc.candidate_from_ncr",
                "source_ncr_id": ncr_id_s,
                "source_ncr_number": data.get("ncr_number") or "",
            }
            session.add(entry)
            await session.commit()
            logger.info(
                "moc: auto-proposed NCR %s → MoCEntry %s (%s, risk=%s)",
                ncr_id_s,
                entry.id,
                code,
                risk_level,
            )
            event_bus.publish_detached(
                "moc.entry.auto_proposed",
                {
                    "source_event": "moc.candidate_from_ncr",
                    "source_ncr_id": ncr_id_s,
                    "entry_id": str(entry.id),
                    "project_id": str(project_id),
                    "code": code,
                    "risk_level": risk_level,
                    "cost_impact": str(cost_impact),
                },
                source_module="oe_moc",
            )
    except Exception:
        logger.debug("moc: _on_moc_candidate_from_ncr failed", exc_info=True)


# ── moc.entry.accepted → changeorders fan-out + BI nudge ────────────────


async def _on_moc_accepted(event: Event) -> None:
    """``moc.entry.accepted`` → ``changeorders.candidate_from_moc`` fan-out.

    Loose-coupling pattern: we don't import changeorders. Any subscriber
    (the changeorders module, BI projections, contracts workflow) can
    react. The MoC.change_order_id linkage is set by whoever ends up
    materialising the CO.
    """
    data = event.data or {}
    entry_id = data.get("entry_id")
    project_id = data.get("project_id")
    if not (entry_id and project_id):
        return
    try:
        event_bus.publish_detached(
            "changeorders.candidate_from_moc",
            {
                "source_event": "moc.entry.accepted",
                "moc_entry_id": str(entry_id),
                "moc_code": data.get("code") or "",
                "project_id": str(project_id),
                "actor_id": data.get("actor_id") or "",
            },
            source_module="oe_moc",
        )
    except Exception:
        logger.debug("moc: changeorders.candidate_from_moc emit failed", exc_info=True)

    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "oe_moc",
                "source_event": "moc.entry.accepted",
                "project_id": str(project_id),
                "kpi_codes": ["moc_accepted_count", "scope_change_value"],
                "reason": "moc_accepted",
            },
            source_module="oe_moc",
        )
    except Exception:
        logger.debug("moc: kpi_recompute emit failed", exc_info=True)


async def _on_moc_implemented(event: Event) -> None:
    """``moc.entry.implemented`` → BI nudge for change-velocity KPI."""
    data = event.data or {}
    project_id = data.get("project_id")
    if not project_id:
        return
    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "oe_moc",
                "source_event": "moc.entry.implemented",
                "project_id": str(project_id),
                "kpi_codes": ["moc_implemented_count", "change_velocity_days"],
                "reason": "moc_implemented",
            },
            source_module="oe_moc",
        )
    except Exception:
        logger.debug("moc: kpi_recompute on implemented failed", exc_info=True)


def register_subscribers() -> None:
    """Idempotently subscribe MoC cross-module handlers."""
    event_bus.subscribe_once("moc.candidate_from_ncr", _on_moc_candidate_from_ncr)
    event_bus.subscribe_once("moc.entry.accepted", _on_moc_accepted)
    event_bus.subscribe_once("moc.entry.implemented", _on_moc_implemented)
    logger.info("MoC: 3 cross-module subscriber(s) registered")
