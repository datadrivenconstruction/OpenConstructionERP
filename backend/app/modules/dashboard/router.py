# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dashboard rollup router.

Mounted by the module loader at ``/api/v1/dashboard/``.

Endpoints:
    GET  /rollup/ - fast path: return all (or filtered) widget payloads in
                    one shot via query-string params.
    POST /rollup/ - config-aware path: accepts ``RollupRequest`` body so
                    callers can supply per-widget ``WidgetConfigItem`` overrides
                    (e.g. the dashboard customisation panel).  The same IDOR
                    posture and 422-validation flow as the GET path.
    GET  /inbox/  - the caller's unified approvals/alerts list.
    POST /inbox/{item_id}/acknowledge - mark a row seen; it stays listed.
    POST /inbox/{item_id}/dismiss     - take a row off the list.
    DELETE /inbox/{item_id}/state     - undo either of the above.

IDOR posture: project IDs the caller doesn't own are silently dropped
from the rollup - never 403. Empty / unaccessible scope returns 200 with
empty per-widget data (frontend renders the "no projects" empty state).
The inbox *read* keeps that posture; the inbox *actions* do not, because a
write must not quietly accept an id that is not the caller's - an item id
outside their own inbox answers 404.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Query, Response, status

from app.dependencies import CurrentUserId, SessionDep
from app.modules.dashboard.inbox import compute_inbox
from app.modules.dashboard.inbox_actions import (
    InboxActionInvalid,
    InboxActionService,
    InboxItemNotFound,
)
from app.modules.dashboard.inbox_logic import STATE_ACKNOWLEDGED, STATE_DISMISSED
from app.modules.dashboard.schemas import (
    InboxActionResponse,
    InboxResponse,
    RollupRequest,
    RollupResponse,  # noqa: F401 - re-exported in OpenAPI
)
from app.modules.dashboard.service import (
    KNOWN_WIDGETS,
    accessible_projects,
    compute_rollup,
    is_admin,
)

router = APIRouter(tags=["dashboard"])


def _parse_csv_list(raw: str | None) -> list[str]:
    """Split a comma-separated query param into a clean list."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_uuid_list(raw: str | None) -> list[uuid.UUID] | None:
    """Parse a CSV of UUIDs; return None when the param is absent.

    Malformed UUIDs are silently dropped - the caller gets whatever
    well-formed ones survive (still IDOR-checked downstream).
    """
    if raw is None:
        return None
    out: list[uuid.UUID] = []
    for item in _parse_csv_list(raw):
        try:
            out.append(uuid.UUID(item))
        except ValueError:
            continue
    return out


@router.get(
    "/rollup/",
    response_model=RollupResponse,
    response_model_exclude_none=True,
    summary="Dashboard rollup - all widgets in one call",
    description=(
        "Aggregates the requested wave-2 dashboard widget payloads in a "
        "single round-trip. Replaces the per-project ``Promise.all`` fan-out "
        "the frontend previously did (50 projects = 50 HTTP calls per "
        "widget). Returns 200 with empty per-widget data when no projects "
        "are accessible. Money fields are Decimal-as-string. Cached for "
        "60 seconds (ETag + ``Cache-Control: max-age=60``)."
    ),
)
async def get_rollup(
    user_id: CurrentUserId,
    session: SessionDep,
    widgets: str | None = Query(
        default=None,
        description=("Comma-separated widget IDs to include. Omit for all 10. Unknown ids are silently ignored."),
    ),
    project_ids: str | None = Query(
        default=None,
        description=(
            "Comma-separated project UUIDs to scope the rollup. Omit for "
            "all accessible projects. IDs the caller can't access are "
            "silently dropped (IDOR-safe)."
        ),
    ),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    requested_widgets = _parse_csv_list(widgets) or sorted(KNOWN_WIDGETS)
    # Drop unknowns now so the ETag doesn't depend on garbage input.
    requested_widgets = [w for w in requested_widgets if w in KNOWN_WIDGETS]

    project_id_filter = _parse_uuid_list(project_ids)
    projects = await accessible_projects(
        session,
        user_id,
        requested_ids=project_id_filter,
    )

    payload = await compute_rollup(session, projects, requested_widgets)

    # Compute the ETag over data + request shape ONLY - never over the
    # generated_at timestamp, otherwise every request gets a fresh ETag
    # and the 304 short-circuit never fires.
    etag_basis = json.dumps(
        {"u": user_id, "w": requested_widgets, "p": payload},
        sort_keys=True,
        default=str,
    )
    etag = '"' + hashlib.sha256(etag_basis.encode("utf-8")).hexdigest()[:16] + '"'

    cache_headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=60",
    }
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers=cache_headers)

    body = {
        **payload,
        "generated_at": datetime.now(UTC).isoformat(),
        "widgets_requested": requested_widgets,
        "project_count": len(projects),
    }
    serialized = json.dumps(body, sort_keys=True, default=str)
    return Response(
        content=serialized,
        media_type="application/json",
        headers=cache_headers,
    )


@router.post(
    "/rollup/",
    response_model=RollupResponse,
    response_model_exclude_none=True,
    summary="Dashboard rollup - config-aware POST path",
    description=(
        "Config-aware variant of the rollup endpoint. Accepts a "
        "``RollupRequest`` body so callers can supply per-widget "
        "``WidgetConfigItem`` overrides (e.g. ``max_by_project`` for "
        "``boq_summary``). Unknown widget ids or config keys return 422 "
        "before any DB work. The same IDOR posture applies: inaccessible "
        "project ids are silently dropped. No ETag caching on the POST "
        "path (the body varies arbitrarily)."
    ),
)
async def post_rollup(
    user_id: CurrentUserId,
    session: SessionDep,
    body: RollupRequest,
) -> Response:
    # Derive widget list from the body's widget_configs.  If no configs are
    # supplied fall back to all known widgets (mirrors GET default).
    if body.widget_configs:
        requested_widgets = [wc.widget_id for wc in body.widget_configs]
        # Keep only those that are also in KNOWN_WIDGETS (the config schema
        # only covers the 10 configurable wave-2 widgets; the project-detail
        # widgets are accessible via GET only).
        requested_widgets = [w for w in requested_widgets if w in KNOWN_WIDGETS]
    else:
        requested_widgets = sorted(KNOWN_WIDGETS)

    # Parse project_ids from body (list of UUID strings).
    project_id_filter: list[uuid.UUID] | None = None
    if body.project_ids is not None:
        parsed: list[uuid.UUID] = []
        for raw in body.project_ids:
            try:
                parsed.append(uuid.UUID(raw))
            except (ValueError, TypeError):
                continue  # silently drop malformed UUIDs
        project_id_filter = parsed

    projects = await accessible_projects(
        session,
        user_id,
        requested_ids=project_id_filter,
    )

    payload = await compute_rollup(session, projects, requested_widgets)

    body_out = {
        **payload,
        "generated_at": datetime.now(UTC).isoformat(),
        "widgets_requested": requested_widgets,
        "project_count": len(projects),
    }
    serialized = json.dumps(body_out, sort_keys=True, default=str)
    return Response(
        content=serialized,
        media_type="application/json",
    )


@router.get(
    "/inbox/",
    response_model=InboxResponse,
    summary="Unified approvals/alerts inbox",
    description=(
        "Aggregates the caller's pending approvals (file-approval steps + "
        "change-order approval steps where they are the named approver) and "
        "their unread in-app notifications (alerts) into one chronologically "
        "sorted list. Reads existing per-module stores only - no new "
        "persistence. IDOR-safe: every row is scoped to the caller's "
        "accessible projects, and notifications are already per-user; rows "
        "the caller can't see are silently dropped (never 403). Returns 200 "
        "with empty data when nothing is pending."
    ),
)
async def get_inbox(
    user_id: CurrentUserId,
    session: SessionDep,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum rows in the returned list (counts are pre-cap).",
    ),
) -> InboxResponse:
    # Same accessible-project scope the rollup uses (admin-aware, partner-pack
    # aware). Passing the resolved list (not just ids) lets the aggregator
    # stamp project names without a second query.
    projects = await accessible_projects(session, user_id)
    admin = await is_admin(session, user_id)
    payload = await compute_inbox(
        session,
        projects,
        user_id,
        is_admin=admin,
        limit=limit,
    )
    return InboxResponse(
        **payload,
        generated_at=datetime.now(UTC).isoformat(),
    )


# ── Inbox actions ────────────────────────────────────────────────────────────


async def _act_on_inbox_item(
    item_id: str,
    state: str,
    user_id: str,
    session: SessionDep,
) -> InboxActionResponse:
    """Shared body for acknowledge and dismiss.

    The ownership check runs first and answers 404 for an id outside the
    caller's own inbox, so a write cannot be used to probe for ids the way a
    silently-dropped read could.
    """
    projects = await accessible_projects(session, user_id)
    admin = await is_admin(session, user_id)
    service = InboxActionService(session)
    try:
        recorded, findings = await service.act(
            projects,
            user_id,
            item_id=item_id,
            state=state,
            is_admin=admin,
        )
    except InboxItemNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox item not found",
        ) from exc
    except InboxActionInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "The inbox action did not pass validation", "findings": exc.findings},
        ) from exc
    await session.commit()
    return InboxActionResponse(item_id=item_id, state=recorded, findings=findings)


@router.post(
    "/inbox/{item_id}/acknowledge",
    response_model=InboxActionResponse,
    summary="Mark one inbox row as seen",
    description=(
        "Records that the caller has seen this row. It stays in the list, flagged "
        "``acknowledged``, so a long inbox can be worked through without anything "
        "silently disappearing. Nothing in the module that owns the row changes."
    ),
)
async def acknowledge_inbox_item(
    item_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InboxActionResponse:
    return await _act_on_inbox_item(item_id, STATE_ACKNOWLEDGED, user_id, session)


@router.post(
    "/inbox/{item_id}/dismiss",
    response_model=InboxActionResponse,
    summary="Take one inbox row off the caller's list",
    description=(
        "Removes the row from the caller's inbox. For an alert this also marks the "
        "underlying notification read, so the notifications screen agrees. For an "
        "approval it is triage only: the step stays pending and stays visible in "
        "the module that owns it, and that is reported back in ``findings``."
    ),
)
async def dismiss_inbox_item(
    item_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InboxActionResponse:
    return await _act_on_inbox_item(item_id, STATE_DISMISSED, user_id, session)


@router.delete(
    "/inbox/{item_id}/state",
    response_model=InboxActionResponse,
    summary="Undo an acknowledge or a dismiss",
    description=(
        "Forgets what the caller did with this row and puts it back on the list. A "
        "dismissed alert is marked unread again, otherwise the row would stay "
        "invisible with its state gone."
    ),
)
async def restore_inbox_item(
    item_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InboxActionResponse:
    restored = await InboxActionService(session).restore(user_id, item_id)
    if not restored:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox item has no recorded state",
        )
    await session.commit()
    return InboxActionResponse(item_id=item_id, state=None, findings=[])
