"""/api/v1/design endpoints that tie the design to the other ERP modules: element links and the project overview."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.dependencies import SessionDep

from . import element_context, field_links, integration, links
from .auth import PrincipalDep, as_aware, now_utc, require_project

MAX_KEYS = 500


class ReportLinks(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=MAX_KEYS)
    position_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_KEYS)


def _coded(status_code: int, code: str, message: str) -> HTTPException:
    """``code`` is the i18n key suffix ``design.link_status.error.<code>``; ``message`` is for logs and old clients."""
    return HTTPException(status_code, {"code": code, "message": message})


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

    @router.get("/projects/{project_id}/link/status")
    async def link_status(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        """Editors linked to this project (live tokens only), their last call, and revisions awaiting a decision."""
        from .models import DesignLinkToken, DesignRevision

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise _coded(status.HTTP_403_FORBIDDEN, "link_status_erp_only", "Link status is read in the ERP")
        from app.modules.projects.models import Project

        now = now_utc()
        sees_all = await can_accept(session, principal.user_id, await session.get(Project, project_id))
        tokens = (
            (
                await session.execute(
                    select(DesignLinkToken)
                    .where(DesignLinkToken.project_id == project_id, DesignLinkToken.revoked_at.is_(None))
                    .order_by(DesignLinkToken.last_used_at.desc().nulls_last())
                )
            )
            .scalars()
            .all()
        )
        editors = [
            {
                "id": str(t.id),
                "client_name": t.client_name,
                "client_version": t.client_version,
                "client_os": t.client_os,
                "mine": t.user_id == principal.user_id,
                "linked_at": t.created_at,
                "last_used_at": t.last_used_at,
                "expires_at": t.expires_at,
            }
            for t in tokens
            if as_aware(t.expires_at) > now and (sees_all or t.user_id == principal.user_id)
        ]
        pending = (
            await session.execute(
                select(func.count())
                .select_from(DesignRevision)
                .where(DesignRevision.project_id == project_id, DesignRevision.status == "shared")
            )
        ).scalar_one()
        from app.modules.users.models import User

        last = (
            await session.execute(
                select(DesignRevision)
                .where(
                    DesignRevision.project_id == project_id,
                    DesignRevision.status.in_(("shared", "published", "rejected", "archived")),
                )
                .order_by(DesignRevision.number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        trace = None
        if last is not None:
            author = await session.get(User, last.author_user_id) if last.author_user_id else None
            trace = {
                "revision_id": str(last.id),
                "number": last.number,
                "status": last.status,
                "source_kind": last.source_kind,
                "package_sha256": last.package_sha256,
                "author": (author.full_name or author.email) if author else None,
                "received_at": last.created_at,
            }
        return {
            "editors": editors,
            "pending_revisions": pending,
            "last_revision_at": last.created_at if last else None,
            "last_revision": trace,
        }

    @router.delete("/projects/{project_id}/link/editors/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_editor(
        project_id: uuid.UUID, token_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
    ) -> Response:
        """Cut one editor off; its holder or a project manager may. The token dies at once."""
        from app.modules.projects.models import Project

        from .models import DesignLinkToken

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise _coded(status.HTTP_403_FORBIDDEN, "link_status_erp_only", "Editors are unlinked from the ERP")
        row = await session.get(DesignLinkToken, token_id)
        if row is None or row.project_id != project_id or row.revoked_at is not None:
            raise _coded(status.HTTP_404_NOT_FOUND, "editor_link_not_found", "Editor link not found")
        if row.user_id != principal.user_id and not await can_accept(
            session, principal.user_id, await session.get(Project, project_id)
        ):
            raise _coded(
                status.HTTP_403_FORBIDDEN, "unlink_not_allowed", "Only the holder or a manager may unlink an editor"
            )
        await session.execute(
            update(DesignLinkToken)
            .where(DesignLinkToken.id == token_id, DesignLinkToken.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
