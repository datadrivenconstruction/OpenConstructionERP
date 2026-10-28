# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Event-reconciliation API routes (auto-mounted at /api/v1/reconciliation).

Assembles the reconciled cross-channel thread for one event and persists a
reviewer's confirm / reject decisions on the engine's suggested links. Every
route is project-scoped: the caller must hold the module capability (read or
write) and pass :func:`verify_project_access` for the project, which 404s on
both "missing" and "denied" so it never leaks project existence. A decision
endpoint takes the project id in its path for the same reason - a link can only
be confirmed or rejected within a project the caller may reach.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.reconciliation.models import RecordLink
from app.modules.reconciliation.schemas import (
    EventThreadOut,
    RecordLinkDecisionIn,
    RecordLinkOut,
    ThreadLinkOut,
    ThreadRecordOut,
)
from app.modules.reconciliation.service import (
    EventThread,
    build_event_thread,
    decide_record_link,
    gather_candidates,
    list_record_links,
)

router = APIRouter(tags=["Reconciliation"])


def _thread_out(thread: EventThread) -> EventThreadOut:
    """Render an assembled :class:`EventThread` onto its wire schema."""
    return EventThreadOut(
        project_id=thread.project_id,
        event_key=thread.event_key,
        seed_type=thread.seed_type,
        seed_id=thread.seed_id,
        records=[
            ThreadRecordOut(
                record_type=tr.record.record_type,
                record_id=tr.record.record_id,
                subject=tr.record.subject or "",
                party=tr.record.party,
                occurred_at=(tr.record.occurred_at.isoformat() if tr.record.occurred_at else None),
                refs=list(tr.record.refs),
                is_seed=tr.is_seed,
            )
            for tr in thread.records
        ],
        links=[
            ThreadLinkOut(
                link_id=tl.link_id,
                left_type=tl.link.left_type,
                left_id=tl.link.left_id,
                right_type=tl.link.right_type,
                right_id=tl.link.right_id,
                relation=tl.link.relation,
                confidence=tl.link.confidence,
                reasons=list(tl.link.reasons),
                status=tl.status,
            )
            for tl in thread.links
        ],
        confirmed_count=thread.confirmed_count,
        rejected_count=thread.rejected_count,
    )


def _link_out(row: RecordLink, subjects: dict[tuple[str, str], str] | None = None) -> RecordLinkOut:
    """Render a persisted :class:`RecordLink` row onto its wire schema.

    Args:
        row: The stored decision.
        subjects: Subject lines keyed by ``(record_type, record_id)``, used to
            name both endpoints. Omitted where the caller has no projection to
            hand, which leaves the subjects null rather than guessing.
    """
    lookup = subjects or {}
    left_type, left_id = row.left_type or "", row.left_id or ""
    right_type, right_id = row.right_type or "", row.right_id or ""
    return RecordLinkOut(
        id=str(row.id),
        project_id=str(row.project_id),
        left_type=left_type,
        left_id=left_id,
        left_subject=lookup.get((left_type, left_id)) or None,
        right_type=right_type,
        right_id=right_id,
        right_subject=lookup.get((right_type, right_id)) or None,
        relation=row.relation or "same_event",
        confidence=float(row.confidence if row.confidence is not None else 0),
        status=row.status or "",
        created_by=row.created_by,
    )


@router.get(
    "/projects/{project_id}/events/{event_key}/thread",
    response_model=EventThreadOut,
    dependencies=[Depends(RequirePermission("reconciliation.read"))],
)
async def get_event_thread(
    project_id: uuid.UUID,
    event_key: str,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> EventThreadOut:
    """Assemble the reconciled cross-channel thread for one event.

    ``event_key`` is either a seed record key ``"<record_type>:<record_id>"``
    (for example ``change_order:<uuid>``) or a normalized-subject key; the
    response echoes the resolved ``seed_type`` / ``seed_id`` (null for a
    subject key). The thread is the connected component of records reachable
    from the seed through links at or above the engine threshold, excluding any
    rejected link, with the scored links among them and a count of the persisted
    confirm / reject decisions reflected.
    """
    await verify_project_access(project_id, user_id or "", session)
    thread = await build_event_thread(session, project_id, event_key)
    return _thread_out(thread)


@router.get(
    "/projects/{project_id}/record-links",
    response_model=list[RecordLinkOut],
    dependencies=[Depends(RequirePermission("reconciliation.read"))],
)
async def list_project_record_links(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[RecordLinkOut]:
    """List every persisted confirm / reject decision recorded for a project."""
    await verify_project_access(project_id, user_id or "", session)
    rows = await list_record_links(session, project_id)
    if not rows:
        return []
    # One projection for the page names every endpoint on it. The log is read
    # away from the threads the decisions were taken in, so there is nothing on
    # the client to resolve an id against; without this the whole list reads
    # "correspondence 69441ec3..." twice per row.
    subjects = {(rec.record_type, rec.record_id): rec.subject for rec in await gather_candidates(session, project_id)}
    return [_link_out(row, subjects) for row in rows]


@router.post(
    "/projects/{project_id}/record-links",
    response_model=RecordLinkOut,
    dependencies=[Depends(RequirePermission("reconciliation.write"))],
)
async def decide_project_record_link(
    project_id: uuid.UUID,
    payload: RecordLinkDecisionIn,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> RecordLinkOut:
    """Confirm or reject a suggested correlation, persisting the decision.

    The link is named by its canonical endpoints (the ``(type, id)`` pairs the
    thread view returns) and ``relation``; re-posting updates the existing
    decision rather than duplicating it. ``status`` must be ``confirmed`` or
    ``rejected`` (anything else is a 422). The decision is fenced to the project
    in the path - a link cannot be ruled on under a project the caller cannot
    reach.
    """
    await verify_project_access(project_id, user_id or "", session)
    try:
        row = await decide_record_link(
            session,
            project_id,
            left=(payload.left_type, payload.left_id),
            right=(payload.right_type, payload.right_id),
            relation=payload.relation or "same_event",
            status=payload.status,
            confidence=payload.confidence,
            created_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _link_out(row)
