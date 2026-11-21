"""Brief endpoints: ``ddc-brief/1`` per project, versioned on every save (contract/README.md §6).

Linked editors may read. Only an ERP session writes: the brief is the ERP's master record and a
confirmation names the person who made it.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.dependencies import SessionDep

from .auth import Principal, PrincipalDep, now_utc, require_project
from .brief_doc import BriefError, apply_confirm, prepare_save
from .brief_models import DesignBrief, DesignBriefVersion

router = APIRouter()

_IF_MATCH = re.compile(r'^\s*(?:W/)?"?(\d+)"?\s*$')


class ConfirmRequest(BaseModel):
    pointers: list[Annotated[str, Field(pattern=r"^(/[^/]+)+$")]] = Field(min_length=1, max_length=500)


class BriefVersionView(BaseModel):
    version: int
    action: str
    saved_by: uuid.UUID
    saved_at: Any


class BriefVersionListResponse(BaseModel):
    items: list[BriefVersionView]
    total: int
    offset: int = 0
    limit: int = 50


def _invalid(exc: BriefError) -> HTTPException:
    return HTTPException(
        422,
        {"message": "The brief does not satisfy ddc-brief/1", "errors": exc.errors[:100]},
    )


def _expected_version(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    m = _IF_MATCH.match(if_match)
    if not m:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "If-Match must carry the brief version")
    return int(m.group(1))


def _require_writer(principal: Principal) -> None:
    if principal.via_link:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The brief is edited in the ERP")


async def _head(session, project_id: uuid.UUID) -> DesignBrief | None:
    return (await session.execute(select(DesignBrief).where(DesignBrief.project_id == project_id))).scalar_one_or_none()


def _send(response: Response, document: dict) -> dict:
    response.headers["ETag"] = f'"{document["version"]}"'
    return document


async def current_brief(session, project_id: uuid.UUID) -> dict | None:
    """The latest document, for the link context."""
    head = await _head(session, project_id)
    return None if head is None else head.document


async def _store(
    session,
    head: DesignBrief | None,
    *,
    project_id,
    expected: int,
    document: dict,
    user_id: uuid.UUID,
    action: str,
    commit: bool = True,
) -> None:
    """Write version ``document['version']`` if the head is still at ``expected``; 409 otherwise.

    ``commit=False`` flushes only, for a caller that owns the transaction (an applied proposal)."""
    if head is None:
        session.add(
            DesignBrief(
                id=uuid.UUID(document["brief_id"]),
                project_id=project_id,
                version=document["version"],
                document=document,
                updated_by=user_id,
            )
        )
    else:
        done = await session.execute(
            update(DesignBrief)
            .where(DesignBrief.id == head.id, DesignBrief.version == expected)
            .values(version=document["version"], document=document, updated_by=user_id, updated_at=now_utc())
        )
        if done.rowcount != 1:
            if commit:
                await session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "The brief was changed by someone else; reload it")
    session.add(
        DesignBriefVersion(
            brief_id=uuid.UUID(document["brief_id"]),
            version=document["version"],
            action=action,
            document=document,
            saved_by=user_id,
        )
    )
    try:
        await (session.commit() if commit else session.flush())
    except IntegrityError as exc:
        if commit:
            await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "The brief was changed by someone else; reload it") from exc


@router.get("/projects/{project_id}/brief")
async def get_brief(
    project_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    response: Response,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> dict:
    await require_project(principal, project_id, session)
    head = await _head(session, project_id)
    await session.commit()
    if head is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No brief yet")
    if version is None or version == head.version:
        return _send(response, head.document)
    row = (
        await session.execute(
            select(DesignBriefVersion).where(
                DesignBriefVersion.brief_id == head.id, DesignBriefVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such brief version")
    return _send(response, row.document)


@router.get("/projects/{project_id}/brief/versions", response_model=BriefVersionListResponse)
async def list_brief_versions(
    project_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> BriefVersionListResponse:
    await require_project(principal, project_id, session)
    head = await _head(session, project_id)
    if head is None:
        return BriefVersionListResponse(items=[], total=0, offset=offset, limit=limit)
    total = (
        await session.execute(
            select(func.count()).select_from(DesignBriefVersion).where(DesignBriefVersion.brief_id == head.id)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(DesignBriefVersion)
            .where(DesignBriefVersion.brief_id == head.id)
            .order_by(DesignBriefVersion.version.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    return BriefVersionListResponse(
        items=[
            BriefVersionView(version=r.version, action=r.action, saved_by=r.saved_by, saved_at=r.created_at)
            for r in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.put("/projects/{project_id}/brief")
async def put_brief(
    project_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    response: Response,
    document: Annotated[dict, Body()],
    if_match: Annotated[str | None, Header()] = None,
    draft: bool = False,
) -> dict:
    """Save a new version. ``If-Match: <version>`` is required once a brief exists.

    ``?draft=true`` accepts a brief that still lacks required values (the form shows it as
    incomplete); it is the only violation a draft may carry.
    """
    await require_project(principal, project_id, session)
    _require_writer(principal)
    expected = _expected_version(if_match)
    head = await _head(session, project_id)
    current = 0 if head is None else head.version
    if head is not None and expected is None:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "Send If-Match with the brief version")
    if expected is not None and expected != current:
        raise HTTPException(status.HTTP_409_CONFLICT, "The brief was changed by someone else; reload it")
    try:
        stored, _withdrawn = prepare_save(
            document,
            None if head is None else head.document,
            project_id=project_id,
            brief_id=uuid.uuid4() if head is None else head.id,
            version=current + 1,
            draft=draft,
        )
    except BriefError as exc:
        raise _invalid(exc) from exc
    await _store(
        session,
        head,
        project_id=project_id,
        expected=current,
        document=stored,
        user_id=principal.user_id,
        action="save",
    )
    return _send(response, stored)


@router.post("/projects/{project_id}/brief/confirm")
async def confirm_brief(
    project_id: uuid.UUID,
    body: ConfirmRequest,
    principal: PrincipalDep,
    session: SessionDep,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    """The caller confirms the values at ``pointers``; each gets confirmed_by/at. New version."""
    await require_project(principal, project_id, session)
    _require_writer(principal)
    expected = _expected_version(if_match)
    head = await _head(session, project_id)
    if head is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No brief yet")
    if expected is not None and expected != head.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "The brief was changed by someone else; reload it")
    try:
        stored = apply_confirm(
            head.document,
            list(dict.fromkeys(body.pointers)),
            user_id=principal.user_id,
            at=now_utc(),
            version=head.version + 1,
        )
    except BriefError as exc:
        raise _invalid(exc) from exc
    await _store(
        session,
        head,
        project_id=project_id,
        expected=head.version,
        document=stored,
        user_id=principal.user_id,
        action="confirm",
    )
    return _send(response, stored)
