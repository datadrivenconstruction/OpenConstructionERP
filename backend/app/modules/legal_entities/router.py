# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legal entity and branch API routes.

Mounted at ``/api/v1/legal_entities/`` by the module loader.

    GET    /entities/                               list (signed-in)
    GET    /entities/default                        the default entity, or null (signed-in)
    POST   /entities/                               create (admin)
    GET    /entities/{entity_id}                    one entity with its branches (signed-in)
    PATCH  /entities/{entity_id}                    update (admin)
    DELETE /entities/{entity_id}                    delete with its branches (admin)
    POST   /entities/{entity_id}/branches/          add a branch (admin)
    PATCH  /entities/{entity_id}/branches/{id}      update a branch (admin)
    DELETE /entities/{entity_id}/branches/{id}      delete a branch (admin)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.legal_entities.models import Branch
from app.modules.legal_entities.schemas import (
    BranchCreate,
    BranchResponse,
    BranchUpdate,
    IssueResponse,
    LegalEntityCreate,
    LegalEntityListResponse,
    LegalEntityResponse,
    LegalEntityUpdate,
)
from app.modules.legal_entities.service import LegalEntityService
from app.modules.legal_entities.validators import Issue

router = APIRouter(tags=["legal-entities"])

_MANAGE = Depends(RequirePermission("legal_entities.manage"))


def _branch_response(branch: Branch, warnings: list[Issue]) -> BranchResponse:
    out = BranchResponse.model_validate(branch)
    out.warnings = [IssueResponse(**vars(w)) for w in warnings]
    return out


@router.get("/entities/", response_model=LegalEntityListResponse)
async def list_entities(
    session: SessionDep,
    _user_id: CurrentUserId,
    include_inactive: bool = Query(default=False),
) -> LegalEntityListResponse:
    items = await LegalEntityService(session).list_entities(include_inactive=include_inactive)
    return LegalEntityListResponse(items=[LegalEntityResponse.model_validate(e) for e in items], total=len(items))


@router.get("/entities/default", response_model=LegalEntityResponse | None)
async def get_default_entity(session: SessionDep, _user_id: CurrentUserId) -> LegalEntityResponse | None:
    entity = await LegalEntityService(session).default_entity()
    return LegalEntityResponse.model_validate(entity) if entity is not None else None


@router.post(
    "/entities/",
    response_model=LegalEntityResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_entity(data: LegalEntityCreate, session: SessionDep, _user_id: CurrentUserId) -> LegalEntityResponse:
    entity = await LegalEntityService(session).create_entity(data.model_dump())
    return LegalEntityResponse.model_validate(entity)


@router.get("/entities/{entity_id}", response_model=LegalEntityResponse)
async def get_entity(entity_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId) -> LegalEntityResponse:
    return LegalEntityResponse.model_validate(await LegalEntityService(session).get_entity(entity_id))


@router.patch("/entities/{entity_id}", response_model=LegalEntityResponse, dependencies=[_MANAGE])
async def update_entity(
    entity_id: uuid.UUID, data: LegalEntityUpdate, session: SessionDep, _user_id: CurrentUserId
) -> LegalEntityResponse:
    entity = await LegalEntityService(session).update_entity(entity_id, data.model_dump(exclude_unset=True))
    return LegalEntityResponse.model_validate(entity)


@router.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_MANAGE])
async def delete_entity(entity_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId) -> Response:
    await LegalEntityService(session).delete_entity(entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/entities/{entity_id}/branches/",
    response_model=BranchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_branch(
    entity_id: uuid.UUID, data: BranchCreate, session: SessionDep, _user_id: CurrentUserId
) -> BranchResponse:
    branch, warnings = await LegalEntityService(session).create_branch(entity_id, data.model_dump())
    return _branch_response(branch, warnings)


@router.patch(
    "/entities/{entity_id}/branches/{branch_id}",
    response_model=BranchResponse,
    dependencies=[_MANAGE],
)
async def update_branch(
    entity_id: uuid.UUID,
    branch_id: uuid.UUID,
    data: BranchUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> BranchResponse:
    branch, warnings = await LegalEntityService(session).update_branch(
        entity_id, branch_id, data.model_dump(exclude_unset=True)
    )
    return _branch_response(branch, warnings)


@router.delete(
    "/entities/{entity_id}/branches/{branch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MANAGE],
)
async def delete_branch(
    entity_id: uuid.UUID, branch_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId
) -> Response:
    await LegalEntityService(session).delete_branch(entity_id, branch_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
