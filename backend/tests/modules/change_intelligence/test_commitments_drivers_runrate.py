# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the commitment register, change drivers and run-rate.

PostgreSQL, py3.12. Seeds records across the source modules directly and drives
the three services that feed the pure :mod:`action_register`,
:mod:`change_drivers` and :mod:`change_run_rate` engines, checking the
cross-source gather, the fault rollup and the cumulative curve against a fixed
clock. Cannot run on the 3.11 pure-engine runner (needs the app + database).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.change_drivers import (
    PARTY_CLIENT,
    PARTY_DESIGNER,
    PARTY_UNCLASSIFIED,
)
from app.modules.change_intelligence.service import (
    build_change_drivers,
    build_change_run_rate,
    build_commitment_register,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.meetings.models import Meeting
from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.risk.models import RiskItem
from app.modules.submittals.models import Submittal
from app.modules.users.models import User
from app.modules.variations.models import (
    DisruptionClaim,
    ExtensionOfTimeClaim,
    VariationOrder,
    VariationRequest,
)
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, **kwargs: object) -> uuid.UUID:
    user = User(
        email=f"cc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CC",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"CC {uuid.uuid4().hex[:6]}", owner_id=user.id, **kwargs)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_commitment_register_gathers_all_sources(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            Meeting(
                project_id=pid,
                meeting_number="M-1",
                meeting_type="progress",
                title="Weekly",
                meeting_date="2026-06-01",
                action_items=[
                    {"description": "Chase design", "owner_id": "alice", "due_date": "2026-06-01", "status": "open"},
                    {"description": "Done item", "owner_id": "bob", "due_date": "2026-06-01", "status": "completed"},
                ],
            ),
            RiskItem(
                project_id=pid,
                code="R-1",
                title="Ground risk",
                mitigation_actions=[
                    {"description": "Survey", "responsible_id": "carol", "due_date": "2026-06-05", "status": "open"},
                ],
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-1",
                title="Extra works",
                status="submitted",
                ball_in_court="alice",
                response_due_date="2026-06-10",
            ),
            RFI(
                project_id=pid,
                rfi_number="RFI-1",
                subject="Slab detail",
                question="?",
                raised_by=uuid.uuid4(),
                status="open",
                ball_in_court="dave",
                response_due_date="2026-06-15",
            ),
            RFI(
                project_id=pid,
                rfi_number="RFI-2",
                subject="Closed one",
                question="?",
                raised_by=uuid.uuid4(),
                status="closed",
                ball_in_court="dave",
                response_due_date="2026-06-15",
            ),
            Submittal(
                project_id=pid,
                submittal_number="SUB-1",
                title="Rebar",
                submittal_type="shop_drawing",
                status="submitted",
                ball_in_court="alice",
                date_required="2026-06-20",
            ),
        ]
    )
    await session.flush()

    register = await build_commitment_register(session, pid, now=datetime(2026, 12, 31, tzinfo=UTC))

    # The completed meeting action and the closed RFI are excluded; everything
    # else (meeting action + risk action + CO + open RFI + submittal) is open.
    assert register.total_open == 5
    assert register.overdue_count == 5  # every due date is in June, well before Dec 31
    assert register.by_source == {
        "change_order": 1,
        "meeting_action": 1,
        "rfi": 1,
        "risk_action": 1,
        "submittal": 1,
    }
    # alice owes three (meeting action + CO + submittal) and tops the ranking.
    assert register.by_owner[0].owner == "alice"
    assert register.by_owner[0].open_count == 3


@pytest.mark.asyncio
async def test_change_drivers_pareto_and_fault_rollup(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            ChangeOrder(
                project_id=pid,
                code="CO-1",
                title="Design fix",
                reason_category="design_error",
                cost_impact=Decimal("6000"),
                currency="EUR",
                status="approved",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-2",
                title="Owner add",
                reason_category="client_request",
                cost_impact=Decimal("3000"),
                currency="EUR",
                status="submitted",
            ),
            DisruptionClaim(
                project_id=pid,
                root_cause="Trade stacking",
                cost_amount=Decimal("1000"),
                currency="EUR",
            ),
            ExtensionOfTimeClaim(
                project_id=pid,
                root_cause_category="employer",
                requested_days=10,
            ),
            RiskItem(
                project_id=pid,
                code="R-1",
                title="Tech risk",
                category="technical",
                impact_cost="500",
                currency="EUR",
            ),
        ]
    )
    await session.flush()

    analytics = await build_change_drivers(session, pid)

    assert analytics.total_count == 5
    assert analytics.total_cost == Decimal("10500")
    assert analytics.primary_currency == "EUR"

    causes = {r.key: r for r in analytics.by_cause}
    assert causes["design_error"].cost == Decimal("6000")
    assert causes["client_request"].cost == Decimal("3000")
    assert causes["trade_stacking"].cost == Decimal("1000")
    assert causes["employer"].cost == Decimal("0")
    # Ranked by cost: design_error carries the most, so it leads and its
    # cumulative share is its own share.
    assert analytics.by_cause[0].key == "design_error"
    assert analytics.by_cause[0].cumulative_pct == pytest.approx(57.14, abs=0.01)

    parties = {r.key: r for r in analytics.by_party}
    assert parties[PARTY_DESIGNER].cost == Decimal("6000")
    # client_request CO + employer EOT both allocate to the client.
    assert parties[PARTY_CLIENT].count == 2
    assert parties[PARTY_CLIENT].cost == Decimal("3000")
    # Disruption free-text root cause + risk category carry no fault signal.
    assert parties[PARTY_UNCLASSIFIED].count == 2
    assert parties[PARTY_UNCLASSIFIED].cost == Decimal("1500")


@pytest.mark.asyncio
async def test_change_run_rate_curve_and_forecast(session: AsyncSession) -> None:
    pid = await _project(
        session,
        contract_value="1000000",
        planned_start_date="2026-01-01",
        planned_end_date="2026-12-31",
    )
    session.add_all(
        [
            ChangeOrder(
                project_id=pid,
                code="CO-1",
                title="Approved",
                status="approved",
                cost_impact=Decimal("50000"),
                currency="EUR",
                submitted_at="2026-03-01",
                approved_at="2026-03-15",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-2",
                title="Pending",
                status="draft",
                cost_impact=Decimal("20000"),
                currency="EUR",
                submitted_at="2026-05-10",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-3",
                title="Rejected",
                status="rejected",
                cost_impact=Decimal("99999"),
                currency="EUR",
            ),
            VariationOrder(
                project_id=pid,
                code="VO-1",
                title="Issued",
                status="issued",
                final_cost_impact=Decimal("30000"),
                currency="EUR",
                agreed_at="2026-04-20",
            ),
            VariationRequest(
                project_id=pid,
                code="VR-1",
                title="Pending req",
                status="submitted",
                estimated_cost_impact=Decimal("10000"),
                currency="EUR",
                submitted_at="2026-06-01",
            ),
            VariationRequest(
                project_id=pid,
                code="VR-2",
                title="Approved req (downstream VO carries it)",
                status="approved",
                estimated_cost_impact=Decimal("77777"),
                currency="EUR",
                submitted_at="2026-06-01",
            ),
        ]
    )
    await session.flush()

    run_rate = await build_change_run_rate(session, pid, now=datetime(2026, 6, 30, tzinfo=UTC))

    # CO-3 (rejected) and VR-2 (approved -> superseded) are excluded.
    assert run_rate.change_count == 4
    assert run_rate.approved_value == Decimal("80000")  # CO-1 + VO-1
    assert run_rate.pending_value == Decimal("30000")  # CO-2 + VR-1
    assert run_rate.total_change_value == Decimal("110000")
    assert run_rate.current_change_pct == Decimal("11.00")
    assert run_rate.currency == "EUR"

    assert [(p.month, p.cumulative_value) for p in run_rate.points] == [
        ("2026-03", Decimal("50000")),
        ("2026-04", Decimal("80000")),
        ("2026-05", Decimal("100000")),
        ("2026-06", Decimal("110000")),
    ]

    assert run_rate.forecast is not None
    assert run_rate.forecast.method == "linear_burn_rate"
    assert run_rate.forecast.elapsed_days == 180  # Jan 1 -> Jun 30
    assert run_rate.forecast.total_days == 364  # Jan 1 -> Dec 31
    assert run_rate.forecast.final_change_pct is not None
