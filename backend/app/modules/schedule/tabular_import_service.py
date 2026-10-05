# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Spreadsheet schedule import: preview, commit and the downloadable template.

The parsing lives in the pure :mod:`app.modules.schedule.tabular_import`; this
service adds what needs the database:

* the target project's working week (the same region resolution and calendar
  ``compute_duration`` counts on), handed to the parser so a Sunday-to-Thursday
  project reads its own durations;
* the duplicate check: every import stamps the file's SHA-256 on the schedule's
  ``metadata["import"]``, and a second commit of the same bytes into the same
  project is refused unless the person says it is wanted;
* the commit itself, through ``ScheduleInterchangeService`` so a spreadsheet
  lands exactly like a neutral interchange document: one transaction, then CPM,
  then the ``schedule_quality`` validation pack with every finding mapped back
  to the sheet row it came from.

Replacing an existing schedule is allowed only while nothing depends on its
current contents: it must be a draft, with no baseline, no recorded progress and
no work orders. Each refusal carries its own ``detail.code``.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import verify_project_access
from app.modules.schedule.interchange_service import ScheduleInterchangeService
from app.modules.schedule.models import (
    Activity,
    Schedule,
    ScheduleBaseline,
    ScheduleProgressEntry,
    WorkOrder,
)
from app.modules.schedule.schedule_interchange import parse_document
from app.modules.schedule.tabular_headers import (
    FIELDS,
    LANGUAGES,
    TEMPLATE_EXAMPLE_NAMES,
    TEMPLATE_HEADERS,
    TEMPLATE_YES_NO,
)
from app.modules.schedule.tabular_import import DateOrder, TabularPreview, preview

logger = logging.getLogger(__name__)

#: Years of a calendar's holidays handed to the parser, around today.
_HOLIDAY_YEARS_BACK = 5
_HOLIDAY_YEARS_AHEAD = 10
#: Languages whose spreadsheets use the decimal comma, so a CSV template is
#: written with ``;`` the way their Excel reads it.
_SEMICOLON_LANGUAGES = frozenset({"de", "es", "fr", "ru", "pt", "it", "nl", "pl", "tr"})

ImportTarget = Literal["new", "replace"]


@dataclass
class ProjectWeek:
    """The working week a project's durations are counted on."""

    region: str | None
    weekdays: frozenset[int]
    holidays: frozenset[date]


@dataclass
class CommitResult:
    """What a commit wrote and what the checks after it found."""

    schedule_id: uuid.UUID
    schedule_name: str
    replaced: bool
    activity_count: int
    relationship_count: int
    critical_count: int
    project_duration: int
    validation: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _conflict(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message, **extra})


class ScheduleTabularImportService:
    """Preview and commit spreadsheet schedules for one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.interchange = ScheduleInterchangeService(session)

    # ── Project context ──────────────────────────────────────────────────

    async def project_week(self, project_id: uuid.UUID) -> ProjectWeek:
        """The project's working weekdays and calendar holidays, as ``compute_duration`` reads them."""
        from app.modules.schedule.service import ScheduleService, get_work_calendar

        region = await ScheduleService(self.session).resolve_project_region(project_id)
        calendar = get_work_calendar(region)
        holidays: set[date] = set()
        holiday_func = calendar.get("holidays")
        if holiday_func is not None:
            this_year = date.today().year
            for year in range(this_year - _HOLIDAY_YEARS_BACK, this_year + _HOLIDAY_YEARS_AHEAD + 1):
                holidays.update(holiday_func(year))
        return ProjectWeek(region, frozenset(calendar["work_days"]), frozenset(holidays))

    async def _parse(
        self,
        week: ProjectWeek,
        data: bytes,
        filename: str,
        column_mapping: Mapping[Any, Any] | None,
        date_order: DateOrder | None,
    ) -> TabularPreview:
        return await asyncio.to_thread(
            preview,
            data,
            filename,
            column_mapping=column_mapping,
            date_order=date_order,
            work_weekdays=week.weekdays,
            holidays=week.holidays,
        )

    async def duplicates(
        self,
        project_id: uuid.UUID,
        sha256: str,
        *,
        exclude: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """Schedules of the project already imported from these exact bytes."""
        rows = (
            await self.session.execute(select(Schedule.id, Schedule.metadata_).where(Schedule.project_id == project_id))
        ).all()
        found: list[uuid.UUID] = []
        for schedule_id, metadata in rows:
            stamp = (metadata or {}).get("import") if isinstance(metadata, dict) else None
            if isinstance(stamp, dict) and stamp.get("sha256") == sha256 and schedule_id != exclude:
                found.append(schedule_id)
        return found

    # ── Preview ──────────────────────────────────────────────────────────

    async def preview(
        self,
        project_id: uuid.UUID,
        user_id: str,
        data: bytes,
        filename: str,
        *,
        column_mapping: Mapping[Any, Any] | None = None,
        date_order: DateOrder | None = None,
    ) -> tuple[TabularPreview, list[uuid.UUID]]:
        """Parse the upload against the project's week; writes nothing.

        Returns the preview and the ids of schedules already imported from the
        same bytes, so the dialog can warn before the commit refuses.
        """
        await verify_project_access(project_id, user_id, self.session)
        week = await self.project_week(project_id)
        result = await self._parse(week, data, filename, column_mapping, date_order)
        return result, await self.duplicates(project_id, result.sha256)

    # ── Commit ───────────────────────────────────────────────────────────

    async def commit(
        self,
        project_id: uuid.UUID,
        user_id: str,
        data: bytes,
        filename: str,
        *,
        expected_sha256: str,
        target: ImportTarget = "new",
        schedule_id: uuid.UUID | None = None,
        name: str | None = None,
        column_mapping: Mapping[Any, Any] | None = None,
        date_order: DateOrder | None = None,
        allow_duplicate: bool = False,
        client_visible_refs: Sequence[str] | None = None,
    ) -> CommitResult:
        """Re-read the file, check it is the previewed one, and write it.

        Client visibility is never taken from the sheet: the preview returns the
        rows it marks as ``client_visible_suggested``, and only the refs the
        person confirmed in ``client_visible_refs`` become visible to the
        client. Omitted or empty, every imported activity stays hidden.

        Raises:
            HTTPException: 404 for a project or schedule the caller cannot
                see; 409 when the bytes differ from the preview
                (``preview_mismatch``), when they were imported before
                (``duplicate_import``) or when the schedule to replace has
                history (``replace_*``); 422 when the file still has errors,
                an unconfirmed date order among them, or when a confirmed
                client-visible ref names no activity (``client_visible_unknown_ref``).
        """
        await verify_project_access(project_id, user_id, self.session)
        existing: Schedule | None = None
        if target == "replace":
            if schedule_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={"code": "schedule_id_required", "message": "Replacing needs the schedule to replace"},
                )
            existing = await self.session.get(Schedule, schedule_id)
            # The schedule must sit in the project the caller was checked
            # against; any other answer is the same 404 a missing id gets.
            if existing is None or existing.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
            await self._guard_replace(existing)

        week = await self.project_week(project_id)
        parsed_file = await self._parse(week, data, filename, column_mapping, date_order)
        if parsed_file.sha256 != expected_sha256.strip().lower():
            raise _conflict(
                "preview_mismatch",
                "The uploaded file is not the one that was previewed; preview it again",
                sha256=parsed_file.sha256,
            )
        if parsed_file.has_errors or parsed_file.document is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "import_has_errors",
                    "message": "The file has errors to fix before it can be imported",
                    "issues": [issue.to_dict() for issue in parsed_file.issues if issue.severity == "error"][:200],
                },
            )
        document = parsed_file.document
        visible = {str(ref) for ref in client_visible_refs or ()}
        unknown = sorted(visible - {a["ref"] for a in document["activities"]})
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "client_visible_unknown_ref",
                    "message": "Some activities confirmed as client-visible are not in the file",
                    "refs": unknown[:200],
                },
            )
        for activity in document["activities"]:
            activity["client_visible"] = activity["ref"] in visible
        if not allow_duplicate:
            earlier = await self.duplicates(project_id, parsed_file.sha256, exclude=schedule_id)
            if earlier:
                raise _conflict(
                    "duplicate_import",
                    "This file was already imported into the project",
                    schedule_ids=[str(found) for found in earlier],
                )

        rows_by_ref = {a["ref"]: a["metadata"].get("import_row") for a in document["activities"]}
        if existing is not None:
            ref_map, rel_count = await self.interchange.replace_schedule_contents(
                existing, parse_document(document), apply_client_visible=True
            )
            if name:
                existing.name = name[:255]
            new_id, new_name, replaced = existing.id, existing.name, True
        else:
            schedule, ref_map, rel_count, _actions, _stats = await self.interchange.import_schedule(
                project_id,
                document,
                user_id,
                clean=False,
                name_override=name[:255] if name else None,
                apply_client_visible=True,
            )
            new_id, new_name, replaced = schedule.id, schedule.name, False
        await self.session.flush()

        # CPM ends in expire_all(): nothing below may read an ORM attribute,
        # so every value the response needs was copied out above.
        from app.modules.schedule.service import ScheduleService

        cpm = await ScheduleService(self.session).calculate_critical_path(new_id)
        validation = await self._validate(document, rows_by_ref, new_id, project_id, week.region)
        return CommitResult(
            schedule_id=new_id,
            schedule_name=new_name,
            replaced=replaced,
            activity_count=len(ref_map),
            relationship_count=rel_count,
            critical_count=len(cpm.critical_path),
            project_duration=int(cpm.project_duration_days),
            validation=validation,
            warnings=[issue.to_dict() for issue in parsed_file.issues if issue.severity == "warning"],
        )

    async def _guard_replace(self, schedule: Schedule) -> None:
        """Refuse to overwrite a schedule whose contents something already relies on."""
        if (schedule.status or "draft") != "draft":
            raise _conflict(
                "replace_not_draft",
                "Only a draft schedule can be replaced",
                status=schedule.status,
            )
        sid = schedule.id

        async def _count(stmt: Any) -> int:
            return int((await self.session.execute(stmt)).scalar_one())

        if await _count(select(func.count()).select_from(ScheduleBaseline).where(ScheduleBaseline.schedule_id == sid)):
            raise _conflict("replace_has_baseline", "The schedule has a baseline; import into a new schedule")

        from app.modules.schedule.models import ProgressUpdate

        activity_ids = select(Activity.id).where(Activity.schedule_id == sid).scalar_subquery()
        progress_rows = await _count(
            select(func.count()).select_from(ProgressUpdate).where(ProgressUpdate.activity_id.in_(activity_ids))
        ) + await _count(
            select(func.count())
            .select_from(ScheduleProgressEntry)
            .where(ScheduleProgressEntry.task_id.in_(activity_ids))
        )
        progress_values = (
            await self.session.execute(select(Activity.progress_pct).where(Activity.schedule_id == sid))
        ).scalars()
        if progress_rows or any(_positive(value) for value in progress_values):
            raise _conflict("replace_has_progress", "Progress is recorded on the schedule; import into a new schedule")
        if await _count(select(func.count()).select_from(WorkOrder).where(WorkOrder.activity_id.in_(activity_ids))):
            raise _conflict("replace_has_work_orders", "Work orders hang off the schedule; import into a new schedule")

    async def _validate(
        self,
        document: dict[str, Any],
        rows_by_ref: dict[str, int | None],
        schedule_id: uuid.UUID,
        project_id: uuid.UUID,
        region: str | None,
    ) -> dict[str, Any]:
        """Run the ``schedule_quality`` pack on the imported network, findings keyed to sheet rows."""
        from app.core.validation.engine import validation_engine

        payload = {
            "activities": [{"id": a["ref"], **a} for a in document["activities"]],
            "relationships": [
                {
                    "predecessor_id": r["predecessor_ref"],
                    "successor_id": r["successor_ref"],
                    "relationship_type": r["relationship_type"],
                    "lag_days": r["lag_days"],
                }
                for r in document["relationships"]
            ],
            "project_region": region,
        }
        report = await validation_engine.validate(
            payload,
            ["schedule_quality"],
            target_type="schedule",
            target_id=str(schedule_id),
            project_id=str(project_id),
            region=region,
        )
        findings = [
            {
                "rule_id": result.rule_id,
                "severity": getattr(result.severity, "value", str(result.severity)),
                "message": result.message,
                "element_ref": result.element_ref,
                "row": rows_by_ref.get(result.element_ref or ""),
                "suggestion": result.suggestion,
            }
            for result in report.results
            if not result.passed
        ]
        return {
            "rule_sets": list(report.rule_sets_applied),
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "infos": len(report.infos),
            "findings": findings[:500],
        }


def _positive(value: Any) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


# ── Template ─────────────────────────────────────────────────────────────────


def template_language(lang: str | None) -> str:
    """The template language for a requested locale: ``"de-AT"`` -> ``"de"``, unknown -> ``"en"``."""
    base = (lang or "en").replace("_", "-").split("-")[0].strip().lower()
    return base if base in LANGUAGES else "en"


def template_rows(lang: str, *, today: date | None = None) -> list[list[Any]]:
    """Header row plus four sample rows in ``lang``, columns in :data:`FIELDS` order.

    The sample start date is next Monday and only the start and the duration
    are given, so the template reads back cleanly on any project's week.
    """
    today = today or date.today()
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    phase, excavation, foundations, accepted = TEMPLATE_EXAMPLE_NAMES[lang]
    yes, no = TEMPLATE_YES_NO[lang]
    samples = [
        {"id": "A10", "name": phase, "wbs": "1", "outline_level": 1},
        {
            "id": "A20",
            "name": excavation,
            "wbs": "1.1",
            "outline_level": 2,
            "start": start.isoformat(),
            "duration": 5,
            "percent_complete": 0,
            "milestone": no,
            "client_visible": no,
        },
        {
            "id": "A30",
            "name": foundations,
            "wbs": "1.2",
            "outline_level": 2,
            "duration": 10,
            "predecessors": "A20FS+2d",
            "percent_complete": 0,
            "milestone": no,
            "client_visible": no,
        },
        {
            "id": "A40",
            "name": accepted,
            "wbs": "1.3",
            "outline_level": 2,
            "duration": 0,
            "predecessors": "A30",
            "milestone": yes,
            "client_visible": yes,
        },
    ]
    return [list(TEMPLATE_HEADERS[lang]), *[[sample.get(f, "") for f in FIELDS] for sample in samples]]


def render_template(lang: str, file_format: Literal["csv", "xlsx"]) -> tuple[bytes, str, str]:
    """``(content, media_type, filename)`` of the import template."""
    rows = template_rows(lang)
    if file_format == "csv":
        out = io.StringIO()
        delimiter = ";" if lang in _SEMICOLON_LANGUAGES else ","
        csv.writer(out, delimiter=delimiter, lineterminator="\r\n").writerows(rows)
        return out.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"schedule_import_template_{lang}.csv"

    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.core.xlsx_text import store_strings_as_text

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Schedule"
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    store_strings_as_text(sheet)
    out_bytes = io.BytesIO()
    workbook.save(out_bytes)
    return (
        out_bytes.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        f"schedule_import_template_{lang}.xlsx",
    )


__all__ = [
    "CommitResult",
    "ProjectWeek",
    "ScheduleTabularImportService",
    "render_template",
    "template_language",
    "template_rows",
]
