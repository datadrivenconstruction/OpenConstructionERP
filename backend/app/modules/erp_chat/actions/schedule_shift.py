# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``schedule.shift_activity`` - the assistant proposes new dates for a schedule activity.

The spoken form is "move the slab pour by two days" or "start the facade on
3 March": a signed number of days, or a new start, and the activity keeps its
length. A person may also edit the start and the finish on the card directly.

Mirrors ``PATCH /api/v1/schedule/activities/{id}``: permission
``schedule.update``, ``verify_project_access`` on the schedule's project, then
``ScheduleService.update_activity`` with only the two dates, which validates
the range (``ActivityUpdate``) and recalculates the duration exactly as the
Gantt edit does. Activities linked to it are not moved; the card says so.

The dates the activity had when the change was proposed are kept in
``before_state``; apply and every edit refuse with 409 ``target_changed`` when
someone moved it in between. Undo restores those dates, only while the
activity still holds what was applied.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions import schedule_progress as activities
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
    make_field,
    make_note,
    parse_date,
    parse_decimal,
)
from app.modules.erp_chat.schemas import ActionEntityRef

if TYPE_CHECKING:
    from app.modules.erp_chat.models import ChatAction

# A shift beyond five years is a misheard number, not a plan.
MAX_SHIFT_DAYS = 5 * 366


def _iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def shifted_dates(start: str, end: str, *, days: int | None = None, new_start: str | None = None) -> tuple[str, str]:
    """Move ``start``..``end`` by ``days`` or to ``new_start``, keeping the length in calendar days."""
    s, e = _iso(start), _iso(end)
    if s is None or e is None:
        raise ActionValidationError(code="activity_no_dates")
    if new_start is not None:
        target = date.fromisoformat(new_start)
        delta = target - s
    else:
        delta = timedelta(days=days or 0)
    return (s + delta).isoformat(), (e + delta).isoformat()


class ScheduleShiftActivitySpec(ActionSpec):
    """Propose moving an activity of a project's schedule to new dates."""

    action_type: ClassVar[str] = "schedule.shift_activity"
    tool_name: ClassVar[str] = "propose_shift_schedule_activity"
    tool_description: ClassVar[str] = (
        "Propose moving an activity of the project schedule, for example 'move the slab pour by two days' or "
        "'start the facade on 2027-03-03'. Identify the activity by activity_id (from get_schedule) or by its name "
        "or WBS code as the user said it; when several match, the result lists them and you ask which one. Give "
        "shift_days (positive later, negative earlier) or new_start (YYYY-MM-DD); the activity keeps its length. "
        "Nothing is saved: the user sees the old and new dates on a card and applies, edits or rejects it."
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
        "shift_days": {
            "type": "integer",
            "minimum": -MAX_SHIFT_DAYS,
            "maximum": MAX_SHIFT_DAYS,
            "description": "Calendar days to move the activity by; negative moves it earlier.",
        },
        "new_start": {"type": "string", "description": "New start date as YYYY-MM-DD, instead of shift_days."},
    }
    entity_type: ClassVar[str] = "activity"
    apply_permissions: ClassVar[tuple[str, ...]] = ("schedule.update",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("schedule.update",)
    reversible: ClassVar[bool] = True
    modules: ClassVar[tuple[str, ...]] = ("oe_schedule",)

    def _target_dates(
        self, args: dict[str, Any], start: str, end: str, errors: FieldErrors
    ) -> tuple[str | None, str | None]:
        """New start and finish: typed on the card, or worked out from a shift or a new start."""
        explicit_start = parse_date(args, "start_date", errors)
        explicit_end = parse_date(args, "end_date", errors)
        if explicit_start or explicit_end:
            return explicit_start or start, explicit_end or end
        new_start = parse_date(args, "new_start", errors)
        days = parse_decimal(args, "shift_days", errors, allow_negative=True)
        if days is not None and days != days.to_integral_value():
            errors.add("shift_days", "not_whole_number")
            return None, None
        if days is not None and abs(days) > MAX_SHIFT_DAYS:
            errors.add("shift_days", "shift_range")
            return None, None
        if new_start is None and days is None:
            if "new_start" not in errors.errors and "shift_days" not in errors.errors:
                errors.add("shift_days", "shift_required")
            return None, None
        if errors:
            return None, None
        return shifted_dates(start, end, days=int(days) if days is not None else None, new_start=new_start)

    async def build(
        self,
        ctx: ActionContext,
        args: dict[str, Any],
        *,
        prior: ChatAction | None = None,
    ) -> ActionDraft:
        errors = FieldErrors()
        activity = await activities.resolve_activity(ctx, args, errors)
        if not activity.start_date or not activity.end_date:
            raise ActionValidationError(code="activity_no_dates")

        if prior is not None and prior.before_state:
            before = dict(prior.before_state)
            if activity.start_date != before.get("start_date") or activity.end_date != before.get("end_date"):
                raise ActionConflictError(code="target_changed", params={"fields": ["start_date", "end_date"]})
        else:
            before = {
                "start_date": activity.start_date,
                "end_date": activity.end_date,
                "name": activity.name,
                "wbs_code": activity.wbs_code,
                "schedule_id": str(activity.schedule_id),
            }

        new_start, new_end = self._target_dates(args, before["start_date"], before["end_date"], errors)
        errors.raise_if_any()
        if new_start is None or new_end is None:
            raise ActionValidationError(code="validation_error")
        if new_end < new_start:
            errors.add("end_date", "end_before_start")
            errors.raise_if_any()
        if new_start == before["start_date"] and new_end == before["end_date"]:
            raise ActionValidationError(code="no_change")

        notes = [make_note("successors_not_moved")]
        progress = Decimal(str(activity.progress_pct or "0"))
        if progress > 0:
            notes.insert(
                0, make_note("activity_started", params={"progress": str(progress.normalize())}, tone="warning")
            )
        if activity.activity_type == "summary":
            notes.insert(0, make_note("summary_dates", tone="warning"))
        payload = {
            "project_id": str(activity.project_id),
            "schedule_id": str(activity.schedule_id),
            "activity_id": str(activity.id),
            "start_date": new_start,
            "end_date": new_end,
        }
        fields = [
            make_field("start_date", "date", new_start, before=before["start_date"], editable=True, required=True),
            make_field("end_date", "date", new_end, before=before["end_date"], editable=True, required=True),
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
                url=activities.schedule_url(activity.project_id),
            ),
            before_state=before,
            notes=notes,
        )

    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        ctx.require_permissions(self.apply_permissions)
        activity = await activities.get_activity(ctx, coerce_uuid(payload.get("activity_id")))
        if activity is None:
            raise ActionNotFoundError(code="activity_not_found")
        await ctx.require_project_access(activity.project_id)

    async def _write_dates(self, ctx: ActionContext, activity_id: uuid.UUID, start: str, end: str) -> Any:
        from pydantic import ValidationError

        from app.modules.schedule.schemas import ActivityUpdate
        from app.modules.schedule.service import ScheduleService

        try:
            update = ActivityUpdate(start_date=start, end_date=end)
        except ValidationError as exc:
            errors = FieldErrors()
            errors.add("end_date", "end_before_start")
            raise errors_to_validation(errors) from exc
        return await ScheduleService(ctx.session).update_activity(activity_id, update, actor_id=str(ctx.user_id))

    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        activity_id = uuid.UUID(draft.payload["activity_id"])
        updated = await self._write_dates(ctx, activity_id, draft.payload["start_date"], draft.payload["end_date"])
        before = draft.before_state or {}
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(activity_id),
            label=f"{updated.wbs_code or ''} {updated.name}".strip(),
            url=activities.schedule_url(draft.payload["project_id"]),
            after_state={
                "start_date": str(updated.start_date or "")[:10],
                "end_date": str(updated.end_date or "")[:10],
            },
            audit_action="updated",
            before_state={"start_date": before.get("start_date"), "end_date": before.get("end_date")},
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        ctx.require_permissions(self.revert_permissions)
        activity = await activities.get_activity(ctx, coerce_uuid(action.applied_entity_id))
        if activity is None:
            raise ActionConflictError(code="target_missing")
        await ctx.require_project_access(activity.project_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        activity = await activities.get_activity(ctx, coerce_uuid(action.applied_entity_id))
        if activity is None:
            raise ActionConflictError(code="target_missing")
        applied = (action.result or {}).get("after_state") or {}
        if activity.start_date != applied.get("start_date") or activity.end_date != applied.get("end_date"):
            raise ActionConflictError(code="changed_since_apply")
        before = action.before_state or {}
        restored = await self._write_dates(ctx, activity.id, str(before["start_date"]), str(before["end_date"]))
        return {"start_date": str(restored.start_date or "")[:10], "end_date": str(restored.end_date or "")[:10]}

    def revert_hint_key(self, action: ChatAction) -> str | None:
        return f"{labels.REVERT_HINT_PREFIX}schedule_dates"


def errors_to_validation(errors: FieldErrors) -> ActionValidationError:
    """The 422 a set of field errors raises, as an exception object."""
    try:
        errors.raise_if_any()
    except ActionValidationError as exc:
        return exc
    return ActionValidationError(code="validation_error")
