"""Dashboard rollup router.

Mounted by the module loader at ``/api/v1/dashboard/``.

Endpoints:
    GET  /rollup/ — fast path: return all (or filtered) widget payloads in
                    one shot via query-string params.
    POST /rollup/ — config-aware path: accepts ``RollupRequest`` body so
                    callers can supply per-widget ``WidgetConfigItem`` overrides
                    (e.g. the dashboard customisation panel).  The same IDOR
                    posture and 422-validation flow as the GET path.

IDOR posture: project IDs the caller doesn't own are silently dropped
from the rollup — never 403. Empty / unaccessible scope returns 200 with
empty per-widget data (frontend renders the "no projects" empty state).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Header, Query, Response

from app.dependencies import CurrentUserId, SessionDep
from app.modules.dashboard.schemas import (
    RollupRequest,
    RollupResponse,  # noqa: F401 — re-exported in OpenAPI
)
from app.modules.dashboard.service import (
    KNOWN_WIDGETS,
    accessible_projects,
    compute_rollup,
)

router = APIRouter()


def _parse_csv_list(raw: str | None) -> list[str]:
    """Split a comma-separated query param into a clean list."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_uuid_list(raw: str | None) -> list[uuid.UUID] | None:
    """Parse a CSV of UUIDs; return None when the param is absent.

    Malformed UUIDs are silently dropped — the caller gets whatever
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
    summary="Dashboard rollup — all widgets in one call",
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

    # Compute the ETag over data + request shape ONLY — never over the
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
    summary="Dashboard rollup — config-aware POST path",
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
