# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Turning a change on a request into something that finds the right person.

Who hears what:
    raised            -> the department's lead and members
    stage / status    -> the requester
    needs-info        -> the requester
    answer            -> the department (lead, members, assignees)
    mention           -> the mentioned people
    handoff           -> the target department
    assigned          -> the people newly put on it
    due tomorrow /
    overdue /
    late (sweep)      -> requester + assignees + responsible, once a day

Written through the platform's own notification service IN THE SAME
TRANSACTION as the action (the way the standup nudge does), so a raised
request and its bell either both land or neither does - and inside a
savepoint, so a notifications hiccup can never poison the session that
holds the actual work.

The notification registry's template table lives in another module and an
unregistered i18n key renders as the key itself in the bell, so the
title/body carried here are the readable sentence, with the structured
facts in ``body_context`` for anything that wants to localise later.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests.models import ACTIVE_STATUSES, WorkDepartment, WorkRequest

logger = logging.getLogger(__name__)

ENTITY_TYPE = "work_request"


def action_url(req: WorkRequest) -> str:
    return f"/work-requests/{req.id}"


def _today() -> date:
    """Server-local calendar day - the same clock ``service._today`` uses,
    so the sweep and the ``is_overdue`` flag can never disagree."""
    return date.today()


async def _real_users(session: AsyncSession, ids: list[str] | set[str], *, exclude: str | None) -> list[uuid.UUID]:
    """Only ACTIVE users that exist, never the actor, no duplicates."""
    from app.modules.users.models import User

    wanted: list[uuid.UUID] = []
    seen: set[str] = set()
    for raw in ids:
        text = str(raw or "").strip()
        if not text or text == str(exclude or "") or text in seen:
            continue
        try:
            wanted.append(uuid.UUID(text))
            seen.add(text)
        except (ValueError, TypeError):
            continue
    if not wanted:
        return []
    rows = (
        (
            await session.execute(select(User.id).where(User.id.in_(wanted), User.is_active == True))  # noqa: E712
        )
        .scalars()
        .all()
    )
    return [r if isinstance(r, uuid.UUID) else uuid.UUID(str(r)) for r in rows]


async def notify(
    session: AsyncSession,
    recipients: list[str] | set[str],
    *,
    req: WorkRequest,
    title: str,
    body: str,
    kind: str = "info",
    actor_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> int:
    """Create one in-app notification per recipient. Returns how many.

    A failure here is logged and swallowed: the bell is never the work.
    """
    users = await _real_users(session, recipients, exclude=actor_id)
    if not users:
        return 0
    try:
        from app.modules.notifications.service import NotificationService
    except ImportError:  # pragma: no cover - notifications module absent
        return 0
    ctx = {
        "reference": req.reference,
        "title": req.title,
        "department": req.department,
        "request_id": str(req.id),
        "project_id": str(req.project_id),
        **(context or {}),
    }
    try:
        async with session.begin_nested():
            await NotificationService(session).notify_users(
                users,
                kind,
                title[:255],
                body_key=body[:255] if body else None,
                body_context=ctx,
                action_url=action_url(req),
                entity_type=ENTITY_TYPE,
                entity_id=str(req.id),
            )
    except Exception:  # noqa: BLE001 - a bell is never a gate
        logger.warning("work_requests: could not notify on %s", req.reference, exc_info=True)
        return 0
    return len(users)


def department_people(dept: WorkDepartment | None) -> list[str]:
    if dept is None:
        return []
    out = [str(m) for m in (dept.member_ids or [])]
    if dept.lead_user_id and str(dept.lead_user_id) not in out:
        out.insert(0, str(dept.lead_user_id))
    return out


def _request_side(req: WorkRequest) -> list[str]:
    out = [str(req.raised_by_id)] if req.raised_by_id else []
    return out


def _department_side(req: WorkRequest, dept: WorkDepartment | None) -> list[str]:
    out = department_people(dept)
    for a in req.assignee_ids or []:
        if str(a) not in out:
            out.append(str(a))
    if req.responsible_user_id and str(req.responsible_user_id) not in out:
        out.append(str(req.responsible_user_id))
    return out


# ── The moments ──────────────────────────────────────────────────────────


async def request_raised(session: AsyncSession, req: WorkRequest, dept: WorkDepartment, *, actor_id: str) -> int:
    return await notify(
        session,
        department_people(dept),
        req=req,
        title=f"{req.reference} raised for {dept.name}",
        body=f"{req.title} - raised by {req.raised_by_name or 'a colleague'}"
        + (f", due {req.due_date}" if req.due_date else ""),
        actor_id=actor_id,
        context={"raised_by": req.raised_by_name or ""},
    )


async def status_changed(session: AsyncSession, req: WorkRequest, previous: str, *, actor_id: str) -> int:
    if req.status == "complete":
        title = f"{req.reference} is complete"
        body = f"{req.title} - the department has finished; close it when you are satisfied"
    else:
        title = f"{req.reference} is now {req.status.replace('_', ' ')}"
        body = f"{req.title} - was {previous.replace('_', ' ')}"
    return await notify(
        session, _request_side(req), req=req, title=title, body=body, actor_id=actor_id, context={"previous": previous}
    )


async def stage_changed(session: AsyncSession, req: WorkRequest, previous: str | None, *, actor_id: str) -> int:
    stage = req.stage or ""
    return await notify(
        session,
        _request_side(req),
        req=req,
        title=f"{req.reference} moved to {stage.replace('_', ' ')}",
        body=req.title + (f" - was {previous.replace('_', ' ')}" if previous else ""),
        actor_id=actor_id,
        context={"stage": stage, "previous": previous or ""},
    )


async def needs_info(session: AsyncSession, req: WorkRequest, question: str, *, actor_id: str) -> int:
    return await notify(
        session,
        _request_side(req),
        req=req,
        title=f"{req.reference} needs information from you",
        body=question,
        kind="warning",
        actor_id=actor_id,
        context={"question": question},
    )


async def answered(
    session: AsyncSession, req: WorkRequest, dept: WorkDepartment | None, answer: str, *, actor_id: str
) -> int:
    return await notify(
        session,
        _department_side(req, dept),
        req=req,
        title=f"{req.reference} answered",
        body=answer,
        actor_id=actor_id,
        context={"answer": answer},
    )


async def mentioned(session: AsyncSession, req: WorkRequest, user_ids: list[str], *, actor_id: str) -> int:
    return await notify(
        session,
        user_ids,
        req=req,
        title=f"You were mentioned on {req.reference}",
        body=req.title,
        actor_id=actor_id,
    )


async def handoff(
    session: AsyncSession, parent: WorkRequest, child: WorkRequest, target: WorkDepartment, *, actor_id: str
) -> int:
    return await notify(
        session,
        department_people(target),
        req=child,
        title=f"{child.reference} handed to {target.name} from {parent.reference}",
        body=child.title,
        actor_id=actor_id,
        context={"parent_reference": parent.reference, "parent_id": str(parent.id)},
    )


async def assigned(session: AsyncSession, req: WorkRequest, user_ids: list[str], *, actor_id: str) -> int:
    if not user_ids:
        return 0
    return await notify(
        session,
        user_ids,
        req=req,
        title=f"{req.reference} assigned to you",
        body=req.title + (f" - due {req.due_date}" if req.due_date else ""),
        actor_id=actor_id,
    )


# ── The deadline sweep ───────────────────────────────────────────────────


def _already_today(req: WorkRequest, reason: str) -> bool:
    log = req.notified or {}
    return isinstance(log, dict) and log.get(reason) == _today().isoformat()


def _mark(req: WorkRequest, reason: str) -> None:
    log = dict(req.notified or {})
    log[reason] = _today().isoformat()
    req.notified = log


async def sweep(session: AsyncSession, *, project_ids: set[uuid.UUID] | None) -> dict[str, Any]:
    """Announce what has newly fallen due - or run past its department's
    own turnaround target - at most once per request per reason per day.

    THE DEDUPE IS THE LOAD-BEARING PART: the workspace polls, and a naive
    publish would ring the same overdue request every poll for days -
    which trains everyone to ignore the bell.

    ``overdue`` and ``late`` are two different facts and ring separately:
    overdue is past the date the REQUESTER asked for, late is past the
    working-day turnaround the DEPARTMENT signed up to.
    """
    from app.modules.work_requests import events, service

    stmt = select(WorkRequest).where(
        WorkRequest.status.in_(list(ACTIVE_STATUSES)),
        # A template is a thing to copy from; it has no deadline to miss.
        WorkRequest.is_template.is_not(True),
        or_(WorkRequest.due_date.is_not(None), WorkRequest.accepted_at.is_not(None)),
    )
    if project_ids is not None:
        if not project_ids:
            return {"published": 0, "detail": []}
        stmt = stmt.where(WorkRequest.project_id.in_(project_ids))
    rows = (await session.execute(stmt)).scalars().all()
    departments = {d.key: d for d in await service.list_departments(session)}
    today = _today()
    published: list[str] = []
    for req in rows:
        recipients = [*_request_side(req), *(str(a) for a in (req.assignee_ids or []))]
        if req.responsible_user_id:
            recipients.append(str(req.responsible_user_id))

        dept = departments.get(req.department)
        target, days_late, is_late = service.lateness(req, dept, today=today)
        if is_late and days_late and not _already_today(req, "late"):
            await notify(
                session,
                recipients,
                req=req,
                title=(
                    f"{req.reference} is {days_late} day{'s' if days_late != 1 else ''} past the "
                    f"{dept.name if dept else req.department} turnaround target"
                ),
                body=req.title + f" - target was {target}",
                kind="warning",
                context={"days_late": days_late, "target_date": target},
            )
            _mark(req, "late")
            published.append(f"{req.reference} late")

        try:
            due = date.fromisoformat(req.due_date or "")
        except ValueError:
            continue
        delta = (due - today).days
        if delta < 0 and not _already_today(req, "overdue"):
            late = -delta
            await notify(
                session,
                recipients,
                req=req,
                title=f"{req.reference} is {late} day{'s' if late != 1 else ''} overdue",
                body=req.title + f" - was due {req.due_date}",
                kind="warning",
                context={"days_late": late},
            )
            events.overdue(req, late)
            _mark(req, "overdue")
            published.append(f"{req.reference} overdue")
        elif delta == 1 and not _already_today(req, "due_tomorrow"):
            await notify(
                session,
                recipients,
                req=req,
                title=f"{req.reference} is due tomorrow",
                body=req.title,
                context={"due_date": req.due_date},
            )
            events.due_tomorrow(req)
            _mark(req, "due_tomorrow")
            published.append(f"{req.reference} due tomorrow")
    await session.flush()
    return {"published": len(published), "detail": published[:100]}
