"""/api/v1/design endpoints that tie the design to the other ERP modules: element links and the project overview."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import SessionDep

from . import element_context, field_links, integration, links
from .auth import PrincipalDep, require_project

MAX_KEYS = 500


class ReportLinks(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=MAX_KEYS)
    position_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_KEYS)


def register(router, can_accept) -> None:
    @router.get("/projects/{project_id}/links")
    async def element_links(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, keys: list[str] = Query(default=[])
    ) -> dict[str, Any]:
        """For the selected elements: the BOQ positions, schedule activities and tender packages they feed."""
        await require_project(principal, project_id, session)
        if len(keys) > MAX_KEYS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"At most {MAX_KEYS} elements at once")
        return await links.lookup(session, project_id, keys)

    @router.get("/projects/{project_id}/element-context")
    async def element_context_view(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, keys: list[str] = Query(default=[])
    ) -> dict[str, Any]:
        """For the selected elements: linked documents and open remarks (tasks, punch items)."""
        await require_project(principal, project_id, session)
        if len(keys) > MAX_KEYS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"At most {MAX_KEYS} elements at once")
        return await element_context.context(session, project_id, keys)

    @router.get("/projects/{project_id}/positions/{position_id}/elements")
    async def position_elements(
        project_id: uuid.UUID, position_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        out = await links.position_elements(session, project_id, position_id)
        if out is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This position does not come from the design")
        return out

    @router.post("/projects/{project_id}/links/sync")
    async def sync_links(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, int]:
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        if principal.via_link or not await can_accept(
            session, principal.user_id, await session.get(Project, project_id)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may relink the design")
        out = await links.sync(session, project_id)
        await session.commit()
        return out

    @router.get("/projects/{project_id}/overview")
    async def overview(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        return await integration.overview(session, project_id, principal.user_id)

    @router.get("/projects/{project_id}/field-reports")
    async def field_reports(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, keys: list[str] = Query(default=[])
    ) -> dict[str, Any]:
        """The project's field reports; with ``keys`` only those that point at one of these elements."""
        await require_project(principal, project_id, session)
        if len(keys) > MAX_KEYS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"At most {MAX_KEYS} elements at once")
        items = (
            await field_links.for_elements(session, project_id, keys)
            if keys
            else await field_links.candidates(session, project_id)
        )
        return {"items": items}

    @router.put("/projects/{project_id}/field-reports/{report_id}/links")
    async def link_field_report(
        project_id: uuid.UUID, report_id: uuid.UUID, body: ReportLinks, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Field reports are linked from the ERP")
        out = await field_links.set_links(session, project_id, report_id, body.keys, body.position_ids)
        await session.commit()
        return out

    @router.get("/projects/{project_id}/field-reports/{report_id}/elements")
    async def field_report_elements(
        project_id: uuid.UUID, report_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        return await field_links.report_elements(session, project_id, report_id)
