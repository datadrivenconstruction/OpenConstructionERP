# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cases API routes.

Mounted at ``/api/v1/cases/``.

    GET    /                      - cases the caller may read
    POST   /                      - write a new case
    GET    /{case_id}             - one case
    PUT    /{case_id}             - replace a case (owner only)
    DELETE /{case_id}             - delete a case and its pins (owner only)
    POST   /{case_id}/duplicate   - fork a readable case into your own

    GET    /pins/                 - the caller's pinned cases
    POST   /pins/                 - pin a case to a project
    DELETE /pins/                 - unpin
    POST   /pins/reorder          - set the pin order for one project

The pin routes are declared before ``/{case_id}`` on purpose. Declared the
other way round, ``/pins/`` is a candidate match for the case-detail route and
the request dies as a malformed UUID instead of reaching the handler.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.validation.engine import RuleResult
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.cases.models import UserCase
from app.modules.cases.schemas import (
    CaseCreateRequest,
    CaseDuplicateRequest,
    CaseFinding,
    CaseResponse,
    CaseSaveResponse,
    CaseUpdateRequest,
    PinReorderRequest,
    PinRequest,
    PinResponse,
)
from app.modules.cases.service import (
    add_pin,
    can_edit,
    create_case,
    delete_case,
    duplicate_case,
    get_case,
    list_cases,
    list_pins,
    remove_pin,
    reorder_pins,
    update_case,
)
from app.modules.cases.validators import blocking_findings, evaluate_case

router = APIRouter(tags=["cases"])


def _user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier",
        ) from exc


def _to_response(case: UserCase, viewer_id: uuid.UUID) -> CaseResponse:
    payload = CaseResponse.model_validate(case)
    payload.can_edit = can_edit(case, viewer_id)
    return payload


def _finding_key(result: RuleResult) -> str:
    """The i18n key a finding is rendered under.

    A rule that crashed may not be shown under its own rule's key. That key
    holds the sentence describing what the rule looks for, so printing it would
    tell the author the check ran and their case failed it, when in fact the
    check never ran at all. Engine failures share one key of their own.
    """
    if result.is_engine_error:
        return "cases.validation.engine_error"
    return f"cases.validation.{result.rule_id}"


def _to_findings(results: list[RuleResult]) -> list[CaseFinding]:
    return [
        CaseFinding(
            key=_finding_key(result),
            rule_id=result.rule_id,
            severity=str(result.severity),
            message=result.message,
            suggestion=result.suggestion or "",
            details=dict(result.details or {}),
            is_engine_error=result.is_engine_error,
        )
        for result in results
    ]


async def _validated(body: CaseCreateRequest | CaseUpdateRequest, case_id: str = "") -> list[RuleResult]:
    """Run the case rules and refuse to *publish* anything with an error.

    A draft may be as rough as its author likes, so a private save never
    blocks. Sharing is a claim that the case is worth a colleague's time, and
    an ERROR finding is exactly the evidence that it is not yet.
    """
    findings = await evaluate_case(body.model_dump(), case_id=case_id)
    if body.is_shared:
        blocking = blocking_findings(findings)
        if blocking:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "message": "This case cannot be shared until its errors are fixed.",
                    "findings": [f.model_dump() for f in _to_findings(blocking)],
                },
            )
    return findings


# ── Pins ─────────────────────────────────────────────────────────────────────


@router.get(
    "/pins/",
    response_model=list[PinResponse],
    dependencies=[Depends(RequirePermission("cases.read"))],
)
async def list_my_pins(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(None),
) -> list[PinResponse]:
    """The caller's pinned cases, in the order they arranged them."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    rows = await list_pins(session, user_id=_user_uuid(user_id), project_id=project_id)
    return [PinResponse.model_validate(row) for row in rows]


@router.post(
    "/pins/",
    response_model=PinResponse,
    dependencies=[Depends(RequirePermission("cases.write"))],
)
async def pin_case(
    payload: PinRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    response: Response,
) -> PinResponse:
    """Pin a case to a project. Idempotent; 201 on first pin, 200 after."""
    await verify_project_access(payload.project_id, user_id, session)
    uid = _user_uuid(user_id)
    if payload.case_source == "custom":
        # Pinning a case nobody can read would put an unresolvable row in the
        # strip, so the target is checked before the pin is written.
        try:
            target = uuid.UUID(payload.case_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A custom case id must be the case UUID.",
            ) from exc
        if await get_case(session, case_id=target, user_id=uid) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    row, created = await add_pin(
        session,
        user_id=uid,
        project_id=payload.project_id,
        case_source=payload.case_source,
        case_id=payload.case_id,
        sort_order=payload.sort_order,
        note=payload.note,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return PinResponse.model_validate(row)


@router.delete(
    "/pins/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("cases.write"))],
)
async def unpin_case(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    case_source: str = Query(..., min_length=1, max_length=16),
    case_id: str = Query(..., min_length=1, max_length=128),
) -> None:
    """Unpin a case. Idempotent - a missing pin still returns 204."""
    await verify_project_access(project_id, user_id, session)
    await remove_pin(
        session,
        user_id=_user_uuid(user_id),
        project_id=project_id,
        case_source=case_source,
        case_id=case_id,
    )


@router.post(
    "/pins/reorder",
    response_model=list[PinResponse],
    dependencies=[Depends(RequirePermission("cases.write"))],
)
async def reorder_my_pins(
    payload: PinReorderRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[PinResponse]:
    """Set the order of the caller's pins on one project."""
    await verify_project_access(payload.project_id, user_id, session)
    rows = await reorder_pins(
        session,
        user_id=_user_uuid(user_id),
        project_id=payload.project_id,
        pin_ids=payload.pin_ids,
    )
    return [PinResponse.model_validate(row) for row in rows]


# ── Cases ────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[CaseResponse],
    dependencies=[Depends(RequirePermission("cases.read"))],
)
async def list_my_cases(
    session: SessionDep,
    user_id: CurrentUserId,
    category: str | None = Query(None, max_length=32),
    mine_only: bool = Query(False),
) -> list[CaseResponse]:
    """Cases the caller may read: their own, plus everyone's shared ones."""
    uid = _user_uuid(user_id)
    rows = await list_cases(session, user_id=uid, category=category, mine_only=mine_only)
    return [_to_response(row, uid) for row in rows]


@router.post(
    "/",
    response_model=CaseSaveResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cases.write"))],
)
async def create_my_case(
    payload: CaseCreateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CaseSaveResponse:
    """Write a new case owned by the caller."""
    findings = await _validated(payload)
    uid = _user_uuid(user_id)
    case = await create_case(session, owner_id=uid, body=payload)
    return CaseSaveResponse(case=_to_response(case, uid), findings=_to_findings(findings))


@router.get(
    "/{case_id}",
    response_model=CaseResponse,
    dependencies=[Depends(RequirePermission("cases.read"))],
)
async def read_case(
    case_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CaseResponse:
    """One case, if the caller may read it."""
    uid = _user_uuid(user_id)
    case = await get_case(session, case_id=case_id, user_id=uid)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return _to_response(case, uid)


@router.put(
    "/{case_id}",
    response_model=CaseSaveResponse,
    dependencies=[Depends(RequirePermission("cases.write"))],
)
async def replace_case(
    case_id: uuid.UUID,
    payload: CaseUpdateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CaseSaveResponse:
    """Replace a case. Only the author may write to it."""
    uid = _user_uuid(user_id)
    case = await get_case(session, case_id=case_id, user_id=uid)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if not can_edit(case, uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A shared case can be read and copied, but only its author can change it.",
        )
    findings = await _validated(payload, case_id=str(case_id))
    updated = await update_case(session, case=case, body=payload)
    return CaseSaveResponse(case=_to_response(updated, uid), findings=_to_findings(findings))


@router.delete(
    "/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("cases.write"))],
)
async def remove_case(
    case_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Delete a case and every pin pointing at it. Only the author may."""
    uid = _user_uuid(user_id)
    case = await get_case(session, case_id=case_id, user_id=uid)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if not can_edit(case, uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A shared case can be read and copied, but only its author can delete it.",
        )
    await delete_case(session, case=case)


@router.post(
    "/{case_id}/duplicate",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cases.write"))],
)
async def fork_case(
    case_id: uuid.UUID,
    payload: CaseDuplicateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CaseResponse:
    """Fork any readable case into a new private case owned by the caller."""
    uid = _user_uuid(user_id)
    source = await get_case(session, case_id=case_id, user_id=uid)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    copy = await duplicate_case(session, source=source, owner_id=uid, title=payload.title)
    return _to_response(copy, uid)
