# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ routes for clarifications, the tender timeline, addenda validation and the bidder side.

Included by ``router.py``. Buyer routes are guarded like the neighbouring
package routes (declared permission plus project access); bidder routes are
public and keyed by the bidder link token, rate-limited like the bid portal.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.validation.engine import ValidationContext, rule_registry
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.tendering.addenda import AddendaService, published_addenda, timeline
from app.modules.tendering.bid_portal import BidPortalService, enforce_rate_limit
from app.modules.tendering.schemas import (
    AddendumCreate,
    AddendumResponse,
    ClarificationAnswer,
    ClarificationCreate,
    ClarificationResponse,
    PublicClarification,
    TenderTimelineResponse,
    TimelineEvent,
)
from app.modules.tendering.service import TenderingService
from app.modules.tendering.validators import ADDENDA_RULE_SET

router = APIRouter()


class PortalQuestion(BaseModel):
    """A question a bidder asks through its link."""

    question: str = Field(..., min_length=3, max_length=5000)


async def _package(session: SessionDep, package_id: uuid.UUID, user_id: str) -> Any:
    package = await TenderingService(session).get_package(package_id)
    await verify_project_access(package.project_id, user_id, session)
    return package


def _days_left(package: Any, row: Any) -> int | None:
    from datetime import UTC, datetime

    from app.modules.tendering.addenda import closing_date

    close = closing_date(package.deadline)
    if close is None:
        return None
    ref = row.answered_at.date() if row.answered_at else datetime.now(UTC).date()
    return (close - ref).days


def _out(package: Any, row: Any) -> ClarificationResponse:
    out = ClarificationResponse.model_validate(row)
    out.days_before_closing = _days_left(package, row)
    return out


# ── Clarifications (buyer) ─────────────────────────────────────────────────


@router.get("/packages/{package_id}/clarifications/", response_model=list[ClarificationResponse])
async def list_clarifications(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.clarification.read")),
) -> list[ClarificationResponse]:
    """Every question on the package, the asker included (buyer view)."""
    package = await _package(session, package_id, user_id)
    return [_out(package, r) for r in await AddendaService(session).list_clarifications(package_id)]


@router.post("/packages/{package_id}/clarifications/", response_model=ClarificationResponse, status_code=201)
async def create_clarification(
    package_id: uuid.UUID,
    data: ClarificationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.clarification.manage")),
) -> ClarificationResponse:
    """Record a question a bidder sent by mail or phone."""
    package = await _package(session, package_id, user_id)
    row = await AddendaService(session).ask(package, data.question, data.recipient_id, data.asked_by_email, user_id)
    return _out(package, row)


@router.post("/packages/{package_id}/clarifications/{clarification_id}/answer/", response_model=ClarificationResponse)
async def answer_clarification(
    package_id: uuid.UUID,
    clarification_id: uuid.UUID,
    data: ClarificationAnswer,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.clarification.manage")),
) -> ClarificationResponse:
    """Draft or change the answer; bidders see nothing until it is published."""
    package = await _package(session, package_id, user_id)
    svc = AddendaService(session)
    row = await svc.answer(await svc.get_clarification(package_id, clarification_id), data.answer, user_id)
    return _out(package, row)


@router.post("/packages/{package_id}/clarifications/{clarification_id}/publish/", response_model=ClarificationResponse)
async def publish_clarification(
    package_id: uuid.UUID,
    clarification_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.clarification.publish")),
) -> ClarificationResponse:
    """Publish the answer to every invited firm, without naming who asked."""
    package = await _package(session, package_id, user_id)
    svc = AddendaService(session)
    row = await svc.publish_answer(package, await svc.get_clarification(package_id, clarification_id), user_id)
    return _out(package, row)


@router.post(
    "/packages/{package_id}/clarifications/{clarification_id}/promote/",
    response_model=AddendumResponse,
    status_code=201,
)
async def promote_clarification(
    package_id: uuid.UUID,
    clarification_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.addendum.create")),
) -> AddendumResponse:
    """Turn an answer into a draft addendum, so it binds bidders and needs acknowledging."""
    package = await _package(session, package_id, user_id)
    svc = AddendaService(session)
    row = await svc.get_clarification(package_id, clarification_id)
    if not row.answer:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Answer the question before promoting it")
    if row.addendum_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already promoted into an addendum")
    created = await TenderingService(session).create_addendum(
        package.id,
        AddendumCreate(
            title=f"Q{row.number}: {row.question[:180]}",
            body=f"{row.question}\n\n{row.answer}",
            source_clarification_id=row.id,
        ),
    )
    row.addendum_id = created.id
    await session.flush()
    return created


# ── Timeline and validation (buyer) ─────────────────────────────────────────


@router.get("/packages/{package_id}/timeline/", response_model=TenderTimelineResponse)
async def tender_timeline(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> TenderTimelineResponse:
    """Issued, questions closed, each addendum, closing; with the rules that dated them."""
    from datetime import UTC, datetime

    package = await _package(session, package_id, user_id)
    rules = await AddendaService(session).rules(package)
    events = timeline(package.metadata_, package.deadline, rules, datetime.now(UTC).date())
    return TenderTimelineResponse(
        package_id=package_id, events=[TimelineEvent(**e) for e in events], rules=rules.as_dict()
    )


@router.get("/packages/{package_id}/addenda/validation/")
async def validate_addenda(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> dict:
    """Run the ``tendering_addenda`` rule set over the package."""
    package = await _package(session, package_id, user_id)
    bids = await TenderingService(session).repo.list_bids_for_package(package_id)
    data = await AddendaService(session).validation_data(package, bids)
    context = ValidationContext(data=data, project_id=str(package.project_id))
    results = []
    for rule in rule_registry.get_rules_for_sets([ADDENDA_RULE_SET]):
        for result in await rule.validate(context):
            results.append(
                {
                    "rule_id": result.rule_id,
                    "severity": str(result.severity),
                    "passed": result.passed,
                    "message": result.message,
                    "element_ref": result.element_ref,
                    "suggestion": result.suggestion,
                }
            )
    errors = [r for r in results if not r["passed"] and r["severity"].lower().endswith("error")]
    return {"package_id": str(package_id), "passed": not errors, "results": results, "rules": data["rules"]}


# ── Bidder side (public, by link token) ─────────────────────────────────────


def _portal_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/bid-portal/{token}/tender-info/")
async def portal_tender_info(token: str, request: Request, response: Response, session: SessionDep) -> dict:
    """Public: published addenda (with this firm's acknowledgement) and published answers."""
    enforce_rate_limit(request, write=False)
    _portal_headers(response)
    invitation = await BidPortalService(session).resolve_live(token)
    package = await TenderingService(session).get_package(invitation.package_id)
    rid = str(invitation.recipient_id)
    addenda = [
        {
            "id": a.get("id"),
            "revision_no": a.get("revision_no"),
            "title": a.get("title"),
            "body": a.get("body"),
            "published_at": a.get("published_at"),
            "new_deadline": a.get("new_deadline"),
            "boq_revision_no": a.get("boq_revision_no"),
            "document_changes": a.get("document_changes") or [],
            "acknowledged": any(str(x.get("bidder_id")) == rid for x in a.get("acknowledged_by") or []),
        }
        for a in published_addenda(package.metadata_)
    ]
    answers = await AddendaService(session).public_clarifications(package.id)
    return {
        "deadline": package.deadline,
        "current_boq_revision": int((package.metadata_ or {}).get("boq_revision_no") or 0),
        "addenda": addenda,
        "clarifications": [PublicClarification(**c).model_dump(mode="json") for c in answers],
    }


@router.post("/bid-portal/{token}/questions/", status_code=201)
async def portal_ask(
    token: str, body: PortalQuestion, request: Request, response: Response, session: SessionDep
) -> dict:
    """Public: a bidder asks a question. Its firm is recorded for the buyer only."""
    enforce_rate_limit(request, write=True)
    _portal_headers(response)
    invitation = await BidPortalService(session).resolve_live(token)
    package = await TenderingService(session).get_package(invitation.package_id)
    row = await AddendaService(session).ask(package, body.question, invitation.recipient_id, invitation.email, None)
    return {"number": row.number, "status": row.status}


@router.post("/bid-portal/{token}/addenda/{addendum_id}/acknowledge/")
async def portal_acknowledge(
    token: str, addendum_id: str, request: Request, response: Response, session: SessionDep
) -> dict:
    """Public: the bidder acknowledges receipt of a published addendum."""
    enforce_rate_limit(request, write=True)
    _portal_headers(response)
    invitation = await BidPortalService(session).resolve_live(token)
    service = TenderingService(session)
    package = await service.get_package(invitation.package_id)
    if not any(str(a.get("id")) == addendum_id for a in published_addenda(package.metadata_)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Addendum not found")
    await service.acknowledge_addendum(package, addendum_id, str(invitation.recipient_id), None)
    return {"addendum_id": addendum_id, "acknowledged": True}
