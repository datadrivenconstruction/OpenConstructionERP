# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Teams API routes.

Teams
    GET    /                                    - List teams (project_id query)
    GET    /project/{project_id}                - List teams for a project
    POST   /                                    - Create a team
    PATCH  /{team_id}                           - Update a team
    DELETE /{team_id}                           - Delete a team

Members
    GET    /{team_id}/members                   - List members (with names)
    POST   /{team_id}/members                   - Add a member
    PATCH  /{team_id}/members/{member_user_id}  - Change a member's role
    DELETE /{team_id}/members/{member_user_id}  - Remove a member

Record restrictions
    GET    /entity-types                        - Which record kinds can be restricted
    GET    /{team_id}/visibility                - Records restricted to this team
    POST   /{team_id}/visibility                - Restrict a record to this team
    DELETE /{team_id}/visibility/{entity_type}/{entity_id}
                                                - Lift this team's restriction
    GET    /project/{project_id}/visibility/{entity_type}/{entity_id}
                                                - Who can see one record
    PUT    /project/{project_id}/visibility/{entity_type}/{entity_id}
                                                - Set the whole team list at once
    GET    /project/{project_id}/restricted     - The project restriction register
    GET    /project/{project_id}/access-matrix  - Who can still open what
    GET    /project/{project_id}/validate       - Run the teams rule set

Project roster (see :mod:`app.modules.teams.roster_router`)
    GET    /roster/vocabulary                   - Trades and site roles
    GET    /project/{project_id}/roster         - Who is on this job
    GET    /project/{project_id}/roster/summary - What the roster adds up to
    GET    /project/{project_id}/roster/candidates
                                                - Users and contacts to pick from
    POST   /project/{project_id}/roster         - Add people
    PATCH  /project/{project_id}/roster/{member_id}
    DELETE /project/{project_id}/roster/{member_id}

Authorisation
~~~~~~~~~~~~~
Every route resolves the caller before it touches data, and every one of them
routes through the service's two gates:

* Reads require project access (owner, system admin, or a member). Denial and
  "no such project" are both 404, so an id cannot be walked.
* Writes require project ownership or system-admin. A caller who can see the
  project gets 403 (they already know it exists, so nothing leaks); a caller
  who cannot gets 404.

A team, a membership or a restriction belonging to another project always
answers 404 rather than 403, for the same reason.

The app runs with ``redirect_slashes=False`` (see ``app/main.py``), so each
collection route is registered in both its bare and its trailing-slash form,
with the alias kept out of the schema.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.teams.roster_router import roster_router
from app.modules.teams.schemas import (
    AccessMatrixResponse,
    AddMemberRequest,
    EntityTypeResponse,
    EntityVisibilityResponse,
    EntityVisibilityState,
    MembershipResponse,
    RestrictedEntityRow,
    SetEntityVisibilityRequest,
    TeamCreate,
    TeamResponse,
    TeamsValidationReport,
    TeamUpdate,
    TeamVisibilityGrantRequest,
    UpdateMemberRoleRequest,
    entity_type_catalogue,
)
from app.modules.teams.service import TeamService

router = APIRouter(tags=["teams"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> TeamService:
    return TeamService(session)


async def _gate_team_admin(
    team_id: uuid.UUID,
    user_id: str | None,
    service: TeamService,
    session: SessionDep,
) -> None:
    """Resolve a team and gate the caller on the project that owns it.

    For an HTTP caller the service is the gate that does the enforcing, and it
    reaches the same verdict on its own: these two layers are behaviourally
    indistinguishable from the wire, which was measured rather than assumed.
    What this adds is structural. ``test_idor_router_guards`` pins that every
    single-resource mutation resolves its parent project at the route, so a
    later refactor of the service cannot quietly become the only thing
    standing between a caller and someone else's data. The team-scoped reads
    call it for the same reason; despite the name it checks project access,
    not ownership, so a plain member passes.

    A team id that names nothing and a team in someone else's project both
    answer "Team not found", so the id cannot be probed for existence.
    Ownership stays with the service, which answers 403 only once the caller
    has already proved they can see the project.
    """
    team = await service.get_team(team_id)
    try:
        await verify_project_access(team.project_id, str(user_id or ""), session)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Team not found") from exc
        raise


# ── Catalogue ────────────────────────────────────────────────────────────


@router.get("/entity-types", response_model=list[EntityTypeResponse])
@router.get("/entity-types/", response_model=list[EntityTypeResponse], include_in_schema=False)
async def list_entity_types(user_id: CurrentUserId) -> list[EntityTypeResponse]:
    """The record kinds a project can restrict to a team.

    Static catalogue, so it needs authentication but no project scope: it
    describes the platform, not any tenant's data. ``enforced`` says whether a
    consumer actually subtracts that kind yet, so the UI can label a
    restriction honestly instead of implying a lock that is not wired.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return entity_type_catalogue()


# ── Teams ────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[TeamResponse])
@router.get("", response_model=list[TeamResponse], include_in_schema=False)
async def list_teams_by_query(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    include_inactive: bool = Query(default=False),
    service: TeamService = Depends(_get_service),
) -> list[TeamResponse]:
    """List teams for a project (query-param style), with counts.

    IDOR-gated on the parent project at the route and inside the service: a
    caller may only list teams of a project they own, admin, or belong to.
    Anything else is 404.
    """
    await verify_project_access(project_id, str(user_id or ""), session)
    return await service.list_teams_detailed(
        project_id,
        actor_id=user_id,
        include_inactive=include_inactive,
    )


@router.get("/project/{project_id}", response_model=list[TeamResponse])
@router.get("/project/{project_id}/", response_model=list[TeamResponse], include_in_schema=False)
async def list_teams(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    include_inactive: bool = Query(default=False),
    service: TeamService = Depends(_get_service),
) -> list[TeamResponse]:
    """List teams for a project (path style). Same gate as the query form."""
    await verify_project_access(project_id, str(user_id or ""), session)
    return await service.list_teams_detailed(
        project_id,
        actor_id=user_id,
        include_inactive=include_inactive,
    )


@router.post("/", response_model=TeamResponse, status_code=201)
@router.post("", response_model=TeamResponse, status_code=201, include_in_schema=False)
async def create_team(
    data: TeamCreate,
    user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> TeamResponse:
    """Create a new team within a project.

    RBAC: project owner or system admin. A team is the container memberships
    live in, and a membership grants project access, so creating one is a
    write on the project's access model.
    """
    team = await service.create_team(data, actor_id=user_id)
    return TeamResponse.model_validate(team)


@router.patch("/{team_id}", response_model=TeamResponse)
@router.patch("/{team_id}/", response_model=TeamResponse, include_in_schema=False)
async def update_team(
    team_id: uuid.UUID,
    data: TeamUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TeamService = Depends(_get_service),
) -> TeamResponse:
    """Update team fields (project owner or system admin).

    Gated on the owning project at the route as well as in the service, so a
    team in another project answers 404 either way.
    """
    await _gate_team_admin(team_id, user_id, service, session)
    updated = await service.update_team(team_id, data, actor_id=user_id)
    return TeamResponse.model_validate(updated)


@router.delete("/{team_id}", status_code=204)
@router.delete("/{team_id}/", status_code=204, include_in_schema=False)
async def delete_team(
    team_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TeamService = Depends(_get_service),
) -> None:
    """Delete a team, its memberships and its restrictions.

    Records that were restricted only to this team become open to every
    project member again. That widens their audience within the project but
    cannot reach anyone outside it.

    Gated on the owning project at the route as well as in the service, so a
    team in another project answers 404 either way.
    """
    await _gate_team_admin(team_id, user_id, service, session)
    await service.delete_team(team_id, actor_id=user_id)


# ── Members ──────────────────────────────────────────────────────────────


@router.get("/{team_id}/members", response_model=list[MembershipResponse])
@router.get("/{team_id}/members/", response_model=list[MembershipResponse], include_in_schema=False)
async def list_members(
    team_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TeamService = Depends(_get_service),
) -> list[MembershipResponse]:
    """List members of a team, with email and display name resolved.

    Read gate: project access. A team in a project the caller cannot reach
    answers 404.
    """
    await _gate_team_admin(team_id, user_id, service, session)
    return await service.list_members_detailed(team_id, actor_id=user_id)


@router.post("/{team_id}/members", response_model=MembershipResponse, status_code=201)
@router.post(
    "/{team_id}/members/",
    response_model=MembershipResponse,
    status_code=201,
    include_in_schema=False,
)
async def add_member(
    team_id: uuid.UUID,
    data: AddMemberRequest,
    user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> MembershipResponse:
    """Add a user to a team.

    RBAC: project owner or system admin only. This is the escalation-critical
    route in the module - a membership row is what
    :func:`app.dependencies.verify_project_access` reads to grant project
    access, so a plain member being able to call it would let them hand an
    outsider a project. ELEVATED roles are gated a second time on top.
    """
    membership = await service.add_member(team_id, data, actor_id=user_id)
    return MembershipResponse.model_validate(membership)


@router.patch("/{team_id}/members/{member_user_id}", response_model=MembershipResponse)
@router.patch(
    "/{team_id}/members/{member_user_id}/",
    response_model=MembershipResponse,
    include_in_schema=False,
)
async def update_member_role(
    team_id: uuid.UUID,
    member_user_id: uuid.UUID,
    data: UpdateMemberRoleRequest,
    user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> MembershipResponse:
    """Change a member's role inside a team.

    Same gate as adding one, so an in-place promotion into an ELEVATED role
    cannot be used to route around the add-time check.
    """
    membership = await service.update_member_role(
        team_id,
        member_user_id,
        data.role,
        actor_id=user_id,
    )
    return MembershipResponse.model_validate(membership)


@router.delete("/{team_id}/members/{member_user_id}", status_code=204)
@router.delete("/{team_id}/members/{member_user_id}/", status_code=204, include_in_schema=False)
async def remove_member(
    team_id: uuid.UUID,
    member_user_id: uuid.UUID,
    user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> None:
    """Remove a user from a team.

    ``user_id`` is the caller (from the JWT); ``member_user_id`` is the
    membership being revoked.
    """
    await service.remove_member(team_id, member_user_id, actor_id=user_id)


# ── Record restrictions ──────────────────────────────────────────────────


@router.get("/{team_id}/visibility", response_model=list[EntityVisibilityResponse])
@router.get(
    "/{team_id}/visibility/",
    response_model=list[EntityVisibilityResponse],
    include_in_schema=False,
)
async def list_team_visibility(
    team_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TeamService = Depends(_get_service),
) -> list[EntityVisibilityResponse]:
    """The records restricted to this team (read gate: project access)."""
    await _gate_team_admin(team_id, user_id, service, session)
    rows = await service.list_team_visibility(team_id, actor_id=user_id)
    return [EntityVisibilityResponse.model_validate(row) for row in rows]


@router.post("/{team_id}/visibility", response_model=EntityVisibilityResponse, status_code=201)
@router.post(
    "/{team_id}/visibility/",
    response_model=EntityVisibilityResponse,
    status_code=201,
    include_in_schema=False,
)
async def grant_visibility(
    team_id: uuid.UUID,
    data: TeamVisibilityGrantRequest,
    user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> EntityVisibilityResponse:
    """Restrict one record to this team.

    Write gate: project owner or system admin. The first restriction on a
    record narrows it from "every project member" to "the named teams"; it
    never opens a record to anyone who could not already reach the project.
    """
    row = await service.grant_visibility(
        data.entity_type,
        data.entity_id,
        team_id,
        actor_id=user_id,
    )
    return EntityVisibilityResponse.model_validate(row)


@router.delete("/{team_id}/visibility/{entity_type}/{entity_id}", status_code=204)
@router.delete(
    "/{team_id}/visibility/{entity_type}/{entity_id}/",
    status_code=204,
    include_in_schema=False,
)
async def revoke_visibility(
    team_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
    user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> None:
    """Drop this team from a record's restriction list."""
    await service.revoke_visibility(entity_type, entity_id, team_id, actor_id=user_id)


@router.get(
    "/project/{project_id}/visibility/{entity_type}/{entity_id}",
    response_model=EntityVisibilityState,
)
@router.get(
    "/project/{project_id}/visibility/{entity_type}/{entity_id}/",
    response_model=EntityVisibilityState,
    include_in_schema=False,
)
async def describe_entity_visibility(
    project_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TeamService = Depends(_get_service),
) -> EntityVisibilityState:
    """Who can currently see one record.

    Read gate: project access. Reporting that a record is restricted, and to
    which teams, tells a project member nothing about a project they cannot
    already reach, and nothing about the record's contents.
    """
    await verify_project_access(project_id, str(user_id or ""), session)
    return await service.describe_entity_visibility(
        project_id,
        entity_type,
        entity_id,
        actor_id=user_id,
    )


@router.put(
    "/project/{project_id}/visibility/{entity_type}/{entity_id}",
    response_model=EntityVisibilityState,
)
@router.put(
    "/project/{project_id}/visibility/{entity_type}/{entity_id}/",
    response_model=EntityVisibilityState,
    include_in_schema=False,
)
async def set_entity_visibility(
    project_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
    data: SetEntityVisibilityRequest,
    user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> EntityVisibilityState:
    """Replace the whole set of teams that may see one record.

    An empty ``team_ids`` lifts the restriction. Every id must name a team of
    this project; one that does not answers 404, exactly as a nonexistent team
    does, so the route cannot be used to probe another project's team ids.
    """
    return await service.set_entity_visibility(
        project_id,
        entity_type,
        entity_id,
        data.team_ids,
        actor_id=user_id,
    )


@router.get("/project/{project_id}/restricted", response_model=list[RestrictedEntityRow])
@router.get(
    "/project/{project_id}/restricted/",
    response_model=list[RestrictedEntityRow],
    include_in_schema=False,
)
async def list_restricted_entities(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    entity_type: str | None = Query(default=None),
    service: TeamService = Depends(_get_service),
) -> list[RestrictedEntityRow]:
    """The project's restriction register: every record that is not open."""
    await verify_project_access(project_id, str(user_id or ""), session)
    return await service.list_restricted_entities(
        project_id,
        entity_type=entity_type,
        actor_id=user_id,
    )


@router.get("/project/{project_id}/access-matrix", response_model=AccessMatrixResponse)
@router.get(
    "/project/{project_id}/access-matrix/",
    response_model=AccessMatrixResponse,
    include_in_schema=False,
)
async def get_access_matrix(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TeamService = Depends(_get_service),
) -> AccessMatrixResponse:
    """Who on this project can still open the restricted records, and who cannot."""
    await verify_project_access(project_id, str(user_id or ""), session)
    return await service.build_access_matrix(project_id, actor_id=user_id)


# ── Validation ───────────────────────────────────────────────────────────


@router.get("/project/{project_id}/validate", response_model=TeamsValidationReport)
@router.get(
    "/project/{project_id}/validate/",
    response_model=TeamsValidationReport,
    include_in_schema=False,
)
async def validate_project_teams(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TeamService = Depends(_get_service),
) -> TeamsValidationReport:
    """Run the ``teams`` rule set over one project's access configuration.

    Read gate: project access, enforced before any row is read. The findings
    describe the project's own teams and restrictions, so they disclose
    nothing a member cannot already list.
    """
    await verify_project_access(project_id, str(user_id or ""), session)
    return await service.validate_project(project_id, actor_id=user_id)


# ── Roster ───────────────────────────────────────────────────────────────
#
# Included last on purpose. FastAPI matches routes in registration order, and
# every roster path is either project-scoped or begins with the literal
# "roster", so none of them can be swallowed by the ``/{team_id}`` patterns
# declared above - checked segment by segment rather than assumed.
router.include_router(roster_router)
