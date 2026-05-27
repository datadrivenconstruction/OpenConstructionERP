"""Unit tests for the Risk Register module — service + scoring + matrix.

Covers the QA-walkthrough findings:

* Risk score = probability x severity_numeric (and recompute on update).
* 5x5 PMBOK matrix scoring: probability_score, impact_score_cost,
  impact_score_time, risk_tier — all computed AND surfaced in the API
  response (regression: they were stored but never returned, which left
  the frontend heatmap permanently dead).
* Auto-generated codes (R-001, R-002, ...).
* Summary aggregation: by_status / by_tier / by_category, exposure,
  high_critical_count, mitigation tracking, top_risks ordering.
* Matrix bucketing incl. legacy severity aliases (negligible/minor/...)
  and the `very_low` impact cell that the frontend previously dropped.
* ``_risk_to_response`` never 500s on an empty-string numeric column.

Per ``feedback_test_isolation.md`` every test uses an isolated temp
SQLite — never ``backend/openestimate.db``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.risk.router import _as_float, _risk_to_response
from app.modules.risk.schemas import RiskCreate, RiskUpdate
from app.modules.risk.service import (
    RiskService,
    _compute_risk_score,
    _compute_risk_tier,
    _probability_to_score,
)

PROJECT_ID = uuid.uuid4()
OTHER_PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


def _register_models() -> None:
    import app.modules.projects.models  # noqa: F401
    import app.modules.risk.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp()) / "risk.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
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
        s.add(Project(id=PROJECT_ID, name="Risk Test", owner_id=OWNER_ID, currency="EUR"))
        s.add(Project(id=OTHER_PROJECT_ID, name="Other", owner_id=OWNER_ID, currency="USD"))
        await s.commit()
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


def _create(**overrides) -> RiskCreate:
    base = {
        "project_id": PROJECT_ID,
        "title": "Foundation soil instability",
        "probability": 0.5,
        "impact_severity": "medium",
        "impact_cost": 100_000.0,
    }
    base.update(overrides)
    return RiskCreate(**base)


# ── Pure scoring functions ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("prob", "sev", "expected"),
    [
        (0.5, "medium", 1.5),  # 0.5 * 3
        (1.0, "critical", 5.0),  # 1.0 * 5
        (0.2, "low", 0.4),  # 0.2 * 2
        (0.0, "high", 0.0),  # 0.0 * 4
        (0.5, "catastrophic", 2.5),  # legacy alias == 5
    ],
)
def test_compute_risk_score(prob, sev, expected):
    assert _compute_risk_score(prob, sev) == expected


@pytest.mark.parametrize(
    ("prob", "expected"),
    [
        (0.0, 1),
        (0.2, 1),
        (0.21, 2),
        (0.4, 2),
        (0.6, 3),
        (0.8, 4),
        (0.81, 5),
        (1.0, 5),
    ],
)
def test_probability_to_score_buckets(prob, expected):
    assert _probability_to_score(prob) == expected


@pytest.mark.parametrize(
    ("p", "i", "tier"),
    [
        (1, 1, "low"),  # product 1  -> band 1-4
        (2, 2, "low"),  # product 4  -> band 1-4
        (1, 5, "medium"),  # product 5  -> band 5-9
        (3, 3, "medium"),  # product 9  -> band 5-9
        (2, 5, "high"),  # product 10 -> band 10-15
        (4, 4, "critical"),  # product 16 -> band 16-25
        (5, 5, "critical"),  # product 25 -> band 16-25
    ],
)
def test_compute_risk_tier_thresholds(p, i, tier):
    # Sanity: tier matches the documented 1-4 / 5-9 / 10-15 / 16-25 bands.
    product = p * i
    if product >= 16:
        assert tier == "critical"
    elif product >= 10:
        assert tier == "high"
    elif product >= 5:
        assert tier == "medium"
    else:
        assert tier == "low"
    assert _compute_risk_tier(p, i) == tier


# ── Create: code generation + stored scoring ──────────────────────────────


@pytest.mark.asyncio
async def test_create_generates_sequential_codes(session):
    svc = RiskService(session)
    r1 = await svc.create_risk(_create(title="A"))
    r2 = await svc.create_risk(_create(title="B"))
    assert r1.code == "R-001"
    assert r2.code == "R-002"
    # Codes are scoped per project.
    r_other = await svc.create_risk(_create(project_id=OTHER_PROJECT_ID, title="C"))
    assert r_other.code == "R-001"


@pytest.mark.asyncio
async def test_create_persists_5x5_scoring_fields(session):
    svc = RiskService(session)
    r = await svc.create_risk(_create(probability=0.9, impact_severity="critical"))
    assert r.probability_score == 5
    assert r.impact_score_cost == 5
    assert r.impact_score_time == 5
    assert r.risk_tier == "critical"
    assert float(r.risk_score) == pytest.approx(4.5)  # 0.9 * 5


@pytest.mark.asyncio
async def test_response_exposes_scoring_fields(session):
    """Regression: scoring fields were stored but absent from the
    response schema, so the frontend heatmap render-guard
    (``probability_score != null && impact_score_cost != null``) was
    permanently false and the 5x5 heatmap never appeared."""
    svc = RiskService(session)
    r = await svc.create_risk(_create(probability=0.5, impact_severity="high"))
    resp = _risk_to_response(r)
    # P(0.5)->score 3, impact "high"->4, product 12 -> "high" tier band.
    assert resp.probability_score == 3
    assert resp.impact_score_cost == 4
    assert resp.impact_score_time == 4
    assert resp.risk_tier == "high"


# ── Update: recompute on probability / severity change ────────────────────


@pytest.mark.asyncio
async def test_update_recomputes_score_and_tier(session):
    svc = RiskService(session)
    r = await svc.create_risk(_create(probability=0.2, impact_severity="low"))
    assert r.risk_tier == "low"

    updated = await svc.update_risk(r.id, RiskUpdate(probability=0.9, impact_severity="critical"))
    assert float(updated.risk_score) == pytest.approx(4.5)
    assert updated.probability_score == 5
    assert updated.impact_score_cost == 5
    assert updated.risk_tier == "critical"


@pytest.mark.asyncio
async def test_update_without_scoring_change_keeps_score(session):
    svc = RiskService(session)
    r = await svc.create_risk(_create(probability=0.5, impact_severity="medium"))
    score_before = r.risk_score
    updated = await svc.update_risk(r.id, RiskUpdate(title="Renamed"))
    assert updated.risk_score == score_before
    assert updated.title == "Renamed"


@pytest.mark.asyncio
async def test_get_missing_risk_raises_404(session):
    svc = RiskService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.get_risk(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_risk(session):
    svc = RiskService(session)
    r = await svc.create_risk(_create())
    await svc.delete_risk(r.id)
    with pytest.raises(HTTPException):
        await svc.get_risk(r.id)


# ── Summary aggregation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_aggregates_correctly(session):
    svc = RiskService(session)
    await svc.create_risk(
        _create(
            title="High one",
            probability=0.9,
            impact_severity="critical",
            impact_cost=200_000.0,
            mitigation_strategy="Survey first",
        )
    )
    r2 = await svc.create_risk(
        _create(
            title="Low one",
            probability=0.1,
            impact_severity="low",
            impact_cost=10_000.0,
        )
    )
    await svc.update_risk(r2.id, RiskUpdate(status="mitigating"))

    summary = await svc.get_summary(PROJECT_ID)
    assert summary["total"] == 2
    assert summary["total_risks"] == 2
    assert summary["high_critical_count"] == 1
    assert summary["with_mitigation"] == 1
    assert summary["without_mitigation"] == 1
    assert summary["mitigated_count"] == 1  # r2 -> mitigating
    # Exposure = sum(impact_cost * probability) = 200000*0.9 + 10000*0.1
    assert summary["total_exposure"] == pytest.approx(180_000.0 + 1_000.0)
    assert summary["by_status"]["mitigating"] == 1
    assert summary["by_category"]["technical"] == 2
    assert summary["by_tier"]["critical"] == 1
    # Top risks sorted by score descending.
    assert summary["top_risks"][0]["title"] == "High one"
    assert summary["currency"] == "EUR"


@pytest.mark.asyncio
async def test_summary_empty_project(session):
    svc = RiskService(session)
    summary = await svc.get_summary(OTHER_PROJECT_ID)
    assert summary["total"] == 0
    assert summary["avg_risk_score"] == 0.0
    assert summary["top_risks"] == []


# ── Risk matrix ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_matrix_has_25_cells_and_buckets_risk(session):
    svc = RiskService(session)
    await svc.create_risk(_create(probability=0.5, impact_severity="medium"))
    cells = await svc.get_matrix(PROJECT_ID)
    assert len(cells) == 25  # 5 probability x 5 impact
    hit = [c for c in cells if c["count"] > 0]
    assert len(hit) == 1
    assert hit[0]["probability_level"] == "0.5"
    assert hit[0]["impact_level"] == "medium"


@pytest.mark.asyncio
async def test_matrix_legacy_alias_maps_to_very_low_cell(session):
    """Legacy 'negligible' severity must land in the canonical
    `very_low` impact cell — the frontend now renders that column."""
    svc = RiskService(session)
    r = await svc.create_risk(_create(probability=0.1))
    # Bypass schema enum lock to simulate legacy / imported data.
    await svc.repo.update_fields(r.id, impact_severity="negligible")
    cells = await svc.get_matrix(PROJECT_ID)
    hit = [c for c in cells if c["count"] > 0]
    assert len(hit) == 1
    assert hit[0]["impact_level"] == "very_low"
    assert hit[0]["probability_level"] == "0.1"


@pytest.mark.asyncio
async def test_matrix_excludes_closed_risks(session):
    svc = RiskService(session)
    r = await svc.create_risk(_create())
    await svc.update_risk(r.id, RiskUpdate(status="closed"))
    cells = await svc.get_matrix(PROJECT_ID)
    assert all(c["count"] == 0 for c in cells)


# ── list_risks: filtering + sorting + pagination ──────────────────────────


@pytest.mark.asyncio
async def test_list_filters_and_sorts(session):
    svc = RiskService(session)
    await svc.create_risk(_create(title="Tech", category="technical", probability=0.2, impact_severity="low"))
    await svc.create_risk(_create(title="Fin", category="financial", probability=0.9, impact_severity="critical"))

    items, total = await svc.list_risks(PROJECT_ID, category_filter="financial")
    assert total == 1
    assert items[0].title == "Fin"

    items, _ = await svc.list_risks(PROJECT_ID, sort_by="risk_score", sort_order="desc")
    assert items[0].title == "Fin"  # highest score first

    items, _ = await svc.list_risks(PROJECT_ID, limit=1, offset=1)
    assert len(items) == 1


# ── _as_float / response hardening ────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "default", "expected"),
    [
        ("1.5", 0.0, 1.5),
        ("", 0.5, 0.5),
        (None, 0.0, 0.0),
        ("not-a-number", 0.0, 0.0),
        ("0", 0.0, 0.0),
    ],
)
def test_as_float_never_raises(raw, default, expected):
    assert _as_float(raw, default) == expected


def test_response_survives_empty_numeric_columns():
    """A legacy / imported row with empty-string numeric columns must not
    500 the whole list endpoint via ``float('')`` — ``_risk_to_response``
    must fall back to the documented defaults instead of raising."""
    from datetime import UTC, datetime

    from app.modules.risk.models import RiskItem

    now = datetime.now(UTC)
    row = RiskItem(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        code="R-001",
        title="Legacy import",
        description="",
        category="technical",
        probability="",  # empty -> would raise float('')
        impact_cost="",
        impact_schedule_days=0,
        impact_severity="medium",
        risk_score="",
        status="identified",
        mitigation_strategy="",
        contingency_plan="",
        owner_name="",
        response_cost="",
        currency="EUR",
        metadata_={},
    )
    row.created_at = now
    row.updated_at = now

    resp = _risk_to_response(row)
    assert resp.probability == 0.5  # documented default
    assert resp.impact_cost == 0.0
    assert resp.risk_score == 0.0
    assert resp.response_cost == 0.0
