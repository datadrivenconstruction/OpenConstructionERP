# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document assistant API (mounted at ``/api/v1/doc-assistant``).

* ``POST /ask``    - grounded answer with citations, or "not found".
* ``POST /saved``  - keep an answer as a note or an RFI draft.
* ``GET  /saved``  - the caller's kept answers on a project.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.doc_assistant.schemas import (
    SOURCE_KINDS,
    AskRequest,
    AskResponse,
    SavedAnswerListResponse,
    SavedAnswerOut,
    SaveRequest,
)
from app.modules.doc_assistant.service import DocAssistantService

router = APIRouter(tags=["doc_assistant"])


def _identity(payload: dict) -> tuple[uuid.UUID, str]:
    try:
        return uuid.UUID(str(payload.get("sub"))), str(payload.get("role") or "viewer")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user") from exc


@router.post("/ask", response_model=AskResponse, dependencies=[Depends(RequirePermission("doc_assistant.ask"))])
async def ask(body: AskRequest, payload: CurrentUserPayload, session: SessionDep) -> AskResponse:
    """Answer a question from the project documents the caller may read."""
    user_id, role = _identity(payload)
    await verify_project_access(body.project_id, str(user_id), session)
    unknown = [k for k in body.kinds if k not in SOURCE_KINDS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown source kinds: {', '.join(unknown)}")
    result = await DocAssistantService(session).ask(
        project_id=body.project_id,
        user_id=user_id,
        role=role,
        question=body.question,
        locale=body.locale,
        kinds=set(body.kinds) or None,
        use_ai=body.use_ai,
    )
    return AskResponse.model_validate(result)


@router.post(
    "/saved",
    response_model=SavedAnswerOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("doc_assistant.save"))],
)
async def save_answer(body: SaveRequest, payload: CurrentUserPayload, session: SessionDep) -> SavedAnswerOut:
    """Keep an answer; citations the caller may no longer read are dropped and the rule set runs."""
    user_id, role = _identity(payload)
    await verify_project_access(body.project_id, str(user_id), session)
    row = await DocAssistantService(session).save(
        project_id=body.project_id,
        user_id=user_id,
        role=role,
        question=body.question,
        answer=body.answer,
        claims=[c.model_dump() for c in body.claims],
        citations=[c.model_dump() for c in body.citations],
        confidence=body.confidence,
        locale=body.locale,
        target=body.target,
        rfi_subject=body.rfi_subject,
    )
    return SavedAnswerOut.model_validate(row)


@router.get("/saved", response_model=SavedAnswerListResponse)
async def list_saved(
    payload: CurrentUserPayload,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> SavedAnswerListResponse:
    """The caller's kept answers on a project, newest first."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    rows, total = await DocAssistantService(session).list_saved(project_id, user_id, limit=limit, offset=offset)
    return SavedAnswerListResponse(
        items=[SavedAnswerOut.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )
