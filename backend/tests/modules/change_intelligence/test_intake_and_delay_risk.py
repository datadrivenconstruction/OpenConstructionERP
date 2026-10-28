# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the multi-source intake (#14) and predictive delay-risk
(#19) service compositions.

Intake is a pure, stateless normalizer, so its service surface is exercised
directly (no database): a foreign change-request record plus a built-in mapping
profile in, a canonical draft with diagnostics out. Delay-risk is a composition
over the live change records, so those tests seed real change orders and a
project contract value and check the wiring: that the board ranks open changes
by the blended risk, money-weights size against the contract, surfaces the four
named factors, and excludes closed changes. The blending and banding maths is
unit-tested against the pure engine itself; here we only assert the wiring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.service import (
    build_delay_risk_board,
    intake_canonical_fields,
    list_intake_profiles,
    preview_intake,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, *, contract_value: str | None = None) -> uuid.UUID:
    user = User(
        email=f"dri-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Dri",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Dri {uuid.uuid4().hex[:6]}", owner_id=user.id, contract_value=contract_value)
    session.add(proj)
    await session.flush()
    return proj.id


def _iso_days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _iso_days_ahead(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


# --- Multi-source intake normalizer (#14) ----------------------------------


def test_list_intake_profiles_exposes_the_builtins() -> None:
    names = {p.profile_name for p in list_intake_profiles()}
    assert "generic_spreadsheet" in names
    assert "generic_email_form" in names


def test_intake_canonical_fields_cover_the_change_request_shape() -> None:
    fields = intake_canonical_fields()
    assert "title" in fields
    assert "cost_impact" in fields
    assert "schedule_impact_days" in fields


def test_preview_intake_maps_aliases_and_parses_money_and_schedule() -> None:
    # A spreadsheet-dialect row: foreign labels, money with a currency symbol and
    # thousands separator, a bare day count, and one column the profile ignores.
    result = preview_intake(
        "generic_spreadsheet",
        {
            "Change Title": "Extra waterproofing",
            "Estimated Cost": "$12,500.00",
            "Schedule Impact (days)": "5",
            "Raised By": "Site Engineer",
            "Change No": "CO-44",
            "Mystery Column": "ignored",
        },
    )
    draft = result.draft
    assert draft.title == "Extra waterproofing"
    assert draft.cost_impact == Decimal("12500.00")
    assert draft.currency == "USD"
    assert draft.schedule_impact_days == Decimal("5")
    assert draft.requested_by == "Site Engineer"
    assert draft.source_ref == "CO-44"
    # The unknown column is reported, not silently dropped; required fields are met.
    assert result.unmapped_fields == ("Mystery Column",)
    assert result.missing_required == ()
    assert result.completeness == 1.0


def test_preview_intake_reports_missing_required_and_completeness() -> None:
    # An email-form row with only a subject: description and cost are required and
    # absent, so they are flagged and completeness is the present-required share.
    result = preview_intake(
        "generic_email_form",
        {"Subject": "New ductwork run", "Random": "x"},
    )
    assert result.draft.title == "New ductwork run"
    assert result.missing_required == ("description", "cost_impact")
    assert result.unmapped_fields == ("Random",)
    assert result.completeness == round(1 / 3, 2)


def test_preview_intake_unknown_profile_raises_lookuperror() -> None:
    with pytest.raises(LookupError):
        preview_intake("no_such_profile", {"Subject": "x"})


# --- Predictive delay / overrun risk (#19) ---------------------------------


@pytest.mark.asyncio
async def test_delay_risk_ranks_overdue_and_costly_change_first(session: AsyncSession) -> None:
    pid = await _project(session, contract_value="1000000.00")
    # CO-BIG: overdue, held by a holder with no other work, worth 30% of the
    # contract (the size sub-score saturates). CO-SMALL: not due yet, tiny value.
    big = ChangeOrder(
        project_id=pid,
        code="CO-BIG",
        title="Big and overdue",
        status="submitted",
        ball_in_court="alice",
        response_due_date=_iso_days_ago(20),
        cost_impact=Decimal("300000.00"),
        currency="EUR",
    )
    small = ChangeOrder(
        project_id=pid,
        code="CO-SMALL",
        title="Small and on time",
        status="submitted",
        ball_in_court="bob",
        response_due_date=_iso_days_ahead(30),
        cost_impact=Decimal("100.00"),
        currency="EUR",
    )
    session.add_all([big, small])
    await session.flush()

    ranked, items_by_id = await build_delay_risk_board(session, pid)

    assert [items_by_id[r.change_id].code for r in ranked] == ["CO-BIG", "CO-SMALL"]
    top = ranked[0]
    # The big overdue change is at least elevated; the on-time tiny one is low.
    assert top.band in ("elevated", "high")
    assert ranked[1].band == "low"
    assert top.risk > ranked[1].risk
    # Every change carries the four named, ranked factors.
    assert {f.name for f in top.top_factors} == {
        "dwell_pressure",
        "holder_overdue_rate",
        "change_size",
        "holder_load",
    }
    # The contributions are ranked highest first.
    contributions = [f.contribution for f in top.top_factors]
    assert contributions == sorted(contributions, reverse=True)


@pytest.mark.asyncio
async def test_delay_risk_size_factor_needs_a_contract_value(session: AsyncSession) -> None:
    # With no contract value the size factor cannot be computed and stays at zero,
    # so an otherwise-quiet, on-time change scores no size pressure.
    pid = await _project(session, contract_value=None)
    session.add(
        ChangeOrder(
            project_id=pid,
            code="CO-NOSIZE",
            title="No contract baseline",
            status="submitted",
            ball_in_court="alice",
            response_due_date=_iso_days_ahead(30),
            cost_impact=Decimal("500000.00"),
            currency="EUR",
        )
    )
    await session.flush()

    ranked, _items = await build_delay_risk_board(session, pid)
    assert len(ranked) == 1
    size = next(f for f in ranked[0].top_factors if f.name == "change_size")
    assert size.value == 0.0


@pytest.mark.asyncio
async def test_delay_risk_excludes_closed_changes(session: AsyncSession) -> None:
    pid = await _project(session, contract_value="500000.00")
    session.add_all(
        [
            ChangeOrder(project_id=pid, code="CO-OPEN", title="Open", status="submitted"),
            # executed is a closed change-order status -> excluded from the board.
            ChangeOrder(project_id=pid, code="CO-DONE", title="Done", status="executed"),
        ]
    )
    await session.flush()

    ranked, items_by_id = await build_delay_risk_board(session, pid)
    assert {items_by_id[r.change_id].code for r in ranked} == {"CO-OPEN"}


@pytest.mark.asyncio
async def test_delay_risk_empty_project(session: AsyncSession) -> None:
    pid = await _project(session)
    ranked, items_by_id = await build_delay_risk_board(session, pid)
    assert ranked == []
    assert items_by_id == {}
