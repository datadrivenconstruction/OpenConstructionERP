"""/api/v1/design schedule endpoints (R10). Registered on the module router by ``register``."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import SessionDep

from . import links
from . import schedule as sch
from .auth import PrincipalDep, require_project
from .models import DesignRevision


class SetupRequest(BaseModel):
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class CrewsRequest(BaseModel):
    crews: dict[str, int] = Field(default_factory=dict)


def register(router, can_accept) -> None:
    async def manager(principal, project_id: uuid.UUID, session) -> None:
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "The schedule is managed in the ERP")
        project = await session.get(Project, project_id)
        if not await can_accept(session, principal.user_id, project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may change the schedule")

    @router.get("/projects/{project_id}/schedule")
    async def get_schedule(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        return await sch.summary(session, project_id)

    @router.post("/projects/{project_id}/schedule/setup", status_code=status.HTTP_201_CREATED)
    async def setup(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, body: SetupRequest | None = None
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        try:
            await sch.setup(session, project_id, body.start_date if body else None, principal.user_id)
            await links.sync(session, project_id)  # BOQ, viewer and 4D see the elements
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        return await sch.summary(session, project_id)

    @router.put("/projects/{project_id}/schedule/settings")
    async def settings(
        project_id: uuid.UUID, body: CrewsRequest, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        if any(not 0 <= v <= 50 for v in body.crews.values()):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A crew is 1 to 50 people (0 clears it)")
        s = await sch.set_crews(session, project_id, body.crews)
        await session.commit()
        return {"crews": s.crews}

    @router.get("/revisions/{revision_id}/schedule-impact")
    async def schedule_impact(revision_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        rev = await session.get(DesignRevision, revision_id)
        if rev is None or rev.status == "uploading":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
        await require_project(principal, rev.project_id, session)
        return await sch.impact(session, rev)
