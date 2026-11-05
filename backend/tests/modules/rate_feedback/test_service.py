# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Confirm and reject against a real cost item row (PostgreSQL lane)."""

import uuid
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costs.models import CostItem
from app.modules.rate_feedback.models import RateFeedbackProposal
from app.modules.rate_feedback.schemas import ConfirmRequest
from app.modules.rate_feedback.service import HISTORY_KEY, HOURS_KEY, RateFeedbackService, _linked_item_id
from app.modules.rate_feedback.validators import RateFeedbackError
from tests._pg import transactional_session

USER = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def seed(session: AsyncSession, rate="100", unit="m3"):
    item = CostItem(code="C-1", description="Concrete", unit=unit, rate=rate, currency="EUR")
    session.add(item)
    await session.flush()
    prop = RateFeedbackProposal(
        cost_item_id=item.id,
        unit=unit,
        current_rate=D(rate),
        suggested_rate=D("120"),
        observed_hours_per_unit=D("3.5"),
        project_count=3,
        line_count=4,
        total_quantity=D("40"),
        confidence=D("0.6"),
        project_ids=[],
    )
    session.add(prop)
    await session.flush()
    return item, prop


@pytest.mark.asyncio
async def test_confirm_applies_rate_hours_and_history(session):
    item, prop = await seed(session)
    out = await RateFeedbackService(session).confirm(prop.id, USER, ConfirmRequest())
    assert out.status == "accepted" and out.applied_rate == D("120")
    assert D(item.rate) == D("120")
    assert item.metadata_[HOURS_KEY] == 3.5
    assert item.metadata_[HISTORY_KEY][-1]["from_rate"] == "100"


@pytest.mark.asyncio
async def test_confirm_keeps_the_estimators_own_rate(session):
    item, prop = await seed(session)
    out = await RateFeedbackService(session).confirm(prop.id, USER, ConfirmRequest(rate=D("110"), apply_hours=False))
    assert D(item.rate) == D("110") and out.applied_rate == D("110")
    assert HOURS_KEY not in (item.metadata_ or {})


@pytest.mark.asyncio
async def test_confirm_twice_and_after_manual_edit_is_refused(session):
    item, prop = await seed(session)
    svc = RateFeedbackService(session)
    await svc.confirm(prop.id, USER, ConfirmRequest())
    with pytest.raises(RateFeedbackError) as again:
        await svc.confirm(prop.id, USER, ConfirmRequest())
    assert again.value.code == "not_pending"

    item2, prop2 = await seed(session)
    item2.rate = "105"
    with pytest.raises(RateFeedbackError) as stale:
        await svc.confirm(prop2.id, USER, ConfirmRequest())
    assert stale.value.code == "stale_rate" and item2.rate == "105"


@pytest.mark.asyncio
async def test_reject_leaves_the_cost_item_alone(session):
    item, prop = await seed(session)
    out = await RateFeedbackService(session).reject(prop.id, USER, "one-off site")
    assert out.status == "rejected" and item.rate == "100"
    with pytest.raises(RateFeedbackError):
        await RateFeedbackService(session).reject(prop.id, USER, None)


@pytest.mark.asyncio
async def test_unknown_proposal_is_404(session):
    with pytest.raises(RateFeedbackError) as exc:
        await RateFeedbackService(session).confirm(uuid.uuid4(), USER, ConfirmRequest())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_orders_by_weighted_change_and_flags_warnings(session):
    _, prop = await seed(session)
    prop.variance_pct = D("20")
    page = await RateFeedbackService(session).list_proposals()
    rows = page.items
    assert len(rows) == 1 and rows[0].cost_item_code == "C-1"
    assert "rate_feedback.unit_matches" not in rows[0].warnings
    cut = await RateFeedbackService(session).list_proposals(offset=1, limit=1)
    assert cut.items == [] and cut.total == 1


def test_linked_item_id_tolerates_garbage_metadata():
    good = uuid.uuid4()
    assert _linked_item_id(SimpleNamespace(metadata_={"cost_item_id": str(good)})) == str(good)
    for meta in (None, {}, {"cost_item_id": "nope"}, "x"):
        assert _linked_item_id(SimpleNamespace(metadata_=meta)) is None
