# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unified approvals/alerts inbox aggregator.

Surfaces, in ONE place, the two things a user opens the app to act on:

* **Pending approvals** assigned to them - file-approval steps and
  change-order approval steps where they are the named approver and the
  step is still ``pending``.
* **Alerts** - their own unread in-app notifications.

Both streams are scoped to the caller's accessible projects (the same IDOR
posture as the rest of the dashboard module: rows the caller can't see are
silently dropped, never 403). Neither stream is owned here - both are read from
the existing per-module tables and merged. The one thing this module does own
is ``oe_dashboard_inbox_item_state``: what the caller already did with a row
(see :mod:`inbox_actions`), which is applied on the way out so a dismissed row
stops coming back. The pure merge / sort / scope / state logic lives in
:mod:`inbox_logic` (DB-free, unit-tested); this file is only the query +
normalise layer.

Sibling-module models are imported **inside** the function so a slim install
that disabled (e.g.) ``oe_file_approvals`` or ``oe_changeorders`` still loads
this module - a failed import for one source degrades that source to empty,
exactly like ``compute_rollup``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.inbox_logic import (
    KIND_ALERT,
    KIND_APPROVAL,
    build_inbox,
    severity_for_notification,
)
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)

# Cap rows pulled per source so a user with thousands of historical
# notifications / approvals can't drag the endpoint down. The merged result
# is capped again by ``build_inbox`` to the requested ``limit``.
_PER_SOURCE_CAP = 200


def _iso(value: Any) -> str | None:
    """Best-effort ISO-8601 string for a datetime / str / None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def _collect_file_approvals(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Pending file-approval steps where the caller is the approver."""
    from app.modules.file_approvals.models import (  # noqa: PLC0415
        FileApprovalStep,
        FileApprovalWorkflow,
    )

    stmt = (
        select(
            FileApprovalStep.id,
            FileApprovalWorkflow.id,
            FileApprovalWorkflow.project_id,
            FileApprovalWorkflow.file_kind,
            FileApprovalWorkflow.file_id,
            FileApprovalWorkflow.submitted_at,
            FileApprovalStep.role_label,
        )
        .join(
            FileApprovalWorkflow,
            FileApprovalWorkflow.id == FileApprovalStep.workflow_id,
        )
        .where(FileApprovalStep.approver_id == user_id)
        .where(FileApprovalStep.decision == "pending")
        .where(FileApprovalWorkflow.status == "in_review")
        .where(FileApprovalWorkflow.project_id.in_(project_ids))
        .order_by(FileApprovalWorkflow.submitted_at.desc())
        .limit(_PER_SOURCE_CAP)
    )
    rows = (await session.execute(stmt)).all()

    items: list[dict[str, Any]] = []
    for step_id, wf_id, project_id, file_kind, file_id, submitted_at, role_label in rows:
        items.append(
            {
                "id": f"file_approval:{step_id}",
                "kind": KIND_APPROVAL,
                "source": "file_approval",
                # Title is a stable English default; the frontend prefers
                # ``title_key`` when present (here it's None) and otherwise
                # shows this string. Keeps the payload self-describing.
                "title": f"Approve {file_kind} document",
                "title_key": "inbox.approval_file",
                "body_context": {"file_kind": file_kind or "file"},
                "project_id": str(project_id),
                "project_name": None,  # filled in by caller from project map
                "entity_type": "file_approval_workflow",
                "entity_id": str(wf_id),
                "action_url": "/files/approvals",
                "severity": "warning",
                "created_at": _iso(submitted_at),
                "role_label": role_label,
            },
        )
    return items


async def _collect_change_order_approvals(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    user_id: uuid.UUID,
    project_name_by_id: dict[uuid.UUID, str],
) -> list[dict[str, Any]]:
    """Pending change-order approval steps where the caller is the approver."""
    from app.modules.changeorders.models import (  # noqa: PLC0415
        ChangeOrder,
        ChangeOrderApproval,
    )

    stmt = (
        select(
            ChangeOrderApproval.id,
            ChangeOrder.id,
            ChangeOrder.project_id,
            ChangeOrder.code,
            ChangeOrder.title,
        )
        .join(ChangeOrder, ChangeOrder.id == ChangeOrderApproval.change_order_id)
        .where(ChangeOrderApproval.approver_user_id == user_id)
        .where(ChangeOrderApproval.decision == "pending")
        .where(ChangeOrder.project_id.in_(project_ids))
        .where(ChangeOrder.status.not_in(("approved", "rejected", "closed")))
        .limit(_PER_SOURCE_CAP)
    )
    rows = (await session.execute(stmt)).all()

    items: list[dict[str, Any]] = []
    for approval_id, co_id, project_id, code, title in rows:
        # ChangeOrderApproval has no created_at column exposed on the row
        # above; use the parent CO's created_at would need a second column,
        # so we leave created_at None (sorts after timestamped items). The
        # approval id keeps ordering deterministic via the tiebreak.
        items.append(
            {
                "id": f"change_order_approval:{approval_id}",
                "kind": KIND_APPROVAL,
                "source": "change_order",
                "title": f"Approve change order {code or ''}".strip(),
                "title_key": "inbox.approval_change_order",
                "body_context": {"code": code or "", "title": title or ""},
                "project_id": str(project_id),
                "project_name": project_name_by_id.get(project_id),
                "entity_type": "change_order",
                "entity_id": str(co_id),
                "action_url": f"/changeorders?highlight={co_id}",
                "severity": "warning",
                "created_at": None,
            },
        )
    return items


async def _collect_alerts(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """The caller's own unread in-app notifications.

    Notifications are stored per-user (``user_id`` FK), so this stream is
    already the caller's own rows - no cross-tenant leakage is possible. We
    still pass them through the project-scope filter in ``build_inbox`` so a
    notification that names a project the caller has since lost access to is
    dropped (defence in depth).
    """
    from app.modules.notifications.models import Notification  # noqa: PLC0415

    stmt = (
        select(
            Notification.id,
            Notification.notification_type,
            Notification.title_key,
            Notification.body_key,
            Notification.body_context,
            Notification.entity_type,
            Notification.entity_id,
            Notification.action_url,
            Notification.created_at,
        )
        .where(Notification.user_id == user_id)
        .where(Notification.is_read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(_PER_SOURCE_CAP)
    )
    rows = (await session.execute(stmt)).all()

    items: list[dict[str, Any]] = []
    for (
        nid,
        ntype,
        title_key,
        body_key,
        body_context,
        entity_type,
        entity_id,
        action_url,
        created_at,
    ) in rows:
        # A notification points at a project when its entity IS a project, or
        # when its body_context carries a project_id (common convention in the
        # notification templates). Either lets the scope filter act on it.
        project_id: str | None = None
        if entity_type == "project" and entity_id:
            project_id = str(entity_id)
        elif isinstance(body_context, dict):
            raw_pid = body_context.get("project_id")
            if raw_pid:
                project_id = str(raw_pid)

        items.append(
            {
                "id": f"notification:{nid}",
                "kind": KIND_ALERT,
                "source": "notification",
                # Alerts are rendered from their i18n key; carry the key as the
                # title and the original key separately so the frontend can
                # interpolate ``body_context``.
                "title": title_key,
                "title_key": title_key,
                "body_key": body_key,
                "body_context": body_context if isinstance(body_context, dict) else {},
                "project_id": project_id,
                "project_name": None,
                "entity_type": entity_type,
                "entity_id": str(entity_id) if entity_id else None,
                "action_url": action_url,
                "severity": severity_for_notification(ntype),
                "created_at": _iso(created_at),
                "notification_type": ntype,
            },
        )
    return items


async def _collect_item_states(session: AsyncSession, user_id: uuid.UUID) -> dict[str, str]:
    """What the caller already did with individual rows.

    Fails **open**: if the state query cannot run, the inbox is built as if
    nothing had been acted on. Showing a row somebody dismissed is a small
    annoyance; hiding a pending approval because a query failed is how a
    deadline gets missed.
    """
    from app.modules.dashboard.repository import InboxItemStateRepository  # noqa: PLC0415

    try:
        return await InboxItemStateRepository(session).states_for_user(user_id)
    except Exception as exc:  # noqa: BLE001 - never hide work behind a failed query
        logger.warning("Inbox item states unavailable: %s", exc, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}


async def compute_inbox(
    session: AsyncSession,
    projects: list[Project],
    user_id: str,
    *,
    is_admin: bool = False,
    limit: int = 50,
    apply_states: bool = True,
) -> dict[str, Any]:
    """Aggregate the caller's pending approvals + alerts into one payload.

    ``projects`` is the caller's already-IDOR-scoped accessible project list
    (resolved by the router via ``accessible_projects``). ``is_admin`` flips
    the scope filter to "keep everything" so an admin's view is not narrowed
    by the project-id intersection (their notifications can reference any
    project). Each source is wrapped so a disabled module only blanks its own
    stream - never the whole inbox.

    ``apply_states`` drops rows the caller dismissed and flags the ones they
    acknowledged. The action endpoints pass False so they can confirm an id
    really belongs to the caller even after it has been acted on once.
    """
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        # Malformed caller id - return an empty, well-formed payload.
        return build_inbox([], [], accessible_project_ids=set(), limit=limit)

    project_ids = [p.id for p in projects]
    project_name_by_id = {p.id: p.name for p in projects}
    accessible_ids: set[str] | None = None if is_admin else {str(p.id) for p in projects}

    approvals: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    # ── Pending approvals (only meaningful when the caller has projects) ──
    if project_ids:
        for collector in (
            lambda: _collect_file_approvals(session, project_ids, uid),
            lambda: _collect_change_order_approvals(session, project_ids, uid, project_name_by_id),
        ):
            try:
                approvals.extend(await collector())
            except Exception as exc:  # noqa: BLE001 - one missing module != broken inbox
                logger.warning("Inbox approval source failed: %s", exc, exc_info=True)
                # A failed statement aborts the PG transaction; roll back so
                # the next source + the alert query run on a clean session.
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    pass

    # Fill in project names for any approval item that didn't get one.
    for item in approvals:
        if item.get("project_name") is None and item.get("project_id"):
            try:
                item["project_name"] = project_name_by_id.get(uuid.UUID(str(item["project_id"])))
            except (ValueError, TypeError):
                pass

    # ── Alerts (the caller's own unread notifications) ──
    try:
        alerts = await _collect_alerts(session, uid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Inbox alert source failed: %s", exc, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        alerts = []

    # Resolve project names on alerts that reference an accessible project.
    for item in alerts:
        if item.get("project_name") is None and item.get("project_id"):
            try:
                item["project_name"] = project_name_by_id.get(uuid.UUID(str(item["project_id"])))
            except (ValueError, TypeError):
                pass

    item_states = await _collect_item_states(session, uid) if apply_states else None

    return build_inbox(
        approvals,
        alerts,
        accessible_project_ids=accessible_ids,
        limit=limit,
        item_states=item_states,
    )


__all__ = ["compute_inbox"]
