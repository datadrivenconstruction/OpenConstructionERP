# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress round-trip through a spreadsheet.

Export writes the activities in scope (filtered by WBS, responsible person and
a date window) to a locked progress sheet. Preview reads an upload back,
matches every row to its activity, shows the change per field and runs the
``schedule_progress_sheet`` validation rules. Apply re-reads the same file
(checked by its digest), and for every confirmed row records an approved
progress update (the audit trail: actual dates, remaining duration, notes,
the file and the row it came from), sets progress through the per-type
progress engine at the status date, and advances the schedule's status date,
which snapshots EVM. Nothing is applied that the preview did not show.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.i18n import t
from app.core.validation.engine import validation_engine
from app.modules.schedule.models import Activity, ProgressUpdate
from app.modules.schedule.profile_service import load_recorded_actuals
from app.modules.schedule.progress_schemas import TypedProgressRequest
from app.modules.schedule.progress_service import ScheduleProgressService
from app.modules.schedule.progress_sheet import (
    COLUMNS,
    ExportRow,
    ParsedRow,
    SheetFormatError,
    build_workbook,
    parse_workbook,
    progress_stamp,
)
from app.modules.schedule.schemas import ScheduleUpdate
from app.modules.schedule.service import ScheduleService, _str_to_float
from app.modules.schedule.validators import PROGRESS_SHEET_RULE_SET

logger = logging.getLogger(__name__)

#: Activity types whose progress rolls up from children and is never typed in.
_ROLLUP_TYPES = frozenset({"summary", "wbs", "hammock", "level_of_effort"})


@dataclass
class SheetFilters:
    """Which activities go into an exported sheet."""

    wbs_prefix: str | None = None
    assignee_id: uuid.UUID | None = None
    date_from: str | None = None
    date_to: str | None = None
    include_completed: bool = False


def _bad_request(code: str, message: str, http: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message})


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _num(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


class ProgressSheetService:
    """Export, preview and apply of the progress sheet."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base = ScheduleService(session)

    async def _activities(self, schedule_id: uuid.UUID) -> list[Activity]:
        activities, _ = await self.base.list_activities_for_schedule(schedule_id, limit=10_000)
        return activities

    @staticmethod
    def _in_scope(act: Activity, filters: SheetFilters) -> bool:
        if (act.activity_type or "task") in _ROLLUP_TYPES:
            return False
        if not filters.include_completed and (act.status == "completed" or _str_to_float(act.progress_pct) >= 100):
            return False
        if filters.wbs_prefix and not (act.wbs_code or "").startswith(filters.wbs_prefix):
            return False
        if filters.assignee_id and act.assignee_id != filters.assignee_id:
            return False
        if filters.date_to and act.start_date and act.start_date[:10] > filters.date_to:
            return False
        return not (filters.date_from and act.end_date and act.end_date[:10] < filters.date_from)

    @staticmethod
    def _stamp(act: Activity, actuals: tuple[date | None, date | None]) -> str:
        start, finish = actuals
        return progress_stamp(
            start_date=act.start_date,
            end_date=act.end_date,
            progress_pct=_str_to_float(act.progress_pct),
            remaining_duration=act.remaining_duration,
            status=act.status,
            actual_start=start.isoformat() if start else None,
            actual_finish=finish.isoformat() if finish else None,
        )

    # ── Export ────────────────────────────────────────────────────────────

    async def export(
        self,
        schedule_id: uuid.UUID,
        filters: SheetFilters,
        *,
        locale: str | None,
        user_id: str,
    ) -> tuple[bytes, str, int]:
        """Build the sheet; returns ``(xlsx bytes, filename, row count)``."""
        schedule = await self.base.get_schedule(schedule_id)
        activities = [a for a in await self._activities(schedule_id) if self._in_scope(a, filters)]
        actuals = await load_recorded_actuals(self.session, [a.id for a in activities])
        names = await self.base.resolve_assignee_names({a.assignee_id for a in activities if a.assignee_id})
        rows: list[ExportRow] = []
        for act in activities:
            recorded = actuals.get(str(act.id), (None, None))
            rows.append(
                ExportRow(
                    row_key=str(act.id),
                    activity_ref=act.activity_code or act.wbs_code or str(act.id)[:8],
                    name=act.name or "",
                    wbs_code=act.wbs_code or "",
                    responsible=names.get(act.assignee_id, "") if act.assignee_id else "",
                    planned_start=act.start_date,
                    planned_finish=act.end_date,
                    percent_complete=round(_str_to_float(act.progress_pct), 2),
                    actual_start=recorded[0].isoformat() if recorded[0] else None,
                    actual_finish=recorded[1].isoformat() if recorded[1] else None,
                    remaining_duration=act.remaining_duration,
                    stamp=self._stamp(act, recorded),
                )
            )
        exported_at = datetime.now(UTC)
        headers = {key: t(f"schedule.progress_sheet.col.{key}", locale=locale) for key, _w, _e in COLUMNS}
        data = build_workbook(
            rows,
            headers=headers,
            sheet_title=t("schedule.progress_sheet.sheet_title", locale=locale),
            title=t("schedule.progress_sheet.title", locale=locale),
            details=[
                t("schedule.progress_sheet.detail_schedule", locale=locale, name=schedule.name),
                t("schedule.progress_sheet.detail_exported", locale=locale, date=exported_at.date().isoformat()),
            ],
            instructions=t("schedule.progress_sheet.instructions", locale=locale),
            meta={
                "schedule_id": str(schedule_id),
                "project_id": str(schedule.project_id),
                "exported_at": exported_at.isoformat(),
                "exported_by": str(user_id) if user_id else None,
                "data_date": schedule.data_date,
                "locale": locale,
                "filters": {
                    "wbs_prefix": filters.wbs_prefix,
                    "assignee_id": str(filters.assignee_id) if filters.assignee_id else None,
                    "date_from": filters.date_from,
                    "date_to": filters.date_to,
                    "include_completed": filters.include_completed,
                },
            },
        )
        await log_activity(
            self.session,
            actor_id=user_id,
            entity_type="schedule",
            entity_id=schedule_id,
            action="progress_sheet_exported",
            module="oe_schedule",
            metadata={"rows": len(rows), "exported_at": exported_at.isoformat()},
        )
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (schedule.name or "schedule"))[:40]
        return data, f"progress_{safe}_{exported_at.date().isoformat()}.xlsx", len(rows)

    # ── Preview ───────────────────────────────────────────────────────────

    def _parse(self, schedule_id: uuid.UUID, data: bytes) -> Any:
        try:
            sheet = parse_workbook(data)
        except SheetFormatError as exc:
            raise _bad_request(exc.code, str(exc)) from exc
        if str(sheet.meta.get("schedule_id")) != str(schedule_id):
            raise _bad_request(
                "sheet_for_another_schedule", "The sheet was exported from another schedule", status.HTTP_409_CONFLICT
            )
        return sheet

    async def preview(
        self,
        schedule_id: uuid.UUID,
        data: bytes,
        filename: str,
        *,
        status_date: str | None,
        locale: str | None,
    ) -> dict[str, Any]:
        """Match, diff and validate every row; writes nothing."""
        sheet = self._parse(schedule_id, data)
        activities = await self._activities(schedule_id)
        by_id = {str(a.id): a for a in activities}
        by_ref: dict[str, Activity] = {}
        for a in activities:
            if a.activity_code:
                by_ref.setdefault(a.activity_code, a)
        actuals = await load_recorded_actuals(self.session, [a.id for a in activities])
        when = status_date or date.today().isoformat()

        payload_rows: list[dict[str, Any]] = []
        out_rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in sheet.rows:
            act = by_id.get(row.row_key or "") or (by_ref.get(row.activity_ref) if row.activity_ref else None)
            recorded = actuals.get(str(act.id), (None, None)) if act else (None, None)
            current_pct = _str_to_float(act.progress_pct) if act else None
            duplicate = bool(act and str(act.id) in seen)
            if act:
                seen.add(str(act.id))
            stale = bool(act and row.stamp and row.stamp != self._stamp(act, recorded))
            changes = self._changes(row, act, recorded, current_pct) if act else {}
            payload_rows.append(
                {
                    "row_number": row.row_number,
                    "row_key": row.row_key,
                    "activity_ref": row.activity_ref,
                    "name": row.name,
                    "activity_id": str(act.id) if act else None,
                    "duplicate": duplicate,
                    "parse_errors": list(row.errors),
                    "percent_complete": row.percent_complete,
                    "remaining_duration": row.remaining_duration,
                    "actual_start": row.actual_start,
                    "actual_finish": row.actual_finish,
                    "recorded_actual_start": recorded[0].isoformat() if recorded[0] else None,
                    "recorded_actual_finish": recorded[1].isoformat() if recorded[1] else None,
                    "current_percent": current_pct,
                    "stale": stale,
                    "status_date": when,
                    "_changed": bool(changes),
                }
            )
            out_rows.append(
                {
                    "row_number": row.row_number,
                    "activity_id": act.id if act else None,
                    "activity_code": act.activity_code if act else row.activity_ref,
                    "name": act.name if act else row.name,
                    "changes": changes,
                    "issues": [],
                    "stale": stale,
                }
            )

        report = await validation_engine.validate(
            data={"rows": payload_rows},
            rule_sets=[PROGRESS_SHEET_RULE_SET],
            target_type="schedule_progress_sheet",
            target_id=str(schedule_id),
            metadata={"locale": locale} if locale else None,
        )
        by_row = {r["row_number"]: r for r in out_rows}
        for result in report.results:
            if result.passed or result.is_engine_error:
                continue
            target = (
                by_row.get(int(result.element_ref)) if result.element_ref and result.element_ref.isdigit() else None
            )
            if target is None:
                continue
            target["issues"].append(
                {
                    "rule_id": result.rule_id,
                    "code": str(result.details.get("code") or "fail"),
                    "severity": str(result.severity.value if hasattr(result.severity, "value") else result.severity),
                    "message": result.message,
                }
            )
        for out, payload in zip(out_rows, payload_rows, strict=True):
            out["has_errors"] = any(i["severity"] == "error" for i in out["issues"])
            out["applicable"] = payload["_changed"] and not out["has_errors"]

        return {
            "schedule_id": schedule_id,
            "filename": filename,
            "sha256": sheet.sha256,
            "exported_at": sheet.meta.get("exported_at"),
            "exported_data_date": sheet.meta.get("data_date"),
            "status_date": when,
            "row_count": len(out_rows),
            "changed_count": sum(1 for p in payload_rows if p["_changed"]),
            "error_count": sum(1 for r in out_rows if r["has_errors"]),
            "stale_count": sum(1 for r in out_rows if r["stale"]),
            "rows": out_rows,
        }

    @staticmethod
    def _changes(
        row: ParsedRow, act: Activity, recorded: tuple[date | None, date | None], current_pct: float | None
    ) -> dict[str, dict[str, Any]]:
        """Fields whose sheet value differs from the app; a blank cell changes nothing."""
        changes: dict[str, dict[str, Any]] = {}
        if row.percent_complete is not None and _num(row.percent_complete) != _num(current_pct):
            changes["percent_complete"] = {"old": _num(current_pct), "new": _num(row.percent_complete)}
        old_start = recorded[0].isoformat() if recorded[0] else None
        if row.actual_start and row.actual_start != old_start:
            changes["actual_start"] = {"old": old_start, "new": row.actual_start}
        old_finish = recorded[1].isoformat() if recorded[1] else None
        if row.actual_finish and row.actual_finish != old_finish:
            changes["actual_finish"] = {"old": old_finish, "new": row.actual_finish}
        if row.remaining_duration is not None and row.remaining_duration != act.remaining_duration:
            changes["remaining_duration"] = {"old": act.remaining_duration, "new": row.remaining_duration}
        if row.notes:
            changes["notes"] = {"old": None, "new": row.notes[:2000]}
        return changes

    # ── Apply ─────────────────────────────────────────────────────────────

    async def apply(
        self,
        schedule_id: uuid.UUID,
        data: bytes,
        filename: str,
        *,
        expected_sha256: str,
        status_date: str,
        row_numbers: list[int],
        user_id: str,
        locale: str | None,
    ) -> dict[str, Any]:
        """Apply the confirmed rows of a previewed sheet."""
        try:
            date.fromisoformat(status_date)
        except ValueError as exc:
            raise _bad_request("invalid_status_date", "The status date is not a date") from exc
        preview = await self.preview(schedule_id, data, filename, status_date=status_date, locale=locale)
        if preview["sha256"] != expected_sha256.strip().lower():
            raise _bad_request(
                "preview_mismatch", "The uploaded file is not the one that was previewed", status.HTTP_409_CONFLICT
            )
        schedule = await self.base.get_schedule(schedule_id)
        project_id = schedule.project_id
        previous_data_date = schedule.data_date
        sheet = parse_workbook(data)
        parsed_by_row = {r.row_number: r for r in sheet.rows}
        wanted = set(row_numbers)
        batch_id = str(uuid.uuid4())
        progress = ScheduleProgressService(self.session)
        applied: list[uuid.UUID] = []
        skipped: list[dict[str, Any]] = []

        for row in preview["rows"]:
            number = row["row_number"]
            if number not in wanted:
                continue
            activity_id = row["activity_id"]
            if not row["applicable"]:
                code = "has_errors" if row["has_errors"] else "no_changes"
                skipped.append({"row_number": number, "activity_id": activity_id, "code": code})
                continue
            parsed = parsed_by_row[number]
            changes = row["changes"]
            actual_finish = parsed.actual_finish
            new_pct = parsed.percent_complete
            if new_pct is not None and new_pct >= 100.0 and not actual_finish:
                actual_finish = status_date
            if "percent_complete" in changes or "remaining_duration" in changes:
                try:
                    await progress.set_typed_progress(
                        activity_id,
                        TypedProgressRequest(
                            percent=new_pct if "percent_complete" in changes else None,
                            remaining_duration=parsed.remaining_duration if "remaining_duration" in changes else None,
                            data_date=status_date,
                        ),
                        actor_id=user_id,
                    )
                except HTTPException as exc:
                    if exc.status_code != status.HTTP_409_CONFLICT:
                        raise
                    skipped.append(
                        {"row_number": number, "activity_id": activity_id, "code": "open_predecessor_blocks_completion"}
                    )
                    continue
            self.session.add(
                ProgressUpdate(
                    project_id=project_id,
                    activity_id=activity_id,
                    update_date=status_date,
                    progress_pct=str(new_pct) if new_pct is not None else None,
                    actual_start=parsed.actual_start,
                    actual_finish=actual_finish,
                    remaining_duration=str(parsed.remaining_duration)
                    if parsed.remaining_duration is not None
                    else None,
                    notes=parsed.notes,
                    status="approved",
                    submitted_by=_uuid_or_none(user_id),
                    approved_by=_uuid_or_none(user_id),
                    metadata_={
                        "source": "progress_sheet",
                        "batch_id": batch_id,
                        "filename": filename,
                        "sha256": preview["sha256"],
                        "row_number": number,
                        "stale_confirmed": bool(row["stale"]),
                        "changes": changes,
                    },
                )
            )
            applied.append(activity_id)
        await self.session.flush()

        parents = {a.parent_id for a in await self._activities(schedule_id) if a.id in set(applied) and a.parent_id}
        for parent_id in parents:
            await self.base._rollup_summary_progress(parent_id)

        advanced = bool(applied) and (not previous_data_date or status_date > str(previous_data_date)[:10])
        if advanced:
            await self.base.update_schedule(schedule_id, ScheduleUpdate(data_date=status_date))
        await log_activity(
            self.session,
            actor_id=user_id,
            entity_type="schedule",
            entity_id=schedule_id,
            action="progress_sheet_applied",
            module="oe_schedule",
            metadata={
                "batch_id": batch_id,
                "filename": filename,
                "sha256": preview["sha256"],
                "status_date": status_date,
                "applied": len(applied),
                "skipped": len(skipped),
                "stale_applied": sum(1 for r in preview["rows"] if r["stale"] and r["activity_id"] in set(applied)),
            },
        )
        logger.info("Progress sheet %s applied to schedule %s: %d rows", batch_id, schedule_id, len(applied))
        return {
            "schedule_id": schedule_id,
            "batch_id": batch_id,
            "status_date": status_date,
            "applied_count": len(applied),
            "applied_activity_ids": applied,
            "skipped": skipped,
            "data_date_advanced": advanced,
        }
