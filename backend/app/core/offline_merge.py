# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared offline-sync plumbing for versioned field records​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Used by daily_diary, punchlist and inspections:

* ``client_op_id`` de-duplication: a phone that retries a create after a lost
  response must not produce a second row.
* The merge endpoint: the client has seen the current version, resolved any
  conflicted long-text or list field, and sends the result. The merge is
  validated (``offline_sync.merge_complete``), applied, version-bumped,
  audited field by field and announced on the event bus.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import get_activity_for_entity, log_activity
from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.optimistic_lock import CLIENT_OP_ID_PATTERN, bump, check_version, three_way_merge, unresolved_conflicts
from app.core.validation.engine import validation_engine

logger = logging.getLogger(__name__)

MERGE_ACTION = "offline_merge"
RULE_SET = "offline_sync"
_CLIENT_OP_ID_RE = re.compile(CLIENT_OP_ID_PATTERN)
_MAX_TEXT = 20000


@dataclass(frozen=True)
class MergeSpec:
    """What one entity lets the merge endpoint touch.

    Attributes:
        entity_type: Audit ``entity_type`` and validation ``target_type``.
        module: Module name used for the audit row and the event prefix.
        fields: Mergeable column -> kind (``text``, ``str`` or ``str<max length>``, ``int``, ``list``, ``dict``).
        long_text_fields: Free-text fields that are never auto-merged.
        list_fields: Checklist-like fields that are never auto-merged.
    """

    entity_type: str
    module: str
    fields: dict[str, str]
    long_text_fields: frozenset[str] = frozenset()
    list_fields: frozenset[str] = frozenset()

    @property
    def event_name(self) -> str:
        """Event published after a merge is applied."""
        return f"{self.module}.offline_merge_resolved"


class OfflineMergeRequest(BaseModel):
    """Body of ``POST .../{id}/merge/``."""

    base_version: int = Field(..., ge=1, description="Version the device edited offline.")
    against_version: int = Field(..., ge=1, description="Current version the device resolved against.")
    fields: dict[str, Any] = Field(default_factory=dict)
    resolutions: dict[str, str] = Field(default_factory=dict)
    base: dict[str, Any] | None = Field(
        default=None,
        description="Optional values of the edited fields at base_version, for a precise three-way merge.",
    )
    device_id: str | None = Field(default=None, max_length=64)


class MergedFieldOut(BaseModel):
    """One field of a merge, as recorded in the audit trail."""

    field: str
    side: str
    old_value: Any = None
    new_value: Any = None


class OfflineMergeResponse(BaseModel):
    """Result of a merge: the new version, what happened per field, the row."""

    version: int
    merged: list[MergedFieldOut]
    item: dict[str, Any]


class MergeAuditOut(BaseModel):
    """One audit row written by a merge."""

    id: str
    created_at: str | None = None
    field: str | None = None
    side: str | None = None
    old_value: Any = None
    new_value: Any = None
    actor_id: str | None = None
    device_id: str | None = None
    base_version: int | None = None
    version: int | None = None


# -- client_op_id --------------------------------------------------------------


def clean_client_op_id(value: str | None) -> str | None:
    """Return the op id when it is well formed, ``None`` when absent or malformed."""
    if value and _CLIENT_OP_ID_RE.match(value):
        return value
    return None


async def find_by_client_op_id(session: AsyncSession, model: Any, op_id: str | None, *where: Any) -> Any | None:
    """Find a row created earlier with the same ``client_op_id``.

    The id lives in the row's ``metadata`` JSON. The JSON text is pre-filtered
    with LIKE (portable across SQLite and PostgreSQL) and then checked exactly
    in Python, so a stray substring match never returns the wrong row.
    """
    op = clean_client_op_id(op_id)
    if op is None:
        return None
    stmt = select(model).where(*where).where(cast(model.metadata_, String).like(f"%{op}%"))
    for row in (await session.execute(stmt)).scalars().all():
        if (getattr(row, "metadata_", None) or {}).get("client_op_id") == op:
            return row
    return None


async def stamp_client_op_id(session: AsyncSession, obj: Any, op_id: str | None) -> None:
    """Record ``client_op_id`` in the row's metadata (a new dict, so the change is tracked)."""
    op = clean_client_op_id(op_id)
    if op is None:
        return
    obj.metadata_ = {**(getattr(obj, "metadata_", None) or {}), "client_op_id": op}
    await session.flush()


# -- merge ---------------------------------------------------------------------


def _unprocessable(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": code, "message": message, **extra},
    )


def _check_value(spec: MergeSpec, name: str, value: Any) -> None:
    kind = spec.fields[name]
    ok = True
    if kind == "text":
        ok = value is None or (isinstance(value, str) and len(value) <= _MAX_TEXT)
    elif kind.startswith("str"):
        limit = int(kind[3:] or 500)
        ok = value is None or (isinstance(value, str) and len(value) <= limit)
    elif kind == "int":
        ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    elif kind == "list":
        ok = isinstance(value, list)
    elif kind == "dict":
        ok = isinstance(value, dict)
    if not ok:
        raise _unprocessable("invalid_merge_field", f"The value for '{name}' is not valid.", field=name)


def detect_conflicts(spec: MergeSpec, request: OfflineMergeRequest, current: dict[str, Any]) -> list[str]:
    """Long-text or list fields the device changed that also differ on the server."""
    guarded = spec.long_text_fields | spec.list_fields
    if request.base is not None:
        names = [n for n in request.fields if n in spec.fields]
        result = three_way_merge(
            {n: request.base.get(n) for n in names},
            {n: request.fields[n] for n in names},
            {n: current.get(n) for n in names},
            spec.long_text_fields,
            spec.list_fields,
        )
        return list(result["conflicts"])
    if request.base_version == request.against_version:
        return []
    return [n for n in request.fields if n in guarded and request.fields[n] != current.get(n)]


def _check_request(spec: MergeSpec, request: OfflineMergeRequest) -> None:
    for name in set(request.fields) | set(request.resolutions):
        if name not in spec.fields:
            raise _unprocessable("unknown_merge_field", f"'{name}' cannot be merged.", field=name)
    for name, value in request.fields.items():
        _check_value(spec, name, value)
    for name, side in request.resolutions.items():
        if side not in ("mine", "theirs", "manual"):
            raise _unprocessable("invalid_resolution", f"'{side}' is not a valid resolution.", field=name)
        if side in ("mine", "manual") and name not in request.fields:
            raise _unprocessable(
                "resolution_without_value", f"Resolution '{side}' for '{name}' needs a value in fields.", field=name
            )


async def apply_merge(
    session: AsyncSession,
    obj: Any,
    spec: MergeSpec,
    request: OfflineMergeRequest,
    *,
    actor_id: str | None,
    project_id: uuid.UUID | str,
    current_payload: dict[str, Any],
) -> tuple[int, list[MergedFieldOut]]:
    """Validate, apply, bump, audit and announce one merge.

    Args:
        session: Session of the request transaction.
        obj: The ORM row (must carry ``version``).
        spec: Which fields of this entity may be merged.
        request: The client's merge body.
        actor_id: User performing the merge.
        project_id: Owning project, for the audit parent and the event.
        current_payload: The serialized current row, returned inside a 409.

    Returns:
        The new version and the per-field outcome.

    Raises:
        HTTPException: 409 when ``against_version`` is stale, 422 for unknown
            fields, bad values or an unresolved conflict.
    """
    check_version(int(obj.version or 1), request.against_version, current_payload)
    _check_request(spec, request)

    current = {name: getattr(obj, name, None) for name in spec.fields}
    conflicts = detect_conflicts(spec, request, current)
    await _validate_complete(spec, obj, project_id, conflicts, request.resolutions)

    merged: list[MergedFieldOut] = []
    for name in sorted(set(request.fields) | set(request.resolutions)):
        side = request.resolutions.get(name, "mine")
        old = current[name]
        new = old if side == "theirs" else request.fields[name]
        if side != "theirs":
            setattr(obj, name, new)
        merged.append(MergedFieldOut(field=name, side=side, old_value=old, new_value=new))
    new_version = bump(obj)
    await session.flush()

    for item in merged:
        await log_activity(
            session,
            actor_id=actor_id,
            entity_type=spec.entity_type,
            entity_id=str(obj.id),
            action=MERGE_ACTION,
            reason=f"Offline merge of {item.field} ({item.side})",
            module=spec.module,
            parent_entity_type="project",
            parent_entity_id=str(project_id),
            before_state={item.field: item.old_value},
            after_state={item.field: item.new_value},
            metadata={
                "field": item.field,
                "side": item.side,
                "device_id": request.device_id,
                "base_version": request.base_version,
                "version": new_version,
            },
        )
    event_bus.publish_detached(
        spec.event_name,
        {
            "entity_type": spec.entity_type,
            "entity_id": str(obj.id),
            "project_id": str(project_id),
            "version": new_version,
            "fields": [m.field for m in merged],
            "sides": {m.field: m.side for m in merged},
            "device_id": request.device_id,
            "actor_id": actor_id,
        },
        source_module=spec.module,
    )
    return new_version, merged


async def _validate_complete(
    spec: MergeSpec,
    obj: Any,
    project_id: uuid.UUID | str,
    conflicts: list[str],
    resolutions: dict[str, str],
) -> None:
    """Run the ``offline_sync`` rule set; 422 when a conflict has no resolution."""
    report = await validation_engine.validate(
        data={"conflicts": conflicts, "resolutions": dict(resolutions)},
        rule_sets=[RULE_SET],
        target_type=spec.entity_type,
        target_id=str(obj.id),
        project_id=str(project_id),
        metadata={"locale": get_locale(), "operation": "merge"},
    )
    # The direct check is a backstop: with the rule set unregistered the engine
    # passes silently, and a silent pass here would drop a person's text.
    missing = unresolved_conflicts(conflicts, resolutions)
    if report.has_errors or missing:
        raise _unprocessable(
            "merge_incomplete",
            "Choose mine, theirs or a manual value for every conflicted field, then send the merge again.",
            conflicts=missing or conflicts,
            errors=[{"rule_id": r.rule_id, "message": r.message, "element_ref": r.element_ref} for r in report.errors],
        )


def _audit_out(row: Any) -> MergeAuditOut:
    meta = row.metadata_ or {}
    field = meta.get("field")
    return MergeAuditOut(
        id=str(row.id),
        created_at=row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        field=field,
        side=meta.get("side"),
        old_value=(row.before_state or {}).get(field),
        new_value=(row.after_state or {}).get(field),
        actor_id=str(row.actor_id) if row.actor_id else None,
        device_id=meta.get("device_id"),
        base_version=meta.get("base_version"),
        version=meta.get("version"),
    )


async def list_merge_audit(session: AsyncSession, entity_type: str, entity_id: uuid.UUID | str) -> list[MergeAuditOut]:
    """Merge audit rows for one entity, oldest first."""
    rows = await get_activity_for_entity(session, entity_type=entity_type, entity_id=entity_id, limit=1000)
    return [_audit_out(r) for r in rows if r.action == MERGE_ACTION]
