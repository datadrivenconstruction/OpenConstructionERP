# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Full EVM service - advanced Earned Value Management with forecasting.

Stateless service layer. Two surfaces live here.

:class:`EVMService` owns the legacy forecast rows derived from a finance EVM
snapshot, plus the predictive alerting that runs on top of them.

:class:`EVMBaselineService` owns the register proper: the performance
measurement baseline, its cumulative planned-value curve, and the measurements
taken against it. It computes every metric through
:mod:`app.modules.full_evm.metrics` (exact Decimal maths, undefined indices as
``None``) and runs the ``full_evm`` rule set on every write, persisting the
findings on the row.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.events import event_bus
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.full_evm.metrics import (
    EAC_FALLBACK_LADDER,
    EAC_METHODS,
    METRIC_GLOSSARY,
    EvmMetrics,
    compute_metrics,
    quantize_money,
    quantum_for_minor_units,
)
from app.modules.full_evm.models import EVMBaseline, EVMBaselinePeriod, EVMForecast, EVMMeasure
from app.modules.full_evm.repository import (
    EVMBaselineRepository,
    EVMForecastRepository,
    EVMMeasureRepository,
)
from app.modules.full_evm.schemas import (
    BaselineCreate,
    BaselinePeriodWrite,
    BaselineUpdate,
    EVMForecastCreate,
    MeasureCreate,
)
from app.modules.full_evm.validators import FULL_EVM_RULE_SET

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
QUANTIZE = Decimal("0.01")
# Upper bound for money values. A finite-but-absurd magnitude (e.g. '1e400')
# survives Decimal() and then overflows quantize() in calculate_forecast,
# aborting the whole batch; clamp such inputs to ZERO at the _dec() choke point.
_MONEY_MAX = Decimal("1e15")

# Event published when a freshly-computed forecast breaches a project
# AlertRule. Item #24 (risk/task auto-escalation) subscribes to this - we
# only emit it here; we never auto-escalate.
FORECAST_ALERT_EVENT = "forecast.alert_triggered"

# Published when a baseline becomes the approved measurement base for a
# project. Scheduling, reporting and change control all care that the number
# every future variance is measured against has moved.
BASELINE_APPROVED_EVENT = "evm.baseline_approved"

# Published on every recorded measurement so dashboards and the alerting
# surface can react without polling the register.
MEASURE_RECORDED_EVENT = "evm.measure_recorded"

# KPI codes an AlertRule may target against an EVM forecast. The batch job
# resolves each to a comparable Decimal from the forecast + its source
# snapshot metadata, then applies the rule's condition/threshold. Anything
# outside this set is silently ignored (forecasts can only speak to EVM
# metrics - other KPIs are bi_dashboards' job, not ours).
FORECAST_KPI_CODES = frozenset(
    {"cpi", "spi", "eac", "vac", "etc", "tcpi", "eac_over_bac"},
)

# Forecast method names accepted by ``calculate_forecast``, mapped onto the
# canonical EAC vocabulary shared with app.modules.eac.evm.
#
# ``spi_cpi`` is this module's original name for the formula the rest of the
# platform calls ``combined``; it stays accepted so existing job payloads and
# saved requests keep working, but the canonical name is what gets recorded.
# Anything outside this map is rejected rather than silently treated as the
# default: the standard EAC formulas disagree, so guessing which one the caller
# meant is how a project ends up reported healthy on the wrong maths.
FORECAST_METHOD_ALIASES: dict[str, str] = {
    "auto": "auto",
    "remaining": "remaining",
    "cpi": "cpi",
    "combined": "combined",
    "spi_cpi": "combined",
}

# Degradation ladder per requested formula. Imported from the metric kernel so
# this legacy surface and the register degrade identically: a second copy that
# drifted would answer the same question two ways inside one module.
_FORECAST_FALLBACK_LADDER = EAC_FALLBACK_LADDER


def _resolve_forecast_method(requested: str) -> str:
    """Map a requested forecast method onto its canonical EAC name.

    Args:
        requested: Method name from the API or a job payload.

    Returns:
        The canonical name, one of :data:`app.modules.full_evm.metrics.EAC_METHODS`.

    Raises:
        HTTPException: 422 when the name is not supported.
    """
    canonical = FORECAST_METHOD_ALIASES.get((requested or "").strip().lower())
    if canonical is None:
        allowed = ", ".join(sorted(FORECAST_METHOD_ALIASES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown forecast method '{requested}'. Choose one of: {allowed}.",
        )
    return canonical


def _dec(value: str) -> Decimal:
    """Safely convert a string to a finite, bounded Decimal.

    Returns ZERO for unparseable, non-finite (NaN/Infinity) or absurd-magnitude
    input so a downstream quantize() in calculate_forecast can never raise
    InvalidOperation and abort the whole forecast batch.

    The fallback is deliberately loud. Clamping a poisoned amount to zero keeps
    the batch running but produces a *plausible* forecast from data that is not,
    so every clamp is logged with the offending value: a silent zero is how a
    corrupt BAC turns into a healthy-looking project nobody questions. The newer
    register path does not share this behaviour - see
    :func:`app.modules.full_evm.metrics.to_decimal`, which rejects a non-finite
    amount outright rather than substituting one.
    """
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError):
        logger.warning("full_evm: unparseable EVM amount %r treated as zero", value)
        return ZERO
    if not d.is_finite() or abs(d) >= _MONEY_MAX:
        logger.warning("full_evm: out-of-range EVM amount %r treated as zero", value)
        return ZERO
    return d


@dataclass
class ForecastBreach:
    """A single AlertRule that a forecast breached.

    Carries everything the event payload and the notification need without
    re-querying the rule - stays decoupled from the bi_dashboards ORM.
    """

    rule_id: str
    rule_name: str
    kpi_code: str
    condition: str
    threshold: Decimal
    observed: Decimal
    severity: str
    recipients: list[str]
    channels: list[str]


def _compare(condition: str, observed: Decimal, threshold: Decimal) -> bool:
    """Apply an AlertRule comparison operator.

    Mirrors the operator grammar in ``bi_dashboards.service.evaluate_alert``
    (``above`` / ``below`` / ``equals`` / ``not_equals``); ``changed_by_…``
    needs history we don't track for forecasts, so it never fires here.
    """
    if condition == "above":
        return observed > threshold
    if condition == "below":
        return observed < threshold
    if condition == "equals":
        return observed == threshold
    if condition == "not_equals":
        return observed != threshold
    return False


class EVMService:
    """Business logic for advanced EVM forecasting."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.forecasts = EVMForecastRepository(session)

    async def list_forecasts(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> tuple[list[EVMForecast], int]:
        """List EVM forecasts for a project."""
        return await self.forecasts.list(project_id=project_id)

    async def create_forecast(self, data: EVMForecastCreate) -> EVMForecast:
        """Create an EVM forecast record manually."""
        forecast = EVMForecast(
            project_id=data.project_id,
            forecast_date=data.forecast_date,
            etc_=data.etc,
            eac=data.eac,
            vac=data.vac,
            tcpi=data.tcpi,
            forecast_method=data.forecast_method,
            confidence_range_low=data.confidence_range_low,
            confidence_range_high=data.confidence_range_high,
            notes=data.notes,
            metadata_=data.metadata,
        )
        forecast = await self.forecasts.create(forecast)
        logger.info("EVM forecast created: project=%s date=%s", data.project_id, data.forecast_date)
        return forecast

    async def calculate_forecast(
        self,
        project_id: uuid.UUID,
        forecast_method: str = "cpi",
    ) -> EVMForecast:
        """Calculate an EVM forecast from the latest finance EVM snapshot.

        Formulas, by method:

        ``cpi``
            ``ETC = (BAC - EV) / CPI``, so ``EAC = AC + (BAC - EV) / CPI``.
            The cost trend seen so far continues.
        ``combined`` (also accepted as the legacy name ``spi_cpi``)
            ``ETC = (BAC - EV) / (SPI * CPI)``. Cost and schedule trends both
            continue.
        ``remaining``
            ``ETC = BAC - EV``. The overspend so far was a one-off and the rest
            of the work runs to budget.
        ``auto``
            The richest formula whose inputs are defined: combined, else cpi,
            else remaining.

        In every case ``EAC = AC + ETC``, ``VAC = BAC - EAC`` and
        ``TCPI = (BAC - EV) / (BAC - AC)``.

        A requested formula whose divisor is zero cannot be computed. Rather
        than return nothing, the calculation falls back to ``remaining`` and
        records that fact: ``forecast_method`` keeps what was asked for and
        ``metadata.effective_method`` says what actually ran. A zero CPI is the
        normal state of a project that has earned nothing yet, so this path is
        expected, not exceptional - but it must never be invisible, because the
        two formulas give different answers.

        Args:
            project_id: Project to forecast.
            forecast_method: One of ``auto``, ``remaining``, ``cpi``,
                ``combined`` or the legacy alias ``spi_cpi``.

        Returns:
            The persisted :class:`EVMForecast` row.

        Raises:
            HTTPException: 404 when the project has no EVM snapshot yet, 422
                when ``forecast_method`` is not a supported name.
        """
        canonical_method = _resolve_forecast_method(forecast_method)

        # Get latest EVM snapshot from finance module
        from sqlalchemy import select

        from app.modules.finance.models import EVMSnapshot

        stmt = (
            select(EVMSnapshot)
            .where(EVMSnapshot.project_id == project_id)
            .order_by(EVMSnapshot.snapshot_date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        snapshot = result.scalar_one_or_none()

        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No EVM snapshots found for this project. Create a snapshot first.",
            )

        bac = _dec(snapshot.bac)
        ev = _dec(snapshot.ev)
        ac = _dec(snapshot.ac)
        cpi = _dec(snapshot.cpi)
        spi = _dec(snapshot.spi)

        # Calculate ETC, walking down from the requested formula to the
        # simplest one whose divisor is non-zero, and recording which one ran.
        remaining = bac - ev
        ladder = _FORECAST_FALLBACK_LADDER[canonical_method]
        effective_method = "remaining"
        etc = remaining
        for candidate in ladder:
            if candidate == "combined" and spi != ZERO and cpi != ZERO:
                effective_method = "combined"
                etc = (remaining / (spi * cpi)).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
                break
            if candidate == "cpi" and cpi != ZERO:
                effective_method = "cpi"
                etc = (remaining / cpi).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
                break
            if candidate == "remaining":
                break

        eac = (ac + etc).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        vac = (bac - eac).quantize(QUANTIZE, rounding=ROUND_HALF_UP)

        # TCPI = (BAC - EV) / (BAC - AC)
        # Denominator-zero edge case: BAC == AC means the project has already
        # consumed its entire budget. If any work remains (remaining > 0) the
        # true TCPI is mathematically infinite - returning 0 (the previous
        # behaviour) would falsely imply "no effort needed". We store the
        # sentinel "inf" so downstream consumers can render it as
        # "Not Achievable" / unbounded rather than treating it as a healthy 0.
        denominator = bac - ac
        if denominator != ZERO:
            tcpi = (remaining / denominator).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        elif remaining > ZERO:
            tcpi = None  # rendered as "inf" sentinel in the forecast row below
        else:
            tcpi = ZERO

        # Confidence range: +/- 10% of EAC
        range_factor = Decimal("0.10")
        conf_low = (eac * (1 - range_factor)).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        conf_high = (eac * (1 + range_factor)).quantize(QUANTIZE, rounding=ROUND_HALF_UP)

        forecast = EVMForecast(
            project_id=project_id,
            forecast_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            etc_=str(etc),
            eac=str(eac),
            vac=str(vac),
            tcpi="inf" if tcpi is None else str(tcpi),
            forecast_method=forecast_method,
            confidence_range_low=str(conf_low),
            confidence_range_high=str(conf_high),
            notes=(
                f"Auto-calculated from snapshot {snapshot.snapshot_date} using the "
                f"'{effective_method}' formula"
                + ("" if effective_method == canonical_method else f" (requested '{canonical_method}')")
            ),
            metadata_={
                "source_snapshot_id": str(snapshot.id),
                "source_snapshot_date": snapshot.snapshot_date,
                "bac": str(bac),
                "ev": str(ev),
                "ac": str(ac),
                "cpi": str(cpi),
                "spi": str(spi),
                # Provenance of the forecast: what was asked for, in canonical
                # form, and which formula could actually be evaluated. They
                # differ whenever a divisor was zero, and the two formulas give
                # materially different numbers.
                "requested_method": canonical_method,
                "effective_method": effective_method,
            },
        )
        forecast = await self.forecasts.create(forecast)
        logger.info(
            "EVM forecast calculated: project=%s requested=%s effective=%s EAC=%s",
            project_id,
            canonical_method,
            effective_method,
            eac,
        )
        return forecast

    async def get_s_curve_data(
        self,
        project_id: uuid.UUID,
    ) -> dict:
        """Return S-curve data combining EVM snapshots and forecasts."""
        from sqlalchemy import select

        from app.modules.finance.models import EVMSnapshot

        # Fetch all snapshots ordered by date
        snap_stmt = (
            select(EVMSnapshot).where(EVMSnapshot.project_id == project_id).order_by(EVMSnapshot.snapshot_date.asc())
        )
        snap_result = await self.session.execute(snap_stmt)
        snapshots = list(snap_result.scalars().all())

        # Fetch all forecasts ordered by date
        forecasts, _ = await self.forecasts.list(project_id=project_id)

        return {
            "project_id": str(project_id),
            "snapshots": [
                {
                    "date": s.snapshot_date,
                    "pv": s.pv,
                    "ev": s.ev,
                    "ac": s.ac,
                    "bac": s.bac,
                }
                for s in snapshots
            ],
            "forecasts": [
                {
                    "date": f.forecast_date,
                    "eac": f.eac,
                    "etc": f.etc_,
                    "vac": f.vac,
                    "tcpi": f.tcpi,
                    "method": f.forecast_method,
                    "confidence_low": f.confidence_range_low,
                    "confidence_high": f.confidence_range_high,
                }
                for f in sorted(forecasts, key=lambda x: x.forecast_date)
            ],
        }

    # ── Predictive alert evaluation (TOP-30 #19) ────────────────────────────

    async def _load_alert_rules(self, project_id: uuid.UUID) -> list[dict]:
        """Read enabled forecast-relevant AlertRules for a project.

        AlertRule lives in the ``bi_dashboards`` module which this module
        does not own; we read its table directly via raw SQL (the same
        cross-module-decoupled pattern ``project_intelligence.collector``
        uses) rather than importing its service. Project-scoped rules
        (``scope_project_id = pid``) and global rules (NULL scope) both
        apply. Failures degrade to "no rules" so a missing/renamed table
        never breaks forecast computation.
        """
        try:
            rows = (
                await self.session.execute(
                    text(
                        "SELECT id, name, kpi_code, condition, threshold_value, "
                        "       severity, recipients_json, channels_json "
                        "FROM oe_bi_dashboards_alert_rule "
                        "WHERE enabled = TRUE "
                        "  AND (scope_project_id = :pid OR scope_project_id IS NULL)"
                    ),
                    {"pid": str(project_id)},
                )
            ).fetchall()
        except Exception:
            logger.debug("full_evm: could not read alert rules for %s", project_id, exc_info=True)
            return []

        rules: list[dict] = []
        for r in rows:
            kpi = (r[2] or "").strip().lower()
            if kpi not in FORECAST_KPI_CODES:
                continue
            rules.append(
                {
                    "id": str(r[0]),
                    "name": r[1] or kpi,
                    "kpi_code": kpi,
                    "condition": (r[3] or "below").strip().lower(),
                    "threshold": _dec(str(r[4])) if r[4] is not None else ZERO,
                    "severity": (r[5] or "warning").strip().lower(),
                    "recipients": list(r[6] or []),
                    "channels": list(r[7] or []),
                }
            )
        return rules

    def _forecast_kpi_values(self, forecast: EVMForecast) -> dict[str, Decimal]:
        """Resolve every forecast KPI code to a comparable Decimal.

        ``cpi`` / ``spi`` come from the source snapshot stashed in the
        forecast metadata; ``eac`` / ``vac`` / ``etc`` / ``tcpi`` are the
        forecast's own fields. ``eac_over_bac`` is the overrun ratio
        (>1 means the project is forecast to finish over budget). The
        ``tcpi`` "inf" sentinel maps to a large finite Decimal so an
        ``above`` rule still fires on an unachievable to-complete index.
        """
        meta = forecast.metadata_ or {}
        bac = _dec(str(meta.get("bac", "0")))
        eac = _dec(forecast.eac)
        values: dict[str, Decimal] = {
            "cpi": _dec(str(meta.get("cpi", "0"))),
            "spi": _dec(str(meta.get("spi", "0"))),
            "eac": eac,
            "vac": _dec(forecast.vac),
            "etc": _dec(forecast.etc_),
            "eac_over_bac": (eac / bac) if bac != ZERO else ZERO,
        }
        values["tcpi"] = Decimal("9999") if forecast.tcpi == "inf" else _dec(forecast.tcpi)
        return values

    async def evaluate_forecast_against_rules(
        self,
        forecast: EVMForecast,
        project_id: uuid.UUID,
    ) -> list[ForecastBreach]:
        """Return the AlertRules a forecast breaches (empty == healthy).

        Deterministic threshold evaluation - no AI, no side effects. The
        batch job uses this; the unit tests call it directly.
        """
        rules = await self._load_alert_rules(project_id)
        if not rules:
            return []
        kpi_values = self._forecast_kpi_values(forecast)
        breaches: list[ForecastBreach] = []
        for rule in rules:
            observed = kpi_values.get(rule["kpi_code"])
            if observed is None:
                continue
            if _compare(rule["condition"], observed, rule["threshold"]):
                breaches.append(
                    ForecastBreach(
                        rule_id=rule["id"],
                        rule_name=rule["name"],
                        kpi_code=rule["kpi_code"],
                        condition=rule["condition"],
                        threshold=rule["threshold"],
                        observed=observed,
                        severity=rule["severity"],
                        recipients=rule["recipients"],
                        channels=rule["channels"],
                    )
                )
        return breaches

    async def _project_owner_id(self, project_id: uuid.UUID) -> str | None:
        """Look up the project owner - the default alert recipient."""
        try:
            row = (
                await self.session.execute(
                    text("SELECT owner_id FROM oe_projects_project WHERE id = :pid"),
                    {"pid": str(project_id)},
                )
            ).first()
            return str(row[0]) if row and row[0] else None
        except Exception:
            logger.debug("full_evm: owner lookup failed for %s", project_id, exc_info=True)
            return None

    async def _dispatch_alert_notifications(
        self,
        project_id: uuid.UUID,
        forecast: EVMForecast,
        breaches: list[ForecastBreach],
    ) -> None:
        """Send one in-app notification per recipient summarising the breach.

        Recipients are the union of every breached rule's ``recipients_json``;
        when a rule lists none we fall back to the project owner so the alert
        is never silently dropped. Uses the existing ``NotificationService``
        (pref-aware, throttled by the user's own digest settings). Best-effort:
        a notification failure never blocks the forecast batch.
        """
        recipients: set[str] = set()
        for breach in breaches:
            recipients.update(str(r) for r in breach.recipients if r)
        if not recipients:
            owner = await self._project_owner_id(project_id)
            if owner:
                recipients.add(owner)
        if not recipients:
            return

        worst = max(breaches, key=lambda b: _SEVERITY_RANK.get(b.severity, 0))
        kpi_label = worst.kpi_code.upper()
        try:
            from app.modules.notifications.service import NotificationService

            svc = NotificationService(self.session)
            for uid in recipients:
                await svc.create(
                    user_id=uid,
                    notification_type="forecast.alert_triggered",
                    title_key="notifications.forecast.alert.title",
                    body_key="notifications.forecast.alert.body",
                    body_context={
                        "kpi": kpi_label,
                        "observed": str(worst.observed),
                        "threshold": str(worst.threshold),
                        "count": len(breaches),
                    },
                    entity_type="evm_forecast",
                    entity_id=str(forecast.id),
                    action_url=f"/project-intelligence?project_id={project_id}&tab=forecasts",
                    metadata={
                        "severity": worst.severity,
                        "project_id": str(project_id),
                        "breaches": [
                            {
                                "rule_id": b.rule_id,
                                "kpi_code": b.kpi_code,
                                "observed": str(b.observed),
                                "threshold": str(b.threshold),
                            }
                            for b in breaches
                        ],
                    },
                )
        except Exception:
            logger.warning(
                "full_evm: alert notification dispatch failed for project %s",
                project_id,
                exc_info=True,
            )

    async def compute_project_forecasts_batch(
        self,
        project_ids: list[uuid.UUID],
        *,
        forecast_method: str = "cpi",
    ) -> list[dict]:
        """Compute a fresh forecast per project, evaluate alerts, dispatch.

        For each project:
            1. Recompute the forecast from the latest EVM snapshot.
            2. Evaluate it against the project's AlertRules.
            3. On a breach: stamp ``alert_status='triggered'`` + ``triggered_at``,
               publish ``forecast.alert_triggered`` (item #24 consumes it), and
               dispatch in-app notifications to the recipients.

        Projects without a snapshot are skipped (no forecast possible yet).
        Returns a per-project result summary for the job runner / tests.
        Caller owns the transaction - we ``flush`` but never ``commit`` so the
        batch is atomic with whatever drove it.
        """
        results: list[dict] = []
        for pid in project_ids:
            try:
                forecast = await self.calculate_forecast(pid, forecast_method=forecast_method)
            except HTTPException:
                # No snapshot for this project - nothing to forecast yet.
                results.append({"project_id": str(pid), "status": "no_snapshot"})
                continue
            except ArithmeticError:
                # A poisoned stored value (non-finite / overflow -> an
                # InvalidOperation, which is an ArithmeticError) must not abort
                # the whole batch; skip just this project. _dec() guards new
                # inputs - this covers legacy / raw-written rows.
                logger.exception("Forecast computation failed for project %s", pid)
                results.append({"project_id": str(pid), "status": "error"})
                continue

            breaches = await self.evaluate_forecast_against_rules(forecast, pid)
            if not breaches:
                results.append({"project_id": str(pid), "status": "ok", "alerts": 0})
                continue

            worst = max(breaches, key=lambda b: _SEVERITY_RANK.get(b.severity, 0))
            forecast.alert_status = "triggered"
            forecast.triggered_at = datetime.now(UTC)
            # Stash a compact breach summary on the forecast row so the
            # read endpoint can render the alert reason without re-querying
            # the (cross-module) AlertRule table. Sorted worst-first.
            meta = dict(forecast.metadata_ or {})
            meta["alert_breaches"] = [
                {
                    "rule_id": b.rule_id,
                    "rule_name": b.rule_name,
                    "kpi_code": b.kpi_code,
                    "condition": b.condition,
                    "threshold": str(b.threshold),
                    "observed": str(b.observed),
                    "severity": b.severity,
                }
                for b in sorted(
                    breaches,
                    key=lambda b: _SEVERITY_RANK.get(b.severity, 0),
                    reverse=True,
                )
            ]
            meta["alert_severity"] = worst.severity
            forecast.metadata_ = meta
            await self.session.flush()

            event_bus.publish_detached(
                FORECAST_ALERT_EVENT,
                {
                    "project_id": str(pid),
                    "forecast_id": str(forecast.id),
                    "severity": worst.severity,
                    "eac": forecast.eac,
                    "vac": forecast.vac,
                    "tcpi": forecast.tcpi,
                    "breaches": [
                        {
                            "rule_id": b.rule_id,
                            "rule_name": b.rule_name,
                            "kpi_code": b.kpi_code,
                            "condition": b.condition,
                            "threshold": str(b.threshold),
                            "observed": str(b.observed),
                            "severity": b.severity,
                        }
                        for b in breaches
                    ],
                },
                source_module="oe_full_evm",
            )
            await self._dispatch_alert_notifications(pid, forecast, breaches)
            results.append(
                {
                    "project_id": str(pid),
                    "status": "alerted",
                    "alerts": len(breaches),
                    "forecast_id": str(forecast.id),
                    "severity": worst.severity,
                }
            )
        return results

    async def acknowledge_alert(self, forecast_id: uuid.UUID) -> EVMForecast | None:
        """Resolve a triggered/snoozed forecast alert.

        Sets ``alert_status='acknowledged'``. Returns the row (None if the
        forecast does not exist). Caller owns IDOR + the transaction.
        """
        forecast = await self.forecasts.get(forecast_id)
        if forecast is None:
            return None
        forecast.alert_status = "acknowledged"
        await self.session.flush()
        logger.info("EVM forecast alert acknowledged: forecast=%s", forecast_id)
        return forecast

    async def snooze_alert(self, forecast_id: uuid.UUID, hours: int) -> EVMForecast | None:
        """Snooze a forecast alert for ``hours`` from now.

        Sets ``alert_status='snoozed'`` and records the snooze-until time in
        the forecast metadata so the UI can show a countdown. The next batch
        run re-triggers on the same condition; an elapsed snooze becomes a
        fresh trigger then.
        """
        forecast = await self.forecasts.get(forecast_id)
        if forecast is None:
            return None
        snooze_until = datetime.now(UTC) + timedelta(hours=max(1, hours))
        forecast.alert_status = "snoozed"
        meta = dict(forecast.metadata_ or {})
        meta["snoozed_until"] = snooze_until.isoformat()
        forecast.metadata_ = meta
        await self.session.flush()
        logger.info(
            "EVM forecast alert snoozed: forecast=%s until=%s",
            forecast_id,
            snooze_until.isoformat(),
        )
        return forecast


# Severity ranking - higher number == louder. Used to pick the "worst"
# breach when several rules fire on one forecast.
_SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "critical": 3,
}


# ── Baseline + measurement register ──────────────────────────────────────────


def _findings_from_report(report: ValidationReport) -> list[dict[str, Any]]:
    """Render a report's failing results as the compact rows stored on a row.

    Passing results are dropped: a stored finding list is a to-do list, and
    keeping the passes would bury the two lines that matter under twenty that
    do not. Engine errors are dropped too - an exception inside a rule is an
    infrastructure problem, not a finding about the data.
    """
    return [
        {
            "rule_id": result.rule_id,
            "severity": result.severity.value,
            "message": result.message,
            "element_ref": result.element_ref,
            "suggestion": result.suggestion,
            "details": dict(result.details or {}),
        }
        for result in report.results
        if not result.passed and not result.is_engine_error
    ]


def _apply_report(row: EVMBaseline | EVMMeasure, report: ValidationReport) -> None:
    """Persist a validation outcome onto the row it describes.

    ``validation_score`` is deliberately not defaulted to 1.0. The engine
    returns ``None`` when no compliance result was produced, and reporting a
    perfect score for something that was never checked is exactly the kind of
    quiet lie this module exists to prevent.
    """
    row.validation_status = report.status.value
    row.validation_findings = _findings_from_report(report)
    row.validation_score = report.score


def _baseline_validation_payload(
    baseline: EVMBaseline,
    periods: list[EVMBaselinePeriod],
) -> dict[str, Any]:
    """Render a baseline as the plain dict the ``full_evm`` rules read."""
    return {
        "kind": "baseline",
        "bac": str(baseline.bac),
        "currency": baseline.currency,
        "periods": [
            {
                "ordinal": period.ordinal,
                "label": period.label,
                "period_end": period.period_end.isoformat() if period.period_end else None,
                "planned_value": str(period.planned_value),
                "planned_quantity": None if period.planned_quantity is None else str(period.planned_quantity),
            }
            for period in periods
        ],
    }


def _measure_validation_payload(measure: EVMMeasure, baseline_pv: Decimal | None) -> dict[str, Any]:
    """Render a measurement as the plain dict the ``full_evm`` rules read."""

    def opt(value: Decimal | None) -> str | None:
        return None if value is None else str(value)

    return {
        "kind": "measure",
        "data_date": measure.data_date.isoformat() if measure.data_date else None,
        "bac": str(measure.bac),
        "pv": str(measure.pv),
        "ev": str(measure.ev),
        "ac": str(measure.ac),
        "baseline_pv": opt(baseline_pv),
        "spi": opt(measure.spi),
        "cpi": opt(measure.cpi),
        "tcpi_bac": opt(measure.tcpi_bac),
        "eac": opt(measure.eac),
        "eac_method": measure.eac_method,
        "eac_method_effective": measure.eac_method_effective,
    }


def planned_value_at(
    periods: list[EVMBaselinePeriod],
    on_date: date,
    *,
    start_date: date | None = None,
) -> Decimal | None:
    """Read the cumulative planned value from a baseline curve at a date.

    The curve is defined at period ends. Between two of them the planned value
    is interpolated linearly by elapsed days, which is the ordinary convention
    for a data date that does not land on a reporting boundary. Before the first
    period end the curve runs from the baseline's ``start_date`` at zero; with
    no start date there is nothing to interpolate from, so the first period's
    own value is the honest answer rather than an invented fraction of it.

    Args:
        periods: The curve, ordered by ``ordinal``.
        on_date: The data date to read the curve at.
        start_date: Baseline start, used as the zero point before period one.

    Returns:
        Cumulative planned value at ``on_date``, or ``None`` when the baseline
        has no curve at all.
    """
    if not periods:
        return None
    if on_date >= periods[-1].period_end:
        return periods[-1].planned_value

    upper_index = next(i for i, p in enumerate(periods) if p.period_end >= on_date)
    upper = periods[upper_index]
    if upper_index > 0:
        lower_end: date | None = periods[upper_index - 1].period_end
        lower_pv = periods[upper_index - 1].planned_value
    else:
        lower_end = start_date
        lower_pv = ZERO

    if lower_end is None or lower_end >= upper.period_end:
        return upper.planned_value

    span = (upper.period_end - lower_end).days
    elapsed = (on_date - lower_end).days
    if span <= 0 or elapsed <= 0:
        return lower_pv
    if elapsed >= span:
        return upper.planned_value
    return lower_pv + (upper.planned_value - lower_pv) * Decimal(elapsed) / Decimal(span)


class EVMBaselineService:
    """Business logic for the EVM baseline and measurement register.

    The caller owns the transaction: every method here ``flush``es so ids and
    defaults are populated, and none of them ``commit``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.baselines = EVMBaselineRepository(session)
        self.measures = EVMMeasureRepository(session)

    # ── Baselines ───────────────────────────────────────────────────────────

    async def create_baseline(self, data: BaselineCreate) -> EVMBaseline:
        """Create a baseline, optionally with its whole planned-value curve.

        Args:
            data: Validated create payload.

        Returns:
            The persisted baseline, already validated against the ``full_evm``
            rule set so its list row shows a real status instead of "pending".

        Raises:
            HTTPException: 409 when the project already has a baseline with
                this name - the pair is unique so a re-baseline is a new,
                distinguishable row rather than a silent overwrite.
        """
        existing = await self.baselines.find_by_name(data.project_id, data.name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Project already has a baseline named '{data.name}'.",
            )

        baseline = EVMBaseline(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            status="draft",
            bac=data.bac,
            currency=data.currency,
            minor_units=data.minor_units,
            start_date=data.start_date,
            finish_date=data.finish_date,
            metadata_=dict(data.metadata),
        )
        baseline = await self.baselines.create(baseline)
        if data.periods:
            await self._write_periods(baseline, data.periods)
        else:
            # A baseline created without a curve has an empty one, and the
            # database already agrees. Say so explicitly: without this the
            # collection stays unloaded on a persistent instance, and the first
            # read - validation here, or the router's response model straight
            # after - would emit a lazy SELECT from an async session and raise
            # MissingGreenlet. Creating the draft first and adding the curve
            # later is the natural authoring order, not an edge case.
            set_committed_value(baseline, "periods", [])
        await self.validate_baseline(baseline)
        logger.info("EVM baseline created: project=%s name=%s", data.project_id, data.name)
        return baseline

    async def get_baseline(self, baseline_id: uuid.UUID) -> EVMBaseline | None:
        """Return a baseline with its curve, or ``None``."""
        return await self.baselines.get(baseline_id)

    async def list_baselines(
        self,
        *,
        project_id: uuid.UUID,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EVMBaseline], int]:
        """List a project's baselines, newest first."""
        return await self.baselines.list(
            project_id=project_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )

    async def update_baseline(self, baseline: EVMBaseline, data: BaselineUpdate) -> EVMBaseline:
        """Patch a baseline's editable fields and re-validate it.

        Args:
            baseline: The row to patch.
            data: Only the supplied fields are written.

        Returns:
            The updated baseline.

        Raises:
            HTTPException: 409 when the baseline is approved (an approved
                baseline is the thing performance is measured against, so it is
                superseded by a new one rather than edited under the numbers
                already reported against it), or when the new name collides.
        """
        if baseline.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An approved baseline cannot be edited, because measurements already reported "
                    "against it would change meaning. Create a new baseline and approve that instead."
                ),
            )

        fields = data.model_dump(exclude_unset=True)
        new_name = fields.get("name")
        if new_name is not None and new_name != baseline.name:
            clash = await self.baselines.find_by_name(baseline.project_id, new_name)
            if clash is not None and clash.id != baseline.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Project already has a baseline named '{new_name}'.",
                )

        for key, value in fields.items():
            if key == "metadata":
                baseline.metadata_ = dict(value or {})
            else:
                setattr(baseline, key, value)
        await self.session.flush()
        await self.validate_baseline(baseline)
        logger.info("EVM baseline updated: %s", baseline.id)
        return baseline

    async def delete_baseline(self, baseline: EVMBaseline) -> None:
        """Delete a baseline together with its curve and measurements.

        Raises:
            HTTPException: 409 when the baseline is approved. Deleting the
                measurement base under a reported history is never what the
                caller wants; archive it instead.
        """
        if baseline.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An approved baseline cannot be deleted. Supersede or archive it instead.",
            )
        await self.baselines.delete(baseline)
        logger.info("EVM baseline deleted: %s", baseline.id)

    async def replace_periods(
        self,
        baseline: EVMBaseline,
        periods: list[BaselinePeriodWrite],
    ) -> EVMBaseline:
        """Replace the whole planned-value curve and re-validate.

        Raises:
            HTTPException: 409 when the baseline is approved.
        """
        if baseline.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The curve of an approved baseline cannot be changed. Create a new baseline instead.",
            )
        await self._write_periods(baseline, periods)
        await self.validate_baseline(baseline)
        logger.info("EVM baseline curve replaced: %s (%d periods)", baseline.id, len(periods))
        return baseline

    async def _write_periods(self, baseline: EVMBaseline, periods: list[BaselinePeriodWrite]) -> None:
        """Persist a curve in submitted order, renumbering the ordinals.

        Sorting is left to the caller on purpose: an out-of-order submission is
        a real authoring mistake that ``full_evm.baseline_periods_ordered``
        reports, and silently sorting it here would hide the fault while
        changing the numbers.
        """
        rows = [
            EVMBaselinePeriod(
                baseline_id=baseline.id,
                ordinal=index,
                period_end=period.period_end,
                label=period.label,
                planned_value=period.planned_value,
                planned_quantity=period.planned_quantity,
            )
            for index, period in enumerate(periods)
        ]
        await self.baselines.replace_periods(baseline.id, rows)
        # Publish the fresh rows as the collection's *loaded* state.
        #
        # A plain `baseline.periods = rows` would be wrong twice over: on a
        # persistent instance whose collection was never loaded, the assignment
        # first emits a lazy SELECT to compute the delta - synchronous IO from
        # an async session, i.e. MissingGreenlet - and then hands the unit of
        # work a second, duplicate set of inserts for rows the bulk write above
        # already persisted. ``set_committed_value`` records the loaded value
        # with no history and no query, which is exactly the situation: the
        # database and this list already agree.
        set_committed_value(baseline, "periods", rows)

    async def approve_baseline(
        self,
        baseline: EVMBaseline,
        *,
        approved_by: uuid.UUID | None = None,
    ) -> EVMBaseline:
        """Approve a baseline, superseding the project's previous approved one.

        Validation is re-run first and a baseline with blocking errors is
        refused. This is the one place the rules are a gate rather than a
        report: a draft may be half-entered, but the moment a curve becomes the
        thing every future SPI is divided by, an error in it is no longer a
        work-in-progress state.

        Args:
            baseline: The baseline to approve.
            approved_by: User id recorded on the approval.

        Returns:
            The approved baseline.

        Raises:
            HTTPException: 409 when the baseline is already approved or has
                blocking validation errors.
        """
        if baseline.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This baseline is already approved.",
            )

        report = await self._run_baseline_rules(baseline)
        _apply_report(baseline, report)
        if report.has_errors:
            messages = "; ".join(r.message for r in report.errors[:5])
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Baseline cannot be approved while it has validation errors: {messages}",
            )

        previous = await self.baselines.get_approved(baseline.project_id)
        if previous is not None and previous.id != baseline.id:
            previous.status = "superseded"

        baseline.status = "approved"
        baseline.approved_by = approved_by
        baseline.approved_at = datetime.now(UTC)
        await self.session.flush()

        event_bus.publish_detached(
            BASELINE_APPROVED_EVENT,
            {
                "project_id": str(baseline.project_id),
                "baseline_id": str(baseline.id),
                "bac": str(baseline.bac),
                "currency": baseline.currency,
                "superseded_baseline_id": None if previous is None else str(previous.id),
            },
            source_module="oe_full_evm",
        )
        logger.info("EVM baseline approved: %s (project=%s)", baseline.id, baseline.project_id)
        return baseline

    async def _run_baseline_rules(self, baseline: EVMBaseline) -> ValidationReport:
        """Run the ``full_evm`` rule set over a baseline and its curve."""
        periods = await self.baselines.list_periods(baseline.id)
        return await validation_engine.validate(
            data=_baseline_validation_payload(baseline, periods),
            rule_sets=[FULL_EVM_RULE_SET],
            target_type="evm_baseline",
            target_id=str(baseline.id),
            project_id=str(baseline.project_id),
        )

    async def validate_baseline(self, baseline: EVMBaseline) -> ValidationReport:
        """Validate a baseline and persist the outcome on the row.

        Never blocks: the findings are stored so a list view can show whether a
        plan is sound. :meth:`approve_baseline` is where they become a gate.
        """
        report = await self._run_baseline_rules(baseline)
        _apply_report(baseline, report)
        await self.session.flush()
        return report

    # ── Measurements ────────────────────────────────────────────────────────

    async def record_measure(self, baseline: EVMBaseline, data: MeasureCreate) -> EVMMeasure:
        """Record (or re-record) an EVM measurement for one data date.

        The Planned Value comes from the baseline curve unless the caller
        overrides it, which is the whole reason the curve is stored. Every
        derived metric is computed exactly in
        :mod:`app.modules.full_evm.metrics` and persisted, because a
        measurement is a historical fact that must not change when the baseline
        is later re-approved.

        Re-recording the same ``data_date`` updates the existing row rather than
        creating a second, contradictory truth for one cutoff.

        Args:
            baseline: The baseline being measured against.
            data: Validated measurement payload.

        Returns:
            The persisted measurement, already validated.

        Raises:
            HTTPException: 422 when the observations cannot produce a metric
                set (a negative or non-finite amount, or an unsupported EAC
                method name).
        """
        periods = await self.baselines.list_periods(baseline.id)
        curve_pv = planned_value_at(periods, data.data_date, start_date=baseline.start_date)
        quantum = quantum_for_minor_units(baseline.minor_units)

        bac = baseline.bac if data.bac is None else data.bac
        pv = data.pv if data.pv is not None else (curve_pv if curve_pv is not None else ZERO)

        try:
            metrics = compute_metrics(
                bac=bac,
                pv=pv,
                ev=data.ev,
                ac=data.ac,
                method=data.eac_method,
                quantum=quantum,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        measure = await self.measures.get_by_date(baseline.id, data.data_date)
        if measure is None:
            measure = EVMMeasure(
                baseline_id=baseline.id,
                project_id=baseline.project_id,
                data_date=data.data_date,
            )
            self.session.add(measure)

        self._apply_metrics(measure, metrics)
        measure.source = data.source
        measure.currency = baseline.currency
        measure.planned_quantity = quantize_money(data.planned_quantity, quantum)
        measure.actual_quantity = quantize_money(data.actual_quantity, quantum)
        measure.notes = data.notes
        measure.metadata_ = dict(data.metadata)
        await self.session.flush()

        await self.validate_measure(measure, baseline_pv=curve_pv)

        event_bus.publish_detached(
            MEASURE_RECORDED_EVENT,
            {
                "project_id": str(baseline.project_id),
                "baseline_id": str(baseline.id),
                "measure_id": str(measure.id),
                "data_date": data.data_date.isoformat(),
                "cpi": None if measure.cpi is None else str(measure.cpi),
                "spi": None if measure.spi is None else str(measure.spi),
                "eac": None if measure.eac is None else str(measure.eac),
                "eac_method_effective": measure.eac_method_effective,
            },
            source_module="oe_full_evm",
        )
        logger.info(
            "EVM measure recorded: baseline=%s date=%s cpi=%s eac=%s (%s)",
            baseline.id,
            data.data_date,
            measure.cpi,
            measure.eac,
            measure.eac_method_effective,
        )
        return measure

    @staticmethod
    def _apply_metrics(measure: EVMMeasure, metrics: EvmMetrics) -> None:
        """Copy a computed metric set onto a measurement row."""
        measure.bac = metrics.bac
        measure.pv = metrics.pv
        measure.ev = metrics.ev
        measure.ac = metrics.ac
        measure.sv = metrics.sv
        measure.cv = metrics.cv
        measure.spi = metrics.spi
        measure.cpi = metrics.cpi
        measure.percent_complete = metrics.percent_complete
        measure.percent_spent = metrics.percent_spent
        measure.eac_method = metrics.eac_method_requested
        measure.eac_method_effective = metrics.eac_method_effective
        measure.eac = metrics.eac
        measure.etc_ = metrics.etc
        measure.vac = metrics.vac
        measure.tcpi_bac = metrics.tcpi_bac
        measure.tcpi_eac = metrics.tcpi_eac
        measure.eac_variants = {
            name: None if value is None else str(value) for name, value in metrics.eac_variants.items()
        }

    async def validate_measure(
        self,
        measure: EVMMeasure,
        *,
        baseline_pv: Decimal | None = None,
    ) -> ValidationReport:
        """Validate a measurement and persist the outcome on the row."""
        report = await validation_engine.validate(
            data=_measure_validation_payload(measure, baseline_pv),
            rule_sets=[FULL_EVM_RULE_SET],
            target_type="evm_measure",
            target_id=str(measure.id),
            project_id=str(measure.project_id),
        )
        _apply_report(measure, report)
        await self.session.flush()
        return report

    async def get_measure(self, measure_id: uuid.UUID) -> EVMMeasure | None:
        """Return a measurement by id, or ``None``."""
        return await self.measures.get(measure_id)

    async def list_measures(
        self,
        *,
        baseline_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EVMMeasure], int]:
        """List measurements oldest first."""
        return await self.measures.list(
            baseline_id=baseline_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

    async def delete_measure(self, measure: EVMMeasure) -> None:
        """Delete a measurement."""
        await self.measures.delete(measure)
        logger.info("EVM measure deleted: %s", measure.id)

    # ── Reporting ───────────────────────────────────────────────────────────

    async def build_s_curve(self, baseline_id: uuid.UUID) -> dict[str, Any]:
        """Build the plan-versus-actual curve for one baseline.

        Every period end contributes a point carrying the planned value. The
        earned value, actual cost and forecast come from the latest measurement
        falling *inside* that period - after the previous period end, up to and
        including this one. A period nobody measured carries nulls rather than
        zeros or a repeat of the month before, so the actual curve stops where
        the data stops, which is what an EVM chart is supposed to show.

        Carrying the previous measurement forward would be the more forgiving
        choice and the wrong one: it states an earned value for a month nobody
        reported, so a month of unreported progress is drawn identically to a
        month of no progress, and February's EAC is labelled as March's
        forecast. An unknown has to read as unknown.

        Args:
            baseline_id: Baseline to plot.

        Returns:
            A dict matching
            :class:`~app.modules.full_evm.schemas.BaselineSCurveResponse`.

        Raises:
            HTTPException: 404 when the baseline does not exist.
        """
        baseline = await self.baselines.get_with_measures(baseline_id)
        if baseline is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Baseline {baseline_id} not found",
            )

        periods = sorted(baseline.periods, key=lambda p: p.ordinal)
        measures = sorted(baseline.measures, key=lambda m: m.data_date)

        points: list[dict[str, Any]] = []
        previous_end: date | None = None
        for period in periods:
            # Latest measurement inside this period's window. The lower bound is
            # exclusive so a measurement dated exactly on a period end belongs to
            # the period it closes, never to the next one as well.
            latest = None
            for measure in measures:
                if measure.data_date > period.period_end:
                    break
                if previous_end is None or measure.data_date > previous_end:
                    latest = measure
            previous_end = period.period_end
            points.append(
                {
                    "as_of": period.period_end,
                    "label": period.label,
                    "planned_value": str(period.planned_value),
                    "earned_value": None if latest is None else str(latest.ev),
                    "actual_cost": None if latest is None else str(latest.ac),
                    "forecast": None if latest is None or latest.eac is None else str(latest.eac),
                }
            )

        # A measurement past the end of the curve still belongs on the chart:
        # it is exactly the overrun the plan did not foresee.
        if measures and periods and measures[-1].data_date > periods[-1].period_end:
            last = measures[-1]
            points.append(
                {
                    "as_of": last.data_date,
                    "label": "",
                    "planned_value": str(periods[-1].planned_value),
                    "earned_value": str(last.ev),
                    "actual_cost": str(last.ac),
                    "forecast": None if last.eac is None else str(last.eac),
                }
            )

        return {
            "baseline_id": baseline.id,
            "project_id": baseline.project_id,
            "currency": baseline.currency,
            "bac": str(baseline.bac),
            "points": points,
        }


def metric_glossary() -> dict[str, Any]:
    """Return the EVM vocabulary in plain language.

    Every metric this module reports is a three-letter code that means nothing
    to someone reading it for the first time, so the API serves the glossary
    alongside the numbers rather than assuming the reader already knows.
    """
    return {
        "metrics": [
            {"code": code, "label": label, "explanation": explanation}
            for code, (label, explanation) in sorted(METRIC_GLOSSARY.items())
        ],
        "eac_methods": [
            {
                "name": "auto",
                "formula": "the richest formula whose inputs are defined",
                "use_when": "you want the best available forecast without choosing a school of thought",
            },
            {
                "name": "remaining",
                "formula": "EAC = AC + (BAC - EV)",
                "use_when": "the overspend so far was a one-off and the remaining work will run to budget",
            },
            {
                "name": "cpi",
                "formula": "EAC = BAC / CPI",
                "use_when": "the cost performance seen so far is the best predictor of the rest",
            },
            {
                "name": "combined",
                "formula": "EAC = AC + (BAC - EV) / (CPI * SPI)",
                "use_when": "being behind schedule is expected to keep pushing cost up",
            },
        ],
        "supported_methods": list(EAC_METHODS),
    }


__all__ = [
    "BASELINE_APPROVED_EVENT",
    "FORECAST_ALERT_EVENT",
    "FORECAST_METHOD_ALIASES",
    "MEASURE_RECORDED_EVENT",
    "EVMBaselineService",
    "EVMService",
    "ForecastBreach",
    "metric_glossary",
    "planned_value_at",
]
