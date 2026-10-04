# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk Register service - business logic for risk management.

Stateless service layer. Handles:
- Risk CRUD with auto-generated codes (R-001, R-002, ...)
- Risk score computation: probability x severity_numeric
- Summary aggregation and risk matrix data
"""

import logging
import math
import random
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.risk.contingency import (
    MATERIALISED_STATUS,
    ContingencyLine,
    DrawdownRecord,
    RiskMoney,
    allocated_amount,
    build_position,
    clamp_probability,
    default_line,
    fx_map_from_rates,
    norm_code,
    parse_drawdown_record,
    quantize_money,
    resolve_base_currency,
    risk_weight,
    to_decimal,
)
from app.modules.risk.models import RiskItem
from app.modules.risk.repository import RiskRepository
from app.modules.risk.schemas import (
    SEVERITY_ALIASES,
    SEVERITY_CANONICAL,
    ContingencyDrawdownRequest,
    RiskCreate,
    RiskUpdate,
)

logger = logging.getLogger(__name__)
_logger_events = logging.getLogger(__name__ + ".events")


async def _safe_publish(
    name: str,
    data: dict[str, Any],
    source_module: str = "oe_risk",
) -> None:
    """Publish event safely - best-effort, never blocks the caller."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_events.debug("Event publish skipped: %s", name)


# Severity → 1-5 numeric scale. Built from the canonical vocabulary in
# schemas.py so the request-schema regex and this map are derived from a
# single source and can never drift (F-PFO-RISK-03). SEVERITY_CANONICAL is
# ordered very_low→critical, so its index+1 is the 1-5 rank; each legacy
# alias maps onto the canonical level at the same ordinal position
# (negligible≈very_low … catastrophic≈critical).
SEVERITY_NUMERIC: dict[str, int] = {level: rank for rank, level in enumerate(SEVERITY_CANONICAL, start=1)}
SEVERITY_NUMERIC.update({alias: rank for rank, alias in enumerate(SEVERITY_ALIASES, start=1)})

# 5x5 matrix scoring: maps probability to a 1-5 score
PROBABILITY_SCORE_MAP: list[tuple[float, int]] = [
    (0.2, 1),  # very low
    (0.4, 2),  # low
    (0.6, 3),  # medium
    (0.8, 4),  # high
    (1.0, 5),  # very high
]

# Impact severity to 1-5 score for the canonical 5x5 PMBOK risk matrix.
# Identical scale to SEVERITY_NUMERIC and likewise derived from the shared
# schema vocabulary - kept as a separate name for call-site clarity.
IMPACT_SCORE_MAP: dict[str, int] = dict(SEVERITY_NUMERIC)


def _probability_to_score(probability: float) -> int:
    """Map probability (0.0-1.0) to a 1-5 score for the 5x5 matrix."""
    for threshold, score in PROBABILITY_SCORE_MAP:
        if probability <= threshold:
            return score
    return 5


def _compute_risk_tier(prob_score: int, impact_score: int) -> str:
    """Compute risk tier from probability_score x impact_score (1-25 range).

    1-4: low, 5-9: medium, 10-15: high, 16-25: critical
    """
    product = prob_score * impact_score
    if product >= 16:
        return "critical"
    if product >= 10:
        return "high"
    if product >= 5:
        return "medium"
    return "low"


def _compute_risk_score(probability: float, severity: str) -> float:
    """Compute risk score as probability x severity_numeric."""
    return round(probability * SEVERITY_NUMERIC.get(severity, 2), 2)


class RiskService:
    """Business logic for risk register operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RiskRepository(session)

    async def _get_project_currency(self, project_id: uuid.UUID) -> str:
        """Return the owning project's configured currency.

        Currency is strictly data-driven - it comes from the project record
        and nowhere else. When the project has no currency set (or the
        lookup fails) we return an empty string rather than fabricating a
        default (mirrors costmodel/finance). The UI renders a currency-less
        number instead of silently mislabelling, e.g., AED costs as EUR.
        """
        try:
            from app.modules.projects.repository import ProjectRepository

            repo = ProjectRepository(self.session)
            project = await repo.get_by_id(project_id)
            return project.currency if project and project.currency else ""
        except Exception:
            return ""

    async def _maybe_escalate(self, risk_id: uuid.UUID) -> bool:
        """Run the auto-escalation engine for one risk (on-create/update hook).

        Best-effort: escalation must never break a normal CRUD path, so any
        failure is logged and swallowed. Returns True iff the risk was
        escalated by this call.
        """
        try:
            from app.modules.risk.escalation import RiskEscalationService

            return await RiskEscalationService(self.session).evaluate_one(risk_id)
        except Exception:
            logger.debug("Risk auto-escalation hook failed for %s", risk_id, exc_info=True)
            return False

    # ── Create ────────────────────────────────────────────────────────────

    async def create_risk(
        self,
        data: RiskCreate,
        *,
        user_id: str | None = None,
    ) -> RiskItem:
        """Create a new risk item with auto-generated code."""
        count = await self.repo.count_for_project(data.project_id)
        code = f"R-{count + 1:03d}"

        # Currency is data-driven: an explicit payload value wins, else it
        # is inherited from the owning project. Never a hardcoded "EUR".
        currency = data.currency or await self._get_project_currency(data.project_id)

        risk_score = _compute_risk_score(data.probability, data.impact_severity)

        # 5x5 matrix scoring
        prob_score = _probability_to_score(data.probability)
        impact_score = IMPACT_SCORE_MAP.get(data.impact_severity, 2)
        risk_tier = _compute_risk_tier(prob_score, impact_score)

        item = RiskItem(
            project_id=data.project_id,
            code=code,
            title=data.title,
            description=data.description,
            category=data.category,
            probability=str(data.probability),
            impact_cost=str(data.impact_cost),
            impact_schedule_days=data.impact_schedule_days,
            impact_severity=data.impact_severity,
            status=data.status,
            risk_score=str(risk_score),
            probability_score=prob_score,
            impact_score_cost=impact_score,
            impact_score_time=impact_score,
            risk_tier=risk_tier,
            mitigation_strategy=data.mitigation_strategy,
            contingency_plan=data.contingency_plan,
            owner_name=data.owner_name,
            owner_user_id=data.owner_user_id,
            response_cost=str(data.response_cost),
            currency=currency,
            escalation_threshold=data.escalation_threshold,
            metadata_=data.metadata,
        )
        item = await self.repo.create(item)
        logger.info("Risk created: %s for project %s", code, data.project_id)
        # On-create escalation hook: a risk can be born already critical (or
        # imported with a lapsed review date), so evaluate it immediately.
        await self._maybe_escalate(item.id)
        await _safe_publish(
            "risk.risk.created",
            {
                "risk_id": str(item.id),
                "project_id": str(data.project_id),
                "code": code,
                "title": data.title,
            },
        )
        if data.owner_user_id is not None:
            await _safe_publish(
                "risk.assigned",
                {
                    "risk_id": str(item.id),
                    "project_id": str(data.project_id),
                    "code": code,
                    "title": data.title,
                    "owner_user_id": str(data.owner_user_id),
                    "assigned_by": user_id or "",
                },
            )
        return item

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_risk(self, risk_id: uuid.UUID) -> RiskItem:
        """Get risk item by ID. Raises 404 if not found."""
        item = await self.repo.get_by_id(risk_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Risk item not found",
            )
        return item

    async def list_risks(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        category_filter: str | None = None,
        severity_filter: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[RiskItem], int]:
        """List risk items for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            category=category_filter,
            severity=severity_filter,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_risk(
        self,
        risk_id: uuid.UUID,
        data: RiskUpdate,
        *,
        user_id: str | None = None,
    ) -> RiskItem:
        """Update risk item fields. Recalculates risk_score if needed."""
        item = await self.get_risk(risk_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(item, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        if not fields:
            return item

        # Recalculate risk_score and 5x5 matrix scoring if probability or severity changed.
        # Stored numerics can be "" on legacy/imported rows (DB-level defaults were
        # removed), so coerce defensively like the read paths instead of float("").
        probability = fields.get("probability")
        if probability is None:
            probability = _safe_float(item.probability, 0.5)
        severity = fields.get("impact_severity", item.impact_severity)
        if "probability" in fields or "impact_severity" in fields:
            fields["risk_score"] = str(_compute_risk_score(probability, severity))
            prob_score = _probability_to_score(probability)
            impact_score = IMPACT_SCORE_MAP.get(severity, 2)
            fields["probability_score"] = prob_score
            fields["impact_score_cost"] = impact_score
            fields["impact_score_time"] = impact_score
            fields["risk_tier"] = _compute_risk_tier(prob_score, impact_score)

        # Convert float fields to strings for storage
        for key in ("probability", "impact_cost", "response_cost"):
            if key in fields:
                fields[key] = str(fields[key])

        # Snapshot owner before update so we can detect (re)assignment.
        old_owner = str(item.owner_user_id) if item.owner_user_id else None
        new_owner = fields.get("owner_user_id")
        code_s = item.code
        title_s = item.title
        project_id_s = str(item.project_id)

        await self.repo.update_fields(risk_id, **fields)
        await self.session.refresh(item)

        # On-update escalation hook: re-score may have crossed the threshold,
        # or the metadata may carry a (now lapsed) review date. Idempotent -
        # a no-op when the risk is already escalated or below threshold.
        await self._maybe_escalate(risk_id)

        logger.info("Risk updated: %s (fields=%s)", risk_id, list(fields.keys()))
        await _safe_publish(
            "risk.risk.updated",
            {
                "risk_id": str(risk_id),
                "project_id": project_id_s,
                "changes": list(fields.keys()),
            },
        )
        if "owner_user_id" in fields and new_owner is not None and str(new_owner) != old_owner:
            await _safe_publish(
                "risk.assigned",
                {
                    "risk_id": str(risk_id),
                    "project_id": project_id_s,
                    "code": code_s,
                    "title": title_s,
                    "owner_user_id": str(new_owner),
                    "assigned_by": user_id or "",
                },
            )
        return item

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_risk(self, risk_id: uuid.UUID) -> None:
        """Delete a risk item."""
        item = await self.get_risk(risk_id)  # Raises 404 if not found
        project_id = str(item.project_id)
        await self.repo.delete(risk_id)
        logger.info("Risk deleted: %s", risk_id)
        await _safe_publish(
            "risk.risk.deleted",
            {
                "risk_id": str(risk_id),
                "project_id": project_id,
            },
        )

    # ── Summary ───────────────────────────────────────────────────────────

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's risk register."""
        items = await self.repo.all_for_project(project_id)
        drawn_ids = await self._drawn_risk_ids(project_id) if items else set()

        by_status: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        by_category: dict[str, int] = {}
        high_critical_count = 0
        mitigated_count = 0
        with_mitigation = 0
        without_mitigation = 0
        # Exposure grouped per currency. Summing impact across mixed
        # currencies under one last-wins label is wrong (F-PFO-RISK-04);
        # we keep each currency separate. "" is the bucket for risks with
        # no resolvable currency.
        exposure_by_currency: dict[str, float] = {}
        risk_scores: list[float] = []
        scored_items: list[tuple[str, float]] = []

        for item in items:
            by_status[item.status] = by_status.get(item.status, 0) + 1
            by_category[item.category] = by_category.get(item.category, 0) + 1

            # Tier breakdown by risk_tier (computed from 5x5 matrix)
            tier = item.risk_tier or item.impact_severity or "medium"
            by_tier[tier] = by_tier.get(tier, 0) + 1

            if item.impact_severity in ("high", "critical"):
                high_critical_count += 1

            # A risk counts as "mitigated" once a mitigation is in flight or
            # complete. Beyond the in-flight "mitigating" and terminal
            # "closed" states, the canonical vocabulary (schemas.STATUS_VALUES)
            # and seed data also use the explicit "mitigated" state plus
            # "monitoring" (mitigation applied, now being watched) - both were
            # previously excluded, understating the Mitigated stat card.
            if item.status in ("mitigating", "mitigated", "monitoring", "closed"):
                mitigated_count += 1

            # Mitigation tracking
            if item.mitigation_strategy and item.mitigation_strategy.strip():
                with_mitigation += 1
            else:
                without_mitigation += 1

            # Exposure = impact_cost x weight, accumulated per currency. The
            # weight is the contingency card's rule (contingency.risk_weight):
            # a closed or already drawn risk carries nothing, an occurred one
            # waiting for its drawdown carries its full impact, every other one
            # its probability.
            try:
                weight = risk_weight(item.status, item.probability, drawn=str(item.id) in drawn_ids)
                exposure = float(item.impact_cost) * float(weight)
                # A legacy / raw-written non-finite or absurd impact_cost makes
                # float() overflow to inf (no exception); inf would poison the
                # whole rollup (round(inf) -> inf -> RiskSummary 500). Skip just
                # this contribution. New rows are guarded by the schema validator.
                if math.isfinite(exposure) and weight > 0:
                    cur = item.currency or ""
                    exposure_by_currency[cur] = exposure_by_currency.get(cur, 0.0) + exposure
            except (ValueError, TypeError):
                pass

            # Risk score: ALWAYS recompute on the single canonical 0-5 scale
            # (probability x severity_numeric) instead of trusting the stored
            # risk_score, which is heterogeneous - seed rows carry a
            # cost-scaled value while API-created rows store 0-5
            # (F-PFO-RISK-06). Recomputing makes the average and ranking
            # scale-correct and comparable across seed + runtime data.
            try:
                score = _compute_risk_score(float(item.probability), item.impact_severity or "medium")
                risk_scores.append(score)
                scored_items.append((item.title, score))
            except (ValueError, TypeError):
                pass

        avg_risk_score = 0.0
        if risk_scores:
            avg_risk_score = round(sum(risk_scores) / len(risk_scores), 1)

        # Top risks sorted by score descending
        scored_items.sort(key=lambda x: x[1], reverse=True)
        top_risks = [{"title": t, "score": s} for t, s in scored_items[:5]]

        # Project currency is data-driven (resolved from the project), not
        # last-wins from item rows. total_exposure is only emitted when all
        # exposure shares a single currency; otherwise it stays 0.0 and
        # callers must read exposure_by_currency.
        project_currency = await self._get_project_currency(project_id)
        non_empty = {c: v for c, v in exposure_by_currency.items() if c}
        if len(non_empty) == 1:
            total_exposure = round(next(iter(non_empty.values())), 2)
        elif not non_empty and exposure_by_currency:
            # All exposure is currency-less - a single (unknown) bucket.
            total_exposure = round(sum(exposure_by_currency.values()), 2)
        else:
            total_exposure = 0.0

        return {
            "total": len(items),
            "total_risks": len(items),
            "by_status": by_status,
            "by_tier": by_tier,
            "by_category": by_category,
            "high_critical_count": high_critical_count,
            "avg_risk_score": avg_risk_score,
            "total_exposure": total_exposure,
            "exposure_by_currency": {c: round(v, 2) for c, v in exposure_by_currency.items()},
            "with_mitigation": with_mitigation,
            "without_mitigation": without_mitigation,
            "mitigated_count": mitigated_count,
            "top_risks": top_risks,
            "currency": project_currency,
        }

    # ── Risk Matrix ───────────────────────────────────────────────────────

    async def get_matrix(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Build 5x5 risk matrix data from project risks.

        Probability levels: 0.1 (very low), 0.3 (low), 0.5 (medium), 0.7 (high), 0.9 (very high)
        Impact levels: very_low, low, medium, high, critical (canonical PMBOK 5-level scheme).
        Legacy values (negligible / minor / moderate / major / catastrophic) are normalised
        to the canonical set below so existing data still falls into a cell.
        """
        items = await self.repo.all_for_project(project_id)

        prob_levels = ["0.1", "0.3", "0.5", "0.7", "0.9"]
        impact_levels = ["very_low", "low", "medium", "high", "critical"]
        legacy_impact_alias = {
            "negligible": "very_low",
            "minor": "low",
            "moderate": "medium",
            "major": "high",
            "catastrophic": "critical",
        }

        # Initialize cells
        cells: list[dict[str, Any]] = []
        for prob in prob_levels:
            for impact in impact_levels:
                cells.append(
                    {
                        "probability_level": prob,
                        "impact_level": impact,
                        "count": 0,
                        "risk_ids": [],
                    }
                )

        # Map each risk to the nearest probability bucket
        def _nearest_prob(val: float) -> str:
            buckets = [0.1, 0.3, 0.5, 0.7, 0.9]
            nearest = min(buckets, key=lambda b: abs(b - val))
            return str(nearest)

        for item in items:
            if item.status == "closed":
                continue
            try:
                prob_bucket = _nearest_prob(float(item.probability))
            except (ValueError, TypeError):
                prob_bucket = "0.5"
            raw_sev = item.impact_severity or "medium"
            # Normalise legacy labels onto the canonical 5-level set.
            raw_sev = legacy_impact_alias.get(raw_sev, raw_sev)
            severity = raw_sev if raw_sev in impact_levels else "medium"

            for cell in cells:
                if cell["probability_level"] == prob_bucket and cell["impact_level"] == severity:
                    cell["count"] += 1
                    cell["risk_ids"].append(item.id)
                    break

        return cells

    # ── Monte Carlo simulation (v3.11 - T1) ──────────────────────────────

    async def simulate(
        self,
        project_id: uuid.UUID,
        *,
        iterations: int = 10000,
        mode: Literal["cost", "schedule", "both"] = "both",
    ) -> dict[str, Any]:
        """Run a Monte Carlo simulation across this project's risks.

        Uses ``random.triangular(low, high, mode)`` per risk per iteration
        - a PERT-style three-point estimate sampling - and multiplies each
        draw by ``probability_score / 5`` (the qualitative probability
        scale) to get the probability-weighted contribution. The
        per-iteration sums form the simulated distribution of project-
        level contingency, and P50/P80/P95 are read off via
        ``statistics.quantiles`` (inclusive method).

        ``mode``:
          * ``"cost"``      - only sample the cost triple.
          * ``"schedule"``  - only sample the schedule triple.
          * ``"both"``      - sample both (independent draws).

        Risks with no PERT triple in the requested mode contribute zero
        - the qualitative 5x5 path keeps working untouched. Each risk
        gets its ``last_simulation`` JSON updated with the full result
        snapshot so the drill-down survives a page refresh.

        Returns a dict matching :class:`RiskSimulationResult`.
        """
        # Bound iterations defensively even though the schema already
        # enforces 1000 ≤ iterations ≤ 100 000.
        iterations = max(1, min(int(iterations), 100_000))

        # ── One query, no N+1: load every risk for the project once. ──
        items = await self.repo.all_for_project(project_id)
        currency = await self._get_project_currency(project_id)

        # Empty project - return an empty (but well-formed) result. The
        # frontend's "Last run" chips render as "-" and the histogram
        # / tornado simply hide.
        if not items:
            return {
                "iterations": iterations,
                "risk_count": 0,
                "mode": mode,
                "p50_cost": None,
                "p80_cost": None,
                "p95_cost": None,
                "p50_schedule_days": None,
                "p80_schedule_days": None,
                "p95_schedule_days": None,
                "histogram_bins": [],
                "tornado": [],
                "currency": currency,
                "mixed_currency": False,
            }

        # Build per-risk PERT triples. Where a triple is incomplete we
        # fall back to (impact_cost, impact_cost, impact_cost) - i.e. a
        # zero-variance point estimate that still folds the risk into
        # the simulation when only the qualitative path is populated.
        cost_triples: list[tuple[float, float, float]] = []
        schedule_triples: list[tuple[float, float, float]] = []
        cost_weights: list[float] = []
        schedule_weights: list[float] = []
        item_meta: list[tuple[uuid.UUID, str]] = []
        drawn_ids = await self._drawn_risk_ids(project_id) if mode in ("cost", "both") else set()

        for item in items:
            # Probability weight on a 0..1 scale. Prefer the 1-5 PMBOK
            # score (probability_score) - it's already discretised - and
            # fall back to the raw ``probability`` string if missing.
            if item.probability_score is not None:
                probability = max(0.0, min(float(item.probability_score) / 5.0, 1.0))
            else:
                try:
                    probability = max(0.0, min(float(item.probability), 1.0))
                except (ValueError, TypeError):
                    probability = 0.0
            # The status rule the contingency card uses (contingency.risk_weight):
            # a closed risk is out, an occurred one is certain. Cost and schedule
            # differ in one place only: a confirmed drawdown takes the cost out
            # (it is drawn money now), but the delay has still happened.
            cost_weights.append(float(risk_weight(item.status, probability, drawn=str(item.id) in drawn_ids)))
            schedule_weights.append(float(risk_weight(item.status, probability)))
            item_meta.append((item.id, item.code))

            cost_triples.append(
                _pert_triple_or_point(
                    item.cost_p10,
                    item.cost_p50,
                    item.cost_p90,
                    fallback=_safe_float(item.impact_cost),
                )
            )
            schedule_triples.append(
                _pert_triple_or_point(
                    item.schedule_p10,
                    item.schedule_p50,
                    item.schedule_p90,
                    fallback=float(item.impact_schedule_days or 0),
                )
            )

        # Currency honesty (F-PFO-RISK-04): the per-iteration cost sum blends
        # every risk's cost draw into one number, which is only meaningful when
        # the cost-bearing risks share a single currency. Collect the distinct
        # non-blank currencies among risks that actually contribute cost (a
        # blank currency inherits the project currency, so it is not a distinct
        # one). If more than one, the blended cost total cannot be honestly
        # labelled, so we suppress the cost read-outs below rather than mislabel
        # them - the same rule get_summary applies to total_exposure.
        cost_currencies: set[str] = set()
        for idx in range(len(items)):
            if cost_weights[idx] > 0.0 and max(cost_triples[idx]) > 0.0:
                cur = (items[idx].currency or "").strip()
                if cur:
                    cost_currencies.add(cur)
        mixed_currency = len(cost_currencies) > 1

        sample_cost = mode in ("cost", "both")
        sample_schedule = mode in ("schedule", "both")
        # When cost currencies are mixed, the cost distribution is not a single-
        # currency quantity; only schedule (currency-agnostic days) stays valid.
        cost_currency_ok = not mixed_currency

        # Per-iteration sums for the contingency distribution.
        cost_totals: list[float] = []
        schedule_totals: list[float] = []
        # Per-risk running sum so we can compute the mean contribution
        # afterwards for the tornado chart. Combined (cost + schedule
        # cast to "days as currency-equivalent" is meaningless), so we
        # tornado on whichever signal was sampled, preferring cost.
        per_risk_cost_sum = [0.0] * len(items)
        per_risk_schedule_sum = [0.0] * len(items)

        for _ in range(iterations):
            c_total = 0.0
            s_total = 0.0
            for idx in range(len(items)):
                c_weight = cost_weights[idx]
                s_weight = schedule_weights[idx]
                if sample_cost and c_weight > 0.0:
                    lo, mid, hi = cost_triples[idx]
                    # random.triangular(low, high, mode) - note the
                    # argument order is (low, high, mode), NOT
                    # (low, mode, high). Easy off-by-one to make.
                    draw = random.triangular(lo, hi, mid) if hi > lo else mid
                    contrib = draw * c_weight
                    c_total += contrib
                    per_risk_cost_sum[idx] += contrib
                if sample_schedule and s_weight > 0.0:
                    lo, mid, hi = schedule_triples[idx]
                    draw = random.triangular(lo, hi, mid) if hi > lo else mid
                    contrib = draw * s_weight
                    s_total += contrib
                    per_risk_schedule_sum[idx] += contrib
            if sample_cost:
                cost_totals.append(c_total)
            if sample_schedule:
                schedule_totals.append(s_total)

        # ── Percentile read-out ─────────────────────────────────────
        # Suppress the cost percentiles when currencies are mixed (a blended
        # total would be mislabelled under one currency).
        if sample_cost and cost_currency_ok:
            p50_cost, p80_cost, p95_cost = _percentiles(cost_totals)
        else:
            p50_cost, p80_cost, p95_cost = None, None, None
        if sample_schedule:
            ps50, ps80, ps95 = _percentiles(schedule_totals)
            p50_sched = int(round(ps50)) if ps50 is not None else None
            p80_sched = int(round(ps80)) if ps80 is not None else None
            p95_sched = int(round(ps95)) if ps95 is not None else None
        else:
            p50_sched = p80_sched = p95_sched = None

        # ── Histogram: 10 equal-width bins over the cost distribution
        # (or schedule if cost wasn't sampled). The frontend draws this
        # as a bar chart.
        # Prefer the cost distribution, but never chart a currency-blended cost
        # total - fall back to schedule (or nothing) when currencies are mixed.
        if sample_cost and cost_currency_ok:
            histogram_source = cost_totals
        elif sample_schedule:
            histogram_source = schedule_totals
        else:
            histogram_source = []
        histogram_bins = _histogram(histogram_source, bins=10)

        # ── Tornado: top contributors by mean probability-weighted
        # contribution. Sort descending so the frontend can slice [:N]
        # without re-sorting.
        if sample_cost and cost_currency_ok:
            contribs = per_risk_cost_sum
        elif sample_schedule:
            contribs = per_risk_schedule_sum
        else:
            contribs = [0.0] * len(items)
        tornado_entries: list[dict[str, Any]] = []
        if iterations > 0:
            for idx, (risk_id, code) in enumerate(item_meta):
                mean_contrib = contribs[idx] / iterations
                if mean_contrib <= 0.0:
                    continue
                tornado_entries.append(
                    {
                        "risk_id": str(risk_id),
                        "code": code,
                        "contribution": round(mean_contrib, 2),
                    }
                )
            tornado_entries.sort(key=lambda e: float(e["contribution"]), reverse=True)

        # JSON-serialisable result. Pydantic widens floats to Decimal on
        # the response schema, but the persisted ``last_simulation`` JSON
        # blob has to round-trip through json.dumps (SQLAlchemy's default
        # serializer rejects Decimal), so we keep floats here and let
        # Pydantic do the float→Decimal lift at response time.
        result: dict[str, Any] = {
            "iterations": iterations,
            "risk_count": len(items),
            "mode": mode,
            "p50_cost": _round_or_none(p50_cost),
            "p80_cost": _round_or_none(p80_cost),
            "p95_cost": _round_or_none(p95_cost),
            "p50_schedule_days": p50_sched,
            "p80_schedule_days": p80_sched,
            "p95_schedule_days": p95_sched,
            "histogram_bins": histogram_bins,
            "tornado": tornado_entries,
            "currency": currency,
            "mixed_currency": mixed_currency,
        }

        # Persist the snapshot on every risk so a page refresh keeps the
        # last-run drill-down. We read IDs into a Python list BEFORE the first
        # update so the loop iterates over a fixed set rather than over rows it
        # is writing to, where a reload raises MissingGreenlet.
        item_ids_to_stamp = [item.id for item in items]
        for risk_id in item_ids_to_stamp:
            await self.repo.update_fields(risk_id, last_simulation=result)

        logger.info(
            "Risk MC simulation: project=%s iterations=%d mode=%s risks=%d",
            project_id,
            iterations,
            mode,
            len(items),
        )
        await _safe_publish(
            "risk.simulation.completed",
            {
                "project_id": str(project_id),
                "iterations": iterations,
                "mode": mode,
                "risk_count": len(items),
            },
        )
        return result

    # ── Risk-based contingency (EMV vs the finance contingency line) ─────

    async def _contingency_inputs(
        self,
        project_id: uuid.UUID,
    ) -> tuple[list[RiskMoney], list[ContingencyLine], str, dict[str, Any]]:
        """Load the register and the finance contingency lines for one project.

        Returns the risks, the lines (with their parsed drawdowns), the project
        currency and its FX table.
        """
        from app.modules.finance.service import FinanceService
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        project_currency = norm_code(getattr(project, "currency", "") or "")
        fx = fx_map_from_rates(getattr(project, "fx_rates", None))

        risks = [
            RiskMoney(
                risk_id=str(item.id),
                code=item.code,
                title=item.title,
                status=item.status,
                probability=clamp_probability(item.probability),
                impact=to_decimal(item.impact_cost),
                currency=norm_code(item.currency),
            )
            for item in await self.repo.all_for_project(project_id)
        ]

        lines: list[ContingencyLine] = []
        for budget in await FinanceService(self.session).list_contingency_lines(project_id):
            line_currency = norm_code(budget.currency_code)
            lines.append(
                ContingencyLine(
                    budget_id=str(budget.id),
                    wbs_id=budget.wbs_id,
                    currency=line_currency,
                    allocated=allocated_amount(budget.revised_budget, budget.original_budget),
                    drawdowns=_line_drawdowns(budget, line_currency or project_currency),
                )
            )
        return risks, lines, project_currency, fx

    async def _drawn_risk_ids(self, project_id: uuid.UUID) -> set[str]:
        """Ids of the risks holding a confirmed drawdown on this project's contingency.

        One read of the contingency lines, for the register summary and the
        Monte Carlo draw, which apply the card's rule (a drawn risk carries no
        cost exposure) without building the whole position.
        """
        from app.modules.finance.service import FinanceService

        return {
            record.risk_id
            for budget in await FinanceService(self.session).list_contingency_lines(project_id)
            for record in _line_drawdowns(budget, norm_code(budget.currency_code))
            if record.risk_id
        }

    async def get_contingency_position(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Risk-based contingency (EMV, P50/P80) against the finance contingency lines."""
        risks, lines, project_currency, fx = await self._contingency_inputs(project_id)
        return build_position(risks, lines, project_currency=project_currency, fx=fx)

    async def confirm_contingency_drawdown(
        self,
        project_id: uuid.UUID,
        risk_id: uuid.UUID,
        data: ContingencyDrawdownRequest,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """A person confirms the money an occurred risk draws from contingency.

        Nothing is drawn automatically when a risk's status turns to
        ``occurred``; the risk only shows up as pending on the contingency
        card until someone confirms an amount here. One drawdown per risk:
        confirming again replaces it (or moves it to another line), and
        replaying the same confirmation leaves the stored record, including
        who confirmed it and when, exactly as it was.

        Raises:
            HTTPException: 404 when the risk is not in this project or the
                line is not one of its contingency lines; 409 when the risk has
                not occurred or the project has no contingency line; 422 when
                several lines could take it and none was chosen.
        """
        from app.modules.finance.service import FinanceService

        risk = await self.get_risk(risk_id)
        if risk.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk item not found")
        if (risk.status or "").strip().lower() != MATERIALISED_STATUS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a risk that has occurred can draw on contingency. Set its status to Occurred first.",
            )
        risk_code = risk.code
        risk_title = risk.title

        risks, lines, project_currency, fx = await self._contingency_inputs(project_id)
        if not lines:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This project has no contingency line in its finance budget. "
                    "Add a budget line with the category Contingency first."
                ),
            )
        base = resolve_base_currency(project_currency, [r.currency for r in risks] + [ln.currency for ln in lines])
        if data.budget_id is not None:
            target = next((ln for ln in lines if ln.budget_id == str(data.budget_id)), None)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Contingency budget line not found for this project",
                )
        else:
            target = default_line(lines, base)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="This project has several contingency lines. Choose the one to draw from.",
                )

        line_currency = norm_code(target.currency) or base
        amount = quantize_money(data.amount, line_currency)
        source = f"risk:{risk_id}"
        existing = next((d for d in target.drawdowns if d.source == source), None)
        if existing is not None and existing.amount == amount and existing.note == data.note:
            # Same confirmation replayed: keep the original record untouched.
            return build_position(risks, lines, project_currency=project_currency, fx=fx)

        record = {
            "amount": format(amount, "f"),
            "currency": line_currency,
            "risk_id": str(risk_id),
            "risk_code": risk_code,
            "risk_title": risk_title,
            "confirmed_by": user_id or "",
            "confirmed_at": datetime.now(UTC).isoformat(),
            "note": data.note,
        }
        await FinanceService(self.session).set_contingency_drawdown(
            project_id=project_id,
            source=source,
            budget_id=uuid.UUID(target.budget_id),
            record=record,
        )
        logger.info(
            "Contingency drawdown confirmed: risk=%s line=%s amount=%s %s",
            risk_code,
            target.budget_id,
            amount,
            line_currency,
        )
        await _safe_publish(
            "risk.contingency.drawdown_confirmed",
            {
                "project_id": str(project_id),
                "risk_id": str(risk_id),
                "budget_id": target.budget_id,
                "amount": format(amount, "f"),
                "currency": line_currency,
                "confirmed_by": user_id or "",
            },
        )
        return await self.get_contingency_position(project_id)

    async def reverse_contingency_drawdown(
        self,
        project_id: uuid.UUID,
        risk_id: uuid.UUID,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Take back a confirmed drawdown (a mistaken confirmation).

        Works for a risk that has since been deleted too: the drawdown is found
        by its source key on the project's contingency lines, not through the
        risk row.

        Raises:
            HTTPException: 404 when no drawdown is recorded for the risk.
        """
        from app.modules.finance.service import FinanceService

        _risks, lines, _currency, _fx = await self._contingency_inputs(project_id)
        source = f"risk:{risk_id}"
        holder = next((ln for ln in lines if any(d.source == source for d in ln.drawdowns)), None)
        if holder is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No contingency drawdown is recorded for this risk",
            )
        await FinanceService(self.session).set_contingency_drawdown(
            project_id=project_id,
            source=source,
            budget_id=None,
            record=None,
        )
        logger.info("Contingency drawdown reversed: risk=%s line=%s", risk_id, holder.budget_id)
        await _safe_publish(
            "risk.contingency.drawdown_reversed",
            {
                "project_id": str(project_id),
                "risk_id": str(risk_id),
                "budget_id": holder.budget_id,
                "reversed_by": user_id or "",
            },
        )
        return await self.get_contingency_position(project_id)


def _line_drawdowns(budget: Any, line_currency: str) -> tuple[DrawdownRecord, ...]:
    """The confirmed drawdowns stored on one contingency budget line's metadata."""
    from app.modules.finance.service import CONTINGENCY_DRAWDOWN_PREFIX

    records: list[DrawdownRecord] = []
    for key, raw in (getattr(budget, "metadata_", None) or {}).items():
        if not str(key).startswith(CONTINGENCY_DRAWDOWN_PREFIX):
            continue
        record = parse_drawdown_record(
            str(key)[len(CONTINGENCY_DRAWDOWN_PREFIX) :],
            raw,
            line_currency=line_currency,
        )
        if record is not None:
            records.append(record)
    return tuple(records)


# ── Monte Carlo helpers (module-level, pure) ──────────────────────────────


def _safe_float(value: object, default: float = 0.0) -> float:
    """Coerce a stored string/Decimal/None numeric to a finite float safely."""
    if value is None or value == "":
        return default
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    # A legacy / raw-written absurd value (e.g. "1e400") yields inf here with no
    # exception; inf would poison the simulation percentiles -> Pydantic 500.
    # Treat non-finite as the default. New rows are guarded by the schema.
    if not math.isfinite(result):
        return default
    return result


def _pert_triple_or_point(
    p10: object,
    p50: object,
    p90: object,
    *,
    fallback: float,
) -> tuple[float, float, float]:
    """Return a (low, mode, high) PERT triple, with safe fallbacks.

    * If all three are present and well-ordered, return them as floats.
    * If any are missing/unparseable, treat ``fallback`` as a zero-
      variance point estimate (lo == mid == hi == fallback) - folds the
      risk into the simulation without inventing data.
    * If the triple is mis-ordered (e.g. p10 > p90) we clamp it so
      ``random.triangular`` never raises.
    """
    lo = _safe_float(p10, fallback)
    mid = _safe_float(p50, fallback)
    hi = _safe_float(p90, fallback)
    # Clamp ordering: lo ≤ mid ≤ hi. random.triangular requires lo ≤ hi
    # and the mode in [lo, hi], so a swapped triple would otherwise raise.
    if hi < lo:
        lo, hi = hi, lo
    if mid < lo:
        mid = lo
    if mid > hi:
        mid = hi
    return lo, mid, hi


def _percentiles(
    samples: list[float],
) -> tuple[float | None, float | None, float | None]:
    """Return (P50, P80, P95) - inclusive method, no numpy dependency.

    We sort once and index by rank; this matches
    ``statistics.quantiles(..., n=100, method='inclusive')[k-1]`` for
    integer percentile k, and avoids the overhead of building a 100-bin
    list when we only want three points.
    """
    if not samples:
        return None, None, None
    sorted_samples = sorted(samples)
    n = len(sorted_samples)

    def _q(p: float) -> float:
        if n == 1:
            return sorted_samples[0]
        # Inclusive method: rank h = p * (n - 1).
        h = p * (n - 1)
        lo = int(h)
        hi = min(lo + 1, n - 1)
        frac = h - lo
        return sorted_samples[lo] + (sorted_samples[hi] - sorted_samples[lo]) * frac

    return _q(0.50), _q(0.80), _q(0.95)


def _histogram(samples: list[float], *, bins: int = 10) -> list[dict[str, Any]]:
    """Build a ``bins``-wide equal-width histogram. Empty → []."""
    if not samples:
        return []
    lo = min(samples)
    hi = max(samples)
    if hi <= lo:
        # All samples identical - collapse to a single point bin so the
        # chart still has something to render.
        return [{"lower": round(lo, 2), "upper": round(hi, 2), "count": len(samples)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for s in samples:
        idx = int((s - lo) / width)
        if idx >= bins:
            idx = bins - 1
        counts[idx] += 1
    return [
        {
            "lower": round(lo + i * width, 2),
            "upper": round(lo + (i + 1) * width, 2),
            "count": counts[i],
        }
        for i in range(bins)
    ]


def _round_or_none(value: float | None) -> float | None:
    """Round a float total to 2 dp, preserving None.

    Stays as a float (not Decimal) so the result dict round-trips through
    SQLAlchemy's default JSON serializer when we persist it on each
    risk's ``last_simulation`` column. Pydantic v2 lifts float → Decimal
    automatically on the response schema, so callers see well-typed
    Decimals at the API boundary without needing pre-coercion here.
    """
    if value is None:
        return None
    return round(value, 2)
