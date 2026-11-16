# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document templates API, mounted at ``/api/v1/doc-templates/``.

GET    /                              - Documents and Emails list
GET    /managers                      - users and their Document manager role (admin)
PUT    /managers/{user_id}            - grant or revoke the role (admin)
GET    /{kind}?locale=                - editor state
PUT    /{kind}/draft?locale=          - save the working text
DELETE /{kind}/draft?locale=          - discard it
POST   /{kind}/publish?locale=        - publish the draft as a new version
POST   /{kind}/versions/{id}/restore  - publish a copy of an old version
POST   /{kind}/reset?locale=          - publish "no overrides"
GET    /{kind}/records                - records "Preview with" can use
POST   /{kind}/preview?locale=        - PDF or email HTML of an unsaved text
POST   /{kind}/test-send?locale=      - email kinds: send to the caller's own address
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
)
from app.modules.doc_templates import service
from app.modules.doc_templates.permissions import DOC_MANAGER_KEY, is_doc_manager
from app.modules.doc_templates.schemas import (
    DraftIn,
    EditorState,
    IssueOut,
    KindListResponse,
    KindSummary,
    ManagerIn,
    ManagerOut,
    PreviewEmailOut,
    PreviewIn,
    PublishIn,
    RecordOut,
    TestSendOut,
)

router = APIRouter(tags=["doc_templates"])

_READ = [Depends(RequirePermission("doc_templates.read"))]
_LOCALE = Query("en", max_length=10)


async def _user(session: Any, user_id: str) -> Any:
    from app.modules.users.models import User

    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user


async def _require_manager(session: Any, user_id: str, payload: dict[str, Any]) -> Any:
    user = await _user(session, user_id)
    if not is_doc_manager(payload.get("role") or user.role, user.metadata_):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: doc_templates.edit")
    return user


def _require_admin(payload: dict[str, Any]) -> None:
    if (payload.get("role") or "") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins grant the Document manager role")


async def _state(session: Any, kind_key: str, locale: str, payload: dict[str, Any], user_id: str) -> EditorState:
    kind = service.require_kind(kind_key)
    countries = await service.workspace_countries(session, payload, user_id)
    return EditorState.model_validate(await service.editor_state(session, kind, locale, countries))


@router.get("/", response_model=KindListResponse, dependencies=_READ)
async def list_kinds(session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload) -> KindListResponse:
    """Every document and email whose module is enabled, with its wording status."""
    from app.config import get_settings
    from app.core.email.service import email_delivery_enabled

    user = await _user(session, user_id)
    items = [KindSummary.model_validate(row) for row in await service.list_kinds(session)]
    return KindListResponse(
        items=items,
        total=len(items),
        can_edit=is_doc_manager(payload.get("role") or user.role, user.metadata_),
        email_enabled=email_delivery_enabled(get_settings()),
    )


@router.get("/managers", response_model=list[ManagerOut], dependencies=_READ)
async def list_managers(session: SessionDep, payload: CurrentUserPayload) -> list[ManagerOut]:
    """Active users and whether each holds the Document manager role."""
    from sqlalchemy import select

    from app.modules.users.models import User

    _require_admin(payload)
    rows = (
        await session.execute(
            select(User).where(User.is_active.is_(True), User.deleted_at.is_(None)).order_by(User.email).limit(500)
        )
    ).scalars()
    return [
        ManagerOut(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name or "",
            role=u.role,
            is_manager=is_doc_manager(u.role, u.metadata_),
        )
        for u in rows
    ]


@router.put("/managers/{target_id}", response_model=ManagerOut, dependencies=_READ)
async def set_manager(
    target_id: uuid.UUID, body: ManagerIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> ManagerOut:
    """Grant or revoke the Document manager role. Admins hold it implicitly."""
    from app.core.audit import audit_log

    _require_admin(payload)
    target = await _user(session, str(target_id))
    metadata = dict(target.metadata_ or {})
    if body.is_manager:
        metadata[DOC_MANAGER_KEY] = True
    else:
        metadata.pop(DOC_MANAGER_KEY, None)
    target.metadata_ = metadata
    await audit_log(
        session,
        action="doc_manager_grant" if body.is_manager else "doc_manager_revoke",
        entity_type="user",
        entity_id=str(target.id),
        user_id=user_id,
    )
    await session.commit()
    return ManagerOut(
        user_id=target.id,
        email=target.email,
        full_name=target.full_name or "",
        role=target.role,
        is_manager=is_doc_manager(target.role, target.metadata_),
    )


@router.get("/{kind_key}", response_model=EditorState, dependencies=_READ)
async def get_editor(
    kind_key: str, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload, locale: str = _LOCALE
) -> EditorState:
    """Editor state for one kind and language."""
    return await _state(session, kind_key, locale, payload, user_id)


@router.put("/{kind_key}/draft", response_model=EditorState, dependencies=_READ)
async def save_draft(
    kind_key: str,
    body: DraftIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    locale: str = _LOCALE,
) -> EditorState:
    """Save the working text; it is not used by any document until published."""
    await _require_manager(session, user_id, payload)
    kind = service.require_kind(kind_key)
    options = body.options.model_dump() if body.options else None
    await service.save_draft(session, kind, locale, body.blocks, options, user_id)
    await session.commit()
    return await _state(session, kind_key, locale, payload, user_id)


@router.delete("/{kind_key}/draft", response_model=EditorState, dependencies=_READ)
async def discard_draft(
    kind_key: str, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload, locale: str = _LOCALE
) -> EditorState:
    """Drop the working text."""
    await _require_manager(session, user_id, payload)
    await service.discard_draft(session, service.require_kind(kind_key), locale)
    await session.commit()
    return await _state(session, kind_key, locale, payload, user_id)


@router.post("/{kind_key}/publish", response_model=EditorState, dependencies=_READ)
async def publish(
    kind_key: str,
    body: PublishIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    locale: str = _LOCALE,
) -> EditorState:
    """Publish the draft as a new version. A text with errors is refused (422)."""
    await _require_manager(session, user_id, payload)
    await service.publish(session, service.require_kind(kind_key), locale, body.note, user_id)
    await session.commit()
    return await _state(session, kind_key, locale, payload, user_id)


@router.post("/{kind_key}/versions/{version_id}/restore", response_model=EditorState, dependencies=_READ)
async def restore(
    kind_key: str,
    version_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    locale: str = _LOCALE,
) -> EditorState:
    """Publish a copy of an older version; history is kept."""
    await _require_manager(session, user_id, payload)
    await service.restore(session, service.require_kind(kind_key), locale, version_id, user_id)
    await session.commit()
    return await _state(session, kind_key, locale, payload, user_id)


@router.post("/{kind_key}/reset", response_model=EditorState, dependencies=_READ)
async def reset(
    kind_key: str, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload, locale: str = _LOCALE
) -> EditorState:
    """Publish a version with no overrides: the built-in wording prints again."""
    await _require_manager(session, user_id, payload)
    await service.reset(session, service.require_kind(kind_key), locale, user_id)
    await session.commit()
    return await _state(session, kind_key, locale, payload, user_id)


@router.get("/{kind_key}/records", response_model=list[RecordOut], dependencies=_READ)
async def records(kind_key: str, session: SessionDep, user_id: CurrentUserId) -> list[RecordOut]:
    """Records of projects the caller can open that "Preview with" can use."""
    kind = service.require_kind(kind_key)
    if kind.records is None:
        return []
    ids = await accessible_project_ids(session, user_id)
    return [RecordOut(id=rid, label=label) for rid, label in await kind.records(session, ids)]


@router.post("/{kind_key}/preview", response_model=None, dependencies=_READ)
async def preview(
    kind_key: str,
    body: PreviewIn,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = _LOCALE,
) -> Response | PreviewEmailOut:
    """Render an unsaved text: a PDF, or for emails the subject and HTML."""
    kind = service.require_kind(kind_key)
    blocks = service.clean_blocks(kind, body.blocks)
    issues = [IssueOut.model_validate(i.as_dict()) for i in service.issues_of(kind, blocks)]
    if kind.channel == "email" and not body.record_id:
        values = service.sample_values(kind)
        lang = service.normalise_locale(locale)
        full = {
            b: blocks.get(b) if (blocks.get(b) or "").strip() else kind.default_blocks(lang).get(b, "")
            for b in kind.blocks
        }
        subject, page = service.render_email(kind, full, values, lang)
        return PreviewEmailOut(subject=subject, html=page, issues=issues)
    ids = await accessible_project_ids(session, user_id)
    options = body.options.model_dump() if body.options else {}
    try:
        data, media = await service.preview(session, kind, locale, blocks, options, body.record_id, ids)
    except TimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Preview took too long") from exc
    except asyncio.CancelledError:
        raise
    if media.startswith("text/html"):
        return PreviewEmailOut(subject="", html=data.decode("utf-8", "replace"), issues=issues)
    return Response(content=data, media_type=media, headers={"Cache-Control": "no-store"})


@router.post("/{kind_key}/test-send", response_model=TestSendOut, dependencies=_READ)
async def test_send(
    kind_key: str,
    body: PreviewIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    locale: str = _LOCALE,
) -> TestSendOut:
    """Send the draft of an email to the signed-in user's own address only."""
    user = await _require_manager(session, user_id, payload)
    kind = service.require_kind(kind_key)
    sent, detail = await service.send_test(kind, locale, service.clean_blocks(kind, body.blocks), user.email)
    return TestSendOut(sent=sent, to=user.email, detail=detail)
