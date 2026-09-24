# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``schedule.update_progress`` - the assistant proposes new progress for a schedule activity.

Mirrors ``PATCH /api/v1/schedule/activities/{id}/progress/``: permission
``schedule.update``, the activity must exist, and ``_verify_schedule_owner``
(``verify_project_access`` on the schedule's project) for the person applying;
then ``ScheduleService.update_progress``, which sets the status from the
progress (0 not started, 100 completed, in progress between), refuses to
complete an activity whose predecessors are still open, and rolls the progress
up into the summary activities above it. The route writes nothing else, so
neither does apply. The service takes no actor, so the assistant's
``oe_activity_log`` row is the record of who changed it.

The activity is given by id, or by its name or WBS code within the project's
schedules; a name that matches several activities is refused with the
candidates, so the model can ask which one. The progress the activity had when
the change was proposed is kept in ``before_state``; apply (and every edit of
the proposal) refuses with 409 ``target_changed`` when someone updated it in
between. Undo restores that progress, only while the activity still holds
what was applied, through the same service call; the status follows the
restored progress, so a status set by hand before is not brought back, and the
card says so when that is the case.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import select

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions._common import resolve_project
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionContext,
    ActionDraft,
    ActionNotFoundError,
    ActionSpec,
    ActionValidationError,
    AppliedResult,
    FieldErrors,
    coerce_uuid,
    decimal_str,
    make_field,
    make_note,
    parse_percent,
    parse_text,
    same_value,
    to_number,
)
from app.modules.erp_chat.schemas import ActionEntityRef

if TYPE_CHECKING:
    from app.modules.erp_chat.models import ChatAction

# The most candidates an ambiguous name returns to the model.
MAX_CANDIDATES = 10


@dataclass(frozen=True)
class ActivityRow:
    """The activity facts a proposal needs, with its schedule and project."""

    id: uuid.UUID
    schedule_id: uuid.UUID
    schedule_name: str
    project_id: uuid.UUID
    name: str
    wbs_code: str
    progress_pct: str
    status: str
    activity_type: str

    @property
    def label(self) -> str:
        """``WBS name`` as the Gantt shows it."""
        return f"{self.wbs_code} {self.name}".strip()

    def candidate(self) -> dict[str, Any]:
        """One option of an ambiguous name, for the model to ask about."""
        return {
            "activity_id": str(self.id),
            "name": self.name,
            "wbs_code": self.wbs_code,
            "schedule": self.schedule_name,
            "progress": to_number(self.progress_pct),
        }


def _select_activities() -> Any:
    from app.modules.schedule.models import Activity, Schedule

    return select(
        Activity.id,
        Activity.schedule_id,
        Schedule.name,
        Schedule.project_id,
        Activity.name,
        Activity.wbs_code,
        Activity.progress_pct,
        Activity.status,
        Activity.activity_type,
    ).join(Schedule, Schedule.id == Activity.schedule_id)


def _row(values: Any) -> ActivityRow:
    aid, sid, sname, pid, name, wbs, progress, status, kind = values
    return ActivityRow(
        id=aid,
        schedule_id=sid,
        schedule_name=str(sname or ""),
        project_id=pid,
        name=str(name or ""),
        wbs_code=str(wbs or ""),
        progress_pct=str(progress or "0"),
        status=str(status or ""),
        activity_type=str(kind or ""),
    )


async def get_activity(ctx: ActionContext, activity_id: uuid.UUID | None) -> ActivityRow | None:
    """One activity with its schedule and project, or None when it is not there."""
    from app.modules.schedule.models import Activity

    if activity_id is None:
        return None
    values = (await ctx.session.execute(_select_activities().where(Activity.id == activity_id))).one_or_none()
    return _row(values) if values is not None else None


async def search_activities(
    ctx: ActionContext,
    project_id: uuid.UUID,
    needle: str,
    *,
    schedule_id: uuid.UUID | None = None,
) -> list[ActivityRow]:
    """Activities of a project's schedules matching a name or WBS code (see :func:`match_activities`).

    Every schedule of the project is searched, not only the first one. The
    match is made here and not with ``ILIKE``: a database created with the C
    locale (the desktop build) does not fold the case of non-ASCII letters, so
    "фундамент" would never find "Фундамент" there.
    """
    from app.modules.schedule.models import Activity, Schedule

    if not needle.strip():
        return []
    stmt = _select_activities().where(Schedule.project_id == project_id)
    if schedule_id is not None:
        stmt = stmt.where(Activity.schedule_id == schedule_id)
    stmt = stmt.order_by(Schedule.name, Activity.sort_order, Activity.name)
    rows = [_row(values) for values in (await ctx.session.execute(stmt)).all()]
    return match_activities(needle, rows)


def match_activities(needle: str, rows: list[ActivityRow]) -> list[ActivityRow]:
    """The rows matching a typed name or WBS code, exact matches first.

    Exact: the whole name or the WBS code, ignoring case in any script. Only
    when nothing matches exactly: every activity whose name contains the typed
    text.
    """
    typed = needle.strip().casefold()
    if not typed:
        return []
    exact = [r for r in rows if typed in {r.name.strip().casefold(), r.wbs_code.strip().casefold()}]
    return exact or [r for r in rows if typed in r.name.casefold()]


def derived_status(progress: Any) -> str:
    """The status ``ScheduleService.update_progress`` gives an activity at ``progress``."""
    number = Decimal(str(progress or "0"))
    if number >= 100:
        return "completed"
    if number > 0:
        return "in_progress"
    return "not_started"


def schedule_url(project_id: Any) -> str:
    """The project's schedules (the Gantt of the activity)."""
    return f"/schedule?project_id={project_id}"


class ScheduleUpdateProgressSpec(ActionSpec):
    """Propose new progress for an activity of a project's schedule."""

    action_type: ClassVar[str] = "schedule.update_progress"
    tool_name: ClassVar[str] = "propose_update_schedule_progress"
    tool_description: ClassVar[str] = (
        "Propose new progress for an activity of the project schedule, for example 'foundations are 60 % done'. "
        "Identify the activity by activity_id (from get_schedule) or by its name or WBS code as the user said "
        "it; when several activities match, the result lists them and you ask the user which one. Give "
        "progress in percent from 0 to 100. Nothing is saved: the user sees the old and new progress on a card "
        "and applies, edits or rejects it. The status follows the progress (100 means completed)."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID. Omit to use the project open in the app."},
        "activity_id": {"type": "string", "description": "UUID of the activity, when you have it."},
        "activity": {
            "type": "string",
            "maxLength": 255,
            "description": "Name or WBS code of the activity, when you do not have its id.",
        },
        "schedule_id": {"type": "string", "description": "UUID of the schedule, to narrow a name search."},
        "progress": {"type": "number", "minimum": 0, "maximum": 100, "description": "New progress in percent."},
    }
    required_args: ClassVar[tuple[str, ...]] = ("progress",)
    entity_type: ClassVar[str] = "activity"
    apply_permissions: ClassVar[tuple[str, ...]] = ("schedule.update",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("schedule.update",)
    reversible: ClassVar[bool] = True
    modules: ClassVar[tuple[str, ...]] = ("oe_schedule",)

    async def _resolve(self, ctx: ActionContext, args: dict[str, Any], errors: FieldErrors) -> ActivityRow:
        raw_id = args.get("activity_id")
        if raw_id not in (None, ""):
            activity = await get_activity(ctx, coerce_uuid(raw_id))
            if activity is None:
                raise ActionValidationError(code="activity_not_found")
            try:
                await ctx.require_project_access(activity.project_id)
            except ActionNotFoundError as exc:
                raise ActionNotFoundError(code="activity_not_found") from exc
            return activity
        needle = parse_text(args, "activity", errors, required=True, max_length=255)
        errors.raise_if_any()
        project = await resolve_project(ctx, args)
        schedule_id = coerce_uuid(args.get("schedule_id"))
        hits = await search_activities(ctx, project.id, needle or "", schedule_id=schedule_id)
        if not hits:
            raise ActionValidationError(code="activity_not_found", params={"activity": needle})
        if len(hits) > 1:
            raise ActionValidationError(
                code="activity_ambiguous",
                params={"activity": needle},
                options=[hit.candidate() for hit in hits[:MAX_CANDIDATES]],
            )
        return hits[0]

    async def build(
        self,
        ctx: ActionContext,
        args: dict[str, Any],
        *,
        prior: ChatAction | None = None,
    ) -> ActionDraft:
        errors = FieldErrors()
        progress = parse_percent(args, "progress", errors, required=True)
        activity = await self._resolve(ctx, args, errors)
        errors.raise_if_any()

        if prior is not None and prior.before_state:
            before = dict(prior.before_state)
            if not same_value(activity.progress_pct, before.get("progress_pct")):
                raise ActionConflictError(code="target_changed", params={"fields": ["progress"]})
        else:
            before = {
                "progress_pct": decimal_str(activity.progress_pct),
                "status": activity.status,
                "name": activity.name,
                "wbs_code": activity.wbs_code,
                "schedule_id": str(activity.schedule_id),
                "activity_type": activity.activity_type,
            }
        if same_value(progress, before.get("progress_pct")):
            raise ActionValidationError(code="no_change")

        notes = []
        if activity.activity_type == "summary":
            notes.append(make_note("summary_activity", field_key="progress", tone="warning"))
        payload = {
            "project_id": str(activity.project_id),
            "schedule_id": str(activity.schedule_id),
            "activity_id": str(activity.id),
            "progress": decimal_str(progress),
        }
        fields = [
            make_field(
                "progress",
                "percent",
                to_number(progress),
                before=to_number(before.get("progress_pct")),
                editable=True,
                required=True,
            ),
        ]
        return ActionDraft(
            payload=payload,
            fields=fields,
            project_id=activity.project_id,
            subtitle=activity.schedule_name,
            target=ActionEntityRef(
                entity_type=self.entity_type,
                entity_id=str(activity.id),
                label=activity.label,
                url=schedule_url(activity.project_id),
            ),
            before_state=before,
            notes=notes,
        )

    async def _gate_activity(self, ctx: ActionContext, activity_id: uuid.UUID | None) -> ActivityRow:
        activity = await get_activity(ctx, activity_id)
        if activity is None:
            raise ActionNotFoundError(code="activity_not_found")
        await ctx.require_project_access(activity.project_id)
        return activity

    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        ctx.require_permissions(self.apply_permissions)
        await self._gate_activity(ctx, coerce_uuid(payload.get("activity_id")))

    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        from app.modules.schedule.service import ScheduleService

        activity_id = uuid.UUID(draft.payload["activity_id"])
        updated = await ScheduleService(ctx.session).update_progress(
            activity_id, float(Decimal(draft.payload["progress"]))
        )
        before = draft.before_state or {}
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(activity_id),
            label=f"{updated.wbs_code or ''} {updated.name}".strip(),
            url=schedule_url(draft.payload["project_id"]),
            after_state={"progress_pct": decimal_str(updated.progress_pct), "status": updated.status},
            audit_action="updated",
            before_state={"progress_pct": before.get("progress_pct"), "status": before.get("status")},
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        ctx.require_permissions(self.revert_permissions)
        activity = await get_activity(ctx, coerce_uuid(action.applied_entity_id))
        if activity is None:
            raise ActionConflictError(code="target_missing")
        await ctx.require_project_access(activity.project_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        from app.modules.schedule.service import ScheduleService

        activity = await get_activity(ctx, coerce_uuid(action.applied_entity_id))
        if activity is None:
            raise ActionConflictError(code="target_missing")
        applied_state = (action.result or {}).get("after_state") or {}
        if not same_value(activity.progress_pct, applied_state.get("progress_pct")):
            raise ActionConflictError(code="changed_since_apply")
        previous = (action.before_state or {}).get("progress_pct") or "0"
        restored = await ScheduleService(ctx.session).update_progress(activity.id, float(Decimal(str(previous))))
        return {"progress_pct": decimal_str(restored.progress_pct), "status": restored.status}

    def revert_hint_key(self, action: ChatAction) -> str | None:
        before = action.before_state or {}
        if before.get("status") and before.get("status") != derived_status(before.get("progress_pct")):
            return f"{labels.REVERT_HINT_PREFIX}schedule_status"
        return None
