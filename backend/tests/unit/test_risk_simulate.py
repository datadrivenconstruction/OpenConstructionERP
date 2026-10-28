"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Risk Register Monte Carlo simulation (v3.11 — T1).

Covers:

* **Smoke**: 3 risks × 100 iterations → P50 ≤ P80 ≤ P95 (monotonic).
* **Determinism**: ``random.seed(42)`` makes the simulation reproducible.
* **Edge**: project with zero risks → empty/null result, no crash.
* **Edge**: project where every PERT triple is unset → falls back to
  zero-variance point estimate from ``impact_cost`` / ``impact_schedule_days``.
* **Edge**: mis-ordered triple (p10 > p90) clamped so triangular() never
  raises (regression guard for the pre-clamp version).
* Tornado entries sorted descending by contribution.
* ``last_simulation`` JSON persisted on every risk row after the run.

All tests use a transaction-isolated PostgreSQL session (rolled back on
teardown by ``tests._pg.transactional_session``) so they run fast and never
touch the production database.
"""

from __future__ import annotations

import random
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.risk.schemas import RiskCreate
from app.modules.risk.service import (
    RiskService,
    _histogram,
    _percentiles,
    _pert_triple_or_point,
)
from tests._pg import transactional_session

PROJECT_ID = uuid.uuid4()
EMPTY_PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session, seeded with two projects."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"o-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            )
        )
        await s.flush()
        s.add(Project(id=PROJECT_ID, name="MC Test", owner_id=OWNER_ID, currency="EUR"))
        s.add(
            Project(
                id=EMPTY_PROJECT_ID,
                name="Empty",
                owner_id=OWNER_ID,
                currency="EUR",
            )
        )
        await s.commit()
        yield s


def _create(**overrides) -> RiskCreate:
    base = {
        "project_id": PROJECT_ID,
        "title": "Test risk",
        "probability": 0.5,
        "impact_severity": "medium",
        "impact_cost": 100_000.0,
    }
    base.update(overrides)
    return RiskCreate(**base)


async def _seed_three_risks(svc: RiskService) -> list[uuid.UUID]:
    """Seed three risks with explicit PERT triples for cost+schedule."""
    r1 = await svc.create_risk(_create(title="Foundation soil", probability=0.5))
    r2 = await svc.create_risk(_create(title="Permit delay", probability=0.3))
    r3 = await svc.create_risk(_create(title="Steel price spike", probability=0.7, impact_severity="high"))
    # Read IDs into Python locals BEFORE issuing any update — the repo
    # ``update_fields`` calls ``session.expire_all()`` which would
    # otherwise force a lazy load on r{1,2,3}.id when read post-update,
    # tripping MissingGreenlet on the sync-cursor path.
    ids = [r1.id, r2.id, r3.id]
    pert_rows = (
        (ids[0], 5_000, 10_000, 25_000, 1, 3, 10),
        (ids[1], 2_000, 8_000, 30_000, 0, 5, 20),
        (ids[2], 20_000, 50_000, 200_000, 7, 14, 60),
    )
    for risk_id, c10, c50, c90, s10, s50, s90 in pert_rows:
        await svc.repo.update_fields(
            risk_id,
            cost_p10=Decimal(c10),
            cost_p50=Decimal(c50),
            cost_p90=Decimal(c90),
            schedule_p10=s10,
            schedule_p50=s50,
            schedule_p90=s90,
        )
    return ids


# ── Pure helpers ─────────────────────────────────────────────────────────


def test_percentiles_monotonic_and_inclusive_method():
    """P50 ≤ P80 ≤ P95 on a known distribution; matches statistics.quantiles."""
    samples = [float(i) for i in range(1, 101)]  # 1..100
    p50, p80, p95 = _percentiles(samples)
    assert p50 is not None
    assert p80 is not None
    assert p95 is not None
    assert p50 <= p80 <= p95
    # Inclusive method: rank = p * (n - 1). p=0.5 on 1..100 → 49.5 → 50.5.
    assert p50 == pytest.approx(50.5)
    assert p80 == pytest.approx(80.2)
    assert p95 == pytest.approx(95.05)


def test_percentiles_empty_returns_nones():
    assert _percentiles([]) == (None, None, None)


def test_percentiles_single_sample_returns_value():
    assert _percentiles([42.0]) == (42.0, 42.0, 42.0)


def test_histogram_bin_count_sums_to_samples():
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    bins = _histogram(samples, bins=5)
    assert len(bins) == 5
    assert sum(b["count"] for b in bins) == 10


def test_histogram_empty_returns_empty():
    assert _histogram([], bins=10) == []


def test_histogram_all_identical_collapses_to_one_bin():
    bins = _histogram([3.0, 3.0, 3.0], bins=10)
    assert len(bins) == 1
    assert bins[0]["count"] == 3


def test_pert_triple_clamps_misordered():
    """p10 > p90 was a triangular() crash bug; clamp pins lo ≤ mid ≤ hi."""
    lo, mid, hi = _pert_triple_or_point(Decimal(90), Decimal(50), Decimal(10), fallback=0.0)
    assert lo <= mid <= hi


def test_pert_triple_falls_back_to_point_when_missing():
    lo, mid, hi = _pert_triple_or_point(None, None, None, fallback=42.0)
    assert lo == mid == hi == 42.0


# ── Smoke: monotonic percentiles + run completes ─────────────────────────


@pytest.mark.asyncio
async def test_simulate_smoke_monotonic_percentiles(session):
    svc = RiskService(session)
    await _seed_three_risks(svc)
    random.seed(42)  # determinism for the assertions below
    res = await svc.simulate(PROJECT_ID, iterations=100, mode="both")

    assert res["risk_count"] == 3
    assert res["iterations"] == 100
    assert res["mode"] == "both"
    assert res["currency"] == "EUR"

    # P50 ≤ P80 ≤ P95 — the whole point of the percentile contract.
    assert res["p50_cost"] is not None
    assert res["p50_cost"] <= res["p80_cost"] <= res["p95_cost"]
    assert res["p50_schedule_days"] is not None
    assert res["p50_schedule_days"] <= res["p80_schedule_days"]
    assert res["p80_schedule_days"] <= res["p95_schedule_days"]

    # Histogram is a 10-bin equal-width distribution.
    assert len(res["histogram_bins"]) == 10
    assert sum(b["count"] for b in res["histogram_bins"]) == 100

    # Tornado entries sorted descending; one per risk.
    tornado = res["tornado"]
    assert len(tornado) == 3
    contribs = [float(e["contribution"]) for e in tornado]
    assert contribs == sorted(contribs, reverse=True)


@pytest.mark.asyncio
async def test_simulate_persists_last_simulation_on_every_row(session):
    """Every risk row must carry the snapshot after a run."""
    svc = RiskService(session)
    risk_ids = await _seed_three_risks(svc)
    random.seed(7)
    await svc.simulate(PROJECT_ID, iterations=50, mode="cost")

    # Refresh each row and check last_simulation is populated.
    from app.modules.risk.models import RiskItem

    for rid in risk_ids:
        row = await session.get(RiskItem, rid)
        assert row is not None
        assert row.last_simulation is not None
        assert row.last_simulation["iterations"] == 50
        assert row.last_simulation["mode"] == "cost"
        assert row.last_simulation["p50_cost"] is not None


# ── Regression: deterministic with the same seed ─────────────────────────


@pytest.mark.asyncio
async def test_simulate_deterministic_with_seed(session):
    """Same seed → byte-for-byte identical P50/P80/P95."""
    svc = RiskService(session)
    await _seed_three_risks(svc)

    random.seed(42)
    a = await svc.simulate(PROJECT_ID, iterations=200, mode="cost")
    random.seed(42)
    b = await svc.simulate(PROJECT_ID, iterations=200, mode="cost")

    assert a["p50_cost"] == b["p50_cost"]
    assert a["p80_cost"] == b["p80_cost"]
    assert a["p95_cost"] == b["p95_cost"]


# ── Edge: project with zero risks ────────────────────────────────────────


@pytest.mark.asyncio
async def test_simulate_zero_risks_returns_empty_result(session):
    """No risks → no crash, all percentiles null, empty histogram/tornado."""
    svc = RiskService(session)
    res = await svc.simulate(EMPTY_PROJECT_ID, iterations=100, mode="both")

    assert res["risk_count"] == 0
    assert res["iterations"] == 100
    assert res["p50_cost"] is None
    assert res["p80_cost"] is None
    assert res["p95_cost"] is None
    assert res["p50_schedule_days"] is None
    assert res["histogram_bins"] == []
    assert res["tornado"] == []


# ── Edge: only impact_cost set, no PERT triple — fallback path ───────────


@pytest.mark.asyncio
async def test_simulate_falls_back_to_point_when_pert_missing(session):
    """A risk with no PERT triple still contributes via ``impact_cost``."""
    svc = RiskService(session)
    # Three risks created with impact_cost only — no p10/p50/p90 set.
    await svc.create_risk(_create(title="A", probability=0.5, impact_cost=10_000))
    await svc.create_risk(_create(title="B", probability=0.3, impact_cost=20_000))
    await svc.create_risk(_create(title="C", probability=0.7, impact_cost=30_000))

    random.seed(123)
    res = await svc.simulate(PROJECT_ID, iterations=100, mode="cost")

    # With zero-variance point estimates the cost total per iteration is
    # constant — P50, P80 and P95 collapse to the same value.
    assert res["p50_cost"] is not None
    assert res["p50_cost"] == res["p80_cost"] == res["p95_cost"]


# ── Mode: schedule-only run skips cost percentiles ───────────────────────


@pytest.mark.asyncio
async def test_simulate_schedule_only_mode(session):
    svc = RiskService(session)
    await _seed_three_risks(svc)
    random.seed(99)
    res = await svc.simulate(PROJECT_ID, iterations=100, mode="schedule")

    assert res["mode"] == "schedule"
    assert res["p50_cost"] is None
    assert res["p50_schedule_days"] is not None
