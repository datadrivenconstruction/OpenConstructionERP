"""/api/v1/design model panel: change the main design values in the ERP and generate a revision (R13 job).

The new values become a brief version (action ``model``) confirmed by the person who set them; the R13
worker then runs ``ddc gen`` + ``ddc publish --parent``. Same gates as R13: manager only, no link token,
409 while an editor holds the project or a job runs. Registered on the module router by ``register``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import SessionDep

from . import jobs, model_params, worker_guard
from .auth import PrincipalDep, now_utc, require_project
from .brief import _head, _store
from .brief_doc import BriefError


class ModelRequest(BaseModel):
    brief_version: int = Field(ge=1)
    # empty: build from the confirmed brief as it stands (the first revision usually changes nothing)
    values: dict[str, Any] = Field(default_factory=dict, max_length=100)


class PreviewRequest(BaseModel):
    brief_version: int = Field(ge=1)
    values: dict[str, Any] = Field(default_factory=dict, max_length=100)


def register(router, can_edit) -> None:
    async def _brief(session, project_id: uuid.UUID):
        head = await _head(session, project_id)
        if head is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No brief yet")
        return head

    @router.get("/projects/{project_id}/model")
    async def model_view(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
        await require_project(principal, project_id, session)
        head = await _brief(session, project_id)
        return model_params.view(head.document)

    @router.post("/projects/{project_id}/model/preview")
    async def model_preview(
        project_id: uuid.UUID, body: PreviewRequest, principal: PrincipalDep, session: SessionDep
    ) -> dict:
        """Dry run of generate: the brief document ``ddc gen --brief`` would get for these values; nothing stored.

        The panel's in-browser preview builds from it, so preview and revision read the same mapping."""
        await require_project(principal, project_id, session)
        head = await _brief(session, project_id)
        if head.version != body.brief_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT, {"message": "The brief was changed; reload it", "version": head.version}
            )
        try:
            doc, _ = model_params.apply(head.document, body.values, user_id=str(principal.user_id), at=now_utc())
        except BriefError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"message": "The values are outside what the generator takes", "errors": exc.errors[:50]},
            ) from exc
        # A brief not yet confirmed is an answer of the dry run, not a fault: no brief, and why.
        problems = jobs.brief_problems(doc)
        if problems:
            return {"brief_version": head.version, "brief": None, "problems": problems}
        return {"brief_version": head.version, "brief": doc}

    @router.post("/projects/{project_id}/model/generate", status_code=status.HTTP_202_ACCEPTED)
    async def model_generate(
        project_id: uuid.UUID, body: ModelRequest, principal: PrincipalDep, session: SessionDep
    ) -> dict:
        from app.modules.collaboration_locks.service import CollabLockService
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Generation is started in the ERP")
        if not await can_edit(session, principal.user_id, await session.get(Project, project_id)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role may not create revisions on this project")
        # Refuse before a brief version is written; start_generation checks all of it again atomically.
        jobs.require_cli()
        await worker_guard.require_runner()
        await jobs.sweep_stale(session, project_id)
        if await jobs.active_job(session, project_id) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "A generation is already running for this project")
        held = await CollabLockService(session).get_for_entity(entity_type=jobs.LOCK_ENTITY, entity_id=project_id)
        if held is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "message": "Project is being edited",
                    "held_by": held.user_name,
                    "expires_at": held.expires_at.isoformat(),
                },
            )
        head = await _brief(session, project_id)
        if head.version != body.brief_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT, {"message": "The brief was changed; reload it", "version": head.version}
            )
        try:
            doc, changed = model_params.apply(head.document, body.values, user_id=str(principal.user_id), at=now_utc())
        except BriefError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"message": "The values are outside what the generator takes", "errors": exc.errors[:50]},
            ) from exc
        problems = jobs.brief_problems(doc)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problems)
        version = head.version
        if changed:
            doc["version"] = version = head.version + 1
            await _store(
                session,
                head,
                project_id=project_id,
                expected=head.version,
                document=doc,
                user_id=principal.user_id,
                action="model",
            )
        else:
            await session.rollback()
        job = await jobs.start_generation(project_id, principal.user_id, version)
        return {"job_id": str(job.id), "brief_version": version, "changed": changed}
