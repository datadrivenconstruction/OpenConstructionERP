# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Match-quality analytics for the §10 production observability layer.

The :func:`compute_match_analytics` function aggregates rows from
``oe_match_elements_search_log`` (populated by ranker_qdrant for every
ranker call, plus the /confirm hook for user-feedback columns) into a
single JSON-serialisable response.

Three classes of output:

* **Totals + distributions** — search volume, pick rate, score / latency
  / tier histograms. Powers the dashboard tiles.
* **Per-dimension breakdowns** — the same metrics segmented by
  ``country``, ``source_type``, ``ifc_class`` so operators can spot
  "DE searches are great, RU is broken" without writing SQL.
* **Alerts** — the §10 thresholds (low top_score, high picked_rank,
  zero-hit rate). Each alert carries the offending metric, the threshold
  it crossed, and a spec reference for traceability.

Portability note: percentile_cont() is PostgreSQL-only. To keep the
endpoint working under SQLite (dev) and Postgres (prod), the SQL stays
plain GROUP BY / COUNT / AVG and percentiles are computed in Python
from the per-row arrays.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements.models import MatchSearchLog
from app.modules.match_elements.schemas import (
    AnalyticsAlert,
    AnalyticsBreakdown,
    AnalyticsResponse,
)

# ── §10 alert thresholds ─────────────────────────────────────────────────
#
# Env-overridable so a deploy can tighten / loosen without a rebuild.
# Defaults match MAPPING_PROCESS.md §10:
#   * top_score < 0.3 across >20% of searches  → catalogue gap
#   * picked_rank > 4 across >20% of picks     → re-train classifier
#   * had_hard_filter && hits=0 across >10%    → over-restrictive filters

_LOW_SCORE_VALUE = float(os.getenv("MATCH_ALERT_LOW_SCORE_VALUE", "0.3"))
_LOW_SCORE_PCT = float(os.getenv("MATCH_ALERT_LOW_SCORE_PCT", "0.20"))
_HIGH_RANK_VALUE = float(os.getenv("MATCH_ALERT_HIGH_RANK_VALUE", "4.0"))
_HIGH_RANK_PCT = float(os.getenv("MATCH_ALERT_HIGH_RANK_PCT", "0.20"))
_ZERO_HIT_PCT = float(os.getenv("MATCH_ALERT_ZERO_HIT_PCT", "0.10"))

_MIN_SAMPLE = int(os.getenv("MATCH_ALERT_MIN_SAMPLE", "20"))
"""‌⁠‍Don't fire any alert until the window has at least this many rows.

Without this guard a fresh deploy with two test queries — one of which
happened to score 0.1 — would page the on-call team. The §10 thresholds
are statistical and need a real denominator."""

_BREAKDOWN_LIMIT = 8
"""‌⁠‍How many rows to surface per by-dimension table (top-N by volume)."""

_MAX_DAYS = 90
"""Hard cap on the lookback window. Even at 100k rows / week the in-Python
percentile is fine; 90 days is the analytical horizon we tested for."""


def _percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile compatible with numpy default.

    Returns ``None`` for an empty list so the response can carry a
    nullable percentile without sentinel magic numbers.
    """
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def _mean(values: list[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


async def compute_match_analytics(
    db: AsyncSession,
    *,
    days: int = 7,
    project_id: uuid.UUID | None = None,
    catalog_id: str | None = None,
) -> AnalyticsResponse:
    """Aggregate the last ``days`` of search-log rows into the §10 dashboard.

    Parameters
    ----------
    days
        Lookback window size. Clamped to ``[1, 90]``.
    project_id
        If provided, restrict to one project's rows. The router authorises
        access before calling.
    catalog_id
        Optional second filter (e.g., ``cwicr_DE``) for catalogue-specific
        diagnostics.
    """
    days = max(1, min(_MAX_DAYS, days))
    now = datetime.now(tz=UTC)
    window_start = now - timedelta(days=days)

    where = [MatchSearchLog.created_at >= window_start]
    if project_id is not None:
        where.append(MatchSearchLog.project_id == project_id)
    if catalog_id:
        where.append(MatchSearchLog.catalog_id == catalog_id)
    base_filter = and_(*where)

    # Single pass: fetch the per-row columns we need for in-Python
    # percentiles + distributions. Limiting columns keeps the transfer
    # bounded even at 100k rows.
    rows = (
        await db.execute(
            select(
                MatchSearchLog.top_score,
                MatchSearchLog.took_ms,
                MatchSearchLog.hits_count,
                MatchSearchLog.relax_tier_used,
                MatchSearchLog.top_confidence_band,
                MatchSearchLog.bge_rerank_used,
                MatchSearchLog.llm_rerank_used,
                MatchSearchLog.picked_rank,
                MatchSearchLog.picked_at,
                MatchSearchLog.hard_filters,
                MatchSearchLog.country,
                MatchSearchLog.source_type,
                MatchSearchLog.ifc_class,
            ).where(base_filter),
        )
    ).all()

    total = len(rows)
    if total == 0:
        return AnalyticsResponse(
            window_days=days,
            project_id=project_id,
            catalog_id=catalog_id,
            generated_at=now,
            total_searches=0,
            total_with_pick=0,
        )

    scores: list[float] = []
    latencies: list[float] = []
    picked_ranks: list[float] = []
    tier_counts: dict[str, int] = {}
    band_counts: dict[str, int] = {}
    bge_used = 0
    llm_used = 0
    low_score = 0
    zero_hit = 0
    zero_hit_with_filter = 0
    with_filter = 0
    high_picked_rank = 0
    with_pick = 0

    by_country_acc: dict[str, dict[str, float]] = {}
    by_source_acc: dict[str, dict[str, float]] = {}
    by_ifc_acc: dict[str, dict[str, float]] = {}

    def _bump(acc: dict[str, dict[str, float]], key: str | None, score: float | None, picked: bool) -> None:
        bucket = acc.setdefault(key or "unknown", {"searches": 0.0, "score_sum": 0.0, "score_n": 0.0, "picks": 0.0})
        bucket["searches"] += 1
        if score is not None:
            bucket["score_sum"] += float(score)
            bucket["score_n"] += 1
        if picked:
            bucket["picks"] += 1

    for r in rows:
        score = r.top_score
        if score is not None:
            scores.append(float(score))
            if score < _LOW_SCORE_VALUE:
                low_score += 1
        if r.took_ms is not None:
            latencies.append(float(r.took_ms))
        if r.hits_count == 0:
            zero_hit += 1
        # "had_hard_filter" — non-empty hard_filters dict
        had_filter = bool(r.hard_filters)
        if had_filter:
            with_filter += 1
            if r.hits_count == 0:
                zero_hit_with_filter += 1
        tier_key = str(r.relax_tier_used if r.relax_tier_used is not None else 0)
        tier_counts[tier_key] = tier_counts.get(tier_key, 0) + 1
        band = r.top_confidence_band or "unknown"
        band_counts[band] = band_counts.get(band, 0) + 1
        if r.bge_rerank_used:
            bge_used += 1
        if r.llm_rerank_used:
            llm_used += 1
        picked = r.picked_at is not None
        if picked:
            with_pick += 1
            if r.picked_rank is not None:
                picked_ranks.append(float(r.picked_rank))
                if r.picked_rank > _HIGH_RANK_VALUE:
                    high_picked_rank += 1
        _bump(by_country_acc, r.country, score, picked)
        _bump(by_source_acc, r.source_type, score, picked)
        _bump(by_ifc_acc, r.ifc_class, score, picked)

    def _to_breakdowns(acc: dict[str, dict[str, float]]) -> list[AnalyticsBreakdown]:
        items = sorted(acc.items(), key=lambda kv: kv[1]["searches"], reverse=True)[:_BREAKDOWN_LIMIT]
        return [
            AnalyticsBreakdown(
                key=k,
                searches=int(v["searches"]),
                mean_score=(v["score_sum"] / v["score_n"]) if v["score_n"] else None,
                pick_rate=(v["picks"] / v["searches"]) if v["searches"] else None,
            )
            for k, v in items
        ]

    pick_rate = with_pick / total if total else 0.0
    low_score_pct = low_score / total if total else 0.0
    zero_hit_pct = zero_hit / total if total else 0.0
    zero_hit_with_filter_pct = (zero_hit_with_filter / with_filter) if with_filter else 0.0
    bge_pct = bge_used / total if total else 0.0
    llm_pct = llm_used / total if total else 0.0
    high_rank_pct = (high_picked_rank / with_pick) if with_pick else 0.0

    alerts: list[AnalyticsAlert] = []
    if total >= _MIN_SAMPLE:
        if low_score_pct >= _LOW_SCORE_PCT:
            alerts.append(
                AnalyticsAlert(
                    id="low_top_score",
                    severity="warning",
                    title="Low-confidence searches above threshold",
                    detail=(
                        f"{low_score_pct:.1%} of {total} searches scored below "
                        f"{_LOW_SCORE_VALUE:.2f} — likely catalogue gap or "
                        "missing language coverage."
                    ),
                    metric=low_score_pct,
                    threshold=_LOW_SCORE_PCT,
                    spec_ref="MAPPING_PROCESS.md §10 (catalogue gap)",
                )
            )
        if with_pick >= _MIN_SAMPLE and high_rank_pct >= _HIGH_RANK_PCT:
            alerts.append(
                AnalyticsAlert(
                    id="high_picked_rank",
                    severity="warning",
                    title="Users picking past suggested top-4",
                    detail=(
                        f"{high_rank_pct:.1%} of {with_pick} picks landed beyond rank "
                        f"{_HIGH_RANK_VALUE:.0f} — re-rank model may need re-training."
                    ),
                    metric=high_rank_pct,
                    threshold=_HIGH_RANK_PCT,
                    spec_ref="MAPPING_PROCESS.md §10 (re-train classifier)",
                )
            )
        if with_filter >= _MIN_SAMPLE and zero_hit_with_filter_pct >= _ZERO_HIT_PCT:
            alerts.append(
                AnalyticsAlert(
                    id="over_restrictive_filters",
                    severity="critical" if zero_hit_with_filter_pct >= 0.25 else "warning",
                    title="Hard filters returning zero hits",
                    detail=(
                        f"{zero_hit_with_filter_pct:.1%} of {with_filter} filtered "
                        "searches returned no candidates — relax-tier ladder may need tuning."
                    ),
                    metric=zero_hit_with_filter_pct,
                    threshold=_ZERO_HIT_PCT,
                    spec_ref="MAPPING_PROCESS.md §10 (over-restrictive filters)",
                )
            )

    return AnalyticsResponse(
        window_days=days,
        project_id=project_id,
        catalog_id=catalog_id,
        generated_at=now,
        total_searches=total,
        total_with_pick=with_pick,
        pick_rate=pick_rate,
        mean_top_score=_mean(scores),
        p95_top_score=_percentile(scores, 0.95),
        low_score_pct=low_score_pct,
        zero_hit_pct=zero_hit_pct,
        relax_tier_distribution=tier_counts,
        confidence_band_distribution=band_counts,
        bge_rerank_pct=bge_pct,
        llm_rerank_pct=llm_pct,
        mean_took_ms=_mean(latencies),
        p95_took_ms=_percentile(latencies, 0.95),
        mean_picked_rank=_mean(picked_ranks),
        p95_picked_rank=_percentile(picked_ranks, 0.95),
        high_picked_rank_pct=high_rank_pct,
        by_country=_to_breakdowns(by_country_acc),
        by_source_type=_to_breakdowns(by_source_acc),
        by_ifc_class=_to_breakdowns(by_ifc_acc),
        alerts=alerts,
    )


# Used in tests so they don't reach into private symbols.
__all__ = [
    "compute_match_analytics",
    "_percentile",
]


# Cosmetic re-exports of module-level constants for tests + diagnostics.
def get_alert_thresholds() -> dict[str, float]:
    """Return the env-overridable §10 thresholds for /api/v1/health-style introspection."""
    return {
        "low_score_value": _LOW_SCORE_VALUE,
        "low_score_pct": _LOW_SCORE_PCT,
        "high_rank_value": _HIGH_RANK_VALUE,
        "high_rank_pct": _HIGH_RANK_PCT,
        "zero_hit_pct": _ZERO_HIT_PCT,
        "min_sample": _MIN_SAMPLE,
    }
