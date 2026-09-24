# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lifecycle of an assistant proposal: propose, review, apply, reject, undo.

The chat stream calls :func:`propose_tool_result` (or :func:`propose_action`)
when the model uses a ``propose_*`` tool. That validates the arguments through
the action's spec and stores a ``proposed`` row. It writes nothing else: no
position, no task. It flushes and does NOT commit; the stream decides when the
row becomes visible to other requests (commit the chat session row first, the
action row points at it).

Everything after that is a person acting through the REST endpoints in
``actions/router.py``, and every step runs for the caller:

* visibility - the caller asked for the change, or can open its project;
* apply - the gates of the record's own REST route, a re-validation against
  the database as it is now (a locked bill, a line someone else changed), then
  the domain write through the domain service with the caller as the actor,
  the route's own side effects, and an ``oe_activity_log`` row that says it
  came through the assistant, who asked, who approved and with what
  confidence. A domain refusal marks the action ``failed`` with the reason, in
  its own savepoint, so a batch never loses the rows that did apply;
* undo - only for an applied action whose record still holds what was applied.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_, select, true, update

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionContext,
    ActionDraft,
    ActionError,
    ActionNotFoundError,
    ActionPermissionError,
    ActionSpec,
    ActionValidationError,
    coerce_uuid,
    error_from_http,
)
from app.modules.erp_chat.actions.registry import (
    get_registered_spec_for_tool,
    get_spec,
    get_spec_for_tool,
    is_available,
)
from app.modules.erp_chat.models import ChatAction
from app.modules.erp_chat.schemas import (
    ActionEntityRef,
    ActionField,
    ActionNote,
    ActionUserRef,
    ChatActionCounts,
    ChatActionResponse,
)

logger = logging.getLogger(__name__)

STATUSES: tuple[str, ...] = ("proposed", "applied", "rejected", "failed", "reverted")
PENDING: frozenset[str] = frozenset({"proposed", "failed"})
MAX_RATIONALE = 1000
MAX_SUMMARY = 500


def _now() -> datetime:
    return datetime.now(UTC)


def _clamp_confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    if number > 1 and number <= 100:
        number = number / 100  # a model that answered in percent
    return max(0.0, min(1.0, number))


def _short_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass
class Viewer:
    """The person calling an endpoint, resolved once per request.

    ``accessible_projects`` is None for an admin (every project) and otherwise
    the set of projects the person owns or is a team member of, the same rule
    ``verify_project_access`` applies one project at a time.
    """

    ctx: ActionContext
    accessible_projects: set[uuid.UUID] | None

    @property
    def user_id(self) -> uuid.UUID:
        return self.ctx.user_id

    def can_open_project(self, project_id: uuid.UUID | None) -> bool:
        """Whether the person may open ``project_id`` (None: the action has no project)."""
        if project_id is None:
            return True
        return self.accessible_projects is None or project_id in self.accessible_projects

    def can_see(self, action: ChatAction) -> bool:
        """Visible when the person asked for it, or can open its project."""
        if action.requested_by == self.user_id:
            return True
        return action.project_id is not None and self.can_open_project(action.project_id)


@dataclass(frozen=True)
class Abilities:
    """What the viewer may do with one action now.

    ``blocked_by`` says why a pending action cannot be applied by this viewer:
    ``"permission"`` (their role or project access) or ``"module_unavailable"``
    (the module it writes to is switched off, so nobody can). None otherwise.
    """

    can_apply: bool
    can_edit: bool
    can_reject: bool
    can_revert: bool
    blocked_by: str | None


class ChatActionService:
    """Proposals and their lifecycle. Flushes; the caller commits."""

    def __init__(self, session: Any) -> None:
        self.session = session

    # ── Who is asking ─────────────────────────────────────────────────────

    async def viewer(self, user_id: str | uuid.UUID) -> Viewer:
        """Resolve the caller's role and reachable projects once for the whole request."""
        from app.dependencies import accessible_project_ids

        ctx = await ActionContext.load(self.session, user_id)
        accessible = await accessible_project_ids(self.session, str(ctx.user_id))
        return Viewer(ctx=ctx, accessible_projects=accessible)

    # ── Propose ───────────────────────────────────────────────────────────

    async def propose(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        user_id: str | uuid.UUID,
        chat_session_id: str | uuid.UUID | None = None,
        project_id: str | uuid.UUID | None = None,
        batch_id: str | None = None,
        message_id: str | uuid.UUID | None = None,
        summary: str | None = None,
    ) -> ChatAction:
        """Validate a tool call through its spec and store it as ``proposed``. No domain write.

        Args:
            tool_name: The ``propose_*`` tool name (an action type is accepted too).
            args: The model's arguments, ``confidence`` and ``rationale`` included.
            user_id: The person talking to the assistant.
            chat_session_id: The conversation the proposal belongs to.
            project_id: The project open in the app; used when ``args`` names none.
            batch_id: One id per assistant turn, shared by that turn's proposals.
            message_id: The assistant message, when it is already persisted.
            summary: One line describing the change, if the caller has one.

        Raises:
            ActionError: Validation, access or state problems, for the model to act on.
        """
        spec = get_spec_for_tool(tool_name) or get_spec(tool_name, available_only=True)
        if spec is None:
            known = get_registered_spec_for_tool(tool_name) or get_spec(tool_name)
            if known is not None:
                raise ActionConflictError(code="module_unavailable", params={"action_type": known.action_type})
            raise ActionValidationError(code="unknown_action", params={"tool": tool_name})
        clean = dict(args or {})
        confidence = _clamp_confidence(clean.pop("confidence", None))
        rationale = _short_text(clean.pop("rationale", None), MAX_RATIONALE)
        ctx = await ActionContext.load(self.session, user_id, project_id=project_id)
        draft = await spec.build(ctx, clean)
        action = ChatAction(
            session_id=coerce_uuid(chat_session_id),
            message_id=coerce_uuid(message_id),
            project_id=draft.project_id,
            requested_by=ctx.user_id,
            action_type=spec.action_type,
            status="proposed",
            title=spec.title,
            summary=_short_text(summary, MAX_SUMMARY),
            original_payload=copy.deepcopy(draft.payload),
            payload=copy.deepcopy(draft.payload),
            preview=draft.preview(),
            confidence=confidence,
            rationale=rationale,
            target_entity_type=draft.target.entity_type if draft.target else None,
            target_entity_id=draft.target.entity_id if draft.target else None,
            before_state=copy.deepcopy(draft.before_state) if draft.before_state is not None else None,
            batch_id=_short_text(batch_id, 64),
        )
        self.session.add(action)
        await self.session.flush()
        return action

    async def attach_message(self, *, batch_id: str, message_id: str | uuid.UUID) -> int:
        """Point a turn's proposals at the assistant message that carried them."""
        mid = coerce_uuid(message_id)
        if not batch_id or mid is None:
            return 0
        result = await self.session.execute(
            update(ChatAction)
            .where(ChatAction.batch_id == batch_id, ChatAction.message_id.is_(None))
            .values(message_id=mid)
        )
        return int(result.rowcount or 0)

    # ── Read ──────────────────────────────────────────────────────────────

    async def _load(self, action_id: uuid.UUID) -> ChatAction | None:
        stmt = select(ChatAction).where(ChatAction.id == action_id).execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_visible(self, action_id: uuid.UUID, viewer: Viewer) -> ChatAction:
        """The action, or 404 when it is missing or not the caller's to see."""
        action = await self._load(action_id)
        if action is None or not viewer.can_see(action):
            raise ActionNotFoundError(code="not_found")
        return action

    def _visibility(self, viewer: Viewer) -> Any:
        if viewer.accessible_projects is None:
            return true()
        clauses = [ChatAction.requested_by == viewer.user_id]
        if viewer.accessible_projects:
            clauses.append(ChatAction.project_id.in_(list(viewer.accessible_projects)))
        return or_(*clauses)

    async def list(
        self,
        viewer: Viewer,
        *,
        project_id: uuid.UUID | None = None,
        statuses: list[str] | None = None,
        session_id: uuid.UUID | None = None,
        batch_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ChatAction], int, ChatActionCounts]:
        """A page of visible actions, newest first, plus per-status counts under the same filters."""
        filters = [self._visibility(viewer)]
        if project_id is not None:
            filters.append(ChatAction.project_id == project_id)
        if session_id is not None:
            filters.append(ChatAction.session_id == session_id)
        if batch_id:
            filters.append(ChatAction.batch_id == batch_id)

        count_rows = (
            await self.session.execute(
                select(ChatAction.status, func.count(ChatAction.id)).where(*filters).group_by(ChatAction.status)
            )
        ).all()
        counts = ChatActionCounts(**{st: int(n) for st, n in count_rows if st in STATUSES})

        page_filters = list(filters)
        if statuses:
            page_filters.append(ChatAction.status.in_(statuses))
        total = int(
            (await self.session.execute(select(func.count(ChatAction.id)).where(*page_filters))).scalar_one() or 0
        )
        rows = (
            (
                await self.session.execute(
                    select(ChatAction)
                    .where(*page_filters)
                    .order_by(ChatAction.created_at.desc(), ChatAction.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total, counts

    # ── Abilities ─────────────────────────────────────────────────────────

    def _spec(self, action: ChatAction) -> ActionSpec:
        """The spec of a stored action, refused while the module it writes to is switched off."""
        spec = get_spec(action.action_type)
        if spec is None:
            raise ActionConflictError(code="unknown_action", params={"action_type": action.action_type})
        if not is_available(spec):
            raise ActionConflictError(code="module_unavailable", params={"action_type": action.action_type})
        return spec

    def abilities(self, action: ChatAction, viewer: Viewer) -> Abilities:
        """What ``viewer`` may do with ``action`` now, under the record's own REST gates.

        While the module an action writes to is switched off, its REST routes
        are gone, so nobody may apply, edit or undo it; the person who asked,
        or anyone entitled to apply it, may still reject it.
        """
        spec = get_spec(action.action_type)
        available = spec is not None and is_available(spec)
        ctx = viewer.ctx
        opens_project = viewer.can_open_project(action.project_id)
        entitled = spec is not None and opens_project and all(ctx.has_permission(p) for p in spec.apply_permissions)
        may_apply = entitled and available
        asked = action.requested_by == viewer.user_id
        pending = action.status in PENDING
        can_apply = pending and may_apply
        can_edit = action.status == "proposed" and available and opens_project and (asked or may_apply)
        can_reject = pending and (asked or entitled)
        can_revert = (
            action.status == "applied"
            and spec is not None
            and spec.reversible
            and available
            and opens_project
            and all(ctx.has_permission(p) for p in spec.revert_permissions)
        )
        blocked_by = None
        if pending and not can_apply:
            blocked_by = "permission" if available else "module_unavailable"
        return Abilities(
            can_apply=can_apply,
            can_edit=can_edit,
            can_reject=can_reject,
            can_revert=can_revert,
            blocked_by=blocked_by,
        )

    # ── Edit, reject ──────────────────────────────────────────────────────

    async def patch(self, action_id: uuid.UUID, viewer: Viewer, patch: dict[str, Any]) -> ChatAction:
        """Lay a person's edits over a pending proposal, re-validate it and rebuild its preview.

        ``original_payload`` is never touched, so what the model proposed and
        what the person changed stay distinguishable.
        """
        action = await self.get_visible(action_id, viewer)
        if action.status != "proposed":
            raise ActionConflictError(code="not_editable")
        spec = self._spec(action)
        if not self.abilities(action, viewer).can_edit:
            raise ActionPermissionError(code="forbidden")
        editable = {f.get("key") for f in (action.preview or {}).get("fields", []) if f.get("editable")}
        allowed = editable | set(spec.patch_aliases)
        unknown = sorted(set(patch) - allowed)
        if unknown:
            raise ActionValidationError(
                code="validation_error",
                field_errors={
                    key: {
                        "code": "not_editable",
                        "message_key": f"{labels.FIELD_ERROR_PREFIX}not_editable",
                        "message": labels.FIELD_ERRORS["not_editable"],
                    }
                    for key in unknown
                },
            )
        merged = spec.merge_patch(copy.deepcopy(action.payload or {}), dict(patch))
        ctx = viewer.ctx.with_project(action.project_id)
        draft = await spec.build(ctx, merged, prior=action)
        self._store_draft(action, draft)
        await self.session.flush()
        return action

    async def reject(self, action_id: uuid.UUID, viewer: Viewer, note: str | None = None) -> ChatAction:
        """Decline a pending proposal. Nothing reaches the domain."""
        action = await self.get_visible(action_id, viewer)
        if action.status not in PENDING:
            raise ActionConflictError(code="not_pending")
        if not self.abilities(action, viewer).can_reject:
            raise ActionPermissionError(code="forbidden")
        action.status = "rejected"
        action.decided_by = viewer.user_id
        action.decided_at = _now()
        action.decision_note = _short_text(note, 2000)
        await self.session.flush()
        return action

    def _store_draft(self, action: ChatAction, draft: ActionDraft) -> None:
        action.payload = copy.deepcopy(draft.payload)
        action.preview = draft.preview()
        if draft.target is not None:
            action.target_entity_type = draft.target.entity_type
            action.target_entity_id = draft.target.entity_id

    # ── Apply ─────────────────────────────────────────────────────────────

    async def apply(self, action_id: uuid.UUID, viewer: Viewer) -> ChatAction:
        """Apply one proposal for the caller. See the module docstring for the steps."""
        action = await self.get_visible(action_id, viewer)
        return await self._apply(action, viewer)

    async def _apply(self, action: ChatAction, viewer: Viewer) -> ChatAction:
        if action.status not in PENDING:
            raise ActionConflictError(code="not_pending")
        spec = self._spec(action)
        ctx = viewer.ctx.with_project(action.project_id)
        # The REST route's gates first (403, then 404), then the state as it is now.
        await spec.check_apply_gates(ctx, dict(action.payload or {}))
        draft = await spec.build(ctx, copy.deepcopy(action.payload or {}), prior=action)
        self._store_draft(action, draft)
        await self.session.flush()

        action_id = action.id
        try:
            async with self.session.begin_nested():
                applied = await spec.apply(ctx, action, draft)
                await self._audit(
                    ctx,
                    action,
                    spec,
                    entity_type=applied.entity_type,
                    entity_id=applied.entity_id,
                    audit_action=applied.audit_action,
                    before_state=applied.before_state,
                    after_state=applied.after_state,
                    url=applied.url,
                    label=applied.label,
                )
        except Exception as exc:  # noqa: BLE001 - every refusal of the domain write is recorded
            error = self._domain_error(exc, action_id)
            refreshed = await self._load(action_id)
            action = refreshed if refreshed is not None else action
            action.status = "failed"
            action.error = error.message
            action.error_code = error.code
            action.decided_by = ctx.user_id
            action.decided_at = _now()
            await self.session.flush()
            return action

        action.status = "applied"
        action.decided_by = ctx.user_id
        action.decided_at = _now()
        action.applied_entity_type = applied.entity_type
        action.applied_entity_id = applied.entity_id
        action.result = {"label": applied.label, "url": applied.url, "after_state": applied.after_state}
        action.error = None
        action.error_code = None
        await self.session.flush()
        return action

    @staticmethod
    def _domain_error(exc: Exception, action_id: uuid.UUID) -> ActionError:
        if isinstance(exc, ActionError):
            return exc
        if isinstance(exc, HTTPException):
            return error_from_http(exc)
        if isinstance(exc, (ValueError, ValidationError)):
            return ActionValidationError(str(exc)[:500] or None, code="domain_error")
        logger.exception("erp_chat action %s: domain write failed", action_id)
        return ActionConflictError(code="internal_error")

    async def apply_batch(
        self,
        ids: list[uuid.UUID],
        viewer: Viewer,
    ) -> tuple[list[ChatAction], list[dict[str, Any]]]:
        """Apply several proposals, each on its own: one refusal never undoes another.

        Proposals are applied in the order they were made, so lines proposed in
        one turn are numbered in that order. Returns every visible action in its
        new state (in the order asked) and one error entry per id that was
        refused before its write started (not visible, already decided, gates,
        a locked bill, a line changed since). A refusal of the write itself
        leaves the action ``failed`` and is not repeated in the errors.
        """
        errors: list[dict[str, Any]] = []
        seen: set[uuid.UUID] = set()
        loaded: list[ChatAction] = []
        for action_id in ids:
            if action_id in seen:
                continue
            seen.add(action_id)
            try:
                loaded.append(await self.get_visible(action_id, viewer))
            except ActionError as exc:
                errors.append(self._batch_error(action_id, exc))
        by_id: dict[uuid.UUID, ChatAction] = {}
        for action in sorted(loaded, key=lambda a: (a.created_at, str(a.id))):
            action_id = action.id
            try:
                by_id[action_id] = await self._apply(action, viewer)
            except ActionError as exc:
                errors.append(self._batch_error(action_id, exc))
                by_id[action_id] = await self._load(action_id) or action
        ordered = [by_id[a] for a in (x for x in ids if x in by_id)]
        unique: list[ChatAction] = []
        for action in ordered:
            if action not in unique:
                unique.append(action)
        return unique, errors

    @staticmethod
    def _batch_error(action_id: uuid.UUID, exc: ActionError) -> dict[str, Any]:
        return {
            "id": action_id,
            "status_code": exc.status_code,
            "code": exc.code,
            "message": exc.message,
            "message_key": exc.message_key,
        }

    # ── Undo ──────────────────────────────────────────────────────────────

    async def revert(self, action_id: uuid.UUID, viewer: Viewer, note: str | None = None) -> ChatAction:
        """Undo an applied action, when its record still holds what was applied."""
        action = await self.get_visible(action_id, viewer)
        if action.status != "applied":
            raise ActionConflictError(code="not_applied")
        spec = self._spec(action)
        if not spec.reversible:
            raise ActionConflictError(code="not_reversible")
        ctx = viewer.ctx.with_project(action.project_id)
        await spec.check_revert_gates(ctx, action)
        applied_state = (action.result or {}).get("after_state")
        try:
            async with self.session.begin_nested():
                state = await spec.revert(ctx, action)
                await self._audit(
                    ctx,
                    action,
                    spec,
                    entity_type=action.applied_entity_type or spec.entity_type,
                    entity_id=action.applied_entity_id or "",
                    audit_action="reverted",
                    before_state=applied_state,
                    after_state=state,
                    # An undo that deleted the record leaves nothing to link to.
                    url=(action.result or {}).get("url") if state is not None else None,
                    label=(action.result or {}).get("label"),
                )
        except ActionError:
            raise
        except HTTPException as exc:
            raise error_from_http(exc) from exc
        except (ValueError, ValidationError) as exc:
            raise ActionValidationError(str(exc)[:500] or None, code="domain_error") from exc
        action.status = "reverted"
        action.reverted_by = ctx.user_id
        action.reverted_at = _now()
        action.revert_note = _short_text(note, 2000)
        await self.session.flush()
        return action

    # ── Audit ─────────────────────────────────────────────────────────────

    async def _audit(
        self,
        ctx: ActionContext,
        action: ChatAction,
        spec: ActionSpec,
        *,
        entity_type: str,
        entity_id: str,
        audit_action: str,
        before_state: dict[str, Any] | None,
        after_state: dict[str, Any] | None,
        url: str | None = None,
        label: str | None = None,
    ) -> None:
        """One ``oe_activity_log`` row saying the change came through the assistant.

        It lands in the same transaction as the domain write, so the project
        Timeline and /admin/audit-log show it next to the record's own rows.
        ``url`` (an in-app path) and ``label`` name the record, so the Timeline
        can link a row whose entity type has no route of its own.
        """
        from app.core.audit_log import log_activity

        edited = spec.edit_view(action.payload or {}) != spec.edit_view(action.original_payload or {})
        approved_by = ctx.user_id if audit_action != "reverted" else action.decided_by
        metadata: dict[str, Any] = {
            "via": "ai_assistant",
            "ai_action_id": str(action.id),
            "action_type": action.action_type,
            "requested_by": str(action.requested_by),
            "approved_by": str(approved_by) if approved_by else None,
            "confidence": action.confidence,
            "session_id": str(action.session_id) if action.session_id else None,
            "edited_by_human": edited,
        }
        if url and url.startswith("/") and not url.startswith("//"):
            metadata["url"] = url
        if label:
            metadata["label"] = label
        if audit_action == "reverted":
            metadata["reverted_by"] = str(ctx.user_id)
        await log_activity(
            self.session,
            actor_id=ctx.user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=audit_action,
            module="erp_chat",
            parent_entity_type="project" if action.project_id else None,
            parent_entity_id=action.project_id,
            before_state=before_state,
            after_state=after_state,
            metadata=metadata,
        )

    # ── DTO ───────────────────────────────────────────────────────────────

    async def to_dtos(self, actions: list[ChatAction], viewer: Viewer) -> list[ChatActionResponse]:
        """Render actions for ``viewer``; names and project names in one query each."""
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        user_ids = {
            uid
            for action in actions
            for uid in (action.requested_by, action.decided_by, action.reverted_by)
            if uid is not None
        }
        names: dict[uuid.UUID, str] = {}
        if user_ids:
            rows = await self.session.execute(
                select(User.id, User.full_name, User.email).where(User.id.in_(list(user_ids)))
            )
            names = {uid: (str(full or "").strip() or str(email or "")) for uid, full, email in rows.all()}
        project_ids = {a.project_id for a in actions if a.project_id is not None}
        project_names: dict[uuid.UUID, str] = {}
        if project_ids:
            rows = await self.session.execute(select(Project.id, Project.name).where(Project.id.in_(list(project_ids))))
            project_names = {pid: str(name or "") for pid, name in rows.all()}
        return [self._to_dto(a, viewer, names, project_names) for a in actions]

    def _to_dto(
        self,
        action: ChatAction,
        viewer: Viewer,
        names: dict[uuid.UUID, str],
        project_names: dict[uuid.UUID, str],
    ) -> ChatActionResponse:
        spec = get_spec(action.action_type)
        preview = action.preview or {}
        abilities = self.abilities(action, viewer)

        def person(uid: uuid.UUID | None) -> ActionUserRef | None:
            if uid is None:
                return None
            return ActionUserRef(id=uid, name=names.get(uid, ""))

        target = None
        if preview.get("target"):
            target = ActionEntityRef.model_validate(preview["target"])
        elif action.target_entity_id:
            target = ActionEntityRef(
                entity_type=action.target_entity_type or "",
                entity_id=action.target_entity_id,
            )
        result = None
        if action.applied_entity_id:
            stored = action.result or {}
            result = ActionEntityRef(
                entity_type=action.applied_entity_type or "",
                entity_id=action.applied_entity_id,
                label=stored.get("label"),
                url=stored.get("url"),
            )
        hint_key = spec.revert_hint_key(action) if spec is not None and action.status == "applied" else None
        hint_text = None
        if hint_key:
            hint_text = labels.REVERT_HINTS.get(hint_key.removeprefix(labels.REVERT_HINT_PREFIX))
        blocked_by = abilities.blocked_by
        blocked_key = f"{labels.BLOCKED_PREFIX}{blocked_by}" if blocked_by else None
        edited = (
            spec.edit_view(action.payload or {}) != spec.edit_view(action.original_payload or {})
            if spec is not None
            else (action.payload or {}) != (action.original_payload or {})
        )
        return ChatActionResponse(
            id=action.id,
            session_id=action.session_id,
            message_id=action.message_id,
            project_id=action.project_id,
            project_name=project_names.get(action.project_id) if action.project_id else None,
            action_type=action.action_type,
            status=action.status,  # type: ignore[arg-type]
            title=action.title or (spec.title if spec else action.action_type),
            title_key=labels.title_key(action.action_type),
            summary=action.summary,
            subtitle=preview.get("subtitle"),
            fields=[ActionField.model_validate(f) for f in preview.get("fields", [])],
            notes=[ActionNote.model_validate(n) for n in preview.get("notes", [])],
            payload=action.payload or {},
            original_payload=action.original_payload or {},
            edited=edited,
            confidence=action.confidence,
            rationale=action.rationale,
            target=target,
            result=result,
            requested_by=person(action.requested_by),
            decided_by=person(action.decided_by),
            decided_at=action.decided_at,
            reverted_by=person(action.reverted_by),
            reverted_at=action.reverted_at,
            decision_note=action.decision_note,
            revert_note=action.revert_note,
            error=action.error,
            error_code=action.error_code,
            can_apply=abilities.can_apply,
            can_edit=abilities.can_edit,
            can_reject=abilities.can_reject,
            can_revert=abilities.can_revert,
            blocked_reason_key=blocked_key,
            blocked_reason=labels.BLOCKED[blocked_by] if blocked_by else None,
            revert_hint_key=hint_key,
            revert_hint=hint_text,
            batch_id=action.batch_id,
            created_at=action.created_at,
            updated_at=action.updated_at,
        )


# ── What the chat stream calls ──────────────────────────────────────────────


async def propose_action(
    session: Any,
    *,
    tool_name: str,
    args: dict[str, Any],
    user_id: str | uuid.UUID,
    chat_session_id: str | uuid.UUID | None = None,
    project_id: str | uuid.UUID | None = None,
    batch_id: str | None = None,
    message_id: str | uuid.UUID | None = None,
    summary: str | None = None,
) -> ChatActionResponse:
    """Store a proposal for a ``propose_*`` tool call and return its DTO. Flushes, never commits.

    Raises:
        ActionError: The arguments do not make a valid change for this person.
    """
    service = ChatActionService(session)
    action = await service.propose(
        tool_name=tool_name,
        args=args,
        user_id=user_id,
        chat_session_id=chat_session_id,
        project_id=project_id,
        batch_id=batch_id,
        message_id=message_id,
        summary=summary,
    )
    viewer = await service.viewer(user_id)
    return (await service.to_dtos([action], viewer))[0]


def _describe_for_model(dto: ChatActionResponse) -> str:
    """What the model is told after proposing: the change, and that it is NOT saved."""

    def shown(f: ActionField, value: Any) -> Any:
        # A pick-list value (a member id) is told to the model by its label, as the person sees it.
        hit = next((o for o in f.options or [] if o.value == str(value)), None)
        return hit.label if hit is not None else value

    parts = []
    for f in dto.fields:
        if f.value in (None, ""):
            continue
        after = shown(f, f.value)
        value = f"{shown(f, f.before)} -> {after}" if f.before is not None else f"{after}"
        parts.append(f"{f.key}={value}")
    where = f" in {dto.subtitle}" if dto.subtitle else ""
    notes = " ".join(n.text for n in dto.notes)
    blocked = " The user cannot apply it themselves; someone with the right role must." if dto.blocked_reason else ""
    return (
        f"Proposed '{dto.title}'{where}: {', '.join(parts)}. NOT saved yet: it waits for the user to "
        f"review the card and click Apply (action {dto.id}). {notes}{blocked}"
    ).strip()


async def propose_tool_result(
    session: Any,
    *,
    tool_name: str,
    args: dict[str, Any],
    user_id: str | uuid.UUID,
    chat_session_id: str | uuid.UUID | None = None,
    project_id: str | uuid.UUID | None = None,
    batch_id: str | None = None,
    message_id: str | uuid.UUID | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """The tool result for a ``propose_*`` call, in the chat's renderer shape. Flushes, never commits.

    Success: ``{"renderer": "action_proposal", "data": <ChatActionResponse JSON>, "summary": ...}``.
    Refusal: ``{"renderer": "error", "data": {"error": code, "message", "field_errors"?, "options"?},
    "summary": ...}``, which the model reads to ask the person or fix its arguments. The proposal is
    written in a savepoint, so a refusal or a database error leaves the stream's transaction usable.
    """
    try:
        async with session.begin_nested():
            dto = await propose_action(
                session,
                tool_name=tool_name,
                args=args,
                user_id=user_id,
                chat_session_id=chat_session_id,
                project_id=project_id,
                batch_id=batch_id,
                message_id=message_id,
                summary=summary,
            )
    except ActionError as exc:
        return exc.to_tool_result()
    except HTTPException as exc:
        return error_from_http(exc).to_tool_result()
    except Exception:
        logger.exception("erp_chat: proposing %s failed", tool_name)
        return ActionConflictError(code="internal_error").to_tool_result()
    return {
        "renderer": "action_proposal",
        "data": dto.model_dump(mode="json"),
        "summary": _describe_for_model(dto),
    }
