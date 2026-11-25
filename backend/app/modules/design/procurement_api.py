"""/api/v1/design procurement endpoints (R11). Registered on the module router by ``register``."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import SessionDep

from . import links
from . import procurement as prc
from .auth import PrincipalDep, require_project
from .models import DesignRevision


class SetupRequest(BaseModel):
    group_by: str = Field(default="type_key", pattern=r"^(type_key|ifc_class)$")


class FollowRequest(BaseModel):
    follow: bool


class BasisRequest(BaseModel):
    basis: str = Field(pattern=r"^(length_m|area_m2|volume_m3|weight_kg|count)$")


def register(router, can_accept) -> None:
    async def manager(principal, project_id: uuid.UUID, session) -> None:
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "The take-off is managed in the ERP")
        project = await session.get(Project, project_id)
        if not await can_accept(session, principal.user_id, project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may change the take-off")

    @router.get("/projects/{project_id}/procurement")
    async def get_procurement(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        return await prc.summary(session, project_id)

    @router.post("/projects/{project_id}/procurement/setup", status_code=status.HTTP_201_CREATED)
    async def setup(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, body: SetupRequest | None = None
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        try:
            await prc.setup(session, project_id, (body or SetupRequest()).group_by, principal.user_id)
            await links.sync(session, project_id)  # BOQ, viewer and 4D see the elements
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        return await prc.summary(session, project_id)

    @router.post("/projects/{project_id}/procurement/packages/{ifc_class}/rfq", status_code=status.HTTP_201_CREATED)
    async def package_rfq(
        project_id: uuid.UUID, ifc_class: str, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        try:
            rfq = await prc.rfq_from_package(session, project_id, ifc_class, principal.user_id)
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        return {"rfq_id": str(rfq.id), "rfq_number": rfq.rfq_number, "status": rfq.status, "url": "/rfq-bidding"}

    @router.put("/projects/{project_id}/procurement/settings")
    async def settings(
        project_id: uuid.UUID, body: FollowRequest, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        proc = await prc.set_follow(session, project_id, body.follow)
        await session.commit()
        return {"follow": proc.follow, "group_by": proc.group_by}

    @router.put("/projects/{project_id}/procurement/lines/{line_id}/basis")
    async def line_basis(
        project_id: uuid.UUID, line_id: uuid.UUID, body: BasisRequest, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        try:
            await prc.set_basis(session, project_id, line_id, body.basis, principal.user_id)
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        return await prc.summary(session, project_id)

    @router.get("/revisions/{revision_id}/procurement-impact")
    async def procurement_impact(
        revision_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        rev = await session.get(DesignRevision, revision_id)
        if rev is None or rev.status == "uploading":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
        await require_project(principal, rev.project_id, session)
        return await prc.impact(session, rev)
