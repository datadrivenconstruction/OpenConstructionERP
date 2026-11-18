# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project tax profile API routes.

Endpoints:
    GET /projects/{project_id}/profile/  - the stored profile or a derived proposal
    PUT /projects/{project_id}/profile/  - save it; 409 inside the method lock
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.project_tax import repository, service
from app.modules.project_tax.schemas import ProfileFinding, ProfileResponse, ProfileSaveResponse, ProfileUpdate
from app.modules.project_tax.validators import evaluate_profile

router = APIRouter(tags=["project_tax"])


async def _project_or_404(session: SessionDep, project_id: uuid.UUID) -> object:
    from app.modules.projects.models import Project  # noqa: PLC0415 - keep import cheap at mount

    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get(
    "/projects/{project_id}/profile/",
    response_model=ProfileResponse,
    dependencies=[Depends(RequirePermission("project_tax.read"))],
)
async def get_profile(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ProfileResponse:
    """The project's tax profile; ``stored=false`` marks a proposal nobody saved."""
    await verify_project_access(project_id, user_id, session)
    project = await _project_or_404(session, project_id)
    row = await repository.get_for_project(session, project_id)
    return service.to_response(project, row)


@router.put(
    "/projects/{project_id}/profile/",
    response_model=ProfileSaveResponse,
    dependencies=[Depends(RequirePermission("project_tax.write"))],
)
async def put_profile(
    project_id: uuid.UUID,
    payload: ProfileUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ProfileSaveResponse:
    """Save the profile. A method change inside the election lock is refused with 409."""
    await verify_project_access(project_id, user_id, session)
    project = await _project_or_404(session, project_id)
    try:
        row = await service.save_profile(session, project, payload, user_id=user_id)
    except service.ProfileLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "lock_ends_on": exc.ends_on.isoformat(),
                "election_date": exc.election.isoformat() if exc.election else None,
            },
        ) from exc
    await session.commit()
    profile = service.to_response(project, row)
    findings = await evaluate_profile(service.record_for_rules(project, profile))
    return ProfileSaveResponse(
        profile=profile,
        findings=[
            ProfileFinding(
                rule_id=f.rule_id, severity=str(f.severity), message=f.message, details=dict(f.details or {})
            )
            for f in findings
        ],
    )
