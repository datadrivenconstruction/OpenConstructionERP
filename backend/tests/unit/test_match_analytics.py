# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the §10 analytics aggregator.

Two surfaces under test:

* Pure helpers — :func:`_percentile` linear-interpolation contract.
* End-to-end ``compute_match_analytics`` — seed real ``MatchSearchLog``
  rows in a per-test SQLite file, then assert the JSON-serialisable
  response carries the expected counters, distributions, and §10 alerts.

Why a real DB and not a mock: the function does the analytics aggregation
in-Python from a single ``select(...).all()`` pass, so a mocked session
would just be re-implementing the same logic. The real fixture is fast
(<300 ms total) and catches a class of bugs (column types, index decls,
default values) that a mock can't.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.match_elements.analytics import (
    _percentile,
    compute_match_analytics,
    get_alert_thresholds,
)
from app.modules.match_elements.models import MatchSearchLog

# ── Pure helpers ────────────────────────────────────────────────────────


def test_percentile_empty_returns_none() -> None:
    """An empty list has no percentile — return None instead of raising."""
    assert _percentile([], 0.5) is None
    assert _percentile([], 0.95) is None


def test_percentile_single_value_returns_that_value() -> None:
    """One sample → every percentile is that one sample."""
    assert _percentile([0.42], 0.5) == 0.42
    assert _percentile([0.42], 0.95) == 0.42


def test_percentile_linear_interpolation_matches_numpy() -> None:
    """Spot-check against numpy's default linear method."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    # numpy.percentile(values, 50) == 3.0
    assert _percentile(values, 0.5) == 3.0
    # numpy.percentile(values, 95) == 4.8
    assert _percentile(values, 0.95) == pytest.approx(4.8, abs=1e-9)


def test_percentile_p0_is_min_p100_is_max() -> None:
    values = [10.0, 5.0, 99.0, 1.0]
    assert _percentile(values, 0.0) == 1.0
    assert _percentile(values, 1.0) == 99.0


def test_get_alert_thresholds_exposes_env_overridable_keys() -> None:
    """The dashboard can introspect what's currently configured.

    Lock the key set so a future env-rename does not silently break the
    /thresholds debug surface."""
    out = get_alert_thresholds()
    assert set(out) == {
        "low_score_value",
        "low_score_pct",
        "high_rank_value",
        "high_rank_pct",
        "zero_hit_pct",
        "min_sample",
    }


# ── End-to-end against a real SQLite ────────────────────────────────────


@pytest.fixture
async def session_factory(tmp_path):
    """Per-test file-backed SQLite holding only ``MatchSearchLog``.

    SQLite doesn't enforce foreign keys by default, so we can insert
    rows referencing arbitrary project_id UUIDs without bootstrapping
    the projects table.
    """
    db_path = tmp_path / "match_analytics.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        # Disable FK enforcement so we can insert search-log rows
        # referencing arbitrary project/session/group UUIDs without
        # bootstrapping every parent table. The aggregator never JOINs
        # against those FKs — it only reads the search-log row itself.
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.run_sync(Base.metadata.create_all, tables=[MatchSearchLog.__table__])
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _seed(
    maker,
    *,
    project_id: uuid.UUID | None = None,
    rows: list[dict] | None = None,
) -> None:
    """Insert a list of MatchSearchLog kwargs dicts. Defaults fill the FK."""
    pid = project_id or uuid.uuid4()
    async with maker() as db:
        for r in rows or []:
            payload = {
                "project_id": pid,
                "hard_filters": {},
                "soft_boosts": [],
                "metadata_": {},
                **r,
            }
            db.add(MatchSearchLog(**payload))
        await db.commit()


async def test_empty_window_returns_zero_counters_no_alerts(session_factory) -> None:
    """Fresh deploy with no search-log rows must return a clean response,
    not crash on missing aggregates."""
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7)
    assert out.total_searches == 0
    assert out.total_with_pick == 0
    assert out.pick_rate == 0.0
    assert out.alerts == []
    assert out.mean_top_score is None
    assert out.p95_top_score is None


async def test_basic_aggregates(session_factory) -> None:
    """Seed 4 rows → assert totals, score distribution, tier histogram."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    await _seed(
        session_factory,
        project_id=pid,
        rows=[
            {
                "hits_count": 5,
                "top_score": 0.9,
                "took_ms": 100,
                "relax_tier_used": 0,
                "top_confidence_band": "high",
                "created_at": now,
            },
            {
                "hits_count": 3,
                "top_score": 0.7,
                "took_ms": 200,
                "relax_tier_used": 1,
                "top_confidence_band": "medium",
                "created_at": now,
            },
            {
                "hits_count": 1,
                "top_score": 0.5,
                "took_ms": 300,
                "relax_tier_used": 2,
                "top_confidence_band": "low",
                "created_at": now,
            },
            {
                "hits_count": 0,
                "top_score": None,
                "took_ms": 400,
                "relax_tier_used": 3,
                "top_confidence_band": None,
                "created_at": now,
            },
        ],
    )
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    assert out.total_searches == 4
    assert out.mean_top_score == pytest.approx((0.9 + 0.7 + 0.5) / 3)
    assert out.zero_hit_pct == 0.25  # 1 of 4
    assert out.relax_tier_distribution == {"0": 1, "1": 1, "2": 1, "3": 1}
    # Note: rows with None confidence_band fall into the "unknown" bucket.
    assert out.confidence_band_distribution["high"] == 1
    assert out.confidence_band_distribution["medium"] == 1
    assert out.confidence_band_distribution["low"] == 1
    assert out.mean_took_ms == pytest.approx((100 + 200 + 300 + 400) / 4)


async def test_window_excludes_old_rows(session_factory) -> None:
    """Rows older than ``days`` must NOT contribute to totals."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    await _seed(
        session_factory,
        project_id=pid,
        rows=[
            {"hits_count": 5, "top_score": 0.9, "created_at": now},
            # 100 days old — way outside any reasonable window
            {"hits_count": 5, "top_score": 0.9, "created_at": now - timedelta(days=100)},
        ],
    )
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    assert out.total_searches == 1


async def test_days_clamped_to_max(session_factory) -> None:
    """``days`` argument must be clamped to the §_MAX_DAYS upper bound."""
    pid = uuid.uuid4()
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=10000, project_id=pid)
    assert out.window_days == 90


async def test_project_id_filter_isolates_rows(session_factory) -> None:
    """A project-scoped query must not see another project's rows."""
    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    now = datetime.now(tz=UTC)
    await _seed(
        session_factory,
        project_id=pid_a,
        rows=[
            {"hits_count": 5, "top_score": 0.9, "created_at": now},
            {"hits_count": 5, "top_score": 0.9, "created_at": now},
        ],
    )
    await _seed(
        session_factory,
        project_id=pid_b,
        rows=[
            {"hits_count": 1, "top_score": 0.1, "created_at": now},
        ],
    )
    async with session_factory() as db:
        out_a = await compute_match_analytics(db, days=7, project_id=pid_a)
        out_b = await compute_match_analytics(db, days=7, project_id=pid_b)
    assert out_a.total_searches == 2
    assert out_b.total_searches == 1
    # Rollup (no project_id filter) sees both
    async with session_factory() as db:
        out_all = await compute_match_analytics(db, days=7)
    assert out_all.total_searches == 3


async def test_pick_rate_and_picked_rank_aggregates(session_factory) -> None:
    """Pick rate must reflect picked_at presence; mean rank only over picks."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    await _seed(
        session_factory,
        project_id=pid,
        rows=[
            # 3 picks at ranks 1, 2, 3
            {"hits_count": 5, "top_score": 0.9, "picked_at": now, "picked_rank": 1, "created_at": now},
            {"hits_count": 5, "top_score": 0.8, "picked_at": now, "picked_rank": 2, "created_at": now},
            {"hits_count": 5, "top_score": 0.7, "picked_at": now, "picked_rank": 3, "created_at": now},
            # 2 unpicked
            {"hits_count": 5, "top_score": 0.6, "created_at": now},
            {"hits_count": 5, "top_score": 0.6, "created_at": now},
        ],
    )
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    assert out.total_searches == 5
    assert out.total_with_pick == 3
    assert out.pick_rate == pytest.approx(3 / 5)
    assert out.mean_picked_rank == pytest.approx(2.0)


async def test_breakdown_by_country_sorted_by_volume(session_factory) -> None:
    """Top-N breakdown must be ordered by search volume (desc)."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    rows = []
    for _ in range(5):
        rows.append({"hits_count": 5, "top_score": 0.8, "country": "DE", "created_at": now})
    for _ in range(2):
        rows.append({"hits_count": 5, "top_score": 0.6, "country": "RU", "created_at": now})
    rows.append({"hits_count": 5, "top_score": 0.4, "country": "BR", "created_at": now})
    await _seed(session_factory, project_id=pid, rows=rows)
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    keys = [b.key for b in out.by_country]
    assert keys == ["DE", "RU", "BR"]
    assert out.by_country[0].searches == 5
    assert out.by_country[0].mean_score == pytest.approx(0.8)


async def test_alert_low_top_score_fires_above_threshold(session_factory) -> None:
    """When >20% of searches score below 0.3, the catalogue-gap alert fires."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    rows = []
    # 30 rows with score 0.1 (low) + 70 with score 0.8 → 30% low → above 20%
    for _ in range(30):
        rows.append({"hits_count": 5, "top_score": 0.1, "created_at": now})
    for _ in range(70):
        rows.append({"hits_count": 5, "top_score": 0.8, "created_at": now})
    await _seed(session_factory, project_id=pid, rows=rows)
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    alert_ids = [a.id for a in out.alerts]
    assert "low_top_score" in alert_ids
    low = next(a for a in out.alerts if a.id == "low_top_score")
    assert low.metric == pytest.approx(0.30)
    assert low.threshold == pytest.approx(0.20)
    assert low.severity == "warning"


async def test_alert_low_top_score_does_not_fire_below_min_sample(session_factory) -> None:
    """Below MIN_SAMPLE rows we must not page on noise."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    # Only 5 rows total, but 4 of them scoring 0.1 — high pct, low N
    rows = [{"hits_count": 5, "top_score": 0.1, "created_at": now} for _ in range(4)]
    rows.append({"hits_count": 5, "top_score": 0.9, "created_at": now})
    await _seed(session_factory, project_id=pid, rows=rows)
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    assert out.alerts == []


async def test_alert_high_picked_rank_fires(session_factory) -> None:
    """If >20% of picks land at rank > 4, the re-train-classifier alert fires."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    rows = []
    # 10 picks at rank 1-3, 10 picks at rank 6 → 50% above rank 4
    for _ in range(10):
        rows.append({"hits_count": 5, "top_score": 0.9, "picked_at": now, "picked_rank": 1, "created_at": now})
    for _ in range(10):
        rows.append({"hits_count": 5, "top_score": 0.9, "picked_at": now, "picked_rank": 6, "created_at": now})
    # Pad to clear MIN_SAMPLE on the un-picked side too
    for _ in range(5):
        rows.append({"hits_count": 5, "top_score": 0.9, "created_at": now})
    await _seed(session_factory, project_id=pid, rows=rows)
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    alert_ids = [a.id for a in out.alerts]
    assert "high_picked_rank" in alert_ids


async def test_alert_over_restrictive_filter_fires_critical_above_25(session_factory) -> None:
    """Zero-hit rate >=25% on filtered searches → critical (not just warning)."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    rows = []
    # 25 filtered + zero-hit + 75 filtered + happy → 25% zero-hit
    for _ in range(25):
        rows.append(
            {
                "hits_count": 0,
                "top_score": None,
                "hard_filters": {"country": "DE"},
                "created_at": now,
            }
        )
    for _ in range(75):
        rows.append(
            {
                "hits_count": 5,
                "top_score": 0.8,
                "hard_filters": {"country": "DE"},
                "created_at": now,
            }
        )
    await _seed(session_factory, project_id=pid, rows=rows)
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    over = next(a for a in out.alerts if a.id == "over_restrictive_filters")
    assert over.severity == "critical"
    assert over.metric == pytest.approx(0.25)


async def test_catalog_id_filter_narrows_results(session_factory) -> None:
    """Catalog-scoped query must exclude other catalogues."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    await _seed(
        session_factory,
        project_id=pid,
        rows=[
            {"hits_count": 5, "top_score": 0.9, "catalog_id": "cwicr_DE", "created_at": now},
            {"hits_count": 5, "top_score": 0.9, "catalog_id": "cwicr_DE", "created_at": now},
            {"hits_count": 5, "top_score": 0.9, "catalog_id": "cwicr_RU", "created_at": now},
        ],
    )
    async with session_factory() as db:
        out_de = await compute_match_analytics(db, days=7, project_id=pid, catalog_id="cwicr_DE")
        out_ru = await compute_match_analytics(db, days=7, project_id=pid, catalog_id="cwicr_RU")
    assert out_de.total_searches == 2
    assert out_ru.total_searches == 1


async def test_rerank_pct_counters(session_factory) -> None:
    """``bge_rerank_used`` / ``llm_rerank_used`` flags roll up to percentages."""
    pid = uuid.uuid4()
    now = datetime.now(tz=UTC)
    await _seed(
        session_factory,
        project_id=pid,
        rows=[
            {"hits_count": 5, "top_score": 0.9, "bge_rerank_used": True, "llm_rerank_used": False, "created_at": now},
            {"hits_count": 5, "top_score": 0.9, "bge_rerank_used": True, "llm_rerank_used": True, "created_at": now},
            {"hits_count": 5, "top_score": 0.9, "bge_rerank_used": False, "llm_rerank_used": False, "created_at": now},
            {"hits_count": 5, "top_score": 0.9, "bge_rerank_used": False, "llm_rerank_used": False, "created_at": now},
        ],
    )
    async with session_factory() as db:
        out = await compute_match_analytics(db, days=7, project_id=pid)
    assert out.bge_rerank_pct == pytest.approx(0.5)
    assert out.llm_rerank_pct == pytest.approx(0.25)
