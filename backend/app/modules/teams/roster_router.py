# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project-roster routes, mounted under ``/api/v1/teams``.

Kept in its own module and included from :mod:`app.modules.teams.router`, the
way ``resources`` mounts its depth routes. The module loader only looks for a
``router`` attribute in ``router.py``, so this file is reached through that
include and never directly.

The reads check project access here as well as in the service, the way the
team routes do, so a later change to the service cannot leave a roster read
with no gate in front of it. The project and user rows the second check needs
are already in the session's identity map.

Every path is project-scoped (``/project/{project_id}/roster/...``). That is
not decoration: it is what lets the service gate a read or a write on the
project before it touches a row, and what stops a roster id from being usable
across projects. The only exception is the static vocabulary, which describes
the platform rather than any tenant's data.

Like the rest of the module, each collection route is registered in both its
bare and its trailing-slash form because the app runs with
``redirect_slashes=False``.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.teams.roster_schemas import (
    RosterBulkCreate,
    RosterCandidateListResponse,
    RosterMemberListResponse,
    RosterMemberResponse,
    RosterMemberUpdate,
    RosterSummary,
    RosterVocabularyResponse,
    roster_vocabulary,
)
from app.modules.teams.roster_service import RosterService

roster_router = APIRouter()


def _get_service(session: SessionDep) -> RosterService:
    return RosterService(session)


# ── Vocabulary ───────────────────────────────────────────────────────────


@roster_router.get("/roster/vocabulary", response_model=RosterVocabularyResponse)
@roster_router.get(
    "/roster/vocabulary/",
    response_model=RosterVocabularyResponse,
    include_in_schema=False,
)
async def get_roster_vocabulary(user_id: CurrentUserId) -> RosterVocabularyResponse:
    """The trades and site roles a roster line can be written in.

    Static, so it needs authentication but no project scope. The frontend
    renders ``teams.trade.<key>`` / ``teams.siteRole.<key>`` and falls back to
    the English label carried here, so the picker is never empty even before a
    locale has caught up.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return roster_vocabulary()


# ── Roster ───────────────────────────────────────────────────────────────


@roster_router.get("/project/{project_id}/roster", response_model=RosterMemberListResponse)
@roster_router.get(
    "/project/{project_id}/roster/",
    response_model=RosterMemberListResponse,
    include_in_schema=False,
)
async def list_roster(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    include_inactive: bool = Query(default=True),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    service: RosterService = Depends(_get_service),
) -> RosterMemberListResponse:
    """Who is on this project: name, firm, trade, role, dates, tickets.

    This is the read other modules consume when they need to offer "the people
    on this job" rather than every user in the deployment. Gated on project
    access inside the service; a caller who cannot see the project gets 404.

    ``include_inactive`` defaults to true because somebody who has left is
    still part of the record of who was here. ``total`` counts the lines that
    filter matched, so a caller can tell a page from the whole roster.

    ``limit`` reaches 500 rather than the 100 the register routes stop at: a
    caller wanting the roster in one read is the normal case here, not paging
    through it, and a large site can put several hundred people on a job.
    """
    await verify_project_access(project_id, str(user_id or ""), session)
    items, total = await service.list_roster(
        project_id,
        actor_id=user_id,
        include_inactive=include_inactive,
        offset=offset,
        limit=limit,
    )
    return RosterMemberListResponse(items=items, total=total, offset=offset, limit=limit)


@roster_router.get("/project/{project_id}/roster/summary", response_model=RosterSummary)
@roster_router.get(
    "/project/{project_id}/roster/summary/",
    response_model=RosterSummary,
    include_in_schema=False,
)
async def get_roster_summary(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RosterService = Depends(_get_service),
) -> RosterSummary:
    """Headcount, firms, trades, expired tickets and the access gaps."""
    await verify_project_access(project_id, str(user_id or ""), session)
    return await service.summary(project_id, actor_id=user_id)


@roster_router.get("/project/{project_id}/roster/candidates", response_model=RosterCandidateListResponse)
@roster_router.get(
    "/project/{project_id}/roster/candidates/",
    response_model=RosterCandidateListResponse,
    include_in_schema=False,
)
async def list_roster_candidates(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    service: RosterService = Depends(_get_service),
) -> RosterCandidateListResponse:
    """People the platform already knows, for the "add people" picker.

    Platform users and address-book contacts in one list, each flagged with
    whether they are already on the roster. This is what makes assembling a
    team a matter of ticking names rather than retyping them.

    ``total`` is what this route exists to report. The picker used to answer
    with fifty names and no way to say there were more, so somebody whose
    colleague sorted fifty-first read the silence as "the platform does not
    know them" and typed a duplicate contact. The count is real, taken over
    the same filters as the page.

    There is no ``offset`` parameter, and ``offset`` in the body is always 0.
    :meth:`RosterService.list_candidates` explains why a second page over two
    independently ordered sources cannot be served honestly; narrowing ``q`` is
    how a caller reaches the names beyond the first page.
    """
    await verify_project_access(project_id, str(user_id or ""), session)
    items, total = await service.list_candidates(project_id, actor_id=user_id, query=q, limit=limit)
    return RosterCandidateListResponse(items=items, total=total, offset=0, limit=limit)


@roster_router.post(
    "/project/{project_id}/roster",
    response_model=list[RosterMemberResponse],
    status_code=201,
)
@roster_router.post(
    "/project/{project_id}/roster/",
    response_model=list[RosterMemberResponse],
    status_code=201,
    include_in_schema=False,
)
async def add_roster_members(
    project_id: uuid.UUID,
    data: RosterBulkCreate,
    user_id: CurrentUserId,
    service: RosterService = Depends(_get_service),
) -> list[RosterMemberResponse]:
    """Add one or more people to the roster.

    Always a list, because the picker is a multi-select and adding one person
    is the same operation with a shorter list. Anybody already on the roster is
    skipped rather than failing the batch.

    Write gate: project access. A roster line grants nothing on its own - see
    the module docstring. The one field that does change access,
    ``grant_project_access``, is passed through to the membership path, which
    keeps its owner-or-admin gate and refuses the whole call when the caller
    does not clear it.
    """
    return await service.add_members(project_id, data.members, actor_id=user_id)


@roster_router.patch(
    "/project/{project_id}/roster/{member_id}",
    response_model=RosterMemberResponse,
)
@roster_router.patch(
    "/project/{project_id}/roster/{member_id}/",
    response_model=RosterMemberResponse,
    include_in_schema=False,
)
async def update_roster_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    data: RosterMemberUpdate,
    user_id: CurrentUserId,
    service: RosterService = Depends(_get_service),
) -> RosterMemberResponse:
    """Change one roster line. Only the fields the request names are written."""
    return await service.update_member(project_id, member_id, data, actor_id=user_id)


@roster_router.delete("/project/{project_id}/roster/{member_id}", status_code=204)
@roster_router.delete(
    "/project/{project_id}/roster/{member_id}/",
    status_code=204,
    include_in_schema=False,
)
async def remove_roster_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RosterService = Depends(_get_service),
) -> None:
    """Take one person off the roster.

    Any project access they hold is a team membership and is left alone:
    revoking access is a separate decision behind a stricter gate.
    """
    await service.remove_member(project_id, member_id, actor_id=user_id)
