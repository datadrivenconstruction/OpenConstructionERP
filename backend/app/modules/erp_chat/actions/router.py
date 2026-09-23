# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""REST endpoints of assistant proposals, mounted under ``/api/v1/erp_chat/actions/``.

    GET    /actions/                    - visible proposals, filters, per-status counts
    GET    /actions/{id}/               - one proposal
    PATCH  /actions/{id}/               - edit a pending proposal (re-validated)
    POST   /actions/{id}/apply/         - apply it under the record's own REST gates
    POST   /actions/{id}/reject/        - decline it
    POST   /actions/apply-batch/        - apply several, each on its own
    POST   /actions/{id}/revert/        - undo an applied one, if nothing changed since

Every refusal is a structured ``detail``: ``{"code", "message", "message_key",
"field_errors"?, "options"?, "params"?}``. ``message`` is what the shared API
client shows; ``code`` is what the dock branches on (``locked``,
``target_changed``, ``changed_since_apply``, ``target_missing``, ``not_pending``, ...).

A domain refusal during apply is not an HTTP error: the action is stored as
``failed`` with the reason and returned with 200, so the card can show it and
offer a retry. Mutations commit here, like the sibling routes, so the events a
domain write defers to commit fire before the response is sent.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from app.dependencies import CurrentUserId, SessionDep
from app.modules.erp_chat.actions.base import ActionError
from app.modules.erp_chat.actions.service import STATUSES, ChatActionService, Viewer
from app.modules.erp_chat.models import ChatAction
from app.modules.erp_chat.schemas import (
    ChatActionBatchError,
    ChatActionBatchRequest,
    ChatActionBatchResponse,
    ChatActionDecisionRequest,
    ChatActionListResponse,
    ChatActionPatchRequest,
    ChatActionResponse,
)

router = APIRouter(prefix="/actions", tags=["ERP Chat actions"])


def _statuses(raw: str | None) -> list[str] | None:
    """``status=proposed`` or ``status=proposed,failed``; unknown values are a 422."""
    if not raw:
        return None
    values = [v.strip() for v in raw.split(",") if v.strip()]
    unknown = [v for v in values if v not in STATUSES]
    if unknown:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "validation_error",
                "message": f"Unknown status: {', '.join(unknown)}. Use {', '.join(STATUSES)}.",
                "message_key": "erp_chat.action.error.validation_error",
            },
        )
    return values or None


async def _one(service: ChatActionService, action: ChatAction, viewer: Viewer) -> ChatActionResponse:
    return (await service.to_dtos([action], viewer))[0]


@router.get("/", response_model=ChatActionListResponse)
async def list_actions(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None, description="One status or a comma-separated list."),
    session_id: uuid.UUID | None = Query(default=None),
    batch_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ChatActionListResponse:
    """Proposals the caller asked for, or that belong to a project the caller can open."""
    statuses = _statuses(status)
    service = ChatActionService(session)
    viewer = await service.viewer(user_id)
    rows, total, counts = await service.list(
        viewer,
        project_id=project_id,
        statuses=statuses,
        session_id=session_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
    return ChatActionListResponse(items=await service.to_dtos(rows, viewer), total=total, counts=counts)


@router.post("/apply-batch/", response_model=ChatActionBatchResponse)
async def apply_batch(
    body: ChatActionBatchRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ChatActionBatchResponse:
    """Apply several proposals. Each succeeds or fails on its own; one failure undoes nothing else."""
    service = ChatActionService(session)
    viewer = await service.viewer(user_id)
    actions, errors = await service.apply_batch(list(body.ids), viewer)
    await session.commit()
    return ChatActionBatchResponse(
        items=await service.to_dtos(actions, viewer),
        errors=[ChatActionBatchError(**e) for e in errors],
    )


@router.get("/{action_id}/", response_model=ChatActionResponse)
async def get_action(action_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> ChatActionResponse:
    """One proposal (404 when it is not the caller's to see)."""
    service = ChatActionService(session)
    viewer = await service.viewer(user_id)
    try:
        action = await service.get_visible(action_id, viewer)
    except ActionError as exc:
        raise exc.to_http() from exc
    return await _one(service, action, viewer)


@router.patch("/{action_id}/", response_model=ChatActionResponse)
async def patch_action(
    action_id: uuid.UUID,
    body: ChatActionPatchRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ChatActionResponse:
    """Edit a pending proposal. Re-validated like a fresh one; the model's original stays on record."""
    service = ChatActionService(session)
    viewer = await service.viewer(user_id)
    try:
        action = await service.patch(action_id, viewer, body.payload)
    except ActionError as exc:
        raise exc.to_http() from exc
    await session.commit()
    return await _one(service, action, viewer)


@router.post("/{action_id}/apply/", response_model=ChatActionResponse)
async def apply_action(action_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> ChatActionResponse:
    """Apply a proposal for the caller, under the gates of the record's own REST route."""
    service = ChatActionService(session)
    viewer = await service.viewer(user_id)
    try:
        action = await service.apply(action_id, viewer)
    except ActionError as exc:
        raise exc.to_http() from exc
    await session.commit()
    return await _one(service, action, viewer)


@router.post("/{action_id}/reject/", response_model=ChatActionResponse)
async def reject_action(
    action_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    body: ChatActionDecisionRequest | None = None,
) -> ChatActionResponse:
    """Decline a pending proposal."""
    service = ChatActionService(session)
    viewer = await service.viewer(user_id)
    try:
        action = await service.reject(action_id, viewer, body.note if body else None)
    except ActionError as exc:
        raise exc.to_http() from exc
    await session.commit()
    return await _one(service, action, viewer)


@router.post("/{action_id}/revert/", response_model=ChatActionResponse)
async def revert_action(
    action_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    body: ChatActionDecisionRequest | None = None,
) -> ChatActionResponse:
    """Undo an applied proposal; 409 ``changed_since_apply`` when it was edited since, ``target_missing`` if gone."""
    service = ChatActionService(session)
    viewer = await service.viewer(user_id)
    try:
        action = await service.revert(action_id, viewer, body.note if body else None)
    except ActionError as exc:
        raise exc.to_http() from exc
    await session.commit()
    return await _one(service, action, viewer)
