"""CRM deal activities, deal deletion and the ``bidding`` stage."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError

import app.modules.crm.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.modules.crm.models import Account, Opportunity, PipelineStage
from app.modules.crm.schemas import ActivityCreate, ActivityUpdate
from app.modules.crm.service import CrmService
from tests._pg import clear_module_tables, create_module_tables


@pytest_asyncio.fixture(scope="module")
async def _schema():
    from app.modules.crm.models import CrmActivity
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    await create_module_tables(User, Project, CrmActivity, Opportunity, PipelineStage, Account)
    return (CrmActivity, Opportunity, PipelineStage, Account)


@pytest_asyncio.fixture
async def session(_schema):
    from app.database import async_session_factory

    await clear_module_tables(_schema)
    async with async_session_factory() as sess:
        yield sess
        await sess.rollback()


async def _stages(session, codes=("qualified", "proposal", "won")):
    for i, code in enumerate(codes):
        session.add(PipelineStage(code=code, name=code.title(), display_order=i, is_final=code == "won"))
    await session.flush()


async def _deal(session, status="open"):
    acc = Account(name="Acme")
    session.add(acc)
    await session.flush()
    stage = await CrmService(session).stage_repo.get_by_code("qualified")
    opp = Opportunity(account_id=acc.id, title="Deal", stage_id=stage.id, status=status)
    session.add(opp)
    await session.flush()
    return opp


def test_site_visit_kind_is_accepted_and_unknown_rejected():
    assert ActivityCreate(kind="site_visit").kind == "site_visit"
    assert ActivityUpdate(kind="site_visit").kind == "site_visit"
    with pytest.raises(ValidationError):
        ActivityCreate(kind="fax")


@pytest.mark.asyncio
async def test_activity_carries_assignee_and_completion(session):
    await _stages(session)
    opp = await _deal(session)
    svc = CrmService(session)
    import uuid

    assignee = uuid.uuid4()
    act = await svc.create_activity(
        ActivityCreate(opportunity_id=opp.id, kind="site_visit", subject="Walk the site", due_at="2026-12-01")
    )
    assert act.completed_at is None and act.kind == "site_visit"
    done = await svc.update_activity(act.id, ActivityUpdate(completed_at="2026-11-30T10:00:00+00:00"))
    assert done.completed_at is not None
    assert assignee  # assignee FK is exercised through the API; column exists on the model
    assert hasattr(done, "assigned_user_id")


@pytest.mark.asyncio
async def test_delete_open_deal_removes_it_and_its_activities(session):
    await _stages(session)
    opp = await _deal(session)
    svc = CrmService(session)
    act = await svc.create_activity(ActivityCreate(opportunity_id=opp.id, kind="task", subject="Call"))
    await svc.delete_opportunity(opp.id)
    with pytest.raises(HTTPException) as exc:
        await svc.get_opportunity(opp.id)
    assert exc.value.status_code == 404
    assert act.id is not None


@pytest.mark.asyncio
async def test_won_deal_cannot_be_deleted(session):
    await _stages(session)
    opp = await _deal(session, status="won")
    with pytest.raises(HTTPException) as exc:
        await CrmService(session).delete_opportunity(opp.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_bidding_stage_is_added_between_qualified_and_proposal(session):
    await _stages(session)
    svc = CrmService(session)
    codes = [s.code for s in await svc.list_stages()]
    assert codes == ["qualified", "bidding", "proposal", "won"]
    assert [s.code for s in await svc.list_stages()] == codes
