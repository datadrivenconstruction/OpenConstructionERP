"""‌⁠‍Risk Register service - business logic for risk management.

Stateless service layer. Handles:
- Risk CRUD with auto-generated codes (R-001, R-002, ...)
- Risk score computation: probability x severity_numeric
- Summary aggregation and risk matrix data
"""

import logging
import random
import uuid
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.risk.models import RiskItem
from app.modules.risk.repository import RiskRepository
from app.modules.risk.schemas import (
    SEVERITY_ALIASES,
    SEVERITY_CANONICAL,
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
    """‌⁠‍Publish event safely - best-effort, never blocks the caller."""
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
    """‌⁠‍Map probability (0.0-1.0) to a 1-5 score for the 5x5 matrix."""
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
            fields["metadata_"] = fields.pop("metadata")

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

            # Exposure = impact_cost * probability, accumulated per currency.
            try:
                exposure = float(item.impact_cost) * float(item.probability)
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
            }

        # Build per-risk PERT triples. Where a triple is incomplete we
        # fall back to (impact_cost, impact_cost, impact_cost) - i.e. a
        # zero-variance point estimate that still folds the risk into
        # the simulation when only the qualitative path is populated.
        cost_triples: list[tuple[float, float, float]] = []
        schedule_triples: list[tuple[float, float, float]] = []
        prob_weights: list[float] = []
        item_meta: list[tuple[uuid.UUID, str]] = []

        for item in items:
            # Probability weight on a 0..1 scale. Prefer the 1-5 PMBOK
            # score (probability_score) - it's already discretised - and
            # fall back to the raw ``probability`` string if missing.
            if item.probability_score is not None:
                weight = max(0.0, min(float(item.probability_score) / 5.0, 1.0))
            else:
                try:
                    weight = max(0.0, min(float(item.probability), 1.0))
                except (ValueError, TypeError):
                    weight = 0.0
            prob_weights.append(weight)
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

        sample_cost = mode in ("cost", "both")
        sample_schedule = mode in ("schedule", "both")

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
                weight = prob_weights[idx]
                if weight <= 0.0:
                    continue
                if sample_cost:
                    lo, mid, hi = cost_triples[idx]
                    # random.triangular(low, high, mode) - note the
                    # argument order is (low, high, mode), NOT
                    # (low, mode, high). Easy off-by-one to make.
                    draw = random.triangular(lo, hi, mid) if hi > lo else mid
                    contrib = draw * weight
                    c_total += contrib
                    per_risk_cost_sum[idx] += contrib
                if sample_schedule:
                    lo, mid, hi = schedule_triples[idx]
                    draw = random.triangular(lo, hi, mid) if hi > lo else mid
                    contrib = draw * weight
                    s_total += contrib
                    per_risk_schedule_sum[idx] += contrib
            if sample_cost:
                cost_totals.append(c_total)
            if sample_schedule:
                schedule_totals.append(s_total)

        # ── Percentile read-out ─────────────────────────────────────
        p50_cost, p80_cost, p95_cost = _percentiles(cost_totals) if sample_cost else (None, None, None)
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
        histogram_source = cost_totals if sample_cost else schedule_totals
        histogram_bins = _histogram(histogram_source, bins=10)

        # ── Tornado: top contributors by mean probability-weighted
        # contribution. Sort descending so the frontend can slice [:N]
        # without re-sorting.
        if sample_cost:
            contribs = per_risk_cost_sum
        else:
            contribs = per_risk_schedule_sum
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
        }

        # Persist the snapshot on every risk so a page refresh keeps the
        # last-run drill-down. We read IDs into a Python list BEFORE the
        # first update - RiskRepository.update_fields calls
        # ``session.expire_all()`` (see repo.py), which would otherwise
        # force a lazy-load of ``item.id`` on the second loop iteration
        # and trip MissingGreenlet on SQLAlchemy's sync cursor path.
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


# ── Monte Carlo helpers (module-level, pure) ──────────────────────────────


def _safe_float(value: object, default: float = 0.0) -> float:
    """‌⁠‍Coerce a stored string/Decimal/None numeric to float safely."""
    if value is None or value == "":
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


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
