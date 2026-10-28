# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FastAPI router for the authority-submission factory.

Auto-mounted at ``/api/v1/authority-submission/``. Profiles are global schema
definitions and are read with only the ``authority_submission.read`` permission.
Submissions are project-scoped: every submission endpoint runs the standard
:func:`app.dependencies.verify_project_access` guard so a caller cannot see or
mutate submissions on a project they lack access to, and a cross-project id
surfaces as 404 (not 403) so the endpoint can't be used as an id-existence
oracle.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    LangDep,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.authority_submission import intl
from app.modules.authority_submission.schemas import (
    FORMAT_KEYS,
    STATUSES,
    GeneratedXmlResponse,
    SubmissionCreate,
    SubmissionProfileResponse,
    SubmissionResponse,
    SubmissionUpdate,
    ValidationReportResponse,
)
from app.modules.authority_submission.service import ProfileService, SubmissionService

router = APIRouter(tags=["authority_submission"])


def _profile_service(session: SessionDep) -> ProfileService:
    return ProfileService(session)


def _submission_service(session: SessionDep) -> SubmissionService:
    return SubmissionService(session)


# ── Meta ────────────────────────────────────────────────────────────────────


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("authority_submission.read"))],
)
async def get_meta(lang: LangDep) -> dict:
    """Expose the validated vocabularies with localized labels for the UI.

    The frontend builds its format / status pickers from this payload so it
    never drifts from the server-side whitelists, pre-translated for the
    requested locale (falling back to English).
    """
    return {
        "format_keys": [{"code": c, "label": intl.describe_format(c, lang)} for c in FORMAT_KEYS],
        "statuses": [{"code": s, "label": intl.describe_status(s, lang)} for s in STATUSES],
    }


# ── Profiles (global read) ───────────────────────────────────────────────────


@router.get(
    "/profiles",
    response_model=list[SubmissionProfileResponse],
    dependencies=[Depends(RequirePermission("authority_submission.read"))],
)
async def list_profiles(
    format_key: str | None = Query(default=None),
    service: ProfileService = Depends(_profile_service),
) -> list[SubmissionProfileResponse]:
    """List the available submission profiles, optionally by format family.

    Built-in, jurisdiction-neutral profiles are seeded on first read.
    """
    items = await service.list_profiles(format_key=format_key)
    return [SubmissionProfileResponse.model_validate(i) for i in items]


@router.get(
    "/profiles/{profile_id}/",
    response_model=SubmissionProfileResponse,
    dependencies=[Depends(RequirePermission("authority_submission.read"))],
)
async def get_profile(
    profile_id: uuid.UUID,
    service: ProfileService = Depends(_profile_service),
) -> SubmissionProfileResponse:
    """Read a single submission profile (its full field spec)."""
    profile = await service.get_profile(profile_id)
    return SubmissionProfileResponse.model_validate(profile)


# ── Submissions (project-scoped) ─────────────────────────────────────────────


@router.get(
    "/submissions/",
    response_model=list[SubmissionResponse],
    dependencies=[Depends(RequirePermission("authority_submission.read"))],
)
async def list_submissions(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    profile_id: uuid.UUID | None = Query(default=None),
    service: SubmissionService = Depends(_submission_service),
) -> list[SubmissionResponse]:
    """List submissions for a project, optionally filtered."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_submissions(
        project_id,
        status=status_filter,
        profile_id=profile_id,
    )
    return [SubmissionResponse.model_validate(i) for i in items]


@router.post(
    "/submissions/",
    response_model=SubmissionResponse,
    status_code=201,
)
async def create_submission(
    data: SubmissionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("authority_submission.create")),
    service: SubmissionService = Depends(_submission_service),
) -> SubmissionResponse:
    """Start a new submission against a profile (opens in ``draft``)."""
    await verify_project_access(data.project_id, user_id, session)
    submission = await service.create_submission(data, user_id=user_id)
    return SubmissionResponse.model_validate(submission)


@router.get(
    "/submissions/{submission_id}/",
    response_model=SubmissionResponse,
    dependencies=[Depends(RequirePermission("authority_submission.read"))],
)
async def get_submission(
    submission_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SubmissionService = Depends(_submission_service),
) -> SubmissionResponse:
    """Read a single submission."""
    submission = await service.get_submission(submission_id)
    await verify_project_access(submission.project_id, user_id, session)
    return SubmissionResponse.model_validate(submission)


@router.patch(
    "/submissions/{submission_id}/",
    response_model=SubmissionResponse,
)
async def update_submission(
    submission_id: uuid.UUID,
    data: SubmissionUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("authority_submission.update")),
    service: SubmissionService = Depends(_submission_service),
) -> SubmissionResponse:
    """Patch a submission. Editing the payload resets it to ``draft``."""
    existing = await service.get_submission(submission_id)
    await verify_project_access(existing.project_id, user_id, session)
    submission = await service.update_submission(submission_id, data, user_id=user_id)
    return SubmissionResponse.model_validate(submission)


@router.delete(
    "/submissions/{submission_id}/",
    status_code=204,
)
async def delete_submission(
    submission_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("authority_submission.delete")),
    service: SubmissionService = Depends(_submission_service),
) -> None:
    """Delete a submission."""
    existing = await service.get_submission(submission_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_submission(submission_id)


# ── Engine actions ───────────────────────────────────────────────────────────


@router.post(
    "/submissions/{submission_id}/validate",
    response_model=ValidationReportResponse,
)
async def validate_submission(
    submission_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("authority_submission.update")),
    service: SubmissionService = Depends(_submission_service),
) -> ValidationReportResponse:
    """Validate the payload against its profile and store the report.

    A clean report advances a ``draft`` submission to ``validated``.
    """
    existing = await service.get_submission(submission_id)
    await verify_project_access(existing.project_id, user_id, session)
    report = await service.validate_submission(submission_id)
    return ValidationReportResponse.model_validate(report)


@router.post(
    "/submissions/{submission_id}/generate-xml",
    response_model=GeneratedXmlResponse,
)
async def generate_xml(
    submission_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("authority_submission.update")),
    service: SubmissionService = Depends(_submission_service),
) -> GeneratedXmlResponse:
    """Build and persist the deterministic XML for a submission."""
    existing = await service.get_submission(submission_id)
    await verify_project_access(existing.project_id, user_id, session)
    xml = await service.generate_submission_xml(submission_id)
    return GeneratedXmlResponse(submission_id=submission_id, xml=xml)


@router.get(
    "/submissions/{submission_id}/render",
    dependencies=[Depends(RequirePermission("authority_submission.read"))],
)
async def render_submission(
    submission_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SubmissionService = Depends(_submission_service),
) -> dict:
    """Render the payload for human review (the readable side of the XML)."""
    existing = await service.get_submission(submission_id)
    await verify_project_access(existing.project_id, user_id, session)
    return await service.render_submission(submission_id)


@router.post(
    "/submissions/{submission_id}/submit",
    response_model=SubmissionResponse,
)
async def submit_submission(
    submission_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("authority_submission.submit")),
    service: SubmissionService = Depends(_submission_service),
) -> SubmissionResponse:
    """Mark a validated submission as submitted to the authority."""
    existing = await service.get_submission(submission_id)
    await verify_project_access(existing.project_id, user_id, session)
    submission = await service.submit_submission(submission_id)
    return SubmissionResponse.model_validate(submission)


__all__ = ["router"]
