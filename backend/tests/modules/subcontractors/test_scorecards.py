# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-backed tests for subcontractor scorecards + prequalification (TOP-30 #20).

Drives the service layer against PostgreSQL so we exercise the real
SQLAlchemy mappings, the ``(subcontractor_id, period)`` unique constraint, and
the idempotent monthly-rating upsert. Each test runs inside an outer
transaction rolled back on teardown (the canonical ``transactional_session``
fixture, function-scoped).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.subcontractors.models  # noqa: F401 — register metadata
from app.modules.subcontractors.models import Subcontractor, SubcontractorRating
from app.modules.subcontractors.service import SubcontractorService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Yield a PostgreSQL session per test, rolled back on teardown."""
    async with transactional_session() as sess:
        yield sess


async def _make_sub(session: AsyncSession, **kwargs: object) -> Subcontractor:
    sub = Subcontractor(
        legal_name=kwargs.pop("legal_name", "ACME Subs"),  # type: ignore[arg-type]
        prequalification_status=kwargs.pop("prequalification_status", "approved"),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(sub)
    await session.flush()
    return sub


@pytest.mark.asyncio
async def test_rating_period_unique_constraint(session: AsyncSession) -> None:
    """TC-10: a second rating row for the same (sub, period) is rejected."""
    sub = await _make_sub(session)
    session.add(SubcontractorRating(subcontractor_id=sub.id, period="2026-05", overall_score=Decimal("80")))
    await session.flush()

    session.add(SubcontractorRating(subcontractor_id=sub.id, period="2026-05", overall_score=Decimal("90")))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_compute_monthly_rating_creates_then_upserts(session: AsyncSession) -> None:
    """TC-5/10: first compute inserts; recompute updates the same row."""
    sub = await _make_sub(session)
    svc = SubcontractorService(session)

    first = await svc.compute_monthly_rating(sub.id, "2026-05")
    assert first is not None
    # No source rows + no event basis -> all-clean 100 score.
    assert first.overall_score == Decimal("100.00")

    second = await svc.compute_monthly_rating(sub.id, "2026-05")
    assert second is not None
    assert second.id == first.id

    rows = await svc.ratings.list_for_subcontractor(sub.id)
    assert len([r for r in rows if r.period == "2026-05"]) == 1


@pytest.mark.asyncio
async def test_compute_monthly_rating_rolls_up_event_basis(session: AsyncSession) -> None:
    """A period whose basis carries event counters scores below 100."""
    sub = await _make_sub(session)
    svc = SubcontractorService(session)

    # Simulate the event subscribers having accumulated 2 NCRs this month.
    await svc.bump_rating_from_event(sub.id, kind="ncr", period="2026-06")
    await svc.bump_rating_from_event(sub.id, kind="ncr", period="2026-06")

    rating = await svc.compute_monthly_rating(sub.id, "2026-06")
    assert rating is not None
    # 2 NCRs (penalty 15) -> quality 70, so overall < 100.
    assert rating.quality_score == Decimal("70.00")
    assert rating.overall_score < Decimal("100")

    # The sub's rolled-up score tracks the new overall.
    refreshed = await svc.subs.get_by_id(sub.id)
    assert refreshed is not None
    assert refreshed.rating_score == rating.overall_score


@pytest.mark.asyncio
async def test_submit_prequal_require_complete_blocks_partial(session: AsyncSession) -> None:
    """TC-14: a partial questionnaire with require_complete raises 400."""
    from fastapi import HTTPException

    sub = await _make_sub(session, prequalification_status="pending")
    svc = SubcontractorService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.submit_prequal(sub.id, {"license_current": "yes"}, require_complete=True)
    assert exc.value.status_code == 400
    assert isinstance(exc.value.detail, dict)
    assert "missing" in exc.value.detail


@pytest.mark.asyncio
async def test_submit_prequal_full_questionnaire_scores(session: AsyncSession) -> None:
    """A complete questionnaire is accepted and scored server-side."""
    sub = await _make_sub(session, prequalification_status="pending")
    svc = SubcontractorService(session)

    answers = {
        "license_current": "yes",
        "wcb_coverage": "yes",
        "insurance_current": "yes",
        "safety_program": "yes",
        "references_available": "yes",
        "financial_statements": "yes",
        "has_open_incidents": "no",
        "has_unpaid_liens": "no",
    }
    updated = await svc.submit_prequal(sub.id, answers, require_complete=True)
    assert updated.prequal_score == 100
    assert updated.prequal_completed_at is not None


@pytest.mark.asyncio
async def test_prequal_view_roundtrip(session: AsyncSession) -> None:
    """prequal_view reflects the stored answers + recomputed score."""
    sub = await _make_sub(session, prequalification_status="pending")
    svc = SubcontractorService(session)
    answers = {
        "license_current": "yes",
        "wcb_coverage": "yes",
        "insurance_current": "yes",
        "safety_program": "yes",
        "references_available": "yes",
        "financial_statements": "yes",
        "has_open_incidents": "yes",  # wrong
        "has_unpaid_liens": "yes",  # wrong
    }
    await svc.submit_prequal(sub.id, answers)
    view = await svc.prequal_view(sub.id)
    assert view["computed_score"] == 75
    assert view["missing_required"] == []
    assert view["approval_threshold"] == 70


@pytest.mark.asyncio
async def test_award_eligibility_blocks_rejected(session: AsyncSession) -> None:
    """TC-7: award eligibility reports a rejected sub as not awardable."""
    sub = await _make_sub(session, prequalification_status="rejected")
    svc = SubcontractorService(session)
    result = await svc.subcontractor_award_eligibility(sub.id)
    assert result.blocked is True
    assert "prequalification_rejected" in result.reasons
