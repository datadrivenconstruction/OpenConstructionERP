"""‌⁠‍Safety service - business logic for incident and observation management."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.safety._dateutil import canonicalize_incident_date, parse_incident_date
from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.safety.repository import IncidentRepository, ObservationRepository
from app.modules.safety.schemas import (
    IncidentCreate,
    IncidentUpdate,
    ObservationCreate,
    ObservationUpdate,
    SafetyStatsResponse,
    SafetyThresholdAlertResponse,
    SafetyTrendEntryExtended,
    SafetyTrendsExtendedResponse,
    SafetyTrendsResponse,
)

logger = logging.getLogger(__name__)

# Recordable treatment heuristic, shared by the stats and trend paths so the
# TRIR numerator is computed identically everywhere.
_RECORDABLE_TREATMENTS = frozenset({"medical", "hospital", "fatality"})


def _incident_man_hours(inc: object) -> float:
    """Exposure hours for one incident from ``metadata.man_hours_total``.

    Tolerates strings/ints coming back from JSON; ignores non-numeric or
    non-positive junk (returning 0.0) rather than corrupting a rate
    denominator. Identical convention to :meth:`SafetyService.get_stats`.
    """
    raw_hours = (getattr(inc, "metadata_", None) or {}).get("man_hours_total")
    if raw_hours is None:
        return 0.0
    try:
        hours = float(raw_hours)
    except (TypeError, ValueError):
        logger.warning(
            "Safety incident %s has a non-numeric man_hours_total %r; ignored",
            getattr(inc, "incident_number", getattr(inc, "id", "?")),
            raw_hours,
        )
        return 0.0
    return hours if hours > 0 else 0.0


def _is_recordable(inc: object) -> bool:
    """OSHA-300 recordability: explicit flag, else treatment-type heuristic."""
    return bool(getattr(inc, "osha_recordable", False)) or (
        getattr(inc, "treatment_type", None) in _RECORDABLE_TREATMENTS
    )


def _rate_status(current: float | None, baseline: float) -> str:
    """Green/yellow/red band for a frequency rate against its safe-baseline.

    * ``unknown`` - current rate could not be computed (no man-hours).
    * ``green``   - at or below the baseline (safe).
    * ``yellow``  - above baseline but within 150 percent of it (watch).
    * ``red``     - more than 150 percent of the baseline (act).

    A zero baseline is degenerate (any positive rate is "above" it): treat
    any positive current as ``red`` and an exactly-zero current as ``green``.
    """
    if current is None:
        return "unknown"
    if baseline <= 0:
        return "green" if current <= 0 else "red"
    ratio = current / baseline
    if ratio <= 1.0:
        return "green"
    if ratio <= 1.5:
        return "yellow"
    return "red"


def _compute_trend_direction(entries: list[SafetyTrendEntryExtended]) -> str:
    """Classify the recent LTIFR trajectory from the last 3 usable periods.

    Uses the last three periods that have a computed LTIFR (skipping
    no-man-hours gaps) and a simple ordinary-least-squares slope. A *falling*
    LTIFR is good, so a negative slope is 'improving'.

    * ``improving`` - slope < -0.2 (rate dropping)
    * ``declining`` - slope >  0.2 (rate rising)
    * ``stable``    - slope within +/-0.2
    * ``unknown``   - fewer than 3 periods carry a usable LTIFR
    """
    rates = [e.ltifr for e in entries if e.ltifr is not None]
    if len(rates) < 3:
        return "unknown"
    window = rates[-3:]
    n = len(window)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(window) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return "stable"
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, window, strict=True)) / denom
    if slope < -0.2:
        return "improving"
    if slope > 0.2:
        return "declining"
    return "stable"


def _compute_risk_tier(risk_score: int) -> str:
    """‌⁠‍Derive risk tier from risk_score.

    Tiers: low (1-5), medium (6-10), high (11-15), critical (16-25).
    """
    if risk_score >= 16:
        return "critical"
    if risk_score >= 11:
        return "high"
    if risk_score >= 6:
        return "medium"
    return "low"


class SafetyService:
    """‌⁠‍Business logic for safety incidents and observations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incident_repo = IncidentRepository(session)
        self.observation_repo = ObservationRepository(session)

    # ── Incidents ─────────────────────────────────────────────────────────

    async def create_incident(
        self,
        data: IncidentCreate,
        user_id: str | None = None,
    ) -> SafetyIncident:
        """Create a new safety incident."""
        corrective_actions = [entry.model_dump() for entry in data.corrective_actions]

        incident = SafetyIncident(
            project_id=data.project_id,
            title=data.title,
            # Store a canonical ISO YYYY-MM-DD string so the "days without
            # incident / LTI" billboard never has to guess on read.
            incident_date=canonicalize_incident_date(data.incident_date),
            location=data.location,
            incident_type=data.incident_type,
            severity=data.severity,
            description=data.description,
            injured_person_details=data.injured_person_details,
            treatment_type=data.treatment_type,
            days_lost=data.days_lost,
            root_cause=data.root_cause,
            corrective_actions=corrective_actions,
            reported_to_regulator=data.reported_to_regulator,
            status=data.status,
            geo_lat=data.geo_lat,
            geo_lon=data.geo_lon,
            created_by=user_id,
            metadata_=data.metadata,
        )
        incident = await self.incident_repo.create(incident)
        # The repository assigns incident_number (with a collision retry) at
        # insert time, so read the committed value back for logging/events.
        incident_number = incident.incident_number
        logger.info(
            "Safety incident created: %s (%s) for project %s",
            incident_number,
            data.incident_type,
            data.project_id,
        )

        # Create notification for project owner (using same session to avoid
        # SQLite write-lock contention that occurs with event_bus handlers)
        try:
            from sqlalchemy import select

            from app.modules.notifications.service import NotificationService
            from app.modules.projects.models import Project

            result = await self.session.execute(select(Project.owner_id).where(Project.id == data.project_id))
            owner_id = result.scalar_one_or_none()
            if owner_id:
                notif_svc = NotificationService(self.session)
                await notif_svc.create(
                    user_id=owner_id,
                    notification_type="warning",
                    title_key="notifications.safety.incident_created",
                    entity_type="safety_incident",
                    entity_id=str(incident.id),
                    body_key="notifications.safety.incident_created_body",
                    body_context={
                        "incident_number": incident_number,
                        "severity": data.severity,
                        "description": (data.description or "")[:200],
                    },
                    action_url=f"/projects/{data.project_id}/safety?incident={incident.id}",
                )
        except Exception:
            logger.exception("Failed to create notification for safety incident %s", incident_number)

        # Emit event for additional cross-module handlers (analytics, etc.)
        event_bus.publish_detached(
            "safety.incident.created",
            {
                "project_id": str(data.project_id),
                "incident_id": str(incident.id),
                "incident_number": incident_number,
                "incident_type": data.incident_type,
                "severity": data.severity,
                "description": (data.description or "")[:200],
            },
            source_module="safety",
        )

        return incident

    async def get_incident(self, incident_id: uuid.UUID) -> SafetyIncident:
        incident = await self.incident_repo.get_by_id(incident_id)
        if incident is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Safety incident not found",
            )
        return incident

    async def list_incidents(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        incident_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[SafetyIncident], int]:
        return await self.incident_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            incident_type=incident_type,
            status=status_filter,
        )

    async def update_incident(
        self,
        incident_id: uuid.UUID,
        data: IncidentUpdate,
    ) -> SafetyIncident:
        incident = await self.get_incident(incident_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields.get("incident_date") is not None:
            fields["incident_date"] = canonicalize_incident_date(fields["incident_date"])
        if "corrective_actions" in fields and fields["corrective_actions"] is not None:
            fields["corrective_actions"] = [
                entry.model_dump() if hasattr(entry, "model_dump") else entry for entry in fields["corrective_actions"]
            ]

        if not fields:
            return incident

        await self.incident_repo.update_fields(incident_id, **fields)
        await self.session.refresh(incident)
        logger.info("Safety incident updated: %s", incident_id)
        return incident

    async def delete_incident(self, incident_id: uuid.UUID) -> None:
        await self.get_incident(incident_id)
        await self.incident_repo.delete(incident_id)
        logger.info("Safety incident deleted: %s", incident_id)

    # ── Observations ─────────────────────────────────────────────────────

    async def create_observation(
        self,
        data: ObservationCreate,
        user_id: str | None = None,
    ) -> SafetyObservation:
        """Create a new safety observation with computed risk score and tier.

        Emits ``safety.observation.high_risk`` event when risk_score > 15.
        """
        risk_score = data.severity * data.likelihood

        observation = SafetyObservation(
            project_id=data.project_id,
            observation_type=data.observation_type,
            description=data.description,
            location=data.location,
            severity=data.severity,
            likelihood=data.likelihood,
            risk_score=risk_score,
            immediate_action=data.immediate_action,
            corrective_action=data.corrective_action,
            status=data.status,
            created_by=user_id,
            metadata_=data.metadata,
        )
        observation = await self.observation_repo.create(observation)
        # The repository assigns observation_number (with a collision retry) at
        # insert time, so read the committed value back for logging/events.
        observation_number = observation.observation_number
        logger.info(
            "Safety observation created: %s (%s, risk=%d) for project %s",
            observation_number,
            data.observation_type,
            risk_score,
            data.project_id,
        )

        # Create notification for project owner on high-risk observations
        if risk_score > 15:
            try:
                from sqlalchemy import select

                from app.modules.notifications.service import NotificationService
                from app.modules.projects.models import Project

                result = await self.session.execute(select(Project.owner_id).where(Project.id == data.project_id))
                owner_id = result.scalar_one_or_none()
                if owner_id:
                    notif_svc = NotificationService(self.session)
                    await notif_svc.create(
                        user_id=owner_id,
                        notification_type="warning",
                        title_key="notifications.safety.high_risk_observation",
                        entity_type="safety_observation",
                        entity_id=str(observation.id),
                        body_key="notifications.safety.high_risk_body",
                        body_context={
                            "observation_number": observation_number,
                            "risk_score": risk_score,
                            "description": data.description[:200],
                        },
                        action_url=f"/projects/{data.project_id}/safety?observation={observation.id}",
                    )
            except Exception:
                logger.exception(
                    "Failed to create notification for high-risk observation %s",
                    observation_number,
                )

            # Emit event for additional cross-module handlers
            event_bus.publish_detached(
                "safety.observation.high_risk",
                data={
                    "project_id": str(data.project_id),
                    "observation_id": str(observation.id),
                    "observation_number": observation_number,
                    "risk_score": risk_score,
                    "description": data.description[:200],
                    "notify_user_ids": [],
                },
                source_module="safety",
            )

        return observation

    async def get_observation(self, observation_id: uuid.UUID) -> SafetyObservation:
        observation = await self.observation_repo.get_by_id(observation_id)
        if observation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Safety observation not found",
            )
        return observation

    async def list_observations(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        observation_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[SafetyObservation], int]:
        return await self.observation_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            observation_type=observation_type,
            status=status_filter,
        )

    async def update_observation(
        self,
        observation_id: uuid.UUID,
        data: ObservationUpdate,
    ) -> SafetyObservation:
        observation = await self.get_observation(observation_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recompute risk score if severity or likelihood changed
        severity = fields.get("severity", observation.severity)
        likelihood = fields.get("likelihood", observation.likelihood)
        if "severity" in fields or "likelihood" in fields:
            fields["risk_score"] = severity * likelihood

        if not fields:
            return observation

        # Capture the risk score before the update so we can detect a genuine
        # upward crossing of the critical threshold. The refresh below would
        # overwrite it with the new value.
        prior_risk_score = observation.risk_score

        await self.observation_repo.update_fields(observation_id, **fields)
        await self.session.refresh(observation)

        # Emit high-risk event only when the score crosses upward into the
        # critical band (prior <= 15 < new). Editing an already-high-risk
        # observation must not re-spam the event on every save.
        new_risk_score = fields.get("risk_score", observation.risk_score)
        if prior_risk_score <= 15 < new_risk_score:
            event_bus.publish_detached(
                "safety.observation.high_risk",
                data={
                    "project_id": str(observation.project_id),
                    "observation_id": str(observation_id),
                    "observation_number": observation.observation_number,
                    "risk_score": new_risk_score,
                    "description": (observation.description or "")[:200],
                    "notify_user_ids": [],
                },
                source_module="safety",
            )

        logger.info("Safety observation updated: %s (risk=%d)", observation_id, new_risk_score)
        return observation

    async def delete_observation(self, observation_id: uuid.UUID) -> None:
        await self.get_observation(observation_id)
        await self.observation_repo.delete(observation_id)
        logger.info("Safety observation deleted: %s", observation_id)

    # ── Stats & Trends ──────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> SafetyStatsResponse:
        """Compute safety KPIs for a project dashboard.

        Includes incident/observation counts, days without incident,
        LTIFR, TRIR, and breakdowns by type/status/risk tier.
        """
        from collections import defaultdict
        from datetime import UTC, date, datetime

        from sqlalchemy import select

        # Fetch all incidents
        inc_result = await self.session.execute(select(SafetyIncident).where(SafetyIncident.project_id == project_id))
        incidents = list(inc_result.scalars().all())

        # Fetch all observations
        obs_result = await self.session.execute(
            select(SafetyObservation).where(SafetyObservation.project_id == project_id)
        )
        observations = list(obs_result.scalars().all())

        total_incidents = len(incidents)
        total_observations = len(observations)
        total_days_lost = 0
        recordable_incidents = 0
        lost_time_incidents = 0
        # Sum of exposure hours, sourced from each incident's
        # ``metadata.man_hours_total`` (the documented convention below).
        # Used as the denominator for the OSHA-style frequency rates.
        total_hours_worked = 0.0
        incidents_by_type: dict[str, int] = defaultdict(int)
        incidents_by_status: dict[str, int] = defaultdict(int)
        open_corrective_actions = 0
        # Compare incidents by *parsed* date, not by raw string max: a
        # malformed string like "9999-99-99" must never win the comparison
        # and then mask a real recent incident.
        latest_incident_dt: date | None = None
        unparseable_incident_dates = 0

        for inc in incidents:
            total_days_lost += inc.days_lost or 0
            incidents_by_type[inc.incident_type] += 1
            incidents_by_status[inc.status] += 1

            # OSHA 300 recordability: the first-class ``osha_recordable``
            # flag is the documented gate. Fall back to the treatment-type
            # heuristic only when the flag was never set, so flagged
            # restricted-duty / first-aid recordables are still counted and
            # the KPI matches the OSHA log the schema is built for.
            if _is_recordable(inc):
                recordable_incidents += 1
            if inc.days_lost and inc.days_lost > 0:
                lost_time_incidents += 1

            # Accumulate exposure hours for the frequency-rate denominator.
            # Convention (documented at the LTIFR/TRIR computation below and in
            # the schema): man-hours live in ``metadata.man_hours_total``.
            # Tolerate strings/ints from JSON and ignore non-numeric or
            # negative junk rather than letting it corrupt the denominator.
            total_hours_worked += _incident_man_hours(inc)

            # Track latest incident date robustly. An unparseable date is
            # NOT silently dropped - it is counted so the metric can fail
            # safe toward "cannot confirm" instead of a reassuring blank.
            if inc.incident_date:
                parsed = parse_incident_date(inc.incident_date)
                if parsed is None:
                    unparseable_incident_dates += 1
                    logger.warning(
                        "Safety incident %s has an unparseable incident_date %r; "
                        "excluded from days-without-incident computation",
                        getattr(inc, "incident_number", inc.id),
                        inc.incident_date,
                    )
                elif latest_incident_dt is None or parsed > latest_incident_dt:
                    latest_incident_dt = parsed

            # Count open corrective actions
            for ca in inc.corrective_actions or []:
                if isinstance(ca, dict) and ca.get("status") in ("open", "in_progress"):
                    open_corrective_actions += 1

        # Days without incident.
        #   - "none": no incidents at all → field is None (genuinely clean).
        #   - "ok": computed from a parseable latest incident date.
        #   - "unconfirmed": incidents exist but no usable date → field stays
        #     None *and* status flags it, so the UI shows "cannot confirm"
        #     rather than a falsely-reassuring blank/large number.
        days_without_incident: int | None = None
        if total_incidents == 0:
            days_without_incident_status = "none"
        elif latest_incident_dt is not None:
            now_date = datetime.now(UTC).date()
            # Inclusive of "today": an incident dated today → 0 days since.
            days_without_incident = max(0, (now_date - latest_incident_dt).days)
            days_without_incident_status = "ok"
        else:
            # Incidents exist but none had a usable date - do NOT report a
            # reassuring number.
            days_without_incident_status = "unconfirmed"

        # Observations by risk tier
        observations_by_risk_tier: dict[str, int] = defaultdict(int)
        for obs in observations:
            tier = _compute_risk_tier(obs.risk_score)
            observations_by_risk_tier[tier] += 1

        # LTIFR and TRIR -- standard OSHA-style frequency rates.
        # Convention: man-hours come from each incident's
        # ``metadata.man_hours_total`` (summed into ``total_hours_worked``
        # in the loop above). When no incident carries man-hours the
        # denominator is unknown, so both rates stay None (not enough data)
        # rather than reporting a falsely-precise 0.0.
        #
        #   TRIR  = recordable_incidents * 200_000 / total_hours_worked
        #           (per 200k hours -> ~100 full-time workers per year)
        #   LTIFR = lost_time_incidents * 1_000_000 / total_hours_worked
        #           (per 1M hours, the international ILO/AS-1885 base the
        #            schema documents)
        ltifr: float | None = None
        trir: float | None = None
        if total_hours_worked > 0:
            trir = round(recordable_incidents * 200_000 / total_hours_worked, 2)
            ltifr = round(lost_time_incidents * 1_000_000 / total_hours_worked, 2)

        return SafetyStatsResponse(
            total_incidents=total_incidents,
            total_observations=total_observations,
            days_without_incident=days_without_incident,
            days_without_incident_status=days_without_incident_status,
            unparseable_incident_dates=unparseable_incident_dates,
            total_days_lost=total_days_lost,
            recordable_incidents=recordable_incidents,
            ltifr=ltifr,
            trir=trir,
            incidents_by_type=dict(incidents_by_type),
            incidents_by_status=dict(incidents_by_status),
            observations_by_risk_tier=dict(observations_by_risk_tier),
            open_corrective_actions=open_corrective_actions,
        )

    async def get_trends(
        self,
        project_id: uuid.UUID,
        period: str = "monthly",
    ) -> SafetyTrendsResponse:
        """Compute time-series safety data grouped by month or week.

        Args:
            project_id: Target project.
            period: 'monthly' (default) or 'weekly'.

        Returns:
            SafetyTrendsResponse with ordered entries.
        """
        from collections import defaultdict

        from sqlalchemy import select

        from app.modules.safety.schemas import SafetyTrendEntry

        # Fetch incidents
        inc_result = await self.session.execute(select(SafetyIncident).where(SafetyIncident.project_id == project_id))
        incidents = list(inc_result.scalars().all())

        # Fetch observations
        obs_result = await self.session.execute(
            select(SafetyObservation).where(SafetyObservation.project_id == project_id)
        )
        observations = list(obs_result.scalars().all())

        buckets: dict[str, dict[str, int]] = defaultdict(
            lambda: {"incident_count": 0, "observation_count": 0, "days_lost": 0}
        )

        def _bucket_key(date_str: str | None) -> str:
            """Derive a period key from a (possibly non-canonical) date string.

            Uses the same robust parser as the stats path so a malformed
            string yields a single honest "unknown" bucket instead of a
            nonsense key like "99/99/9" that fragments the chart.
            """
            d = parse_incident_date(date_str)
            if d is None:
                return "unknown"
            if period == "weekly":
                iso_year, iso_week, _ = d.isocalendar()
                return f"{iso_year}-W{iso_week:02d}"
            # monthly: YYYY-MM
            return f"{d.year:04d}-{d.month:02d}"

        for inc in incidents:
            key = _bucket_key(inc.incident_date)
            buckets[key]["incident_count"] += 1
            buckets[key]["days_lost"] += inc.days_lost or 0

        for obs in observations:
            # Observations use created_at for trending
            if obs.created_at:
                key = _bucket_key(str(obs.created_at)[:10])
                buckets[key]["observation_count"] += 1

        # Sort by period key
        entries = [
            SafetyTrendEntry(
                period=k,
                incident_count=v["incident_count"],
                observation_count=v["observation_count"],
                days_lost=v["days_lost"],
            )
            for k, v in sorted(buckets.items())
        ]

        return SafetyTrendsResponse(period_type=period, entries=entries)

    # ── Extended trends (LTIFR/TRIR time series) ────────────────────────────

    # Trailing-window size used for the "rolling 12-month" averages. Weekly
    # buckets keep the same intent ("about a year") at 52 periods.
    _ROLLING_MONTHS = 12
    _ROLLING_WEEKS = 52

    async def get_trends_extended(
        self,
        project_id: uuid.UUID,
        period: str = "monthly",
    ) -> SafetyTrendsExtendedResponse:
        """Compute a per-period LTIFR/TRIR time series with a trend direction.

        For every period bucket the man-hours are summed and the OSHA-style
        frequency rates are computed exactly as in :meth:`get_stats` (per 1M
        hours for LTIFR, per 200k for TRIR). A period with no usable man-hours
        keeps ``ltifr``/``trir`` as ``None`` so the chart can show a gap rather
        than a misleading zero.

        Args:
            project_id: Target project.
            period: 'monthly' (default) or 'weekly'.

        Returns:
            SafetyTrendsExtendedResponse with ordered entries, rolling
            averages, the current period's rates, and a trend direction.
        """
        from collections import defaultdict

        from sqlalchemy import select

        inc_result = await self.session.execute(select(SafetyIncident).where(SafetyIncident.project_id == project_id))
        incidents = list(inc_result.scalars().all())

        obs_result = await self.session.execute(
            select(SafetyObservation).where(SafetyObservation.project_id == project_id)
        )
        observations = list(obs_result.scalars().all())

        def _bucket_key(date_str: str | None) -> str:
            d = parse_incident_date(date_str)
            if d is None:
                return "unknown"
            if period == "weekly":
                iso_year, iso_week, _ = d.isocalendar()
                return f"{iso_year}-W{iso_week:02d}"
            return f"{d.year:04d}-{d.month:02d}"

        # Per-bucket accumulators. ``man_hours`` is the rate denominator;
        # recordable/lost-time are the TRIR/LTIFR numerators.
        buckets: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "incident_count": 0.0,
                "observation_count": 0.0,
                "days_lost": 0.0,
                "man_hours": 0.0,
                "recordable": 0.0,
                "lost_time": 0.0,
            }
        )

        for inc in incidents:
            key = _bucket_key(inc.incident_date)
            b = buckets[key]
            b["incident_count"] += 1
            b["days_lost"] += inc.days_lost or 0
            b["man_hours"] += _incident_man_hours(inc)
            if _is_recordable(inc):
                b["recordable"] += 1
            if inc.days_lost and inc.days_lost > 0:
                b["lost_time"] += 1

        for obs in observations:
            if obs.created_at:
                key = _bucket_key(str(obs.created_at)[:10])
                buckets[key]["observation_count"] += 1

        entries: list[SafetyTrendEntryExtended] = []
        for key, b in sorted(buckets.items()):
            man_hours = b["man_hours"]
            ltifr: float | None = None
            trir: float | None = None
            if man_hours > 0:
                trir = round(b["recordable"] * 200_000 / man_hours, 2)
                ltifr = round(b["lost_time"] * 1_000_000 / man_hours, 2)
            entries.append(
                SafetyTrendEntryExtended(
                    period=key,
                    incident_count=int(b["incident_count"]),
                    observation_count=int(b["observation_count"]),
                    days_lost=int(b["days_lost"]),
                    ltifr=ltifr,
                    trir=trir,
                    man_hours_total=round(man_hours, 2),
                    recordable_incidents=int(b["recordable"]),
                    lost_time_incidents=int(b["lost_time"]),
                )
            )

        # Rolling averages over the trailing window, ignoring "unknown"-keyed
        # buckets (malformed dates) and gaps with no usable rate so a missing
        # denominator never drags the mean toward zero.
        window = self._ROLLING_WEEKS if period == "weekly" else self._ROLLING_MONTHS
        dated = [e for e in entries if e.period != "unknown"]
        recent = dated[-window:]
        ltifr_vals = [e.ltifr for e in recent if e.ltifr is not None]
        trir_vals = [e.trir for e in recent if e.trir is not None]
        rolling_ltifr = round(sum(ltifr_vals) / len(ltifr_vals), 2) if ltifr_vals else None
        rolling_trir = round(sum(trir_vals) / len(trir_vals), 2) if trir_vals else None

        current_ltifr = dated[-1].ltifr if dated else None
        current_trir = dated[-1].trir if dated else None

        return SafetyTrendsExtendedResponse(
            period_type=period,
            entries=entries,
            rolling_12_month_ltifr=rolling_ltifr,
            rolling_12_month_trir=rolling_trir,
            current_period_ltifr=current_ltifr,
            current_period_trir=current_trir,
            trend_direction=_compute_trend_direction(dated),
        )

    async def get_threshold_alert(
        self,
        project_id: uuid.UUID,
        baseline_ltifr: float = 2.5,
        baseline_trir: float = 3.0,
    ) -> SafetyThresholdAlertResponse:
        """Check the project's current LTIFR/TRIR against safe-baselines.

        Reuses :meth:`get_stats` for the current rates (so the alert can never
        disagree with the dashboard KPIs), then bands each rate green/yellow/
        red and emits a ``safety.threshold_alert_triggered`` event when either
        rate is non-green so downstream BI / notification consumers can react.

        Args:
            project_id: Target project.
            baseline_ltifr: Safe-baseline LTIFR (per 1M hours).
            baseline_trir: Safe-baseline TRIR (per 200k hours).
        """
        stats = await self.get_stats(project_id)
        current_ltifr = stats.ltifr
        current_trir = stats.trir

        ltifr_status = _rate_status(current_ltifr, baseline_ltifr)
        trir_status = _rate_status(current_trir, baseline_trir)

        ltifr_delta = round(current_ltifr - baseline_ltifr, 2) if current_ltifr is not None else None
        trir_delta = round(current_trir - baseline_trir, 2) if current_trir is not None else None

        # Worst band drives the headline message; "unknown" is informational.
        order = {"red": 3, "yellow": 2, "green": 1, "unknown": 0}
        worst = ltifr_status if order[ltifr_status] >= order[trir_status] else trir_status
        if worst == "red":
            message = "One or more safety rates exceed 150% of baseline - immediate action required."
        elif worst == "yellow":
            message = "A safety rate is above baseline - monitor closely."
        elif worst == "green":
            message = "Safety rates are within baseline."
        else:
            message = "Not enough man-hours data to compute frequency rates."

        if worst in {"red", "yellow"}:
            event_bus.publish_detached(
                "safety.threshold_alert_triggered",
                {
                    "project_id": str(project_id),
                    "ltifr": current_ltifr,
                    "trir": current_trir,
                    "baseline_ltifr": baseline_ltifr,
                    "baseline_trir": baseline_trir,
                    "ltifr_status": ltifr_status,
                    "trir_status": trir_status,
                },
                source_module="safety",
            )

        return SafetyThresholdAlertResponse(
            current_ltifr=current_ltifr,
            current_trir=current_trir,
            baseline_ltifr=baseline_ltifr,
            baseline_trir=baseline_trir,
            ltifr_delta=ltifr_delta,
            trir_delta=trir_delta,
            ltifr_status=ltifr_status,
            trir_status=trir_status,
            message=message,
        )
