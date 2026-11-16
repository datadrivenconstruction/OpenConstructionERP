# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Legal entity and branch API routes.

Mounted at ``/api/v1/legal-entities/`` by the module loader.

    GET    /entities/                               list with counts (signed-in)
    GET    /entities/default                        the default entity, or null (signed-in)
    GET    /ui-state                                how many companies, which are mine (signed-in)
    GET    /tax-schemes/{country_code}              tax ids a company of that country carries
    POST   /entities/                               create (admin)
    GET    /entities/{entity_id}                    one entity with its branches (signed-in)
    PATCH  /entities/{entity_id}                    update (admin)
    DELETE /entities/{entity_id}                    delete with its branches (admin)
    POST   /entities/{entity_id}/branches/          add a site (admin)
    PATCH  /entities/{entity_id}/branches/{id}      update a site (admin)
    DELETE /entities/{entity_id}/branches/{id}      delete a site (admin)
    GET    /entities/{entity_id}/members/           people of the company (signed-in)
    POST   /entities/{entity_id}/members/           add a person (admin)
    PATCH  /entities/{entity_id}/members/{id}       change the role (admin)
    DELETE /entities/{entity_id}/members/{id}       remove (admin)
    GET    /projects/{project_id}/entity            the entity owning a project (project access)
    PUT    /projects/{project_id}/entity            name or clear it (admin, or the project owner)
    GET    /projects/{project_id}/seller            the seller block its documents print (project access)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.legal_entities.models import Branch, LegalEntity
from app.modules.legal_entities.schemas import (
    BranchCreate,
    BranchResponse,
    BranchUpdate,
    IssueResponse,
    LegalEntityCreate,
    LegalEntityListResponse,
    LegalEntityResponse,
    LegalEntityUpdate,
    MemberCreate,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
    ProjectEntityAssign,
    ProjectEntityResponse,
    SellerResponse,
    TaxSchemeResponse,
    TaxSchemesResponse,
    UiStateResponse,
)
from app.modules.legal_entities.seller import resolve_seller
from app.modules.legal_entities.service import LegalEntityService
from app.modules.legal_entities.tax_ids import primary_tax_id, schemes_for
from app.modules.legal_entities.validators import Issue, check_seller_complete

router = APIRouter(tags=["legal-entities"])

_MANAGE = Depends(RequirePermission("legal_entities.manage"))


def _issues(found: list[Issue]) -> list[IssueResponse]:
    return [IssueResponse(**vars(i)) for i in found]


def _is_admin(payload: dict) -> bool:
    from app.core.permissions import ROLE_HIERARCHY, _resolve_role

    role = _resolve_role(payload.get("role", ""))
    admin = _resolve_role("admin")
    return role is not None and admin is not None and ROLE_HIERARCHY.get(role, -1) >= ROLE_HIERARCHY.get(admin, 999)


async def _entity_response(
    service: LegalEntityService,
    entity: LegalEntity,
    *,
    project_counts: dict | None = None,
    member_counts: dict | None = None,
    own_settings: set[str] | None = None,
) -> LegalEntityResponse:
    out = LegalEntityResponse.model_validate(entity)
    out.primary_tax_id = primary_tax_id(entity.country_code, entity.tax_ids, entity.tax_id)
    projects = project_counts if project_counts is not None else await service.project_counts()
    members = member_counts if member_counts is not None else await service.member_counts()
    settings = own_settings if own_settings is not None else await service.entities_with_own_settings()
    out.project_count = projects.get(entity.id, 0)
    out.member_count = members.get(entity.id, 0)
    out.has_own_einvoice_settings = str(entity.id) in settings
    out.warnings = _issues(service.entity_warnings(entity))
    return out


def _branch_response(branch: Branch, warnings: list[Issue]) -> BranchResponse:
    out = BranchResponse.model_validate(branch)
    out.warnings = _issues(warnings)
    return out


@router.get("/entities/", response_model=LegalEntityListResponse)
async def list_entities(
    session: SessionDep,
    _user_id: CurrentUserId,
    include_inactive: bool = Query(default=False),
) -> LegalEntityListResponse:
    service = LegalEntityService(session)
    items = await service.list_entities(include_inactive=include_inactive)
    projects, members, settings = (
        await service.project_counts(),
        await service.member_counts(),
        await service.entities_with_own_settings(),
    )
    out = [
        await _entity_response(service, e, project_counts=projects, member_counts=members, own_settings=settings)
        for e in items
    ]
    return LegalEntityListResponse(items=out, total=len(out))


@router.get("/entities/default", response_model=LegalEntityResponse | None)
async def get_default_entity(session: SessionDep, _user_id: CurrentUserId) -> LegalEntityResponse | None:
    service = LegalEntityService(session)
    entity = await service.default_entity()
    return await _entity_response(service, entity) if entity is not None else None


@router.get("/ui-state", response_model=UiStateResponse)
async def ui_state(session: SessionDep, user_id: CurrentUserId) -> UiStateResponse:
    """Whether the company pickers and filters should show at all: only from two active companies."""
    service = LegalEntityService(session)
    active = await service.list_entities()
    default = await service.default_entity()
    try:
        mine = await service.my_entity_ids(uuid.UUID(str(user_id)))
    except ValueError:
        mine = []
    return UiStateResponse(
        active_entity_count=len(active),
        multi_company=len(active) >= 2,
        my_entity_ids=mine,
        default_entity_id=default.id if default is not None else None,
    )


@router.get("/tax-schemes/{country_code}", response_model=TaxSchemesResponse)
async def tax_schemes(country_code: str, _user_id: CurrentUserId) -> TaxSchemesResponse:
    """The tax identifiers a company registered in the country carries, from the country data."""
    code = country_code.strip().upper()[:2]
    return TaxSchemesResponse(
        country_code=code,
        schemes=[TaxSchemeResponse(**vars(s)) for s in schemes_for(code)],
    )


@router.post(
    "/entities/",
    response_model=LegalEntityResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_entity(data: LegalEntityCreate, session: SessionDep, _user_id: CurrentUserId) -> LegalEntityResponse:
    service = LegalEntityService(session)
    entity = await service.create_entity(data.model_dump())
    return await _entity_response(service, entity)


@router.get("/entities/{entity_id}", response_model=LegalEntityResponse)
async def get_entity(entity_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId) -> LegalEntityResponse:
    service = LegalEntityService(session)
    return await _entity_response(service, await service.get_entity(entity_id))


@router.patch("/entities/{entity_id}", response_model=LegalEntityResponse, dependencies=[_MANAGE])
async def update_entity(
    entity_id: uuid.UUID, data: LegalEntityUpdate, session: SessionDep, _user_id: CurrentUserId
) -> LegalEntityResponse:
    service = LegalEntityService(session)
    entity = await service.update_entity(entity_id, data.model_dump(exclude_unset=True))
    return await _entity_response(service, entity)


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


# ── Members ──────────────────────────────────────────────────────────────


def _member_response(member, user) -> MemberResponse:
    out = MemberResponse.model_validate(member)
    if user is not None:
        out.email = user.email or ""
        out.full_name = user.full_name or ""
    return out


@router.get("/entities/{entity_id}/members/", response_model=MemberListResponse)
async def list_members(entity_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId) -> MemberListResponse:
    service = LegalEntityService(session)
    rows = await service.list_members(entity_id)
    return MemberListResponse(items=[_member_response(m, u) for m, u in rows], any_members=await service.any_members())


@router.post(
    "/entities/{entity_id}/members/",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def add_member(
    entity_id: uuid.UUID, data: MemberCreate, session: SessionDep, _user_id: CurrentUserId
) -> MemberResponse:
    from app.modules.users.models import User

    member = await LegalEntityService(session).add_member(entity_id, data.user_id, data.role)
    return _member_response(member, await session.get(User, data.user_id))


@router.patch("/entities/{entity_id}/members/{member_id}", response_model=MemberResponse, dependencies=[_MANAGE])
async def update_member(
    entity_id: uuid.UUID, member_id: uuid.UUID, data: MemberUpdate, session: SessionDep, _user_id: CurrentUserId
) -> MemberResponse:
    from app.modules.users.models import User

    member = await LegalEntityService(session).update_member(entity_id, member_id, data.role)
    return _member_response(member, await session.get(User, member.user_id))


@router.delete(
    "/entities/{entity_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MANAGE],
)
async def remove_member(
    entity_id: uuid.UUID, member_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId
) -> Response:
    await LegalEntityService(session).remove_member(entity_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Projects ─────────────────────────────────────────────────────────────


async def _project_entity_response(
    service: LegalEntityService,
    project_id: uuid.UUID,
    entity: LegalEntity | None,
    source: str,
    warnings: list[Issue] | None = None,
) -> ProjectEntityResponse:
    from app.modules.projects.models import Project

    project = await service.session.get(Project, project_id)
    return ProjectEntityResponse(
        project_id=project_id,
        legal_entity=await _entity_response(service, entity) if entity is not None else None,
        source=source,
        legal_entity_branch_id=project.legal_entity_branch_id if project is not None else None,
        issued_invoice_count=await service.issued_invoice_count(project_id),
        warnings=_issues(warnings or []),
    )


@router.get("/projects/{project_id}/entity", response_model=ProjectEntityResponse)
async def get_project_entity(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> ProjectEntityResponse:
    await verify_project_access(project_id, user_id, session)
    service = LegalEntityService(session)
    entity, source = await service.project_entity(project_id)
    return await _project_entity_response(service, project_id, entity, source)


@router.put("/projects/{project_id}/entity", response_model=ProjectEntityResponse)
async def assign_project_entity(
    project_id: uuid.UUID, data: ProjectEntityAssign, session: SessionDep, payload: CurrentUserPayload
) -> ProjectEntityResponse:
    """Name the company (and site) of a project. An admin may, and so may the project's owner."""
    from app.modules.projects.models import Project

    user_id = str(payload.get("sub", ""))
    await verify_project_access(project_id, user_id, session)
    project = await session.get(Project, project_id)
    if not _is_admin(payload) and (project is None or str(project.owner_id) != user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an admin or the project owner")
    service = LegalEntityService(session)
    entity, source, warnings = await service.assign_project(
        project_id, data.legal_entity_id, data.legal_entity_branch_id
    )
    return await _project_entity_response(service, project_id, entity, source, warnings)


@router.get("/projects/{project_id}/seller", response_model=SellerResponse)
async def get_project_seller(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> SellerResponse:
    """The seller block the project's invoices and pay applications print, with what is missing."""
    await verify_project_access(project_id, user_id, session)
    resolution = await resolve_seller(session, project_id, with_profile_fallback=True)
    entity = resolution.entity
    issues = check_seller_complete(
        resolution.seller, resolution.country_code, entity_code=entity.code if entity else ""
    )
    return SellerResponse(
        project_id=project_id,
        source=resolution.source,
        legal_entity_id=entity.id if entity is not None else None,
        legal_entity_code=entity.code if entity is not None else None,
        seller=resolution.seller,
        complete=not issues,
        missing=resolution.missing,
        issues=_issues(issues),
    )
