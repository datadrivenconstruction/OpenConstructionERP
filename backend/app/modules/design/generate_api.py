"""/api/v1/design generation endpoints (R13). Registered on the module router by ``register``."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import SessionDep

from . import jobs
from .auth import PrincipalDep, require_project
from .models import DesignJob


class GenerateRequest(BaseModel):
    brief_version: int = Field(ge=1)


def register(router, can_edit) -> None:
    """``can_edit(session, user_id, project)``: may this person create revisions here (the project's design rights)."""

    async def manager(principal, project_id: uuid.UUID, session) -> None:
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Generation is started in the ERP")
        project = await session.get(Project, project_id)
        if not await can_edit(session, principal.user_id, project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role may not create revisions on this project")

    async def job_of(principal, job_id: uuid.UUID, session) -> DesignJob:
        job = await session.get(DesignJob, job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
        await require_project(principal, job.project_id, session)  # a foreign project looks like a missing job
        return job

    @router.get("/projects/{project_id}/generation")
    async def generation_state(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
        await require_project(principal, project_id, session)
        _, reason = jobs.cli_state()
        await jobs.sweep_stale(session, project_id)
        job = await jobs.active_job(session, project_id)
        if job is None:  # the last finished one, so the page can show how it ended
            from sqlalchemy import select

            job = (
                await session.execute(
                    select(DesignJob)
                    .where(DesignJob.project_id == project_id)
                    .order_by(DesignJob.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return {"enabled": reason is None, "reason": reason, "job": jobs.job_view(job) if job else None}

    @router.post("/projects/{project_id}/generate", status_code=status.HTTP_202_ACCEPTED)
    async def generate(
        project_id: uuid.UUID, body: GenerateRequest, principal: PrincipalDep, session: SessionDep
    ) -> dict:
        await manager(principal, project_id, session)
        await session.rollback()  # end the read transaction; the start works in its own sessions
        job = await jobs.start_generation(project_id, principal.user_id, body.brief_version)
        return {"job_id": str(job.id)}

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
        job = await job_of(principal, job_id, session)
        await jobs.sweep_stale(session, job.project_id)
        return jobs.job_view(await session.get(DesignJob, job_id, populate_existing=True))

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
        job = await job_of(principal, job_id, session)
        if job.user_id != principal.user_id:
            await manager(principal, job.project_id, session)
        return jobs.job_view(await jobs.cancel_generation(session, job))
