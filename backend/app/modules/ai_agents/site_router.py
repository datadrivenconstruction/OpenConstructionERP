# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site assistant endpoints, mounted under ``/v1/ai-agents/site``.

Every response is one envelope ``{provider_used|null, degraded, items, confidence, ...}``.
Nothing here writes to the diary, an RFI or a meeting except ``/proposals/{id}/confirm``,
which also needs the target module's own write permission.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.i18n import get_locale
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.ai_agents import site

router = APIRouter(prefix="/site", tags=["ai_agents_site"])

_RUN = Depends(RequirePermission("ai_agents.site.run"))
_READ = Depends(RequirePermission("ai_agents.read"))


class BriefingRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    refresh: bool = False


class DiaryDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    diary_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    transcripts: list[str] = Field(default_factory=list, max_length=20)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., max_length=40)
    edits: dict[str, Any] | None = None


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Selection] = Field(default_factory=list, max_length=60)


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=5, max_length=1000)
    proposal_id: uuid.UUID | None = None


class PrefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    enabled: bool = False
    briefing_time: str = Field(default="06:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    enabled_sections: list[str] = Field(default_factory=list, max_length=len(site.BRIEFING_SECTIONS))


def _pref_out(pref: Any, project_id: uuid.UUID) -> dict[str, Any]:
    return {
        "project_id": str(project_id),
        "enabled": bool(pref.enabled) if pref else False,
        "briefing_time": pref.briefing_time if pref else "06:30",
        "enabled_sections": list(pref.enabled_sections or []) if pref else [],
        "available_sections": list(site.BRIEFING_SECTIONS),
    }


@router.post("/briefing/run", dependencies=[_RUN])
async def run_briefing(body: BriefingRunRequest, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(body.project_id, user_id, session)
    envelope = await site.run_briefing(
        session,
        project_id=body.project_id,
        user_id=uuid.UUID(user_id),
        locale=get_locale() or "en",
        refresh=body.refresh,
    )
    await session.commit()
    return envelope


@router.get("/briefing/latest", dependencies=[_READ])
async def latest_briefing(
    user_id: CurrentUserId, session: SessionDep, project_id: uuid.UUID = Query(...)
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    envelope = await site.latest_briefing(session, project_id, uuid.UUID(user_id))
    if envelope is None:
        return {
            "provider_used": None,
            "degraded": True,
            "items": [],
            "confidence": 1.0,
            "exists": False,
            "is_today": False,
        }
    return {**envelope, "exists": True, "is_today": envelope.get("day") == date.today().isoformat()}


@router.get("/prefs", dependencies=[_READ])
async def get_prefs(user_id: CurrentUserId, session: SessionDep, project_id: uuid.UUID = Query(...)) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _pref_out(await site.get_pref(session, project_id, uuid.UUID(user_id)), project_id)


@router.put("/prefs", dependencies=[_RUN])
async def put_prefs(body: PrefIn, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(body.project_id, user_id, session)
    unknown = [s for s in body.enabled_sections if s not in site.BRIEFING_SECTIONS]
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown section: {unknown[0]}")
    from app.modules.ai_agents.models import SiteAssistantPref

    uid = uuid.UUID(user_id)
    pref = await site.get_pref(session, body.project_id, uid)
    if pref is None:
        pref = SiteAssistantPref(project_id=body.project_id, user_id=uid)
        session.add(pref)
    pref.enabled = body.enabled
    pref.briefing_time = body.briefing_time
    pref.enabled_sections = body.enabled_sections
    await session.commit()
    return _pref_out(pref, body.project_id)


@router.post("/diary-draft", dependencies=[_RUN])
async def diary_draft(body: DiaryDraftRequest, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(body.project_id, user_id, session)
    envelope = await site.run_diary_draft(
        session,
        project_id=body.project_id,
        user_id=uuid.UUID(user_id),
        diary_date=body.diary_date,
        transcripts=body.transcripts,
        locale=get_locale() or "en",
    )
    await session.commit()
    return envelope


@router.post("/rfi-check/{rfi_id}", dependencies=[_RUN])
async def rfi_check(rfi_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    from app.modules.rfi.models import RFI

    rfi = await session.get(RFI, rfi_id)
    if rfi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFI not found")
    await verify_project_access(rfi.project_id, user_id, session)
    envelope = await site.run_rfi_check(
        session, rfi_id=rfi_id, project_id=rfi.project_id, user_id=uuid.UUID(user_id), locale=get_locale() or "en"
    )
    await session.commit()
    return envelope


@router.post("/rfi-check/{rfi_id}/override", dependencies=[_RUN])
async def rfi_check_override(
    rfi_id: uuid.UUID, body: OverrideRequest, user_id: CurrentUserId, session: SessionDep
) -> dict[str, Any]:
    from app.modules.rfi.models import RFI

    rfi = await session.get(RFI, rfi_id)
    if rfi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFI not found")
    await verify_project_access(rfi.project_id, user_id, session)
    out = await site.record_rfi_override(
        session, rfi_id=rfi_id, user_id=uuid.UUID(user_id), reason=body.reason.strip(), proposal_id=body.proposal_id
    )
    await session.commit()
    return out


@router.post("/meeting-actions/{meeting_id}", dependencies=[_RUN])
async def meeting_actions(meeting_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    from app.modules.meetings.models import Meeting

    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    await verify_project_access(meeting.project_id, user_id, session)
    envelope = await site.run_meeting_actions(
        session,
        meeting_id=meeting_id,
        project_id=meeting.project_id,
        user_id=uuid.UUID(user_id),
        locale=get_locale() or "en",
    )
    await session.commit()
    return envelope


@router.get("/proposals/{proposal_id}", dependencies=[_READ])
async def get_proposal(proposal_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    run, envelope = await site.load_proposal(session, proposal_id)
    if str(run.user_id) != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if run.project_id is not None:
        await verify_project_access(run.project_id, user_id, session)
    return envelope


@router.post("/proposals/{proposal_id}/confirm", dependencies=[_RUN])
async def confirm_proposal(
    proposal_id: uuid.UUID,
    body: ConfirmRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    run, envelope = await site.load_proposal(session, proposal_id)
    permission = site.CONFIRM_PERMISSION.get(str(envelope.get("kind")))
    if permission is not None:
        # Writing needs the target module's own permission, not just the right to run assistants.
        await RequirePermission(permission)(payload)
    if run.project_id is not None:
        await verify_project_access(run.project_id, user_id, session)
    out = await site.confirm_proposal(
        session,
        proposal_id=proposal_id,
        user_id=uuid.UUID(user_id),
        selections=[s.model_dump() for s in body.items],
    )
    await session.commit()
    return out


@router.post("/proposals/{proposal_id}/reject", dependencies=[_RUN])
async def reject_proposal(
    proposal_id: uuid.UUID, body: RejectRequest, user_id: CurrentUserId, session: SessionDep
) -> dict[str, Any]:
    run, _ = await site.load_proposal(session, proposal_id)
    if run.project_id is not None:
        await verify_project_access(run.project_id, user_id, session)
    out = await site.reject_proposal(session, proposal_id=proposal_id, user_id=uuid.UUID(user_id), reason=body.reason)
    await session.commit()
    return out
