# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the value-realized service.

PostgreSQL, py3.12. Seeds the upstream records the service composes - approved
change orders / variation orders (committed cost + schedule), back-charges (the
recovery ledger) and activity-log rows (the hours-saved signal) - and drives the
thin service over the pure value engines, checking the composed per-currency
summary, the hours roll-up, the portfolio aggregation and the adoption
benchmark. Confidence labels are asserted at the documented low-n boundaries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog
from app.modules.changeorders.models import ChangeOrder
from app.modules.cost_recovery.models import BackCharge
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from app.modules.value.service import (
    build_adoption_benchmark,
    build_hours_saved,
    build_portfolio_summary,
    build_value_summary,
)
from app.modules.value.time_saved import BY_FEATURE, BY_USER
from tests._pg import transactional_session

NOW = datetime(2026, 6, 24, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"val-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Val",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Val {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


def _activity(project_id: uuid.UUID, module: str, action: str, *, actor: str | None = None) -> ActivityLog:
    """One activity-log row scoped to a project the way the timeline rolls up."""
    return ActivityLog(
        actor_id=uuid.UUID(actor) if actor else None,
        entity_type="rfi",
        entity_id=str(uuid.uuid4()),
        action=action,
        module=module,
        parent_entity_type="project",
        parent_entity_id=str(project_id),
        created_at=NOW,
    )


@pytest.mark.asyncio
async def test_value_summary_composes_exposure_recovery_and_hours(session: AsyncSession) -> None:
    pid = await _project(session)
    # Two approved change orders in EUR carry the exposure managed + schedule.
    session.add_all(
        [
            ChangeOrder(
                project_id=pid,
                code="CO-1",
                title="Approved",
                status="executed",
                cost_impact=Decimal("1000.00"),
                schedule_impact_days=5,
                currency="EUR",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-2",
                title="Approved 2",
                status="approved",
                cost_impact=Decimal("500.00"),
                schedule_impact_days=2,
                currency="EUR",
            ),
            # A draft change is not committed and must be excluded from exposure.
            ChangeOrder(
                project_id=pid,
                code="CO-3",
                title="Draft",
                status="draft",
                cost_impact=Decimal("999.00"),
                schedule_impact_days=9,
                currency="EUR",
            ),
        ]
    )
    # One back-charge in EUR: 1000 gross * 0.6 chargeable = 600 chargeable,
    # 150 recovered -> a recovery rate of 0.25.
    session.add(
        BackCharge(
            project_id=pid,
            responsible_party="subcontractor a",
            gross_amount=Decimal("1000.00"),
            chargeable_pct=Decimal("0.6"),
            recovered_amount=Decimal("150.00"),
            currency="EUR",
            status="agreed",
        )
    )
    # Two saving-bearing activity rows (an RFI answered + a takeoff parsed) plus
    # one row whose action saves nothing.
    session.add_all(
        [
            _activity(pid, "rfi", "rfi_answered"),
            _activity(pid, "takeoff", "takeoff_parsed"),
            _activity(pid, "projects", "project_viewed"),
        ]
    )
    await session.flush()

    summary = await build_value_summary(session, pid)

    assert summary.primary_currency == "EUR"
    assert len(summary.by_currency) == 1
    eur = summary.by_currency[0]
    assert eur.currency == "EUR"
    # Exposure managed = committed cost of the two approved changes only.
    assert eur.overrun_exposure_managed == Decimal("1500.00")
    assert eur.schedule_days_managed == Decimal("7")
    assert eur.impact_count == 2
    # Recovery figures from the back-charge.
    assert eur.chargeable_total == Decimal("600.00")
    assert eur.recovered_total == Decimal("150.00")
    assert eur.recovery_rate == Decimal("0.2500")
    assert eur.recovery_item_count == 1
    # Hours saved: rfi_answered (25) + takeoff_parsed (35) = 60 min = 1.00 h.
    assert summary.estimated_hours_saved == Decimal("1.00")
    # Two approved impacts and one recovery item: both low-n.
    assert summary.exposure_confidence == "low"
    assert summary.recovery_confidence == "low"
    # The hours figure rests on the two saving-bearing rows.
    assert summary.hours_sample == 2
    assert summary.hours_confidence == "low"
    # Activity count includes every scoped row (3), not only saving rows.
    assert summary.activity_count == 3
    # A recovery rate exists, so the dispute-risk proxy is defined.
    assert summary.dispute_risk_reduction is not None
    # No benchmark percentile is resolvable for a single project.
    assert summary.cost_position_percentile is None


@pytest.mark.asyncio
async def test_value_summary_empty_project(session: AsyncSession) -> None:
    pid = await _project(session)
    summary = await build_value_summary(session, pid)
    assert summary.by_currency == ()
    assert summary.primary_currency == ""
    assert summary.estimated_hours_saved == Decimal("0.00")
    assert summary.dispute_risk_reduction is None
    assert summary.exposure_confidence == "none"
    assert summary.recovery_confidence == "none"
    assert summary.hours_confidence == "none"
    assert summary.risk_confidence == "none"


@pytest.mark.asyncio
async def test_value_summary_never_blends_currencies(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            ChangeOrder(
                project_id=pid,
                code="CO-EUR",
                title="EUR change",
                status="executed",
                cost_impact=Decimal("1000.00"),
                schedule_impact_days=1,
                currency="EUR",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-USD",
                title="USD change",
                status="executed",
                cost_impact=Decimal("2000.00"),
                schedule_impact_days=3,
                currency="USD",
            ),
        ]
    )
    await session.flush()

    summary = await build_value_summary(session, pid)
    currencies = {row.currency for row in summary.by_currency}
    assert currencies == {"EUR", "USD"}
    # The larger USD exposure leads (rows sorted by descending exposure).
    assert summary.by_currency[0].currency == "USD"
    assert summary.primary_currency == "USD"


@pytest.mark.asyncio
async def test_hours_saved_grouped_by_feature(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            _activity(pid, "rfi", "rfi_answered"),
            _activity(pid, "rfi", "rfi_answered"),
            _activity(pid, "takeoff", "takeoff_parsed"),
        ]
    )
    await session.flush()

    buckets, total, event_count = await build_hours_saved(session, pid, by=BY_FEATURE)

    assert event_count == 3
    # Two rfi_answered (25 each) + one takeoff_parsed (35) = 85 min = 1.42 h.
    assert total == Decimal("1.42")
    by_key = {b.key: b for b in buckets}
    assert by_key["rfi/rfi_answered"].event_count == 2
    assert by_key["rfi/rfi_answered"].minutes == Decimal("50")
    assert by_key["takeoff/takeoff_parsed"].minutes == Decimal("35")


@pytest.mark.asyncio
async def test_hours_saved_grouped_by_user(session: AsyncSession) -> None:
    pid = await _project(session)
    actor = str(uuid.uuid4())
    session.add_all(
        [
            _activity(pid, "rfi", "rfi_answered", actor=actor),
            _activity(pid, "takeoff", "takeoff_parsed"),  # no actor -> unknown bucket
        ]
    )
    await session.flush()

    buckets, _total, _count = await build_hours_saved(session, pid, by=BY_USER)
    keys = {b.key for b in buckets}
    assert actor in keys
    assert "unknown" in keys


@pytest.mark.asyncio
async def test_portfolio_summary_sums_per_currency(session: AsyncSession) -> None:
    pid_a = await _project(session)
    pid_b = await _project(session)
    session.add_all(
        [
            ChangeOrder(
                project_id=pid_a,
                code="A-CO",
                title="A",
                status="executed",
                cost_impact=Decimal("1000.00"),
                schedule_impact_days=2,
                currency="EUR",
            ),
            ChangeOrder(
                project_id=pid_b,
                code="B-CO",
                title="B",
                status="executed",
                cost_impact=Decimal("3000.00"),
                schedule_impact_days=4,
                currency="EUR",
            ),
        ]
    )
    await session.flush()

    summary = await build_portfolio_summary(session, [pid_a, pid_b])
    assert summary.primary_currency == "EUR"
    assert len(summary.by_currency) == 1
    # Exposure sums across the two projects in the same currency.
    assert summary.by_currency[0].overrun_exposure_managed == Decimal("4000.00")
    assert summary.by_currency[0].impact_count == 2


@pytest.mark.asyncio
async def test_portfolio_summary_empty_input(session: AsyncSession) -> None:
    summary = await build_portfolio_summary(session, [])
    assert summary.by_currency == ()
    assert summary.primary_currency == ""
    assert summary.estimated_hours_saved == Decimal("0.00")


@pytest.mark.asyncio
async def test_adoption_benchmark_scores_and_splits(session: AsyncSession) -> None:
    # A high-adoption project: a change with a recorded owner + dense activity.
    pid_high = await _project(session)
    session.add(
        ChangeOrder(
            project_id=pid_high,
            code="H-CO",
            title="Traceable",
            status="submitted",
            ball_in_court="alice",
        )
    )
    # Several assisted actions per change -> high activity density.
    session.add_all([_activity(pid_high, "rfi", "rfi_answered") for _ in range(6)])

    # A low-adoption project: a change with no owner and no assisted activity.
    pid_low = await _project(session)
    session.add(
        ChangeOrder(
            project_id=pid_low,
            code="L-CO",
            title="Untraceable",
            status="submitted",
            ball_in_court=None,
        )
    )
    await session.flush()

    benchmark = await build_adoption_benchmark(session, [pid_high, pid_low])

    scores = {s.project_id: s for s in benchmark.project_scores}
    assert scores[str(pid_high)].cohort == "high"
    assert scores[str(pid_low)].cohort == "low"
    assert benchmark.high_count == 1
    assert benchmark.low_count == 1
    # One project per cohort is an anecdote, not a benchmark: confidence none.
    assert benchmark.confidence == "none"
    # Three outcome metrics are always reported, in engine order.
    assert [c.metric for c in benchmark.comparisons] == [
        "recovery_rate",
        "overrun_pct",
        "avg_cycle_days",
    ]


@pytest.mark.asyncio
async def test_adoption_benchmark_empty_input(session: AsyncSession) -> None:
    benchmark = await build_adoption_benchmark(session, [])
    assert benchmark.project_scores == ()
    assert benchmark.high_count == 0
    assert benchmark.low_count == 0
    assert benchmark.confidence == "none"
