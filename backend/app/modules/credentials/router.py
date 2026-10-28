# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FastAPI router for the professional-credentials registry.

Auto-mounted at ``/api/v1/credentials/``. Every endpoint is project-scoped via
:func:`app.dependencies.verify_project_access` - the same guard the compliance
docs and RFI modules use - so a caller cannot see or mutate credentials on a
project they lack access to, and a cross-project id surfaces as 404 (not 403) so
the endpoint can't be turned into an id-existence oracle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    LangDep,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.credentials import intl
from app.modules.credentials.models import Credential
from app.modules.credentials.schemas import (
    CREDENTIAL_TYPES,
    HOLDER_KINDS,
    STATUSES,
    ComplianceReport,
    CredentialCreate,
    CredentialResponse,
    CredentialSummary,
    CredentialsValidationReport,
    CredentialUpdate,
    CredentialVerifyRequest,
    RefreshResult,
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
)
from app.modules.credentials.service import (
    CredentialService,
    RequirementService,
    recompute_status,
)

router = APIRouter(tags=["credentials"])


def _get_service(session: SessionDep) -> CredentialService:
    return CredentialService(session)


def _get_requirement_service(session: SessionDep) -> RequirementService:
    return RequirementService(session)


def _to_response(item: Credential, *, today: date | None = None) -> CredentialResponse:
    """Build a response with the derived status and ``days_until_expiry``.

    ``days_until_expiry`` is ``None`` for a perpetual credential (no
    ``valid_until``); otherwise a signed day count, negative once expired.

    ``status`` is recomputed here rather than read off the column. The stored
    value is only written when something writes to the row, so a credential that
    merely aged past its threshold would otherwise be reported with the status it
    had when it was last edited - beside a negative ``days_until_expiry`` that
    contradicts it. ``status_is_stale`` reports that divergence instead of hiding
    it, so an operator can see the stored column needs the refresh endpoint.
    """
    as_of = today or datetime.now(UTC).date()
    valid_until = item.valid_until
    days_until_expiry: int | None = None
    if valid_until is not None:
        days_until_expiry = (valid_until - as_of).days

    derived = recompute_status(
        today=as_of,
        valid_until=valid_until,
        notify_days_before=item.notify_days_before,
        current_status=item.status,
    )

    resp = CredentialResponse.model_validate(item)
    return resp.model_copy(
        update={
            "status": derived,
            "days_until_expiry": days_until_expiry,
            "status_is_stale": derived != item.status,
        }
    )


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
async def get_meta(lang: LangDep) -> dict:
    """Expose the validated vocabularies with localized labels for the UI.

    The frontend builds its type / status pickers from this payload so it never
    drifts from the server-side whitelists, and the labels come pre-translated
    for the requested locale (falling back to English).
    """
    return {
        "credential_types": [{"code": c, "label": intl.describe_type(c, lang)} for c in CREDENTIAL_TYPES],
        "holder_kinds": list(HOLDER_KINDS),
        "statuses": [{"code": s, "label": intl.describe_status(s, lang)} for s in STATUSES],
    }


@router.get(
    "/",
    response_model=list[CredentialResponse],
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
async def list_credentials(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    credential_type: str | None = Query(default=None),
    holder_user_id: uuid.UUID | None = Query(default=None),
    service: CredentialService = Depends(_get_service),
) -> list[CredentialResponse]:
    """List credentials for a project, optionally filtered."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_credentials(
        project_id,
        status=status_filter,
        credential_type=credential_type,
        holder_user_id=holder_user_id,
    )
    return [_to_response(i) for i in items]


@router.get(
    "/expiring-soon/",
    response_model=list[CredentialResponse],
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
@router.get(
    "/expiring-soon",
    response_model=list[CredentialResponse],
    dependencies=[Depends(RequirePermission("credentials.read"))],
    include_in_schema=False,
)
async def list_expiring_soon(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    service: CredentialService = Depends(_get_service),
) -> list[CredentialResponse]:
    """Credentials already expired or due within their reminder window.

    Ascending by expiry - designed for the dashboard "credentials to renew"
    widget.
    """
    await verify_project_access(project_id, user_id, session)
    items = await service.list_expiring_soon(project_id, limit=limit)
    return [_to_response(i) for i in items]


@router.post(
    "/",
    response_model=CredentialResponse,
    status_code=201,
)
async def create_credential(
    data: CredentialCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("credentials.create")),
    service: CredentialService = Depends(_get_service),
) -> CredentialResponse:
    """Register a new credential against a project."""
    await verify_project_access(data.project_id, user_id, session)
    credential = await service.create_credential(data, user_id=user_id)
    return _to_response(credential)


# ── Requirements ───────────────────────────────────────────────────────
#
# Declared ahead of the ``/{credential_id}/`` routes on purpose. FastAPI matches
# in declaration order, so a literal path registered after a single-segment
# parameter route would be swallowed by it and answer 422 on a UUID parse.


@router.get(
    "/requirements/",
    response_model=list[RequirementResponse],
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
@router.get(
    "/requirements",
    response_model=list[RequirementResponse],
    dependencies=[Depends(RequirePermission("credentials.read"))],
    include_in_schema=False,
)
async def list_requirements(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    include_inactive: bool = Query(default=False),
    service: RequirementService = Depends(_get_requirement_service),
) -> list[RequirementResponse]:
    """What this project requires, blocking rules first."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_requirements(project_id, include_inactive=include_inactive)
    return [RequirementResponse.model_validate(i) for i in items]


@router.post(
    "/requirements/",
    response_model=RequirementResponse,
    status_code=201,
)
@router.post(
    "/requirements",
    response_model=RequirementResponse,
    status_code=201,
    include_in_schema=False,
)
async def create_requirement(
    data: RequirementCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("credentials.create")),
    service: RequirementService = Depends(_get_requirement_service),
) -> RequirementResponse:
    """Record a credential this project requires. 409 if one already covers it."""
    await verify_project_access(data.project_id, user_id, session)
    requirement = await service.create_requirement(data, user_id=user_id)
    return RequirementResponse.model_validate(requirement)


@router.patch(
    "/requirements/{requirement_id}/",
    response_model=RequirementResponse,
)
async def update_requirement(
    requirement_id: uuid.UUID,
    data: RequirementUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("credentials.update")),
    service: RequirementService = Depends(_get_requirement_service),
) -> RequirementResponse:
    """Amend a requirement."""
    await service.get_requirement_for_caller(requirement_id, actor_id=user_id)
    requirement = await service.update_requirement(requirement_id, data, user_id=user_id)
    return RequirementResponse.model_validate(requirement)


@router.delete(
    "/requirements/{requirement_id}/",
    status_code=204,
)
async def delete_requirement(
    requirement_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("credentials.delete")),
    service: RequirementService = Depends(_get_requirement_service),
) -> None:
    """Retire a requirement outright."""
    await service.get_requirement_for_caller(requirement_id, actor_id=user_id)
    await service.delete_requirement(requirement_id)


# ── Reports ────────────────────────────────────────────────────────────


@router.get(
    "/compliance/",
    response_model=ComplianceReport,
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
@router.get(
    "/compliance",
    response_model=ComplianceReport,
    dependencies=[Depends(RequirePermission("credentials.read"))],
    include_in_schema=False,
)
async def get_compliance(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: RequirementService = Depends(_get_requirement_service),
) -> ComplianceReport:
    """Who may not work today, and what is about to stop them.

    Blocked holders lead the list. The holder population is the register's own
    holders, so ``holder_count`` is what the report could actually assess.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.build_compliance_report(project_id)


@router.get(
    "/summary/",
    response_model=CredentialSummary,
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
@router.get(
    "/summary",
    response_model=CredentialSummary,
    dependencies=[Depends(RequirePermission("credentials.read"))],
    include_in_schema=False,
)
async def get_summary(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: CredentialService = Depends(_get_service),
) -> CredentialSummary:
    """Counts for the register's dashboard tile, all on the derived status."""
    await verify_project_access(project_id, user_id, session)
    return await service.summarise(project_id)


@router.get(
    "/validate/",
    response_model=CredentialsValidationReport,
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
@router.get(
    "/validate",
    response_model=CredentialsValidationReport,
    dependencies=[Depends(RequirePermission("credentials.read"))],
    include_in_schema=False,
)
async def validate_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: RequirementService = Depends(_get_requirement_service),
) -> CredentialsValidationReport:
    """Run the ``credentials`` rule set over the project's register."""
    await verify_project_access(project_id, user_id, session)
    return await service.validate_project(project_id)


@router.post(
    "/refresh-statuses/",
    response_model=RefreshResult,
)
@router.post(
    "/refresh-statuses",
    response_model=RefreshResult,
    include_in_schema=False,
)
async def refresh_statuses(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("credentials.update")),
    service: CredentialService = Depends(_get_service),
) -> RefreshResult:
    """Write the derived status back onto rows that have drifted.

    Reads are already correct without this - they derive the status every time.
    Running it brings the indexed column into line and fires the expiry event
    for anything that lapsed while nobody was editing the register.
    """
    await verify_project_access(project_id, user_id, session)
    examined, updated = await service.refresh_statuses(project_id)
    return RefreshResult(
        project_id=project_id,
        as_of=datetime.now(UTC).date(),
        examined=examined,
        updated=updated,
    )


@router.get(
    "/{credential_id}/",
    response_model=CredentialResponse,
    dependencies=[Depends(RequirePermission("credentials.read"))],
)
async def get_credential(
    credential_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CredentialService = Depends(_get_service),
) -> CredentialResponse:
    """Read a single credential."""
    credential = await service.get_credential_for_caller(credential_id, actor_id=user_id)
    return _to_response(credential)


@router.patch(
    "/{credential_id}/",
    response_model=CredentialResponse,
)
async def update_credential(
    credential_id: uuid.UUID,
    data: CredentialUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("credentials.update")),
    service: CredentialService = Depends(_get_service),
) -> CredentialResponse:
    """Patch a credential. Status is recomputed unless a manual status is set."""
    await service.get_credential_for_caller(credential_id, actor_id=user_id)
    credential = await service.update_credential(credential_id, data, user_id=user_id)
    return _to_response(credential)


@router.delete(
    "/{credential_id}/",
    status_code=204,
)
async def delete_credential(
    credential_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("credentials.delete")),
    service: CredentialService = Depends(_get_service),
) -> None:
    """Delete a credential."""
    await service.get_credential_for_caller(credential_id, actor_id=user_id)
    await service.delete_credential(credential_id)


@router.post(
    "/{credential_id}/verify/",
    response_model=CredentialResponse,
)
async def verify_credential(
    credential_id: uuid.UUID,
    data: CredentialVerifyRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("credentials.update")),
    service: CredentialService = Depends(_get_service),
) -> CredentialResponse:
    """Record that a human checked this credential against its authority.

    Verification is not validity: an expired ticket that was genuinely checked
    is still expired, and this endpoint never changes the status.
    """
    await service.get_credential_for_caller(credential_id, actor_id=user_id)
    credential = await service.verify_credential(credential_id, data, user_id=user_id)
    return _to_response(credential)


__all__ = ["router"]
