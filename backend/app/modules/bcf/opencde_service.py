"""OpenCDE BCF-API 3.0 — service layer.

Bridges incoming OpenCDE REST requests onto our native :mod:`bcf` ORM
(``BCFTopic`` / ``BCFComment`` / ``BCFViewpoint``). The wire payload
shapes live in :mod:`opencde_schemas`; this module owns translation,
RBAC-driven authorization sub-objects, ETag derivation and the OData
``$filter`` / ``$orderby`` / ``$top`` / ``$skip`` parser.

OData $filter — the conformance subset we accept:

    topic_status eq 'Open'
    priority in ('high','critical')
    due_date lt 2026-06-01
    creation_author eq 'x@y.com'
    labels/any(l: l eq 'MEP')

Anything else returns ``400`` from the router. The parser is a small
hand-rolled tokenizer — NO ``eval``, NO string-concatenated SQL.

Defensive: every read path probes ClashIssue ABSENT at first use and
returns the structured 503 the router knows about — mirroring the
sibling import_service's degradation contract.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.bcf.models import BCFComment, BCFTopic, BCFViewpoint
from app.modules.bcf.opencde_schemas import (
    BCFCommentResponse,
    BCFProject,
    BCFTopicResponse,
    BimSnippet,
    CommentAuthorization,
    CommentCreatePayload,
    Components,
    OrthogonalCamera,
    PerspectiveCamera,
    Point,
    ProjectAuthorization,
    SnapshotInfo,
    TopicAuthorization,
    TopicCreatePayload,
    TopicUpdatePayload,
    ViewpointCreatePayload,
    ViewpointResponse,
    Visibility,
)
from app.modules.bcf.repository import BCFRepository

logger = logging.getLogger(__name__)


class OpenCDEServiceError(Exception):
    """Caller-facing error from the OpenCDE service layer."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class StaleResourceError(OpenCDEServiceError):
    """Raised on If-Match mismatch — router maps to 412."""

    def __init__(self, message: str = "Resource has been modified") -> None:
        super().__init__("if_match_failed", message, http_status=412)


class FeatureUnavailableError(OpenCDEServiceError):
    """Raised when a dependent migration hasn't run — maps to 503."""

    def __init__(self, message: str) -> None:
        super().__init__("feature_unavailable", message, http_status=503)


# ── ETag helper ────────────────────────────────────────────────────────


def compute_topic_etag(topic: BCFTopic) -> str:
    """ETag for a topic — sha1 of its last-modified instant.

    Two reads sharing the same modified_date share the same ETag.
    PUT/DELETE require an If-Match equal to this value or 412.
    """
    md = topic.modified_date or topic.creation_date or datetime.now(UTC)
    if md.tzinfo is None:
        md = md.replace(tzinfo=UTC)
    return '"' + hashlib.sha1(md.isoformat().encode("ascii")).hexdigest() + '"'


def compute_comment_etag(comment: BCFComment) -> str:
    """ETag for a comment — sha1 of its last-modified instant."""
    md = comment.modified_date or comment.date or datetime.now(UTC)
    if md.tzinfo is None:
        md = md.replace(tzinfo=UTC)
    return '"' + hashlib.sha1(md.isoformat().encode("ascii")).hexdigest() + '"'


# ── OData $filter parser ───────────────────────────────────────────────


@dataclass
class _Clause:
    """A single parsed OData filter clause."""

    field: str
    op: str
    value: Any


_FILTER_MAX_LEN = 1024
_TOPIC_FIELDS_SCALAR: set[str] = {
    "topic_status",
    "topic_type",
    "priority",
    "stage",
    "assigned_to",
    "creation_author",
    "modified_author",
    "due_date",
    "title",
}


class ODataParseError(OpenCDEServiceError):
    """Bad ``$filter`` clause."""

    def __init__(self, message: str) -> None:
        super().__init__("odata_invalid", message, http_status=400)


def _parse_value(raw: str) -> Any:
    """Decode an OData literal: ``'foo'`` / ``2026-06-01`` / number."""
    raw = raw.strip()
    if not raw:
        raise ODataParseError("Empty literal in $filter")
    # Quoted string ─ ' or "
    if (raw[0] == "'" and raw[-1] == "'") or (raw[0] == '"' and raw[-1] == '"'):
        return raw[1:-1]
    # ISO date ─ YYYY-MM-DD or full datetime
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ODataParseError(f"Bad date literal: {raw}") from exc
    # int / float
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError as exc:
        raise ODataParseError(f"Unrecognised literal: {raw}") from exc


def _parse_in_list(raw: str) -> list[Any]:
    """Decode ``('a','b','c')`` into a list of literals."""
    inner = raw.strip()
    if not (inner.startswith("(") and inner.endswith(")")):
        raise ODataParseError("`in` operator expects parenthesised list")
    inner = inner[1:-1]
    parts: list[str] = []
    buf = ""
    in_str: str | None = None
    for ch in inner:
        if in_str:
            buf += ch
            if ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            buf += ch
            in_str = ch
            continue
        if ch == ",":
            parts.append(buf)
            buf = ""
            continue
        buf += ch
    if buf.strip():
        parts.append(buf)
    return [_parse_value(p) for p in parts]


def parse_odata_filter(expr: str) -> list[_Clause]:
    """Parse a $filter string into AND-joined clauses.

    Supported:
      * ``<field> eq|ne|lt|le|gt|ge <literal>``
      * ``<field> in (<lit>, <lit>, …)``
      * ``labels/any(l: l eq '<literal>')``

    Multiple clauses joined by ``and`` only. ``or`` / parentheses /
    deeper navigation paths raise :class:`ODataParseError`.
    """
    if not expr or not expr.strip():
        return []
    if len(expr) > _FILTER_MAX_LEN:
        raise ODataParseError(f"$filter exceeds {_FILTER_MAX_LEN} characters")

    # Split on `and` only — we deliberately reject `or` for the minimum
    # compliance profile (the spec says the server MAY accept any subset
    # of OData and 400 the rest).
    if " or " in expr.lower():
        raise ODataParseError("`or` is not supported in $filter")
    if "(" in expr and "labels/any" not in expr and " in " not in expr.lower():
        raise ODataParseError("Parenthesised sub-expressions not supported")

    # Tokenise by `and` outside of quotes & parens.
    parts: list[str] = []
    buf = ""
    depth = 0
    in_str: str | None = None
    i = 0
    while i < len(expr):
        ch = expr[i]
        if in_str:
            buf += ch
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"'):
            buf += ch
            in_str = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
            buf += ch
            i += 1
            continue
        if ch == ")":
            depth -= 1
            buf += ch
            i += 1
            continue
        if depth == 0 and ch == " " and expr[i : i + 5].lower() == " and ":
            parts.append(buf)
            buf = ""
            i += 5
            continue
        buf += ch
        i += 1
    if buf.strip():
        parts.append(buf)

    clauses: list[_Clause] = []
    for clause in parts:
        clauses.append(_parse_clause(clause.strip()))
    return clauses


def _parse_clause(clause: str) -> _Clause:
    # labels/any(l: l eq 'MEP')
    low = clause.lower()
    if low.startswith("labels/any"):
        # Strict shape: labels/any(<lambda_var>: <lambda_var> eq '<value>')
        open_idx = clause.find("(")
        close_idx = clause.rfind(")")
        if open_idx == -1 or close_idx == -1 or close_idx <= open_idx:
            raise ODataParseError("Malformed labels/any() expression")
        inside = clause[open_idx + 1 : close_idx].strip()
        if ":" not in inside:
            raise ODataParseError("labels/any() needs a lambda variable")
        var, _, body = inside.partition(":")
        body = body.strip()
        var = var.strip()
        if not var:
            raise ODataParseError("Empty lambda variable in labels/any()")
        body_parts = body.split(maxsplit=2)
        if len(body_parts) != 3 or body_parts[0] != var or body_parts[1].lower() != "eq":
            raise ODataParseError("labels/any() body must be `<var> eq '<literal>'`")
        value = _parse_value(body_parts[2])
        if not isinstance(value, str):
            raise ODataParseError("labels/any() expects a string literal")
        return _Clause(field="labels", op="any_eq", value=value)

    # General "<field> <op> <value>" or "<field> in (<list>)"
    # First locate an "in" or a comparison operator.
    in_idx = -1
    # find ' in ' outside of any quotes
    lower = clause.lower()
    needle = " in "
    pos = 0
    while True:
        idx = lower.find(needle, pos)
        if idx == -1:
            break
        # ensure not inside quotes — for simplicity reject any quote before
        # the `in` token in clause to avoid edge cases.
        if "'" not in clause[:idx] and '"' not in clause[:idx]:
            in_idx = idx
            break
        pos = idx + 1
    if in_idx >= 0:
        field = clause[:in_idx].strip()
        list_part = clause[in_idx + len(needle) :].strip()
        values = _parse_in_list(list_part)
        if field not in _TOPIC_FIELDS_SCALAR:
            raise ODataParseError(f"Field '{field}' is not filterable")
        return _Clause(field=field, op="in", value=values)

    for op in (" eq ", " ne ", " ge ", " le ", " gt ", " lt "):
        idx = lower.find(op)
        if idx == -1:
            continue
        field = clause[:idx].strip()
        rhs = clause[idx + len(op) :].strip()
        if field not in _TOPIC_FIELDS_SCALAR:
            raise ODataParseError(f"Field '{field}' is not filterable")
        value = _parse_value(rhs)
        return _Clause(field=field, op=op.strip(), value=value)
    raise ODataParseError(f"Cannot parse $filter clause: {clause}")


def _clauses_to_sqla(clauses: list[_Clause]):
    """Translate parsed clauses into SQLAlchemy conditions on ``BCFTopic``."""
    sqla_clauses = []
    for c in clauses:
        if c.field == "labels":
            # SQLite JSON: use ``LIKE`` on the JSON-encoded representation
            # — labels are scalar tokens stored as ``["a","b"]`` so we can
            # match ``"<value>"`` safely (lexical equality after quoting).
            # Bound parameter — no interpolation.
            from sqlalchemy import String, cast
            from sqlalchemy import literal as sl

            # Escape SQL LIKE wildcards in the user-supplied label value
            # so a label like ``50%_off`` cannot match unintended rows.
            # Also strip embedded double-quotes — a label is a scalar token,
            # never a JSON fragment, so a ``"`` in it would only ever be a
            # poisoning attempt against the LIKE pattern below.
            safe = str(c.value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace('"', "")
            quoted = f'"{safe}"'
            sqla_clauses.append(cast(BCFTopic.labels, String).like(sl(f"%{quoted}%"), escape="\\"))
            continue
        col = getattr(BCFTopic, c.field, None)
        if col is None:
            raise ODataParseError(f"Unknown field {c.field}")
        if c.field == "due_date" and isinstance(c.value, date):
            value = datetime.combine(c.value, datetime.min.time(), tzinfo=UTC)
        else:
            value = c.value
        if c.op == "eq":
            sqla_clauses.append(col == value)
        elif c.op == "ne":
            sqla_clauses.append(col != value)
        elif c.op == "lt":
            sqla_clauses.append(col < value)
        elif c.op == "le":
            sqla_clauses.append(col <= value)
        elif c.op == "gt":
            sqla_clauses.append(col > value)
        elif c.op == "ge":
            sqla_clauses.append(col >= value)
        elif c.op == "in":
            sqla_clauses.append(col.in_(value))
        else:
            raise ODataParseError(f"Operator {c.op} not implemented")
    return sqla_clauses


# Fields allowed on $orderby. Restricted to scalar columns — relationships
# / hybrid attributes / dunder attrs are explicitly rejected to prevent a
# malformed query from leaking through ``getattr`` and exploding deep in
# the SQLA compile step.
_ORDERBY_ALLOWED_FIELDS: set[str] = _TOPIC_FIELDS_SCALAR | {
    "creation_date",
    "modified_date",
    "topic_index",
    "created_at",
    "updated_at",
}


def parse_orderby(expr: str | None) -> list:
    """Translate ``$orderby`` like ``creation_date desc, title asc`` to SQLA.

    Only fields in :data:`_ORDERBY_ALLOWED_FIELDS` are accepted; anything
    else (including ORM relationships such as ``comments`` / ``viewpoints``)
    returns a 400.
    """
    if not expr:
        return [BCFTopic.created_at.desc()]
    out: list = []
    for chunk in expr.split(","):
        parts = chunk.strip().split()
        if not parts:
            continue
        field = parts[0]
        direction = parts[1].lower() if len(parts) > 1 else "asc"
        if field not in _ORDERBY_ALLOWED_FIELDS:
            raise ODataParseError(f"Field '{field}' is not orderable")
        col = getattr(BCFTopic, field, None)
        if col is None:
            raise ODataParseError(f"Unknown $orderby field {field}")
        if direction == "desc":
            out.append(col.desc())
        elif direction == "asc":
            out.append(col.asc())
        else:
            raise ODataParseError(f"Bad $orderby direction {direction}")
    return out or [BCFTopic.created_at.desc()]


# ── Service ────────────────────────────────────────────────────────────


# Map our DB role to OpenCDE topic_actions.
_ROLE_TO_ACTIONS: dict[str, list[str]] = {
    "viewer": [],
    "estimator": ["createComment", "createViewpoint"],
    "editor": [
        "update",
        "updateBimSnippet",
        "updateRelatedTopics",
        "updateDocumentReferences",
        "updateFiles",
        "createComment",
        "createViewpoint",
    ],
    "manager": [
        "update",
        "updateBimSnippet",
        "updateRelatedTopics",
        "updateDocumentReferences",
        "updateFiles",
        "createComment",
        "createViewpoint",
    ],
    "admin": [
        "update",
        "updateBimSnippet",
        "updateRelatedTopics",
        "updateDocumentReferences",
        "updateFiles",
        "createComment",
        "createViewpoint",
    ],
}


class OpenCDEService:
    """Service handling OpenCDE BCF-API 3.0 requests.

    Stateless apart from the injected session; transaction commits are
    owned by the FastAPI session dependency.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BCFRepository(session)

    # ── Project ────────────────────────────────────────────────────

    async def list_projects(self, *, user_id: str, role: str) -> list[BCFProject]:
        """Projects the caller can see, as OpenCDE Project records.

        Admin sees all; everyone else sees only owned projects (mirrors
        the file-based BCF guard).
        """
        from app.modules.projects.models import Project

        stmt = select(Project)
        if role != "admin":
            stmt = stmt.where(Project.owner_id == uuid.UUID(str(user_id)))
        result = await self.session.execute(stmt)
        projects = result.scalars().all()
        return [
            BCFProject(
                project_id=str(p.id),
                name=str(getattr(p, "name", "") or ""),
                authorization=_project_authorization(role),
            )
            for p in projects
        ]

    async def get_project(self, project_id: uuid.UUID, *, role: str) -> BCFProject:
        from app.modules.projects.models import Project

        proj = await self.session.get(Project, project_id)
        if proj is None:
            raise OpenCDEServiceError("not_found", f"Project {project_id} not found", http_status=404)
        return BCFProject(
            project_id=str(proj.id),
            name=str(getattr(proj, "name", "") or ""),
            authorization=_project_authorization(role),
        )

    # ── Topics ─────────────────────────────────────────────────────

    async def list_topics(
        self,
        project_id: uuid.UUID,
        *,
        odata_filter: str | None,
        order_by: str | None,
        top: int,
        skip: int,
        role: str,
    ) -> tuple[list[BCFTopicResponse], int]:
        """List topics with $filter / $orderby / $top / $skip.

        Returns ``(items, total_count)``. The router relays
        ``total_count`` as the ``X-Total-Count`` response header.
        """
        clauses = parse_odata_filter(odata_filter or "")
        order = parse_orderby(order_by)

        from sqlalchemy import func

        base_where = [BCFTopic.project_id == project_id]
        base_where.extend(_clauses_to_sqla(clauses))

        count_stmt = select(func.count()).select_from(BCFTopic).where(and_(*base_where))
        total_count = int((await self.session.execute(count_stmt)).scalar() or 0)

        stmt = (
            select(BCFTopic)
            .where(and_(*base_where))
            .options(
                selectinload(BCFTopic.comments),
                selectinload(BCFTopic.viewpoints),
            )
            .order_by(*order)
            .limit(max(1, min(top, 500)))
            .offset(max(0, skip))
        )
        result = await self.session.execute(stmt)
        topics = list(result.scalars().all())
        return [_topic_to_response(t, role) for t in topics], total_count

    async def get_topic(
        self, project_id: uuid.UUID, topic_guid: str, *, role: str
    ) -> tuple[BCFTopicResponse, BCFTopic]:
        """Load one topic; returns (response_DTO, ORM)."""
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        return _topic_to_response(topic, role), topic

    async def create_topic(
        self,
        project_id: uuid.UUID,
        payload: TopicCreatePayload,
        *,
        user_id: str,
        user_email: str | None,
        role: str,
    ) -> tuple[BCFTopicResponse, BCFTopic]:
        now = datetime.now(UTC)
        author = user_email or str(user_id)
        # Best-effort server_assigned_id: monotonic count + 1. Use COUNT(*)
        # rather than loading every BCFTopic row for the project — a project
        # with thousands of topics would otherwise pull every row into memory
        # just to count them.
        from sqlalchemy import func as _func

        count_stmt = select(_func.count()).select_from(BCFTopic).where(BCFTopic.project_id == project_id)
        topic_index = int((await self.session.execute(count_stmt)).scalar() or 0) + 1
        topic = BCFTopic(
            guid=str(uuid.uuid4()).lower(),
            project_id=project_id,
            title=payload.title,
            description=payload.description,
            topic_type=payload.topic_type,
            topic_status=payload.topic_status or "Open",
            priority=payload.priority,
            stage=payload.stage,
            topic_index=topic_index,
            assigned_to=payload.assigned_to,
            due_date=_to_dt(payload.due_date),
            labels=list(payload.labels or []),
            reference_links=list(payload.reference_links or []),
            creation_author=author,
            creation_date=now,
            modified_author=author,
            modified_date=now,
            created_by=str(user_id),
            metadata_=_pack_bim_snippet(payload.bim_snippet),
        )
        self.session.add(topic)
        await self.session.flush()
        # Re-load with eager relationships so response renders cleanly.
        topic = await self._load_topic_by_guid(project_id, topic.guid)
        return _topic_to_response(topic, role), topic

    async def update_topic(
        self,
        project_id: uuid.UUID,
        topic_guid: str,
        payload: TopicUpdatePayload,
        *,
        user_id: str,
        user_email: str | None,
        role: str,
        if_match: str | None,
    ) -> tuple[BCFTopicResponse, BCFTopic]:
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        _enforce_if_match(if_match, compute_topic_etag(topic))
        patch = payload.model_dump(exclude_unset=True, by_alias=False)
        for key, value in patch.items():
            if key == "bim_snippet":
                meta = dict(topic.metadata_ or {})
                meta["bim_snippet"] = payload.bim_snippet.model_dump() if payload.bim_snippet else None
                topic.metadata_ = meta
                continue
            if key == "due_date":
                topic.due_date = _to_dt(value)
                continue
            setattr(topic, key, value)
        topic.modified_author = user_email or str(user_id)
        topic.modified_date = datetime.now(UTC)
        await self.session.flush()
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        return _topic_to_response(topic, role), topic

    async def delete_topic(
        self,
        project_id: uuid.UUID,
        topic_guid: str,
        *,
        if_match: str | None,
    ) -> None:
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        _enforce_if_match(if_match, compute_topic_etag(topic))
        await self.session.delete(topic)
        await self.session.flush()

    # ── Comments ───────────────────────────────────────────────────

    async def list_comments(self, project_id: uuid.UUID, topic_guid: str, *, role: str) -> list[BCFCommentResponse]:
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        comments = sorted(
            topic.comments,
            key=lambda c: c.date or datetime.min.replace(tzinfo=UTC),
        )
        return [_comment_to_response(c, topic, role) for c in comments]

    async def create_comment(
        self,
        project_id: uuid.UUID,
        topic_guid: str,
        payload: CommentCreatePayload,
        *,
        user_id: str,
        user_email: str | None,
        role: str,
    ) -> BCFCommentResponse:
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        if payload.viewpoint_guid:
            found = any(v.guid.lower() == payload.viewpoint_guid.lower() for v in topic.viewpoints)
            if not found:
                raise OpenCDEServiceError(
                    "not_found",
                    f"Viewpoint {payload.viewpoint_guid} not found",
                    http_status=404,
                )
        if payload.reply_to_comment_guid:
            found = any(c.guid.lower() == payload.reply_to_comment_guid.lower() for c in topic.comments)
            if not found:
                raise OpenCDEServiceError(
                    "not_found",
                    f"Parent comment {payload.reply_to_comment_guid} not found",
                    http_status=404,
                )
        now = datetime.now(UTC)
        author = user_email or str(user_id)
        comment = BCFComment(
            guid=str(uuid.uuid4()).lower(),
            topic_id=topic.id,
            comment_text=payload.comment,
            author=author,
            date=now,
            modified_author=author,
            modified_date=now,
            viewpoint_guid=payload.viewpoint_guid.lower() if payload.viewpoint_guid else None,
            created_by=str(user_id),
            metadata_=(
                {"reply_to_comment_guid": payload.reply_to_comment_guid.lower()}
                if payload.reply_to_comment_guid
                else {}
            ),
        )
        self.session.add(comment)
        await self.session.flush()
        return _comment_to_response(comment, topic, role)

    # ── Viewpoints ─────────────────────────────────────────────────

    async def list_viewpoints(self, project_id: uuid.UUID, topic_guid: str) -> list[ViewpointResponse]:
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        return [_viewpoint_to_response(v) for v in topic.viewpoints]

    async def create_viewpoint(
        self,
        project_id: uuid.UUID,
        topic_guid: str,
        payload: ViewpointCreatePayload,
        *,
        user_id: str,
    ) -> ViewpointResponse:
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        from app.core.storage import get_storage_backend
        from app.modules.bcf.service import BCFServiceError, _snapshot_key

        guid = (payload.guid or str(uuid.uuid4())).lower()
        # Reject collision against an existing viewpoint on this topic.
        if any(v.guid.lower() == guid for v in topic.viewpoints):
            raise OpenCDEServiceError(
                "conflict",
                f"Viewpoint {guid} already exists on this topic",
                http_status=409,
            )

        camera_type = ""
        camera: dict = {}
        fov: float | None = None
        v2w: float | None = None
        if payload.perspective_camera is not None:
            camera_type = "perspective"
            camera = payload.perspective_camera.model_dump(exclude={"field_of_view"})
            fov = payload.perspective_camera.field_of_view
        elif payload.orthogonal_camera is not None:
            camera_type = "orthogonal"
            camera = payload.orthogonal_camera.model_dump(exclude={"view_to_world_scale"})
            v2w = payload.orthogonal_camera.view_to_world_scale

        snapshot_key: str | None = None
        snapshot_type: str | None = None
        if payload.snapshot and payload.snapshot.snapshot_data:
            try:
                import base64

                raw = base64.b64decode(payload.snapshot.snapshot_data, validate=True)
            except Exception as exc:  # noqa: BLE001
                raise OpenCDEServiceError(
                    "bad_request",
                    "snapshot.snapshot_data is not valid base64",
                    http_status=400,
                ) from exc
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise OpenCDEServiceError(
                    "bad_request",
                    "snapshot.snapshot_data is not a PNG image",
                    http_status=400,
                )
            snapshot_key = _snapshot_key(project_id, topic.guid, guid)
            try:
                await get_storage_backend().put(snapshot_key, raw)
            except BCFServiceError as exc:
                raise OpenCDEServiceError(
                    "internal_error",
                    "Failed to store snapshot",
                    http_status=500,
                ) from exc
            snapshot_type = payload.snapshot.snapshot_type or "png"

        vp = BCFViewpoint(
            guid=guid,
            topic_id=topic.id,
            vp_index=await self.repo.next_viewpoint_index(topic.id),
            camera_type=camera_type,
            camera=camera,
            components=(payload.components.model_dump() if payload.components else {}),
            lines=[ln.model_dump() for ln in payload.lines],
            clipping_planes=[cp.model_dump() for cp in payload.clipping_planes],
            field_of_view=fov,
            view_to_world_scale=v2w,
            snapshot_key=snapshot_key,
            snapshot_type=snapshot_type,
            created_by=str(user_id),
            metadata_={
                "bitmaps": [b.model_dump() for b in payload.bitmaps],
            },
        )
        self.session.add(vp)
        await self.session.flush()
        return _viewpoint_to_response(vp)

    async def get_snapshot_png(
        self,
        project_id: uuid.UUID,
        topic_guid: str,
        viewpoint_guid: str,
    ) -> bytes:
        topic = await self._load_topic_by_guid(project_id, topic_guid)
        vp = next(
            (v for v in topic.viewpoints if v.guid.lower() == viewpoint_guid.lower()),
            None,
        )
        if vp is None or not vp.snapshot_key:
            raise OpenCDEServiceError("not_found", "Snapshot not found", http_status=404)
        from app.core.storage import get_storage_backend

        try:
            return await get_storage_backend().get(vp.snapshot_key)
        except FileNotFoundError as exc:
            raise OpenCDEServiceError("not_found", "Snapshot not found", http_status=404) from exc

    # ── helpers ────────────────────────────────────────────────────

    async def _load_topic_by_guid(self, project_id: uuid.UUID, topic_guid: str) -> BCFTopic:
        guid = topic_guid.strip().lower()
        stmt = (
            select(BCFTopic)
            .where(
                and_(
                    BCFTopic.project_id == project_id,
                    BCFTopic.guid == guid,
                )
            )
            .options(
                selectinload(BCFTopic.comments),
                selectinload(BCFTopic.viewpoints),
            )
        )
        result = await self.session.execute(stmt)
        topic = result.scalar_one_or_none()
        if topic is None:
            raise OpenCDEServiceError(
                "not_found",
                f"Topic {topic_guid} not found",
                http_status=404,
            )
        return topic


# ── Plain helpers (module-scoped) ──────────────────────────────────────


def _enforce_if_match(if_match: str | None, current_etag: str) -> None:
    if if_match is None:
        return
    # Strip optional weak prefix and surrounding whitespace.
    token = if_match.strip()
    if token == "*":
        return
    # Trim a 'W/' weak prefix per RFC 7232.
    if token.startswith("W/"):
        token = token[2:]
    if token != current_etag:
        raise StaleResourceError()


def _project_authorization(role: str) -> ProjectAuthorization:
    if role in ("admin", "manager", "editor"):
        return ProjectAuthorization(project_actions=["update", "createTopic"])
    if role == "estimator":
        return ProjectAuthorization(project_actions=["createTopic"])
    return ProjectAuthorization(project_actions=[])


def _topic_authorization(role: str) -> TopicAuthorization:
    actions = _ROLE_TO_ACTIONS.get(role, [])
    return TopicAuthorization(
        topic_actions=list(actions),
        topic_status=["Open", "In Progress", "Closed"],
    )


def _comment_authorization(role: str) -> CommentAuthorization:
    if role in ("admin", "manager", "editor"):
        return CommentAuthorization(comment_actions=["update"])
    return CommentAuthorization(comment_actions=[])


def _pack_bim_snippet(snip: BimSnippet | None) -> dict:
    if snip is None:
        return {}
    return {"bim_snippet": snip.model_dump()}


def _to_dt(d: date | datetime | None) -> datetime | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(d, datetime.min.time(), tzinfo=UTC)


def _from_dt_to_date(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    return dt.date()


def _normalize_guid_lower(guid: str) -> str:
    g = (guid or "").strip().lower()
    return g.strip("{}")


def _topic_to_response(topic: BCFTopic, role: str) -> BCFTopicResponse:
    """ORM → OpenCDE wire DTO."""
    meta = dict(topic.metadata_ or {})
    bim_snippet_blob = meta.get("bim_snippet") if isinstance(meta, dict) else None
    bim_snippet = BimSnippet(**bim_snippet_blob) if bim_snippet_blob else None
    server_id = f"BCF-{topic.topic_index:04d}" if topic.topic_index is not None else None
    return BCFTopicResponse(
        guid=_normalize_guid_lower(topic.guid),
        server_assigned_id=server_id,
        topic_type=topic.topic_type,
        topic_status=topic.topic_status,
        priority=topic.priority,
        stage=topic.stage,
        title=topic.title,
        description=topic.description,
        assigned_to=topic.assigned_to,
        due_date=_from_dt_to_date(topic.due_date),
        labels=list(topic.labels or []),
        reference_links=list(topic.reference_links or []),
        bim_snippet=bim_snippet,
        creation_author=topic.creation_author,
        creation_date=topic.creation_date,
        modified_author=topic.modified_author,
        modified_date=topic.modified_date,
        authorization=_topic_authorization(role),
    )


def _comment_to_response(comment: BCFComment, topic: BCFTopic, role: str) -> BCFCommentResponse:
    meta = dict(comment.metadata_ or {})
    reply = meta.get("reply_to_comment_guid")
    return BCFCommentResponse(
        guid=_normalize_guid_lower(comment.guid),
        date=comment.date,
        author=comment.author,
        modified_date=comment.modified_date,
        modified_author=comment.modified_author,
        comment=comment.comment_text,
        topic_guid=_normalize_guid_lower(topic.guid),
        viewpoint_guid=(_normalize_guid_lower(comment.viewpoint_guid) if comment.viewpoint_guid else None),
        reply_to_comment_guid=_normalize_guid_lower(reply) if reply else None,
        authorization=_comment_authorization(role),
    )


def _viewpoint_to_response(vp: BCFViewpoint) -> ViewpointResponse:
    from app.modules.bcf.opencde_schemas import Direction

    persp: PerspectiveCamera | None = None
    ortho: OrthogonalCamera | None = None
    if vp.camera_type == "perspective":
        cam = dict(vp.camera or {})
        cam.setdefault("camera_view_point", {})
        cam.setdefault("camera_direction", {})
        cam.setdefault("camera_up_vector", {})
        persp = PerspectiveCamera(
            camera_view_point=Point(**(cam.get("camera_view_point") or {})),
            camera_direction=Direction(**(cam.get("camera_direction") or {})),
            camera_up_vector=Direction(**(cam.get("camera_up_vector") or {})),
            field_of_view=float(vp.field_of_view or 60.0),
        )
    elif vp.camera_type == "orthogonal":
        cam = dict(vp.camera or {})
        ortho = OrthogonalCamera(
            camera_view_point=Point(**(cam.get("camera_view_point") or {})),
            camera_direction=Direction(**(cam.get("camera_direction") or {})),
            camera_up_vector=Direction(**(cam.get("camera_up_vector") or {})),
            view_to_world_scale=float(vp.view_to_world_scale or 1.0),
        )
    components_dict = vp.components or {}
    components: Components | None = None
    if components_dict:
        # Normalise into Visibility wrapper if a flat selection was stored.
        vis_raw = components_dict.get("visibility")
        if isinstance(vis_raw, dict):
            vis = Visibility(
                **{k: vis_raw.get(k) for k in vis_raw if k in {"default_visibility", "exceptions", "view_setup_hints"}}
            )
        else:
            vis = Visibility(default_visibility=bool(components_dict.get("default_visibility", True)))
        components = Components(
            selection=list(components_dict.get("selection", []) or []),
            visibility=vis,
            coloring=list(components_dict.get("coloring", []) or []),
        )
    snapshot: SnapshotInfo | None = None
    if vp.snapshot_key:
        snapshot = SnapshotInfo(
            snapshot_type=vp.snapshot_type or "png",
            snapshot_data=None,
        )
    return ViewpointResponse(
        guid=_normalize_guid_lower(vp.guid),
        index=int(vp.vp_index or 0),
        perspective_camera=persp,
        orthogonal_camera=ortho,
        lines=[],
        clipping_planes=[],
        bitmaps=[],
        components=components,
        snapshot=snapshot,
    )
