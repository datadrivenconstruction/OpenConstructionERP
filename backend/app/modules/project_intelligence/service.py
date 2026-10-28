# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Forecast service for Project Intelligence (TOP-30 #19).

Assembles the predictive cost + schedule + risk analytics for a project by
reading from already-committed sibling modules **read-only**:

* ``finance.EVMSnapshot`` (the latest EVM snapshot: BAC / EV / AC / PV) - the
  same source ``full_evm.EVMService.calculate_forecast`` reads. We recompute
  the canonical Earned-Value formulas live (no row is written) via the pure
  helpers in :mod:`forecast`.
* ``schedule`` activities + the schedule baseline finish - for the schedule
  slip projection.
* ``risk`` register - open high-severity unmitigated risks feed the risk score.

The service owns no models and writes nothing. It uses raw SQL through the
request session (the same decoupled pattern :mod:`collector` uses) so it does
not import or perturb the sibling services. Every read is wrapped so a missing
or renamed sibling table degrades to "unavailable" rather than failing the
whole forecast.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_intelligence.forecast import (
    CostForecast,
    ProjectForecast,
    ScheduleSlip,
    compute_cost_forecast,
    degraded_cost_forecast,
    project_schedule_slip,
    score_cost_overrun_risk,
    to_decimal,
)

logger = logging.getLogger(__name__)


class ForecastService:
    """Read-only predictive analytics assembler for a single project.

    Stateless apart from the injected session. All public methods are safe to
    call without mutating any sibling module's data.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Store the request-scoped async session."""
        self.session = session

    async def get_project_forecast(self, project_id: uuid.UUID) -> ProjectForecast:
        """Compute the full predictive forecast for a project.

        Reads the latest EVM snapshot, the schedule progress and the open
        high-severity risks, then composes the deterministic cost forecast,
        schedule-slip projection and cost-overrun risk score. Always returns a
        :class:`ProjectForecast`; individual sections degrade independently
        when their source data is absent.
        """
        name, currency = await self._project_meta(project_id)
        cost = await self._cost_forecast(project_id, currency)
        schedule = await self._schedule_slip(project_id)
        open_high_risks = await self._open_high_severity_risks(project_id)

        risk = score_cost_overrun_risk(
            cpi=cost.cpi,
            spi=cost.spi,
            vac=to_decimal(cost.vac) if cost.vac is not None else None,
            bac=to_decimal(cost.bac) if cost.bac is not None else None,
            finish_variance_days=schedule.finish_variance_days,
            open_high_severity_risks=open_high_risks,
        )

        return ProjectForecast(
            project_id=str(project_id),
            project_name=name,
            currency=currency,
            generated_at=datetime.now(UTC).isoformat(),
            cost=cost,
            schedule=schedule,
            risk=risk,
            review_required=True,
        )

    # ── Project metadata ────────────────────────────────────────────────────

    async def _project_meta(self, project_id: uuid.UUID) -> tuple[str, str]:
        """Return ``(project_name, currency)`` for display (best-effort)."""
        try:
            row = (
                await self.session.execute(
                    text("SELECT name, currency FROM oe_projects_project WHERE id = :pid"),
                    {"pid": str(project_id)},
                )
            ).first()
            if row:
                return (row[0] or ""), (row[1] or "")
        except Exception:
            logger.debug("forecast: project meta lookup failed for %s", project_id, exc_info=True)
        return "", ""

    # ── Cost forecast ───────────────────────────────────────────────────────

    async def _cost_forecast(self, project_id: uuid.UUID, currency: str) -> CostForecast:
        """Compute the EVM cost forecast from the latest finance snapshot.

        Degrades gracefully (``available=False`` + reason) when the project has
        no EVM snapshot yet, which is the common case for an early-stage
        estimate.
        """
        try:
            row = (
                await self.session.execute(
                    text(
                        "SELECT snapshot_date, bac, ev, ac, pv "
                        "FROM oe_finance_evm_snapshot "
                        "WHERE project_id = :pid "
                        "ORDER BY snapshot_date DESC LIMIT 1"
                    ),
                    {"pid": str(project_id)},
                )
            ).first()
        except Exception:
            logger.debug("forecast: EVM snapshot read failed for %s", project_id, exc_info=True)
            return degraded_cost_forecast("evm_snapshot_unavailable", currency)

        if row is None:
            return degraded_cost_forecast("no_evm_snapshot", currency)

        bac = to_decimal(row[1])
        if bac <= to_decimal("0"):
            # Without a budget at completion the EVM math is meaningless.
            return degraded_cost_forecast("no_budget_at_completion", currency)

        return compute_cost_forecast(
            bac=bac,
            ev=to_decimal(row[2]),
            ac=to_decimal(row[3]),
            pv=to_decimal(row[4]),
            currency=currency,
            snapshot_date=str(row[0]) if row[0] else None,
        )

    # ── Schedule slip ───────────────────────────────────────────────────────

    async def _schedule_slip(self, project_id: uuid.UUID) -> ScheduleSlip:
        """Project the schedule finish-date variance from activity progress.

        Reads the project's first schedule, its activities (planned finish +
        actual progress percent) and the active baseline finish. Planned
        progress for each activity is derived deterministically from the
        baseline span elapsed at the data date; actual progress is the stored
        ``progress_pct``.
        """
        try:
            sched_row = (
                await self.session.execute(
                    text(
                        "SELECT id, start_date, end_date, data_date "
                        "FROM oe_schedule_schedule WHERE project_id = :pid "
                        "ORDER BY created_at ASC LIMIT 1"
                    ),
                    {"pid": str(project_id)},
                )
            ).first()
        except Exception:
            logger.debug("forecast: schedule read failed for %s", project_id, exc_info=True)
            return ScheduleSlip(available=False, reason="schedule_unavailable")

        if sched_row is None:
            return ScheduleSlip(available=False, reason="no_schedule")

        schedule_id = str(sched_row[0])
        data_date = sched_row[3] or sched_row[1]

        try:
            act_rows = (
                await self.session.execute(
                    text(
                        "SELECT start_date, end_date, progress_pct, status "
                        "FROM oe_schedule_activity WHERE schedule_id = :sid"
                    ),
                    {"sid": schedule_id},
                )
            ).fetchall()
        except Exception:
            logger.debug("forecast: activity read failed for %s", project_id, exc_info=True)
            return ScheduleSlip(available=False, reason="schedule_activities_unavailable")

        baseline_finish = await self._baseline_finish(project_id, schedule_id, sched_row[2])

        activities = [
            {
                "planned_pct": self._planned_pct(r[0], r[1], data_date),
                "actual_pct": to_decimal(r[2]),
                "end_date": r[1],
            }
            for r in act_rows
        ]
        return project_schedule_slip(
            activities=activities,
            baseline_finish=baseline_finish,
            data_date=data_date,
        )

    @staticmethod
    def _planned_pct(start: str | None, end: str | None, data_date: str | None) -> float:
        """Deterministic planned percent-complete at the data date.

        Linear time-elapsed model: 0% before the activity starts, 100% after
        its planned finish, linearly interpolated in between. With no dates we
        return 0 so the activity simply contributes a "not started" baseline.
        """
        from app.modules.project_intelligence.forecast import _parse_iso_date

        sd = _parse_iso_date(start)
        ed = _parse_iso_date(end)
        dd = _parse_iso_date(data_date) or datetime.now(UTC).date()
        if sd is None or ed is None or ed <= sd:
            return 0.0
        if dd <= sd:
            return 0.0
        if dd >= ed:
            return 100.0
        return round((dd - sd).days / (ed - sd).days * 100.0, 4)

    async def _baseline_finish(
        self,
        project_id: uuid.UUID,
        schedule_id: str,
        schedule_end: str | None,
    ) -> str | None:
        """Resolve the baseline finish date.

        Prefers an active :class:`ScheduleBaseline` for the schedule; falls
        back to the schedule's own ``end_date`` when no baseline is set (a
        schedule without a baseline still has a planned finish).
        """
        try:
            row = (
                await self.session.execute(
                    text(
                        "SELECT baseline_date FROM oe_schedule_baseline "
                        "WHERE (schedule_id = :sid OR project_id = :pid) "
                        "  AND is_active = TRUE "
                        "ORDER BY baseline_date DESC LIMIT 1"
                    ),
                    {"sid": schedule_id, "pid": str(project_id)},
                )
            ).first()
            if row and row[0]:
                return str(row[0])
        except Exception:
            logger.debug("forecast: baseline read failed for %s", project_id, exc_info=True)
        return schedule_end

    # ── Risk ────────────────────────────────────────────────────────────────

    async def _open_high_severity_risks(self, project_id: uuid.UUID) -> int:
        """Count open, high-severity, unmitigated risks for the project.

        "Open" means not closed/retired; "high severity" matches the same set
        the collector flags; "unmitigated" means no mitigation strategy text.
        Read-only against the risk register; returns 0 if the table is absent.
        """
        try:
            row = (
                await self.session.execute(
                    text(
                        "SELECT COUNT(*) FROM oe_risk_register "
                        "WHERE project_id = :pid "
                        "  AND impact_severity IN ('high', 'very_high', 'critical') "
                        "  AND status NOT IN ('closed', 'retired', 'resolved') "
                        "  AND (mitigation_strategy = '' OR mitigation_strategy IS NULL)"
                    ),
                    {"pid": str(project_id)},
                )
            ).first()
            return int(row[0]) if row and row[0] else 0
        except Exception:
            logger.debug("forecast: risk count failed for %s", project_id, exc_info=True)
            return 0
