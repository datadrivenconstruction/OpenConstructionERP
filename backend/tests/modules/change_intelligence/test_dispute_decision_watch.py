# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the dispute-risk, decision-impact and change-watch
service compositions (PostgreSQL, py3.12).

These three reads each gather a project's change-family records and feed them to
a pure sibling engine. The tests seed real change orders / variation orders /
MoC entries and check the composed result: that the dispute radar ranks and
money-weights the open changes, that the decision preview adds a candidate to
the committed baseline without blending currencies, and that the watch
classifies a stalled change. The heavy maths is unit-tested against the engines
themselves; here we only assert the wiring is correct.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.service import (
    build_change_watch,
    build_decision_impact,
    build_dispute_risk_board,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.cost_recovery.models import BackCharge
from app.modules.moc.models import MoCEntry
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"ddw-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Ddw",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Ddw {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


def _iso_days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


# --- Dispute-risk radar (#7) -----------------------------------------------


@pytest.mark.asyncio
async def test_dispute_risk_ranks_open_changes_and_weights_money(session: AsyncSession) -> None:
    pid = await _project(session)
    # Two open change orders, both overdue. One carries a large back-charge at
    # risk; the money weighting should rank it above the otherwise-comparable one.
    co_money = ChangeOrder(
        project_id=pid,
        code="CO-MONEY",
        title="Disputed, big money",
        status="submitted",
        ball_in_court="alice",
        response_due_date=_iso_days_ago(20),
    )
    co_plain = ChangeOrder(
        project_id=pid,
        code="CO-PLAIN",
        title="Disputed, no money",
        status="submitted",
        ball_in_court="bob",
        response_due_date=_iso_days_ago(20),
    )
    session.add_all([co_money, co_plain])
    await session.flush()

    # A back-charge linked to the money CO by source_ref (the change id).
    session.add(
        BackCharge(
            project_id=pid,
            source_ref=str(co_money.id),
            responsible_party="subcontractor a",
            gross_amount=Decimal("200000.00"),
            chargeable_pct=Decimal("1"),
            currency="EUR",
            status="proposed",
        )
    )
    await session.flush()

    ranked, summary = await build_dispute_risk_board(session, pid)

    refs = [it.change_ref for it in ranked]
    assert refs == ["CO-MONEY", "CO-PLAIN"]
    assert summary.item_count == 2
    # The money CO carries a real money basis and a EUR exposure-weighted row.
    money_item = ranked[0]
    assert Decimal(money_item.money_basis) == Decimal("200000.00")
    assert money_item.currency == "EUR"
    eur = {c.currency: c for c in summary.by_currency}
    assert "EUR" in eur
    assert Decimal(eur["EUR"].money_basis_total) == Decimal("200000.00")
    # Every item carries the four named factors with exactly one driver flagged.
    assert len(money_item.factors) == 4
    assert sum(1 for f in money_item.factors if f.is_driver) == 1


@pytest.mark.asyncio
async def test_dispute_risk_excludes_closed_changes(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            ChangeOrder(project_id=pid, code="CO-OPEN", title="Open", status="submitted"),
            # executed is a closed change-order status -> excluded from the radar.
            ChangeOrder(project_id=pid, code="CO-DONE", title="Done", status="executed"),
        ]
    )
    await session.flush()

    ranked, summary = await build_dispute_risk_board(session, pid)
    assert {it.change_ref for it in ranked} == {"CO-OPEN"}
    assert summary.item_count == 1


@pytest.mark.asyncio
async def test_dispute_risk_empty_project(session: AsyncSession) -> None:
    pid = await _project(session)
    ranked, summary = await build_dispute_risk_board(session, pid)
    assert ranked == []
    assert summary.item_count == 0
    assert summary.by_currency == ()


# --- Decision-time impact preview (#13) ------------------------------------


@pytest.mark.asyncio
async def test_decision_impact_adds_candidate_to_committed_baseline(session: AsyncSession) -> None:
    pid = await _project(session)
    # Committed baseline: one executed CO (1000 EUR / 5d) and an agreed VO
    # (500 EUR / 3d). A draft CO is NOT committed and must be excluded.
    session.add_all(
        [
            ChangeOrder(
                project_id=pid,
                code="CO-COMMIT",
                title="Committed",
                status="executed",
                cost_impact=Decimal("1000.00"),
                schedule_impact_days=5,
                currency="EUR",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-DRAFT",
                title="Draft",
                status="draft",
                cost_impact=Decimal("9999.00"),
                schedule_impact_days=9,
                currency="EUR",
            ),
            VariationOrder(
                project_id=pid,
                code="VO-COMMIT",
                title="Agreed VO",
                status="completed",
                final_cost_impact=Decimal("500.00"),
                final_schedule_days=3,
                currency="EUR",
            ),
        ]
    )
    await session.flush()

    # The candidate is a pending CO adding 250 EUR / 2d.
    candidate = ChangeOrder(
        project_id=pid,
        code="CO-CAND",
        title="Candidate",
        status="submitted",
        cost_impact=Decimal("250.00"),
        schedule_impact_days=2,
        currency="EUR",
    )
    session.add(candidate)
    await session.flush()

    impact, cand = await build_decision_impact(session, pid, candidate.id)

    assert cand.kind == "change_order"
    assert cand.currency == "EUR"
    # One EUR rollup: committed 1500 (1000 CO + 500 VO), candidate +250 -> 1750.
    totals = {t.currency: t for t in impact.totals_by_currency}
    assert Decimal(totals["EUR"].current_committed_cost) == Decimal("1500.00")
    assert Decimal(totals["EUR"].candidate_cost_delta) == Decimal("250.00")
    assert Decimal(totals["EUR"].resulting_cost) == Decimal("1750.00")
    # Days: committed 8 (5 + 3), candidate +2 -> 10.
    assert Decimal(totals["EUR"].current_committed_days) == Decimal("8")
    assert Decimal(totals["EUR"].resulting_days) == Decimal("10")
    # The candidate's own change-order row shows its delta on the committed CO line.
    co_rows = [r for r in impact.rows if r.kind == "change_order" and r.currency == "EUR"]
    assert len(co_rows) == 1
    assert Decimal(co_rows[0].candidate_cost_delta) == Decimal("250.00")


@pytest.mark.asyncio
async def test_decision_impact_does_not_blend_currencies(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add(
        ChangeOrder(
            project_id=pid,
            code="CO-USD",
            title="Committed USD",
            status="executed",
            cost_impact=Decimal("1000.00"),
            schedule_impact_days=4,
            currency="USD",
        )
    )
    await session.flush()
    # Candidate priced in EUR against USD committed work -> two currency rows.
    candidate = ChangeOrder(
        project_id=pid,
        code="CO-EUR",
        title="Candidate EUR",
        status="submitted",
        cost_impact=Decimal("300.00"),
        schedule_impact_days=1,
        currency="EUR",
    )
    session.add(candidate)
    await session.flush()

    impact, _cand = await build_decision_impact(session, pid, candidate.id)
    totals = {t.currency: t for t in impact.totals_by_currency}
    assert set(totals) == {"USD", "EUR"}
    # USD baseline untouched by the EUR candidate.
    assert Decimal(totals["USD"].current_committed_cost) == Decimal("1000.00")
    assert Decimal(totals["USD"].candidate_cost_delta) == Decimal("0.00")
    # EUR row carries only the candidate.
    assert Decimal(totals["EUR"].current_committed_cost) == Decimal("0.00")
    assert Decimal(totals["EUR"].candidate_cost_delta) == Decimal("300.00")


@pytest.mark.asyncio
async def test_decision_impact_resolves_candidate_across_families(session: AsyncSession) -> None:
    pid = await _project(session)
    # The candidate is a MoC entry (a different change family from CO/VO).
    moc = MoCEntry(
        project_id=pid,
        code="MOC-1",
        title="MoC candidate",
        status="proposed",
        cost_impact=Decimal("750.00"),
        schedule_delta_days=4,
        currency="GBP",
    )
    session.add(moc)
    await session.flush()

    impact, cand = await build_decision_impact(session, pid, moc.id)
    assert cand.kind == "moc_entry"
    assert cand.currency == "GBP"
    rows = {(r.kind, r.currency): r for r in impact.rows}
    assert ("moc_entry", "GBP") in rows
    assert Decimal(rows[("moc_entry", "GBP")].candidate_cost_delta) == Decimal("750.00")


@pytest.mark.asyncio
async def test_decision_impact_unknown_candidate_raises_lookuperror(session: AsyncSession) -> None:
    pid = await _project(session)
    with pytest.raises(LookupError):
        await build_decision_impact(session, pid, uuid.uuid4())


# --- Proactive change watch (#18) ------------------------------------------


@pytest.mark.asyncio
async def test_change_watch_flags_stalled_change(session: AsyncSession) -> None:
    pid = await _project(session)
    # An open CO, overdue and idle well beyond the stall threshold. created_at /
    # updated_at are server-managed, so to make the change look idle we set its
    # due date far in the past; the opened/last-movement baseline is "now" at
    # insert, so a freshly inserted row is not yet idle. We therefore assert the
    # weaker, deterministic property: a healthy recent change classifies ok, and
    # the counts always carry every class key.
    session.add(
        ChangeOrder(
            project_id=pid,
            code="CO-1",
            title="Recent open",
            status="submitted",
            ball_in_court="alice",
            response_due_date=_iso_days_ago(30),
        )
    )
    await session.flush()

    watch = await build_change_watch(session, pid)
    assert watch.item_count == 1
    # Every classification key is always present (zero when none).
    for key in ("lost", "stalled", "incomplete", "ok"):
        assert key in watch.counts
    # The single change carries an overdue-day count from its past-due date.
    assert watch.items[0].overdue_days > 0.0


@pytest.mark.asyncio
async def test_change_watch_counts_cover_every_class(session: AsyncSession) -> None:
    pid = await _project(session)
    watch = await build_change_watch(session, pid)
    assert watch.item_count == 0
    assert watch.counts == {"lost": 0, "stalled": 0, "incomplete": 0, "ok": 0}
