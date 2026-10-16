# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project party routes, mounted under the teams router.

Parties
    GET    /party-registers                                   - Registers parties scope
    GET    /project/{project_id}/parties                      - List parties
    POST   /project/{project_id}/parties                      - Add a party
    PATCH  /project/{project_id}/parties/{party_id}           - Change a party
    DELETE /project/{project_id}/parties/{party_id}           - Remove a party
    GET    /project/{project_id}/parties/me                   - The caller's scope
    GET    /project/{project_id}/parties/members              - Who belongs to which party
    PUT    /project/{project_id}/parties/members/{user_id}    - Bind a member to a party
    DELETE /project/{project_id}/parties/members/{user_id}    - Unbind a member

Record shares
    GET    /project/{project_id}/records/{entity_type}/{entity_id}/parties
    POST   /project/{project_id}/records/{entity_type}/{entity_id}/shares
    DELETE /project/{project_id}/records/{entity_type}/{entity_id}/shares/{party_id}
    PUT    /project/{project_id}/records/{entity_type}/{entity_id}/originator

Every route resolves the caller and routes through :class:`PartyService`,
which applies project access (404), owner or admin for configuration (403
once the caller can see the project), and record visibility (404) for shares.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Path

from app.dependencies import CurrentUserId, SessionDep
from app.modules.teams.party_access import PARTY_SCOPED_REGISTERS
from app.modules.teams.party_schemas import (
    PartyMemberBind,
    PartyMemberResponse,
    PartyRegisterResponse,
    PartyScopeResponse,
    ProjectPartyCreate,
    ProjectPartyResponse,
    ProjectPartyUpdate,
    RecordOriginatorSet,
    RecordPartiesResponse,
    RecordShareCreate,
    validate_party_entity_type,
)
from app.modules.teams.party_service import PartyService

party_router = APIRouter()


def _require_user(user_id: str | None) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _entity_type(value: str) -> str:
    try:
        return validate_party_entity_type(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc


@party_router.get("/party-registers", response_model=list[PartyRegisterResponse])
async def list_party_registers(user_id: CurrentUserId) -> list[PartyRegisterResponse]:
    """The shared registers whose records carry party visibility."""
    _require_user(user_id)
    return [PartyRegisterResponse(key=r.key, label=r.label, module=r.module) for r in PARTY_SCOPED_REGISTERS]


@party_router.get("/project/{project_id}/parties", response_model=list[ProjectPartyResponse])
async def list_parties(
    project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> list[ProjectPartyResponse]:
    """Every party on the project, the host party first."""
    return await PartyService(session).list_parties(project_id, actor_id=_require_user(user_id))


@party_router.post("/project/{project_id}/parties", response_model=ProjectPartyResponse, status_code=201)
async def create_party(
    project_id: uuid.UUID,
    data: ProjectPartyCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ProjectPartyResponse:
    """Add a company to the project (owner or admin)."""
    return await PartyService(session).create_party(project_id, data, actor_id=_require_user(user_id))


@party_router.get("/project/{project_id}/parties/me", response_model=PartyScopeResponse)
async def my_party_scope(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> PartyScopeResponse:
    """Whether the caller is external on this project, and as which party."""
    return await PartyService(session).my_scope(project_id, actor_id=_require_user(user_id))


@party_router.get("/project/{project_id}/parties/members", response_model=list[PartyMemberResponse])
async def list_party_members(
    project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> list[PartyMemberResponse]:
    """Which project member belongs to which party."""
    return await PartyService(session).list_members(project_id, actor_id=_require_user(user_id))


@party_router.put("/project/{project_id}/parties/members/{member_user_id}", response_model=PartyMemberResponse)
async def bind_party_member(
    project_id: uuid.UUID,
    member_user_id: uuid.UUID,
    data: PartyMemberBind,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PartyMemberResponse:
    """Bind a member to a party. 409 when they already belong to another one."""
    return await PartyService(session).bind_member(
        project_id, member_user_id, data.party_id, actor_id=_require_user(user_id)
    )


@party_router.delete("/project/{project_id}/parties/members/{member_user_id}", status_code=204)
async def unbind_party_member(
    project_id: uuid.UUID,
    member_user_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Unbind a member; they become internal again."""
    await PartyService(session).unbind_member(project_id, member_user_id, actor_id=_require_user(user_id))


@party_router.patch("/project/{project_id}/parties/{party_id}", response_model=ProjectPartyResponse)
async def update_party(
    project_id: uuid.UUID,
    party_id: uuid.UUID,
    data: ProjectPartyUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ProjectPartyResponse:
    """Change a party (owner or admin)."""
    return await PartyService(session).update_party(project_id, party_id, data, actor_id=_require_user(user_id))


@party_router.delete("/project/{project_id}/parties/{party_id}", status_code=204)
async def delete_party(
    project_id: uuid.UUID,
    party_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Remove a party, its bindings and its shares (owner or admin)."""
    await PartyService(session).delete_party(project_id, party_id, actor_id=_require_user(user_id))


_RECORD = "/project/{project_id}/records/{entity_type}/{entity_id}"


@party_router.get(_RECORD + "/parties", response_model=RecordPartiesResponse)
async def get_record_parties(
    project_id: uuid.UUID,
    entity_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    entity_type: str = Path(..., max_length=64),
) -> RecordPartiesResponse:
    """Originator and shares of one record."""
    return await PartyService(session).record_parties(
        project_id, _entity_type(entity_type), entity_id, actor_id=_require_user(user_id)
    )


@party_router.post(_RECORD + "/shares", response_model=RecordPartiesResponse)
async def share_record(
    project_id: uuid.UUID,
    entity_id: uuid.UUID,
    data: RecordShareCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    entity_type: str = Path(..., max_length=64),
) -> RecordPartiesResponse:
    """Share one record with a party of the same project."""
    return await PartyService(session).share_record(
        project_id,
        _entity_type(entity_type),
        entity_id,
        data.party_id,
        data.permission,
        actor_id=_require_user(user_id),
    )


@party_router.delete(_RECORD + "/shares/{party_id}", status_code=204)
async def revoke_record_share(
    project_id: uuid.UUID,
    entity_id: uuid.UUID,
    party_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    entity_type: str = Path(..., max_length=64),
) -> None:
    """Withdraw a share. Always audited."""
    await PartyService(session).revoke_share(
        project_id, _entity_type(entity_type), entity_id, party_id, actor_id=_require_user(user_id)
    )


@party_router.put(_RECORD + "/originator", response_model=RecordPartiesResponse)
async def set_record_originator(
    project_id: uuid.UUID,
    entity_id: uuid.UUID,
    data: RecordOriginatorSet,
    user_id: CurrentUserId,
    session: SessionDep,
    entity_type: str = Path(..., max_length=64),
) -> RecordPartiesResponse:
    """Name the party that originated a record (owner or admin)."""
    return await PartyService(session).set_originator(
        project_id, _entity_type(entity_type), entity_id, data.party_id, actor_id=_require_user(user_id)
    )
