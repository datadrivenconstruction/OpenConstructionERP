"""Risk Register service — business logic for risk management.

Stateless service layer. Handles:
- Risk CRUD with auto-generated codes (R-001, R-002, ...)
- Risk score computation: probability x severity_numeric
- Summary aggregation and risk matrix data
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.risk.models import RiskItem
from app.modules.risk.repository import RiskRepository
from app.modules.risk.schemas import RiskCreate, RiskUpdate

logger = logging.getLogger(__name__)
_logger_events = logging.getLogger(__name__ + ".events")


async def _safe_publish(
    name: str,
    data: dict[str, Any],
    source_module: str = "oe_risk",
) -> None:
    """Publish event safely — best-effort, never blocks the caller."""
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_events.debug("Event publish skipped: %s", name)

SEVERITY_NUMERIC: dict[str, int] = {
    "very_low": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
    # Aliases for legacy / PMBOK-style enum values:
    "negligible": 1,
    "minor": 2,
    "moderate": 3,
    "major": 4,
    "catastrophic": 5,
}

# 5x5 matrix scoring: maps probability to a 1-5 score
PROBABILITY_SCORE_MAP: list[tuple[float, int]] = [
    (0.2, 1),   # very low
    (0.4, 2),   # low
    (0.6, 3),   # medium
    (0.8, 4),   # high
    (1.0, 5),   # very high
]

# Impact severity to 1-5 score for the canonical 5x5 PMBOK risk matrix.
# The canonical level set is: very_low / low / medium / high / critical.
# Legacy enum values (negligible / minor / moderate / major / catastrophic)
# are accepted as aliases so existing seed / demo data keeps working.
# TODO (v1.4): proper enum migration — right now `impact_severity` is a
# free-text String(20) in the DB, so no CHECK constraint / Alembic step is
# needed yet, but the schemas should be tightened alongside a data backfill.
IMPACT_SCORE_MAP: dict[str, int] = {
    "very_low": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
    # Aliases — same numeric scale as above:
    "negligible": 1,
    "minor": 2,
    "moderate": 3,
    "major": 4,
    "catastrophic": 5,
}


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

    # ── Create ────────────────────────────────────────────────────────────

    async def create_risk(self, data: RiskCreate) -> RiskItem:
        """Create a new risk item with auto-generated code."""
        count = await self.repo.count_for_project(data.project_id)
        code = f"R-{count + 1:03d}"

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
            risk_score=str(risk_score),
            probability_score=prob_score,
            impact_score_cost=impact_score,
            impact_score_time=impact_score,
            risk_tier=risk_tier,
            mitigation_strategy=data.mitigation_strategy,
            contingency_plan=data.contingency_plan,
            owner_name=data.owner_name,
            response_cost=str(data.response_cost),
            currency=data.currency,
            metadata_=data.metadata,
        )
        item = await self.repo.create(item)
        logger.info("Risk created: %s for project %s", code, data.project_id)
        await _safe_publish(
            "risk.risk.created",
            {
                "risk_id": str(item.id),
                "project_id": str(data.project_id),
                "code": code,
                "title": data.title,
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
    ) -> tuple[list[RiskItem], int]:
        """List risk items for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            category=category_filter,
            severity=severity_filter,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_risk(
        self,
        risk_id: uuid.UUID,
        data: RiskUpdate,
    ) -> RiskItem:
        """Update risk item fields. Recalculates risk_score if needed."""
        item = await self.get_risk(risk_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return item

        # Recalculate risk_score and 5x5 matrix scoring if probability or severity changed
        probability = fields.get("probability", float(item.probability))
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

        await self.repo.update_fields(risk_id, **fields)
        await self.session.refresh(item)

        logger.info("Risk updated: %s (fields=%s)", risk_id, list(fields.keys()))
        await _safe_publish(
            "risk.risk.updated",
            {
                "risk_id": str(risk_id),
                "project_id": str(item.project_id),
                "changes": list(fields.keys()),
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
        total_exposure = 0.0
        risk_scores: list[float] = []
        scored_items: list[tuple[str, float]] = []
        currency = "EUR"

        for item in items:
            by_status[item.status] = by_status.get(item.status, 0) + 1
            by_category[item.category] = by_category.get(item.category, 0) + 1

            # Tier breakdown by risk_tier (computed from 5x5 matrix)
            tier = item.risk_tier or item.impact_severity or "medium"
            by_tier[tier] = by_tier.get(tier, 0) + 1

            if item.impact_severity in ("high", "critical"):
                high_critical_count += 1

            if item.status in ("mitigating", "closed"):
                mitigated_count += 1

            # Mitigation tracking
            if item.mitigation_strategy and item.mitigation_strategy.strip():
                with_mitigation += 1
            else:
                without_mitigation += 1

            # Exposure = impact_cost * probability
            try:
                total_exposure += float(item.impact_cost) * float(item.probability)
            except (ValueError, TypeError):
                pass

            # Risk score tracking
            try:
                score = float(item.risk_score)
                risk_scores.append(score)
                scored_items.append((item.title, score))
            except (ValueError, TypeError):
                pass

            if item.currency:
                currency = item.currency

        avg_risk_score = 0.0
        if risk_scores:
            avg_risk_score = round(sum(risk_scores) / len(risk_scores), 1)

        # Top risks sorted by score descending
        scored_items.sort(key=lambda x: x[1], reverse=True)
        top_risks = [{"title": t, "score": s} for t, s in scored_items[:5]]

        return {
            "total": len(items),
            "total_risks": len(items),
            "by_status": by_status,
            "by_tier": by_tier,
            "by_category": by_category,
            "high_critical_count": high_critical_count,
            "avg_risk_score": avg_risk_score,
            "total_exposure": round(total_exposure, 2),
            "with_mitigation": with_mitigation,
            "without_mitigation": without_mitigation,
            "mitigated_count": mitigated_count,
            "top_risks": top_risks,
            "currency": currency,
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
