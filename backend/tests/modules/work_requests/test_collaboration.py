# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Cross-team collaboration: the ball in court, hand-offs, comments with
mentions, and who hears about what."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import day, make_project, make_user, raise_request, seeded


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _bells(session: AsyncSession, user) -> list[Notification]:
    rows = await session.execute(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_raising_tells_the_department_not_the_raiser(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    lead = await make_user(session, name="Lead Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(
        session, depts["workshop"], {"lead_user_id": str(lead.id), "member_ids": [str(fitter.id), str(pm.id)]}
    )
    req = await raise_request(session, project=proj, user=pm, due_date=day(10))
    for person in (lead, fitter):
        bells = await _bells(session, person)
        assert len(bells) == 1
        assert req.reference in bells[0].title_key
        assert bells[0].entity_id == str(req.id)
        assert bells[0].action_url == f"/work-requests/{req.id}"
    assert await _bells(session, pm) == [], "the raiser is a member too, but never rings their own bell"


@pytest.mark.asyncio
async def test_needs_info_and_answer_flip_the_ball(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(session, depts["workshop"], {"member_ids": [str(fitter.id)]})
    req = await raise_request(session, project=proj, user=pm)

    with pytest.raises(service.ConflictError):
        await service.answer(session, req, "nothing to answer", user_id=str(pm.id), can_manage=False)

    await service.needs_info(
        session, req, "Which fault level - 25kA or 36kA?", user_id=str(fitter.id), can_manage=False
    )
    assert req.ball_in_court == "requester"
    assert req.needs_info == "Which fault level - 25kA or 36kA?"
    pm_bells = await _bells(session, pm)
    assert len(pm_bells) == 1 and "needs information" in pm_bells[0].title_key
    assert pm_bells[0].body_key == "Which fault level - 25kA or 36kA?"

    await service.answer(session, req, "36kA - see the SLD rev C", user_id=str(pm.id), can_manage=False)
    assert req.ball_in_court == "department"
    assert req.needs_info is None
    fitter_bells = await _bells(session, fitter)
    assert any("answered" in b.title_key for b in fitter_bells)

    kinds = [c["kind"] for c in await service.list_comments(session, req, include_system=False)]
    assert kinds == ["needs_info", "answer"]
    payload = await service.payload(session, req)
    assert payload["comment_count"] == 2
    assert payload["ball_in_court"] == "department"


@pytest.mark.asyncio
async def test_a_stranger_cannot_ask_for_information(session: AsyncSession) -> None:
    pm = await make_user(session)
    fitter = await make_user(session, name="Fitter Example")
    stranger = await make_user(session, name="Stranger Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(session, depts["workshop"], {"member_ids": [str(fitter.id)]})
    req = await raise_request(session, project=proj, user=pm)
    with pytest.raises(service.NotPermitted):
        await service.needs_info(session, req, "?", user_id=str(stranger.id), can_manage=False)


@pytest.mark.asyncio
async def test_handoff_creates_a_child_the_parent_waits_on(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    drafter = await make_user(session, name="Drafter Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(session, depts["drafting"], {"member_ids": [str(drafter.id)]})
    board = await raise_request(
        session,
        project=proj,
        user=pm,
        links=[{"label": "SLD", "url": "https://example.com/sld.pdf"}],
        due_date=day(30),
    )
    child = await service.handoff(
        session,
        board,
        department="drafting",
        request_type="drafting_only",
        title="GA + schematics for MSB-01",
        due_date=day(14),
        user_id=str(pm.id),
        can_manage=False,
    )
    assert child.reference == "WR-DRF-000001"
    assert child.parent_id == board.id
    assert child.project_id == board.project_id
    assert child.links == board.links, "copy_links carries the drawings across"
    assert str(child.id) in board.depends_on_ids

    parent_payload = await service.payload(session, board)
    child_payload = await service.payload(session, child)
    assert [d["reference"] for d in parent_payload["depends_on"]] == ["WR-DRF-000001"]
    assert [c["reference"] for c in parent_payload["children"]] == ["WR-DRF-000001"]
    assert child_payload["parent_reference"] == board.reference
    assert [b["reference"] for b in child_payload["blocks"]] == [board.reference]
    assert (await _bells(session, drafter))[0].title_key.startswith("WR-DRF-000001 handed to Drafting")
    log = [line["what"] for line in await service.activity(session, board)]
    assert "Handed off to Drafting" in log


@pytest.mark.asyncio
async def test_comments_mention_people_and_ring_only_them(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    eng = await make_user(session, name="Engineer Example")
    other = await make_user(session, name="Other Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    comment = await service.add_comment(
        session, req, body="Can you check the CT ratios?", mention_ids=[str(eng.id), str(pm.id)], user_id=str(pm.id)
    )
    assert comment.kind == "comment"
    assert comment.author_name == "PM Example"
    assert len(await _bells(session, eng)) == 1
    assert await _bells(session, other) == []
    assert await _bells(session, pm) == [], "mentioning yourself is not a bell"
    with pytest.raises(service.WorkRequestError):
        await service.add_comment(session, req, body="   ", mention_ids=[], user_id=str(pm.id))
    with pytest.raises(service.WorkRequestError):
        await service.add_comment(session, req, body="hi", mention_ids=[str(uuid.uuid4())], user_id=str(pm.id))


@pytest.mark.asyncio
async def test_assignment_rings_the_newly_assigned(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    a = await make_user(session, name="A Example")
    b = await make_user(session, name="B Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    await service.assign(
        session, req, assignee_ids=[str(a.id)], responsible_user_id=None, user_id=str(pm.id), can_manage=False
    )
    await service.assign(
        session,
        req,
        assignee_ids=[str(a.id), str(b.id)],
        responsible_user_id=str(a.id),
        user_id=str(pm.id),
        can_manage=False,
    )
    assert len(await _bells(session, a)) == 2, "assigned, then made responsible"
    assert len(await _bells(session, b)) == 1
    payload = await service.payload(session, req)
    assert [x["name"] for x in payload["assignees"]] == ["A Example", "B Example"]
    assert payload["responsible"] == {"id": str(a.id), "name": "A Example"}
    with pytest.raises(service.WorkRequestError):
        await service.assign(
            session, req, assignee_ids=["not-a-user"], responsible_user_id=None, user_id=str(pm.id), can_manage=False
        )


@pytest.mark.asyncio
async def test_stage_and_completion_ring_the_requester(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    await service.move_stage(session, req, "build", user_id=str(fitter.id), can_manage=False)
    await service.move_stage(session, req, "delivered", user_id=str(fitter.id), can_manage=False)
    titles = [b.title_key for b in await _bells(session, pm)]
    assert any("moved to build" in t for t in titles), titles
    assert any("is complete" in t for t in titles), titles
