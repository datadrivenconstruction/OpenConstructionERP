# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The status machine and the board, each rail tested with the failure it
exists to prevent: a status skipped, a request closed by the wrong
person, a closing stage that did not complete, a first move that did not
start the work, an edit on a closed record."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import make_project, make_user, raise_request, seeded


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _set(session, req, status, *, user, manage=False, **kw):
    return await service.update_request(session, req, {"status": status, **kw}, user_id=str(user.id), can_manage=manage)


@pytest.mark.asyncio
async def test_the_happy_path_walks_every_state(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    assert req.status == "submitted"
    assert req.ball_in_court == "department"
    for status in ("accepted", "in_progress", "on_hold", "in_progress", "review", "complete"):
        await _set(session, req, status, user=pm)
        assert req.status == status
    assert req.ball_in_court == "requester", "complete hands the ball back to the requester"
    await _set(session, req, "closed", user=pm)
    assert req.status == "closed"
    assert req.closed_at is not None
    assert service.allowed_transitions(req) == []


@pytest.mark.asyncio
async def test_an_illegal_move_says_what_is_allowed(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    with pytest.raises(service.TransitionError) as exc:
        await _set(session, req, "complete", user=pm)
    assert exc.value.allowed == ["accepted", "cancelled"]
    assert req.status == "submitted", "a refused move changes nothing"
    with pytest.raises(service.WorkRequestError):
        await _set(session, req, "finished", user=pm)


@pytest.mark.asyncio
async def test_cancelled_from_any_open_state_but_never_from_closed(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    for path in (("draft",), ("submitted",), ("accepted",), ("accepted", "in_progress", "review")):
        req = await raise_request(session, project=proj, user=pm, draft=path[0] == "draft")
        for status in path:
            if status not in ("draft", "submitted"):
                await _set(session, req, status, user=pm)
        await _set(session, req, "cancelled", user=pm)
        assert req.status == "cancelled"
    done = await raise_request(session, project=proj, user=pm)
    await _set(session, done, "accepted", user=pm)
    await _set(session, done, "in_progress", user=pm)
    await _set(session, done, "complete", user=pm)
    await _set(session, done, "closed", user=pm)
    with pytest.raises(service.TransitionError):
        await _set(session, done, "cancelled", user=pm)


@pytest.mark.asyncio
async def test_only_the_requester_or_a_manager_closes(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    boss = await make_user(session, name="Boss Example", role="manager")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(session, depts["workshop"], {"member_ids": [str(fitter.id)]})
    req = await raise_request(session, project=proj, user=pm)
    await service.move_stage(session, req, "build", user_id=str(fitter.id), can_manage=False)
    await service.move_stage(session, req, "delivered", user_id=str(fitter.id), can_manage=False)
    assert req.status == "complete"
    with pytest.raises(service.NotPermitted):
        await _set(session, req, "closed", user=fitter)
    assert req.status == "complete"
    await _set(session, req, "closed", user=boss, manage=True)
    assert req.status == "closed"


@pytest.mark.asyncio
async def test_a_closing_stage_completes_and_the_first_move_starts_the_work(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    assert req.stage == "requested", "raised into the department's first stage"
    assert req.stage_history[0]["note"] == "Raised"

    await service.move_stage(session, req, "drawings_received", note="Rev B", user_id=str(pm.id), can_manage=False)
    assert req.status == "in_progress", "the first board move IS the department starting"
    assert req.stage_history[-1] == {
        **req.stage_history[-1],
        "stage": "drawings_received",
        "by_id": str(pm.id),
        "by_name": "Alex Example",
        "note": "Rev B",
    }
    await service.move_stage(session, req, "delivered", user_id=str(pm.id), can_manage=False)
    assert req.status == "complete"
    assert req.ball_in_court == "requester"
    # The activity log recorded the TRUE previous status, not a faked one.
    log = await service.activity(session, req)
    assert any(line["what"] == "Status submitted → in_progress" for line in log), [line["what"] for line in log]
    assert any(line["what"] == "Status in_progress → complete" for line in log)


@pytest.mark.asyncio
async def test_board_refusals(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    with pytest.raises(service.WorkRequestError):
        await service.move_stage(session, req, "painting", user_id=str(pm.id), can_manage=False)
    with pytest.raises(service.ConflictError):
        await service.move_stage(session, req, "requested", user_id=str(pm.id), can_manage=False)
    await _set(session, req, "cancelled", user=pm)
    with pytest.raises(service.ConflictError):
        await service.move_stage(session, req, "build", user_id=str(pm.id), can_manage=False)
    with pytest.raises(service.ConflictError):
        await service.update_request(session, req, {"title": "renamed"}, user_id=str(pm.id), can_manage=False)


@pytest.mark.asyncio
async def test_a_stranger_cannot_change_somebody_elses_request(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    stranger = await make_user(session, name="Stranger Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(session, depts["workshop"], {"member_ids": [str(fitter.id)]})
    req = await raise_request(session, project=proj, user=pm)
    with pytest.raises(service.NotPermitted):
        await service.update_request(session, req, {"title": "hijacked"}, user_id=str(stranger.id), can_manage=False)
    with pytest.raises(service.NotPermitted):
        await service.move_stage(session, req, "build", user_id=str(stranger.id), can_manage=False)
    # The requester may edit; the department may move.
    await service.update_request(session, req, {"title": "MSB-01 rev B"}, user_id=str(pm.id), can_manage=False)
    await service.move_stage(session, req, "build", user_id=str(fitter.id), can_manage=False)
    # A manager may do anything.
    await service.move_stage(session, req, "wiring", user_id=str(stranger.id), can_manage=True)


@pytest.mark.asyncio
async def test_an_unconfigured_department_is_open_to_update_holders(session: AsyncSession) -> None:
    """A fresh install has no rosters yet; the boards must still move."""
    pm = await make_user(session)
    colleague = await make_user(session, name="Colleague Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    await service.move_stage(session, req, "build", user_id=str(colleague.id), can_manage=False)
    assert req.stage == "build"


@pytest.mark.asyncio
async def test_draft_then_submit(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    # Make a field required so the draft path can be told apart.
    types = [dict(t) for t in depts["workshop"].request_types]
    for t in types:
        if t["key"] == "switchboard":
            t["fields"] = [{**f, "required": f["key"] == "factory_cost_centre"} for f in t["fields"]]
    await service.update_department(session, depts["workshop"], {"request_types": types})
    with pytest.raises(service.WorkRequestError) as exc:
        await raise_request(session, project=proj, user=pm)
    assert "Factory cost centre" in str(exc.value)
    draft = await raise_request(session, project=proj, user=pm, draft=True)
    assert draft.status == "draft" and draft.ball_in_court == "requester"
    await _set(session, draft, "submitted", user=pm)
    assert draft.ball_in_court == "department"
